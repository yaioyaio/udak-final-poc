#!/usr/bin/env python3
"""Verify SQL inventory validation, metadata privacy and reporting with synthetic inputs."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("sql_inventory", Path(__file__).with_name("sql-inventory.py"))
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)

BASE = "inventory/base/SQL-INVENTORY.json"
HEAD = "inventory/head/SQL-INVENTORY.json"
PROFILE = "f" * 64
TEST_1 = "1" * 64
TEST_2 = "2" * 64
TEST_3 = "3" * 64
FINGERPRINT_1 = {"fingerprint_hash": "c" * 64, "statement_kind": "SELECT"}
FINGERPRINT_2 = {"fingerprint_hash": "d" * 64, "statement_kind": "UPDATE"}
STOCK_QUERY = "4" * 64
STOCK_BASE = {"fingerprint_hash": "5" * 64, "statement_kind": "UPDATE"}
STOCK_HEAD = {"fingerprint_hash": "6" * 64, "statement_kind": "UPDATE"}
GENERIC_ERROR = "ERROR: invalid SQL inventory input or arguments\n"
SCHEMA_REVIEW = "SCHEMA-REVIEW.json"
REGISTERED_DEVICE_TEST = hashlib.sha256(b"udak-inventory-test-id-v1\0thingsboard-14036-device-profile-replay").hexdigest()
REVIEW_SPEC = importlib.util.spec_from_file_location("pr_schema_review", Path(__file__).with_name("pr-schema-review.py"))
schema_review = importlib.util.module_from_spec(REVIEW_SPEC)
REVIEW_SPEC.loader.exec_module(schema_review)


def snapshot(*entries, **extra):
    return {"schema_version": 1, "revision": "a" * 40, "profile": PROFILE, "dropped": 0,
            "entries": list(entries), **extra}


def entry(query="0" * 64, **extra):
    return {"framework": "JDBC", "identity": "SCOPED", "query_id_hash": query, "declared": True,
            "observed": 1, "unavailable": 0, "test_ids": [TEST_1], "shapes": [FINGERPRINT_1], **extra}


def linked_shape(shape, *test_ids):
    return {**shape, "test_ids": list(test_ids)}


def stock_entries(shape):
    return [
        entry(STOCK_QUERY, observed=3, shapes=[FINGERPRINT_1, shape]),
        entry(STOCK_QUERY, framework="MYBATIS", observed=2, shapes=[shape]),
    ]


@unittest.skipUnless(os.name == "posix", "descriptor-relative inventory reads require POSIX")
class SqlInventoryTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(directory.name)
        for path in (BASE, HEAD):
            Path(path).parent.mkdir(parents=True)
            self.write(path, snapshot())

    def write(self, path, value):
        Path(path).write_text(json.dumps(value), encoding="utf-8")

    def invoke(self, *flags, base=BASE, head=HEAD):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = inventory.main(["--base", base, "--head", head, *flags])
        return status, out.getvalue(), err.getvalue()

    def report(self, code=0, *flags):
        status, stdout, stderr = self.invoke(*flags)
        self.assertEqual((status, stderr), (code, ""))
        return json.loads(stdout)

    def assert_invalid(self, *flags, **paths):
        self.assertEqual(self.invoke(*flags, **paths), (1, "", GENERIC_ERROR))

    def compare_guarded(self, status, *options):
        tools = Path(__file__).resolve().parent
        scratch = Path.cwd() / "protected-scratch"
        scratch.mkdir(exist_ok=True)
        environment = {"TMPDIR": str(scratch), "LC_ALL": "C.UTF-8"}
        arguments = ["--base", BASE, "--head", HEAD, *options]
        direct = subprocess.run([sys.executable, "-B", str(tools / "sql-inventory.py"), *arguments],
                                capture_output=True, env=environment, timeout=20)
        protected = subprocess.run([sys.executable, "-B", str(tools / "run-sql-inventory.py"),
                                    "--pr-report", *arguments], capture_output=True, env=environment, timeout=20)
        self.assertEqual(direct.returncode, status)
        self.assertEqual((protected.returncode, protected.stdout, protected.stderr),
                         (direct.returncode, direct.stdout, direct.stderr))
        self.assertEqual(list(scratch.iterdir()), [])
        return protected.stdout

    def write_schema_review(self, capture_status="VERIFIED", test_id=TEST_1):
        before, after = "a" * 40, "b" * 40
        query = entry(test_ids=[test_id], shapes=[linked_shape(FINGERPRINT_1, test_id)])
        self.write(BASE, snapshot(query, schema_version=2, revision=before))
        self.write(HEAD, snapshot(query, schema_version=2, revision=after))
        customer = {"type": "UUID", "width": 0, "nullable": True}
        change = {"table": "device", "column": "customer_id", "kind": "REMOVED", "before": customer, "after": None}
        identifier = {"table": "device", "column": "id", **customer, "nullable": False}
        for side, revision, columns in (
            ("base", before, [identifier, {"table": "device", "column": "customer_id", **customer}]),
            ("head", after, [identifier]),
        ):
            self.write(f"inventory/{side}/SCHEMA-SNAPSHOT.json", {
                "schema_version": 1, "revision": revision, "scope": PROFILE, "columns": columns})
        self.write("inventory/head/QUERY-DEPENDENCIES.json", {
            "schema_version": 2, "revision": after, "scope": PROFILE, "dependencies": [{
                "framework": "JDBC", "query_id_hash": query["query_id_hash"], "test_ids": [test_id],
                "fingerprint_hash": FINGERPRINT_1["fingerprint_hash"],
                "columns": [{"table": "device", "column": "customer_id"}],
            }],
        })
        applied = {"version": "2", "checksum_sha256": "9" * 64}
        digest = hashlib.sha256(json.dumps([change], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.write("inventory/head/MIGRATION-MANIFEST.json", {
            "schema_version": 1, "base_revision": before, "revision": after, "scope": PROFILE,
            **applied, "expected_changes_sha256": digest,
        })
        self.write("inventory/base/MIGRATION-HISTORY.json", {
            "schema_version": 1, "revision": before, "scope": PROFILE, "migrations": [],
        })
        capture = {"status": capture_status, "revision": after, "scope": PROFILE}
        if capture_status != "HISTORY_FILE_UNVERIFIED":
            capture["history"] = "inventory/head/MIGRATION-HISTORY.json"
            self.write(capture["history"], {
                "schema_version": 1, "revision": after, "scope": PROFILE,
                "migrations": [applied] if capture_status == "VERIFIED" else [],
            })
        request = {
            "schema_version": 1, "base_schema": "inventory/base/SCHEMA-SNAPSHOT.json",
            "head_schema": "inventory/head/SCHEMA-SNAPSHOT.json", "dependencies": "inventory/head/QUERY-DEPENDENCIES.json",
            "base_history": "inventory/base/MIGRATION-HISTORY.json", "manifest": "inventory/head/MIGRATION-MANIFEST.json",
            "flyway_capture": capture,
        }
        self.write(SCHEMA_REVIEW, request)
        return request, change

    def setup_replay_receipt(self, capture="VERIFIED", test_id=REGISTERED_DEVICE_TEST):
        self.write_schema_review(capture, test_id)
        code = 0 if capture == "VERIFIED" else 2
        flags = ("--schema-review", SCHEMA_REVIEW, "--fail-on-change")
        base_json = self.compare_guarded(code, *flags)
        base_report = json.loads(base_json)
        self.assertNotIn("registered_replay", base_report)
        base_markdown = self.compare_guarded(code, *flags, "--format", "markdown").decode()
        receipt = {"schema_version": 1, "status": "PASS", "report_sha256": hashlib.sha256(base_json).hexdigest(),
                   "test_id_hash": test_id, "target_schema_sha256": base_report["schema_review"]["head_schema_sha256"],
                   "entry_point": "THINGSBOARD_14036_DEVICE_PROFILE", "sqlstate": "42703", "executed_queries": 1}
        return (base_json, base_markdown), receipt

    def test_guarded_report_displays_bound_replay_in_both_formats(self):
        base, receipt = self.setup_replay_receipt()
        report, markdown = schema_review.attach_guarded_replay(*base, receipt)
        self.assertEqual(report.pop("registered_replay"), {
            "status": "VERIFIED", "result": "PASS",
            **{key: value for key, value in receipt.items() if key not in ("schema_version", "status")}})
        self.assertEqual(report, json.loads(base[0]))
        self.assertEqual(markdown.split("\n## Registered replay\n")[0], base[1])
        for label in ("## Registered replay", "**VERIFIED**", "**PASS**", "42703", receipt["report_sha256"],
                      receipt["test_id_hash"], receipt["target_schema_sha256"]):
            self.assertIn(label, markdown)

    def test_guarded_report_displays_unverified_receipts_without_detail(self):
        base, receipt = self.setup_replay_receipt()
        cases = (
            (None, "RECEIPT_MISSING"),
            ({**receipt, "report_sha256": "1" * 64}, "REPORT_HASH_MISMATCH"),
            ({**receipt, "test_id_hash": "2" * 64}, "TEST_HASH_MISMATCH"),
            ({**receipt, "target_schema_sha256": "3" * 64}, "SCHEMA_HASH_MISMATCH"),
            ({**receipt, "execution_detail": "private-payload"}, "INVALID_RECEIPT"),
            ({**receipt, "executed_queries": True}, "INVALID_RECEIPT"),
        )
        for record, reason in cases:
            with self.subTest(reason=reason):
                report, markdown = schema_review.attach_guarded_replay(*base, record)
                verdict = report["registered_replay"]
                self.assertEqual(verdict, {"status": "UNVERIFIED", "reason": reason})
                self.assertIn("**UNVERIFIED**", markdown)
                self.assertIn(reason, markdown)
                self.assertNotIn("42703", markdown)
                self.assertNotIn("private-payload", markdown)
        self.write("REPLAY-RECEIPT.json", receipt)
        self.compare_guarded(1, "--schema-review", SCHEMA_REVIEW, "--replay-receipt", "REPLAY-RECEIPT.json")

    def test_replay_verdict_requires_complete_report_and_registered_test(self):
        for capture, test_id, reason in (
            ("EMPTY", REGISTERED_DEVICE_TEST, "INCOMPLETE_REPORT"),
            ("VERIFIED", TEST_1, "TEST_HASH_MISMATCH"),
        ):
            with self.subTest(reason=reason):
                base, receipt = self.setup_replay_receipt(capture, test_id)
                report, _ = schema_review.attach_guarded_replay(*base, receipt)
                self.assertEqual(report["registered_replay"],
                                 {"status": "UNVERIFIED", "reason": reason})

    def test_schema_review_matches_registered_test_when_sql_is_unchanged(self):
        request, change = self.write_schema_review()
        self.assertNotIn("schema_review", self.report())
        flags = ("--schema-review", SCHEMA_REVIEW, "--fail-on-change")
        report = self.report(0, *flags)
        self.assertFalse(report["changes_detected"])
        self.assertEqual(report["impacted_test_ids"], [])
        self.assertEqual(report["schema_review"]["change"], change)
        head_sha = hashlib.sha256(Path(request["head_schema"]).read_bytes()).hexdigest()
        self.assertEqual(report["schema_review"]["head_schema_sha256"], head_sha)
        self.assertEqual(report["schema_review"]["impacted_test_ids"], [TEST_1])
        self.assertEqual(report["schema_review"]["flyway_history"], {"status": "MATCHED", "reasons": []})
        code, markdown, error = self.invoke(*flags, "--format", "markdown")
        self.assertEqual((code, error), (0, ""))
        for value in ("device.customer_id", "MATCHED", TEST_1):
            self.assertIn(value, markdown)

    def test_registered_schema_replay_requires_exact_snapshot_and_observed_fingerprint(self):
        request, change = self.write_schema_review()
        report = self.report(0, "--schema-review", SCHEMA_REVIEW)
        target = Path(request["head_schema"]).read_bytes()
        source = Path(__file__).resolve().with_name("schema-pr-regression.py")
        spec = importlib.util.spec_from_file_location("schema_pr_regression", source)
        planner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(planner)
        registration = {"query_id_hash": "0" * 64, "test_id_hash": TEST_1,
                        "head_fingerprint_hash": FINGERPRINT_1["fingerprint_hash"]}
        ready = planner.plan(report, target, registration, change)
        self.assertEqual((ready["status"], ready["entry_point"]), ("READY", planner.ENTRY_POINT))
        for modified_snapshot, amended_registration, expected_reason in (
            (target + b"\n", registration, "SCHEMA_MISMATCH"),
            (target, {**registration, "head_fingerprint_hash": FINGERPRINT_2["fingerprint_hash"]},
             "REGISTRATION_MISMATCH"),
            (target, {**registration, "test_id_hash": TEST_2}, "UNKNOWN_TEST_HASH"),
        ):
            with self.subTest(reason=expected_reason):
                blocked = planner.plan(report, modified_snapshot, amended_registration, change)
                self.assertEqual(blocked["status"], "REVIEW_REQUIRED")
                self.assertEqual(blocked["reasons"], [expected_reason])
                self.assertIsNone(blocked["entry_point"])

    def test_schema_review_keeps_test_candidates_for_distinct_history_failures(self):
        for capture, reason in (("EMPTY", "HISTORY_MISSING"), ("HISTORY_FILE_UNVERIFIED", "HISTORY_FILE_UNVERIFIED")):
            with self.subTest(capture=capture):
                self.write_schema_review(capture)
                flags = ("--schema-review", SCHEMA_REVIEW, "--fail-on-change")
                report = self.report(2, *flags)
                self.assertEqual(report["status"], "INCOMPLETE")
                self.assertEqual(report["schema_review"]["impacted_test_ids"], [TEST_1])
                self.assertEqual(report["schema_review"]["flyway_history"]["reasons"], [reason])
                code, markdown, error = self.invoke(*flags, "--format", "markdown")
                self.assertEqual((code, error), (2, ""))
                self.assertIn(reason, markdown)
                self.assertNotIn("Unavailable observations or dropped records limit", markdown)

    def test_schema_review_rejects_unbound_snapshots_and_inconsistent_capture(self):
        request, _ = self.write_schema_review("HISTORY_FILE_UNVERIFIED")
        flags = ("--schema-review", SCHEMA_REVIEW)
        for field, value in (("scope", "0" * 64), ("revision", "0" * 40),
                             ("history", "inventory/head/MIGRATION-HISTORY.json")):
            with self.subTest(field=field):
                self.write(SCHEMA_REVIEW, {**request, "flyway_capture": {**request["flyway_capture"], field: value}})
                self.assert_invalid(*flags)
        self.write(SCHEMA_REVIEW, request)
        self.write(BASE, snapshot(revision="0" * 40))
        self.assert_invalid(*flags)
        self.assert_invalid("--schema-review", "")

    def test_schema_review_reports_exact_change_mismatch_and_fingerprint_test_mismatch(self):
        request, _ = self.write_schema_review()
        flags = ("--schema-review", SCHEMA_REVIEW)
        manifest = json.loads(Path(request["manifest"]).read_bytes())
        self.write(request["manifest"], {**manifest, "expected_changes_sha256": "0" * 64})
        review = self.report(2, *flags)["schema_review"]
        self.assertEqual(review["flyway_history"]["reasons"], ["CHANGE_MISMATCH"])
        self.assertEqual(review["impacted_test_ids"], [TEST_1])
        self.write(request["manifest"], manifest)
        dependencies = json.loads(Path(request["dependencies"]).read_bytes())
        dependencies["dependencies"][0]["test_ids"] = [TEST_2]
        self.write(request["dependencies"], dependencies)
        review = self.report(2, *flags)["schema_review"]
        self.assertEqual(review["flyway_history"]["status"], "MATCHED")
        self.assertEqual(review["impacted_test_ids"], [])
        self.assertIn("FINGERPRINT_TEST_MISMATCH", review["unresolved_queries"][0]["reasons"])

    def test_guarded_review_preserves_reports_statuses_and_cleanup(self):
        for capture, code in (("VERIFIED", 0), ("EMPTY", 2), ("HISTORY_FILE_UNVERIFIED", 2)):
            with self.subTest(capture=capture):
                self.write_schema_review(capture)
                for output_format in ("json", "markdown"):
                    self.compare_guarded(code, "--schema-review", SCHEMA_REVIEW, "--format", output_format,
                                         "--fail-on-change")
        self.compare_guarded(1, "--schema-review", "missing/SCHEMA-REVIEW.json")

    def test_guarded_sql_only_preserves_all_report_exit_codes(self):
        self.write(BASE, snapshot(entry()))
        self.write(HEAD, snapshot(entry()))
        report = json.loads(self.compare_guarded(0, "--fail-on-change"))
        self.assertNotIn("schema_review", report)
        self.write(HEAD, snapshot(entry(shapes=[FINGERPRINT_2])))
        self.compare_guarded(3, "--format", "markdown", "--fail-on-change")
        self.write(HEAD, snapshot(entry(shapes=[FINGERPRINT_2]), dropped=1))
        self.compare_guarded(2, "--fail-on-change")
        self.write(HEAD, {"fixture": "REJECTED_PAYLOAD"})
        self.compare_guarded(1)

    def test_guarded_sql_only_preserves_report_larger_than_diagnostic_log(self):
        test_ids = [f"{index:064x}" for index in range(8)]
        shapes = [linked_shape({"fingerprint_hash": f"{index:064x}", "statement_kind": "SELECT"}, *test_ids)
                  for index in range(8)]
        for path, start in ((BASE, 0), (HEAD, 128)):
            self.write(path, snapshot(*(entry(f"{index:064x}", observed=64, test_ids=test_ids, shapes=shapes)
                                         for index in range(start, start + 128)), schema_version=2))
        self.assertGreater(len(self.compare_guarded(3, "--fail-on-change")), 1024 * 1024)

    def test_shape_reference_and_declaration_changes(self):
        self.write(BASE, snapshot(entry(test_ids=[TEST_2, TEST_1])))
        self.write(HEAD, snapshot(entry(declared=False, observed=2, test_ids=[TEST_3, TEST_2], shapes=[FINGERPRINT_2]),
                                  revision="b" * 64))
        report = self.report(3, "--fail-on-change")
        self.assertEqual(self.report(), report)
        self.assertTrue(report["changes_detected"])
        self.assertEqual(report["status"], "COMPLETE")
        self.assertEqual(report["base"]["declared_queries"], 1)
        self.assertEqual(report["head"]["declared_queries"], 0)
        self.assertEqual(report["head"]["revision"], "b" * 64)
        query, = report["queries"]
        self.assertEqual(query["shape_status"], "DIFFERENT")
        self.assertEqual(query["changes"], ["DECLARATION_LOST", "TEST_REFS_GAINED", "TEST_REFS_LOST",
                                            "OBSERVED_SHAPES_ADDED", "OBSERVED_SHAPES_ABSENT"])
        self.assertEqual(query["added_observed_shapes"], [FINGERPRINT_2])
        self.assertEqual(query["absent_observed_shapes"], [FINGERPRINT_1])
        self.assertEqual(query["gained_test_ids"], [TEST_3])
        self.assertEqual(query["lost_test_ids"], [TEST_1])
        self.assertEqual(query["impacted_test_ids"], report["impacted_test_ids"])
        self.assertEqual(report["impacted_test_ids"], [TEST_1, TEST_2, TEST_3])

    def test_shared_stock_shape_keeps_both_observations_and_unrelated_changes(self):
        jdbc_base, mybatis_base = stock_entries(STOCK_BASE)
        jdbc_head, mybatis_head = stock_entries(STOCK_HEAD)
        unrelated_base = entry(framework="JPA", test_ids=[TEST_3])
        unrelated_head = {**unrelated_base, "shapes": [FINGERPRINT_2]}
        jdbc_base["test_ids"] = [TEST_2, TEST_1]
        jdbc_head["declared"] = False
        self.write(BASE, snapshot(mybatis_base, unrelated_base, jdbc_base))
        self.write(HEAD, snapshot(jdbc_head, mybatis_head, unrelated_head))

        report = self.report(3, "--fail-on-change")
        self.assertEqual((report["status"], report["changes_detected"]), ("COMPLETE", True))
        self.assertEqual(report["shared_shape_changes"], [{
            "query_id_hash": STOCK_QUERY,
            "base_shape": STOCK_BASE,
            "head_shape": STOCK_HEAD,
            "observations": [
                {"framework": "JDBC", "point": "JDBC_EXECUTE"},
                {"framework": "MYBATIS", "point": "MYBATIS_PREPARE"},
            ],
            "shared_test_ids": [TEST_1],
        }])
        self.assertEqual(report["impacted_test_ids"], [TEST_1, TEST_2, TEST_3])
        self.assertEqual(len(report["queries"]), 3)
        by_framework = {query["framework"]: query for query in report["queries"]}
        for framework in ("JDBC", "MYBATIS"):
            self.assertEqual(by_framework[framework]["absent_observed_shapes"], [STOCK_BASE])
            self.assertEqual(by_framework[framework]["added_observed_shapes"], [STOCK_HEAD])
        self.assertIn("DECLARATION_LOST", by_framework["JDBC"]["changes"])
        self.assertEqual(by_framework["JDBC"]["lost_test_ids"], [TEST_2])
        self.assertEqual(by_framework["JPA"]["added_observed_shapes"], [FINGERPRINT_2])

        code, markdown, stderr = self.invoke("--format", "markdown", "--fail-on-change")
        self.assertEqual((code, stderr), (3, ""))
        self.assertEqual(markdown.count("\n### Shared SQL shape change"), 1)
        for heading in ("#### JDBC_EXECUTE", "#### MYBATIS_PREPARE", "### JPA `SCOPED`"):
            self.assertIn(heading, markdown)
        for framework in ("JDBC", "MYBATIS"):
            self.assertNotIn(f"### {framework} `SCOPED` `{STOCK_QUERY}`", markdown)
        for shape in (STOCK_BASE, STOCK_HEAD):
            self.assertEqual(markdown.count(shape["fingerprint_hash"]), 1)
        self.assertIn("DECLARATION_LOST", markdown)
        self.assertIn("Lost test references", markdown)

        self.write(BASE, snapshot(jdbc_base, unrelated_base, mybatis_base))
        self.write(HEAD, snapshot(unrelated_head, mybatis_head, jdbc_head))
        self.assertEqual(self.report(3, "--fail-on-change"), report)
        self.assertEqual(self.invoke("--format", "markdown", "--fail-on-change"), (code, markdown, stderr))

    def test_shared_shape_requires_matching_scope_replacement_and_test_on_all_sides(self):
        jdbc_base, mybatis_base = stock_entries(STOCK_BASE)
        jdbc_head, mybatis_head = stock_entries(STOCK_HEAD)
        for label, base_overrides, head_overrides in (
            ("fallback scope", {"identity": "OBSERVE_ID", "declared": False, "test_ids": []},
             {"identity": "OBSERVE_ID", "declared": False, "test_ids": []}),
            ("different query", {"query_id_hash": "7" * 64}, {"query_id_hash": "7" * 64}),
            ("different framework", {"framework": "JPA"}, {"framework": "JPA"}),
            ("missing test", {"test_ids": []}, {}),
            ("no common test", {"test_ids": [TEST_2]}, {"test_ids": [TEST_2]}),
            ("different base shape", {"shapes": [FINGERPRINT_2]}, {}),
            ("different head shape", {}, {"shapes": [FINGERPRINT_2]}),
            ("additional removed shape", {"shapes": [FINGERPRINT_2, STOCK_BASE]}, {}),
            ("only added shape", {}, {"shapes": [STOCK_BASE, STOCK_HEAD]}),
            ("previously unobserved", {"observed": 0, "shapes": []}, {}),
        ):
            with self.subTest(label=label):
                self.write(BASE, snapshot(jdbc_base, {**mybatis_base, **base_overrides}))
                self.write(HEAD, snapshot(jdbc_head, {**mybatis_head, **head_overrides}))
                report = self.report(3, "--fail-on-change")
                self.assertNotIn("shared_shape_changes", report)
                self.assertEqual(len(report["queries"]), 2)

        select_head = {**STOCK_HEAD, "statement_kind": "SELECT"}
        self.write(BASE, snapshot(jdbc_base, mybatis_base))
        self.write(HEAD, snapshot(*stock_entries(select_head)))
        self.assertNotIn("shared_shape_changes", self.report(3, "--fail-on-change"))

    def test_shared_shape_preserves_incomplete_status_and_evidence(self):
        jdbc_base, mybatis_base = stock_entries(STOCK_BASE)
        jdbc_head, mybatis_head = stock_entries(STOCK_HEAD)
        unavailable = entry(framework="JPA", unavailable=1, shapes=[],
                            unavailable_reasons={"UNSUPPORTED_SYNTAX": 1})
        self.write(BASE, snapshot(jdbc_base, mybatis_base))
        self.write(HEAD, snapshot(jdbc_head, mybatis_head, unavailable))
        report = self.report(2, "--fail-on-change")
        self.assertEqual((report["status"], report["changes_detected"]), ("INCOMPLETE", True))
        self.assertEqual(len(report["shared_shape_changes"]), 1)
        self.assertEqual(report["head"]["unavailable_reasons"], {"UNSUPPORTED_SYNTAX": 1})
        code, markdown, stderr = self.invoke("--format", "markdown", "--fail-on-change")
        self.assertEqual((code, stderr), (2, ""))
        self.assertIn("### Shared SQL shape change", markdown)
        self.assertIn("### JPA `SCOPED`", markdown)
        self.assertIn("`UNSUPPORTED_SYNTAX` 1", markdown)

        self.write(HEAD, snapshot(jdbc_head, {**mybatis_head, "unavailable": 1}))
        self.assertNotIn("shared_shape_changes", self.report(2, "--fail-on-change"))
        self.write(HEAD, snapshot(jdbc_head, mybatis_head, dropped=1))
        self.assertNotIn("shared_shape_changes", self.report(2, "--fail-on-change"))

    def test_binding_only_control_has_no_shared_shape_change(self):
        jdbc, mybatis = stock_entries(STOCK_BASE)
        self.write(BASE, snapshot(jdbc, mybatis))
        self.write(HEAD, snapshot({**jdbc, "observed": 5}, {**mybatis, "observed": 3}))
        report = self.report(0, "--fail-on-change")
        self.assertFalse(report["changes_detected"])
        self.assertNotIn("shared_shape_changes", report)
        self.assertEqual([query["shape_status"] for query in report["queries"]], ["UNCHANGED", "UNCHANGED"])
        self.assertEqual(report["impacted_test_ids"], [])

    def test_coverage_and_static_only_categories(self):
        self.write(BASE, snapshot(entry("0" * 64), entry("1" * 64, observed=0, shapes=[]),
                                  entry("3" * 64, observed=0, shapes=[])))
        self.write(HEAD, snapshot(entry("1" * 64), entry("2" * 64, observed=0, shapes=[])))
        queries = self.report()["queries"]
        self.assertIn("NO_LONGER_OBSERVED", queries[0]["changes"])
        self.assertIsNone(queries[0]["head"])
        self.assertEqual(queries[1]["changes"], ["NEWLY_OBSERVED", "OBSERVED_SHAPES_ADDED"])
        self.assertIn("STATIC_ONLY_ADDED", queries[2]["changes"])
        self.assertIn("STATIC_ONLY_MISSING", queries[3]["changes"])
        self.assertNotIn("NO_LONGER_OBSERVED", queries[3]["changes"])

    def test_count_variation_does_not_invalidate_unchanged_shape_set(self):
        self.write(BASE, snapshot(entry(observed=2, shapes=[FINGERPRINT_2, FINGERPRINT_1])))
        self.write(HEAD, snapshot(entry(observed=10, shapes=[FINGERPRINT_1, FINGERPRINT_2])))
        report = self.report(0, "--fail-on-change")
        self.assertFalse(report["changes_detected"])
        self.assertEqual(report["queries"][0]["shape_status"], "UNCHANGED")
        self.assertEqual(report["base"]["observations"], 2)
        self.assertEqual(report["head"]["observations"], 10)
        self.assertEqual(report["impacted_test_ids"], [])

    def test_mixed_snapshot_versions_keep_pr_report_shape_semantics(self):
        previous = stock_entries(STOCK_BASE)
        current = stock_entries(STOCK_HEAD)
        previous_v2, current_v2 = [
            snapshot(
                {**jdbc, "shapes": [linked_shape(FINGERPRINT_1, TEST_1), linked_shape(stock)]},
                {**mybatis, "shapes": [linked_shape(stock, TEST_1)]},
                schema_version=2,
            )
            for (jdbc, mybatis), stock in ((previous, STOCK_BASE), (current, STOCK_HEAD))
        ]
        previous_v1, current_v1 = snapshot(*previous), snapshot(*current)
        self.write(BASE, previous_v1)
        self.write(HEAD, current_v1)
        expected = self.report(3, "--fail-on-change")
        self.assertEqual(expected["schema_version"], 1)
        self.assertNotIn("fingerprint_test_status", expected)
        self.assertEqual(len(expected["shared_shape_changes"]), 1)
        code, markdown, stderr = self.invoke("--format", "markdown", "--fail-on-change")
        self.assertEqual((code, stderr), (3, ""))
        self.assertNotIn("Fingerprint test links", markdown)

        for base, head in ((previous_v1, current_v2), (previous_v2, current_v1)):
            with self.subTest(base_version=base["schema_version"]):
                self.write(BASE, base)
                self.write(HEAD, head)
                self.assertEqual(self.report(3, "--fail-on-change"),
                                 {**expected, "fingerprint_test_status": "MIXED_VERSIONS"})
                code, markdown, stderr = self.invoke("--format", "markdown", "--fail-on-change")
                self.assertEqual((code, stderr), (3, ""))
                self.assertIn("Fingerprint test links **MIXED_VERSIONS**", markdown)
                self.assertIn("### Shared SQL shape change", markdown)
                self.assertNotIn("- Fingerprint test links `", markdown)

        self.write(BASE, previous_v2)
        self.write(HEAD, current_v2)
        report = self.report(3, "--fail-on-change")
        self.assertEqual(report["shared_shape_changes"], expected["shared_shape_changes"])
        code, markdown, stderr = self.invoke("--format", "markdown", "--fail-on-change")
        self.assertEqual((code, stderr), (3, ""))
        self.assertIn("### Shared SQL shape change", markdown)
        self.assertIn(f"- Fingerprint test links `UPDATE` `{STOCK_HEAD['fingerprint_hash']}`", markdown)

    def test_fingerprint_test_link_swap_with_unchanged_sql_triggers_change_gate(self):
        scope = entry(observed=3, test_ids=[TEST_1, TEST_2, TEST_3])
        self.write(BASE, snapshot({**scope, "shapes": [
            linked_shape(FINGERPRINT_2, TEST_2), linked_shape(FINGERPRINT_1, TEST_3, TEST_1),
        ]}, schema_version=2))
        self.write(HEAD, snapshot({**scope, "shapes": [
            linked_shape(FINGERPRINT_1, TEST_2, TEST_3), linked_shape(FINGERPRINT_2, TEST_1),
        ]}, schema_version=2))
        report = self.report(3, "--fail-on-change")
        self.assertEqual(self.report(), report)
        self.assertEqual((report["status"], report["fingerprint_test_status"]), ("COMPLETE", "COMPARABLE"))
        self.assertTrue(report["changes_detected"])
        query, = report["queries"]
        self.assertEqual(query["shape_status"], "UNCHANGED")
        self.assertEqual(query["changes"], ["FINGERPRINT_TEST_LINKS_CHANGED"])
        for field in ("added_observed_shapes", "absent_observed_shapes", "gained_test_ids", "lost_test_ids"):
            self.assertEqual(query[field], [])
        for side in ("base", "head"):
            self.assertEqual(query[side]["shapes"], [FINGERPRINT_1, FINGERPRINT_2])
        self.assertEqual(query["fingerprint_test_changes"], [
            {**FINGERPRINT_1, "gained_test_ids": [TEST_2], "lost_test_ids": [TEST_1]},
            {**FINGERPRINT_2, "gained_test_ids": [TEST_1], "lost_test_ids": [TEST_2]},
        ])
        self.assertEqual(query["impacted_test_ids"], [TEST_1, TEST_2])
        self.assertEqual(report["impacted_test_ids"], [TEST_1, TEST_2])
        self.assertNotIn("shared_shape_changes", report)
        code, markdown, stderr = self.invoke("--format", "markdown", "--fail-on-change")
        self.assertEqual((code, stderr), (3, ""))
        self.assertIn("Fingerprint test links **COMPARABLE**", markdown)
        self.assertIn("`FINGERPRINT_TEST_LINKS_CHANGED`", markdown)
        self.assertIn(f"- Fingerprint test links `SELECT` `{FINGERPRINT_1['fingerprint_hash']}`", markdown)
        self.assertIn(f"  - Gained test references `{TEST_2}`", markdown)
        self.assertIn(f"  - Lost test references `{TEST_1}`", markdown)
        self.assertNotIn(TEST_3, markdown)

    def test_fingerprint_test_link_pure_gain_loss_and_link_order_control(self):
        scope = entry(observed=3, test_ids=[TEST_3, TEST_1, TEST_2])
        without_links = snapshot({**scope, "shapes": [linked_shape(FINGERPRINT_1, TEST_3)]}, schema_version=2)
        with_links = snapshot({**scope, "shapes": [
            linked_shape(FINGERPRINT_1, TEST_3, TEST_2, TEST_1),
        ]}, schema_version=2)
        for base, head, gained, lost in (
            (without_links, with_links, [TEST_1, TEST_2], []),
            (with_links, without_links, [], [TEST_1, TEST_2]),
        ):
            with self.subTest(gained=gained, lost=lost):
                self.write(BASE, base)
                self.write(HEAD, head)
                report = self.report(3, "--fail-on-change")
                query, = report["queries"]
                self.assertEqual(query["changes"], ["FINGERPRINT_TEST_LINKS_CHANGED"])
                self.assertEqual(query["fingerprint_test_changes"], [
                    {**FINGERPRINT_1, "gained_test_ids": gained, "lost_test_ids": lost},
                ])
                self.assertEqual(report["impacted_test_ids"], [TEST_1, TEST_2])

        self.write(BASE, with_links)
        self.write(HEAD, snapshot({**scope, "observed": 4, "shapes": [
            linked_shape(FINGERPRINT_1, TEST_1, TEST_2, TEST_3),
        ]}, schema_version=2))
        report = self.report(0, "--fail-on-change")
        self.assertEqual(report["fingerprint_test_status"], "COMPARABLE")
        self.assertFalse(report["changes_detected"])
        self.assertEqual(report["impacted_test_ids"], [])
        self.assertNotIn("fingerprint_test_changes", report["queries"][0])

    def test_fingerprint_test_link_changes_keep_framework_identity_and_kind_separate(self):
        update = {**FINGERPRINT_1, "statement_kind": "UPDATE"}
        jdbc_base = entry(test_ids=[TEST_1, TEST_3], shapes=[linked_shape(FINGERPRINT_1, TEST_1)])
        jdbc_head = entry(test_ids=[TEST_1, TEST_3], shapes=[linked_shape(update, TEST_1)])
        mybatis = entry(framework="MYBATIS", test_ids=[TEST_2], shapes=[linked_shape(FINGERPRINT_1, TEST_2)])
        fallback = entry(identity="OBSERVE_ID", declared=False, test_ids=[], shapes=[linked_shape(FINGERPRINT_1)])
        self.write(BASE, snapshot(mybatis, fallback, jdbc_base, schema_version=2))
        self.write(HEAD, snapshot(jdbc_head, mybatis, fallback, schema_version=2))
        report = self.report(3, "--fail-on-change")
        queries = {(query["framework"], query["identity"]): query for query in report["queries"]}
        jdbc = queries["JDBC", "SCOPED"]
        self.assertEqual(jdbc["added_observed_shapes"], [update])
        self.assertEqual(jdbc["absent_observed_shapes"], [FINGERPRINT_1])
        self.assertEqual(jdbc["fingerprint_test_changes"], [
            {**FINGERPRINT_1, "gained_test_ids": [], "lost_test_ids": [TEST_1]},
            {**update, "gained_test_ids": [TEST_1], "lost_test_ids": []},
        ])
        for key in (("MYBATIS", "SCOPED"), ("JDBC", "OBSERVE_ID")):
            self.assertEqual(queries[key]["changes"], [])
            self.assertNotIn("fingerprint_test_changes", queries[key])
        self.assertEqual(report["impacted_test_ids"], [TEST_1, TEST_3])

    def test_fingerprint_test_links_when_query_entry_is_added_or_absent(self):
        observed = snapshot(entry(shapes=[linked_shape(FINGERPRINT_1, TEST_1)]), schema_version=2)
        absent = snapshot(schema_version=2)
        for base, head, empty_side, observation_change, gained, lost in (
            (absent, observed, "base", "NEWLY_OBSERVED", [TEST_1], []),
            (observed, absent, "head", "NO_LONGER_OBSERVED", [], [TEST_1]),
        ):
            with self.subTest(empty_side=empty_side):
                self.write(BASE, base)
                self.write(HEAD, head)
                report = self.report(3, "--fail-on-change")
                query, = report["queries"]
                self.assertIsNone(query[empty_side])
                self.assertIn(observation_change, query["changes"])
                self.assertIn("FINGERPRINT_TEST_LINKS_CHANGED", query["changes"])
                self.assertEqual(query["fingerprint_test_changes"], [
                    {**FINGERPRINT_1, "gained_test_ids": gained, "lost_test_ids": lost},
                ])

    def test_incomplete_snapshots_suppress_fingerprint_test_changes_for_all_queries(self):
        scope = entry(test_ids=[TEST_1, TEST_2])
        changed = (
            {**scope, "shapes": [linked_shape(FINGERPRINT_1, TEST_1)]},
            {**scope, "shapes": [linked_shape(FINGERPRINT_1, TEST_2)]},
        )
        unavailable = entry(framework="JPA", unavailable=1, shapes=[], test_ids=[],
                            unavailable_reasons={"UNSUPPORTED_SYNTAX": 1})
        for side in (0, 1):
            for cause in ("dropped", "unavailable"):
                with self.subTest(side=side, cause=cause):
                    sides = [snapshot(query, schema_version=2) for query in changed]
                    if cause == "dropped":
                        sides[side]["dropped"] = 1
                    else:
                        sides[side]["entries"].append(unavailable)
                    self.write(BASE, sides[0])
                    self.write(HEAD, sides[1])
                    report = self.report(2, "--fail-on-change")
                    self.assertEqual((report["status"], report["fingerprint_test_status"]),
                                     ("INCOMPLETE", "INCOMPLETE"))
                    self.assertEqual(report["changes_detected"], True if cause == "unavailable" else None)
                    self.assertEqual(report["impacted_test_ids"], [])
                    for query in report["queries"]:
                        self.assertNotIn("FINGERPRINT_TEST_LINKS_CHANGED", query["changes"])
                        self.assertNotIn("fingerprint_test_changes", query)
                    code, markdown, stderr = self.invoke("--format", "markdown", "--fail-on-change")
                    self.assertEqual((code, stderr), (2, ""))
                    self.assertIn("Fingerprint test links **INCOMPLETE**", markdown)
                    self.assertNotIn("- Fingerprint test links `", markdown)

    def test_fallback_and_scoped_keys_stay_separate(self):
        self.write(BASE, snapshot(entry()))
        self.write(HEAD, snapshot(entry(identity="OBSERVE_ID", declared=False, test_ids=[])))
        queries = self.report()["queries"]
        self.assertEqual([query["identity"] for query in queries], ["OBSERVE_ID", "SCOPED"])
        self.assertIn("NEWLY_OBSERVED", queries[0]["changes"])
        self.assertIn("NO_LONGER_OBSERVED", queries[1]["changes"])
        self.assertEqual(queries[0]["impacted_test_ids"], [])

    def test_unavailable_and_dropped_are_incomplete_before_change_gate(self):
        self.write(HEAD, snapshot(entry(observed=2, unavailable=2, shapes=[])))
        report = self.report(2, "--fail-on-change")
        self.assertEqual(report["status"], "INCOMPLETE")
        self.assertEqual(report["head"]["unavailable"], 2)
        self.assertEqual(report["queries"][0]["shape_status"], "UNAVAILABLE")
        self.assertTrue(report["changes_detected"])
        self.write(HEAD, snapshot(dropped=1))
        report = self.report(2, "--fail-on-change")
        self.assertEqual(report["head"]["dropped"], 1)
        self.assertIsNone(report["changes_detected"])
        status, markdown, stderr = self.invoke("--format", "markdown", "--fail-on-change")
        self.assertEqual((status, stderr), (2, ""))
        self.assertIn("**INCOMPLETE**", markdown)
        self.assertIn("limit this comparison", markdown)

    def test_profile_mismatch_is_invalid_even_when_dropped(self):
        self.write(HEAD, snapshot(profile="b" * 64, dropped=1))
        self.assert_invalid("--fail-on-change")

    def test_reason_totals_per_side_and_query_with_legacy_input(self):
        self.write(BASE, snapshot(entry(observed=1, unavailable=1, shapes=[])))
        self.write(HEAD, snapshot(
            entry(observed=3, unavailable=3, shapes=[],
                  unavailable_reasons={"EMPTY_SQL": 1, "MALFORMED_SYNTAX": 2}),
            entry("1" * 64, observed=2, unavailable=2, shapes=[], unavailable_reasons={"EMPTY_SQL": 2}),
        ))
        report = self.report(2, "--fail-on-change")
        self.assertEqual(report["base"]["unavailable_reasons"], {"UNSPECIFIED": 1})
        self.assertEqual(report["head"]["unavailable_reasons"], {"EMPTY_SQL": 3, "MALFORMED_SYNTAX": 2})
        query = report["queries"][0]
        self.assertEqual(query["shape_status"], "UNAVAILABLE")
        self.assertEqual(query["changes"], [])
        self.assertEqual(query["head"]["unavailable_reasons"], {"EMPTY_SQL": 1, "MALFORMED_SYNTAX": 2})
        status, markdown, stderr = self.invoke("--format", "markdown")
        self.assertEqual((status, stderr), (2, ""))
        self.assertIn("| `EMPTY_SQL` | 0 | 3 |", markdown)
        self.assertIn("- `MALFORMED_SYNTAX` 2", markdown)

    def test_reason_validation(self):
        for invalid in ([], {}, None, {"NONE": 1}, {"synthetic-private-marker": 1}, {"EMPTY_SQL": 0},
                        {"EMPTY_SQL": True}, {"EMPTY_SQL": -1}, {"EMPTY_SQL": 2}):
            with self.subTest(value=invalid):
                self.write(HEAD, snapshot(entry(unavailable=1, shapes=[], unavailable_reasons=invalid)))
                self.assert_invalid()

    def test_json_and_markdown_sort_independent_of_input_order(self):
        jdbc = entry(test_ids=[TEST_2, TEST_1], observed=2, shapes=[FINGERPRINT_2, FINGERPRINT_1])
        mybatis = entry(framework="MYBATIS", test_ids=[TEST_3])
        self.write(HEAD, snapshot(mybatis, jdbc))
        json_result = self.invoke()
        markdown_result = self.invoke("--format", "markdown")
        self.assertIn("`OBSERVE_ID` identifies a fallback observation bucket", markdown_result[1])
        self.assertIn(TEST_1, markdown_result[1])
        self.assertIn("SQL removal and semantic equivalence require separate evidence", markdown_result[1])
        self.write(HEAD, snapshot({**jdbc, "test_ids": [TEST_1, TEST_2],
                                   "shapes": [FINGERPRINT_1, FINGERPRINT_2]}, mybatis))
        self.assertEqual(self.invoke(), json_result)
        self.assertEqual(self.invoke("--format", "markdown"), markdown_result)

    def test_snapshot_shape_and_bounds(self):
        for invalid in (
            snapshot(schema_version=True), snapshot(schema_version=3),
            snapshot(revision="a" * 41), snapshot(revision="A" * 40),
            snapshot(dropped=-1), snapshot(dropped=True), snapshot(dropped=inventory.MAX_COUNT + 1),
            snapshot(profile="f" * 63), snapshot(entries={}), snapshot(entries=[entry()] * 129),
            snapshot(entry(), entry()), snapshot(unknown_field="synthetic-input-marker"),
        ):
            with self.subTest(invalid=list(invalid)):
                self.write(HEAD, invalid)
                self.assert_invalid()

    def test_entry_and_shape_validation(self):
        for invalid in (
            entry(declared=1), entry(observed=True), entry(unavailable=True), entry(unavailable=2),
            entry(observed=inventory.MAX_COUNT + 1), entry(observed=0), entry(shapes=[]),
            entry(declared=False, observed=0, test_ids=[], shapes=[]), entry(declared=False, test_ids=[TEST_1, TEST_2]),
            entry(query_id_hash="G" * 64), entry(framework="SQL"), entry(identity="SCOPE"),
            entry(identity="OBSERVE_ID"), entry(identity="OBSERVE_ID", declared=False),
            entry(test_ids=[TEST_1, TEST_1]), entry(test_ids=[f"{number:064x}" for number in range(9)]),
            entry(observed=2, shapes=[FINGERPRINT_1, FINGERPRINT_1]),
            entry(observed=9, shapes=[{**FINGERPRINT_1, "fingerprint_hash": f"{number:064x}"}
                                      for number in range(9)]),
            entry(shapes=[{**FINGERPRINT_1, "statement_kind": "SELECT <synthetic-input-marker>"}]),
            entry(shapes=[{**FINGERPRINT_1, "sql": "synthetic-input-marker"}]),
        ):
            with self.subTest(invalid=invalid):
                self.write(HEAD, snapshot(invalid))
                self.assert_invalid()

    def test_v2_reader_preserves_bounded_observed_test_ids(self):
        tests = [f"{number:064x}" for number in reversed(range(8))]
        self.write(HEAD, snapshot(
            entry(observed=8, test_ids=sorted(tests), shapes=[{**FINGERPRINT_1, "test_ids": tests}]),
            entry(identity="OBSERVE_ID", declared=False, test_ids=[], shapes=[{**FINGERPRINT_1, "test_ids": []}]),
            schema_version=2,
        ))
        parsed = inventory.read_snapshot(inventory.path_parts(HEAD))
        self.assertEqual(parsed["schema_version"], 2)
        scoped = parsed["entries"]["JDBC", "SCOPED", "0" * 64]
        self.assertEqual(scoped["shapes"][0]["test_ids"], tests)
        fallback = parsed["entries"]["JDBC", "OBSERVE_ID", "0" * 64]
        self.assertEqual(fallback["shapes"][0]["test_ids"], [])

    def test_shape_fields_are_exact_for_each_version(self):
        with_tests = {**FINGERPRINT_1, "test_ids": [TEST_1]}
        for version, shape in ((1, with_tests), (2, FINGERPRINT_1), (2, {**with_tests, "unknown_field": ""})):
            with self.subTest(version=version, shape=shape):
                self.write(HEAD, snapshot(entry(shapes=[shape]), schema_version=version))
                self.assert_invalid()

    def test_v2_observed_test_validation(self):
        for tests in (None, TEST_1, [[TEST_1]], [TEST_1, TEST_1], [TEST_2],
                      ["G" * 64], [f"{number:064x}" for number in range(9)]):
            with self.subTest(tests=tests):
                self.write(HEAD, snapshot(entry(shapes=[{**FINGERPRINT_1, "test_ids": tests}]), schema_version=2))
                self.assert_invalid()

        self.write(HEAD, snapshot(entry(identity="OBSERVE_ID", declared=False, test_ids=[],
                                        shapes=[{**FINGERPRINT_1, "test_ids": [TEST_1]}]), schema_version=2))
        self.assert_invalid()

    def test_v2_observed_test_pairs_require_available_events(self):
        for second_shape_tests in ([], [TEST_1]):
            with self.subTest(second_shape_tests=second_shape_tests):
                self.write(HEAD, snapshot(entry(observed=3, unavailable=1, test_ids=[TEST_1, TEST_2], shapes=[
                    {**FINGERPRINT_1, "test_ids": [TEST_1, TEST_2]},
                    {**FINGERPRINT_2, "test_ids": second_shape_tests},
                ]), schema_version=2))
                self.assert_invalid()

    def test_malformed_json_is_sanitized(self):
        valid = json.dumps(snapshot()).encode("utf-8")
        for raw in (
            b"synthetic-input-marker\xff", valid[:-1], valid + valid, b"[" * 1500,
            valid.replace(b'"dropped": 0', b'"dropped": 0, "dropped": 1'),
            valid.replace(b'"dropped": 0', b'"dropped": NaN'),
            valid.replace(b'"dropped": 0', b'"dropped": 0.0'),
            valid.replace(b'"dropped": 0', b'"dropped": 1000000000000'),
        ):
            Path(HEAD).write_bytes(raw)
            self.assert_invalid()

    def test_argument_and_path_validation_precede_reading(self):
        with patch.object(inventory, "read_bytes") as read_bytes:
            for path in (
                str(Path(HEAD).absolute()), "./" + HEAD, "../" + HEAD, "inventory//" + HEAD,
                "inventory/../" + HEAD, ".git/" + HEAD, "private/" + HEAD, "workspace.env.bak/" + HEAD,
                "custom.deploy.localenv/" + HEAD, "secret.key/" + HEAD, "synthetic-input-marker.json",
                "inventory\\head\\SQL-INVENTORY.json", HEAD + "\u0000", "a" * 255 + "/" + HEAD,
            ):
                with self.subTest(path=path):
                    self.assert_invalid(head=path)
            self.assert_invalid("--format", "synthetic-input-marker")
            self.assert_invalid("--synthetic-input-marker")
            read_bytes.assert_not_called()

    def test_links_fifo_and_oversize_are_rejected_before_read(self):
        path = Path(HEAD)
        path.unlink()
        path.symlink_to(Path(BASE).absolute())
        self.assert_invalid()
        path.unlink()
        self.write(HEAD, snapshot())
        os.link(HEAD, "inventory/hardlink")
        self.assert_invalid()
        Path("inventory/hardlink").unlink()
        path.unlink()
        os.mkfifo(HEAD)
        self.assert_invalid()
        path.unlink()
        with path.open("wb") as stream:
            stream.truncate(inventory.MAX_BYTES + 1)
        self.assert_invalid()
        raw = json.dumps(snapshot()).encode("utf-8")
        path.write_bytes(raw.ljust(inventory.MAX_BYTES, b" "))
        self.assertEqual(self.report()["queries"], [])
        directory = Path("inventory/linked")
        directory.symlink_to(Path(BASE).parent.absolute(), target_is_directory=True)
        self.assert_invalid(head=str(directory / inventory.FILENAME))


if __name__ == "__main__":
    unittest.main()
