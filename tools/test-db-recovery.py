#!/usr/bin/env python3
"""Regression checks for the bounded public JDBC evidence protocol."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('db_recovery', Path(__file__).with_name('run-db-recovery.py'))
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


def example(profile):
    versions = {'POSTGRESQL': ('17.11', '42.7.14'), 'MYSQL': ('8.0.46', '26.10.0')}
    database, driver = versions[profile]
    lines = [f'RECOVERY_VERSION profile={profile} database={database} driver={driver}']
    states = ('57014', '57014', '57P01') if profile == 'POSTGRESQL' else ('NONE', 'NONE', '08S01')
    types = ('PSQLException',) * 3 if profile == 'POSTGRESQL' else (
        'MySQLStatementCancelledException', 'MySQLTimeoutException', 'CommunicationsException')
    for name, state, exception in zip(recovery.SCENARIOS, states, types):
        loss = name == 'SESSION_LOSS'
        blocked, new = ('false', 'true') if loss else ('true', 'false')
        transaction = 'DISCONNECTED' if loss else ('ABORTED' if profile == 'POSTGRESQL' else 'ACTIVE')
        lines.append(f'RECOVERY_RESULT profile={profile} scenario={name} status=PASS sqlstate={state}'
                     f' exception={exception} blocked_observed={blocked} statement_gone_while_blocked={blocked}'
                     f' failed_write_absent=true transaction_state={transaction} rollback_verified=true'
                     f' session_reused={blocked} new_session_verified={new} followup_committed=true assertions=20')
    return lines


class RecoveryProtocolTest(unittest.TestCase):
    def test_complete_matrix(self):
        for profile in ('POSTGRESQL', 'MYSQL'):
            with self.subTest(profile=profile):
                actual = recovery.parse_protocol('\n'.join(example(profile)), profile)
                self.assertEqual([row['scenario'] for row in actual['scenarios']], list(recovery.SCENARIOS))
                self.assertTrue(actual['scenarios'][0]['session_reused'])
                self.assertTrue(actual['scenarios'][-1]['new_session_verified'])
                self.assertEqual(sum(row['assertions'] for row in actual['scenarios']), 60)

    def test_incomplete_or_duplicate_scenario_denied(self):
        lines = example('POSTGRESQL')
        for failed in (lines[:-1], lines + lines[-1:], lines[:-1] + lines[1:2], [lines[0], *reversed(lines[1:])]):
            with self.assertRaises(ValueError):
                recovery.parse_protocol('\n'.join(failed), 'POSTGRESQL')

    def test_wrong_runtime_identity_denied(self):
        output = '\n'.join(example('POSTGRESQL'))
        for profile, text in (('MYSQL', output), ('POSTGRESQL', output.replace('42.7.14', '42.7.13'))):
            with self.assertRaises(ValueError):
                recovery.parse_protocol(text, profile)

    def test_missing_impact_observations_denied(self):
        output = '\n'.join(example('MYSQL'))
        for field in ('blocked_observed', 'statement_gone_while_blocked', 'failed_write_absent',
                      'rollback_verified', 'session_reused', 'new_session_verified', 'followup_committed'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                recovery.parse_protocol(output.replace(f'{field}=true', f'{field}=false', 1), 'MYSQL')

    def test_wrong_state_or_commit_classification_denied(self):
        output = '\n'.join(example('POSTGRESQL'))
        for old, new in (('transaction_state=ABORTED', 'transaction_state=ACTIVE'),
                         ('sqlstate=57014', 'sqlstate=55P03'), ('assertions=20', 'assertions=0')):
            with self.subTest(field=old), self.assertRaises(ValueError):
                recovery.parse_protocol(output.replace(old, new, 1), 'POSTGRESQL')

    def test_unrecognized_driver_exception_denied(self):
        output = '\n'.join(example('MYSQL'))
        for state, name in (('NONE', 'SocketTimeoutException'), ('S1T00', 'SQLException')):
            changed = output.replace('sqlstate=NONE exception=MySQLTimeoutException', f'sqlstate={state} exception={name}')
            with self.assertRaises(ValueError):
                recovery.parse_protocol(changed, 'MYSQL')

    def test_extra_output_denied(self):
        output = '\n'.join(example('MYSQL'))
        for failed in (output + '\nextra', output.replace('assertions=20', 'assertions=20 extra', 1)):
            with self.assertRaises(ValueError):
                recovery.parse_protocol(failed, 'MYSQL')

    def test_protocol_output_cap(self):
        with tempfile.TemporaryDirectory(prefix='udak-recovery-protocol-') as name:
            trace = Path(name) / 'fixture.output'
            trace.write_bytes(b'x' * 4097)
            with self.assertRaises(ValueError):
                recovery.protocol_text(trace)


if __name__ == '__main__':
    unittest.main()
