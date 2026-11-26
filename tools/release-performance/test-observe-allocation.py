"""Offline checks for allocation partitions and the same-session reference."""

import importlib.util
from pathlib import Path
import sys
import unittest


sys.dont_write_bytecode = True
path = Path(__file__).with_name("run-observe-allocation.py")
spec = importlib.util.spec_from_file_location("allocation", path)
allocation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(allocation)


def protocol(normalization=160, fingerprint=784, event=40, residual=0):
    ops = allocation.OPS_PER_BLOCK
    total = normalization + fingerprint + event + residual
    row = "BLOCK " + " ".join(map(str, (ops, normalization * ops, fingerprint * ops, event * ops, total * ops)))
    return "\n".join(("OBSERVE_ALLOCATION PASS", *([row] * allocation.BLOCKS)))


class AllocationTest(unittest.TestCase):
    def test_balanced_partition_and_priority(self):
        blocks = allocation.parse_blocks(protocol())
        result = allocation.assess(blocks, [[570, 984], [580, 984]])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["priority_stage"], "fingerprint")
        self.assertEqual(result["instrumented_median_bytes_per_op"]["fingerprint"], 784)
        self.assertEqual(result["instrumented_median_bytes_per_op"]["total"], 984)

    def test_rejects_missing_block_wrong_iteration_count_and_negative_residual(self):
        proof = protocol()
        for invalid in (proof.rsplit("\n", 1)[0], proof.replace("BLOCK 200000", "BLOCK 199999"),
                        protocol(residual=-1)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                allocation.parse_blocks(invalid)

    def test_refuses_priority_when_comparison_does_not_reconcile(self):
        for blocks, baseline in ((protocol(), [850, 984]), (protocol(residual=17), [984, 984]),
                                 (protocol(460, 484, 40), [950, 950])):
            result = allocation.assess(allocation.parse_blocks(blocks), [[560, value] for value in baseline])
            self.assertEqual(result["status"], "INCONCLUSIVE")
            self.assertIsNone(result["priority_stage"])


if __name__ == "__main__":
    unittest.main()
