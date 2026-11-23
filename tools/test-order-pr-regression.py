#!/usr/bin/env python3
"""Verify order PR regression mapping against reports from the inventory comparator."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
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
TOOLS = Path(__file__).resolve().parent
REPORT = "inventory/SQL-INVENTORY-REPORT.json"
GENERIC_ERROR = "ERROR: invalid order PR regression input or arguments\n"


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), TOOLS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inventory = load_tool("sql-inventory")
registry = load_tool("order-pr-regression")


def inventory_hash(kind, name):
    return hashlib.sha256(f"udak-inventory-{kind}-id-v1\0{name}".encode("utf-8")).hexdigest()


PLACEMENT = inventory_hash("test", "case.order.place")
STOCK_ON = inventory_hash("test", "case.order.stock-on")
STOCK_OFF = inventory_hash("test", "case.order.stock-off")
UNKNOWN = inventory_hash("test", "case.order.synthetic-unknown")
SECOND_UNKNOWN = inventory_hash("test", "case.order.synthetic-unregistered")
PLACEMENT_MATCH = {"test_id_hash": PLACEMENT, "entry_point": "ORDER_PLACEMENT_RELATED"}
STOCK_ON_MATCH = {"test_id_hash": STOCK_ON, "entry_point": "ORDER_STOCK_ON_RELATED"}
STOCK_OFF_MATCH = {"test_id_hash": STOCK_OFF, "entry_point": "ORDER_STOCK_OFF_RELATED"}


def query(index, fingerprint, tests, version):
    shape = {"fingerprint_hash": fingerprint, "statement_kind": "UPDATE"}
    if version == 2:
        shape["test_ids"] = list(tests)
    return {
        "framework": "MYBATIS",
        "identity": "SCOPED",
        "query_id_hash": inventory_hash("query", f"order.synthetic.{index}"),
        "declared": True,
        "observed": max(1, len(tests)),
        "unavailable": 0,
        "test_ids": list(tests),
        "shapes": [shape],
    }


@unittest.skipUnless(os.name == "posix", "descriptor-relative report reads require POSIX")
class OrderPrRegressionTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(directory.name)
        Path(REPORT).parent.mkdir()

    def report(self, *test_groups, changed=True, versions=(2, 2), dropped=0):
        snapshots = []
        for side, version in enumerate(versions):
            path = f"inventory/{side}/{inventory.FILENAME}"
            Path(path).parent.mkdir(exist_ok=True)
            revision = ("a", "b")[side]
            fingerprint = "d" * 64 if side and changed else "c" * 64
            snapshot = {
                "schema_version": version,
                "revision": revision * 40,
                "profile": "f" * 64,
                "dropped": dropped if side else 0,
                "entries": [query(index, fingerprint, tests, version) for index, tests in enumerate(test_groups)],
            }
            Path(path).write_text(json.dumps(snapshot), encoding="utf-8")
            snapshots.append(inventory.read_snapshot(inventory.path_parts(path)))
        return inventory.compare_snapshots(*snapshots)

    def write(self, report):
        Path(REPORT).write_text(json.dumps(report), encoding="utf-8")

    def invoke(self, *args, path=REPORT):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            with patch.object(subprocess, "Popen") as process, patch.object(os, "system") as shell:
                code = registry.main(["--report", path, *args])
        process.assert_not_called()
        shell.assert_not_called()
        return code, out.getvalue(), err.getvalue()

    def assert_mapping(self, report, status, *, matched=(), unknown=(), reasons=()):
        self.write(report)
        code, out, err = self.invoke()
        self.assertEqual((code, err), (2 if status == "REVIEW_REQUIRED" else 0, ""))
        self.assertEqual(json.loads(out), {
            "schema_version": 1,
            "status": status,
            "matched_tests": sorted(matched, key=lambda test: test["test_id_hash"]),
            "unknown_test_ids": sorted(unknown),
            "review_reasons": sorted(reasons),
        })
        self.assertEqual(json.loads(Path(REPORT).read_text(encoding="utf-8")), report)
        return out

    def assert_invalid(self, *args, path=REPORT):
        self.assertEqual(self.invoke(*args, path=path), (1, "", GENERIC_ERROR))

    def test_registered_tests_map_to_fixed_entry_points(self):
        for test, match in ((PLACEMENT, PLACEMENT_MATCH), (STOCK_ON, STOCK_ON_MATCH),
                            (STOCK_OFF, STOCK_OFF_MATCH)):
            with self.subTest(entry_point=match["entry_point"]):
                self.assert_mapping(self.report((test,)), "READY", matched=[match])

    def test_both_stock_branches_in_one_report_map_to_distinct_entry_points(self):
        self.assert_mapping(self.report((STOCK_ON, STOCK_OFF)), "READY",
                            matched=[STOCK_ON_MATCH, STOCK_OFF_MATCH])

    def test_unknown_and_known_hashes_are_retained_for_review(self):
        self.assert_mapping(self.report((UNKNOWN,)), "REVIEW_REQUIRED", unknown=[UNKNOWN],
                            reasons=["UNKNOWN_TEST_HASH"])
        self.assert_mapping(self.report((PLACEMENT, UNKNOWN), (STOCK_ON, STOCK_OFF, SECOND_UNKNOWN)),
                            "REVIEW_REQUIRED", matched=[PLACEMENT_MATCH, STOCK_ON_MATCH, STOCK_OFF_MATCH],
                            unknown=[UNKNOWN, SECOND_UNKNOWN], reasons=["UNKNOWN_TEST_HASH"])

    def test_complete_report_without_impacted_tests_has_no_impact(self):
        self.assert_mapping(self.report((PLACEMENT, STOCK_ON, STOCK_OFF), changed=False), "NO_IMPACT")
        self.assert_mapping(self.report(()), "NO_IMPACT")

    def test_incomplete_report_retains_known_impact_or_requests_review_with_no_candidates(self):
        self.assert_mapping(self.report((PLACEMENT,), dropped=1), "REVIEW_REQUIRED",
                            matched=[PLACEMENT_MATCH], reasons=["INCOMPLETE_REPORT"])
        self.assert_mapping(self.report((PLACEMENT,), changed=False, dropped=1), "REVIEW_REQUIRED",
                            reasons=["INCOMPLETE_REPORT"])

    def test_mixed_inventory_versions_require_review_even_without_impacts(self):
        self.assert_mapping(self.report((STOCK_ON,), versions=(1, 2)), "REVIEW_REQUIRED",
                            matched=[STOCK_ON_MATCH], reasons=["MIXED_INVENTORY_VERSIONS"])
        self.assert_mapping(self.report((STOCK_ON,), changed=False, versions=(2, 1)), "REVIEW_REQUIRED",
                            reasons=["MIXED_INVENTORY_VERSIONS"])
        self.assert_mapping(self.report((STOCK_ON, UNKNOWN), versions=(1, 2), dropped=1),
                            "REVIEW_REQUIRED", matched=[STOCK_ON_MATCH], unknown=[UNKNOWN],
                            reasons=["INCOMPLETE_REPORT", "MIXED_INVENTORY_VERSIONS", "UNKNOWN_TEST_HASH"])

    def test_legacy_same_version_report_maps_known_hashes(self):
        self.assert_mapping(self.report((PLACEMENT,), versions=(1, 1)), "READY",
                            matched=[PLACEMENT_MATCH])

    def test_output_is_deterministic_when_query_and_impact_order_changes(self):
        report = self.report((PLACEMENT, SECOND_UNKNOWN), (STOCK_ON, UNKNOWN, PLACEMENT))
        expected = self.assert_mapping(report, "REVIEW_REQUIRED",
                                       matched=[PLACEMENT_MATCH, STOCK_ON_MATCH],
                                       unknown=[UNKNOWN, SECOND_UNKNOWN], reasons=["UNKNOWN_TEST_HASH"])
        reversed_report = deepcopy(report)
        reversed_report["queries"].reverse()
        reversed_report["impacted_test_ids"].reverse()
        for item in reversed_report["queries"]:
            item["impacted_test_ids"].reverse()
        self.write(reversed_report)
        self.assertEqual(self.invoke(), (2, expected, ""))

    def test_disputed_and_duplicate_impacted_hashes_fail_closed(self):
        for aggregate, per_query in (
            ([PLACEMENT, STOCK_ON], [PLACEMENT]),
            ([STOCK_ON], [STOCK_OFF]),
            ([], [PLACEMENT]),
            ([PLACEMENT], []),
            ([PLACEMENT, PLACEMENT], [PLACEMENT]),
            ([PLACEMENT], [PLACEMENT, PLACEMENT]),
            (["synthetic-invalid-hash"], ["synthetic-invalid-hash"]),
            ([PLACEMENT], PLACEMENT),
        ):
            with self.subTest(aggregate_count=len(aggregate), query_impact_type=type(per_query).__name__):
                report = self.report((PLACEMENT,))
                report["impacted_test_ids"] = aggregate
                report["queries"][0]["impacted_test_ids"] = per_query
                self.write(report)
                self.assert_invalid()

    def test_duplicate_query_identity_and_malformed_json_fail_closed(self):
        report = self.report((PLACEMENT,))
        report["queries"].append(deepcopy(report["queries"][0]))
        self.write(report)
        self.assert_invalid()

        valid = json.dumps(self.report((PLACEMENT,))).encode("utf-8")
        for raw in (valid[:-1], b"synthetic-input-marker\xff",
                    valid.replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1')):
            Path(REPORT).write_bytes(raw)
            self.assert_invalid()

    def test_report_path_and_unsupported_dispatch_options_are_rejected(self):
        self.write(self.report((PLACEMENT,)))
        with patch.object(registry.inventory, "read_bytes") as read_bytes:
            for path in (str(Path(REPORT).absolute()), "./" + REPORT, "../" + REPORT,
                         "inventory/../" + REPORT, "inventory//" + Path(REPORT).name,
                         ".git/" + REPORT, "private/" + REPORT, "fixture.env.bak/" + REPORT,
                         "fixture.deploy.localenv/" + REPORT, "fixture.pem/" + REPORT,
                         "inventory\\SQL-INVENTORY-REPORT.json", "inventory/SNAPSHOT.json", REPORT + "\0"):
                with self.subTest(path=path):
                    self.assert_invalid(path=path)
            self.assert_invalid("--run", "ORDER_PLACEMENT_RELATED")
        read_bytes.assert_not_called()

    def test_symlink_hardlink_fifo_and_non_report_files_are_rejected(self):
        self.write(self.report((PLACEMENT,)))
        name = Path(REPORT).name
        Path("linked").symlink_to(Path(REPORT).parent.absolute(), target_is_directory=True)
        self.assert_invalid(path=f"linked/{name}")
        Path("other").mkdir()
        path = Path("other") / name
        path.symlink_to(Path(REPORT).absolute())
        self.assert_invalid(path=str(path))
        path.unlink()
        os.link(REPORT, path)
        self.assert_invalid(path=REPORT)
        path.unlink()
        os.mkfifo(path)
        self.assert_invalid(path=str(path))
        self.assert_invalid(path=f"missing/{name}")


if __name__ == "__main__":
    unittest.main()
