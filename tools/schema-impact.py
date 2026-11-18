#!/usr/bin/env python3
"""Report the impact of normalized schema changes using local metadata."""

import importlib.util
import json
from pathlib import Path
import re
import sys


sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("sql_inventory", Path(__file__).with_name("sql-inventory.py"))
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)

SCHEMA_FILENAME = "SCHEMA-SNAPSHOT.json"
DEPENDENCIES_FILENAME = "QUERY-DEPENDENCIES.json"
MAX_COLUMNS = 4096
MAX_QUERY_COLUMNS = 128
MAX_WIDTH = 100_000
NAME = re.compile(r"[a-z][a-z0-9_]{0,62}")
TYPES = ("INTEGER", "BIGINT", "VARCHAR", "DECIMAL", "BOOLEAN", "DATE", "TIMESTAMP", "TEXT")
HEADER = {"schema_version", "revision", "scope"}
COLUMN_FIELDS = {"table", "column", "type", "width", "nullable"}
DEPENDENCY_FIELDS = {"framework", "query_id_hash", "columns"}
REFERENCE_FIELDS = {"table", "column"}


def path_parts(path, filename):
    parts = path.split("/")
    if len(path) > 255 or parts[-1] != filename or not all(
        inventory.PATH_PART.fullmatch(part) and not inventory.PRIVATE_NAME.search(part) for part in parts
    ):
        raise inventory.InvalidInventory()
    return parts


def read_document(parts, collection, maximum):
    document = json.loads(
        inventory.read_bytes(parts).decode("utf-8"), object_pairs_hook=inventory.unique_object,
        parse_constant=inventory.invalid_number, parse_float=inventory.invalid_number,
        parse_int=inventory.bounded_integer,
    )
    if not inventory.exact_fields(document, HEADER | {collection}) or not (
        type(document["schema_version"]) is int and document["schema_version"] == 1
        and inventory.matches(document["revision"], inventory.REVISION)
        and inventory.matches(document["scope"], inventory.HASH)
        and inventory.bounded_list(document[collection], maximum)
    ):
        raise inventory.InvalidInventory()
    return document


def column_key(row):
    return row["table"], row["column"]


def read_schema(parts):
    document = read_document(parts, "columns", MAX_COLUMNS)
    columns = {}
    for row in document["columns"]:
        if not inventory.exact_fields(row, COLUMN_FIELDS) or not (
            inventory.matches(row["table"], NAME) and inventory.matches(row["column"], NAME)
            and row["type"] in TYPES and type(row["nullable"]) is bool
            and type(row["width"]) is int and 0 <= row["width"] <= MAX_WIDTH
            and (row["type"] == "VARCHAR") == (row["width"] > 0)
        ):
            raise inventory.InvalidInventory()
        key = column_key(row)
        if key in columns:
            raise inventory.InvalidInventory()
        columns[key] = {"type": row["type"], "width": row["width"], "nullable": row["nullable"]}
    return {**document, "columns": columns}


def read_dependencies(parts):
    document = read_document(parts, "dependencies", inventory.MAX_ENTRIES)
    dependencies = {}
    for row in document["dependencies"]:
        if not inventory.exact_fields(row, DEPENDENCY_FIELDS) or not (
            row["framework"] in inventory.FRAMEWORKS and inventory.matches(row["query_id_hash"], inventory.HASH)
            and inventory.bounded_list(row["columns"], MAX_QUERY_COLUMNS)
        ):
            raise inventory.InvalidInventory()
        refs = set()
        for ref in row["columns"]:
            if not inventory.exact_fields(ref, REFERENCE_FIELDS) or not (
                inventory.matches(ref["table"], NAME)
                and (ref["column"] == "*" or inventory.matches(ref["column"], NAME))
            ):
                raise inventory.InvalidInventory()
            key = column_key(ref)
            if key in refs:
                raise inventory.InvalidInventory()
            refs.add(key)
        query = row["framework"], "SCOPED", row["query_id_hash"]
        if query in dependencies:
            raise inventory.InvalidInventory()
        dependencies[query] = refs
    return {**document, "dependencies": dependencies}


def compare_columns(base, head):
    changes = []
    for table, column in sorted(base.keys() | head.keys()):
        key = table, column
        before, after = base.get(key), head.get(key)
        if before is None:
            kinds = ["ADDED"]
        elif after is None:
            kinds = ["REMOVED"]
        else:
            kinds = [kind for field, kind in (("type", "TYPE"), ("width", "WIDTH"), ("nullable", "NULLABILITY"))
                     if before[field] != after[field]]
        changes.extend({"table": table, "column": column, "kind": kind, "before": before, "after": after}
                       for kind in kinds)
    return changes


def assess_queries(entries, dependencies, known_refs, changed_refs):
    affected, unresolved = [], []
    for key in sorted(entries.keys() | dependencies.keys()):
        framework, identity, query_id = key
        query = {"framework": framework, "query_id_hash": query_id}
        reasons = []
        entry = entries.get(key)
        if entry is None:
            reasons.append("UNKNOWN_QUERY")
        else:
            if entry["unavailable"]:
                reasons.append("UNAVAILABLE_OBSERVATIONS")
            refs = dependencies.get(key)
            if identity == "OBSERVE_ID":
                reasons.append("OBSERVE_ID")
            else:
                if not entry["test_ids"]:
                    reasons.append("MISSING_TESTS")
                if not refs:
                    reasons.append("MISSING_DEPENDENCIES")
                else:
                    if refs - known_refs:
                        reasons.append("UNKNOWN_REFERENCE")
                    if refs & changed_refs:
                        affected.append({**query, "test_ids": sorted(entry["test_ids"])})
        if reasons:
            unresolved.append({**query, "identity": identity, "reasons": sorted(reasons)})
    return affected, unresolved


def build_report(base, head, snapshot, manifest):
    if base["revision"] == head["revision"] or not (
        base["scope"] == head["scope"] == manifest["scope"] == snapshot["profile"]
        and head["revision"] == snapshot["revision"] == manifest["revision"]
    ):
        raise inventory.InvalidInventory()

    changes = compare_columns(base["columns"], head["columns"])
    known_columns = base["columns"].keys() | head["columns"].keys()
    known_refs = known_columns | {(table, "*") for table, _ in known_columns}
    changed_columns = {column_key(change) for change in changes}
    changed_refs = changed_columns | {(table, "*") for table, _ in changed_columns}
    affected, unresolved = assess_queries(snapshot["entries"], manifest["dependencies"], known_refs, changed_refs)
    coverage_reasons = []
    if snapshot["dropped"]:
        coverage_reasons.append("DROPPED_OBSERVATIONS")
    if changes and not snapshot["entries"]:
        coverage_reasons.append("EMPTY_INVENTORY")
    return {
        "schema_version": 1,
        "status": "INCOMPLETE" if coverage_reasons or unresolved else "COMPLETE",
        "coverage_reasons": coverage_reasons,
        "base_revision": base["revision"],
        "head_revision": head["revision"],
        "scope": head["scope"],
        "changes": changes,
        "affected_queries": affected,
        "unresolved_queries": unresolved,
        "inventory_dropped": snapshot["dropped"],
        "impacted_test_ids": sorted({test for query in affected for test in query["test_ids"]}),
    }


def main(argv=None):
    parser = inventory.ArgumentParser(prog="schema-impact.py", description=__doc__, allow_abbrev=False)
    parser.add_argument("--base", required=True, metavar=SCHEMA_FILENAME)
    parser.add_argument("--head", required=True, metavar=SCHEMA_FILENAME)
    parser.add_argument("--inventory", required=True, metavar=inventory.FILENAME)
    parser.add_argument("--dependencies", required=True, metavar=DEPENDENCIES_FILENAME)
    try:
        args = parser.parse_args(argv)
        base = path_parts(args.base, SCHEMA_FILENAME)
        head = path_parts(args.head, SCHEMA_FILENAME)
        snapshot = inventory.path_parts(args.inventory)
        manifest = path_parts(args.dependencies, DEPENDENCIES_FILENAME)
        report = build_report(read_schema(base), read_schema(head), inventory.read_snapshot(snapshot),
                              read_dependencies(manifest))
    except (OSError, ValueError, RecursionError, NotImplementedError):
        print("ERROR: invalid schema impact input or arguments", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if report["status"] == "INCOMPLETE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
