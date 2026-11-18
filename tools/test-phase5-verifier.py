#!/usr/bin/env python3
"""Negative completion checks; requires actual local and four-DB reports."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("phase5_verifier_tests", Path(__file__).with_name("verify-phase5.py"))
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class EvidenceTest(unittest.TestCase):
    def setUp(self):
        self.local = json.loads((v.ROOT / v.INPUTS[0]).read_text())
        if not (v.ROOT / v.INPUTS[1]).is_file():
            self.skipTest("Four-DB execution NOT RUN")
        self.real = json.loads((v.ROOT / v.INPUTS[1]).read_text())

    def test_complete(self):
        self.assertEqual(v.verify(self.real, self.local)["gate"], "G4")

    def test_secret_input_rejected_before_read(self):
        self.local["source_sha512"][".env"] = "0" * 128
        with patch.object(Path, "read_bytes", side_effect=AssertionError("Unsafe read")):
            with self.assertRaises(ValueError):
                v.verify_local(self.local)

    def test_missing_target(self):
        del self.real["profiles"]["ORACLE"]
        with self.assertRaises(ValueError):
            v.verify(self.real, self.local)

    def test_digest_field_tampering(self):
        for field in ("evidence_digest", "server_release_hash", "driver_release_hash", "result_digest"):
            candidate = copy.deepcopy(self.real)
            candidate["profiles"]["MYSQL"][field] = "0" * 64
            with self.assertRaises(ValueError):
                v.verify(candidate, self.local)

    def test_source_actual_execution_required(self):
        self.real["profiles"]["POSTGRESQL"]["source_sql_executed"] = False
        with self.assertRaises(ValueError):
            v.verify(self.real, self.local)

    def test_h2_cannot_claim_postgresql_execution(self):
        self.local["h2"]["source_sql_executed"] = True
        with self.assertRaises(ValueError):
            v.verify_local(self.local)

    def test_uncertain_cleanup(self):
        self.real["cleanup"]["temporary_directory_remaining"] = True
        with self.assertRaises(ValueError):
            v.verify(self.real, self.local)

    def test_driver_integrity_required(self):
        for field, value in (("jar_sha512", "0" * 128), ("published_checksum_verified", False)):
            candidate = copy.deepcopy(self.real)
            candidate["driver_dependencies"]["artifacts"][0][field] = value
            with self.assertRaises(ValueError):
                v.verify(candidate, self.local)

    def test_health_and_retention_proof_required(self):
        for key in ("health", "retention"):
            candidate = copy.deepcopy(self.real)
            del candidate["profiles"]["MYSQL"][key]
            with self.assertRaises((ValueError, KeyError)):
                v.verify(candidate, self.local)

    def test_runtime_failure_rejected(self):
        next(s for s in self.real["steps"] if s["name"] == "equivalence-MYSQL")["exit_code"] = 124
        with self.assertRaises(ValueError):
            v.verify(self.real, self.local)

    def test_prior_resources_preserved(self):
        self.real["existing_resources_modified"] = 1
        with self.assertRaises(ValueError):
            v.verify(self.real, self.local)

    def test_protocol_truncation(self):
        with self.assertRaises(ValueError):
            v.h.protocol("H2", "H2 PASS\nCHECKS=8", 0)

    def test_consistent_distinct_config_id_and_manifest(self):
        candidate = copy.deepcopy(self.real)
        r = candidate["profiles"]["MYSQL"]
        r["image_config_id"] = "sha256:" + "f" * 64
        r["retention"]["image_id"] = r["image_config_id"]
        next(s for s in candidate["steps"] if s["name"] == "image-config-MYSQL")["output_sha512"] = hashlib.sha512(
            f"{r['image_config_id']} {r['image_config_platform']}\n".encode()).hexdigest()
        saved = r["retention"]
        next(s for s in candidate["steps"] if s["name"] == "retention-MYSQL")["output_sha512"] = hashlib.sha512(
            f"{saved['state']} {saved['exit_code']} false {saved['image_id']} {saved['mount_count']}\n".encode()).hexdigest()
        self.assertEqual(v.verify(candidate, self.local)["status"], "PASS")
        r["image_config_id"] = "sha256:" + "e" * 64
        with self.assertRaises(ValueError):
            v.verify(candidate, self.local)


class LocalEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.local = json.loads((v.ROOT / v.INPUTS[0]).read_text())

    def test_complete_local(self):
        self.assertEqual(v.verify_local(self.local)["status"], "PASS")

    def test_unsafe_source_path(self):
        self.local["source_sha512"][".env.java"] = "0" * 128
        with patch.object(Path, "read_bytes", side_effect=AssertionError("Unsafe read")):
            with self.assertRaises(ValueError):
                v.verify_local(self.local)

    def test_preservation_baseline_changed(self):
        self.local["preservation_baseline_sha512"][v.h.BASELINES[0]] = "0" * 128
        with self.assertRaises(ValueError):
            v.verify_local(self.local)

    def test_h2_source_claim(self):
        self.local["h2"]["source_sql_executed"] = True
        with self.assertRaises(ValueError):
            v.verify_local(self.local)

    def test_h2_output_digest_tamper(self):
        self.local["h2"]["evidence_digest"] = "0" * 64
        with self.assertRaises(ValueError):
            v.verify_local(self.local)

    def test_existing_real_driver_attestation_schema(self):
        proof = json.loads((v.ROOT / "evidence/PHASE3-REAL-VALIDATION.json").read_text())["driver_dependencies"]
        v.verify_driver_proof(proof)
        changed = copy.deepcopy(proof)
        changed["upstream_license_checks"][0]["status"] = "NOT RUN"
        with self.assertRaises(ValueError):
            v.verify_driver_proof(changed)

    def test_parser_artifact_tamper(self):
        self.local["parser_dependency"]["jar_sha512"] = "0" * 128
        with self.assertRaises(ValueError):
            v.verify_local(self.local)


if __name__ == "__main__":
    unittest.main()
