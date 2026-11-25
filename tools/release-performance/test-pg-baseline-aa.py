"""Offline checks for same-path PostgreSQL results and measured host quietness."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from macos_cpu_window import CpuWindow, quiet, sample

spec = importlib.util.spec_from_file_location('baseline_aa', Path(__file__).with_name('run-pg-baseline-aa.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
PLAN = {'absolute_noise_budget_ns': 30635, 'arm_p95_gap_budget_percent': 5,
        'limits': {'min_start_spacing_ns': 125_000_000, 'max_starts_per_second': 8}}


def series(label, numbers):
    return label + ' ' + ','.join(map(str, numbers))


def protocol(a, b):
    return '\n'.join((
        'PG_BASELINE_AA profile=POSTGRESQL starts=80 completed=80 warmup_per_arm=8 measured_per_arm=32'
        ' verified_rows=80 events=0 errors=0 max_in_flight=1 max_rolling_second=8 min_spacing_ns=125000000',
        series('A_NS', a), series('B_NS', b), series('SCHEDULE', runner.workload_order()),
        series('GAPS_NS', [125_000_000] * 79),
    ))


class BaselineAA(unittest.TestCase):
    def test_same_row_and_both_orders(self):
        schedules = list(runner.workload_order())
        self.assertEqual(80, len(schedules))
        orders = {}
        for block in range(4):
            for offset in range(block * 20 + 4, (block + 1) * 20, 2):
                first, second = schedules[offset:offset + 2]
                self.assertEqual(first // 2, second // 2)
                self.assertNotEqual(first % 2, second % 2)
                orders.setdefault(first // 2, []).append(first % 2)
        self.assertEqual(set(range(1, 9)), set(orders))
        for choices in orders.values():
            self.assertEqual([0, 0, 1, 1], sorted(choices))

    def test_paired_variation_can_fail_with_identical_arm_p95(self):
        a = [400000, 500000] * 16
        b = list(reversed(a))
        result = runner.assess(protocol(a, b), PLAN)
        self.assertEqual('NOT REPRODUCIBLE', result['status'])
        self.assertEqual(0, result['p95_gap_percent_of_mean'])
        self.assertEqual(100000, result['paired_abs_p95_ns'])

    def test_nearby_samples_pass_under_quiet_host_budget(self):
        result = runner.assess(protocol([600000] * 32, [620000] * 32), PLAN)
        self.assertEqual('PASS', result['status'])
        self.assertEqual(20000, result['paired_abs_p95_ns'])
        self.assertEqual(0, result['pairs_above_reference_allowance'])

    def test_missing_host_observations_and_contention_fail(self):
        good = {'cpu': {'interval_ns': 5_000_000_001, 'total_ticks': 1000, 'idle_ticks': 900}, 'memory_pressure': 1}
        rows = [good] * runner.FLOOR['samples']
        self.assertTrue(runner.ready(rows, runner.FLOOR))
        self.assertFalse(runner.ready(rows[:-1], runner.FLOOR))
        self.assertFalse(runner.ready([*rows[:-1], {**good, 'memory_pressure': 2}], runner.FLOOR))
        busy = {**good, 'cpu': {**good['cpu'], 'idle_ticks': 899}}
        self.assertFalse(runner.ready([*rows[:-1], busy], runner.FLOOR))

    def test_live_coverage_requires_quiet_contiguous_receipt(self):
        row = {'interval_ns': 1_000_000_000, 'total_ticks': 1000, 'idle_ticks': 810}
        proof = {'live_host_samples': [row] * 10, 'live_window': {'elapsed_ns': 10_000_001_000, 'tail_ns': 1000}}
        self.assertTrue(runner.live_quiet(proof, {'limit': runner.FLOOR}))
        proof['live_window']['elapsed_ns'] += 1
        self.assertFalse(runner.live_quiet(proof, {'limit': runner.FLOOR}))

    def test_cpu_window_rejects_competing_load(self):
        clock = iter((0, 1_000_000_001)).__next__
        ticks = iter(((0, 0, 0, 0), (10, 10, 60, 20))).__next__
        window = CpuWindow([], 800, ticks, clock)
        with self.assertRaisesRegex(ValueError, 'HOST_CPU_OVERLAP'):
            window.observe()
        self.assertFalse(quiet(window.samples[0], 800, 3_000_000_000))
        with self.assertRaisesRegex(ValueError, 'INVALID_CPU_COUNTER'):
            sample((10, 0, 0, 0), (9, 0, 99, 0), 1)

    def test_wrong_schedule_or_events_fail(self):
        base = protocol([600000] * 32, [610000] * 32)
        for bad in (base.replace('events=0', 'events=1'), base.replace('SCHEDULE 2,3', 'SCHEDULE 3,2')):
            with self.assertRaisesRegex(ValueError, 'COUNTS_OR_ORDER'):
                runner.assess(bad, PLAN)

    def test_unapproved_run_cannot_sample_or_start_database(self):
        with (tempfile.TemporaryDirectory() as folder, patch.object(runner, 'ROOT', Path(folder)),
              patch.object(runner, 'cpu_reader') as probe, patch.object(runner.native, 'instance') as database):
            with self.assertRaisesRegex(ValueError, 'SEPARATE_APPROVAL_REQUIRED'):
                runner.run(PLAN, {})
            probe.assert_not_called()
            database.assert_not_called()

    def test_preflight_failure_does_not_build_or_consume(self):
        with (tempfile.TemporaryDirectory() as folder, patch.object(runner, 'ROOT', Path(folder)),
              patch.object(runner, 'approval_sha'), patch.object(runner, 'preparation'),
              patch.object(runner, 'cpu_reader'), patch.object(runner, 'preflight', return_value=[]),
              patch.object(runner, 'build') as build, patch.object(runner.guard, 'claim') as claim):
            with self.assertRaisesRegex(ValueError, 'HOST_NOT_QUIET'):
                runner.run({**PLAN, 'limit': runner.FLOOR}, {})
            build.assert_not_called()
            claim.assert_not_called()


if __name__ == '__main__':
    unittest.main()
