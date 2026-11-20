#!/usr/bin/env python3
"""Offline regressions for the native SQL Server runner and evidence verifier."""
from contextlib import ExitStack, contextmanager, redirect_stdout
import hashlib
import importlib.util
from io import BytesIO, StringIO
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def load(filename):
    spec = importlib.util.spec_from_file_location(filename, HERE / (filename + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verifier = load("verify-sqlserver-g5")
runner = verifier.load_runner()
host = load("check-sqlserver-host")

FUNCTIONAL = "SQLSERVER_G5 FUNCTIONAL PASS 48 2 4 250000000"
APPROVAL_DIGEST = "a" * 128
INPUTS = {"tools/release-provider/SqlServerG5Fixture.java": "b" * 128}


def synthetic_report():
    return {
        "schema_version": 1,
        "requirement": "RELEASE-025",
        "status": "PASS",
        "sqlserver_g5": "PASS",
        "profile": "SQLSERVER",
        "platform": "linux/amd64",
        "image": runner.get_pin()["image"],
        "server_version": "16.0.1000.1",
        "driver_version": "13.6.2.0",
        "input_sha512": dict(INPUTS),
        "approval_sha512": APPROVAL_DIGEST,
        "limits": dict(runner.LIMITS),
        "checks": dict.fromkeys(verifier.REQUIRED_CHECKS, True),
        "concurrency": runner.parse_functional(FUNCTIONAL.encode("ascii") + b"\n"),
        "cleanup": {"status": "PASS", "remaining": False},
        "fixture_receipts": {
            "functional": FUNCTIONAL,
            "crash_recover": "SQLSERVER_G5 RECOVER PASS",
            "clean_recover": "SQLSERVER_G5 GRACEFUL PASS",
        },
        "crash_exit_code": 137,
    }


class ReportValidation(unittest.TestCase):
    def verify(self, report):
        return verifier.validate(report, runner, INPUTS, APPROVAL_DIGEST)

    def test_synthetic_report_verifies(self):
        report = synthetic_report()
        result = self.verify(report)
        for capability in verifier.CAPABILITIES:
            self.assertEqual(result[capability], "PASS")
        self.assertEqual(result["native_execution"], {
            name: report[name] for name in ("image", "platform", "server_version", "driver_version")
        })

    def test_changed_identity_is_rejected(self):
        for field, value in {
            "platform": "linux/arm64",
            "image": "mcr.microsoft.com/mssql/server@sha256:" + "0" * 64,
            "server_version": "15.0.1000.1",
            "driver_version": "13.6.1.0",
        }.items():
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify({**synthetic_report(), field: value})

    def test_changed_approval_or_source_is_rejected(self):
        for field, value in {
            "approval_sha512": "c" * 128,
            "input_sha512": dict.fromkeys(INPUTS, "d" * 128),
        }.items():
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify({**synthetic_report(), field: value})

    def test_missing_cleanup_or_bad_crash_exit_is_rejected(self):
        for change in (
            {"cleanup": {"status": "PASS"}},
            {"cleanup": {"status": "PASS", "remaining": True}},
            {"crash_exit_code": 0},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify({**synthetic_report(), **change})
        report = synthetic_report()
        del report["checks"]["owned_cleanup"]
        with self.assertRaises(ValueError):
            self.verify(report)

    def test_spoofed_protocol_is_rejected(self):
        for field, receipt in (
            ("functional", "prefixed " + FUNCTIONAL),
            ("functional", FUNCTIONAL + "\n" + FUNCTIONAL),
            ("functional", FUNCTIONAL + " trailing"),
            ("crash_recover", "SQLSERVER_G5 GRACEFUL PASS"),
            ("clean_recover", "SQLSERVER_G5 RECOVER PASS"),
        ):
            with self.subTest(field=field, receipt=receipt), self.assertRaises(ValueError):
                report = synthetic_report()
                report["fixture_receipts"][field] = receipt
                self.verify(report)

    def test_concurrency_receipt_rejects_out_of_bound_measurements(self):
        for metrics in ("49 2 4 250000000", "48 3 4 250000000",
                        "48 2 5 250000000", "48 2 4 249999999"):
            with self.subTest(metrics=metrics), self.assertRaises(ValueError):
                report = synthetic_report()
                report["fixture_receipts"]["functional"] = "SQLSERVER_G5 FUNCTIONAL PASS " + metrics
                self.verify(report)

    def test_report_metrics_must_match_receipt(self):
        report = synthetic_report()
        metric = next(iter(report["concurrency"]))
        report["concurrency"][metric] += 1
        with self.assertRaises(ValueError):
            self.verify(report)

    def test_report_rejects_changed_limits(self):
        report = synthetic_report()
        report["limits"]["unapproved_limit"] = 1
        with self.assertRaises(ValueError):
            self.verify(report)

    def test_report_rejects_float_for_integer_limit(self):
        report = synthetic_report()
        limit = next(key for key, value in report["limits"].items() if type(value) is int)
        report["limits"][limit] = float(report["limits"][limit])
        with self.assertRaises(ValueError):
            self.verify(report)

    def test_assess_rejects_evidence_changed_during_read(self):
        report_bytes = json.dumps(synthetic_report())
        report_path = Mock()
        report_path.stat.return_value.st_size = len(report_bytes)
        report_path.read_text.return_value = report_bytes
        authorized_inputs = {
            **INPUTS, runner.APPROVAL: APPROVAL_DIGEST, runner.REPORT: "e" * 128,
        }
        mocked_runner = SimpleNamespace(
            APPROVAL=runner.APPROVAL,
            REPORT=runner.REPORT,
            LIMITS=runner.LIMITS,
            sources=lambda: tuple(INPUTS),
            authorized=Mock(),
            get_pin=runner.get_pin,
            parse_functional=runner.parse_functional,
            h=SimpleNamespace(
                hashes=Mock(side_effect=[
                    authorized_inputs, {**authorized_inputs, runner.REPORT: "f" * 128}
                ]),
                p5=SimpleNamespace(
                    p4=SimpleNamespace(approved_paths=Mock(return_value=[(runner.REPORT, report_path)]))
                ),
            ),
        )
        with patch.object(verifier, "load_runner", return_value=mocked_runner):
            with self.assertRaisesRegex(ValueError, "changed during assessment"):
                verifier.assess()
        mocked_runner.authorized.assert_called_once_with()

    def test_main_keeps_missing_evidence_not_run(self):
        with tempfile.TemporaryDirectory() as directory, StringIO() as stdout:
            with patch.object(verifier, "ROOT", Path(directory)), patch.object(sys, "argv", ["verifier"]):
                with redirect_stdout(stdout):
                    self.assertEqual(verifier.main(), 2)
            self.assertEqual(json.loads(stdout.getvalue()), {
                "evidence_review": "NOT RUN", "sqlserver_g5": "NOT RUN",
            })


class HostPreflight(unittest.TestCase):
    def test_non_native_host_stops_before_docker(self):
        for system, machine in (("darwin", "arm64"), ("linux", "aarch64")):
            with self.subTest(system=system, machine=machine):
                with (
                    patch.object(host.sys, "platform", system),
                    patch.object(host.os, "uname", return_value=SimpleNamespace(machine=machine)),
                    patch.object(host, "docker_fields") as docker,
                ):
                    self.assertEqual(host.probe(), ["HOST_LINUX_X86_64"])
                docker.assert_not_called()


class RunnerAuthorization(unittest.TestCase):
    def test_proposal_neither_approves_nor_starts_a_trial(self):
        with (
            patch.object(runner.h, "hashes", return_value=INPUTS),
            patch.object(runner, "authorized") as authorize,
            patch.object(runner, "preconditions") as preconditions,
            patch.object(runner, "perform") as perform,
            StringIO() as stdout,
            redirect_stdout(stdout),
        ):
            self.assertEqual(runner.main(["--proposal"]), 0)
            proposal = json.loads(stdout.getvalue())
            self.assertEqual(set(proposal), {
                "schema_version", "requirement", "profile", "platform", "image", "limits", "input_sha512",
            })
            self.assertEqual(proposal["input_sha512"], INPUTS)
        authorize.assert_not_called()
        preconditions.assert_not_called()
        perform.assert_not_called()

    def test_runner_refuses_wrong_arch_before_approval_or_execution(self):
        with (
            patch.object(runner.sys, "platform", "linux"),
            patch.object(runner.os, "uname", return_value=SimpleNamespace(machine="aarch64")),
            patch.object(runner.signal, "signal"),
            patch.object(runner.signal, "setitimer"),
            patch.object(runner, "perform") as perform,
            patch.object(runner, "preconditions") as preconditions,
            StringIO() as stdout,
            redirect_stdout(stdout),
        ):
            self.assertEqual(runner.main(["--run"]), 2)
            self.assertEqual(json.loads(stdout.getvalue()), {
                "status": "BLOCKED", "sqlserver_g5": "NOT RUN", "reason": "HOST_LINUX_X86_64",
            })
        perform.assert_not_called()
        preconditions.assert_not_called()

    def test_approval_requires_current_inputs_and_exact_scope(self):
        with patch.object(runner.h, "hashes", return_value=INPUTS):
            approved = runner.expected_approval()
            for document, valid in (
                (approved, True),
                ({**approved, "authorized_runs": True}, False),
                ({**approved, "platform": "linux/arm64"}, False),
                ({**approved, "input_sha512": dict.fromkeys(INPUTS, "c" * 128)}, False),
            ):
                with self.subTest(valid=valid, document=document):
                    raw = json.dumps(document).encode("ascii")
                    approved_file = Mock()
                    approved_file.open.return_value = BytesIO(raw)
                    paths = [(runner.APPROVAL, approved_file)]
                    with patch.object(runner.h.p5.p4, "approved_paths", return_value=paths):
                        if valid:
                            self.assertEqual(runner.authorized(), hashlib.sha512(raw).hexdigest())
                        else:
                            with self.assertRaisesRegex(runner.Gate, "APPROVAL_SCOPE"):
                                runner.authorized()

    def test_one_claim_cannot_be_reused_with_different_file_format(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(runner.h, "hashes", return_value=INPUTS),
            patch.object(runner, "HOST_PRIVATE", Path(directory)),
        ):
            first = hashlib.sha512(runner.canonical(runner.expected_approval())).hexdigest()
            reformatted = hashlib.sha512(json.dumps(runner.expected_approval(), indent=2).encode("ascii")).hexdigest()
            runner.claim_once(first)
            with self.assertRaises(FileExistsError):
                runner.claim_once(reformatted)
            self.assertEqual([claim.read_text(encoding="ascii") for claim in Path(directory).glob("*.claim")],
                             [first + "\n"])


class RunnerLifecycle(unittest.TestCase):
    CID = "1" * 64
    IMAGE = "sha256:" + "3" * 64

    @contextmanager
    def trial(self):
        engine = Mock()
        engine._created = {}
        engine._json.return_value = {"Id": self.CID}
        engine._owned.return_value = {"Profile": "SQLSERVER", "State": "created"}
        frame, version, namespace = b"synthetic frame", "16.0.1000.1", "/synthetic-netns"
        sandbox = Mock()
        sandbox.engine, sandbox.version = engine, version

        def journal(_path, record):
            sandbox.journal(record["phase"])

        def state(status):
            engine._owned.return_value = {"Profile": "SQLSERVER", "State": status}

        def start(_engine, _cid, _run, _cp, _password, _work, _label, previous, _handles):
            self.assertEqual(engine._owned.return_value["State"], previous)
            state("running")
            return frame, version, namespace

        def stop(*_args, **_kwargs):
            state("exited")

        def remove(_engine, method, path, _status):
            if method == "DELETE" and path.startswith("/containers/"):
                engine._owned.return_value = None

        engine.stop.side_effect = stop
        with ExitStack() as context:
            replacements = {
                "inventory": Mock(return_value=""),
                "start": Mock(side_effect=start),
                "phase": Mock(side_effect=[
                    FUNCTIONAL.encode("ascii") + b"\n",
                    b"SQLSERVER_G5 RECOVER PASS\n",
                    b"SQLSERVER_G5 GRACEFUL PASS\n",
                ]),
                "seed_and_crash": Mock(side_effect=stop),
                "stopped": Mock(),
                "action": Mock(side_effect=remove),
            }
            context.enter_context(patch.multiple(runner, **replacements))
            context.enter_context(patch.object(runner.managed.docker, "Engine", return_value=engine))
            context.enter_context(patch.object(runner.managed, "save", side_effect=journal))
            context.enter_context(patch.object(runner.secrets, "token_hex", side_effect=lambda size: "4" * (2 * size)))
            context.enter_context(patch.object(runner.host, "docker_fields", side_effect=[
                f"{self.IMAGE} 0 4G none", "0",
            ]))
            yield sandbox

    def test_success_reclaims_original_container_without_touching_networks(self):
        with self.trial() as trial:
            work, result = Path("/synthetic-workspace"), {}
            runner.run_db(work, "synthetic classpath", self.IMAGE, result)
            self.assertEqual([entry.args[-2] for entry in runner.start.call_args_list],
                             ["created", "exited", "exited"])
            runner.seed_and_crash.assert_called_once()
            self.assertEqual([entry.args[2] for entry in runner.phase.call_args_list],
                             ["FUNCTIONAL", "RECOVER", "GRACEFUL"])
            self.assertEqual(result["crash_exit_code"], 137)
            self.assertEqual(result["server_version"], trial.version)
            self.assertEqual(result["fixture_receipts"]["clean_recover"], "SQLSERVER_G5 GRACEFUL PASS")
            self.assertEqual(runner.action.call_args_list, [
                call(trial.engine, "DELETE", f"/containers/{self.CID}?force=false&v=false", (204,)),
            ])
            trial.journal.assert_called_with("CLOSED")

    def test_invalid_protocol_reclaims_owned_resources_without_result(self):
        with self.trial() as trial:
            runner.phase.side_effect = None
            runner.phase.return_value = b"SQLSERVER_G5 FUNCTIONAL PASS\n"
            result = {}
            with self.assertRaisesRegex(runner.Gate, "FUNCTIONAL_PROTOCOL"):
                runner.run_db(Path("/synthetic-workspace"), "synthetic classpath", self.IMAGE, result)
            self.assertEqual(result, {})
            runner.start.assert_called_once()
            runner.seed_and_crash.assert_not_called()
            runner.action.assert_called_once()
            trial.journal.assert_called_with("CLOSED")

    def test_lost_ownership_refuses_to_start_stop_or_delete(self):
        with self.trial() as trial:
            trial.engine._owned.return_value = None
            with self.assertRaisesRegex(runner.Gate, "OWNERSHIP_OR_STATE"):
                runner.run_db(Path("/synthetic-workspace"), "synthetic classpath", self.IMAGE, {})
            runner.start.assert_not_called()
            trial.engine.stop.assert_not_called()
            runner.action.assert_not_called()
            trial.journal.assert_called_with("CREATED")

    def test_wrong_prestart_image_reclaims_owned_container_without_starting(self):
        with self.trial() as trial:
            runner.host.docker_fields.side_effect = ["sha256:" + "9" * 64 + " 0 4G none", "0"]
            result = {}
            with self.assertRaisesRegex(runner.Gate, "PRESTART_IMAGE_MOUNTS_QUOTA"):
                runner.run_db(Path("/synthetic-workspace"), "synthetic classpath", self.IMAGE, result)
            self.assertEqual(result, {})
            runner.start.assert_not_called()
            runner.phase.assert_not_called()
            runner.action.assert_called_once()
            trial.journal.assert_called_with("CLOSED")

    def test_ambiguous_create_leaves_intent_open_without_lookups_or_deletes(self):
        with self.trial() as trial:
            trial.engine._json.return_value = {}
            with self.assertRaisesRegex(runner.Gate, "CREATE_OUTCOME_UNCONFIRMED"):
                runner.run_db(Path("/synthetic-workspace"), "synthetic classpath", self.IMAGE, {})
            runner.start.assert_not_called()
            trial.engine._owned.assert_not_called()
            runner.action.assert_not_called()
            trial.journal.assert_called_once_with("CONTAINER_CREATE_INTENT")

    def test_published_port_rejects_jdbc_before_opening_namespace(self):
        with (
            patch.object(runner, "owned"),
            patch.object(runner, "action"),
            patch.object(runner.host, "docker_fields", return_value="123 none 1 1 none"),
            patch.object(runner.os, "open") as open_namespace,
            patch.object(runner.subprocess, "run") as process,
            patch.object(runner, "phase") as fixture,
            ExitStack() as handles,
        ):
            with self.assertRaisesRegex(runner.Gate, "LOOPBACK_NAMESPACE"):
                runner.start(Mock(), self.CID, "synthetic-run", "synthetic classpath",
                             "synthetic", Path("/synthetic-workspace"), "initial", "created", handles)
            open_namespace.assert_not_called()
            process.assert_not_called()
            fixture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
