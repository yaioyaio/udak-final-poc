"""Offline verification of protocol invariants and the pre-execution gate."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('comparison_runner', Path(__file__).with_name('run-postgres-comparison.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
LIMITS = {'min_start_spacing_ns': 125_000_000, 'max_starts_per_second': 8}
SCOPE = {'limits': LIMITS, 'query_starts': 160, 'block_order': ['before', 'after', 'after', 'before']}


def line(label, samples):
    return label + ' ' + ','.join(map(str, samples))


def protocol(block):
    lines = ['PRODUCT_PERF profile=POSTGRESQL starts=40 completed=40 warmup_per_arm=4 measured_per_arm=16'
             ' verified_rows=40 events=20 errors=0 max_in_flight=1 max_rolling_second=8 min_spacing_ns=125000000',
             line('PLAIN_NS', [30] * 16), line('OBSERVE_NS', [40] * 16)]
    for arm, total in zip(runner.ARMS, (30, 40), strict=True):
        for metric in runner.METRICS:
            if metric == 'TOTAL':
                values = [total] * 16
            elif metric in ('JDBC_PREPARE', 'JDBC_EXECUTE', 'JDBC_OTHER'):
                values = [10] * 16
            elif arm == 'OBSERVE' and metric in runner.OBSERVE_ONLY:
                values = [2] * 16
            else:
                values = [0] * 16
            lines.append(line(f'ATTRIBUTION {arm} {metric}', values))
    return '\n'.join((*lines, f"EVENT_KEY {'a' * 64} {'b' * 64}",
                       line('SCHEDULE', runner.expected_schedule(block)), line('GAPS_NS', [125_000_000] * 39)))


class ComparisonTest(unittest.TestCase):
    def test_summary_of_four_blocks(self):
        blocks = [runner.decode_block(protocol(block), block, LIMITS) for block in range(4)]
        summary = runner.summarize(blocks, [125_000_000] * 3, {'scope': SCOPE})
        self.assertEqual((160, 160, 80, 64), tuple(summary[key] for key in
                         ('starts', 'verified_rows', 'events', 'measured_pairs')))
        self.assertEqual(8, summary['max_rolling_second_conservative'])
        for block in summary['blocks']:
            self.assertEqual(10, block['median_paired_delta_ns']['TOTAL'])
            self.assertEqual(2, block['median_paired_delta_ns']['SHAPE'])
            for arm in runner.ARMS:
                self.assertEqual(10, block['median_paired_delta_ns_by_first_arm'][arm]['TOTAL'])
            self.assertEqual(10, block['p95_total_paired_delta_ns'])
            self.assertEqual(0, block['slowest_observe_pairs']['mean_paired_delta_ns']['JDBC_EXECUTE'])

    def test_rejects_double_counted_timing(self):
        text = protocol(0).replace('OBSERVE SHAPE 2,', 'OBSERVE SHAPE 3,', 1)
        with self.assertRaisesRegex(ValueError, 'EXCLUSIVE_ACCOUNTING'):
            runner.decode_block(text, 0, LIMITS)

    def test_rejects_changed_normalized_event_between_variants(self):
        blocks = [runner.decode_block(protocol(block), block, LIMITS) for block in range(4)]
        blocks[1]['event_key'][1] = 'c' * 64
        with self.assertRaisesRegex(ValueError, 'EVENT_METADATA_CHANGED'):
            runner.summarize(blocks, [125_000_000] * 3, {'scope': SCOPE})

    def test_rejects_wrong_order_even_with_same_events(self):
        with self.assertRaisesRegex(ValueError, 'ROW_ORDER_INVARIANT'):
            runner.decode_block(protocol(1), 0, LIMITS)

    def test_rejects_global_gap_even_when_all_blocks_pass(self):
        blocks = [runner.decode_block(protocol(block), block, LIMITS) for block in range(4)]
        with self.assertRaisesRegex(ValueError, 'MIN_START_SPACING'):
            runner.summarize(blocks, [125_000_000, 124_999_999, 125_000_000], {'scope': SCOPE})

    def test_rejects_unvalidated_protocol_text(self):
        with self.assertRaisesRegex(ValueError, 'PROTOCOL_LENGTH'):
            runner.decode_block(protocol(0) + '\nunexpected', 0, LIMITS)

    def test_absent_approval_never_opens_workspace_or_launches_process(self):
        with (tempfile.TemporaryDirectory() as root, patch.object(runner, 'ROOT', Path(root)),
              patch.object(runner, 'protected_workspace') as workspace, patch.object(runner, 'prepare') as prepare,
              patch.object(runner.native, 'instance') as database):
            with self.assertRaisesRegex(ValueError, 'SEPARATE_APPROVAL_REQUIRED'):
                runner.run({}, {})
            workspace.assert_not_called()
            prepare.assert_not_called()
            database.assert_not_called()

    def test_approval_must_bind_exact_proposal_and_integer_scope(self):
        plan = {'scope': SCOPE}
        with tempfile.TemporaryDirectory() as root, patch.object(runner, 'ROOT', Path(root)):
            approval_file = Path(root) / runner.APPROVAL
            approval_file.parent.mkdir()
            approval_file.touch()
            for candidate in (runner.authorization({'scope': {}}), {**runner.authorization(plan), 'authorized_runs': True}):
                with patch.object(runner.review, 'read', return_value=candidate):
                    with self.assertRaisesRegex(ValueError, 'APPROVAL_SCOPE_MISMATCH'):
                        runner.require_approval(plan)

    def test_approval_alone_never_opens_workspace(self):
        with (patch.object(runner, 'require_approval'), patch.object(runner, 'prepared',
              side_effect=ValueError('PREPARATION_REQUIRED')), patch.object(runner, 'protected_workspace') as workspace):
            with self.assertRaisesRegex(ValueError, 'PREPARATION_REQUIRED'):
                runner.run({}, {})
            workspace.assert_not_called()

    def test_claim_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / 'claimed'
            with patch.object(runner, 'MARKER', marker):
                runner.claim('test-approval')
                with self.assertRaises(FileExistsError):
                    runner.claim('other-approval')
            self.assertEqual('test-approval\n', marker.read_text())

    def test_receipt_cannot_be_replaced_and_scratch_is_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            receipt = Path(temp) / 'result'
            runner.save_once(receipt, {'status': 'PASS'})
            with self.assertRaises(FileExistsError):
                runner.save_once(receipt, {'status': 'FAIL'})
            self.assertEqual({'status': 'PASS'}, json.loads(receipt.read_text()))
            self.assertEqual([receipt], list(Path(temp).iterdir()))

    def test_pressure_guard_fails_closed_and_restores_existing_guard(self):
        base = runner.native._Child
        for pressure in (None, 2, 4):
            with patch.object(runner.host, 'memory_pressure', return_value=pressure):
                with runner.watch_host(Path('/tmp')):
                    child = object.__new__(runner.native._Child)
                    with self.assertRaisesRegex(ValueError, 'HOST_MEMORY_PRESSURE'):
                        child._sample()
            self.assertIs(runner.native._Child, base)

    def test_pressure_abort_reaps_the_owned_synthetic_process(self):
        base = runner.native._Child
        children = []

        class TrackChild(base):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                children.append(self)

        with (tempfile.TemporaryDirectory() as scratch,
              patch.object(runner.native, '_Child', TrackChild),
              patch.object(runner.host, 'memory_pressure', return_value=2)):
            with runner.watch_host(Path(scratch)):
                with self.assertRaisesRegex(ValueError, 'HOST_MEMORY_PRESSURE'):
                    runner.native.run_private('pressure-probe', [sys.executable, '-B', '-c',
                        'import time; time.sleep(10)'], Path(scratch).resolve(), 3)
        child, = children
        self.assertIsNotNone(child.process.returncode)
        self.assertTrue(child.quiesced)
        self.assertFalse(child.watcher.is_alive())

    def test_override_does_not_swallow_current_observer_reason(self):
        name = runner.sources.previous.OBSERVER
        original = (runner.ROOT / name).read_text()
        instrumented = runner.sources.instrument(name, original)
        self.assertIn('sink.accept(event, shape.reason());', instrumented)
        self.assertIn('AttributionProbe.finishCurrent("EVENT_SINK");', instrumented)
        with self.assertRaisesRegex(ValueError, 'INSTRUMENTATION_ANCHOR'):
            runner.sources.instrument(name, original.replace('shape.reason()', 'otherReason()'))


if __name__ == '__main__':
    unittest.main(verbosity=1)
