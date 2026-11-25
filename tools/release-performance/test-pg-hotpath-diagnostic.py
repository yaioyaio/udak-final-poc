"""Offline tests for PostgreSQL same-connection measurement and launch gating."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('pg_hotpath_runner', Path(__file__).with_name('run-pg-hotpath-diagnostic.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
PLAN = {'limits': {'min_start_spacing_ns': 125_000_000, 'max_starts_per_second': 8}}


def series(label, values):
    return label + ' ' + ','.join(map(str, values))


def protocol():
    lines = ['PG_HOTPATH starts=160 rows=160 events=80 groups=32', f"EVENT_KEY {'a' * 64} {'b' * 64}",
             series('SCHEDULE', runner.schedule()), series('GAPS_NS', [125_000_000] * 159)]
    for arm, total in zip(runner.ARMS, (100, 103, 129, 105), strict=True):
        for metric in runner.METRICS:
            if metric == 'TOTAL':
                value = total
            elif metric in ('JDBC_PREPARE', 'JDBC_EXECUTE'):
                value = 15
            else:
                value = 0 if arm.startswith('PLAIN') else (3 if arm == 'AFTER' else 5)
            lines.append(series(f'SAMPLE {arm} {metric}', [value] * 32))
    return '\n'.join(lines)


class PgHotPathTest(unittest.TestCase):
    def test_measurement_balances_positions_and_predecessors_for_each_row(self):
        pairs = {}
        calls = list(runner.schedule())
        self.assertEqual(len(calls), 160)
        for block in range(4):
            for start in range(block * 40 + 8, (block + 1) * 40, 4):
                group = calls[start:start + 4]
                row, _ = divmod(group[0], 4)
                self.assertTrue(all(code // 4 == row for code in group))
                pairs.setdefault(row, []).append([code % 4 for code in group])
        self.assertEqual(set(pairs), set(range(1, 9)))
        for orders in pairs.values():
            self.assertEqual(4, len(orders))
            self.assertTrue(all(set(group) == set(range(4)) for group in orders))
            self.assertTrue(all(set(position) == set(range(4)) for position in zip(*orders, strict=True)))
            self.assertEqual(12, len({(a, b) for order in orders for a, b in zip(order, order[1:])}))

    def test_summary_compares_aa_and_candidate_separately(self):
        result = runner.decode(protocol(), PLAN)
        self.assertEqual((160, 80, 32, 8), (result['starts'], result['events'], result['groups'],
                                            result['max_rolling_second']))
        total = result['paired']['TOTAL']
        self.assertEqual(3, total['baseline_abs_delta_p95_ns'])
        self.assertEqual(-24, total['candidate_minus_previous_median_ns'])
        self.assertEqual([-24] * 4, total['candidate_minus_previous_block_medians_ns'])
        self.assertEqual(3.5, total['slowest_candidate_two_minus_baselines_mean_ns'])
        self.assertEqual(-16, result['paired']['OTHER']['candidate_minus_previous_median_ns'])

    def test_rejects_changed_counts_and_missing_samples(self):
        data = protocol()
        with self.assertRaisesRegex(ValueError, 'FIXTURE_COUNTS'):
            runner.decode(data.replace('events=80', 'events=79'), PLAN)
        with self.assertRaisesRegex(ValueError, 'PROTOCOL_LENGTH'):
            runner.decode('\n'.join(data.splitlines()[:-1]), PLAN)

    def test_baseline_cannot_contain_observation_and_segments_cannot_exceed_total(self):
        data = protocol()
        with self.assertRaisesRegex(ValueError, 'BASELINE_OBSERVATION'):
            runner.decode(data.replace('PLAIN_A METADATA 0,', 'PLAIN_A METADATA 1,'), PLAN)
        with self.assertRaisesRegex(ValueError, 'TIMING_ACCOUNTING'):
            runner.decode(data.replace('AFTER METADATA 3,', 'AFTER METADATA 106,'), PLAN)

    def test_gaps_and_sequence_are_verified(self):
        data = protocol()
        with self.assertRaisesRegex(ValueError, 'MIN_START_SPACING'):
            runner.decode(data.replace('GAPS_NS 125000000,', 'GAPS_NS 124999999,'), PLAN)
        with self.assertRaisesRegex(ValueError, 'PAIR_SCHEDULE'):
            runner.decode(data.replace('SCHEDULE 4,5', 'SCHEDULE 5,4'), PLAN)

    def test_missing_or_wrong_approval_cannot_open_workspace_or_database(self):
        with (tempfile.TemporaryDirectory() as folder, patch.object(runner, 'ROOT', Path(folder)),
              patch.object(runner.guard, 'protected_workspace') as lock,
              patch.object(runner.native, 'instance') as instance):
            with self.assertRaisesRegex(ValueError, 'SEPARATE_APPROVAL_REQUIRED'):
                runner.run(PLAN, {})
            approval = Path(folder) / runner.APPROVAL
            approval.parent.mkdir()
            approval.touch()
            wrong = {**runner.approval_for(PLAN), 'authorized_runs': True}
            with patch.object(runner.review, 'read', return_value=wrong):
                with self.assertRaisesRegex(ValueError, 'APPROVAL_SCOPE_CHANGED'):
                    runner.run(PLAN, {})
            lock.assert_not_called()
            instance.assert_not_called()

    def test_hook_refuses_changed_execute_anchor(self):
        source = (runner.ROOT / runner.sources.DATA_SOURCE).read_text()
        with self.assertRaisesRegex(ValueError, 'INSTRUMENTATION_ANCHOR'):
            runner.sources.data_source(source.replace('target).executeQuery()', 'target).executeUpdate()'), False)


if __name__ == '__main__':
    unittest.main()
