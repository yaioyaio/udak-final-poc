#!/usr/bin/env python3
"""Exercise the CLI and release gate using synthetic repository fixtures."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).absolute().parent.parent / "udak-cli"))

import udak_cli as cli


SYNTHETIC_VALUE = "synthetic-sensitive-marker"


class Phase6CliTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "repository"
        self.artifact_content = b"synthetic candidate bytes"
        self.artifact_digest = hashlib.sha512(self.artifact_content).hexdigest()
        self.policy = {"schema_version": 1, **cli.BLOCKING_POLICY, **cli.RELEASE_POLICY}
        self.write_json(cli.POLICY, self.policy)
        for gate, path in cli.HISTORICAL.items():
            self.write_json(path, {"schema_version": 1, "gate": gate, "status": "PASS"})
        sources = [f"{module}/src/main/java/dev/udak/Fixture.java" for module in cli.REQUIRED_SOURCE_MODULES]
        pins = self.dependency_pins()
        pin_digest = hashlib.sha512(self.write_json(cli.DEPENDENCY_PINS, pins).read_bytes()).hexdigest()
        baseline = self.write_json(cli.BASELINE_PINS, {"schema_version": 1})
        baseline_digest = hashlib.sha512(baseline.read_bytes()).hexdigest()
        policy_digest = hashlib.sha512(self.policy_bytes()).hexdigest()
        cleanup = {
            "status": "PASS", "temporary_directory_remaining": False,
            "temporary_files_removed": 100, "temporary_bytes_removed": 2048,
        }
        self.report = {
            "schema_version": 1,
            "phase": 6,
            "status": "PASS",
            "authorize_publish": False,
            "external_publications": 0,
            "containers_started": 0,
            "steps": [self.step(name) for name in cli.VALIDATION_STEPS],
            "boot_lines": {
                lane.lower(): {
                    **self.protocol(lane, cli.POSITIVE_SCENARIOS, 79),
                    "application_started": True, "application_closed": True,
                    "resolution": self.consumer_resolution(lane, "positive"),
                }
                for lane in cli.BOOT_VERSIONS
            },
            "bom_consumer": {
                "lane": "BOOT4", "status": "PASS",
                "protocol": {
                    **self.protocol("BOOT4", cli.POSITIVE_SCENARIOS, 79),
                    "application_started": True, "application_closed": True,
                },
                "resolution": self.consumer_resolution("BOOT4", "bom"),
            },
            "negative_consumers": [
                {
                    "lane": lane, "mode": mode, "status": "PASS",
                    "protocol": {**self.protocol(lane, (scenario,), 2), "startup_refused": True},
                    "resolution": self.consumer_resolution(lane, mode),
                }
                for (lane, mode), scenario in cli.NEGATIVE_SCENARIOS.items()
            ],
            "dependencies": {
                "status": "PASS", "sha512": pin_digest, "lanes": pins["lanes"],
                "consumer_lanes": pins["consumer_lanes"],
                "artifacts": len(pins["artifacts"]),
            },
            "cleanup": {
                **cleanup, "gradle_daemons_quiesced": True, "gradle_stop": self.step("cleanup-gradle-stop"),
            },
            "candidate_cleanup": dict(cleanup),
            "api_compatibility": {
                "status": "PASS", "baseline": "evidence/PHASE5-VALIDATION.json", "preserved_sources": 8,
                "prior_published_release": "NONE",
                "binary_backward_compatibility": "NOT RUN; no prior published release",
            },
            "source_sha512": self.hash_inputs(sources),
            "harness_sha512": self.hash_inputs(cli.REQUIRED_HARNESS),
            "configuration_sha512": self.hash_inputs(cli.REQUIRED_CONFIGURATION),
            "manifest_sha512": {
                cli.DEPENDENCY_PINS: pin_digest, cli.BASELINE_PINS: baseline_digest, cli.POLICY: policy_digest,
            },
            "artifacts": [],
        }
        for path in sorted(cli.ARTIFACTS):
            self.report["artifacts"].append({
                "path": path, "size": len(self.artifact_content), "sha512": self.artifact_digest,
            })
        self.report["reproducibility"] = {
            "status": "PASS", "repackaged_artifacts": len(cli.REPOSITORY_ARTIFACTS),
            "artifact_sha512": dict.fromkeys(cli.REPOSITORY_ARTIFACTS, self.artifact_digest),
        }
        self.save_report()

    @staticmethod
    def step(name):
        return {
            "name": name, "status": "PASS", "exit_code": 0, "child_reaped": True,
            "process_group_quiesced": True, "output_sha512": "a" * 128,
        }

    @staticmethod
    def protocol(lane, scenarios, assertions):
        lines = [f"{lane} PASS", f"ASSERTIONS={assertions}"]
        lines.extend(f"SCENARIO={scenario}:PASS" for scenario in scenarios)
        return {
            "status": "PASS", "assertions": assertions, "scenarios": list(scenarios),
            "protocol_sha512": hashlib.sha512(("\n".join(lines) + "\n").encode("ascii")).hexdigest(),
        }

    @staticmethod
    def framework(lane, *, pom_default=False):
        boot, spring = cli.BOOT_VERSIONS[lane]
        spring_modules = ["aop", "beans", "context", "core", "expression", "jdbc", "tx"]
        extras = []
        if lane == "BOOT3":
            spring_modules.append("jcl")
            micrometer = "1.15.12"
        else:
            micrometer = "1.16.8" if pom_default else "1.17.2"
            logging = "1.3.5" if pom_default else "1.3.6"
            extras.extend((f"commons-logging:commons-logging:{logging}", "org.jspecify:jspecify:1.0.1"))
        return sorted([
            f"org.springframework.boot:spring-boot:{boot}",
            f"org.springframework.boot:spring-boot-autoconfigure:{boot}",
            f"io.micrometer:micrometer-commons:{micrometer}",
            f"io.micrometer:micrometer-observation:{micrometer}",
            *(f"org.springframework:spring-{module}:{spring}" for module in spring_modules),
            *extras,
        ])

    def dependency_pins(self):
        lanes = {"starter-" + lane.lower(): self.framework(lane) for lane in cli.BOOT_VERSIONS}
        lanes["h2"] = ["com.h2database:h2:2.3.232"]
        consumer_lanes = {
            "starter-" + lane.lower(): self.framework(lane, pom_default=True)
            for lane in cli.BOOT_VERSIONS
        }
        coordinates = {coordinate for items in (*lanes.values(), *consumer_lanes.values()) for coordinate in items}
        artifacts = []
        for coordinate in sorted(coordinates):
            group, name, version = coordinate.split(":")
            base = f"{cli.MAVEN_CENTRAL}{group.replace('.', '/')}/{name}/{version}/{name}-{version}"
            artifacts.append({
                "group": group, "name": name, "version": version, "size": 1000,
                "sha512": "a" * 128, "pom_sha512": "b" * 128, "published_checksum": "sha512",
                "jar_url": base + ".jar", "pom_url": base + ".pom",
                "pom_chain": [{"url": base + ".pom", "sha512": "b" * 128}],
                "licenses": [{"name": "Synthetic example", "url": "https://example.invalid/license"}],
                "license_resources_sha512": {"META-INF/LICENSE.txt": "c" * 128},
            })
        return {
            "schema_version": 1, "gradle": cli.GRADLE_PIN, "lanes": lanes,
            "consumer_lanes": consumer_lanes, "artifacts": artifacts,
            "approval": "DECLARED LICENSES VERIFIED; redistribution NOT GRANTED",
        }

    def consumer_resolution(self, lane, mode):
        selected = ["starter-" + lane.lower()]
        if mode == "mixed":
            selected = ["starter-boot3", "starter-boot4"]
        if mode == "wrong":
            selected = ["starter-boot4" if lane == "BOOT3" else "starter-boot3"]
        boot, spring = cli.BOOT_VERSIONS[lane]
        external = self.framework(lane, pom_default=mode == "positive") + ["com.h2database:h2:2.3.232"]
        own = [f"dev.udak:{module}:{cli.VERSION}" for module in (*cli.RELEASE_MODULES[:4], *selected)]
        return {
            "status": "PASS", "boot_version": boot, "spring_versions": [spring], "pom_only": True,
            "artifacts": sorted(external + own),
            "artifact_sha512": dict.fromkeys(external, "a" * 128) | dict.fromkeys(own, self.artifact_digest),
        }

    def write(self, path, value):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(value)
        return file

    def write_json(self, path, value):
        return self.write(path, json.dumps(value).encode("utf-8"))

    def policy_bytes(self):
        return json.dumps(self.policy).encode("utf-8")

    def save_report(self):
        self.write_json(cli.VALIDATION, self.report)

    def hash_inputs(self, paths):
        contents = b"synthetic public fixture"
        digest = hashlib.sha512(contents).hexdigest()
        for path in paths:
            self.write(path, contents)
        return dict.fromkeys(paths, digest)

    def prepare_artifacts(self):
        for row in self.report["artifacts"]:
            self.write(row["path"], self.artifact_content)

    def run_main(self, command="inspect", *, args=None, root=None):
        if args is None:
            args = ["inspect", "--format", "json"] if command == "inspect" else ["--format", "json"]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = cli.main(command, args, self.root if root is None else root)
            except SystemExit as exit_error:
                code = exit_error.code
        self.assertNotIn(SYNTHETIC_VALUE, out.getvalue() + err.getvalue())
        return code, out.getvalue(), err.getvalue()

    def assert_invalid(self, reason, command="inspect"):
        code, out, err = self.run_main(command)
        self.assertEqual((code, err), (1, ""))
        self.assertEqual(json.loads(out)["error"], reason)
        if command == "release-gate":
            self.assertIs(json.loads(out)["authorize_publish"], False)
            self.assertEqual(json.loads(out)["status"], "BLOCKED")

    def test_verified_evidence_distinguishes_candidate_and_history(self):
        self.report["detail"] = SYNTHETIC_VALUE
        self.save_report()
        code, out, err = self.run_main()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out), {
            "status": "VERIFIED_EVIDENCE",
            "default_mode": "OBSERVE",
            "default_rewrite": "DENY",
            "boot_lines": {"boot3": "VERIFIED_EVIDENCE", "boot4": "VERIFIED_EVIDENCE"},
            "candidate_artifacts": "NOT AVAILABLE",
            "historical_gates": dict.fromkeys(cli.HISTORICAL, "HISTORICAL PASS"),
        })

    def test_text_output_uses_fixed_public_labels(self):
        code, out, err = self.run_main(args=["inspect"])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("default_mode=OBSERVE\n", out)
        self.assertIn("default_rewrite=DENY\n", out)
        self.assertIn("historical_gates.G4=HISTORICAL PASS\n", out)

    def test_valid_candidate_does_not_enable_publication(self):
        self.prepare_artifacts()
        code, out, err = self.run_main()
        self.assertEqual((code, json.loads(out)["candidate_artifacts"], err), (0, "VERIFIED", ""))
        code, out, err = self.run_main("release-gate")
        self.assertEqual((code, err), (2, ""))
        self.assertEqual(json.loads(out), {
            "status": "BLOCKED",
            "authorize_publish": False,
            "phase6_evidence": "VERIFIED_EVIDENCE",
            "candidate_artifacts": "VERIFIED",
            "operator_approvals": "MISSING",
            "blockers": cli.BLOCKING_POLICY,
        })

    def test_local_self_attestation_has_no_publishing_authority(self):
        self.write_json(cli.APPROVALS, {
            "schema_version": 1, "authorize_publish": True, "operator": SYNTHETIC_VALUE,
            **dict.fromkeys(cli.BLOCKING_POLICY, "PASS"),
        })
        code, out, err = self.run_main("release-gate")
        self.assertEqual((code, err), (2, ""))
        self.assertEqual(json.loads(out)["operator_approvals"], "UNVERIFIED")
        self.assertIs(json.loads(out)["authorize_publish"], False)

    def test_changed_release_policy_is_invalid(self):
        self.policy["formal_publisher"] = "PASS"
        self.write_json(cli.POLICY, self.policy)
        self.assert_invalid("INVALID_RELEASE_POLICY", "release-gate")

    def test_missing_validation_for_gate_is_blocked(self):
        self.write_json("evidence/PHASE6-VALIDATION.json", self.report)
        (self.root / cli.VALIDATION).unlink()
        self.assert_invalid("MISSING_INPUT")
        code, out, err = self.run_main("release-gate")
        self.assertEqual((code, err), (2, ""))
        gate = json.loads(out)
        self.assertEqual(gate["phase6_evidence"], "NOT AVAILABLE")
        self.assertIs(gate["authorize_publish"], False)

    def test_invalid_current_evidence_never_falls_back_to_historical_evidence(self):
        self.write_json("evidence/PHASE6-VALIDATION.json", self.report)
        self.report["status"] = "FAIL"
        self.save_report()
        self.assert_invalid("PHASE6_INCOMPLETE")
        self.assert_invalid("PHASE6_INCOMPLETE", "release-gate")

    def test_missing_declared_source_is_invalid_for_gate(self):
        (self.root / next(iter(self.report["source_sha512"]))).unlink()
        self.assert_invalid("MISSING_INPUT", "release-gate")

    def test_missing_boot_line_is_invalid(self):
        del self.report["boot_lines"]["boot4"]
        self.save_report()
        self.assert_invalid("PHASE6_INCOMPLETE")

    def test_bare_pass_does_not_validate(self):
        self.write_json(cli.VALIDATION, {"schema_version": 1, "phase": 6, "status": "PASS"})
        self.assert_invalid("PHASE6_INCOMPLETE")

    def test_missing_or_duplicate_step_is_invalid(self):
        steps = self.report["steps"]
        self.report["steps"] = steps[:-1]
        self.save_report()
        self.assert_invalid("INVALID_VALIDATION_STEPS")
        self.report["steps"] = [steps[0], *steps[:-1]]
        self.save_report()
        self.assert_invalid("INVALID_VALIDATION_STEPS")

    def test_unconfirmed_process_shutdown_is_invalid(self):
        self.report["steps"][0]["process_group_quiesced"] = SYNTHETIC_VALUE
        self.save_report()
        self.assert_invalid("INVALID_VALIDATION_STEPS")

    def test_missing_or_duplicate_boot_scenario_is_invalid(self):
        boot = self.report["boot_lines"]["boot4"]
        scenarios = boot["scenarios"]
        for invalid in (scenarios[:-1], [scenarios[0], *scenarios[:-1]]):
            with self.subTest(scenarios=invalid):
                boot["scenarios"] = invalid
                self.save_report()
                self.assert_invalid("INVALID_BOOT_CONTRACT")

    def test_missing_negative_contract_proof_is_invalid(self):
        negative = self.report["negative_consumers"][0]
        negative["protocol"]["scenarios"] = [SYNTHETIC_VALUE]
        self.save_report()
        self.assert_invalid("INVALID_NEGATIVE_CONTRACT")

    def test_boot_consumer_graph_contamination_is_invalid(self):
        self.report["boot_lines"]["boot3"]["resolution"]["artifacts"].append("dev.udak:starter-boot4:0.1.0-poc")
        self.save_report()
        self.assert_invalid("INVALID_CONSUMER_RESOLUTION")

    def test_bom_consumer_proof_is_required(self):
        del self.report["bom_consumer"]
        self.save_report()
        self.assert_invalid("INVALID_BOM_CONTRACT")

    def test_bom_consumer_assertions_match_the_boot4_pom_contract(self):
        self.report["bom_consumer"]["protocol"].update(self.protocol("BOOT4", cli.POSITIVE_SCENARIOS, 78))
        self.save_report()
        self.assert_invalid("INVALID_BOM_CONTRACT")

    def test_boot4_pom_and_bom_graphs_cannot_be_swapped(self):
        boot4 = self.report["boot_lines"]["boot4"]
        bom = self.report["bom_consumer"]
        boot4["resolution"], bom["resolution"] = bom["resolution"], boot4["resolution"]
        self.save_report()
        self.assert_invalid("INVALID_CONSUMER_RESOLUTION")

    def test_missing_pom_graph_pin_is_invalid(self):
        del self.report["dependencies"]["consumer_lanes"]["starter-boot4"]
        self.save_report()
        self.assert_invalid("INVALID_DEPENDENCY_PROOF")

    def test_bom_jar_hash_must_match_frozen_manifest(self):
        self.report["bom_consumer"]["resolution"]["artifact_sha512"]["commons-logging:commons-logging:1.3.6"] = "0" * 128
        self.save_report()
        self.assert_invalid("INVALID_CONSUMED_ARTIFACTS")

    def test_dependency_proof_requires_the_declared_pin_hash(self):
        self.report["dependencies"]["sha512"] = "0" * 128
        self.save_report()
        self.assert_invalid("INVALID_DEPENDENCY_PROOF")

    def test_report_hash_cannot_excuse_an_invalid_pin_manifest(self):
        pins = self.dependency_pins()
        pins["artifacts"][0]["published_checksum"] = SYNTHETIC_VALUE
        path = self.write_json(cli.DEPENDENCY_PINS, pins)
        digest = hashlib.sha512(path.read_bytes()).hexdigest()
        self.report["manifest_sha512"][cli.DEPENDENCY_PINS] = digest
        self.report["dependencies"]["sha512"] = digest
        self.save_report()
        self.assert_invalid("INVALID_DEPENDENCY_PINS")

    def test_candidate_cleanup_must_report_no_remaining_directory(self):
        self.report["candidate_cleanup"]["temporary_directory_remaining"] = True
        self.save_report()
        self.assert_invalid("INVALID_CLEANUP_PROOF")

    def test_reproducibility_requires_matching_repository_digests(self):
        path = next(iter(cli.REPOSITORY_ARTIFACTS))
        self.report["reproducibility"]["artifact_sha512"][path] = "0" * 128
        self.save_report()
        self.assert_invalid("INVALID_REPRODUCIBILITY")

    def test_binary_compatibility_self_attestation_is_rejected(self):
        self.report["api_compatibility"]["binary_backward_compatibility"] = "PASS"
        self.save_report()
        self.assert_invalid("INVALID_API_COMPATIBILITY")

    def test_publication_claim_in_evidence_is_invalid(self):
        self.report["authorize_publish"] = True
        self.save_report()
        self.assert_invalid("PHASE6_INCOMPLETE", "release-gate")

    def test_missing_required_harness_is_invalid(self):
        self.report["harness_sha512"].pop("tools/udak-cli.py")
        self.save_report()
        self.assert_invalid("INVALID_INPUT_INVENTORY")

    def test_missing_baseline_manifest_from_inventory_is_invalid(self):
        del self.report["manifest_sha512"][cli.BASELINE_PINS]
        self.save_report()
        self.assert_invalid("INVALID_INPUT_INVENTORY", "release-gate")

    def test_missing_baseline_manifest_file_is_invalid(self):
        (self.root / cli.BASELINE_PINS).unlink()
        self.assert_invalid("MISSING_INPUT", "release-gate")

    def test_tampered_baseline_manifest_is_invalid(self):
        self.write_json(cli.BASELINE_PINS, {"schema_version": 2})
        self.assert_invalid("HASH_MISMATCH", "release-gate")

    def test_tampered_source_is_invalid(self):
        path = next(iter(self.report["source_sha512"]))
        self.write(path, SYNTHETIC_VALUE.encode())
        self.assert_invalid("HASH_MISMATCH")

    def test_partial_artifacts_are_invalid(self):
        first = self.report["artifacts"][0]
        self.write(first["path"], self.artifact_content)
        self.assert_invalid("PARTIAL_ARTIFACTS")

    def test_tampered_artifact_is_invalid(self):
        self.prepare_artifacts()
        self.write(self.report["artifacts"][0]["path"], b"x" * len(self.artifact_content))
        self.assert_invalid("HASH_MISMATCH", "release-gate")

    def test_artifact_size_limit_checked_from_inventory(self):
        self.report["artifacts"][0]["size"] = cli.MAX_ARTIFACT_BYTES + 1
        self.save_report()
        self.assert_invalid("INVALID_ARTIFACT_RECORD")

    def test_total_candidate_size_limit_checked_from_inventory(self):
        for row in self.report["artifacts"]:
            row["size"] = cli.MAX_ARTIFACT_BYTES
        self.save_report()
        self.assert_invalid("INVALID_ARTIFACT_INVENTORY")

    def test_path_from_artifact_record_is_never_opened(self):
        self.report["artifacts"][0]["path"] = f"build/phase6/{SYNTHETIC_VALUE}.env.local"
        self.save_report()
        with patch.object(cli, "regular_file", wraps=cli.regular_file) as opened:
            self.assert_invalid("INVALID_ARTIFACT_INVENTORY")
        self.assertNotIn(self.report["artifacts"][0]["path"], [call.args[1] for call in opened.call_args_list])

    def test_secret_escape_and_outside_module_paths_are_rejected_before_hashing(self):
        for path in (
            f"core/src/test/java/{SYNTHETIC_VALUE}.env.backup",
            f"core/src/test/java/password/Fixture.java",
            f"core/src/test/java/../{SYNTHETIC_VALUE}.java",
            f"/{SYNTHETIC_VALUE}",
            "unknown/src/main/java/Fixture.java",
        ):
            with self.subTest(path=path):
                self.report["source_sha512"][path] = "a" * 128
                self.save_report()
                with patch.object(cli, "verify_digest") as hash_file:
                    self.assert_invalid("INVALID_INPUT_INVENTORY")
                hash_file.assert_not_called()
                del self.report["source_sha512"][path]

    def test_symlink_report_is_rejected_before_opening_target(self):
        path = self.root / cli.VALIDATION
        path.unlink()
        outside = self.root.parent / SYNTHETIC_VALUE
        outside.write_bytes(b"synthetic untrusted target")
        path.symlink_to(outside)
        with patch.object(cli.os, "open", wraps=os.open) as opened:
            self.assert_invalid("UNSAFE_FILE")
        self.assertNotIn(path.name, [call.args[0] for call in opened.call_args_list])

    def test_symlink_ancestor_is_rejected(self):
        evidence = self.root / "evidence"
        external = self.root.parent / SYNTHETIC_VALUE
        evidence.rename(external)
        evidence.symlink_to(external, target_is_directory=True)
        self.assert_invalid("UNSAFE_OR_UNREADABLE_INPUT")

    def test_symlink_repository_ancestor_is_rejected(self):
        alias = self.root.parent / SYNTHETIC_VALUE
        alias.symlink_to(self.root, target_is_directory=True)
        code, out, err = self.run_main(root=alias)
        self.assertEqual((code, json.loads(out)["error"], err), (1, "UNSAFE_OR_UNREADABLE_INPUT", ""))

    def test_hard_link_is_rejected_before_opening(self):
        path = self.root / cli.VALIDATION
        os.link(path, self.root.parent / SYNTHETIC_VALUE)
        with patch.object(cli.os, "open", wraps=os.open) as opened:
            self.assert_invalid("UNSAFE_FILE")
        self.assertNotIn(path.name, [call.args[0] for call in opened.call_args_list])

    def test_non_regular_file_is_rejected(self):
        path = self.root / cli.VALIDATION
        path.unlink()
        os.mkfifo(path)
        self.assert_invalid("UNSAFE_FILE")

    def test_oversize_report_is_rejected_before_opening(self):
        path = self.root / cli.VALIDATION
        with path.open("wb") as stream:
            stream.truncate(cli.MAX_JSON_BYTES + 1)
        with patch.object(cli.os, "open", wraps=os.open) as opened:
            self.assert_invalid("INVALID_FILE_SIZE")
        self.assertNotIn(path.name, [call.args[0] for call in opened.call_args_list])

    def test_strict_json_rejects_duplicates_nonfinite_and_malformed_bytes(self):
        for contents in (
            b'{"schema_version": 1, "schema_version": 1}',
            b'{"schema_version": 1, "unsafe": NaN}',
            b'{"schema_version": 1, "unsafe": 1e999}',
            b'{"schema_version": 1, "unsafe": "\xff"}',
            b'{"schema_version": 1, "unsafe":',
        ):
            with self.subTest(contents=contents):
                self.write(cli.VALIDATION, contents)
                self.assert_invalid("INVALID_JSON")

    def test_argument_errors_never_echo_user_input(self):
        for command, argv in (
            ("inspect", ["inspect", "--root", SYNTHETIC_VALUE]),
            ("inspect", ["inspect", "--format", SYNTHETIC_VALUE]),
            ("inspect", [SYNTHETIC_VALUE]),
            ("release-gate", ["--publish", SYNTHETIC_VALUE]),
        ):
            with self.subTest(command=command, argv=argv):
                self.assertEqual(self.run_main(command, args=argv), (2, "", "INVALID_ARGUMENTS\n"))


if __name__ == "__main__":
    unittest.main()
