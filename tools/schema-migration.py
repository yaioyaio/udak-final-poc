#!/usr/bin/env python3
"""Compare a reviewed migration with applied history and normalized schema changes."""

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys


sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("schema_impact", Path(__file__).with_name("schema-impact.py"))
schema = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schema)
inventory = schema.inventory

HISTORY_FILENAME = "MIGRATION-HISTORY.json"
MANIFEST_FILENAME = "MIGRATION-MANIFEST.json"
VERSION = re.compile(r"[1-9][0-9]{0,8}(?:\.[0-9]{1,6}){0,3}")
RECORD_FIELDS = {"version", "checksum_sha256"}
MANIFEST_FIELDS = schema.HEADER | RECORD_FIELDS | {"base_revision", "expected_changes_sha256"}
MAX_MIGRATIONS = 128


def valid_record(record):
    return (inventory.matches(record["version"], VERSION)
            and inventory.matches(record["checksum_sha256"], inventory.HASH))


def read_history(path):
    history = schema.read_document(schema.path_parts(path, HISTORY_FILENAME), "migrations", MAX_MIGRATIONS)
    records = history["migrations"]
    if not all(inventory.exact_fields(row, RECORD_FIELDS) and valid_record(row) for row in records):
        raise inventory.InvalidInventory()
    if len({row["version"] for row in records}) != len(records):
        raise inventory.InvalidInventory()
    return history


def read_manifest(path):
    parts = schema.path_parts(path, MANIFEST_FILENAME)
    manifest = json.loads(
        inventory.read_bytes(parts).decode("utf-8"), object_pairs_hook=inventory.unique_object,
        parse_constant=inventory.invalid_number, parse_float=inventory.invalid_number,
        parse_int=inventory.bounded_integer,
    )
    if not inventory.exact_fields(manifest, MANIFEST_FIELDS) or not (
        type(manifest["schema_version"]) is int and manifest["schema_version"] == 1
        and inventory.matches(manifest["revision"], inventory.REVISION)
        and inventory.matches(manifest["base_revision"], inventory.REVISION)
        and inventory.matches(manifest["scope"], inventory.HASH)
        and inventory.matches(manifest["expected_changes_sha256"], inventory.HASH)
        and valid_record(manifest)
    ):
        raise inventory.InvalidInventory()
    return manifest


def changes_digest(changes):
    canonical = json.dumps(changes, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def compare_history(before, after, expected):
    if after[:len(before)] != before:
        return [], ["HISTORY_DIVERGED"]
    applied = after[len(before):]
    if not applied:
        return applied, ["HISTORY_MISSING"]
    if len(applied) != 1:
        return applied, ["MULTIPLE_MIGRATIONS"]
    actual, = applied
    reasons = [reason for field, reason in (("version", "VERSION_MISMATCH"), ("checksum_sha256", "CHECKSUM_MISMATCH"))
               if actual[field] != expected[field]]
    return applied, reasons


def build_report(base, head, base_history, head_history, manifest):
    if base["revision"] == head["revision"] or not (
        base["revision"] == base_history["revision"] == manifest["base_revision"]
        and head["revision"] == head_history["revision"] == manifest["revision"]
        and base["scope"] == head["scope"] == base_history["scope"] == head_history["scope"] == manifest["scope"]
    ):
        raise inventory.InvalidInventory()

    observed = schema.compare_columns(base["columns"], head["columns"])
    digest = changes_digest(observed)
    expected = {"version": manifest["version"], "checksum_sha256": manifest["checksum_sha256"]}
    applied, reasons = compare_history(base_history["migrations"], head_history["migrations"], expected)
    if not observed or digest != manifest["expected_changes_sha256"]:
        reasons.append("CHANGE_MISMATCH")
    return {
        "schema_version": 1, "status": "UNRESOLVED" if reasons else "MATCHED", "reasons": reasons,
        "base_revision": base["revision"], "head_revision": head["revision"], "scope": head["scope"],
        "expected_migration": expected, "newly_applied": applied, "observed_changes": observed,
        "observed_changes_sha256": digest, "expected_changes_sha256": manifest["expected_changes_sha256"],
    }


def main(argv=None):
    parser = inventory.ArgumentParser(prog="schema-migration.py", description=__doc__, allow_abbrev=False)
    parser.add_argument("--base", required=True, metavar=schema.SCHEMA_FILENAME)
    parser.add_argument("--head", required=True, metavar=schema.SCHEMA_FILENAME)
    parser.add_argument("--base-history", required=True, metavar=HISTORY_FILENAME)
    parser.add_argument("--head-history", required=True, metavar=HISTORY_FILENAME)
    parser.add_argument("--manifest", required=True, metavar=MANIFEST_FILENAME)
    try:
        args = parser.parse_args(argv)
        base = schema.read_schema(schema.path_parts(args.base, schema.SCHEMA_FILENAME))
        head = schema.read_schema(schema.path_parts(args.head, schema.SCHEMA_FILENAME))
        report = build_report(base, head, read_history(args.base_history), read_history(args.head_history),
                              read_manifest(args.manifest))
    except (OSError, ValueError, RecursionError, NotImplementedError):
        print("ERROR: invalid schema migration input or scope", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if report["status"] == "UNRESOLVED" else 0


if __name__ == "__main__":
    sys.exit(main())
