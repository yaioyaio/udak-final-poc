#!/usr/bin/env python3
"""Verify that follow-up G5 functional evidence preserves the archived run."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("product_g5", TOOLS / "verify-product-g5.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
runner = gate.load("observe_candidate", "tools/release-performance/verify-observe-candidate.py")
RUN_ID = "OBSERVE-G5-SYNTHETIC"


class ObserveCandidateEvidenceTest(unittest.TestCase):
    def test_archive_is_intact_and_fresh_run_cannot_reuse_it(self):
        self.assertEqual(gate.candidate_status(gate.DEFAULT_CANDIDATE_RUN)["status"], "PASS")
        with tempfile.TemporaryDirectory() as folder, patch.object(gate, "ROOT", Path(folder)):
            self.assertEqual(gate.candidate_status(RUN_ID), {"status": "NOT RUN"})

    def test_scoped_report_checks_identity_and_candidate_inputs(self):
        proof = {**gate.read(gate.OBSERVE_CANDIDATE), "schema_version": 2,
                 "run_id": RUN_ID, "input_sha512": {"synthetic": "a" * 128}}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / gate.candidate_evidence_path(RUN_ID)
            path.parent.mkdir()
            path.touch()
            with (patch.object(gate, "ROOT", root),
                  patch.object(gate, "load", return_value=runner),
                  patch.object(gate, "read", return_value=proof) as reader,
                  patch.object(runner, "input_hashes", return_value=proof["input_sha512"])):
                self.assertEqual(gate.candidate_status(RUN_ID)["status"], "PASS")
                reader.assert_called_once_with(path.relative_to(root).as_posix())
                proof["run_id"] = "OBSERVE-OTHER"
                with self.assertRaisesRegex(ValueError, "identity"):
                    gate.candidate_status(RUN_ID)
                proof.update(run_id=RUN_ID, input_sha512={"synthetic": "b" * 128})
                with self.assertRaisesRegex(ValueError, "inputs differ"):
                    gate.candidate_status(RUN_ID)

    def test_archive_and_invalid_ids_cannot_start_contracts(self):
        for args in ([], ["--run-id", gate.DEFAULT_CANDIDATE_RUN], ["--run-id", "../OBSERVE"]):
            with (self.subTest(args=args),
                  patch.object(sys, "argv", ["verify-observe-candidate.py", *args]),
                  patch.object(runner, "execute") as execute, redirect_stdout(io.StringIO())):
                self.assertEqual(runner.main(), 2)
                execute.assert_not_called()

    def test_publish_keeps_first_complete_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder).resolve() / Path(gate.candidate_evidence_path(RUN_ID)).name
            proof = {"status": "PASS", "run_id": RUN_ID}
            runner.publish(path, proof)
            self.assertEqual(json.loads(path.read_bytes()), proof)
            with self.assertRaises(FileExistsError):
                runner.publish(path, {"status": "FAIL"})
            self.assertEqual(json.loads(path.read_bytes()), proof)
            self.assertEqual(list(path.parent.iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
