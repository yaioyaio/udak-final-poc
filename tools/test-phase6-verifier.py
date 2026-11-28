#!/usr/bin/env python3
"""Mutation tests on an actual Phase 6 report, plus explicitly synthetic file-safety probes."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import signal
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("phase6_verify_tests", Path(__file__).with_name("verify-phase6.py"))
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class ActualEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with v.root_dir() as fd:
            cls.report = v.cli.read_report(fd, v.REPORT)
            cls.manifest = v.cli.read_report(fd, v.h.MANIFEST)
            cls.old = v.cli.read_report(fd, v.BASELINE)
            cls.g4 = v.cli.read_report(fd, v.G4)
            cls.old_digest = v.digest_file(fd,v.BASELINE)

    def change(self, *keys, value):
        report = copy.deepcopy(self.report)
        dest = report
        for key in keys[:-1]:
            dest = dest[key]
        dest[keys[-1]] = value
        return report

    def test_actual_complete_candidate(self):
        with v.root_dir() as fd:
            gate = v.verify(fd,self.report)
        self.assertEqual(gate["status"], "PASS")
        self.assertEqual(gate["consumer_executions"], 6)
        self.assertEqual(gate["formal_release"], "BLOCKED")
        self.assertIs(gate["authorize_publish"], False)

    def test_sensitive_inventory_rejected_before_open(self):
        row = copy.deepcopy(self.report)
        row["source_sha512"]["example.env.backup"] = "1"*128
        with patch.object(v.cli,"regular_file",side_effect=AssertionError("Unapproved read")):
            with self.assertRaises(ValueError):
                v.verify(None,row)

    def test_omitted_harness_rejected(self):
        r = copy.deepcopy(self.report)
        r["harness_sha512"].pop(v.TESTS)
        with self.assertRaises(ValueError):
            v.check_input_names(r)

    def test_extra_configuration_rejected(self):
        r = copy.deepcopy(self.report)
        r["configuration_sha512"]["unapproved.properties"] = "a"*128
        with self.assertRaises(ValueError):
            v.check_input_names(r)

    def test_changed_real_source_digest_rejected(self):
        path = next(iter(self.report["source_sha512"]))
        r = self.change("source_sha512",path,value="1"*128)
        with v.root_dir() as fd, self.assertRaises(ValueError):
            v.cli.verify_inputs(fd,r)

    def test_step_omitted(self):
        with self.assertRaises(ValueError):
            v.check_runtime(self.change("steps",value=self.report["steps"][:-1]))

    def test_steps_out_of_order(self):
        r = copy.deepcopy(self.report)
        r["steps"][0],r["steps"][1] = r["steps"][1],r["steps"][0]
        with self.assertRaises(ValueError):
            v.check_runtime(r)

    def test_child_must_be_reaped(self):
        with self.assertRaises(ValueError):
            v.check_runtime(self.change("steps",4,"child_reaped",value=False))

    def test_live_process_group_rejected(self):
        with self.assertRaises(ValueError):
            v.check_runtime(self.change("steps",3,"process_group_quiesced",value=False))

    def test_timeout_rejected(self):
        with self.assertRaises(ValueError):
            v.check_runtime(self.change("steps",2,"exit_code",value=124))

    def test_boolean_as_success_code_rejected(self):
        with self.assertRaises(ValueError):
            v.check_runtime(self.change("steps",1,"exit_code",value=False))

    def test_missing_output_digest_rejected(self):
        with self.assertRaises(ValueError):
            v.check_runtime(self.change("steps",2,"output_sha512",value=""))

    def test_real_containers_rejected(self):
        with self.assertRaises(ValueError):
            v.check_runtime(self.change("containers_started",value=1))

    def test_publication_rejected(self):
        for field,value in (("external_publications",1),("authorize_publish",True)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                v.check_runtime(self.change(field,value=value))

    def test_bound_increase_rejected(self):
        with self.assertRaises(ValueError):
            v.check_runtime(self.change("limits","workspace_bytes",value=2**35))

    def test_unexecuted_claims_preserved(self):
        with self.assertRaises(ValueError):
            v.check_runtime(self.change("not_run",value=[]))

    def reject_consumer(self, *keys, value):
        with self.assertRaises(ValueError):
            v.consumers(self.change(*keys,value=value),self.manifest)

    def test_protocol_requires_exact_scenarios(self):
        self.reject_consumer("boot_lines","boot3","scenarios",value=list(v.SCENARIOS[:-1]))

    def test_protocol_rejects_duplicate(self):
        self.reject_consumer("boot_lines","boot4","scenarios",value=[v.SCENARIOS[0]]*len(v.SCENARIOS))

    def test_no_actual_application_close(self):
        self.reject_consumer("boot_lines","boot3","application_closed",value=False)

    def test_no_positive_assertions(self):
        self.reject_consumer("boot_lines","boot4","assertions",value=0)

    def test_protocol_digest_binds_counts(self):
        self.reject_consumer("boot_lines","boot3","assertions",
                             value=self.report["boot_lines"]["boot3"]["assertions"]+1)

    def test_consumed_jar_digest_must_match_published_bytes(self):
        coord = "dev.udak:starter-boot3:"+v.cli.VERSION
        report = self.change("boot_lines","boot3","resolution","artifact_sha512",coord,value="0"*128)
        with self.assertRaises(ValueError):
            v.consumed_bytes(report,self.manifest)

    def test_missing_negative_execution(self):
        self.reject_consumer("negative_consumers",value=self.report["negative_consumers"][1:])

    def test_wrong_negative_scenario(self):
        self.reject_consumer("negative_consumers",0,"protocol","scenarios",value=["WRONG_BOOT_MAJOR"])

    def test_wrong_negative_graph(self):
        self.reject_consumer("negative_consumers",1,"resolution","artifacts",
                             value=self.report["boot_lines"]["boot3"]["resolution"]["artifacts"])

    def test_positive_graph_cannot_mix_starters(self):
        rows = self.report["boot_lines"]["boot3"]["resolution"]["artifacts"]
        self.reject_consumer("boot_lines","boot3","resolution","artifacts",
                             value=rows+["dev.udak:starter-boot4:"+v.cli.VERSION])

    def test_requires_pom_only(self):
        self.reject_consumer("boot_lines","boot3","resolution","pom_only",value=False)

    def test_runtime_framework_cannot_change(self):
        self.reject_consumer("boot_lines","boot4","resolution","spring_versions",value=["6.2.19"])

    def test_missing_bom_execution_rejected(self):
        self.reject_consumer("bom_consumer",value={})

    def test_pom_graph_cannot_substitute_for_bom_graph(self):
        self.reject_consumer("bom_consumer","resolution",
                             value=self.report["boot_lines"]["boot4"]["resolution"])

    def test_bom_graph_cannot_substitute_for_pom_graph(self):
        self.reject_consumer("boot_lines","boot4","resolution",
                             value=self.report["bom_consumer"]["resolution"])

    def test_bom_jar_digest_tied_to_pins(self):
        coord = "dev.udak:starter-boot4:"+v.cli.VERSION
        report = self.change("bom_consumer","resolution","artifact_sha512",coord,value="0"*128)
        with self.assertRaises(ValueError):
            v.consumed_bytes(report,self.manifest)

    def test_dependency_difference_requires_own_pin(self):
        plain = set(self.manifest["consumer_lanes"]["starter-boot4"])
        native = set(self.manifest["lanes"]["starter-boot4"])
        self.assertTrue(plain - native)
        different = min(plain - native)
        manifest = copy.deepcopy(self.manifest)
        manifest["artifacts"] = [r for r in manifest["artifacts"]
                                 if ":".join(r[k] for k in ("group","name","version")) != different]
        with self.assertRaises(ValueError):
            v.dependencies(self.report,manifest)

    def test_report_cannot_omit_plain_dependency_graph(self):
        with self.assertRaises(ValueError):
            v.dependencies(self.change("dependencies","consumer_lanes",value={}),self.manifest)

    def test_frozen_dependency_lanes(self):
        r = self.change("dependencies","lanes",value={})
        with self.assertRaises(ValueError):
            v.dependencies(r,self.manifest)

    def test_license_declaration_required(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["artifacts"][0]["licenses"] = []
        with self.assertRaises(ValueError):
            v.dependencies(self.report,manifest)

    def test_dependency_pin_origin(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["artifacts"][0]["jar_url"] = "https://example.invalid/other.jar"
        with self.assertRaises(ValueError):
            v.dependencies(self.report,manifest)

    def test_repackage_must_match_first_build(self):
        path = next(iter(self.report["reproducibility"]["artifact_sha512"]))
        with self.assertRaises(ValueError):
            v.reproduction(self.change("reproducibility","artifact_sha512",path,value="f"*128))

    def test_source_jar_required(self):
        rows = [r for r in self.report["artifacts"] if not r["path"].endswith("-sources.jar")]
        with self.assertRaises(ValueError):
            v.reproduction(self.change("artifacts",value=rows))

    def test_source_changes_cannot_claim_compatibility(self):
        path = next(p for p in self.report["source_sha512"] if p.startswith("core/src/main/java/"))
        with self.assertRaises(ValueError):
            v.baseline(self.change("source_sha512",path,value="0"*128),self.old,self.g4,self.old_digest)

    def test_baseline_must_belong_to_g4(self):
        with self.assertRaises(ValueError):
            v.baseline(self.report,self.old,self.g4,"0"*128)

    def test_pinned_public_addition_must_match_reviewed_bytes(self):
        pins = json.loads((v.ROOT / v.h.BASELINE_PINS).read_bytes())
        path = next(iter(pins["added_public_sources"]))
        with self.assertRaises(ValueError):
            v.baseline(self.change("source_sha512",path,value="0"*128),self.old,self.g4,self.old_digest)

    def test_current_receipt_requires_historical_g4_protocol(self):
        with self.assertRaises(ValueError):
            v.baseline(self.change("steps",2,"output_sha512",value="0"*128),self.old,self.g4,self.old_digest)

    def test_unavailable_binary_baseline(self):
        with self.assertRaises(ValueError):
            v.baseline(self.change("api_compatibility","binary_backward_compatibility",value="PASS"),
                       self.old,self.g4,self.old_digest)

    def test_temporary_residue(self):
        with self.assertRaises(ValueError):
            v.cleanup(dict(self.report["cleanup"],temporary_directory_remaining=True),20000,2*1024**3)

    def test_candidate_cleanup_size(self):
        with self.assertRaises(ValueError):
            v.cleanup(dict(self.report["candidate_cleanup"],temporary_bytes_removed=2**40),500,200*1024**2)


class SyntheticFileSafety(unittest.TestCase):
    """Only benign contents are created, under a test-owned private directory."""

    def test_denied_basename_before_filesystem_open(self):
        with patch.object(os,"open",side_effect=AssertionError("Unexpected open")):
            with self.assertRaises(ValueError), v.cli.regular_file(-1,"sample.env.backup",10):
                pass

    def test_oversized_file_before_content_open(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            (root/"public.json").write_bytes(b"oversized fixture")
            with v.cli.directory(root.parts[1:]) as fd:
                with patch.object(os,"fdopen",side_effect=AssertionError("Unexpected content read")):
                    with self.assertRaises(ValueError), v.cli.regular_file(fd,"public.json",2):
                        pass

    def test_symlink_does_not_open_destination(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            (root/"fixture.json").write_bytes(b"public fixture")
            (root/"linked.json").symlink_to(root/"fixture.json")
            with v.cli.directory(root.parts[1:]) as fd:
                with patch.object(os,"fdopen",side_effect=AssertionError("Unexpected content read")):
                    with self.assertRaises(ValueError), v.cli.regular_file(fd,"linked.json",64):
                        pass


class SyntheticRuntimeSafety(unittest.TestCase):
    """Exercise cleanup on short-lived, owned children independently of product tests."""

    measurements = {}

    def removed(self, label, work, cleanup):
        self.assertFalse(work.exists())
        self.assertEqual(cleanup["status"], "PASS")
        self.assertIs(cleanup["temporary_directory_remaining"], False)
        self.assertEqual(cleanup["temporary_files_removed"], 1)
        self.measurements[label] = {field:cleanup[field] for field in
                                    ("temporary_files_removed","temporary_bytes_removed","temporary_directory_remaining")}

    def test_failed_child(self):
        with self.assertRaises(RuntimeError) as failure:
            with v.h.workspace() as (work,cleanup):
                v.h.step("failure-probe", ["/bin/sh","-c","exit 7"], work, timeout=2)
        evidence = json.loads(str(failure.exception))
        self.assertEqual(evidence["exit_code"], 7)
        self.assertTrue(evidence["child_reaped"] and evidence["process_group_quiesced"])
        self.removed("failure",work,cleanup)

    def test_timed_out_child(self):
        with v.h.workspace() as (work,cleanup):
            evidence = v.h.step("timeout-probe", ["/bin/sleep","2"], work, timeout=0.1, expected=124)
        self.assertEqual(evidence["exit_code"],124)
        self.assertTrue(evidence["child_reaped"] and evidence["process_group_quiesced"])
        self.removed("timeout",work,cleanup)

    def test_interrupted_child(self):
        # Arm the signal only after the owned child has started.
        # The target of SIGTERM is this isolated unit-test worker.
        original = v.h.subprocess.Popen
        interrupted_child = []
        timer = threading.Timer(0.1, os.kill, args=(os.getpid(),signal.SIGTERM))

        def start(*args, **kwargs):
            child = original(*args, **kwargs)
            interrupted_child.append(child)
            timer.start()
            return child

        previous = signal.signal(signal.SIGTERM,v.h.guard.interrupted)
        try:
            with self.assertRaises(InterruptedError):
                with v.h.workspace() as (work,cleanup):
                    with patch.object(v.h.subprocess,"Popen",side_effect=start):
                        v.h.step("signal-probe", ["/bin/sleep","2"], work, timeout=3)
        finally:
            timer.cancel()
            if timer.ident is not None:
                timer.join(timeout=1)
            signal.signal(signal.SIGTERM,previous)
        self.assertEqual(len(interrupted_child),1)
        self.assertIsNotNone(interrupted_child[0].poll())
        self.assertFalse(v.h.guard.group_alive(interrupted_child[0].pid))
        self.removed("interrupt",work,cleanup)


def worker():
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
    if not result.wasSuccessful() or result.skipped:
        print("VERIFIER_TESTS_FAILED")
        for test,_ in result.failures + result.errors:
            name = test.id().split(".")[-1]
            if re.fullmatch(r"test_[a-z_]+",name):
                print("TEST="+name)
        return 1
    print("VERIFIER_TESTS="+str(result.testsRun))
    print("SKIPPED=0")
    print("SYNTHETIC_CLEANUP="+json.dumps(SyntheticRuntimeSafety.measurements,sort_keys=True,separators=(",",":")))
    return 0


def main():
    if sys.argv[1:] == ["--worker"]:
        return worker()
    if sys.argv[1:]:
        return 2
    report = {"schema_version":1,"status":"FAIL","scope":"actual report mutations and synthetic file/process cleanup probes"}
    try:
        with v.root_dir() as fd:
            report["validation_sha512"] = v.digest_file(fd,v.REPORT)
            report["source_sha512"] = {p:v.digest_file(fd,p) for p in (v.VERIFIER,v.TESTS)}
        with v.h.guard.workspace("udak-phase6-verifier-") as (work,clean):
            report["cleanup"] = clean
            report["step"] = v.h.step("phase6-verifier-tests",
                                     [sys.executable,"-B",str(Path(__file__).resolve()),"--worker"],work,timeout=60)
            output = (work/"phase6-verifier-tests.output").read_bytes()
            match = re.fullmatch(rb"VERIFIER_TESTS=([0-9]{1,3})\nSKIPPED=0\nSYNTHETIC_CLEANUP=([^\n]{1,1024})\n",output)
            v.require(match is not None,"TEST_PROTOCOL")
            report.update(tests=int(match[1]),skipped=0,synthetic_cleanup=json.loads(match[2]))
        report["status"] = "PASS"
        with v.root_dir() as fd:
            v.verify_unit(fd,report,v.digest_file(fd,v.REPORT))
    except (ValueError, KeyError, TypeError, AttributeError, OSError, RuntimeError) as error:
        report.update(status="FAIL",failure_type=type(error).__name__)
    v.save_report(v.UNIT,report)
    print("PHASE6_VERIFIER_TESTS "+report["status"]+" "+str(report.get("tests",0)))
    return int(report["status"] != "PASS")


if __name__ == "__main__":
    sys.exit(main())
