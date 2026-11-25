#!/usr/bin/env python3
"""Prepare and verify a two-DB crossover with one JDBC connection per profile."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import signal
import statistics
import subprocess
import sys

import lexer_crossover_sources as sources

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = 'OBSERVE-LEXER-CROSSOVER-01'
STEM = f'evidence/PRODUCT-G5-{RUN_ID}'
PREPARATION = STEM + '-PREPARATION.json'
APPROVAL = STEM + '-APPROVAL.json'
RESULT = STEM + '-RESULT.json'
VARIANTS = {
    'before': ('OBSERVE-DIGEST-TEMPLATE-01', 'bf2b0ab71bb250dc6188e2bb97f0df87a0260b72'),
    'after': ('OBSERVE-LEXER-WORDS-01', '4bbbc8a421bf782b2c6775f24e6611cebf7b7610'),
}
PROFILES = ('POSTGRESQL', 'MYSQL')
PREPARED_FIELDS = ('native_binaries', 'jdbc_dependencies', 'spring_dependencies', 'generated_sha512')
PREVIOUS = 'tools/release-performance/run-postgres-comparison.py'
PROBE_CLASS = 'dev.udak.diagnostic.LexerCrossoverProbe'
FIXTURE_CLASS = 'ProductG5PerformanceMain'
STARTS_PER_PROFILE = 160

spec = importlib.util.spec_from_file_location('postgres_comparison', ROOT / PREVIOUS)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
performance, review, schema, native, h = guard.performance, guard.review, guard.schema, guard.native, guard.h
require = guard.require


def proposal():
    profile_criteria = review.criteria()['performance']
    pins, archived_paths = {}, []
    for arm, (run_id, revision) in VARIANTS.items():
        approval, result = performance.run_paths(run_id)
        archived_paths.extend((approval, result, review.candidate_evidence_path(run_id)))
        require(review.candidate_status(run_id)['status'] == 'PASS', 'SOURCE_CONTRACTS_UNVERIFIED')
        official = review.performance_result(profile_criteria, run_id)
        require(all(row['status'] in ('PASS', 'FAIL') for row in official.values()), 'OFFICIAL_INPUT_UNVERIFIED')
        pins[arm] = review.read(approval)['candidate_sha512']
        # Read only the fixed execution inputs bound to each historical approval.
        for path, digest in pins[arm].items():
            sources.pinned_source(ROOT, revision, path, digest)
    before, after = pins['before'], pins['after']
    differences = {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
    require(differences == {sources.SHAPE, 'tools/verify-product-g5.py'}, 'SOURCE_SCOPE_CHANGED')
    files = (*performance.performance_inputs(), *archived_paths, PREVIOUS, guard.HOST_PROBE, sources.PROBE,
             'tools/run-phase1.py', 'tools/run-phase4.py', 'tools/run-phase5.py',
             review.read(performance.SPRING)['h2_license_file'],
             'tools/release-performance/comparison_sources.py', 'tools/release-performance/attribution_sources.py',
             'tools/release-performance/lexer_crossover_sources.py', 'tools/release-performance/run-lexer-crossover.py',
             'tools/release-performance/test-lexer-crossover.py')
    binary_proof = review.read(review.PILOT)['profiles']
    return {'schema_version': 1, 'run_id': RUN_ID, 'diagnostic_only': True,
            'variants': {arm: {'run_id': run_id, 'revision': rev} for arm, (run_id, rev) in VARIANTS.items()},
            'profiles': {name: {**profile_criteria['profiles'][name],
                                'sha256': binary_proof[name]['native_runtime']['server_sha256']} for name in PROFILES},
            'profile_order': list(PROFILES), 'limits': profile_criteria['limits'],
            'host_stability': dict(guard.STABILITY), 'input_sha512': h.hashes(files),
            'design': {'connection_per_profile': 1, 'jvm_per_profile': 1, 'blocks_per_profile': 4,
                       'warmup_pairs_per_block': 4, 'measured_pairs_per_block': 16,
                       'starts_per_profile': STARTS_PER_PROFILE, 'total_starts': 2 * STARTS_PER_PROFILE,
                       'metrics': ['SHAPE_ALLOCATED_BYTES', 'JDBC_EXECUTE_NS']}}


def approval_for(plan):
    return {'schema_version': 1, 'status': 'APPROVED', 'run_id': RUN_ID, 'authorized_runs': 1,
            'approval_basis': 'EXPLICIT_USER_CONFIRMATION', 'proposal_sha512': guard.digest(plan)}


def approval_hash(plan):
    require((ROOT / APPROVAL).is_file(), 'SEPARATE_APPROVAL_REQUIRED')
    require(guard.canonical(review.read(APPROVAL)) == guard.canonical(approval_for(plan)), 'APPROVAL_SCOPE_CHANGED')
    return h.hashes((APPROVAL,))[APPROVAL]


def decode(protocol, profile, limits):
    lines = protocol.splitlines()
    require(profile in PROFILES and len(lines) == 8, 'PROTOCOL_LENGTH_OR_PROFILE')
    header = re.fullmatch(
        f'LEXER_CROSSOVER profile={profile} starts=160 completed=160 warmup_per_arm=16 measured_per_arm=64'
        r' verified_rows=160 events=160 errors=0 max_in_flight=1 max_rolling_second=([1-8]) min_spacing_ns=([0-9]{1,11})',
        lines[0])
    event = re.fullmatch(r'EVENT_KEY ([a-f0-9]{64}) ([a-f0-9]{64})', lines[1])
    require(header is not None and event is not None, 'FIXTURE_PROTOCOL')
    order = guard.numbers(lines[2], 'SCHEDULE', STARTS_PER_PROFILE)
    require(order == [row for block in range(4) for row in guard.expected_schedule(block)], 'PAIR_SCHEDULE')
    gaps = guard.numbers(lines[3], 'GAPS_NS', STARTS_PER_PROFILE - 1)
    require((guard.pacing(gaps, limits), min(gaps)) == (int(header[1]), int(header[2])), 'PACING_RECEIPT')
    keys = ('BEFORE_SHAPE_BYTES', 'AFTER_SHAPE_BYTES', 'BEFORE_JDBC_EXECUTE_NS', 'AFTER_JDBC_EXECUTE_NS')
    samples = {key: guard.numbers(line, key, 64) for key, line in zip(keys, lines[4:], strict=True)}
    blocks = []
    for start in range(0, 64, 16):
        entry = {}
        for suffix in ('SHAPE_BYTES', 'JDBC_EXECUTE_NS'):
            before, after = (samples[f'{arm}_{suffix}'][start:start + 16] for arm in ('BEFORE', 'AFTER'))
            entry[suffix] = {'before_median': statistics.median(before), 'after_median': statistics.median(after),
                             'median_paired_after_minus_before': statistics.median(
                                 b - a for a, b in zip(before, after, strict=True))}
        blocks.append(entry)
    return {'starts': STARTS_PER_PROFILE, 'events': STARTS_PER_PROFILE, 'measured_pairs': 64,
            'max_rolling_second': int(header[1]), 'min_spacing_ns': int(header[2]),
            'event_key': list(event.groups()), 'blocks': blocks}


def build(work, plan, result):
    result['native_binaries'] = {}
    paths = {'POSTGRESQL': native.PG / 'postgres', 'MYSQL': native.MYSQL / 'mysqld'}
    for profile in PROFILES:
        pin = plan['profiles'][profile]
        binary = native._fingerprint(paths[profile], profile.lower(), work)
        require(binary == {'version': pin['server_version'], 'server_sha256': pin['sha256']}, 'DB_BINARY')
        result['native_binaries'][profile] = binary
    jdbc, result['jdbc_dependencies'] = schema.pinned_drivers(work)
    spring, result['spring_dependencies'] = schema.g2.phase2.dependencies(work, review.read(performance.SPRING))
    signed = {name: review.read(performance.run_paths(info['run_id'])[0])['candidate_sha512']
              for name, info in plan['variants'].items()}
    revisions = {name: info['revision'] for name, info in plan['variants'].items()}
    inputs, result['generated_sha512'] = sources.materialize(
        ROOT, work, revisions, signed, performance.sources(), plan['input_sha512'][sources.PROBE])
    classes = work / 'classes'
    classes.mkdir()
    cp = ':'.join(str(jar) for jar in (*jdbc, *spring))
    command = [*schema.base.JAVAC, '-cp', cp, '-d', str(classes), *map(str, inputs)]
    result['compile'], _ = native.run_private('lexer-crossover-compile', performance.limited(command, plan), work, 30)
    classpath = f'{classes}:{cp}'
    command = [*schema.base.JAVA, '-cp', classpath, PROBE_CLASS]
    result['probe'], output = native.run_private('lexer-crossover-probe', performance.limited(command, plan), work, 15)
    require(guard.reaped(result['compile']) and guard.reaped(result['probe'])
            and output.stat().st_size == 27 and output.read_bytes() == b'LEXER_CROSSOVER_PROBE PASS\n', 'PROBE_SELF_CHECK')
    return classpath


def prepared(plan):
    receipt = review.read(PREPARATION)
    require(receipt['run_id'] == RUN_ID and receipt['status'] == 'PASS'
            and receipt['proposal_sha512'] == guard.digest(plan) and guard.clean(receipt['cleanup'])
            and guard.reaped(receipt['compile']) and guard.reaped(receipt['probe'])
            and receipt['database_started'] is False and receipt['workload_run_claimed'] is False,
            'PREPARATION_UNVERIFIED')
    return receipt


def prepare(plan, result):
    require(not (ROOT / PREPARATION).exists(), 'PREPARATION_ALREADY_RECORDED')
    with guard.protected_workspace() as (work, cleanup):
        result['cleanup'] = cleanup
        guard.check_host(work)
        with guard.watch_host(work):
            build(work, plan, result)
        require(proposal() == plan, 'INPUTS_CHANGED')
    require(guard.clean(cleanup), 'WORKSPACE_CLEANUP')
    result['status'] = 'PASS'
    guard.save_once(ROOT / PREPARATION, result)


def measure(profile, work, classpath, plan, result):
    result['initialization_attempted'] = True
    with native.instance(profile.lower(), work) as (port, private, runtime):
        result['runtime'] = runtime
        require(runtime['loopback_listener_owned'] is True and
                all(runtime[key] == pin for key, pin in result['binary'].items()), 'DB_LISTENER_IDENTITY')
        command = [*schema.base.JAVA, '-cp', classpath, FIXTURE_CLASS, profile, str(port)]
        result['client'], output = native.run_private('crossover-' + profile.lower(), performance.limited(command, plan),
            work, performance.CLIENT_SECONDS, (private + '\n').encode('ascii'))
        require(guard.reaped(result['client']) and 0 < output.stat().st_size <= guard.PROTOCOL_BYTES, 'CLIENT_RECEIPT')
        protocol = output.read_text(encoding='ascii')
        summary = decode(protocol, profile, plan['limits'])
        result.update(protocol=protocol, summary=summary)
    require(runtime['server_stopped'] is True and runtime['process_groups_quiesced'] is True, 'DB_CLEANUP')


def run(plan, result):
    signed = approval_hash(plan)
    prep = prepared(plan)
    marker = ROOT / '.git/udak-product-g5' / (RUN_ID + '.claimed')
    try:
        with guard.protected_workspace() as (work, cleanup):
            require(not marker.exists() and not (ROOT / RESULT).exists(), 'APPROVAL_ALREADY_USED')
            result['cleanup'] = cleanup
            guard.check_host(work)
            with guard.watch_host(work):
                classpath = build(work, plan, result)
                require(all(result[key] == prep[key] for key in PREPARED_FIELDS), 'PREPARED_INPUTS_CHANGED')
                readings = result['host_pressure_readings'] = []
                guard.stable_host(work, plan['host_stability'], readings)
                require(proposal() == plan and approval_hash(plan) == signed, 'INPUTS_CHANGED')
                guard.check_host(work)
                guard.claim(marker, signed)
                result.update(status='INCONCLUSIVE', approval_sha512=signed, workload_run_claimed=True)
                results = result['profiles'] = {}
                for profile in plan['profile_order']:
                    guard.check_host(work)
                    results[profile] = {'binary': result['native_binaries'][profile]}
                    measure(profile, work, classpath, plan, results[profile])
        require(guard.clean(cleanup), 'WORKSPACE_CLEANUP')
        result['status'] = 'PASS'
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        if result['workload_run_claimed']:
            result['stop_reason'] = guard.failure_code(error)
        raise
    finally:
        if result['workload_run_claimed']:
            result['database_started'] = any('runtime' in row for row in result['profiles'].values())
            guard.save_once(ROOT / RESULT, result)


def verify(plan):
    result = review.read(RESULT)
    prep = prepared(plan)
    require(result['run_id'] == RUN_ID and result['status'] == 'PASS' and result['diagnostic_only'] is True
            and result['workload_run_claimed'] is True and result['database_started'] is True
            and result['proposal_sha512'] == guard.digest(plan)
            and result['approval_sha512'] == approval_hash(plan) and guard.clean(result['cleanup'])
            and guard.reaped(result['compile']) and guard.reaped(result['probe'])
            and all(result[key] == prep[key] for key in PREPARED_FIELDS)
            and guard.canonical(result['host_pressure_readings']) ==
                guard.canonical([1] * plan['host_stability']['samples'])
            and set(result['profiles']) == set(PROFILES), 'RESULT_UNVERIFIED')
    checked = {}
    for profile, row in result['profiles'].items():
        runtime = row['runtime']
        require(guard.reaped(row['client']) and runtime['server_stopped'] is True
                and runtime['process_groups_quiesced'] is True and runtime['loopback_listener_owned'] is True
                and 0 < runtime['peak_rss_bytes'] <= plan['limits']['db_rss_bytes']
                and 0 < runtime['peak_data_bytes'] <= plan['limits']['db_scratch_bytes']
                and all(runtime[k] == v for k, v in prep['native_binaries'][profile].items())
                and 0 < len(row['protocol']) <= guard.PROTOCOL_BYTES, 'PROFILE_UNVERIFIED')
        checked[profile] = decode(row['protocol'], profile, plan['limits'])
        require(checked[profile] == row['summary'], 'SUMMARY_UNVERIFIED')
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('proposal', 'prepare', 'run', 'verify'))
    args = parser.parse_args()
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, schema.interrupted)
    result = {'status': 'NOT RUN', 'run_id': RUN_ID, 'diagnostic_only': True,
              'workload_run_claimed': False, 'database_started': False}
    signal.alarm(300)
    try:
        plan = proposal()
        result['proposal_sha512'] = guard.digest(plan)
        if args.mode == 'proposal':
            answer = {key: value for key, value in plan.items() if key != 'input_sha512'}
            answer['proposal_sha512'] = result['proposal_sha512']
        elif args.mode == 'prepare':
            prepare(plan, result)
            answer = {key: result[key] for key in ('status', 'proposal_sha512', 'database_started', 'cleanup')}
        elif args.mode == 'run':
            run(plan, result)
            answer = {name: row['summary'] for name, row in result['profiles'].items()}
        else:
            answer = verify(plan)
        print(json.dumps(answer, sort_keys=True))
        return 0
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'INCONCLUSIVE' if result['workload_run_claimed'] else 'NOT RUN',
                          'reason': guard.failure_code(error), 'workload_run_claimed': result['workload_run_claimed'],
                          'cleanup': result.get('cleanup')}, sort_keys=True))
        return 1
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    sys.exit(main())
