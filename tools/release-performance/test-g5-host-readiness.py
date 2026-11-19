#!/usr/bin/env python3
"""Exercise the G5 host gate without starting any workload."""
from contextlib import ExitStack, nullcontext, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    'g5_performance', Path(__file__).resolve().parents[1] / 'run-g5-performance.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

RUN_ID = 'HOST-GATE-TEST'


class HostReadinessTest(unittest.TestCase):
    def setUp(self):
        self.contexts = ExitStack()
        self.addCleanup(self.contexts.close)
        self.now = 0
        self.sample_times = []
        clock = SimpleNamespace(monotonic=lambda: self.now, sleep=self.advance_clock)
        self.contexts.enter_context(patch.object(runner, 'time', clock))
        self.probe = self.contexts.enter_context(patch.object(runner.subprocess, 'run'))

    def advance_clock(self, seconds):
        self.now += seconds

    def host_preflight(self):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['run-g5-performance.py', '--host-preflight']), redirect_stdout(output):
            code = runner.main()
        return code, json.loads(output.getvalue())

    def test_host_preflight_samples_the_full_stable_window(self):
        def normal_pressure(*args, **kwargs):
            self.sample_times.append(self.now)
            return SimpleNamespace(stdout=b'1\n')

        self.probe.side_effect = normal_pressure
        self.assertEqual(self.host_preflight(), (0, {
            'status': 'PASS', 'stable_seconds': 15, 'workload_run_claimed': False,
        }))
        self.assertEqual(self.sample_times, [0, 2, 4, 6, 8, 10, 12, 14, 15])

    def test_host_preflight_blocks_pressure_and_unknown_status(self):
        timeout = runner.subprocess.TimeoutExpired('sysctl', timeout=3)
        for readings, reason in [
            ([SimpleNamespace(stdout=b'1\n'), SimpleNamespace(stdout=b'2\n')], 'HOST_MEMORY_PRESSURE'),
            ([SimpleNamespace(stdout=b'4\n')], 'HOST_MEMORY_PRESSURE'),
            ([SimpleNamespace(stdout=b'unknown\n')], 'HOST_PRESSURE_UNAVAILABLE'),
            ([OSError()], 'HOST_PRESSURE_UNAVAILABLE'),
            ([timeout], 'HOST_PRESSURE_UNAVAILABLE'),
        ]:
            with self.subTest(reason=reason, readings=readings):
                self.probe.side_effect = readings
                self.assertEqual(self.host_preflight(), (2, {
                    'status': 'BLOCKED', 'reason': reason, 'workload_run_claimed': False,
                }))

    def isolated_run(self):
        root = Path(self.contexts.enter_context(TemporaryDirectory()))
        self.contexts.enter_context(patch.object(runner, 'ROOT', root))
        approval, _ = runner.run_paths(RUN_ID)
        self.contexts.enter_context(patch.object(runner, 'input_hashes', return_value={approval: 'fake-digest'}))
        profile = self.contexts.enter_context(patch.object(runner, 'run_profile'))
        marker = root / '.git' / 'udak-product-g5' / f'{RUN_ID}.claimed'
        return root, profile, marker

    def test_pressure_before_preparation_blocks_workspace(self):
        _, profile, marker = self.isolated_run()
        workspace = self.contexts.enter_context(patch.object(runner.schema, 'workspace'))
        self.probe.return_value = SimpleNamespace(stdout=b'2\n')
        result = {'workload_run_claimed': False}

        with self.assertRaisesRegex(runner.HostReadinessError, 'HOST_MEMORY_PRESSURE'):
            runner.run({}, result, RUN_ID)

        workspace.assert_not_called()
        profile.assert_not_called()
        self.assertFalse(result['workload_run_claimed'])
        self.assertFalse(marker.exists())

    def test_pressure_after_preparation_does_not_claim_or_start_a_profile(self):
        root, profile, marker = self.isolated_run()
        workspace = self.contexts.enter_context(
            patch.object(runner.schema, 'workspace', return_value=nullcontext((root, {}))))
        self.contexts.enter_context(patch.object(runner.schema, 'pinned_drivers', return_value=([], {})))
        self.contexts.enter_context(patch.object(runner.schema.g2.phase2, 'dependencies', return_value=([], {})))
        compile_fixture = self.contexts.enter_context(patch.object(runner, 'compile_fixture'))
        names = ('POSTGRESQL', 'MYSQL')
        plan = {'profiles': {name: {'server_version': 'test-version'} for name in names}}
        pilot = {'profiles': {name: {'native_runtime': {'server_sha256': 'fake-hash'}} for name in names}}
        self.contexts.enter_context(patch.object(runner.review, 'read', return_value=pilot))
        self.contexts.enter_context(patch.object(runner, 'authorized', return_value=plan))
        self.contexts.enter_context(patch.object(runner.native, '_fingerprint',
                                                  return_value={'server_sha256': 'fake-hash', 'version': 'test-version'}))
        self.probe.side_effect = [SimpleNamespace(stdout=b'1\n')] * 9 + [SimpleNamespace(stdout=b'2\n')]
        result = {'workload_run_claimed': False}

        with self.assertRaisesRegex(runner.HostReadinessError, 'HOST_MEMORY_PRESSURE'):
            runner.run(plan, result, RUN_ID)

        workspace.assert_called_once()
        compile_fixture.assert_called_once()
        profile.assert_not_called()
        self.assertFalse(result['workload_run_claimed'])
        self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
