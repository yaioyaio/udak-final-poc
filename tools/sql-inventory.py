#!/usr/bin/env python3
"""Compare two local UDAK SQL inventory snapshots using metadata only."""

import argparse
from collections import Counter
from contextlib import contextmanager
import json
import os
import re
import stat
import sys


FILENAME = "SQL-INVENTORY.json"
MAX_BYTES = 1024 * 1024
MAX_COUNT = 2**31 - 1
MAX_ENTRIES = 128
MAX_REFERENCES = 8
HASH = re.compile(r"[0-9a-f]{64}")
REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
PATH_PART = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
PRIVATE_NAME = re.compile(
    r"(?:^|[._-])(?:env|private|secrets?|credentials?|passwords?|tokens?|accounts?|"
    r"connections?|id_rsa|id_ed25519|authorized_keys|api[_-]?keys?)(?:[._-]|$)"
    r"|\.(?:key|pem|p12|pfx|jks|keystore)(?:\.|$)|\.deploy\..*env(?:[._-]|$)",
    re.IGNORECASE,
)
FRAMEWORKS = ("JPA", "MYBATIS", "JDBC")
IDENTITIES = ("SCOPED", "OBSERVE_ID")
STATEMENT_KINDS = ("SELECT", "INSERT", "UPDATE", "DELETE", "MERGE", "CALL", "DDL", "OTHER", "UNKNOWN")
SNAPSHOT_FIELDS = {"schema_version", "revision", "profile", "dropped", "entries"}
ENTRY_FIELDS = {"framework", "identity", "query_id_hash", "declared", "observed", "unavailable", "test_ids", "shapes"}
UNAVAILABLE_REASONS = {
    "UNSPECIFIED", "EMPTY_SQL", "SQL_TOO_LONG", "MULTIPLE_STATEMENTS",
    "AMBIGUOUS_SYNTAX", "UNSUPPORTED_SYNTAX", "MALFORMED_SYNTAX", "LEXER_LIMIT",
}
SHAPE_FIELDS = {"fingerprint_hash", "statement_kind"}
SNAPSHOT_SHAPE_FIELDS = {1: SHAPE_FIELDS, 2: SHAPE_FIELDS | {"test_ids"}}


class InvalidInventory(ValueError):
    """An input or option was rejected without disclosing its contents."""


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise InvalidInventory()


def path_parts(path):
    parts = path.split("/")
    if len(path) > 255 or parts[-1] != FILENAME or not all(
        PATH_PART.fullmatch(part) and not PRIVATE_NAME.search(part) for part in parts
    ):
        raise InvalidInventory()
    return parts


@contextmanager
def directory(parts):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(".", flags)
    try:
        for part in parts:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def file_identity(info):
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
        info.st_mtime_ns, info.st_ctime_ns,
    )


def read_bytes(parts):
    if os.name != "posix":
        raise InvalidInventory()
    with directory(parts[:-1]) as parent:
        before = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_BYTES:
            raise InvalidInventory()
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        expected = file_identity(before)
        fd = os.open(parts[-1], flags, dir_fd=parent)
        try:
            if file_identity(os.fstat(fd)) != expected:
                raise InvalidInventory()
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(before.st_size + 1)
            if len(raw) != before.st_size or file_identity(os.fstat(fd)) != expected:
                raise InvalidInventory()
        finally:
            os.close(fd)
    return raw


def unique_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise InvalidInventory()
    return result


def invalid_number(_value):
    raise InvalidInventory()


def bounded_integer(value):
    if len(value) > 10:
        raise InvalidInventory()
    return int(value)


def exact_fields(value, fields):
    return isinstance(value, dict) and value.keys() == fields


def matches(value, pattern):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def valid_count(value):
    return type(value) is int and 0 <= value <= MAX_COUNT


def bounded_list(value, maximum):
    return isinstance(value, list) and len(value) <= maximum


def valid_test_ids(value):
    return (bounded_list(value, MAX_REFERENCES) and all(matches(test, HASH) for test in value)
            and len(set(value)) == len(value))


def entry_key(entry):
    return entry["framework"], entry["identity"], entry["query_id_hash"]


def shape_key(shape):
    return shape["fingerprint_hash"], shape["statement_kind"]


def validate_entry(entry, schema_version):
    if not isinstance(entry, dict) or entry.keys() - {"unavailable_reasons"} != ENTRY_FIELDS or not (
        entry["framework"] in FRAMEWORKS and entry["identity"] in IDENTITIES
        and matches(entry["query_id_hash"], HASH) and type(entry["declared"]) is bool
        and valid_count(entry["observed"]) and valid_count(entry["unavailable"])
        and entry["unavailable"] <= entry["observed"]
        and valid_test_ids(entry["test_ids"])
        and bounded_list(entry["shapes"], MAX_REFERENCES)
    ):
        raise InvalidInventory()
    if "unavailable_reasons" in entry:
        reasons = entry["unavailable_reasons"]
        if not (isinstance(reasons, dict) and reasons and reasons.keys() <= UNAVAILABLE_REASONS
                and all(valid_count(count) and count > 0 for count in reasons.values())
                and sum(reasons.values()) == entry["unavailable"]):
            raise InvalidInventory()
    tests, shapes = entry["test_ids"], entry["shapes"]
    if not entry["declared"] and (entry["observed"] == 0 or len(tests) > entry["observed"]):
        raise InvalidInventory()
    if entry["identity"] == "OBSERVE_ID" and (entry["declared"] or tests):
        raise InvalidInventory()
    if not all(
        exact_fields(shape, SNAPSHOT_SHAPE_FIELDS[schema_version]) and matches(shape["fingerprint_hash"], HASH)
        and shape["statement_kind"] in STATEMENT_KINDS for shape in shapes
    ) or len({shape["fingerprint_hash"] for shape in shapes}) != len(shapes):
        raise InvalidInventory()
    available = entry["observed"] - entry["unavailable"]
    if len(shapes) > available or (available > 0 and not shapes):
        raise InvalidInventory()
    if schema_version == 2:
        aggregate_tests = set(tests)
        minimum_observations = 0
        for shape in shapes:
            shape_tests = shape["test_ids"]
            if not valid_test_ids(shape_tests) or not aggregate_tests.issuperset(shape_tests):
                raise InvalidInventory()
            minimum_observations += max(1, len(shape_tests))
        if minimum_observations > available:
            raise InvalidInventory()


def read_snapshot(parts):
    snapshot = json.loads(
        read_bytes(parts).decode("utf-8"), object_pairs_hook=unique_object,
        parse_constant=invalid_number, parse_float=invalid_number, parse_int=bounded_integer,
    )
    if not exact_fields(snapshot, SNAPSHOT_FIELDS) or not (
        type(snapshot["schema_version"]) is int and snapshot["schema_version"] in SNAPSHOT_SHAPE_FIELDS
        and matches(snapshot["revision"], REVISION) and matches(snapshot["profile"], HASH)
        and valid_count(snapshot["dropped"]) and bounded_list(snapshot["entries"], MAX_ENTRIES)
    ):
        raise InvalidInventory()
    entries = {}
    for entry in snapshot["entries"]:
        validate_entry(entry, snapshot["schema_version"])
        key = entry_key(entry)
        if key in entries:
            raise InvalidInventory()
        entries[key] = entry
    return {**snapshot, "entries": entries}


def unavailable_reasons(entry):
    if "unavailable_reasons" in entry:
        return entry["unavailable_reasons"]
    return {"UNSPECIFIED": entry["unavailable"]} if entry["unavailable"] else {}


def observation_stats(snapshot):
    entries = snapshot["entries"].values()
    reasons = Counter()
    for entry in entries:
        reasons.update(unavailable_reasons(entry))
    return {
        "revision": snapshot["revision"],
        "entries": len(entries),
        "declared_queries": sum(entry["declared"] for entry in entries),
        "observed_queries": sum(entry["observed"] > 0 for entry in entries),
        "static_only_queries": sum(entry["declared"] and entry["observed"] == 0 for entry in entries),
        "observations": sum(entry["observed"] for entry in entries),
        "unavailable": sum(entry["unavailable"] for entry in entries),
        **({"unavailable_reasons": dict(sorted(reasons.items()))} if reasons else {}),
        "dropped": snapshot["dropped"],
    }


def summarize_entry(entry):
    if entry is None:
        return None
    reasons = unavailable_reasons(entry)
    shapes = [{"fingerprint_hash": fingerprint, "statement_kind": kind}
              for fingerprint, kind in sorted(map(shape_key, entry["shapes"]))]
    return {
        "declared": entry["declared"], "observed": entry["observed"], "unavailable": entry["unavailable"],
        **({"unavailable_reasons": reasons} if reasons else {}),
        "test_ids": sorted(entry["test_ids"]), "shapes": shapes,
    }


def compare_query(key, before, after):
    base = summarize_entry(before)
    head = summarize_entry(after)
    before, after = base or {}, head or {}
    was_observed, is_observed = before.get("observed", 0) > 0, after.get("observed", 0) > 0
    was_declared, is_declared = before.get("declared", False), after.get("declared", False)
    was_static, is_static = was_declared and not was_observed, is_declared and not is_observed
    previous_tests, current_tests = set(before.get("test_ids", [])), set(after.get("test_ids", []))
    previous_shapes = {shape_key(shape): shape for shape in before.get("shapes", [])}
    current_shapes = {shape_key(shape): shape for shape in after.get("shapes", [])}
    added = [current_shapes[shape] for shape in sorted(current_shapes.keys() - previous_shapes.keys())]
    absent = [previous_shapes[shape] for shape in sorted(previous_shapes.keys() - current_shapes.keys())]
    gained_tests = sorted(current_tests - previous_tests)
    lost_tests = sorted(previous_tests - current_tests)
    changes = [label for label, changed in (
        ("NEWLY_OBSERVED", is_observed and not was_observed),
        ("NO_LONGER_OBSERVED", was_observed and not is_observed),
        ("STATIC_ONLY_ADDED", is_static and not was_declared),
        ("STATIC_ONLY_MISSING", was_static and not is_declared),
        ("DECLARATION_GAINED", is_declared and not was_declared),
        ("DECLARATION_LOST", was_declared and not is_declared),
        ("TEST_REFS_GAINED", gained_tests), ("TEST_REFS_LOST", lost_tests),
        ("OBSERVED_SHAPES_ADDED", added), ("OBSERVED_SHAPES_ABSENT", absent),
    ) if changed]
    if before.get("unavailable", 0) or after.get("unavailable", 0):
        shape_status = "UNAVAILABLE"
    elif added or absent:
        shape_status = "DIFFERENT"
    elif previous_shapes:
        shape_status = "UNCHANGED"
    else:
        shape_status = "UNOBSERVED"
    return {
        "framework": key[0], "identity": key[1], "query_id_hash": key[2],
        "base": base, "head": head, "changes": changes, "shape_status": shape_status,
        "added_observed_shapes": added, "absent_observed_shapes": absent,
        "gained_test_ids": gained_tests, "lost_test_ids": lost_tests,
        "impacted_test_ids": sorted(previous_tests | current_tests) if changes else [],
    }


def shared_shape_changes(queries):
    points = {"JDBC": "JDBC_EXECUTE", "MYBATIS": "MYBATIS_PREPARE"}
    eligible = {
        (query["query_id_hash"], query["framework"]): query for query in queries
        if query["identity"] == "SCOPED" and query["framework"] in points
        and query["shape_status"] == "DIFFERENT"
        and len(query["absent_observed_shapes"]) == len(query["added_observed_shapes"]) == 1
    }
    groups = []
    for (query_id, framework), jdbc in sorted(eligible.items()):
        if framework != "JDBC" or (mybatis := eligible.get((query_id, "MYBATIS"))) is None:
            continue
        before, = jdbc["absent_observed_shapes"]
        after, = jdbc["added_observed_shapes"]
        if (before["statement_kind"] != after["statement_kind"]
                or mybatis["absent_observed_shapes"] != [before] or mybatis["added_observed_shapes"] != [after]):
            continue
        shared_tests = set(jdbc["base"]["test_ids"]).intersection(
            jdbc["head"]["test_ids"], mybatis["base"]["test_ids"], mybatis["head"]["test_ids"],
        )
        if shared_tests:
            groups.append({
                "query_id_hash": query_id, "base_shape": before, "head_shape": after,
                "observations": [{"framework": framework, "point": point} for framework, point in points.items()],
                "shared_test_ids": sorted(shared_tests),
            })
    return groups


def compare_snapshots(base, head):
    if base["profile"] != head["profile"]:
        raise InvalidInventory()
    base_stats, head_stats = observation_stats(base), observation_stats(head)
    base_entries, head_entries = base["entries"], head["entries"]
    queries = [compare_query(key, base_entries.get(key), head_entries.get(key))
               for key in sorted(base_entries.keys() | head_entries.keys())]
    incomplete = any(side["dropped"] or side["unavailable"] for side in (base_stats, head_stats))
    detected = any(query["changes"] for query in queries)
    shared = shared_shape_changes(queries) if not (base_stats["dropped"] or head_stats["dropped"]) else []
    return {
        "schema_version": 1,
        "status": "INCOMPLETE" if incomplete else "COMPLETE",
        "profile": base["profile"],
        "base": base_stats, "head": head_stats,
        "changes_detected": True if detected else (None if incomplete else False),
        "queries": queries,
        **({"shared_shape_changes": shared} if shared else {}),
        "impacted_test_ids": sorted({test for query in queries for test in query["impacted_test_ids"]}),
    }


def query_details(query, *, include_shapes=True):
    lines = [
        "- Changes " + (", ".join(f"`{label}`" for label in query["changes"]) or "none detected"),
        f"- Shape status `{query['shape_status']}`",
    ]
    for label, side in (("Base", query["base"]), ("Head", query["head"])):
        if side is None:
            lines.append(f"- {label} has no inventory entry")
        else:
            lines.append(f"- {label} observed {side['observed']} times, {side['unavailable']} unavailable")
            for reason, count in sorted(side.get("unavailable_reasons", {}).items()):
                lines.append(f"  - `{reason}` {count}")
    if include_shapes:
        for label, shapes in (("Added observed shapes", query["added_observed_shapes"]),
                              ("Absent observed shapes", query["absent_observed_shapes"])):
            if shapes:
                lines.append(f"- {label} " + ", ".join(
                    f"`{shape['statement_kind']}` `{shape['fingerprint_hash']}`" for shape in shapes
                ))
    for label, tests in (("Gained test references", query["gained_test_ids"]),
                         ("Lost test references", query["lost_test_ids"])):
        if tests:
            lines.append(f"- {label} " + ", ".join(f"`{test}`" for test in tests))
    return lines


def format_markdown(report):
    base, head = report["base"], report["head"]
    queries = report["queries"]
    lines = [
        "# UDAK SQL inventory report", "",
        f"Status **{report['status']}** | Profile `{report['profile']}`", "",
        "| Observation statistic | Base | Head |", "| --- | --- | --- |",
        f"| Revision | `{base['revision']}` | `{head['revision']}` |",
    ]
    for key, label in (
        ("entries", "Queries"), ("declared_queries", "Declared queries"),
        ("observed_queries", "Observed queries"), ("static_only_queries", "Static-only queries"),
        ("observations", "Observations"), ("unavailable", "Unavailable observations"),
        ("dropped", "Dropped records"),
    ):
        lines.append(f"| {label} | {base[key]} | {head[key]} |")
    base_reasons, head_reasons = (side.get("unavailable_reasons", {}) for side in (base, head))
    for reason in sorted(base_reasons.keys() | head_reasons.keys()):
        lines.append(f"| `{reason}` | {base_reasons.get(reason, 0)} | {head_reasons.get(reason, 0)} |")
    if report["status"] == "INCOMPLETE":
        lines += ["", "Unavailable observations or dropped records limit this comparison."]
    shared = report.get("shared_shape_changes", [])
    changed = sum(bool(query["changes"]) for query in queries)
    change_summary = (f"Review candidates **{changed - len(shared)}** | Changed observation entries **{changed}**"
                      if shared else f"Queries with detected changes **{changed}**")
    lines += [
        "", "Shape differences describe the supplied observations. SQL removal and semantic equivalence require separate evidence.",
        "`OBSERVE_ID` identifies a fallback observation bucket. `SCOPED` identifies a registered query scope.", "",
        change_summary + f" | Queries with matching recorded shapes **{sum(query['shape_status'] == 'UNCHANGED' for query in queries)}**",
    ]
    by_key = {entry_key(query): query for query in queries}
    grouped_keys = set()
    for group in shared:
        query_id = group["query_id_hash"]
        lines += ["", f"### Shared SQL shape change `SCOPED` `{query_id}`", ""]
        for label, shape in (("Base shape", group["base_shape"]), ("Head shape", group["head_shape"])):
            lines.append(f"- {label} `{shape['statement_kind']}` `{shape['fingerprint_hash']}`")
        lines.append("- Shared test references " + ", ".join(f"`{test}`" for test in group["shared_test_ids"]))
        for observation in group["observations"]:
            key = observation["framework"], "SCOPED", query_id
            grouped_keys.add(key)
            lines += ["", f"#### {observation['point']}", "", *query_details(by_key[key], include_shapes=False)]
    for query in queries:
        if entry_key(query) not in grouped_keys and (query["changes"] or query["shape_status"] == "UNAVAILABLE"):
            lines += [
                "", f"### {query['framework']} `{query['identity']}` `{query['query_id_hash']}`", "",
                *query_details(query),
            ]
    lines += ["", "## Impacted test references", ""]
    lines += [f"- `{test}`" for test in report["impacted_test_ids"]] or ["None recorded for the reported changes."]
    return "\n".join(lines)


def main(argv=None):
    parser = ArgumentParser(prog="sql-inventory.py", description=__doc__, allow_abbrev=False)
    parser.add_argument("--base", required=True, metavar=FILENAME)
    parser.add_argument("--head", required=True, metavar=FILENAME)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--fail-on-change", action="store_true")
    try:
        args = parser.parse_args(argv)
        base_parts, head_parts = path_parts(args.base), path_parts(args.head)
        report = compare_snapshots(read_snapshot(base_parts), read_snapshot(head_parts))
    except (OSError, ValueError, RecursionError, NotImplementedError):
        print("ERROR: invalid SQL inventory input or arguments", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True) if args.format == "json" else format_markdown(report))
    if report["status"] == "INCOMPLETE":
        return 2
    if args.fail_on_change and report["changes_detected"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
