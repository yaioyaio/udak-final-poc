#!/usr/bin/env python3
"""Diagnose PostgreSQL baseline variation and Observe costs on one JDBC connection."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import signal
import statistics
import subprocess
import sys

import pg_hotpath_sources as sources

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = 'OBSERVE-PG-HOTPATH-DIAG-01'
BEFORE = 'OBSERVE-LEXER-WORDS-02'
AFTER = 'OBSERVE-JDBC-HOTPATH-01'
VARIANTS = {'before': '030a69ab19e014f7805954faf28a920630560d10',
            'after': '4d1bc0bfeac7c08ff83fea70a2e48550fb08d097'}
STEM = f'evidence/PRODUCT-G5-{RUN_ID}'
PREPARATION, APPROVAL, RESULT = (STEM + suffix + '.json' for suffix in ('-PREPARATION', '-APPROVAL', '-RESULT'))
PRIOR_RUNNER = 'tools/release-performance/run-postgres-comparison.py'
ARMS = ('PLAIN_A', 'PLAIN_B', 'BEFORE', 'AFTER')
ORDERS = ((0, 1, 3, 2), (1, 2, 0, 3), (2, 3, 1, 0), (3, 0, 2, 1))
METRICS = ('TOTAL', 'CONNECTION_WRAP', 'STATEMENT_WRAP', 'METADATA', 'EVENT_SINK', 'JDBC_PREPARE', 'JDBC_EXECUTE')
OBSERVE_METRICS = METRICS[1:5]
BUILD_KEYS = ('native_binary', 'jdbc_dependencies', 'spring_dependencies', 'generated_sha512')
FIXTURE = 'ProductG5PerformanceMain'
TRIAL = 'dev.udak.diagnostic.PgHotPathTrial'

spec = importlib.util.spec_from_file_location('hotpath_guard', ROOT / PRIOR_RUNNER)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
performance, review, schema, native, h = guard.performance, guard.review, guard.schema, guard.native, guard.h
require = guard.require


def pinned_inputs():
    previous, result = performance.run_paths(BEFORE)
    previous_contract, current_contract = (review.candidate_evidence_path(run_id) for run_id in (BEFORE, AFTER))
    paths = previous, result, previous_contract, current_contract
    require(all(review.candidate_status(run_id)['status'] == 'PASS' for run_id in (BEFORE, AFTER)), 'CONTRACTS_UNVERIFIED')
    before = review.read(previous)['candidate_sha512']
    after = {**review.read(current_contract)['input_sha512'], **h.hashes((performance.FIXTURE,))}
    for arm, pins in (('before', before), ('after', after)):
        for name, digest in pins.items():
            sources.pinned_source(ROOT, VARIANTS[arm], name, digest)
    changed = {name for name in performance.sources() if before[name] != after[name]}
    require(changed == {sources.OBSERVER, sources.DATA_SOURCE}, 'VARIANT_SCOPE_CHANGED')
    return {'before': before, 'after': after}, paths


def proposal():
    _, reports = pinned_inputs()
    criteria = review.criteria()['performance']
    require(review.performance_result(criteria, BEFORE)['POSTGRESQL']['status'] == 'FAIL', 'REFERENCE_UNVERIFIED')
    binary = review.read(review.PILOT)['profiles']['POSTGRESQL']['native_runtime']['server_sha256']
    paths = (*performance.performance_inputs(), *reports, PRIOR_RUNNER, guard.HOST_PROBE, sources.TRIAL,
             'tools/run-phase1.py', 'tools/run-phase4.py', 'tools/run-phase5.py',
             review.read(performance.SPRING)['h2_license_file'],
             'tools/release-performance/attribution_sources.py', 'tools/release-performance/comparison_sources.py',
             'tools/release-performance/lexer_crossover_sources.py', 'tools/release-performance/pg_hotpath_sources.py',
             'tools/release-performance/run-pg-hotpath-diagnostic.py', 'tools/release-performance/test-pg-hotpath-diagnostic.py')
    return {'run_id': RUN_ID, 'schema_version': 1, 'diagnostic_only': True, 'variants': VARIANTS,
            'profile': 'POSTGRESQL', 'binary': {'server_sha256': binary,
                      'version': criteria['profiles']['POSTGRESQL']['server_version']},
            'driver_version': criteria['profiles']['POSTGRESQL']['driver_version'],
            'limits': criteria['limits'], 'host_stability': guard.STABILITY,
            'workload': {'connections': 1, 'jvms': 1, 'starts': 160, 'blocks': 4,
                         'warmup_groups_per_block': 2, 'measured_groups_per_block': 8, 'arms': ARMS,
                         'orders': ORDERS, 'metrics': METRICS},
            'input_sha512': h.hashes(paths)}


def approval_for(plan):
    return {'run_id': RUN_ID, 'status': 'APPROVED', 'authorized_runs': 1, 'schema_version': 1,
            'approval_basis': 'EXPLICIT_USER_CONFIRMATION', 'proposal_sha512': guard.digest(plan)}


def approval_sha(plan):
    require((ROOT / APPROVAL).is_file(), 'SEPARATE_APPROVAL_REQUIRED')
    require(guard.canonical(review.read(APPROVAL)) == guard.canonical(approval_for(plan)), 'APPROVAL_SCOPE_CHANGED')
    return h.hashes((APPROVAL,))[APPROVAL]


def schedule():
    for block in range(4):
        for slot in range(10):
            row = 1 + (slot + 2 * block) % 8
            for arm in ORDERS[(row - 1 + block) % 4]:
                yield 4 * row + arm


def paired_summary(samples):
    comparisons = {}
    slowest = sorted(range(32), key=lambda index: (-samples['AFTER']['TOTAL'][index], index))[:2]
    for metric in (*METRICS, 'OTHER'):
        a, b, before, after = (samples[arm][metric] for arm in ARMS)
        aa = [y - x for x, y in zip(a, b, strict=True)]
        change = [y - x for x, y in zip(before, after, strict=True)]
        candidate = [z - (x + y) / 2 for x, y, z in zip(a, b, after, strict=True)]
        comparisons[metric] = {
            'baseline_abs_delta_median_ns': statistics.median(abs(x) for x in aa),
            'baseline_abs_delta_p95_ns': sorted(abs(x) for x in aa)[30],
            'candidate_minus_previous_median_ns': statistics.median(change),
            'candidate_minus_previous_block_medians_ns': [statistics.median(change[i:i + 8]) for i in range(0, 32, 8)],
            'candidate_minus_baselines_median_ns': statistics.median(candidate),
            'slowest_candidate_two_minus_baselines_mean_ns': statistics.mean(candidate[i] for i in slowest),
        }
    return comparisons


def decode(protocol, plan):
    lines = protocol.splitlines()
    require(len(lines) == 4 + len(ARMS) * len(METRICS), 'PROTOCOL_LENGTH')
    require(lines[0] == 'PG_HOTPATH starts=160 rows=160 events=80 groups=32', 'FIXTURE_COUNTS')
    event = re.fullmatch(r'EVENT_KEY ([a-f0-9]{64}) ([a-f0-9]{64})', lines[1])
    require(event is not None and guard.numbers(lines[2], 'SCHEDULE', 160) == list(schedule()), 'PAIR_SCHEDULE')
    gaps = guard.numbers(lines[3], 'GAPS_NS', 159)
    pacing = guard.pacing(gaps, plan['limits'])
    samples = {}
    lines = iter(lines[4:])
    for arm in ARMS:
        row = samples[arm] = {metric: guard.numbers(next(lines), f'SAMPLE {arm} {metric}', 32) for metric in METRICS}
        row['OTHER'] = []
        for total, *segments in zip(*(row[key] for key in METRICS), strict=True):
            require(total > 0 and sum(segments) <= total, 'TIMING_ACCOUNTING')
            row['OTHER'].append(total - sum(segments))
        if arm.startswith('PLAIN'):
            require(not any(value for metric in OBSERVE_METRICS for value in row[metric]), 'BASELINE_OBSERVATION')
    return {'starts': 160, 'events': 80, 'groups': 32, 'min_spacing_ns': min(gaps),
            'max_rolling_second': pacing, 'paired': paired_summary(samples)}


def build(work, plan, result):
    result['native_binary'] = native._fingerprint(native.PG / 'postgres', 'postgresql', work)
    require(result['native_binary'] == plan['binary'], 'DB_BINARY')
    jdbc, result['jdbc_dependencies'] = schema.pinned_drivers(work)
    spring, result['spring_dependencies'] = schema.g2.phase2.dependencies(work, review.read(performance.SPRING))
    pins, _ = pinned_inputs()
    inputs, result['generated_sha512'] = sources.materialize(
        ROOT, work, plan['variants'], pins, performance.sources(), plan['input_sha512'][sources.TRIAL])
    classes = work / 'classes'
    classes.mkdir()
    deps = ':'.join(str(jar) for jar in (*jdbc, *spring))
    command = [*schema.base.JAVAC, '-cp', deps, '-d', str(classes), *map(str, inputs)]
    result['compile'], _ = native.run_private('pg-hotpath-compile', performance.limited(command, plan), work, 30)
    cp = f'{classes}:{deps}'
    result['contract'], output = native.run_private('pg-hotpath-contract',
        performance.limited([*schema.base.JAVA, '-cp', cp, TRIAL], plan), work, 15)
    expect = b'PG_HOTPATH_CONTRACT PASS\n'
    require(guard.reaped(result['compile']) and guard.reaped(result['contract'])
            and output.stat().st_size == len(expect) and output.read_bytes() == expect, 'OFFLINE_CONTRACT')
    return cp


def get_preparation(plan):
    row = review.read(PREPARATION)
    require(row['status'] == 'PASS' and row['run_id'] == RUN_ID and row['proposal_sha512'] == guard.digest(plan)
            and row['workload_run_claimed'] is False and row['postgresql_ready'] is False
            and guard.reaped(row['compile']) and guard.reaped(row['contract']) and guard.clean(row['cleanup']),
            'PREPARATION_UNVERIFIED')
    return row


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


def measure(work, cp, plan, result):
    result['postgresql_initialization_attempted'] = True
    with native.instance('postgresql', work) as (port, private, runtime):
        result['runtime'] = runtime
        result['postgresql_ready'] = True
        require(runtime['loopback_listener_owned'] is True
                and all(runtime[key] == value for key, value in plan['binary'].items()), 'DB_LISTENER_IDENTITY')
        command = [*schema.base.JAVA, '-cp', cp, FIXTURE, 'POSTGRESQL', str(port)]
        result['client'], output = native.run_private('pg-hotpath-measure',
            performance.limited(command, plan), work, performance.CLIENT_SECONDS, (private + '\n').encode('ascii'))
        require(guard.reaped(result['client']) and 0 < output.stat().st_size <= guard.PROTOCOL_BYTES, 'CLIENT_RECEIPT')
        protocol = output.read_text(encoding='ascii')
        result['summary'] = decode(protocol, plan)
        result['protocol'] = protocol
    require(runtime['server_stopped'] is True and runtime['process_groups_quiesced'] is True, 'DB_CLEANUP')


def run(plan, result):
    digest = approval_sha(plan)
    prep = get_preparation(plan)
    marker = ROOT / '.git/udak-product-g5' / (RUN_ID + '.claimed')
    try:
        with guard.protected_workspace() as (work, cleanup):
            require(not marker.exists() and not (ROOT / RESULT).exists(), 'APPROVAL_ALREADY_USED')
            result['cleanup'] = cleanup
            guard.check_host(work)
            with guard.watch_host(work):
                cp = build(work, plan, result)
                require(all(result[key] == prep[key] for key in BUILD_KEYS), 'PREPARED_INPUTS_CHANGED')
                readings = result['host_pressure_readings'] = []
                guard.stable_host(work, plan['host_stability'], readings)
                require(proposal() == plan and approval_sha(plan) == digest, 'INPUTS_CHANGED')
                guard.check_host(work)
                guard.claim(marker, digest)
                result.update(status='INCONCLUSIVE', approval_sha512=digest, workload_run_claimed=True)
                measure(work, cp, plan, result)
        require(guard.clean(cleanup), 'WORKSPACE_CLEANUP')
        result['status'] = 'PASS'
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        if result['workload_run_claimed']:
            result['stop_reason'] = guard.failure_code(error)
        raise
    finally:
        if result['workload_run_claimed']:
            guard.save_once(ROOT / RESULT, result)


def verify(plan):
    result = review.read(RESULT)
    prep = get_preparation(plan)
    runtime = result['runtime']
    require(result['status'] == 'PASS' and result['run_id'] == RUN_ID and result['diagnostic_only'] is True
            and result['proposal_sha512'] == guard.digest(plan) and result['approval_sha512'] == approval_sha(plan)
            and result['workload_run_claimed'] is True and result['postgresql_ready'] is True
            and all(result[key] == prep[key] for key in BUILD_KEYS) and guard.clean(result['cleanup'])
            and all(guard.reaped(result[key]) for key in ('compile', 'contract', 'client'))
            and runtime['server_stopped'] is True and runtime['process_groups_quiesced'] is True
            and runtime['loopback_listener_owned'] is True and all(runtime[k] == v for k, v in plan['binary'].items())
            and 0 < runtime['peak_rss_bytes'] <= plan['limits']['db_rss_bytes']
            and 0 < runtime['peak_data_bytes'] <= plan['limits']['db_scratch_bytes']
            and guard.canonical(result['host_pressure_readings']) ==
                guard.canonical([1] * plan['host_stability']['samples'])
            and 0 < len(result['protocol']) <= guard.PROTOCOL_BYTES, 'RESULT_UNVERIFIED')
    checked = decode(result['protocol'], plan)
    require(checked == result['summary'], 'STORED_SUMMARY_CHANGED')
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('proposal', 'prepare', 'run', 'verify'))
    args = parser.parse_args()
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, schema.interrupted)
    result = {'status': 'NOT RUN', 'run_id': RUN_ID, 'diagnostic_only': True,
              'workload_run_claimed': False, 'postgresql_ready': False}
    signal.alarm(300)
    try:
        plan = proposal()
        result['proposal_sha512'] = guard.digest(plan)
        if args.mode == 'proposal':
            answer = {k: v for k, v in plan.items() if k != 'input_sha512'}
            answer['proposal_sha512'] = result['proposal_sha512']
        elif args.mode == 'prepare':
            prepare(plan, result)
            answer = {k: result[k] for k in ('status', 'proposal_sha512', 'postgresql_ready', 'cleanup')}
        elif args.mode == 'run':
            run(plan, result)
            answer = result['summary']
        else:
            answer = verify(plan)
        print(json.dumps(answer, sort_keys=True))
        return 0
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'INCONCLUSIVE' if result['workload_run_claimed'] else 'NOT RUN',
                          'reason': guard.failure_code(error), 'workload_run_claimed': result['workload_run_claimed'],
                          'postgresql_ready': result['postgresql_ready'], 'cleanup': result.get('cleanup')}, sort_keys=True))
        return 1
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    sys.exit(main())
