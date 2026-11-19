#!/usr/bin/env python3
"""Validate recorded native SQL Server G5 results without contacting the provider."""
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
REQUIRED_CHECKS = frozenset({
    'native_host', 'dedicated_empty_baseline', 'pinned_image', 'quota_before_start',
    'cgroup_limits', 'loopback_only', 'functional', 'commit_ack_loss', 'seed_disconnect',
    'crash_recovery', 'clean_restart', 'owned_cleanup',
})
FIELDS = frozenset({
    'schema_version', 'requirement', 'status', 'sqlserver_g5', 'profile', 'platform',
    'image', 'server_version', 'driver_version', 'input_sha512', 'approval_sha512',
    'limits', 'checks', 'concurrency', 'cleanup', 'fixture_receipts', 'crash_exit_code',
})
CAPABILITIES = (
    'pool_functional', 'native_concurrency_pilot', 'jdbc_cancel_timeout_precommit_loss',
    'unknown_commit_outcome', 'graceful_restart_recovery', 'crash_restart_recovery',
)


def load_runner():
    spec = importlib.util.spec_from_file_location(
        'sqlserver_native_runner', ROOT / 'tools/release-provider/run-sqlserver-g5.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner


def validate(report, runner, inputs, approval_digest):
    if (not isinstance(report, dict) or report.keys() != FIELDS
            or type(report['schema_version']) is not int or report['schema_version'] != 1
            or report['requirement'] != 'RELEASE-025' or report['status'] != 'PASS'
            or report['sqlserver_g5'] != 'PASS' or report['profile'] != 'SQLSERVER'
            or report['platform'] != 'linux/amd64' or report['image'] != runner.get_pin()['image']
            or not isinstance(report['server_version'], str)
            or not re.fullmatch(r'16\.0\.[0-9]{1,5}\.[0-9]{1,5}', report['server_version'])
            or report['driver_version'] != '13.6.2.0' or report['input_sha512'] != inputs
            or not inputs or report['approval_sha512'] != approval_digest
            or json.dumps(report['limits'], sort_keys=True) != json.dumps(runner.LIMITS, sort_keys=True)):
        raise ValueError('SQL Server identity, authorization, or input evidence differs')

    checks = report['checks']
    if (not isinstance(checks, dict) or checks.keys() != REQUIRED_CHECKS
            or any(value is not True for value in checks.values())
            or type(report['crash_exit_code']) is not int or report['crash_exit_code'] != 137
            or not isinstance(report['cleanup'], dict)
            or report['cleanup'].keys() != {'status', 'remaining'}
            or report['cleanup']['status'] != 'PASS' or report['cleanup']['remaining'] is not False):
        raise ValueError('SQL Server lifecycle or cleanup evidence differs')

    receipts = report['fixture_receipts']
    if (not isinstance(receipts, dict) or receipts.keys() != {'functional', 'crash_recover', 'clean_recover'}
            or receipts['crash_recover'] != 'SQLSERVER_G5 RECOVER PASS'
            or receipts['clean_recover'] != 'SQLSERVER_G5 GRACEFUL PASS'
            or not isinstance(receipts['functional'], str) or len(receipts['functional']) > 128):
        raise ValueError('SQL Server fixture receipts differ')
    try:
        measured = runner.parse_functional(receipts['functional'].encode('ascii') + b'\n')
    except (RuntimeError, ValueError) as error:
        raise ValueError('SQL Server concurrency receipt is invalid') from error
    counts = report['concurrency']
    if counts != measured or any(type(value) is not int for value in counts.values()):
        raise ValueError('SQL Server concurrency evidence differs')

    return {**dict.fromkeys(CAPABILITIES, 'PASS'), 'native_execution': {
        key: report[key] for key in ('image', 'platform', 'server_version', 'driver_version')
    }}


def assess():
    runner = load_runner()
    paths = (runner.APPROVAL, runner.REPORT, *runner.sources())
    before = runner.h.hashes(paths)
    try:
        runner.authorized()
    except RuntimeError as error:
        raise ValueError('SQL Server approval cannot be verified') from error
    path = runner.h.p5.p4.approved_paths([runner.REPORT])[0][1]
    if path.stat().st_size > 32 * 1024:
        raise ValueError('SQL Server report exceeds the bound')
    report = json.loads(path.read_text(encoding='ascii'))
    result = validate(report, runner, {key: before[key] for key in runner.sources()}, before[runner.APPROVAL])
    if runner.h.hashes(paths) != before:
        raise ValueError('SQL Server evidence changed during assessment')
    return result


def main():
    if sys.argv[1:]:
        return 2
    if not (ROOT / 'evidence/PRODUCT-G5-SQLSERVER.json').exists():
        print(json.dumps({'evidence_review': 'NOT RUN', 'sqlserver_g5': 'NOT RUN'}))
        return 2
    try:
        assessment = assess()
    except (OSError, ValueError, KeyError, AttributeError, TypeError, RuntimeError):
        print(json.dumps({'evidence_review': 'FAIL', 'sqlserver_g5': 'NOT VERIFIED'}))
        return 1
    print(json.dumps({'evidence_review': 'PASS', 'sqlserver_g5': 'PASS', 'assessment': assessment}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
