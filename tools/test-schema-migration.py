#!/usr/bin/env python3
"""Exercise migration attribution with synthetic metadata and local file inputs."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("schema_migration", Path(__file__).with_name("schema-migration.py"))
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)

PATHS = {
    "base": "base/SCHEMA-SNAPSHOT.json",
    "head": "head/SCHEMA-SNAPSHOT.json",
    "base-history": "base/MIGRATION-HISTORY.json",
    "head-history": "head/MIGRATION-HISTORY.json",
    "manifest": "MIGRATION-MANIFEST.json",
}
BASE = "1" * 40
HEAD = "2" * 40
SCOPE = "3" * 64
ERROR = "ERROR: invalid schema migration input or scope\n"
PRIOR = {"version": "1", "checksum_sha256": "a" * 64}
EXPECTED = {"version": "2", "checksum_sha256": "b" * 64}
OTHER = {"version": "3", "checksum_sha256": "c" * 64}


def definition(width, nullable=False):
    return {"type": "VARCHAR", "width": width, "nullable": nullable}


def column(name, width, nullable=False):
    return {"table": "order_audit", "column": name, **definition(width, nullable)}


def widening(name, nullable=False):
    return {"table": "order_audit", "column": name, "kind": "WIDTH",
            "before": definition(16, nullable), "after": definition(32, nullable)}


EVENT_CHANGE = widening("event_code")
NOTE_CHANGE = widening("fixture_note", nullable=True)


def digest(changes):
    canonical = json.dumps(changes, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


@unittest.skipUnless(os.name == "posix", "descriptor-relative metadata reads require POSIX")
class SchemaMigrationTest(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(workspace.name)
        Path("base").mkdir()
        Path("head").mkdir()
        self.write_schema("base", BASE, column("event_code", 16), column("fixture_note", 16, nullable=True))
        self.write_schema("head", HEAD, column("event_code", 32), column("fixture_note", 16, nullable=True))
        self.write_history("base-history", BASE, PRIOR)
        self.write_history("head-history", HEAD, PRIOR, EXPECTED)
        self.write_manifest()

    def write(self, key, value):
        Path(PATHS[key]).write_text(json.dumps(value), encoding="utf-8")

    def write_schema(self, key, revision, *columns, scope=SCOPE):
        self.write(key, {"schema_version": 1, "revision": revision, "scope": scope, "columns": list(columns)})

    def write_history(self, key, revision, *records, **overrides):
        self.write(key, {"schema_version": 1, "revision": revision, "scope": SCOPE,
                         "migrations": list(records), **overrides})

    def write_manifest(self, **overrides):
        self.write("manifest", {"schema_version": 1, "base_revision": BASE, "revision": HEAD, "scope": SCOPE,
                                **EXPECTED, "expected_changes_sha256": digest([EVENT_CHANGE]), **overrides})

    def invoke(self, **paths):
        options = {**PATHS, **paths}
        args = [argument for flag, path in options.items() for argument in (f"--{flag}", path)]
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = migration.main(args)
        return status, output.getvalue(), error.getvalue()

    def assert_invalid(self, **paths):
        self.assertEqual(self.invoke(**paths), (1, "", ERROR))

    def assert_report(self, reasons, observed, applied):
        status, output, error = self.invoke()
        self.assertEqual((status, error), (2 if reasons else 0, ""))
        expected_report = {
            "schema_version": 1,
            "status": "UNRESOLVED" if reasons else "MATCHED",
            "reasons": reasons,
            "observed_changes": observed,
            "observed_changes_sha256": digest(observed),
            "expected_changes_sha256": digest([EVENT_CHANGE]),
            "newly_applied": applied,
            "expected_migration": EXPECTED,
            "base_revision": BASE,
            "head_revision": HEAD,
            "scope": SCOPE,
        }
        self.assertEqual(json.loads(output), expected_report)

    def test_single_new_migration_matches_history_and_observed_schema(self):
        self.assert_report([], [EVENT_CHANGE], [EXPECTED])

    def test_missing_history_leaves_the_matching_change_unresolved(self):
        self.write_history("base-history", BASE)
        self.write_history("head-history", HEAD)
        self.assert_report(["HISTORY_MISSING"], [EVENT_CHANGE], [])

    def test_previously_applied_migration_does_not_explain_a_new_change(self):
        self.write_history("base-history", BASE, PRIOR, EXPECTED)
        self.assert_report(["HISTORY_MISSING"], [EVENT_CHANGE], [])

    def test_wrong_version_or_checksum_does_not_attribute_an_identical_change(self):
        for reason, record in (
            ("VERSION_MISMATCH", {**EXPECTED, "version": OTHER["version"]}),
            ("CHECKSUM_MISMATCH", {**EXPECTED, "checksum_sha256": OTHER["checksum_sha256"]}),
        ):
            with self.subTest(reason=reason):
                self.write_history("head-history", HEAD, PRIOR, record)
                self.assert_report([reason], [EVENT_CHANGE], [record])

    def test_changed_base_prefix_does_not_produce_a_trusted_suffix(self):
        self.write_history("head-history", HEAD, {**PRIOR, "checksum_sha256": "d" * 64}, EXPECTED)
        self.assert_report(["HISTORY_DIVERGED"], [EVENT_CHANGE], [])

    def test_multiple_new_migrations_remain_ambiguous(self):
        self.write_history("head-history", HEAD, PRIOR, EXPECTED, OTHER)
        self.assert_report(["MULTIPLE_MIGRATIONS"], [EVENT_CHANGE], [EXPECTED, OTHER])

    def test_unrelated_column_change_does_not_match_the_recorded_migration(self):
        self.write_schema("head", HEAD, column("event_code", 16), column("fixture_note", 32, nullable=True))
        self.assert_report(["CHANGE_MISMATCH"], [NOTE_CHANGE], [EXPECTED])

    def test_required_change_with_extra_drift_does_not_match(self):
        self.write_schema("head", HEAD, column("fixture_note", 32, nullable=True), column("event_code", 32))
        self.assert_report(["CHANGE_MISMATCH"], [EVENT_CHANGE, NOTE_CHANGE], [EXPECTED])

    def test_empty_delta_does_not_match_even_its_exact_manifest_digest(self):
        self.write_schema("head", HEAD, column("event_code", 16), column("fixture_note", 16, nullable=True))
        self.write_manifest(expected_changes_sha256=digest([]))
        status, output, error = self.invoke()
        self.assertEqual((status, error), (2, ""))
        report = json.loads(output)
        self.assertEqual((report["status"], report["reasons"], report["observed_changes"]),
                         ("UNRESOLVED", ["CHANGE_MISMATCH"], []))
        self.assertEqual(report["observed_changes_sha256"], report["expected_changes_sha256"])

    def test_reports_history_problem_before_change_mismatch(self):
        self.write_history("head-history", HEAD, PRIOR)
        self.write_schema("head", HEAD, column("event_code", 16), column("fixture_note", 32, nullable=True))
        self.assert_report(["HISTORY_MISSING", "CHANGE_MISMATCH"], [NOTE_CHANGE], [])

    def test_rejects_same_snapshot_revision_and_cross_scope_snapshots(self):
        for revision, scope in ((BASE, SCOPE), (HEAD, "4" * 64)):
            with self.subTest(revision=revision, scope=scope):
                self.write_schema("head", revision, column("event_code", 32), scope=scope)
                self.assert_invalid()

    def test_rejects_scope_or_revision_mismatches_in_all_evidence(self):
        for key, revision, records in (("base-history", BASE, [PRIOR]), ("head-history", HEAD, [PRIOR, EXPECTED])):
            with self.subTest(key=key):
                self.write_history(key, "4" * 40, *records)
                self.assert_invalid()
                self.write_history(key, revision, *records, scope="4" * 64)
                self.assert_invalid()
                self.write_history(key, revision, *records)
        for overrides in ({"scope": "4" * 64}, {"base_revision": HEAD}, {"revision": BASE}):
            with self.subTest(overrides=overrides):
                self.write_manifest(**overrides)
                self.assert_invalid()

    def test_rejects_duplicate_versions_and_malformed_history_records(self):
        for records in ([PRIOR, EXPECTED, EXPECTED], [PRIOR, {**EXPECTED, "checksum_sha256": "B" * 64}],
                        [PRIOR, {**EXPECTED, "version": {"invalid": True}}], [PRIOR, {**EXPECTED, "unknown": 1}]):
            with self.subTest(records=records):
                self.write_history("head-history", HEAD, *records)
                self.assert_invalid()

    def test_rejects_invalid_manifest_fields_and_duplicate_json_keys(self):
        for overrides in ({"schema_version": True}, {"expected_changes_sha256": "c" * 63}, {"unknown": 1}):
            with self.subTest(overrides=overrides):
                self.write_manifest(**overrides)
                self.assert_invalid()
        self.write_manifest()
        manifest = Path(PATHS["manifest"])
        manifest.write_text(manifest.read_text(encoding="utf-8")[:-1] + ', "version": "2"}', encoding="utf-8")
        self.assert_invalid()

    def test_rejects_unsafe_paths_oversized_files_and_missing_input_files(self):
        self.assert_invalid(manifest="../MIGRATION-MANIFEST.json")
        self.assert_invalid(manifest="missing/MIGRATION-MANIFEST.json")
        head_history = Path(PATHS["head-history"])
        head_history.write_bytes(b" " * (1024 * 1024 + 1))
        self.assert_invalid()
        head_history.unlink()
        head_history.symlink_to(Path(PATHS["base-history"]).resolve())
        self.assert_invalid()


if __name__ == "__main__":
    unittest.main()
