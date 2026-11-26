"""Offline checks for the paired allocation decision."""

import importlib.util
from pathlib import Path
import unittest


path = Path(__file__).with_name("run-observe-query-id-comparison.py")
spec = importlib.util.spec_from_file_location("query_id_comparison", path)
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


class ComparisonTest(unittest.TestCase):
    def test_reports_paired_savings_and_sample_medians(self):
        rows = [
            {"BASELINE": [560, 984], "CANDIDATE": [540, 872]},
            {"CANDIDATE": [545, 880], "BASELINE": [570, 985]},
            {"BASELINE": [565, 986], "CANDIDATE": [542, 876]},
        ]
        result = comparison.assess(rows)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["bytes_saved_per_block"], [112, 105, 110])
        self.assertEqual(result["median_bytes_saved_per_op"], 110)
        self.assertEqual(result["baseline"]["ns_per_op"], 565)
        self.assertEqual(result["candidate"]["ns_per_op"], 542)

    def test_does_not_hide_a_block_below_the_savings_floor(self):
        good = {"BASELINE": [560, 984], "CANDIDATE": [545, 872]}
        weak = {"BASELINE": [560, 984], "CANDIDATE": [540, 969]}
        self.assertEqual(comparison.assess([good, weak, good])["status"], "FAIL")

    def test_rejects_missing_arm_and_nonfinite_or_zero_values(self):
        good = {"BASELINE": [560, 984], "CANDIDATE": [545, 872]}
        for bad in ({"BASELINE": [560, 984]}, {**good, "CANDIDATE": [545, float("inf")]},
                    {**good, "CANDIDATE": [0, 872]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                comparison.assess([good, bad, good])


if __name__ == "__main__":
    unittest.main()
