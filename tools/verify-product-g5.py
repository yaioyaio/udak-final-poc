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
OBSERVE_BASELINE = 'evidence/PRODUCT-G5-OBSERVE-BASELINE.json'
OBSERVE_BASELINE_ARCHIVE = 'evidence/archive/observe-baseline'
OBSERVE_CANDIDATE = 'evidence/PRODUCT-G5-OBSERVE-CANDIDATE.json'
OBSERVE_BASELINE_REVISION = 'cf616a0f88ded96a68c68467d2b75bd88f2e870d'
OBSERVE_BASELINE_SHA512 = ('3d5cc665f04707ec0c272952bbc4d7e185b7652d81a936fa08bd7d489d114d4aea9f'
                           '943d8bea8f3b633aed4ff2eb49b34f5e73f251c3706f957edd69d4f7e04d')
DEFAULT_CANDIDATE_RUN = 'OBSERVE-V2'
ARCHIVED_RUNS = {
    'OBSERVE-V2': {
        'contracts_path': OBSERVE_CANDIDATE,
        'approval_sha512': ('f9118aaaafab46c39df86cf4910cbc904e5da77def48a42c3327f163d8ba1dbc36e1'
                            '308526a0c15c386162c9aa4596d583b5c761c3b0c982974268af77a49bef'),
        'result_sha512': ('ec257141f502cc2d0d10e7073ba1744499604f400753ab86acc06739dceb6b08fbc5'
                          '5e28e377cc89feeeaf7e072881256a07d443c82ccf4a634ce5fabb6d5f94'),
        'contracts_sha512': ('d8132a587333ca0b56617ddbab33b5940dab36e07cdf4fe6d3544bcae98f3a7dda52'
                             '7fcde8b9cbb8a81d2fd8da5a67d450d94ff6237afe0d0a68892fcaa4e209'),
    },
    'OBSERVE-G5-FOLLOWUP': {
        'contracts_path': 'evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-G5-FOLLOWUP-CONTRACTS.json',
        'approval_sha512': ('c8f32b4f38a3b102ce275bfd80a8aaa93b22789a96f422c1c13fb38b1247bfbf8652'
                            '812d56554a7e0cce7017da7fb75bb48649f8e5a085809f3e8f434906b957'),
        'result_sha512': ('d9a11e0b32f5ce3c48cbf537e9f3cde692cb1cf6d73589c2e59d4891776d0016ca'
                          '3fe818c00baa056c668d8ad4d34162133140f12cf5a19069b850ed63fbca73'),
        'contracts_sha512': ('cbc4099d52a0b9c486edff0a3f46f455c06cd7ec92d1b647840855644bfe37a9c1'
                             '1871495cbe7506455f66aaff9e445605dcf02d3a9a68420c78b04ade7586fe'),
    },
    'OBSERVE-SHAPE-BYTES-01': {
        'contracts_path': 'evidence/PRODUCT-G5-PERFORMANCE-OBSERVE-SHAPE-BYTES-01-CONTRACTS.json',
        'approval_sha512': ('03e5cdf23609ea1a93c00ee21fd24386308c9f29e8137f71821e7b6c84391a9a72e'
                            '7bcefec5f44c8e34c1a4aec816df7d12c5b6c46dac93dae0ff5e5d0e4f8f9'),
        'result_sha512': ('86012b64dbaf8180fdb572b57b06e6c9e46db7ebbb24f31302ce0ce07dde86f975'
                          'fc922a54575e4a5df8778db50b6be67a2c0bcfa165649dec6f65a9cae5f8b7'),
        'contracts_sha512': ('3a160b921aba67b492f271e079224334155e41030dd229e8f13a3bb30e05a121fcf'
                             '90f1e9b5ba7a0840cb9f8e62e5904a2e4a230d23d8ff4798b09f5e90210e7'),
    },
}
POOL = 'evidence/PRODUCT-G5-POOL.json'
RESTART = 'evidence/PRODUCT-G5-RESTART.json'
FAILURE = 'evidence/PRODUCT-G5-FAILURE.json'
ORACLE = 'evidence/PRODUCT-G5-ORACLE.json'
ORACLE_RECOVERY = 'evidence/PRODUCT-G5-ORACLE-RECOVERY.json'
ORACLE_INSTANCE = 'evidence/PRODUCT-G5-ORACLE-INSTANCE.json'
SQLSERVER_NATIVE = 'evidence/PRODUCT-G5-SQLSERVER.json'
SQLSERVER_APPROVAL = 'evidence/PRODUCT-G5-SQLSERVER-APPROVAL.json'
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


def performance_result(p, run_id=None):
    run = load('product_g5_performance_runner', 'tools/run-g5-performance.py')
    path = PERFORMANCE if run_id is None else run.run_paths(run_id)[1]
    if not (ROOT / path).exists():
        return {name: {'status': 'NOT RUN'} for name in p['profiles']}
    proof = read(path)
    if run_id is not None and (proof.get('schema_version') != 2 or proof.get('run_id') != run_id):
        raise ValueError('Candidate performance report identity differs')
    archived = ARCHIVED_RUNS.get(run_id)
    if archived is not None:
        approval, _ = run.run_paths(run_id)
        digest = archived['approval_sha512']
        if h.hashes((approval, path)) != {approval: digest, path: archived['result_sha512']}:
            raise ValueError('Archived candidate approval or result differs')
        signed = read(approval)
        if signed['criteria_sha512'] != h.hashes((CRITERIA,))[CRITERIA]:
            raise ValueError('Archived candidate criteria differ')
        verified_inputs(proof, {**signed['candidate_sha512'], approval: digest})
    else:
        run.authorized(run_id)
        verified_inputs(proof, run.input_hashes(run_id))
    prior_profiles = read(PILOT)['profiles']
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
        step = row['step']
        if (row['versions'] != p['profiles'][name] or checked != row['assessment'] or row['status'] != checked['status']
                or runtime['version'] != p['profiles'][name]['server_version']
                or runtime['server_sha256'] != prior_profiles[name]['native_runtime']['server_sha256']
                or not 0 < runtime['peak_rss_bytes'] <= p['limits']['db_rss_bytes']
                or not 0 < runtime['peak_data_bytes'] <= p['limits']['db_scratch_bytes']
                or not runtime['loopback_listener_owned'] or not runtime['server_stopped']
                or not runtime['process_groups_quiesced'] or step['status'] != 'PASS'
                or not step['child_reaped'] or not step['process_group_quiesced']):
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


def failure_result(p):
    if not (ROOT / FAILURE).exists():
        return {}
    proof = read(FAILURE)
    runner = load('product_g5_failure_runner', 'tools/release-failure/run-failure.py')
    verified_inputs(proof, runner.inputs())
    if (proof['requirement'] != 'RELEASE-011' or proof['status'] != 'PASS'
            or proof['profiles'].keys() != p['profiles'].keys() or proof['scenario_count'] != 4
            or proof['limits'] != runner.LIMITS or proof['docker_containers_started'] != 0
            or proof['cleanup']['status'] != 'PASS' or proof['cleanup']['remaining'] is not False):
        raise ValueError('Functional failure recovery proof incomplete')
    result = {}
    for name, row in proof['profiles'].items():
        expected = p['profiles'][name]
        crashed, recovered = row['crashed_runtime'], row['recovered_runtime']
        if (row['status'] != 'PASS' or row['server_version'] != expected['server_version']
                or row['driver_version'] != expected['driver_version'] or row['crash_signal'] != 'SIGKILL'
                or row['crash_exit_code'] != -9 or not row['seed_process_reaped']
                or not row['uncommitted_write_observed'] or not recovered['owned_data_directory_reused']
                or not recovered['fresh_loopback_port'] or not recovered['graceful_stop']
                or recovered['server_exit_code'] != 0 or crashed['server_sha256'] != recovered['server_sha256']
                or row['scenarios'] != {'CRASH_RESTART': 'PASS', 'LOST_COMMIT_ACK': 'PASS'}):
            raise ValueError('Recovery result or runtime identity differs')
        for runtime in (crashed, recovered):
            if runtime['version'] != expected['server_version'] or not all(runtime[key] is True for key in
                    ('loopback_listener_owned', 'server_stopped', 'process_groups_quiesced')):
                raise ValueError('Recovery process cleanup or ownership unconfirmed')
        for step in (row['crash_recovery_step'], row['unknown_commit_step']):
            if step['status'] != 'PASS' or not step['child_reaped'] or not step['process_group_quiesced']:
                raise ValueError('Recovery client result incomplete')
        result[name] = row['scenarios']
    return result


def oracle_result():
    if not (ROOT / ORACLE).exists():
        return {}
    proof = read(ORACLE)
    runner = load('product_g5_oracle_runner', 'tools/release-provider/run-oracle.py')
    verified_inputs(proof, h.hashes(runner.INPUTS))
    prior = read('evidence/PHASE5-REAL-VALIDATION.json')['profiles']['ORACLE']
    if (proof['requirement'] != 'RELEASE-012' or proof['profile'] != 'ORACLE' or proof['status'] != 'PASS'
            or proof['stage'] != 'COMPLETE' or proof['platform'] != 'linux/arm64'
            or proof['image'] != prior['image'] or proof['driver_version'] != runner.COORDINATE.rsplit(':', 1)[1]
            or not re.fullmatch(r'23\.26(?:\.[0-9]{1,3}){3}', proof['server_version'])
            or proof['pool'] != runner.pool.HIKARI or proof['limits'] != runner.LIMITS
            or proof['scenarios'] != {'ROLLBACK_RESET_REUSE': 'PASS', 'INDEPENDENT_COMMIT_VISIBILITY': 'PASS'}
            or proof['docker_containers_started'] != 1 or proof['docker_containers_created'] != 0
            or proof['schema_cleanup'] != 'CONFIRMED' or proof['storage_cleanup'] != 'CONFIRMED'
            or proof['retention_cleanup'] != 'CONFIRMED' or not proof['retained_bounds_reapplied']
            or not proof['live_cgroup_verified']
            or proof['retained_instances'] != 12 or proof['managed_running'] != 0
            or proof['cleanup']['status'] != 'PASS' or proof['cleanup']['remaining'] is not False):
        raise ValueError('Oracle isolated pool evidence differs')
    return {key: proof[key] for key in ('server_version', 'driver_version', 'platform', 'scenarios')}


def oracle_recovery_result(oracle):
    if not (ROOT / ORACLE_RECOVERY).exists():
        return {}
    proof = read(ORACLE_RECOVERY)
    runner = load('product_g5_oracle_recovery', 'tools/release-provider/run-oracle-recovery.py')
    verified_inputs(proof, runner.inputs())
    if (not oracle or proof['requirement'] != 'RELEASE-013' or proof['profile'] != 'ORACLE' or proof['status'] != 'PASS'
            or proof['image'] != read(ORACLE)['image'] or proof['limits'] != runner.LIMITS
            or any(proof[key] != oracle[key] for key in ('server_version', 'driver_version', 'platform'))
            or proof['scenario_count'] != len(runner.SCENARIOS)
            or proof['scenarios'] != dict.fromkeys(runner.SCENARIOS, 'PASS')
            or proof['starts_of_retained_container'] != 2 or proof['new_containers'] != 0
            or proof['oracle_shutdown_immediate_confirmed'] is not True
            or any(proof[key] != 'CONFIRMED' for key in ('schema_cleanup', 'storage_cleanup', 'retention_cleanup'))
            or proof['retained_instances'] != 12 or proof['managed_running'] != 0
            or proof['cleanup']['status'] != 'PASS' or proof['cleanup']['remaining'] is not False
            or any(proof['commit_ack_step'].get(key) is not True for key in ('child_reaped', 'process_group_quiesced'))):
        raise ValueError('Oracle recovery evidence or cleanup differs')
    return proof['scenarios']


def oracle_instance_result(oracle):
    if not (ROOT / ORACLE_INSTANCE).exists():
        return {}
    proof = read(ORACLE_INSTANCE)
    runner = load('product_g5_oracle_instance', 'tools/release-provider/run-oracle-instance.py')
    verified_inputs(proof, h.hashes(runner.sources()))
    cap = runner.authorized()
    metrics = proof['concurrency']
    pattern = 'ORACLE_INSTANCE CONCURRENCY PASS {starts} {max_in_flight} {max_rolling_second} {min_spacing_ns}\n'
    if (not oracle or proof['requirement'] != 'RELEASE-014' or proof['status'] != 'PASS'
            or proof['oracle_instance_g5'] != 'PASS' or proof['crash_recovery'] != 'PASS'
            or proof['image'] != runner.get_pin()['image'] or proof['limits'] != runner.LIMITS
            or proof['approval_sha512'] != h.hashes((runner.APPROVAL,))[runner.APPROVAL]
            or any(proof[key] != oracle[key] for key in ('server_version', 'driver_version', 'platform'))
            or metrics != runner.protocol(pattern.format(**metrics).encode('ascii')) or proof['crash_exit_code'] != 137
            or any(proof[key] is not True for key in ('matching_dbid_and_new_startup', 'cgroup_limits_confirmed',
                                                      'storage_quota_creation_confirmed'))
            or proof['retention_cleanup'] != 'PASS' or proof['retained_before'] != cap - 1
            or proof['retained_after'] != cap - 1 or proof['cleanup']['status'] != 'PASS'
            or proof['cleanup']['remaining'] is not False):
        raise ValueError('Oracle instance evidence or authorization differs')
    for step in ('concurrency_step', 'recovery_step'):
        if proof[step]['status'] != 'PASS' or not proof[step]['child_reaped'] or not proof[step]['process_group_quiesced']:
            raise ValueError('Oracle instance client ownership differs')
    return {'native_concurrency_pilot': 'PASS', 'crash_restart_recovery': 'PASS'}


def g5_blockers(profiles, performance_profiles):
    required = ('pool_functional', 'native_concurrency_pilot', 'jdbc_cancel_timeout_precommit_loss',
                'unknown_commit_outcome', 'graceful_restart_recovery', 'crash_restart_recovery')
    blockers = {}
    for name, row in profiles.items():
        missing = {key: row[key] for key in required if row[key] != 'PASS'}
        if name in performance_profiles and row['observe_p95']['status'] != 'PASS':
            missing['observe_p95'] = row['observe_p95']['status']
        if missing:
            blockers[name] = missing
    return blockers


def observe_baseline(p):
    if h.hashes([OBSERVE_BASELINE])[OBSERVE_BASELINE] != OBSERVE_BASELINE_SHA512:
        raise ValueError('Archived Observe baseline differs from the accepted decision')
    snapshot = read(OBSERVE_BASELINE)
    immutable_inputs = dict(snapshot['evidence_sha512'])
    # The historical verifier is covered by the archived decision digest. Its current
    # source assesses the candidate and can change independently of the original run.
    del immutable_inputs['tools/verify-product-g5.py']
    historical_paths = {
        path: f'{OBSERVE_BASELINE_ARCHIVE}/{Path(path).name}' if path in (CANCEL, POOL, RESTART, FAILURE) else path
        for path in immutable_inputs
    }
    actual = h.hashes(historical_paths.values())
    if any(actual[historical_paths[path]] != digest for path, digest in immutable_inputs.items()):
        raise ValueError('Archived Observe inputs changed')
    proof = read(PERFORMANCE)
    run = load('product_g5_archived_authorization', 'tools/run-g5-performance.py')
    run.authorized()
    if proof['input_sha512'][run.APPROVAL] != h.hashes([run.APPROVAL])[run.APPROVAL]:
        raise ValueError('Archived authorization differs')
    for name in p['profiles']:
        row = proof['profiles'][name]
        if compare(row['plain_ns'], row['observe_ns'], p) != snapshot['profiles'][name]['observe_p95']:
            raise ValueError('Archived Observe verdict differs')
    return snapshot


def performance_run_stem(run_id):
    if not re.fullmatch(r'[A-Z][A-Z0-9]*(?:-[A-Z0-9]+){0,5}', run_id) or len(run_id) > 32:
        raise ValueError('Invalid performance run ID')
    return 'evidence/PRODUCT-G5-PERFORMANCE-' + run_id


def candidate_evidence_path(run_id):
    archived = ARCHIVED_RUNS.get(run_id)
    if archived is not None:
        return archived['contracts_path']
    return performance_run_stem(run_id) + '-CONTRACTS.json'


def candidate_status(run_id):
    path = candidate_evidence_path(run_id)
    if not (ROOT / path).exists():
        return {'status': 'NOT RUN'}
    report = read(path)
    runner = load('observe_candidate_checks', 'tools/release-performance/verify-observe-candidate.py')
    archived = ARCHIVED_RUNS.get(run_id)
    if archived is not None:
        if h.hashes((path,))[path] != archived['contracts_sha512']:
            raise ValueError('Archived candidate contracts differ')
    else:
        if report.get('schema_version') != 2 or report.get('run_id') != run_id:
            raise ValueError('Candidate contract evidence identity differs')
        verified_inputs(report, runner.input_hashes())
    if (report['status'] != 'PASS' or report['requirement'] != 'RELEASE-015'
            or report['real_database_trials'] != 0 or report['performance_trials'] != 0
            or report['cleanup']['status'] != 'PASS' or report['cleanup']['temporary_directory_remaining'] is not False
            or report['h2']['status'] != 'PASS' or report['h2']['checks'] != 10
            or any(step['status'] != 'PASS' or not step['process_group_quiesced'] or not step['child_reaped']
                   for step in report['steps'].values())
            or report['steps'].keys() != (runner.CONTRACTS.keys() | {'core-smoke', 'compile-phase3'})):
        raise ValueError('Observe candidate contract evidence differs')
    return {'status': 'PASS', 'h2': report['h2']['checks'],
            'observe_assertions': report['steps']['observe-contract']['assertions'],
            'adapter_assertions': report['steps']['adapter-contract']['assertions']}


def acceptance(run_id=None):
    contract = criteria()
    p = contract['performance']
    archived = observe_baseline(p) if (ROOT / OBSERVE_BASELINE).exists() else None
    if archived is not None:
        run_id = run_id or DEFAULT_CANDIDATE_RUN
    paths = [CRITERIA, SUPPORT, PILOT, CANCEL, POOL, 'tools/verify-product-g5.py']
    paths.extend(path for path in (PERFORMANCE, RESTART, FAILURE, ORACLE, ORACLE_RECOVERY, ORACLE_INSTANCE)
                 if (ROOT / path).exists())
    if (ROOT / SQLSERVER_NATIVE).exists():
        paths.extend((SQLSERVER_NATIVE, SQLSERVER_APPROVAL, 'tools/release-provider/verify-sqlserver-g5.py'))
    optional_run_evidence = []
    if archived is not None:
        contracts = candidate_evidence_path(run_id)
        optional_run_evidence.append(contracts)
        paths.extend(path for path in (OBSERVE_BASELINE, contracts) if (ROOT / path).exists())
    if run_id is not None:
        runner = load('product_g5_candidate_runner', 'tools/run-g5-performance.py')
        approval, result = runner.run_paths(run_id)
        optional_run_evidence.append(result)
        if (ROOT / result).exists():
            paths.extend((approval, result))
    evidence = h.hashes(paths)
    if archived is None:
        old = load('product_g5_recheck_baseline', 'tools/run-release-support-matrix.py')
        if read(SUPPORT) != old.matrix():
            raise ValueError('Prior support evidence differs')
    pilot, recovery = read(PILOT), read(CANCEL)
    prior_pilot = load('product_g5_pilot_runner', 'tools/run-g5-pilot.py')
    prior_recovery = load('product_g5_recovery_runner', 'tools/run-db-recovery.py')
    verified_inputs(pilot, h.hashes(prior_pilot.INPUTS))
    recovery_matches_candidate = recovery['input_sha512'] == prior_recovery.input_hashes()
    if archived is None and not recovery_matches_candidate:
        raise ValueError('Current recovery inputs differ')
    if pilot['status'] != 'PASS' or recovery['status'] != 'PASS':
        raise ValueError('Existing concurrency and recovery evidence differs')
    performance, pools, restarts = performance_result(p, run_id), pool_result(p), restart_result(p)
    failures = failure_result(p)
    oracle = oracle_result()
    oracle_recovery = oracle_recovery_result(oracle)
    profiles = {}
    for name in contract['support_profiles']:
        native = name in p['profiles']
        if native and (pilot['profiles'][name]['versions'] != p['profiles'][name]
                       or recovery['profiles'][name]['server_version'] != p['profiles'][name]['server_version']
                       or recovery['profiles'][name]['driver_version'] != p['profiles'][name]['driver_version']):
            raise ValueError('Prior native tuple differs')
        profiles[name] = {'older_fixed_image_evidence': 'HISTORICAL' if archived else 'VERIFIED',
                          'pool_functional': pools.get(name, 'NOT RUN'),
                          'native_concurrency_pilot': 'PASS' if native else 'NOT RUN',
                          'jdbc_cancel_timeout_precommit_loss': ('PASS' if recovery_matches_candidate else 'HISTORICAL PASS')
                          if native else 'NOT RUN',
                          'observe_p95': performance.get(name, {'status': 'NOT RUN'}),
                          'unknown_commit_outcome': failures.get(name, {}).get('LOST_COMMIT_ACK', 'NOT RUN'),
                          'graceful_restart_recovery': restarts.get(name, 'NOT RUN'),
                          'crash_restart_recovery': failures.get(name, {}).get('CRASH_RESTART', 'NOT RUN')}
    profiles['SQLSERVER']['native_support_precondition'] = 'Require isolated x86-64 Linux provider'
    if SQLSERVER_NATIVE in evidence:
        verifier = load('product_g5_sqlserver', 'tools/release-provider/verify-sqlserver-g5.py')
        profiles['SQLSERVER'].update(verifier.assess())
    if oracle:
        profiles['ORACLE']['pool_subset'] = oracle
    if oracle_recovery:
        profiles['ORACLE'].update(pool_functional=oracle_recovery['SESSION_REPLACEMENT'],
            jdbc_cancel_timeout_precommit_loss='PASS', unknown_commit_outcome=oracle_recovery['LOST_COMMIT_ACK'],
            graceful_restart_recovery=oracle_recovery['GRACEFUL_RESTART'], recovery_scenarios=oracle_recovery)
    profiles['ORACLE'].update(oracle_instance_result(oracle))
    blockers = g5_blockers(profiles, p['profiles'])
    candidate = candidate_status(run_id) if archived else None
    if candidate and candidate['status'] != 'PASS':
        blockers['OBSERVE_CANDIDATE'] = {'functional': candidate['status']}
    if (any((ROOT / path).exists() != (path in evidence) for path in optional_run_evidence)
            or evidence != h.hashes(paths)):
        raise ValueError('Evidence changed during assessment')
    result = {'schema_version': 1, 'evidence_review': 'PASS', 'product_g5': 'BLOCKED' if blockers else 'PASS',
            'performance_criterion': 'NFR-02: Observe p95 <= 105% of baseline', 'product_support': 'NOT CERTIFIED',
            'authorize_publish': False, 'profiles': profiles, 'g5_blockers': blockers, 'evidence_sha512': evidence}
    if archived:
        result['observe_candidate'] = {'run_id': run_id, 'functional': candidate}
        result['previous_observe_run'] = {'revision': OBSERVE_BASELINE_REVISION, 'profiles': {
            name: archived['profiles'][name]['observe_p95'] for name in p['profiles']}}
    return result


def main():
    args = sys.argv[1:]
    if args and (len(args) != 2 or args[0] != '--run-id'):
        print('PRODUCT_G5 INVALID_ARGUMENTS')
        return 2
    try:
        result = acceptance(args[1] if args else None)
        h.save(DECISION, result)
        print(json.dumps({key: value for key, value in result.items() if key != 'evidence_sha512'}))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'evidence_review': 'FAIL', 'failure_type': type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
