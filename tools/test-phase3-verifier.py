#!/usr/bin/env python3
"""Reject stale, partial, unsafe or unclean Phase 3 evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("phase3_verifier", Path(__file__).with_name("verify-phase3.py"))
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class EvidenceTest(unittest.TestCase):
    def setUp(self):
        self.reports = [json.loads((v.ROOT / name).read_text()) for name in v.INPUTS]

    def test_complete(self):
        self.assertEqual(v.verify(*self.reports)["status"], "PASS")

    def test_source_injection_rejected_before_file_read(self):
        self.reports[0]["source_sha512"][".env"] = "0" * 128
        with patch.object(Path, "read_bytes", side_effect=AssertionError("Unsafe file read")):
            with self.assertRaises(ValueError):
                v.verify(*self.reports)

    def test_missing_real_profile_rejected(self):
        del self.reports[1]["profiles"]["ORACLE"]
        with self.assertRaises(ValueError):
            v.verify(*self.reports)

    def test_missing_identity_or_timeout_rejected(self):
        for field, value in (("server_version", ""), ("driver_version", "0.0"), ("cleanup", "UNCONFIRMED")):
            reports = copy.deepcopy(self.reports)
            reports[1]["profiles"]["SQLSERVER"][field] = value
            with self.assertRaises(ValueError):
                v.verify(*reports)
        next(s for s in self.reports[1]["steps"] if s["name"] == "compatibility-SQLSERVER")["exit_code"] = 124
        with self.assertRaises(ValueError):
            v.verify(*self.reports)

    def test_active_runtime_rejected(self):
        self.reports[2]["active_managed_instances"] = 1
        with self.assertRaises(ValueError):
            v.verify(*self.reports)

    def test_incomplete_h2_regression_rejected(self):
        self.reports[0]["h2"]["scenarios"]["MYBATIS_CACHE"] = "NOT RUN"
        with self.assertRaises(ValueError):
            v.verify(*self.reports)


if __name__ == "__main__":
    unittest.main()
