#!/usr/bin/env python3
"""Security regression cases for the allowlisted G2 evidence protocol."""
import importlib.util
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("g2_harness", Path(__file__).with_name("run-g2.py"))
g2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g2)


class EvidenceProtocolTest(unittest.TestCase):
    def success(self):
        return ("POSTGRESQL PASS\nSERVER_VERSION=17.0\nDRIVER_VERSION=42.7\nCHECKS=10\nCLEANUP=CONFIRMED\n"
                + "\n".join("SCENARIO=" + name + ":PASS" for name in g2.SCENARIOS))

    def test_complete_evidence(self):
        result = g2.parse_profile("POSTGRESQL", self.success(), 0)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(result["scenarios"]), 10)

    def test_incomplete_or_unsafe_evidence_cannot_pass(self):
        unsafe = "SYNTHETIC_PRIVATE_SENTINEL"
        variants = ["", "POSTGRESQL PASS", self.success().replace("CHECKS=10", "CHECKS=9"),
                    self.success().replace("CLEANUP=CONFIRMED", "CLEANUP=UNKNOWN"),
                    self.success().replace("SERVER_VERSION=17.0", "SERVER_VERSION=" + unsafe),
                    self.success().replace("SCENARIO=PAGE:PASS", "SCENARIO=PAGE:FAIL"),
                    self.success() + "\n" + unsafe,
                    self.success().replace("SCENARIO=BIND:PASS", "SCENARIO=PAGE:PASS")]
        for output in variants:
            with self.subTest(output_index=variants.index(output)):
                result = g2.parse_profile("POSTGRESQL", output, 0)
                self.assertEqual(result["status"], "FAIL")
                self.assertNotIn(unsafe, str(result))

    def test_failed_process_cannot_pass(self):
        for code in (1, 124, -15):
            self.assertEqual(g2.parse_profile("POSTGRESQL", self.success(), code)["status"], "FAIL")

    def test_owned_fixture_failure_is_preserved(self):
        result = g2.parse_profile("ORACLE", "ORACLE FAIL: CLEANUP_UNCONFIRMED FIXTURE=udak_p2_012345abcdef", 1)
        self.assertEqual(result["cleanup"], "UNCONFIRMED")
        self.assertEqual(result["fixture"], "udak_p2_012345abcdef")

    def test_missing_provider_is_not_success(self):
        self.assertEqual(g2.parse_profile("MYSQL", "MYSQL NOT RUN: DEDICATED_PROVIDER_REQUIRED", 1),
                         {"status": "NOT RUN", "reason": "DEDICATED_PROVIDER_REQUIRED"})
        for code in (0, 124, -15):
            self.assertEqual(g2.parse_profile("MYSQL", "MYSQL NOT RUN: DEDICATED_PROVIDER_REQUIRED", code)["status"], "FAIL")
        self.assertEqual(g2.parse_profile("MYSQL", "MYSQL NOT RUN: DEDICATED_PROVIDER_REQUIRED\nUNEXPECTED", 1)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
