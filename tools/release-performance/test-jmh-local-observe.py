#!/usr/bin/env python3
"""Bounded process tests. No JMH measurement or DB is started."""

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
path = Path(__file__).with_name("run-jmh-local-observe.py")
spec = importlib.util.spec_from_file_location("local_jmh", path)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
guard = runner.guard


class GuardTest(unittest.TestCase):
    def fixture(self, script, *, wall=3, rss=128 * 1024**2, cpu=2, watch=False):
        schema = runner.diagnosis.g5_verifier().schema
        with schema.workspace() as (work, cleanup):
            result = guard.run_owned([str(Path(sys.executable).resolve()), "-I", "-S", "-c", script],
                                     work, work / "fixture.output", wall_seconds=wall,
                                     rss_bytes=rss, cpu_seconds=cpu, watch_pressure=watch, poll_seconds=0.05)
            self.assertTrue(result["child_reaped"] and result["process_group_quiesced"])
            self.assertGreater(result["cpu_seconds"], 0)
            self.assertGreater(result["peak_tree_rss_bytes"], 0)
        self.assertEqual(cleanup["status"], "PASS")
        self.assertFalse(cleanup["remaining"])
        self.assertFalse(work.exists())
        return result

    def test_reap_and_cleanup_after_normal_run(self):
        self.assertEqual(self.fixture("pass")["status"], "PASS")

    def test_wall_stop_and_cleanup(self):
        record = self.fixture("import time; time.sleep(10)", wall=0.15)
        self.assertEqual((record["status"], record["reason"]), ("STOPPED", "WALL_LIMIT"))

    def test_rss_stop_and_cleanup(self):
        record = self.fixture("import time; data = b'x' * (32 * 1024**2); time.sleep(10)", rss=16 * 1024**2)
        self.assertEqual(record["reason"], "RSS_LIMIT")
        self.assertGreater(record["peak_tree_rss_bytes"], 16 * 1024**2)

    def test_cpu_stop_and_cleanup(self):
        record = self.fixture("while True: pass", cpu=1)
        self.assertEqual(record["reason"], "CPU_LIMIT")
        self.assertGreaterEqual(record["cpu_seconds"], 0.9)

    def test_unexpected_child_stops_the_owned_group(self):
        script = """
import signal, subprocess, sys
child = subprocess.Popen([sys.executable, "-I", "-S", "-c", "import time; time.sleep(10)"])
def stop(_signal, _frame):
    child.wait(timeout=1)
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
child.wait()
"""
        self.assertEqual(self.fixture(script)["reason"], "UNEXPECTED_CHILD")

    def test_pressure_warning_stops_child(self):
        with patch.object(guard, "memory_pressure", return_value=2):
            record = self.fixture("import time; time.sleep(10)", watch=True)
        self.assertEqual(record["reason"], "HOST_MEMORY_PRESSURE")

    def test_cpu_time_formats(self):
        self.assertEqual(guard.seconds("2:05.50"), 125.5)
        self.assertEqual(guard.seconds("1-01:00:00"), 90000)


class LauncherTest(unittest.TestCase):
    def test_unapproved_run_cannot_start_preparation_or_workload(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(runner, "ROOT", Path(tmp)),
            patch.object(runner, "proposal", return_value={"authorized_runs": 1}),
            patch.object(runner, "execute") as execute,
            patch.object(sys, "argv", [str(path), "--run", "SYNTHETIC-NO-APPROVAL"]),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(runner.main(), 2)
            execute.assert_not_called()
            result = json.loads(output.getvalue())
            self.assertEqual(result["reason"], "APPROVAL_REQUIRED")
            self.assertFalse(result["workload_started"])

    def test_proposal_binds_measurement_inputs_without_approval(self):
        plan = runner.proposal("SYNTHETIC-PROPOSAL")
        self.assertEqual(plan["phase"], "A/A")
        self.assertEqual(plan["benchmark"], runner.BENCHMARK)
        self.assertEqual(plan["authorized_runs"], 1)
        self.assertIn("tools/release-performance/jmh-process-guard.py", plan["inputs_sha256"])
        self.assertNotIn("approval_basis", plan)

    def test_fixed_jmh_command_and_synthetic_output_protocol(self):
        metric = {"benchmark": runner.BENCHMARK, "mode": "avgt", "forks": 0, "threads": 1,
                  "primaryMetric": {"score": 120, "scoreUnit": "ns/op"},
                  "secondaryMetrics": {"gc.alloc.rate.norm": {"score": 24, "scoreUnit": "B/op"}}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, "executable", return_value="/test/java"):
            work = Path(tmp).resolve()

            def step(name, command, timeout):
                self.assertEqual((name, timeout), ("sample-0", 30))
                self.assertEqual(command[command.index("-f") + 1], "0")
                self.assertEqual(command[command.index("-t") + 1], "1")
                self.assertEqual(command[command.index("-prof") + 1], "gc")
                output = Path(command[command.index("-rff") + 1])
                self.assertEqual(output.parent, work)
                output.write_text(json.dumps([metric]))

            batch = SimpleNamespace(work=work, step=step)
            self.assertEqual(runner.sample(batch, "fixed-runtime", 0), [120, 24])
            metric["primaryMetric"]["scoreUnit"] = "ms/op"
            with self.assertRaises(ValueError):
                runner.sample(batch, "fixed-runtime", 0)

    def test_batch_reserves_remaining_cpu_before_each_fork(self):
        report = {"steps": {}}
        batch = runner.Batch(Path("/tmp"), report, True, lambda: False)
        batch.cpu_used = runner.limits["tree_cpu_seconds"] - 4
        with patch.object(guard, "run_owned", return_value={"status": "PASS", "cpu_seconds": 4}) as owned:
            with self.assertRaisesRegex(runner.Stopped, "BATCH_LIMIT_OR_CANCEL"):
                batch.step("sample-0", ["/test/java"], 30)
            self.assertEqual(owned.call_args.kwargs["cpu_seconds"], 4)
        with patch.object(guard, "run_owned") as owned:
            with self.assertRaisesRegex(runner.Stopped, "BATCH_LIMIT_OR_CANCEL"):
                batch.step("sample-1", ["/test/java"], 30)
            owned.assert_not_called()

    def test_uncertain_cleanup_preserves_workspace(self):
        paths = []

        def unavailable(batch, *_args):
            paths.append(batch.work)
            raise guard.CleanupUnconfirmed("SYNTHETIC_UNKNOWN")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".git").mkdir()
            report = {"steps": {}}
            with (
                patch.object(runner, "ROOT", root),
                patch.object(runner, "dependencies", return_value={}),
                patch.object(runner, "link", side_effect=unavailable),
                self.assertRaisesRegex(RuntimeError, "JMH cleanup unconfirmed"),
            ):
                runner.execute(report, None, lambda: False)
            work, = paths
            self.addCleanup(work.rmdir)  # The injected fixture started no child and created no files.
            self.assertTrue(work.is_dir())
            self.assertEqual(report["cleanup"]["status"], "PRESERVED_UNKNOWN")
            self.assertFalse(report["resources"]["cleanup_confirmed"])


if __name__ == "__main__":
    unittest.main()
