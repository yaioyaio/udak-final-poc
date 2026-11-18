#!/usr/bin/env python3
"""Reject partial, stale, duplicate and unclean real-database evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("real_g2_verifier", Path(__file__).with_name("verify-real-g2.py"))
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class RealEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.batches = [json.loads((v.ROOT / name).read_text()) for name in v.INPUTS]

    def test_complete_real_evidence(self):
        self.assertEqual(v.verify(self.batches)["checks"], 40)

    def test_missing_real_profile_is_rejected(self):
        self.batches[0]["profiles"]["SQLSERVER"]["status"] = "NOT RUN"
        with self.assertRaises(ValueError):
            v.verify(self.batches)

    def test_timeout_cannot_pass(self):
        next(s for s in self.batches[0]["steps"] if s["name"] == "live-SQLSERVER")["exit_code"] = 124
        with self.assertRaises(ValueError):
            v.verify(self.batches)

    def test_uncertain_fixture_or_server_cleanup_cannot_pass(self):
        for key, value in (("cleanup", "UNCONFIRMED"), ("container_stopped", False)):
            batches = copy.deepcopy(self.batches)
            batches[0]["profiles"]["SQLSERVER"][key] = value
            with self.assertRaises(ValueError):
                v.verify(batches)

    def test_stale_or_different_source_is_rejected(self):
        key = next(iter(self.batches[0]["source_sha512"]))
        self.batches[1]["source_sha512"][key] = "0" * 128
        with self.assertRaises(ValueError):
            v.verify(self.batches)

    def test_duplicate_database_identity_is_rejected(self):
        self.batches[1]["profiles"]["MYSQL"]["container_id"] = self.batches[1]["profiles"]["POSTGRESQL"]["container_id"]
        with self.assertRaises(ValueError):
            v.verify(self.batches)


if __name__ == "__main__":
    unittest.main()
