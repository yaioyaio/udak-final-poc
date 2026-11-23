#!/usr/bin/env python3
"""Verify schema impact reporting with synthetic metadata."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("schema_impact", Path(__file__).with_name("schema-impact.py"))
impact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(impact)

BASE = "input/base/SCHEMA-SNAPSHOT.json"
HEAD = "input/head/SCHEMA-SNAPSHOT.json"
INVENTORY = "input/head/SQL-INVENTORY.json"
DEPENDENCIES = "input/head/QUERY-DEPENDENCIES.json"
BASE_REVISION = "a" * 40
HEAD_REVISION = "b" * 64
SCOPE = "c" * 64
QUERY = "d" * 64
FINGERPRINT_1, FINGERPRINT_2, UNKNOWN_FINGERPRINT = "e" * 64, "f" * 64, "0" * 64
TEST_1, TEST_2 = "1" * 64, "2" * 64
FOREIGN_TEST = "3" * 64
ERROR = "ERROR: invalid schema impact input or arguments\n"


def schema(revision, *columns, **extra):
    return {"schema_version": 1, "revision": revision, "scope": SCOPE, "columns": list(columns), **extra}


def column(name="label", table="items", kind="VARCHAR", width=32, nullable=False):
    return {"table": table, "column": name, "type": kind, "width": width, "nullable": nullable}


def shape(fingerprint, test_ids=None):
    row = {"fingerprint_hash": fingerprint, "statement_kind": "SELECT"}
    if test_ids is not None:
        row["test_ids"] = test_ids
    return row


def entry(query=QUERY, **extra):
    return {
        "framework": "JDBC", "identity": "SCOPED", "query_id_hash": query, "declared": True,
        "observed": 1, "unavailable": 0, "test_ids": [TEST_1],
        "shapes": [shape(FINGERPRINT_1)], **extra,
    }


def snapshot(*entries, **extra):
    return {"schema_version": 1, "revision": HEAD_REVISION, "profile": SCOPE,
            "dropped": 0, "entries": list(entries), **extra}


def ref(name="label", table="items"):
    return {"table": table, "column": name}


def dependency(*refs, query=QUERY, framework="JDBC"):
    return {"framework": framework, "query_id_hash": query, "columns": list(refs)}


def fingerprint_dependency(fingerprint, test_ids, *refs, **query):
    return {**dependency(*refs, **query), "fingerprint_hash": fingerprint, "test_ids": test_ids}


def manifest(*dependencies, **extra):
    return {"schema_version": 1, "revision": HEAD_REVISION, "scope": SCOPE,
            "dependencies": list(dependencies), **extra}


@unittest.skipUnless(os.name == "posix", "descriptor-relative input reads require POSIX")
class SchemaImpactTest(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(workspace.name)
        Path(BASE).parent.mkdir(parents=True)
        Path(HEAD).parent.mkdir(parents=True)
        self.write(BASE, schema(BASE_REVISION, column()))
        self.write(HEAD, schema(HEAD_REVISION, column(width=64)))
        self.write(INVENTORY, snapshot(entry()))
        self.write(DEPENDENCIES, manifest(dependency(ref())))

    def write(self, path, value):
        Path(path).write_text(json.dumps(value), encoding="utf-8")

    def invoke(self, *flags, **paths):
        options = {"base": BASE, "head": HEAD, "inventory": INVENTORY, "dependencies": DEPENDENCIES, **paths}
        argv = [argument for name, path in options.items() for argument in (f"--{name}", path)]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = impact.main([*argv, *flags])
        return status, out.getvalue(), err.getvalue()

    def report(self, exit_code=0):
        status, output, error = self.invoke()
        self.assertEqual((status, error), (exit_code, ""))
        report = json.loads(output)
        self.assertEqual(report["status"], "COMPLETE" if exit_code == 0 else "INCOMPLETE")
        return report

    def assert_invalid(self, *flags, **paths):
        self.assertEqual(self.invoke(*flags, **paths), (1, "", ERROR))

    def write_fingerprint_fixture(self, *, inventory_version=1):
        self.write(BASE, schema(BASE_REVISION, column(), column("other_label")))
        self.write(HEAD, schema(HEAD_REVISION, column(width=64), column("other_label")))
        shapes = [shape(fingerprint, [test_id] if inventory_version == 2 else None)
                  for fingerprint, test_id in ((FINGERPRINT_1, TEST_1), (FINGERPRINT_2, TEST_2))]
        self.write(INVENTORY, snapshot(entry(
            observed=2, test_ids=[TEST_1, TEST_2], shapes=shapes,
        ), schema_version=inventory_version))

    def assert_unresolved_fingerprints(self, report, reasons, *issues):
        expected = {"framework": "JDBC", "identity": "SCOPED", "query_id_hash": QUERY, "reasons": reasons}
        if issues:
            expected["fingerprint_issues"] = [
                {"fingerprint_hash": fingerprint, "reasons": fingerprint_reasons}
                for fingerprint, fingerprint_reasons in issues
            ]
        self.assertEqual(report["unresolved_queries"], [expected])

    def test_v2_selects_only_tests_linked_to_the_changed_fingerprint(self):
        self.write(DEPENDENCIES, manifest(
            fingerprint_dependency(FINGERPRINT_1, [TEST_1], ref()),
            fingerprint_dependency(FINGERPRINT_2, [TEST_2], ref("other_label")),
            schema_version=2,
        ))
        for inventory_version in (1, 2):
            self.write_fingerprint_fixture(inventory_version=inventory_version)
            for changed_name, test_id in (("label", TEST_1), ("other_label", TEST_2)):
                with self.subTest(inventory_version=inventory_version, column=changed_name):
                    self.write(HEAD, schema(HEAD_REVISION, *(
                        column(name, width=64 if name == changed_name else 32)
                        for name in ("label", "other_label")
                    )))
                    report = self.report()
                    self.assertEqual(report["schema_version"], 1)
                    self.assertEqual(report["affected_queries"], [
                        {"framework": "JDBC", "query_id_hash": QUERY, "test_ids": [test_id]},
                    ])
                    self.assertEqual(report["impacted_test_ids"], [test_id])
                    self.assertEqual(report["unresolved_queries"], [])

    def test_v2_inventory_rejects_swapped_test_links_under_the_same_query(self):
        self.write_fingerprint_fixture(inventory_version=2)
        self.write(DEPENDENCIES, manifest(
            fingerprint_dependency(FINGERPRINT_1, [TEST_2], ref()),
            fingerprint_dependency(FINGERPRINT_2, [TEST_1], ref("other_label")),
            schema_version=2,
        ))
        report = self.report(2)
        self.assertEqual(report["affected_queries"], [
            {"framework": "JDBC", "query_id_hash": QUERY, "test_ids": []},
        ])
        self.assertEqual(report["impacted_test_ids"], [])
        self.assert_unresolved_fingerprints(
            report, ["FINGERPRINT_TEST_MISMATCH", "UNMAPPED_TESTS"],
            (FINGERPRINT_1, ["FINGERPRINT_TEST_MISMATCH"]),
            (FINGERPRINT_2, ["FINGERPRINT_TEST_MISMATCH"]),
        )

        self.write(HEAD, schema(HEAD_REVISION, column(), column("other_label")))
        unchanged = self.report(2)
        self.assertEqual(unchanged["changes"], [])
        self.assertEqual(unchanged["affected_queries"], [])
        self.assertEqual(unchanged["impacted_test_ids"], [])
        self.assertEqual(unchanged["unresolved_queries"], report["unresolved_queries"])

    def test_v2_inventory_requires_every_observed_test_and_preserves_the_intersection(self):
        self.write_fingerprint_fixture(inventory_version=2)
        self.write(INVENTORY, snapshot(entry(
            observed=3, test_ids=[TEST_1, TEST_2],
            shapes=[shape(FINGERPRINT_1, [TEST_1, TEST_2]), shape(FINGERPRINT_2, [TEST_2])],
        ), schema_version=2))
        for tests, issues, impacted in (
            ([TEST_1], ["FINGERPRINT_TEST_MISMATCH"], [TEST_1]),
            ([TEST_1, FOREIGN_TEST], ["FINGERPRINT_TEST_MISMATCH", "UNKNOWN_TEST"], [TEST_1]),
            ([], ["FINGERPRINT_TEST_MISMATCH", "MISSING_FINGERPRINT_TESTS"], []),
        ):
            with self.subTest(tests=tests):
                self.write(DEPENDENCIES, manifest(
                    fingerprint_dependency(FINGERPRINT_1, tests, ref()),
                    fingerprint_dependency(FINGERPRINT_2, [TEST_2], ref("other_label")),
                    schema_version=2,
                ))
                report = self.report(2)
                self.assertEqual(report["affected_queries"], [
                    {"framework": "JDBC", "query_id_hash": QUERY, "test_ids": impacted},
                ])
                self.assertEqual(report["impacted_test_ids"], impacted)
                self.assert_unresolved_fingerprints(report, sorted([*issues, "UNMAPPED_TESTS"]),
                                                    (FINGERPRINT_1, issues))

    def test_v2_inventory_aggregate_tests_do_not_establish_shape_links(self):
        for unavailable in (0, 1):
            with self.subTest(unavailable=unavailable):
                self.write(INVENTORY, snapshot(entry(
                    observed=1 + unavailable, unavailable=unavailable,
                    shapes=[shape(FINGERPRINT_1, [])],
                ), schema_version=2))
                self.write(DEPENDENCIES, manifest(
                    fingerprint_dependency(FINGERPRINT_1, [TEST_1], ref()), schema_version=2,
                ))
                report = self.report(2)
                self.assertEqual(report["affected_queries"], [
                    {"framework": "JDBC", "query_id_hash": QUERY, "test_ids": []},
                ])
                self.assertEqual(report["impacted_test_ids"], [])
                reasons = ["FINGERPRINT_TEST_MISMATCH", "UNMAPPED_TESTS"]
                if unavailable:
                    reasons.insert(1, "UNAVAILABLE_OBSERVATIONS")
                self.assert_unresolved_fingerprints(report, reasons,
                                                    (FINGERPRINT_1, ["FINGERPRINT_TEST_MISMATCH"]))

    def test_v2_inventory_unscoped_shape_cannot_be_mapped_to_a_scoped_dependency(self):
        self.write(INVENTORY, snapshot(entry(identity="OBSERVE_ID", declared=False, test_ids=[],
                                             shapes=[shape(FINGERPRINT_1, [])]), schema_version=2))
        self.write(DEPENDENCIES, manifest(
            fingerprint_dependency(FINGERPRINT_1, [TEST_1], ref()), schema_version=2,
        ))
        report = self.report(2)
        self.assertEqual(report["impacted_test_ids"], [])
        self.assertEqual(report["affected_queries"], [])
        self.assertEqual(report["unresolved_queries"], [
            {"framework": "JDBC", "identity": "OBSERVE_ID", "query_id_hash": QUERY,
             "reasons": ["OBSERVE_ID"]},
            {"framework": "JDBC", "identity": "SCOPED", "query_id_hash": QUERY,
             "reasons": ["UNKNOWN_QUERY"]},
        ])

    def test_v2_missing_fingerprint_preserves_known_impact(self):
        self.write_fingerprint_fixture(inventory_version=2)
        self.write(DEPENDENCIES, manifest(fingerprint_dependency(FINGERPRINT_1, [TEST_1], ref()),
                                          schema_version=2))
        report = self.report(2)
        self.assertEqual(report["affected_queries"], [
            {"framework": "JDBC", "query_id_hash": QUERY, "test_ids": [TEST_1]},
        ])
        self.assertEqual(report["impacted_test_ids"], [TEST_1])
        self.assert_unresolved_fingerprints(report, ["MISSING_FINGERPRINT_DEPENDENCIES", "UNMAPPED_TESTS"],
                                            (FINGERPRINT_2, ["MISSING_FINGERPRINT_DEPENDENCIES"]))

        self.write(HEAD, schema(HEAD_REVISION, column(), column("other_label")))
        unchanged = self.report(2)
        self.assertEqual(unchanged["changes"], [])
        self.assertEqual(unchanged["affected_queries"], [])
        self.assertEqual(unchanged["impacted_test_ids"], [])
        self.assertEqual(unchanged["unresolved_queries"], report["unresolved_queries"])

    def test_v2_absent_rows_report_every_observed_fingerprint_in_hash_order(self):
        self.write_fingerprint_fixture()
        self.write(INVENTORY, snapshot(entry(
            observed=2, test_ids=[TEST_2, TEST_1], shapes=[shape(FINGERPRINT_2), shape(FINGERPRINT_1)],
        )))
        self.write(DEPENDENCIES, manifest(schema_version=2))
        report = self.report(2)
        self.assertEqual(report["affected_queries"], [])
        self.assertEqual(report["impacted_test_ids"], [])
        self.assert_unresolved_fingerprints(
            report, ["MISSING_FINGERPRINT_DEPENDENCIES", "UNMAPPED_TESTS"],
            (FINGERPRINT_1, ["MISSING_FINGERPRINT_DEPENDENCIES"]),
            (FINGERPRINT_2, ["MISSING_FINGERPRINT_DEPENDENCIES"]),
        )

    def test_v2_unknown_fingerprint_cannot_supply_dependencies_or_test_coverage(self):
        self.write_fingerprint_fixture()
        self.write(DEPENDENCIES, manifest(
            fingerprint_dependency(FINGERPRINT_1, [TEST_1], ref("other_label")),
            fingerprint_dependency(FINGERPRINT_2, [], ref("other_label")),
            fingerprint_dependency(UNKNOWN_FINGERPRINT, [TEST_2], ref()),
            schema_version=2,
        ))
        report = self.report(2)
        self.assertEqual(report["affected_queries"], [])
        self.assertEqual(report["impacted_test_ids"], [])
        self.assert_unresolved_fingerprints(
            report, ["MISSING_FINGERPRINT_TESTS", "UNKNOWN_FINGERPRINT", "UNMAPPED_TESTS"],
            (UNKNOWN_FINGERPRINT, ["UNKNOWN_FINGERPRINT"]),
            (FINGERPRINT_2, ["MISSING_FINGERPRINT_TESTS"]),
        )

    def test_v2_missing_or_foreign_test_links_preserve_known_tests(self):
        self.write_fingerprint_fixture()
        for test_ids, fingerprint_reason in (
            ([], "MISSING_FINGERPRINT_TESTS"),
            ([FOREIGN_TEST], "UNKNOWN_TEST"),
            ([TEST_1, FOREIGN_TEST], "UNKNOWN_TEST"),
        ):
            with self.subTest(test_ids=test_ids):
                self.write(DEPENDENCIES, manifest(
                    fingerprint_dependency(FINGERPRINT_1, test_ids, ref()),
                    fingerprint_dependency(FINGERPRINT_2, [TEST_2], ref("other_label")),
                    schema_version=2,
                ))
                report = self.report(2)
                known_tests = [TEST_1] if TEST_1 in test_ids else []
                self.assertEqual(report["affected_queries"], [
                    {"framework": "JDBC", "query_id_hash": QUERY, "test_ids": known_tests},
                ])
                self.assertEqual(report["impacted_test_ids"], known_tests)
                self.assert_unresolved_fingerprints(report, [fingerprint_reason, "UNMAPPED_TESTS"],
                                                    (FINGERPRINT_1, [fingerprint_reason]))

    def test_v2_incomplete_aggregate_test_coverage_preserves_known_tests(self):
        self.write_fingerprint_fixture()
        self.write(DEPENDENCIES, manifest(
            fingerprint_dependency(FINGERPRINT_1, [TEST_1], ref()),
            fingerprint_dependency(FINGERPRINT_2, [TEST_1], ref("other_label")),
            schema_version=2,
        ))
        report = self.report(2)
        self.assertEqual(report["impacted_test_ids"], [TEST_1])
        self.assert_unresolved_fingerprints(report, ["UNMAPPED_TESTS"])

    def test_v2_unknown_reference_preserves_known_column_impact(self):
        self.write_fingerprint_fixture()
        self.write(DEPENDENCIES, manifest(
            fingerprint_dependency(FINGERPRINT_1, [TEST_1], ref(), ref("unknown")),
            fingerprint_dependency(FINGERPRINT_2, [TEST_2], ref("other_label")),
            schema_version=2,
        ))
        report = self.report(2)
        self.assertEqual(report["impacted_test_ids"], [TEST_1])
        self.assert_unresolved_fingerprints(report, ["UNKNOWN_REFERENCE", "UNMAPPED_TESTS"],
                                            (FINGERPRINT_1, ["UNKNOWN_REFERENCE"]))

    def test_v2_empty_references_are_incomplete_without_selecting_their_tests(self):
        self.write_fingerprint_fixture()
        self.write(DEPENDENCIES, manifest(
            fingerprint_dependency(FINGERPRINT_1, [TEST_1]),
            fingerprint_dependency(FINGERPRINT_2, [TEST_2], ref("other_label")),
            schema_version=2,
        ))
        report = self.report(2)
        self.assertEqual(report["affected_queries"], [])
        self.assertEqual(report["impacted_test_ids"], [])
        self.assert_unresolved_fingerprints(report, ["MISSING_FINGERPRINT_DEPENDENCIES", "UNMAPPED_TESTS"],
                                            (FINGERPRINT_1, ["MISSING_FINGERPRINT_DEPENDENCIES"]))

    def test_v2_rows_cannot_supply_evidence_for_a_query_without_observed_fingerprints(self):
        self.write(INVENTORY, snapshot(entry(observed=0, shapes=[]), schema_version=2))
        self.write(DEPENDENCIES, manifest(fingerprint_dependency(FINGERPRINT_1, [TEST_1], ref()),
                                          schema_version=2))
        report = self.report(2)
        self.assertEqual(report["affected_queries"], [])
        self.assertEqual(report["impacted_test_ids"], [])
        self.assert_unresolved_fingerprints(
            report, ["MISSING_FINGERPRINT_DEPENDENCIES", "UNKNOWN_FINGERPRINT", "UNMAPPED_TESTS"],
            (FINGERPRINT_1, ["UNKNOWN_FINGERPRINT"]),
        )

    def test_v2_fingerprint_rows_are_scoped_to_framework_and_query_id(self):
        self.write_fingerprint_fixture()
        other_query = "4" * 64
        self.write(DEPENDENCIES, manifest(
            fingerprint_dependency(FINGERPRINT_1, [TEST_1], ref()),
            fingerprint_dependency(FINGERPRINT_2, [TEST_2], ref("other_label")),
            fingerprint_dependency(FINGERPRINT_2, [TEST_2], ref(), framework="JPA"),
            fingerprint_dependency(FINGERPRINT_2, [TEST_2], ref(), query=other_query),
            schema_version=2,
        ))
        report = self.report(2)
        self.assertEqual(report["impacted_test_ids"], [TEST_1])
        self.assertEqual(report["unresolved_queries"], [
            {"framework": "JDBC", "identity": "SCOPED", "query_id_hash": other_query,
             "reasons": ["UNKNOWN_QUERY"]},
            {"framework": "JPA", "identity": "SCOPED", "query_id_hash": QUERY, "reasons": ["UNKNOWN_QUERY"]},
        ])

    def test_v2_deduplicates_impacted_tests_and_orders_output_deterministically(self):
        self.write_fingerprint_fixture(inventory_version=2)
        self.write(HEAD, schema(HEAD_REVISION, column(width=64), column("other_label", width=64)))
        self.write(INVENTORY, snapshot(entry(
            observed=3, test_ids=[TEST_1, TEST_2],
            shapes=[shape(FINGERPRINT_1, [TEST_1, TEST_2]), shape(FINGERPRINT_2, [TEST_1])],
        ), schema_version=2))
        first = fingerprint_dependency(FINGERPRINT_1, [TEST_2, TEST_1], ref(), ref("other_label"))
        second = fingerprint_dependency(FINGERPRINT_2, [TEST_1], ref("other_label"))
        self.write(DEPENDENCIES, manifest(first, second, schema_version=2))
        report = self.report()
        self.assertEqual(report["affected_queries"], [
            {"framework": "JDBC", "query_id_hash": QUERY, "test_ids": [TEST_1, TEST_2]},
        ])
        self.assertEqual(report["impacted_test_ids"], [TEST_1, TEST_2])
        first["test_ids"].reverse()
        first["columns"].reverse()
        self.write(DEPENDENCIES, manifest(second, first, schema_version=2))
        self.assertEqual(self.report(), report)

    def test_v2_rejects_duplicate_or_malformed_fingerprint_rows(self):
        row = fingerprint_dependency(FINGERPRINT_1, [TEST_1], ref())
        for rows in (
            [row, fingerprint_dependency(FINGERPRINT_1, [TEST_2], ref("other_label"))],
            [dependency(ref())],
            [{key: value for key, value in row.items() if key != "fingerprint_hash"}],
            [{key: value for key, value in row.items() if key != "test_ids"}],
            [{**row, "fingerprint_hash": FINGERPRINT_1.upper()}],
            [{**row, "fingerprint_hash": [FINGERPRINT_1]}],
            [{**row, "test_ids": TEST_1}],
            [{**row, "test_ids": ["synthetic-marker"]}],
            [{**row, "test_ids": [TEST_1, TEST_1]}],
            [{**row, "test_ids": [TEST_1] * (impact.inventory.MAX_REFERENCES + 1)}],
            [{**row, "columns": [ref(), ref()]}],
            [{**row, "extra": "synthetic-marker"}],
        ):
            self.write(DEPENDENCIES, manifest(*rows, schema_version=2))
            self.assert_invalid()

    def test_v1_multiple_fingerprints_are_conservatively_incomplete(self):
        self.write(DEPENDENCIES, manifest(dependency(ref())))
        for inventory_version in (1, 2):
            with self.subTest(inventory_version=inventory_version):
                self.write_fingerprint_fixture(inventory_version=inventory_version)
                report = self.report(2)
                self.assertEqual(report["affected_queries"], [
                    {"framework": "JDBC", "query_id_hash": QUERY, "test_ids": [TEST_1, TEST_2]},
                ])
                self.assertEqual(report["impacted_test_ids"], [TEST_1, TEST_2])
                self.assert_unresolved_fingerprints(report, ["MISSING_FINGERPRINT_DEPENDENCIES"])

    def test_same_revision_in_a_different_inventory_scope_is_rejected(self):
        self.write(INVENTORY, snapshot(entry(), profile="f" * 64))
        self.assert_invalid()

    def test_changed_schema_with_an_empty_inventory_is_incomplete(self):
        self.write(INVENTORY, snapshot())
        self.write(DEPENDENCIES, manifest())
        report = self.report(2)
        self.assertEqual(report["coverage_reasons"], ["EMPTY_INVENTORY"])
        self.assertEqual(report["affected_queries"], [])

    def test_reports_all_structural_changes_with_before_and_after_metadata(self):
        self.write(BASE, schema(BASE_REVISION, column(), column("count", kind="INTEGER", width=0),
                                column("legacy"), column("value", "other")))
        self.write(HEAD, schema(HEAD_REVISION, column("note"), column(width=64, nullable=True),
                                column("value", "other"), column("count", kind="BIGINT", width=0)))
        report = self.report()
        self.assertEqual([(row["column"], row["kind"]) for row in report["changes"]], [
            ("count", "TYPE"), ("label", "WIDTH"), ("label", "NULLABILITY"),
            ("legacy", "REMOVED"), ("note", "ADDED"),
        ])
        self.assertEqual(report["changes"][1], {
            "table": "items", "column": "label", "kind": "WIDTH",
            "before": {"type": "VARCHAR", "width": 32, "nullable": False},
            "after": {"type": "VARCHAR", "width": 64, "nullable": True},
        })
        self.assertIsNone(report["changes"][3]["after"])
        self.assertIsNone(report["changes"][4]["before"])
        self.assertEqual((report["base_revision"], report["head_revision"], report["scope"]),
                         (BASE_REVISION, HEAD_REVISION, SCOPE))
        self.assertEqual(report["affected_queries"], [
            {"framework": "JDBC", "query_id_hash": QUERY, "test_ids": [TEST_1]},
        ])
        self.assertEqual(report["impacted_test_ids"], [TEST_1])
        self.assertEqual(report["unresolved_queries"], [])

    def test_joins_scoped_queries_by_framework_and_keeps_only_impacted_tests(self):
        self.write(BASE, schema(BASE_REVISION, column(), column("value", "other")))
        self.write(HEAD, schema(HEAD_REVISION, column(width=64), column("value", "other")))
        self.write(INVENTORY, snapshot(entry(framework="JPA", test_ids=[TEST_2]), entry(),
                                       entry(framework="MYBATIS", test_ids=[TEST_2])))
        self.write(DEPENDENCIES, manifest(dependency(ref("value", "other"), framework="JPA"),
                                          dependency(ref("*")), dependency(ref(), framework="MYBATIS")))
        report = self.report()
        self.assertEqual(report["affected_queries"], [
            {"framework": "JDBC", "query_id_hash": QUERY, "test_ids": [TEST_1]},
            {"framework": "MYBATIS", "query_id_hash": QUERY, "test_ids": [TEST_2]},
        ])
        self.assertEqual(report["impacted_test_ids"], [TEST_1, TEST_2])
        self.assertEqual(report["unresolved_queries"], [])

    def test_wildcards_on_added_and_removed_tables_and_exact_removed_columns(self):
        self.write(BASE, schema(BASE_REVISION, column(), column(table="removed")))
        self.write(HEAD, schema(HEAD_REVISION, column(), column(table="added")))
        self.write(INVENTORY, snapshot(entry(), entry(framework="JPA"), entry(framework="MYBATIS")))
        self.write(DEPENDENCIES, manifest(dependency(ref("*", "added")),
                                          dependency(ref("*", "removed"), framework="JPA"),
                                          dependency(ref(table="removed"), framework="MYBATIS")))
        report = self.report()
        self.assertEqual([row["framework"] for row in report["affected_queries"]], ["JDBC", "JPA", "MYBATIS"])
        self.assertEqual(report["impacted_test_ids"], [TEST_1])

    def test_no_change_and_known_unaffected_produce_no_impacted_tests(self):
        self.write(HEAD, schema(HEAD_REVISION, column()))
        report = self.report()
        self.assertEqual(report["changes"], [])
        self.assertEqual(report["affected_queries"], [])
        self.assertEqual(report["impacted_test_ids"], [])

    def test_unresolved_dependencies_during_a_no_change_comparison(self):
        self.write(HEAD, schema(HEAD_REVISION, column()))
        self.write(INVENTORY, snapshot(entry(), entry(framework="JPA"), entry(framework="MYBATIS")))
        self.write(DEPENDENCIES, manifest(dependency(), dependency(ref("*", "unknown"), framework="JPA")))
        report = self.report(2)
        self.assertEqual(report["changes"], [])
        self.assertEqual(report["affected_queries"], [])
        self.assertEqual([(row["framework"], row["reasons"]) for row in report["unresolved_queries"]], [
            ("JDBC", ["MISSING_DEPENDENCIES"]), ("JPA", ["UNKNOWN_REFERENCE"]),
            ("MYBATIS", ["MISSING_DEPENDENCIES"]),
        ])

    def test_incomplete_metadata_preserves_known_affected_queries_and_tests(self):
        self.write(INVENTORY, snapshot(entry(test_ids=[]), entry(framework="JPA", unavailable=1, shapes=[]),
                                       entry(framework="MYBATIS", identity="OBSERVE_ID", declared=False, test_ids=[]),
                                       dropped=2))
        self.write(DEPENDENCIES, manifest(dependency(ref()), dependency(ref(), ref("unknown"), framework="JPA"),
                                          dependency(ref(), framework="MYBATIS")))
        report = self.report(2)
        self.assertEqual(report["inventory_dropped"], 2)
        self.assertEqual(report["affected_queries"], [
            {"framework": "JDBC", "query_id_hash": QUERY, "test_ids": []},
            {"framework": "JPA", "query_id_hash": QUERY, "test_ids": [TEST_1]},
        ])
        self.assertEqual(report["impacted_test_ids"], [TEST_1])
        self.assertEqual([(row["framework"], row["identity"], row["reasons"])
                          for row in report["unresolved_queries"]], [
            ("JDBC", "SCOPED", ["MISSING_TESTS"]),
            ("JPA", "SCOPED", ["UNAVAILABLE_OBSERVATIONS", "UNKNOWN_REFERENCE"]),
            ("MYBATIS", "OBSERVE_ID", ["OBSERVE_ID"]), ("MYBATIS", "SCOPED", ["UNKNOWN_QUERY"]),
        ])

    def test_dropped_inventory_alone_marks_report_incomplete(self):
        self.write(INVENTORY, snapshot(entry(), dropped=1))
        report = self.report(2)
        self.assertEqual(report["inventory_dropped"], 1)
        self.assertEqual(report["unresolved_queries"], [])

    def test_output_is_independent_of_row_reference_and_test_order(self):
        first, second = column(), column("same", "other")
        entries = [entry(observed=2, test_ids=[TEST_2, TEST_1]), entry(framework="JPA")]
        dependencies = [dependency(ref(), ref("same", "other")), dependency(ref(), framework="JPA")]
        self.write(BASE, schema(BASE_REVISION, first, second))
        self.write(HEAD, schema(HEAD_REVISION, {**first, "width": 64}, second))
        self.write(INVENTORY, snapshot(*entries))
        self.write(DEPENDENCIES, manifest(*dependencies))
        before = self.invoke()
        self.assertEqual(before[0], 0)
        entries[0]["test_ids"].reverse()
        dependencies[0]["columns"].reverse()
        self.write(BASE, schema(BASE_REVISION, second, first))
        self.write(HEAD, schema(HEAD_REVISION, second, {**first, "width": 64}))
        self.write(INVENTORY, snapshot(*reversed(entries)))
        self.write(DEPENDENCIES, manifest(*reversed(dependencies)))
        self.assertEqual(self.invoke(), before)

    def test_rejects_inconsistent_revisions_and_scopes(self):
        for path, contents in (
            (BASE, schema(HEAD_REVISION, column())),
            (BASE, schema(BASE_REVISION, column(), scope="0" * 64)),
            (INVENTORY, snapshot(entry(), revision=BASE_REVISION)),
            (DEPENDENCIES, manifest(dependency(ref()), revision=BASE_REVISION)),
            (DEPENDENCIES, manifest(dependency(ref()), scope="0" * 64)),
        ):
            with self.subTest(path=path):
                original = Path(path).read_bytes()
                self.write(path, contents)
                self.assert_invalid()
                Path(path).write_bytes(original)

    def test_rejects_invalid_schema_shapes_values_and_duplicates(self):
        for invalid in (
            schema(HEAD_REVISION, column(), column()), schema(HEAD_REVISION, schema_version=True),
            schema(HEAD_REVISION, columns={}), schema(HEAD_REVISION, column("A")),
            schema(HEAD_REVISION, column("a" * 64)), schema(HEAD_REVISION, column("*")),
            schema(HEAD_REVISION, column(kind="UNKNOWN")), schema(HEAD_REVISION, column(kind="INTEGER")),
            schema(HEAD_REVISION, column(width=0)), schema(HEAD_REVISION, column(width=True)),
            schema(HEAD_REVISION, column(width=-1)), schema(HEAD_REVISION, column(width=impact.MAX_WIDTH + 1)),
            schema(HEAD_REVISION, column(nullable=1)), schema(HEAD_REVISION, **{"marker": "private"}),
            schema(HEAD_REVISION, {**column(), "data": "synthetic-marker"}),
            schema(HEAD_REVISION, columns=[column()] * (impact.MAX_COLUMNS + 1)),
        ):
            with self.subTest(fields=invalid.keys()):
                self.write(HEAD, invalid)
                self.assert_invalid()

    def test_rejects_invalid_dependency_shapes_values_and_duplicates(self):
        for invalid in (
            manifest(dependency(ref()), dependency(ref())), manifest(dependency(ref(), ref())),
            manifest(dependency(ref("*", "*"))), manifest(dependency(ref("unknown column"))),
            manifest(dependency(ref(), framework="OTHER")), manifest(dependency(ref(), query="not-a-hash")),
            manifest(dependency({**ref(), "sql": "synthetic-marker"})),
            manifest(dependency(*([ref()] * (impact.MAX_QUERY_COLUMNS + 1)))),
            manifest(*([dependency(ref())] * (impact.inventory.MAX_ENTRIES + 1))),
        ):
            self.write(DEPENDENCIES, invalid)
            self.assert_invalid()

    def test_inherits_inventory_validation_and_keeps_errors_generic(self):
        for invalid in (
            snapshot(entry(test_ids=[TEST_1, TEST_1])), snapshot(entry(), entry()),
            snapshot(entry(test_ids=["synthetic-marker"])), snapshot(entry(sql="synthetic-marker")),
        ):
            self.write(INVENTORY, invalid)
            self.assert_invalid()

    def test_rejects_malformed_json_and_disallowed_number_forms(self):
        valid = Path(HEAD).read_bytes()
        for raw in (
            b"synthetic-marker\xff", valid[:-1], valid + valid, b"[" * 1500,
            valid.replace(b'"width": 64', b'"width": 32, "width": 64'),
            valid.replace(b'"width": 64', b'"width": 64.0'),
            valid.replace(b'"width": 64', b'"width": NaN'),
            valid.replace(b'"width": 64', b'"width": 10000000000000'),
        ):
            Path(HEAD).write_bytes(raw)
            self.assert_invalid()

    def test_validates_paths_and_arguments_before_loading_any_metadata(self):
        with patch.object(impact.inventory, "read_bytes") as reader:
            for path in (
                "/absolute/SCHEMA-SNAPSHOT.json", "../SCHEMA-SNAPSHOT.json", "./SCHEMA-SNAPSHOT.json",
                "secrets/SCHEMA-SNAPSHOT.json", "image-pins.local.env/SCHEMA-SNAPSHOT.json",
                "workspace.env.bak/SCHEMA-SNAPSHOT.json", "service.deploy.localenv/SCHEMA-SNAPSHOT.json",
                "staging//SCHEMA-SNAPSHOT.json", "config.key/SCHEMA-SNAPSHOT.json",
                "input/SCHEMA-SNAPSHOT.json\0", "input/synthetic-marker", "a" * 255 + "/SCHEMA-SNAPSHOT.json",
            ):
                self.assert_invalid(head=path)
            self.assert_invalid(dependencies=HEAD)
            self.assert_invalid(inventory=DEPENDENCIES)
            self.assert_invalid("--synthetic-marker")
            self.assert_invalid("--he", HEAD)
            reader.assert_not_called()

    def test_rejects_links_fifos_and_oversize_files(self):
        path = Path(HEAD)
        original = path.read_bytes()
        path.unlink()
        path.symlink_to(Path(BASE).absolute())
        self.assert_invalid()
        path.unlink()
        path.write_bytes(original)
        link = Path("input/link")
        os.link(HEAD, link)
        self.assert_invalid()
        link.unlink()
        path.unlink()
        os.mkfifo(path)
        self.assert_invalid()
        path.unlink()
        with path.open("wb") as stream:
            stream.truncate(impact.inventory.MAX_BYTES + 1)
        self.assert_invalid()
        path.write_bytes(original.ljust(impact.inventory.MAX_BYTES, b" "))
        self.report()
        link.symlink_to(Path(HEAD).parent.absolute(), target_is_directory=True)
        self.assert_invalid(head=str(link / impact.SCHEMA_FILENAME))


if __name__ == "__main__":
    unittest.main()
