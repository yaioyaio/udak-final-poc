#!/usr/bin/env python3
"""Synthetic checks for the approved local PostgreSQL A/A schedule."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location(
    'aa_schedule', Path(__file__).with_name('schedule-pg-baseline-aa.py'))
SCHEDULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCHEDULE)


def at(hour, minute, second=0):
    return datetime.combine(SCHEDULE.APPROVED_DATE, SCHEDULE.time(hour, minute, second), SCHEDULE.SEOUL)


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        root = Path(work.name)
        (root / '.git').mkdir()
        state = root / '.git' / 'schedule'
        for name, value in dict(ROOT=root, STATE=state, CLAIM=root / '.git' / 'claimed',
                                RESULT=root / 'result').items():
            override = patch.object(SCHEDULE, name, value)
            override.start()
            self.addCleanup(override.stop)
        SCHEDULE.private_state(create=True)

    def test_seoul_date_six_windows_and_utc_equivalence(self):
        for slot in SCHEDULE.SLOTS:
            start = at(slot.hour, slot.minute)
            expected = slot.strftime('%H%M')
            with self.subTest(slot=expected):
                self.assertEqual(SCHEDULE.local_slot(start.astimezone(timezone.utc)), expected)
                self.assertEqual(SCHEDULE.local_slot(start + timedelta(minutes=4, seconds=59)), expected)
                self.assertIsNone(SCHEDULE.local_slot(start - timedelta(seconds=1)))
                self.assertIsNone(SCHEDULE.local_slot(start + timedelta(minutes=5)))
                self.assertIsNone(SCHEDULE.local_slot(start + timedelta(days=1)))
                self.assertIsNone(SCHEDULE.local_slot(start.replace(year=2027)))

    def test_plist_has_one_entrypoint_and_six_fixed_calendar_times(self):
        job = plistlib.loads(plistlib.dumps(SCHEDULE.job_plist('/python', '/jdk')))
        self.assertEqual(job['Label'], SCHEDULE.LABEL)
        self.assertEqual(job['ProgramArguments'], ['/python', '-I', '-B', str(SCHEDULE.SCRIPT), '--dispatch'])
        self.assertEqual(job['StartCalendarInterval'][:-1], [
            dict(Month=11, Day=27, Hour=hour, Minute=minute)
            for hour in (1, 2, 3) for minute in (0, 30)
        ])
        self.assertEqual(job['StartCalendarInterval'][-1], dict(Month=11, Day=27, Hour=3, Minute=35))
        self.assertEqual(job['EnvironmentVariables']['PATH'], f'/jdk/bin:{SCHEDULE.SYSTEM_PATH}')
        self.assertTrue(set(job).isdisjoint(('KeepAlive', 'RunAtLoad', 'StartInterval', 'ProcessType')))

    def test_transient_failure_allows_at_most_six_unique_attempts(self):
        runner = Mock(return_value='HOST_NOT_QUIET')
        for slot in SCHEDULE.SLOTS:
            now = at(slot.hour, slot.minute)
            self.assertEqual(SCHEDULE.dispatch(now, runner), 'HOST_NOT_QUIET')
            self.assertEqual(SCHEDULE.dispatch(now + timedelta(seconds=1), runner), 'SLOT_ALREADY_RECORDED')
        self.assertEqual(SCHEDULE.dispatch(at(3, 35), runner), 'OUTSIDE_WINDOW')
        self.assertEqual(runner.call_count, 6)
        self.assertTrue(all(outcome == 'HOST_NOT_QUIET' for outcome in SCHEDULE.history().values()))

    def test_clock_rollback_does_not_fill_past_slots(self):
        runner = Mock(return_value='RUNNER_LOCKED')
        self.assertEqual(SCHEDULE.dispatch(at(1, 30), runner), 'RUNNER_LOCKED')
        self.assertEqual(SCHEDULE.dispatch(at(1, 0), runner), 'SLOT_ALREADY_PASSED')
        runner.assert_called_once_with()

    def test_active_lock_blocks_parallel_attempt(self):
        runner = Mock()
        with SCHEDULE.state_lock():
            with self.assertRaisesRegex(SCHEDULE.ScheduleError, '^SCHEDULE_LOCKED$'):
                SCHEDULE.dispatch(at(1, 0), runner)
        runner.assert_not_called()

    def test_each_existing_approval_artifact_independently_blocks_run(self):
        runner = Mock()
        for marker in (SCHEDULE.CLAIM, SCHEDULE.RESULT):
            with patch.object(SCHEDULE, 'exists', side_effect=lambda path: path == marker):
                self.assertEqual(SCHEDULE.dispatch(at(1, 0), runner), 'APPROVAL_USED')
        runner.assert_not_called()

    def test_terminal_status_and_interrupted_dispatch_stop_future_slots(self):
        runner = Mock(return_value='RUNNER_STOPPED')
        self.assertEqual(SCHEDULE.dispatch(at(1, 0), runner), 'RUNNER_STOPPED')
        self.assertEqual(SCHEDULE.dispatch(at(1, 30), runner), 'SCHEDULE_STOPPED')
        runner.assert_called_once_with()
        with patch.object(SCHEDULE, 'history', return_value={'0100': 'INTERRUPTED', '0130': 'PENDING'}):
            self.assertEqual(SCHEDULE.dispatch(at(1, 30), runner), 'SCHEDULE_STOPPED')
        runner.assert_called_once_with()

    def test_interrupted_run_keeps_a_persistent_fail_closed_receipt(self):
        runner = Mock(side_effect=OSError)
        with self.assertRaises(OSError):
            SCHEDULE.dispatch(at(1, 0), runner)
        self.assertEqual(SCHEDULE.history()['0100'], 'INTERRUPTED')
        self.assertEqual(SCHEDULE.dispatch(at(1, 30), runner), 'SCHEDULE_STOPPED')
        runner.assert_called_once_with()

    def test_only_terminal_outcomes_or_schedule_end_request_unload(self):
        self.assertFalse(SCHEDULE.retire_due(at(1, 0), 'HOST_NOT_QUIET'))
        self.assertTrue(SCHEDULE.retire_due(at(1, 0), 'APPROVAL_USED'))
        self.assertTrue(SCHEDULE.retire_due(at(1, 0), 'RUNNER_STOPPED'))
        self.assertTrue(SCHEDULE.retire_due(at(1, 0), 'SCHEDULE_STOPPED'))
        self.assertTrue(SCHEDULE.retire_due(at(3, 30), 'HOST_NOT_QUIET'))
        self.assertTrue(SCHEDULE.retire_due(at(3, 35), 'OUTSIDE_WINDOW'))
        runner = Mock()
        self.assertEqual(SCHEDULE.dispatch(at(3, 35), runner), 'OUTSIDE_WINDOW')
        runner.assert_not_called()

    def test_runner_has_external_timeout_and_timeout_never_retries(self):
        with patch.object(SCHEDULE, 'jdk_home', return_value=Path('/jdk')):
            with patch.object(SCHEDULE.subprocess, 'run',
                              side_effect=SCHEDULE.subprocess.TimeoutExpired('run', 320)) as run:
                self.assertEqual(SCHEDULE.run_existing(), 'RUNNER_STOPPED')
                self.assertEqual(run.call_args.kwargs['timeout'], 320)

    def test_only_explicit_transients_with_safe_cleanup_are_retryable(self):
        payload = dict(status='NOT RUN', workload_run_claimed=False, postgresql_initialized=False,
                       reason='HOST_NOT_QUIET', cleanup=None, host_samples=[{}])
        outcome = SCHEDULE.runner_outcome
        encode = lambda **changes: json.dumps({**payload, **changes}).encode()
        self.assertEqual(outcome(1, encode(), False), 'HOST_NOT_QUIET')
        self.assertEqual(outcome(1, encode(reason='HOST_MEMORY_PRESSURE',
                                          cleanup=dict(status='PASS', remaining=False)), False), 'HOST_MEMORY_PRESSURE')
        self.assertEqual(outcome(1, encode(reason='BlockingIOError'), False), 'RUNNER_LOCKED')
        for changes in (dict(reason='BlockingIOError', host_samples=None),
                        dict(reason='BlockingIOError', cleanup=dict(status='PASS', remaining=False)),
                        dict(reason='INPUTS_CHANGED'),
                        dict(cleanup=dict(status='PRESERVED_UNKNOWN', remaining=True)),
                        dict(workload_run_claimed=True), dict(postgresql_initialized=True)):
            self.assertEqual(outcome(1, encode(**changes), False), 'RUNNER_STOPPED')
        self.assertEqual(outcome(0, b'{', False), 'RUNNER_STOPPED')
        self.assertEqual(outcome(1, b'x' * 65537, False), 'RUNNER_STOPPED')
        self.assertEqual(outcome(1, encode(), True), 'APPROVAL_USED')


if __name__ == '__main__':
    unittest.main()
