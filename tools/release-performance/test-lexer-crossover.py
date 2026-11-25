"""Offline approval, allocation-boundary and protocol checks."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('crossover_runner', Path(__file__).with_name('run-lexer-crossover.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
LIMITS = {'min_start_spacing_ns': 125_000_000, 'max_starts_per_second': 8}


def values(label, samples):
    return label + ' ' + ','.join(map(str, samples))


def protocol(profile):
    return '\n'.join((
        f'LEXER_CROSSOVER profile={profile} starts=160 completed=160 warmup_per_arm=16 measured_per_arm=64'
        ' verified_rows=160 events=160 errors=0 max_in_flight=1 max_rolling_second=8 min_spacing_ns=125000000',
        f"EVENT_KEY {'a'*64} {'b'*64}",
        values('SCHEDULE', [code for block in range(4) for code in runner.guard.expected_schedule(block)]),
        values('GAPS_NS', [125_000_000]*159),
        values('BEFORE_SHAPE_BYTES', [32]*64), values('AFTER_SHAPE_BYTES', [0]*64),
        values('BEFORE_JDBC_EXECUTE_NS', [10]*64), values('AFTER_JDBC_EXECUTE_NS', [20]*64),
    ))


class CrossoverTest(unittest.TestCase):
    def test_profiles_report_allocation_and_jdbc_with_different_units(self):
        for profile in runner.PROFILES:
            with self.subTest(profile=profile):
                report = runner.decode(protocol(profile), profile, LIMITS)
                self.assertEqual((160, 160, 64, 4), (report['starts'], report['events'],
                    report['measured_pairs'], len(report['blocks'])))
                for block in report['blocks']:
                    self.assertEqual(-32, block['SHAPE_BYTES']['median_paired_after_minus_before'])
                    self.assertEqual(10, block['JDBC_EXECUTE_NS']['median_paired_after_minus_before'])

    def test_wrong_profile_event_and_error_counts_fail(self):
        data = protocol('MYSQL')
        samples = ((data, 'POSTGRESQL'), (data.replace('events=160', 'events=159'), 'MYSQL'),
                   (data.replace('errors=0', 'errors=1'), 'MYSQL'))
        for sample, profile in samples:
            with self.assertRaisesRegex(ValueError, 'FIXTURE_PROTOCOL'):
                runner.decode(sample, profile, LIMITS)

    def test_reject_missing_allocation_and_negative_counter(self):
        report = protocol('MYSQL')
        missing = '\n'.join(line for line in report.splitlines() if not line.startswith('AFTER_SHAPE_BYTES'))
        for result in (missing, report.replace('BEFORE_SHAPE_BYTES 32,', 'BEFORE_SHAPE_BYTES -1,')):
            with self.assertRaises(ValueError):
                runner.decode(result, 'MYSQL', LIMITS)

    def test_reject_wrong_schedule_and_spacing(self):
        report = protocol('POSTGRESQL')
        for result in (report.replace('SCHEDULE 2,3', 'SCHEDULE 3,2', 1),
                       report.replace('GAPS_NS 125000000,', 'GAPS_NS 124999999,', 1)):
            with self.assertRaises(ValueError):
                runner.decode(result, 'POSTGRESQL', LIMITS)

    def test_missing_or_wrong_approval_cannot_start_any_workspace(self):
        with (tempfile.TemporaryDirectory() as root, patch.object(runner, 'ROOT', Path(root)),
              patch.object(runner.guard, 'protected_workspace') as lock,
              patch.object(runner.native, 'instance') as instance,
              patch.object(runner, 'prepared') as prepared):
            plan = {'limits': LIMITS}
            with self.assertRaisesRegex(ValueError, 'SEPARATE_APPROVAL_REQUIRED'):
                runner.run(plan, {})
            approval = Path(root) / runner.APPROVAL
            approval.parent.mkdir()
            approval.touch()
            for decision in (runner.approval_for({}), {**runner.approval_for(plan), 'authorized_runs': True}):
                with patch.object(runner.review, 'read', return_value=decision):
                    with self.assertRaisesRegex(ValueError, 'APPROVAL_SCOPE_CHANGED'):
                        runner.run(plan, {})
            lock.assert_not_called()
            instance.assert_not_called()
            prepared.assert_not_called()

    def test_preparation_route_compiles_without_measurement(self):
        from contextlib import nullcontext
        with (tempfile.TemporaryDirectory() as root, patch.object(runner, 'ROOT', Path(root)),
              patch.object(runner.guard, 'protected_workspace', return_value=nullcontext((Path(root),
                  {'status': 'PASS', 'remaining': False}))), patch.object(runner.guard, 'check_host'),
              patch.object(runner, 'build') as build, patch.object(runner, 'proposal', return_value={}),
              patch.object(runner.guard, 'save_once') as save, patch.object(runner.native, 'instance') as instance):
            result = {'database_started': False, 'workload_run_claimed': False}
            runner.prepare({}, result)
            build.assert_called_once()
            save.assert_called_once()
            instance.assert_not_called()
            self.assertEqual('PASS', result['status'])
            self.assertIs(result['database_started'], False)

    def test_lexer_hook_brackets_normalization_before_digest(self):
        path = runner.sources.SHAPE
        original = (runner.ROOT / path).read_text()
        for older in (False, True):
            java = runner.sources.shape(original, older)
            self.assertEqual(1, java.count('LexerCrossoverProbe.startNormalization();'))
            self.assertEqual(1, java.count('LexerCrossoverProbe.finishNormalization();'))
            self.assertIn('startNormalization();\n        return new Lexer(sql)', java)
            self.assertIn('finishNormalization();\n' + runner.sources.SHAPE_RETURN, java)
        with self.assertRaisesRegex(ValueError, 'INSTRUMENTATION_ANCHOR'):
            runner.sources.shape(original.replace('return new Lexer(sql)', 'return new Lexer(other)'), False)

    def test_only_prepared_delegate_gets_jdbc_timer(self):
        name = runner.sources.DATA_SOURCE
        java = runner.sources.instrument(name, (runner.ROOT / name).read_text())
        self.assertEqual(1, java.count('LexerCrossoverProbe.execute((PreparedStatement) target)'))
        self.assertIn('yield target.executeQuery(sql);', java)


if __name__ == '__main__':
    unittest.main()
