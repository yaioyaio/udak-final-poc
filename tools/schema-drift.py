#!/usr/bin/env python3
"""Compare the column contract of two local snapshots for one DBMS and table scope."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys


sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("schema_impact", Path(__file__).with_name("schema-impact.py"))
schema = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schema)
inventory = schema.inventory

SUPPORTED_DBMS = ("H2", "POSTGRESQL", "MYSQL")
MAX_TABLES = 128


def load_contract(path, scope, selected):
    snapshot = schema.read_schema(schema.path_parts(path, schema.SCHEMA_FILENAME))
    if snapshot["scope"] != scope or {table for table, _ in snapshot["columns"]} != selected:
        raise inventory.InvalidInventory()
    return snapshot


def main(argv=None):
    parser = inventory.ArgumentParser(prog="schema-drift.py", description=__doc__, allow_abbrev=False)
    parser.add_argument("--baseline", required=True, metavar=schema.SCHEMA_FILENAME)
    parser.add_argument("--current", required=True, metavar=schema.SCHEMA_FILENAME)
    parser.add_argument("--dbms", choices=SUPPORTED_DBMS, required=True)
    parser.add_argument("--table", action="append", required=True, metavar="LOGICAL_TABLE")
    try:
        args = parser.parse_args(argv)
        selected = set(args.table)
        if len(args.table) != len(selected) or len(selected) > MAX_TABLES or not all(
            schema.NAME.fullmatch(table) for table in selected
        ):
            raise inventory.InvalidInventory()
        scope_input = "\n".join(("udak-schema-contract-v1", args.dbms, *sorted(selected), ""))
        scope = hashlib.sha256(scope_input.encode("ascii")).hexdigest()
        baseline = load_contract(args.baseline, scope, selected)
        current = load_contract(args.current, scope, selected)
        changes = schema.compare_columns(baseline["columns"], current["columns"])
    except (OSError, ValueError, RecursionError, NotImplementedError):
        print("ERROR: invalid schema drift input or scope", file=sys.stderr)
        return 1
    report = {
        "schema_version": 1,
        "status": "DRIFT" if changes else "MATCH",
        "dbms": args.dbms,
        "scope": scope,
        "baseline_revision": baseline["revision"],
        "current_revision": current["revision"],
        "changes": changes,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if changes else 0


if __name__ == "__main__":
    raise SystemExit(main())
