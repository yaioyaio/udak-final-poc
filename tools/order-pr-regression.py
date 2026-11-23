#!/usr/bin/env python3
"""Map a local SQL inventory PR report to registered order regression tests."""

import hashlib
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace


inventory = SimpleNamespace(**runpy.run_path(str(Path(__file__).with_name("sql-inventory.py"))))
InvalidInventory = inventory.InvalidInventory
FILENAME = "SQL-INVENTORY-REPORT.json"
MAX_QUERIES = 2 * inventory.MAX_ENTRIES
MAX_QUERY_IMPACT = 2 * inventory.MAX_REFERENCES
MAX_IMPACT = MAX_QUERIES * inventory.MAX_REFERENCES
REPORT_FIELDS = {"schema_version", "status", "profile", "base", "head", "changes_detected",
                 "queries", "impacted_test_ids"}
REGISTRY = {
    hashlib.sha256(b"udak-inventory-test-id-v1\0" + test_id).hexdigest(): entry_point
    for test_id, entry_point in (
        (b"case.order.place", "ORDER_PLACEMENT_RELATED"),
        (b"case.order.stock-on", "ORDER_STOCK_ON_RELATED"),
    )
}


def report_path(path):
    parts = path.split("/")
    if len(path) > 255 or parts[-1] != FILENAME or not all(
        inventory.PATH_PART.fullmatch(part) and not inventory.PRIVATE_NAME.search(part)
        for part in parts
    ):
        raise InvalidInventory()
    return parts


def report_integer(value):
    # Report totals can sum up to MAX_ENTRIES snapshot counts.
    if len(value) > len(str(inventory.MAX_ENTRIES * inventory.MAX_COUNT)):
        raise InvalidInventory()
    return int(value)


def test_hashes(value, maximum):
    if not (inventory.bounded_list(value, maximum)
            and all(inventory.matches(test_id, inventory.HASH) for test_id in value)
            and len(set(value)) == len(value)):
        raise InvalidInventory()
    return set(value)


def query_entry(value, key):
    if value is None:
        return None
    if not isinstance(value, dict) or value.keys() & key.keys():
        raise InvalidInventory()
    entry = {**value, **key}
    inventory.validate_entry(entry, 1)
    return entry


def fingerprint_impact(rows, base, head):
    if not inventory.bounded_list(rows, MAX_QUERY_IMPACT) or not rows:
        raise InvalidInventory()
    base_shapes = set(map(inventory.shape_key, (base or {}).get("shapes", [])))
    head_shapes = set(map(inventory.shape_key, (head or {}).get("shapes", [])))
    base_tests = set((base or {}).get("test_ids", []))
    head_tests = set((head or {}).get("test_ids", []))
    fields = {"fingerprint_hash", "statement_kind", "gained_test_ids", "lost_test_ids"}
    seen, impacted = set(), set()
    for row in rows:
        if not (inventory.exact_fields(row, fields)
                and inventory.matches(row["fingerprint_hash"], inventory.HASH)
                and row["statement_kind"] in inventory.STATEMENT_KINDS):
            raise InvalidInventory()
        shape = inventory.shape_key(row)
        gained = test_hashes(row["gained_test_ids"], inventory.MAX_REFERENCES)
        lost = test_hashes(row["lost_test_ids"], inventory.MAX_REFERENCES)
        if (shape in seen or not (gained or lost) or gained & lost
                or (gained and (shape not in head_shapes or not gained <= head_tests))
                or (lost and (shape not in base_shapes or not lost <= base_tests))):
            raise InvalidInventory()
        seen.add(shape)
        impacted.update(gained | lost)
    return impacted


def query_impact(query, fingerprint_status):
    if not isinstance(query, dict) or not (
        query.get("framework") in inventory.FRAMEWORKS and query.get("identity") in inventory.IDENTITIES
        and inventory.matches(query.get("query_id_hash"), inventory.HASH)
    ):
        raise InvalidInventory()
    key_fields = {field: query[field] for field in ("framework", "identity", "query_id_hash")}
    key = inventory.entry_key(key_fields)
    base = query_entry(query.get("base"), key_fields)
    head = query_entry(query.get("head"), key_fields)
    if base is None and head is None:
        raise InvalidInventory()
    expected = inventory.compare_query(key, base, head, compare_links=False)
    if "fingerprint_test_changes" in query:
        if fingerprint_status != "COMPARABLE" or key[1] != "SCOPED":
            raise InvalidInventory()
        affected = fingerprint_impact(query["fingerprint_test_changes"], base, head)
        if not expected["changes"]:
            expected["impacted_test_ids"] = sorted(affected)
        expected["changes"].append("FINGERPRINT_TEST_LINKS_CHANGED")
        expected["fingerprint_test_changes"] = query["fingerprint_test_changes"]
    impacted = test_hashes(query.get("impacted_test_ids"), MAX_QUERY_IMPACT)
    if {**query, "impacted_test_ids": sorted(impacted)} != expected:
        raise InvalidInventory()
    return key, base, head, impacted


def check_side(side, entries):
    if not (isinstance(side, dict) and inventory.matches(side.get("revision"), inventory.REVISION)
            and inventory.valid_count(side.get("dropped")) and len(entries) <= inventory.MAX_ENTRIES):
        raise InvalidInventory()
    expected = inventory.observation_stats({**side, "entries": entries})
    if (side != expected
            or any(type(side[field]) is not int for field, value in expected.items() if type(value) is int)
            or any(type(count) is not int for count in side.get("unavailable_reasons", {}).values())):
        raise InvalidInventory()
    return bool(expected["dropped"] or expected["unavailable"])


def read_report(path):
    report = json.loads(
        inventory.read_bytes(report_path(path)).decode("utf-8"),
        object_pairs_hook=inventory.unique_object, parse_constant=inventory.invalid_number,
        parse_float=inventory.invalid_number, parse_int=report_integer,
    )
    if not (isinstance(report, dict)
            and report.keys() - {"fingerprint_test_status", "shared_shape_changes"} == REPORT_FIELDS
            and type(report["schema_version"]) is int and report["schema_version"] == 1
            and inventory.matches(report["profile"], inventory.HASH)
            and inventory.bounded_list(report["queries"], MAX_QUERIES)):
        raise InvalidInventory()
    fingerprint_status = report.get("fingerprint_test_status")
    if "fingerprint_test_status" in report and fingerprint_status not in (
        "COMPARABLE", "INCOMPLETE", "MIXED_VERSIONS"
    ):
        raise InvalidInventory()

    seen, impacted, base, head = set(), set(), {}, {}
    for query in report["queries"]:
        key, before, after, tests = query_impact(query, fingerprint_status)
        if key in seen:
            raise InvalidInventory()
        seen.add(key)
        if before is not None:
            base[key] = before
        if after is not None:
            head[key] = after
        impacted.update(tests)

    base_incomplete = check_side(report["base"], base)
    head_incomplete = check_side(report["head"], head)
    incomplete = base_incomplete or head_incomplete
    detected = any(query["changes"] for query in report["queries"])
    dropped = report["base"]["dropped"] or report["head"]["dropped"]
    shared_shapes = [] if dropped else inventory.shared_shape_changes(report["queries"])
    if (report["status"] != ("INCOMPLETE" if incomplete else "COMPLETE")
            or report["changes_detected"] is not (True if detected else None if incomplete else False)
            or (fingerprint_status == "COMPARABLE" and incomplete)
            or (fingerprint_status == "INCOMPLETE" and not incomplete)
            or report.get("shared_shape_changes", []) != shared_shapes
            or test_hashes(report["impacted_test_ids"], MAX_IMPACT) != impacted):
        raise InvalidInventory()
    return report, impacted


def regression_plan(report, impacted):
    matched = [{"test_id_hash": test_id, "entry_point": REGISTRY[test_id]}
               for test_id in sorted(impacted & REGISTRY.keys())]
    unknown = sorted(impacted - REGISTRY.keys())
    reasons = []
    if report["status"] == "INCOMPLETE":
        reasons.append("INCOMPLETE_REPORT")
    if report.get("fingerprint_test_status") == "MIXED_VERSIONS":
        reasons.append("MIXED_INVENTORY_VERSIONS")
    if unknown:
        reasons.append("UNKNOWN_TEST_HASH")
    status = "REVIEW_REQUIRED" if reasons else "READY" if matched else "NO_IMPACT"
    return {"schema_version": 1, "status": status, "matched_tests": matched,
            "unknown_test_ids": unknown, "review_reasons": reasons}


def main(argv=None):
    parser = inventory.ArgumentParser(prog="order-pr-regression.py", description=__doc__, allow_abbrev=False)
    parser.add_argument("--report", required=True, metavar=FILENAME)
    try:
        args = parser.parse_args(argv)
        report, impacted = read_report(args.report)
    except (OSError, ValueError, RecursionError, NotImplementedError):
        print("ERROR: invalid order PR regression input or arguments", file=sys.stderr)
        return 1
    plan = regression_plan(report, impacted)
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 2 if plan["status"] == "REVIEW_REQUIRED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
