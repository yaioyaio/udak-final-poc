#!/usr/bin/env python3
"""Reject partial, injected, stale or uncertain Phase 4 completion claims."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("phase4_verifier_test", Path(__file__).with_name("verify-phase4.py"))
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class EvidenceTest(unittest.TestCase):
    def setUp(self):
        self.report = json.loads((v.ROOT / v.REPORT).read_text())

    def test_complete(self):
        self.assertEqual(v.verify(self.report)["status"], "PASS")

    def test_secret_path_rejected_before_read(self):
        self.report["source_sha512"][".env"] = "0" * 128
        with patch.object(Path, "read_bytes", side_effect=AssertionError("Unsafe file read")):
            with self.assertRaises(ValueError):
                v.verify(self.report)

    def test_missing_harness_rejected_before_read(self):
        del self.report["harness_sha512"]["tools/run-phase4.py"]
        with patch.object(Path, "read_bytes", side_effect=AssertionError("Unexpected file read")):
            with self.assertRaises(ValueError):
                v.verify(self.report)

    def test_altered_source_hash_rejected(self):
        first = sorted(self.report["source_sha512"])[0]
        self.report["source_sha512"][first] = "0" * 128
        with self.assertRaises(ValueError):
            v.verify(self.report)

    def test_incomplete_scenario_rejected(self):
        self.report["h2"]["scenarios"]["REQUIRES_NEW_BOUNDARY"] = "NOT RUN"
        with self.assertRaises(ValueError):
            v.verify(self.report)

    def test_failed_or_live_child_rejected(self):
        for field, value in (("exit_code", 124), ("process_group_quiesced", False), ("child_reaped", False)):
            candidate = copy.deepcopy(self.report)
            candidate["steps"][-1][field] = value
            with self.assertRaises(ValueError):
                v.verify(candidate)

    def test_uncertain_cleanup_rejected(self):
        self.report["cleanup"]["temporary_directory_remaining"] = True
        with self.assertRaises(ValueError):
            v.verify(self.report)

    def test_resource_preservation_violation_rejected(self):
        self.report["existing_managed_instances_modified"] = 1
        with self.assertRaises(ValueError):
            v.verify(self.report)

    def test_legacy_regression_and_g3_required(self):
        self.report["legacy_h2"]["checks"] = 0
        with self.assertRaises(ValueError):
            v.verify(self.report)
        self.report = json.loads((v.ROOT / v.REPORT).read_text())
        self.report["prior_g3"]["status"] = "NOT RUN"
        with self.assertRaises(ValueError):
            v.verify(self.report)

    def test_protocol_rejects_extra_or_missing_lines(self):
        valid = "\n".join(["H2 PASS", "CHECKS=10", "CLEANUP=CONFIRMED"]
                          + ["SCENARIO=" + n + ":PASS" for n in v.execution.CHECKS] + ["ASSERTIONS=30"])
        self.assertEqual(v.execution.protocol(valid, 0)["checks"], 10)
        for text, exit_code in ((valid + "\nEXTRA", 0), (valid.rsplit("\n", 1)[0], 0), (valid, 1)):
            with self.assertRaises(ValueError):
                v.execution.protocol(text, exit_code)

    def test_prior_gate_path_map_rejected_before_any_bytes_read(self):
        gate = json.loads((v.ROOT / "evidence/PHASE3-GATE.json").read_text())
        for injected in (None, ".env", "../.env", "/tmp/phase4.env"):
            candidate = copy.deepcopy(gate)
            if injected is None:
                candidate["execution_reports_sha512"] = {}
            else:
                candidate["execution_reports_sha512"][injected] = "0" * 128
            with patch.object(Path, "read_bytes", side_effect=AssertionError("Unsafe prior report read")):
                with self.assertRaises(ValueError):
                    v.execution.prior_gate(candidate)

    def test_source_inputs_rejected_before_bytes_read(self):
        for name in (".env.java", "module/Probe.env.java", "../Probe.java", "/tmp/Probe.java"):
            with patch.object(Path, "read_bytes", side_effect=AssertionError("Unsafe source read")):
                with self.assertRaises(ValueError):
                    v.execution.hashes([name])
        with tempfile.TemporaryDirectory(prefix="udak-phase4-path-probe-") as work:
            root = Path(work).resolve()
            (root / "Target.java").write_text("synthetic-probe")
            (root / "Linked.java").symlink_to(root / "Target.java")
            with patch.object(Path, "read_bytes", side_effect=AssertionError("Symlink target read")):
                with self.assertRaises(ValueError):
                    v.execution.approved_paths(["Linked.java"], root)

    def test_dependency_identity_and_integrity_required(self):
        for mutation in ("empty", "duplicate", "jar", "pom", "checksum"):
            candidate = copy.deepcopy(self.report)
            artifacts = candidate["dependencies"]["artifacts"]
            if mutation == "empty":
                candidate["dependencies"]["artifacts"] = [{} for _ in range(36)]
            elif mutation == "duplicate":
                artifacts[1] = copy.deepcopy(artifacts[0])
            elif mutation == "checksum":
                artifacts[0]["published_checksum_verified"] = False
            else:
                artifacts[0][mutation + "_sha512"] = "0" * 128
            with self.assertRaises(ValueError):
                v.verify(candidate)


if __name__ == "__main__":
    unittest.main()
