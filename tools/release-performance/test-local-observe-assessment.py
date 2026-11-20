#!/usr/bin/env python3
"""Synthetic, workload-free regressions for local Observe evidence."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
PATH = Path(__file__).with_name("assess-local-observe.py")
spec = importlib.util.spec_from_file_location("local_observe", PATH)
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


class LocalObserveTest(unittest.TestCase):
    def l1(self, aa=100, ab=100, *, limit=10, blocks=6):
        return {
            "workload_started": True,
            "resources": {**local.L1_RESOURCE_PLAN, "memory_warning_observed": False,
                          "cleanup_confirmed": True},
            "regression_limit_percent": limit,
            "aa_ns_per_op": [[100, aa]] * blocks,
            "ab_ns_per_op": [[100, ab]] * blocks,
            "ab_alloc_bytes_per_op": [[0, 16]] * blocks,
        }

    def test_no_run(self):
        self.assertEqual(local.assess_l1({"workload_started": False}), {"status": "NOT RUN"})

    def test_unset_limit_keeps_pilot_inconclusive(self):
        result = local.assess_l1(self.l1(limit=None))
        self.assertEqual((result["status"], result["reason"]), ("INCONCLUSIVE", "REGRESSION_LIMIT_UNSET"))

    def test_small_fork_count_cannot_yield_95_percent_interval(self):
        result = local.assess_l1(self.l1(blocks=5))
        self.assertEqual(result["reason"], "INSUFFICIENT_BLOCKS")

    def test_a_a_limit_is_half_the_declared_margin(self):
        for value in (95, 105):
            with self.subTest(value=value):
                result = local.assess_l1(self.l1(aa=value, ab=110))
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(result["aa_limit_percent"], 5)
        result = local.assess_l1(self.l1(aa=103, limit=5))
        self.assertEqual(result["reason"], "AA_NOISE")

    def test_a_a_interval_must_be_entirely_inside_the_margin(self):
        data = self.l1()
        data["aa_ns_per_op"][0] = [100, 117]
        self.assertEqual(local.assess_l1(data)["reason"], "AA_NOISE")

    def test_regression_interval_can_pass_fail_or_overlap(self):
        self.assertEqual(local.assess_l1(self.l1(ab=90))["status"], "PASS")
        self.assertEqual(local.assess_l1(self.l1(ab=111))["status"], "FAIL")
        data = self.l1(ab=99)
        data["ab_ns_per_op"][0] = [100, 112]
        self.assertEqual(local.assess_l1(data)["reason"], "REGRESSION_LIMIT_OVERLAP")

    def test_direct_paired_difference_and_allocation(self):
        data = self.l1()
        data["ab_ns_per_op"] = [[value, value + 1] for value in (10, 20, 40, 80, 160, 320)]
        result = local.assess_l1(data)
        self.assertEqual(result["ab_ns_per_op"]["confidence_interval"], [1, 1])
        self.assertEqual(result["ab_bytes_per_op"]["confidence_interval"], [16, 16])

    def test_each_actual_resource_limit_blocks_a_verdict(self):
        fields = {**{key: limit + 1 for key, limit in local.L1_RESOURCE_PLAN.items()},
                  "memory_warning_observed": True, "cleanup_confirmed": False}
        for key, value in fields.items():
            with self.subTest(key=key):
                data = self.l1()
                data["resources"][key] = value
                result = local.assess_l1(data)
                self.assertEqual(result, {"status": "INCONCLUSIVE", "reason": "RESOURCE_EVIDENCE"})

    def test_missing_or_inconsistent_resource_receipt_is_inconclusive(self):
        self.assertEqual(local.assess_l1({"workload_started": True})["reason"], "RESOURCE_EVIDENCE")
        data = self.l1()
        data["resources"]["tree_cpu_seconds"] = 1
        self.assertEqual(local.assess_l1(data)["reason"], "RESOURCE_EVIDENCE")

    def test_bad_samples_are_rejected(self):
        for value in (0, -1, True, float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                local.paired_summary([[value, 100]], relative=True)

    def test_l2_caps_come_from_existing_product_criteria(self):
        plan = local.local_plan()
        self.assertEqual(plan["l1"]["approval"], "PENDING")
        self.assertEqual(plan["l2"]["starts_per_database"], 208)
        self.assertEqual(plan["l2"]["limits"]["max_starts_per_second"], 8)
        self.assertEqual(plan["l2"]["limits"]["wall_seconds"], 300)
        self.assertEqual(plan["l2"]["max_observe_p95_increase_percent"], 5)

    def test_l2_attempt_distinguishes_interruption_from_no_start(self):
        progress = local.assess_l2_progress({"workload_run_claimed": True,
                                             "profiles": {"POSTGRESQL": {"status": "FAIL"}}})
        self.assertEqual(progress["status"], "INCONCLUSIVE")
        self.assertEqual(progress["profiles"]["POSTGRESQL"]["status"], "INCONCLUSIVE")
        self.assertEqual(progress["profiles"]["MYSQL"]["status"], "NOT RUN")
        self.assertEqual(local.assess_l2_progress({"workload_run_claimed": True, "profiles": {}})["status"],
                         "NOT RUN")

    def test_complete_l2_receipt_is_for_the_official_gate(self):
        row = self.measured_l2_row()
        with self.assertRaisesRegex(ValueError, "official G5"):
            local.assess_l2_progress({"workload_run_claimed": True, "profiles": {"POSTGRESQL": row, "MYSQL": row}})

    def measured_l2_row(self):
        return {"plain_ns": [100] * 96, "observe_ns": [106] * 96,
                "assessment": {"status": "FAIL", "measured_per_arm": 96, "nearest_rank": 92,
                               "baseline_p95_ns": 100, "observe_p95_ns": 106, "overhead_percent": 6.0}}

    def test_partial_l2_measurement_remains_available_for_diagnosis(self):
        row = self.measured_l2_row()
        report = {"workload_run_claimed": True, "profiles": {"POSTGRESQL": row}}
        progress = local.assess_l2_progress(report)
        self.assertEqual(progress["status"], "INCONCLUSIVE")
        self.assertEqual(progress["profiles"]["POSTGRESQL"]["recorded_p95"]["status"], "FAIL")
        self.assertEqual(progress["profiles"]["POSTGRESQL"]["paired_delta_ns"]["median"], 6)
        row["assessment"]["overhead_percent"] = 5.0
        with self.assertRaisesRegex(ValueError, "Recorded p95 differs"):
            local.assess_l2_progress(report)

    def test_cli_rejects_oversized_input(self):
        call = subprocess.run([sys.executable, "-B", str(PATH), "l1"], input=b" " * (local.MAX_INPUT_BYTES + 1),
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
        self.assertEqual(call.returncode, 2)
        self.assertEqual(json.loads(call.stdout), {"error": "INVALID_EVIDENCE_OR_MODE"})


if __name__ == "__main__":
    unittest.main()
