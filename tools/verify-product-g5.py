#!/usr/bin/env python3
"""Validate the release decision inputs and calculate the paired p95 result."""
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
CRITERIA = 'tools/product-g5-criteria.json'
PERFORMANCE = 'evidence/PRODUCT-G5-PERFORMANCE.json'
POOL = 'evidence/PRODUCT-G5-POOL.json'
RESTART = 'evidence/PRODUCT-G5-RESTART.json'
DECISION = 'evidence/PRODUCT-G5-ACCEPTANCE.json'
SUPPORT = 'evidence/RELEASE-SUPPORT-MATRIX.json'
PILOT = 'evidence/RELEASE-G5-PILOT.json'
CANCEL = 'evidence/DB-RECOVERY-VALIDATION.json'
EXPECTED_FIELDS = ('starts', 'completed', 'warmup_per_arm', 'measured_per_arm', 'verified_rows',
                   'events', 'errors', 'max_in_flight', 'max_rolling_second', 'min_spacing_ns')


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


schema = load('product_g5_native', 'tools/run-schema-regression.py')
h = schema.h


def read(path):
    approved = h.p5.p4.approved_paths([path])[0][1]
    if approved.stat().st_size > 1024**2:
        raise ValueError('Input report exceeds bound')
    return json.loads(approved.read_text())


def criteria():
    data = read(CRITERIA)
    p = data['performance']
    if (data['schema_version'] != 1 or data['requirement'] != 'NFR-02'
            or p['max_observe_p95_increase_percent'] != 5 or p['warmup_per_arm'] != 8
            or p['measured_per_arm'] != 96 or p['starts_per_database'] != 2 * (p['warmup_per_arm'] + p['measured_per_arm'])
            or p['profiles'] != {'POSTGRESQL': {'server_version': '17.11', 'driver_version': '42.7.14'},
                                 'MYSQL': {'server_version': '8.0.46', 'driver_version': '26.10.0'}}
            or p['limits'] != {'database_parallelism': 1, 'max_in_flight': 1,
                               'max_starts_per_second': 8, 'min_start_spacing_ns': 125000000, 'wall_seconds': 300,
                               'db_processes': 48, 'db_rss_bytes': 1073741824, 'db_scratch_bytes': 805306368,
                               'process_cpu_seconds': 90, 'jvm_heap_mib': 256, 'jvm_active_cpus': 2,
                               'child_log_bytes': 16777216}
            or data['support_profiles'] != ['POSTGRESQL', 'MYSQL', 'SQLSERVER', 'ORACLE']
            or data['additional_recovery_required'] != ['unknown commit outcome', 'server restart recovery']
            or data['certification_requires_exact_profile_evidence'] is not True):
        raise ValueError('Product acceptance contract differs')
    return data


def compare(plain, observe, performance):
    n = performance['measured_per_arm']
    for sample in (plain, observe):
        if len(sample) != n or any(type(value) is not int or not 1 <= value <= 10**10 for value in sample):
            raise ValueError('Complete positive nanosecond samples required')
    rank = (95 * n + 99) // 100
    baseline, observed = (sorted(sample)[rank - 1] for sample in (plain, observe))
    threshold = performance['max_observe_p95_increase_percent']
    return {'status': 'PASS' if 100 * observed <= (100 + threshold) * baseline else 'FAIL',
            'measured_per_arm': n, 'nearest_rank': rank, 'baseline_p95_ns': baseline, 'observe_p95_ns': observed,
            'overhead_percent': round(100 * (observed - baseline) / baseline, 4)}


def protocol(output, profile, p):
    lines = output.splitlines()
    if len(lines) != 3:
        raise ValueError('Incomplete performance protocol')
    pattern = r'PRODUCT_PERF profile=' + re.escape(profile) + ''.join(r' ' + key + r'=([0-9]{1,12})' for key in EXPECTED_FIELDS)
    match = re.fullmatch(pattern, lines[0])
    if match is None:
        raise ValueError('Unexpected performance protocol header')
    counts = dict(zip(EXPECTED_FIELDS, map(int, match.groups())))
    expected = dict(starts=p['starts_per_database'], completed=p['starts_per_database'],
                    warmup_per_arm=p['warmup_per_arm'], measured_per_arm=p['measured_per_arm'],
                    verified_rows=p['starts_per_database'], events=p['starts_per_database'] // 2,
                    errors=0, max_in_flight=p['limits']['max_in_flight'])
    if (any(counts[key] != value for key, value in expected.items())
            or not 1 <= counts['max_rolling_second'] <= p['limits']['max_starts_per_second']
            or counts['min_spacing_ns'] < p['limits']['min_start_spacing_ns']):
        raise ValueError('Workload, verification or Observe events differ')
    samples = []
    for line, arm in zip(lines[1:], ('PLAIN', 'OBSERVE')):
        match = re.fullmatch(arm + r'_NS ([0-9]{1,11}(?:,[0-9]{1,11})*)', line)
        if not match:
            raise ValueError('Invalid nanosecond samples')
        samples.append([int(value) for value in match[1].split(',')])
    return {'workload': counts, 'plain_ns': samples[0], 'observe_ns': samples[1], 'assessment': compare(*samples, p)}


def verified_inputs(report, expected):
    if not expected or report['input_sha512'] != expected:
        raise ValueError('Recorded execution inputs differ')


def performance_result(p):
    path = ROOT / PERFORMANCE
    if not path.exists():
        return {name: {'status': 'NOT RUN'} for name in p['profiles']}
    proof = read(PERFORMANCE)
    run = load('product_g5_performance_runner', 'tools/run-g5-performance.py')
    run.authorized()
    verified_inputs(proof, run.input_hashes())
    if (proof['workload_run_claimed'] is not True or proof['containers_started'] != 0
            or proof['cleanup']['status'] != 'PASS' or proof['cleanup']['remaining'] is not False
            or not 0 < proof['wall_seconds'] <= p['limits']['wall_seconds']
            or proof['profiles'].keys() != p['profiles'].keys()):
        raise ValueError('Measured run or cleanup evidence incomplete')
    result = {}
    for name, row in proof['profiles'].items():
        header = f'PRODUCT_PERF profile={name}' + ''.join(f' {key}={row["workload"][key]}' for key in EXPECTED_FIELDS)
        text = '\n'.join((header, 'PLAIN_NS ' + ','.join(map(str, row['plain_ns'])),
                         'OBSERVE_NS ' + ','.join(map(str, row['observe_ns']))))
        checked = protocol(text, name, p)['assessment']
        runtime = row['native_runtime']
        if (row['versions'] != p['profiles'][name] or checked != row['assessment'] or row['status'] != checked['status']
                or not runtime['loopback_listener_owned'] or not runtime['server_stopped']
                or not runtime['process_groups_quiesced'] or not row['step']['child_reaped']):
            raise ValueError('Performance timing, identity or cleanup mismatch')
        result[name] = checked
    expected = 'PASS' if all(row['status'] == 'PASS' for row in result.values()) else 'FAIL'
    if proof['status'] != expected:
        raise ValueError('Performance verdict differs from measured samples')
    return result


def pool_result(p):
    proof = read(POOL)
    runner = load('product_g5_pool_runner', 'tools/run-g5-pool.py')
    if (proof['status'] != 'PASS' or proof['profiles'].keys() != p['profiles'].keys()
            or proof['input_sha512'] != runner.input_hashes() or proof['core_smoke']['status'] != 'PASS'
            or proof['scenario_count'] != 4 or proof['docker_containers_started'] != 0
            or proof['cleanup']['status'] != 'PASS' or proof['cleanup']['remaining'] is not False):
        raise ValueError('Functional pool proof incomplete')
    result = {}
    for name, row in proof['profiles'].items():
        runtime = row['native_runtime']
        if (row['status'] != 'PASS' or runtime['version'] != p['profiles'][name]['server_version']
                or row['server_version'] != p['profiles'][name]['server_version']
                or row['driver_version'] != p['profiles'][name]['driver_version']
                or row['scenarios'] != {scenario: 'PASS' for scenario in runner.SCENARIOS}
                or not row['step']['child_reaped'] or not row['step']['process_group_quiesced']
                or not runtime['loopback_listener_owned'] or not runtime['server_stopped']
                or not runtime['process_groups_quiesced']):
            raise ValueError('Functional pool profile or cleanup mismatch')
        result[name] = 'PASS'
    return result


def restart_result(p):
    if not (ROOT / RESTART).exists():
        return {}
    proof = read(RESTART)
    runner = load('product_g5_restart_runner', 'tools/release-pool/run-restart.py')
    verified_inputs(proof, runner.input_hashes())
    if (proof['status'] != 'PASS' or proof['profiles'].keys() != p['profiles'].keys()
            or proof['scenario_count'] != 2 or proof['docker_containers_started'] != 0
            or proof['cleanup']['status'] != 'PASS' or proof['cleanup']['remaining'] is not False):
        raise ValueError('Functional restart proof incomplete')
    result = {}
    for name, row in proof['profiles'].items():
        expected = p['profiles'][name]
        first, second = row['native_runtime'], row['restart_runtime']
        if (row['status'] != 'PASS' or row['server_version'] != expected['server_version']
                or row['driver_version'] != expected['driver_version'] or row['scenarios'] != {'GRACEFUL_RESTART': 'PASS'}
                or second['owned_data_directory_reused'] is not True or second['fresh_loopback_port'] is not True
                or first['server_sha256'] != second['server_sha256']):
            raise ValueError('Restart identity or durability proof differs')
        for runtime in (first, second):
            if (runtime['version'] != expected['server_version'] or runtime['server_exit_code'] != 0
                    or any(runtime[key] is not True for key in ('loopback_listener_owned', 'graceful_stop',
                                                               'server_stopped', 'process_groups_quiesced'))):
                raise ValueError('Owned server stop unconfirmed')
        for step in (row['seed_step'], row['verify_step']):
            if step['status'] != 'PASS' or not step['child_reaped'] or not step['process_group_quiesced']:
                raise ValueError('Restart client receipt incomplete')
        result[name] = 'PASS'
    return result


def acceptance():
    contract = criteria()
    p = contract['performance']
    paths = [CRITERIA, SUPPORT, PILOT, CANCEL, POOL, 'tools/verify-product-g5.py']
    paths.extend(path for path in (PERFORMANCE, RESTART) if (ROOT / path).exists())
    evidence = h.hashes(paths)
    old = load('product_g5_recheck_baseline', 'tools/run-release-support-matrix.py')
    if read(SUPPORT) != old.matrix():
        raise ValueError('Prior support evidence differs')
    pilot, recovery = read(PILOT), read(CANCEL)
    prior_pilot = load('product_g5_pilot_runner', 'tools/run-g5-pilot.py')
    prior_recovery = load('product_g5_recovery_runner', 'tools/run-db-recovery.py')
    verified_inputs(pilot, h.hashes(prior_pilot.INPUTS))
    verified_inputs(recovery, prior_recovery.input_hashes())
    if pilot['status'] != 'PASS' or recovery['status'] != 'PASS':
        raise ValueError('Existing concurrency and recovery evidence differs')
    performance, pools, restarts = performance_result(p), pool_result(p), restart_result(p)
    profiles = {}
    for name in contract['support_profiles']:
        native = name in p['profiles']
        if native and (pilot['profiles'][name]['versions'] != p['profiles'][name]
                       or recovery['profiles'][name]['server_version'] != p['profiles'][name]['server_version']
                       or recovery['profiles'][name]['driver_version'] != p['profiles'][name]['driver_version']):
            raise ValueError('Prior native tuple differs')
        profiles[name] = {'older_fixed_image_evidence': 'VERIFIED', 'pool_functional': pools.get(name, 'NOT RUN'),
                          'native_concurrency_pilot': 'PASS' if native else 'NOT RUN',
                          'jdbc_cancel_timeout_precommit_loss': 'PASS' if native else 'NOT RUN',
                          'observe_p95': performance.get(name, {'status': 'NOT RUN'}),
                          'unknown_commit_outcome': 'NOT RUN', 'graceful_restart_recovery': restarts.get(name, 'NOT RUN'),
                          'crash_restart_recovery': 'NOT RUN'}
    if evidence != h.hashes(paths):
        raise ValueError('Evidence changed during assessment')
    return {'schema_version': 1, 'evidence_review': 'PASS', 'product_g5': 'BLOCKED',
            'performance_criterion': 'NFR-02: Observe p95 <= 105% of baseline', 'product_support': 'NOT CERTIFIED',
            'authorize_publish': False, 'profiles': profiles, 'evidence_sha512': evidence}


def main():
    if sys.argv[1:]:
        print('PRODUCT_G5 INVALID_ARGUMENTS')
        return 2
    try:
        result = acceptance()
        h.save(DECISION, result)
        print(json.dumps({key: value for key, value in result.items() if key != 'evidence_sha512'}))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'evidence_review': 'FAIL', 'failure_type': type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
