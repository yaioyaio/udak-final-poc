#!/usr/bin/env python3
"""Run or verify the separately approved, instrumented PostgreSQL Observe diagnostic."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import statistics
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
SELF = 'tools/release-performance/run-postgres-attribution.py'
GENERATE = 'tools/release-performance/attribution_sources.py'
PROBE = 'tools/release-performance/AttributionProbe.java'
APPROVAL = 'evidence/PRODUCT-G5-POSTGRESQL-ATTRIBUTION-APPROVAL.json'
REPORT = 'evidence/PRODUCT-G5-POSTGRESQL-ATTRIBUTION.json'
RUN_ID = 'POSTGRESQL-ATTRIBUTION'
REFERENCE = 'OBSERVE-V2'
PROFILE = 'POSTGRESQL'
ARMS = ('PLAIN', 'OBSERVE')
METRICS = ('TOTAL', 'JDBC_PREPARE', 'JDBC_EXECUTE', 'JDBC_OTHER', 'FINGERPRINT', 'EVENT_CREATE',
           'EVENT_SINK', 'OBSERVE_PROXY', 'OTHER')
JDBC = ('JDBC_PREPARE', 'JDBC_EXECUTE', 'JDBC_OTHER')
OBSERVATION = ('FINGERPRINT', 'EVENT_CREATE', 'EVENT_SINK')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


performance = load('attribution_performance', 'tools/run-g5-performance.py')
review, schema, h, native = performance.review, performance.schema, performance.h, performance.native


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def scope():
    previous = review.criteria()['performance']
    return {**previous, 'profiles': {PROFILE: previous['profiles'][PROFILE]}}


def inputs():
    return h.hashes((*performance.performance_inputs(), *performance.run_paths(REFERENCE), SELF, GENERATE, PROBE,
                     'tools/run-sql-inventory.py', 'tools/run-phase4.py', 'tools/run-phase1.py'))


def approval():
    return {'schema_version': 1, 'status': 'APPROVED', 'approval_basis': 'EXPLICIT_USER_CONFIRMATION',
            'run_id': RUN_ID, 'authorized_runs': 1, 'diagnostic_only': True, 'scope': scope(), 'input_sha512': inputs()}


def require_approval():
    signed = review.read(APPROVAL)
    require(signed == approval() and type(signed['authorized_runs']) is int, 'APPROVAL_MISMATCH')
    return signed


def rank95(samples):
    return sorted(samples)[(95 * len(samples) + 99) // 100 - 1]


def sum_at(samples, keys, index):
    return sum(samples[key][index] for key in keys)


def relative_ratio(observed, baseline):
    return round(100 * (observed - baseline) / baseline, 4)


def summarize(samples, plan):
    n = plan['measured_per_arm']
    measured = range(n)
    for arm in ARMS:
        row = samples[arm]
        require(row.keys() == set(METRICS), 'TIMING_COLUMNS')
        require(all(len(values) == n and all(type(x) is int and 0 <= x <= 10**10 for x in values)
                    for values in row.values()), 'TIMING_SAMPLES')
        require(all(row['TOTAL'][i] > 0 and row['TOTAL'][i] == sum_at(row, METRICS[1:], i)
                    for i in measured), 'TIMING_PARTITION')
    plain, observe = (samples[arm] for arm in ARMS)
    require(all(not any(plain[key]) for key in (*OBSERVATION, 'OBSERVE_PROXY')), 'PLAIN_OBSERVE_COMPONENTS')
    require(all(any(observe[key]) for key in (*OBSERVATION, 'OBSERVE_PROXY')), 'MISSING_OBSERVE_COMPONENTS')

    # The tail contains the five slowest Observe requests. All component deltas
    # for this group compare the same pairs, so the totals are additive.
    tail = sorted(measured, key=lambda i: (observe['TOTAL'][i], i))[-((n * 5 + 99) // 100):]
    differences = {key: [observe[key][i] - plain[key][i] for i in measured] for key in METRICS}
    tail_totals = {key: sum(deltas[i] for i in tail) for key, deltas in differences.items()}
    all_totals = {key: sum(deltas) for key, deltas in differences.items()}
    plain95 = rank95(plain['TOTAL'])
    minus_observer = [observe['TOTAL'][i] - sum_at(observe, OBSERVATION, i) for i in measured]
    minus_observer95 = rank95(minus_observer)
    return {'total_p95_ns': {arm: rank95(samples[arm]['TOTAL']) for arm in ARMS},
            'arm_statistics_ns': {arm: {key: {'p50': statistics.median(samples[arm][key]),
                                              'p95': rank95(samples[arm][key])} for key in METRICS} for arm in ARMS},
            'paired_median_delta_ns': {key: statistics.median(deltas) for key, deltas in differences.items()},
            'total_median_delta_by_start_order_ns': {'plain_first': statistics.median(differences['TOTAL'][::2]),
                                                    'observe_first': statistics.median(differences['TOTAL'][1::2])},
            'all_pairs': {'count': n, 'signed_delta_sums_ns': all_totals,
                          'jdbc_delta_sum_ns': sum(all_totals[key] for key in JDBC)},
            'observe_tail_pairs': {'count': len(tail), 'indices': tail, 'signed_delta_sums_ns': tail_totals,
                                   'jdbc_delta_sum_ns': sum(tail_totals[key] for key in JDBC)},
            'arithmetic_without_fingerprint_and_events': {'observe_p95_ns': minus_observer95,
                'relative_to_plain_p95_percent': relative_ratio(minus_observer95, plain95)}}


def decode(text, plan):
    lines = text.splitlines()
    require(len(lines) == 3 + len(ARMS) * len(METRICS), 'PROTOCOL_LENGTH')
    query = review.protocol('\n'.join(lines[:3]), PROFILE, plan)
    rows = {arm: {} for arm in ARMS}
    i = 3
    for arm in ARMS:
        for key in METRICS:
            pattern = rf'ATTRIBUTION {arm} {key} ([0-9]{{1,11}}(?:,[0-9]{{1,11}})*)'
            match = re.fullmatch(pattern, lines[i])
            require(match is not None, 'TIMING_PROTOCOL')
            rows[arm][key] = list(map(int, match[1].split(',')))
            i += 1
    require(rows['PLAIN']['TOTAL'] == query['plain_ns'] and rows['OBSERVE']['TOTAL'] == query['observe_ns'],
            'QUERY_TIMING_BOUNDS')
    return {'workload': query['workload'], 'samples_ns': rows, 'diagnosis': summarize(rows, plan)}


def render(work):
    module = load('attribution_sources', GENERATE)
    return module.build_sources(ROOT, work, (*performance.sources(), PROBE))


def compile_fixture(work, cp, result, plan):
    sources, result['instrumented_source_sha512'] = render(work)
    classes = work / 'classes'
    classes.mkdir()
    command = schema.base.JAVAC + ['-cp', cp, '-d', str(classes), *map(str, sources)]
    result['compile'], _ = native.run_private('compile-postgres-attribution', performance.limited(command, plan), work, 30)
    return os.pathsep.join((str(classes), cp))


def run(result):
    signed = require_approval()
    plan = signed['scope']
    measured = review.performance_result(review.criteria()['performance'], REFERENCE)
    require(measured[PROFILE]['status'] == 'FAIL', 'REFERENCE_EXPECTED_FAIL')
    result['input_sha512'] = signed['input_sha512']
    result['approval_sha512'] = h.hashes((APPROVAL,))[APPROVAL]
    audit = ROOT / '.git/udak-product-g5'
    audit.mkdir(parents=True, exist_ok=True)
    marker = audit / (RUN_ID + '.claimed')
    lock_dir = ROOT / '.git/udak-g2-managed'
    lock_dir.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(lock_dir / 'RUN.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(not marker.exists() and not (ROOT / REPORT).exists(), 'APPROVAL_ALREADY_USED')
        with schema.workspace() as (work, cleanup):
            result['cleanup'] = cleanup
            jdbc, result['jdbc_dependencies'] = schema.pinned_drivers(work)
            spring, result['spring_dependencies'] = schema.g2.phase2.dependencies(work, review.read(performance.SPRING))
            cp = compile_fixture(work, os.pathsep.join(map(str, (*jdbc, *spring))), result, plan)
            expected = review.read(review.PILOT)['profiles'][PROFILE]['native_runtime']['server_sha256']
            match = {'version': plan['profiles'][PROFILE]['server_version'], 'server_sha256': expected}
            require(native._fingerprint(native.PG / 'postgres', 'postgresql', work) == match, 'DB_BINARY')
            require(require_approval() == signed and h.hashes((APPROVAL,))[APPROVAL] == result['approval_sha512'],
                    'APPROVAL_CHANGED')
            with marker.open('x') as record:
                record.write(result['approval_sha512'] + '\n')
                record.flush()
                os.fsync(record.fileno())
            result['workload_run_claimed'] = True
            with native.instance('postgresql', work) as (port, private, runtime):
                result['native_runtime'] = runtime
                require(runtime['loopback_listener_owned'] and all(runtime[key] == value for key, value in match.items()),
                        'DB_LISTENER_IDENTITY')
                command = [*schema.base.JAVA, '-cp', cp, 'ProductG5PerformanceMain', PROFILE, str(port)]
                try:
                    result['client'], output = native.run_private('postgres-attribution', performance.limited(command, plan),
                        work, performance.CLIENT_SECONDS, (private + '\n').encode('ascii'))
                except RuntimeError:
                    output = work / 'postgres-attribution.output'
                    if output.is_file() and output.stat().st_size < 96:
                        failure = re.fullmatch(rb'PRODUCT_PERF_ERROR stage=([A-Z]{1,20})\n', output.read_bytes())
                        if failure:
                            result['fixture_stage'] = failure[1].decode('ascii')
                    raise
                require(output.stat().st_size <= 32 * 1024, 'OUTPUT_BOUND')
                result['measurement'] = decode(output.read_text(encoding='ascii'), plan)
            require(runtime['server_stopped'] and runtime['process_groups_quiesced'], 'DB_CLEANUP')
        require(cleanup['status'] == 'PASS' and cleanup['remaining'] is False, 'WORKSPACE_CLEANUP')
    result['status'] = 'PASS'


def verify():
    signed = require_approval()
    proof = review.read(REPORT)
    plan = signed['scope']
    require(proof['schema_version'] == 1 and proof['status'] == 'PASS' and proof['run_id'] == RUN_ID
            and proof['diagnostic_only'] is True
            and proof['workload_run_claimed'] is True and proof['docker_containers_started'] == 0
            and proof['profile'] == PROFILE and proof['input_sha512'] == signed['input_sha512']
            and proof['approval_sha512'] == h.hashes((APPROVAL,))[APPROVAL]
            and 0 < proof['wall_seconds'] <= plan['limits']['wall_seconds'], 'RUN_EVIDENCE')
    with schema.workspace() as (work, _):
        _, generated = render(work)
    require(generated == proof['instrumented_source_sha512'], 'INSTRUMENTED_SOURCE_HASHES')
    for key in ('compile', 'client'):
        job = proof[key]
        require(job['status'] == 'PASS' and job['child_reaped'] is True and job['process_group_quiesced'] is True,
                'CLIENT_LIFECYCLE')
    runtime = proof['native_runtime']
    require(proof['cleanup']['status'] == 'PASS' and proof['cleanup']['remaining'] is False
            and all(runtime[k] is True for k in ('loopback_listener_owned', 'server_stopped', 'process_groups_quiesced'))
            and runtime['version'] == plan['profiles'][PROFILE]['server_version']
            and runtime['server_sha256'] == review.read(review.PILOT)['profiles'][PROFILE]['native_runtime']['server_sha256']
            and 0 < runtime['peak_rss_bytes'] <= plan['limits']['db_rss_bytes']
            and 0 < runtime['peak_data_bytes'] <= plan['limits']['db_scratch_bytes'], 'DB_RESOURCE_OR_CLEANUP')
    result = proof['measurement']
    rows = result['samples_ns']
    encode = lambda samples: ','.join(map(str, samples))
    header = 'PRODUCT_PERF profile=POSTGRESQL' + ''.join(f' {k}={result["workload"][k]}' for k in review.EXPECTED_FIELDS)
    lines = [header, 'PLAIN_NS ' + encode(rows['PLAIN']['TOTAL']), 'OBSERVE_NS ' + encode(rows['OBSERVE']['TOTAL'])]
    lines.extend(f'ATTRIBUTION {arm} {key} ' + encode(rows[arm][key]) for arm in ARMS for key in METRICS)
    require(result == decode('\n'.join(lines), plan), 'TIMING_EVIDENCE')
    return result['diagnosis']


def main():
    args = sys.argv[1:]
    if args == ['--verify']:
        try:
            print(json.dumps({'status': 'PASS', 'diagnosis': verify()}))
            return 0
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(json.dumps({'status': 'FAIL', 'failure_type': type(error).__name__}))
            return 1
    if args != ['--run']:
        return 2
    result = {'schema_version': 1, 'status': 'FAIL', 'run_id': RUN_ID, 'profile': PROFILE, 'diagnostic_only': True,
              'workload_run_claimed': False, 'docker_containers_started': 0}
    for sig in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, schema.interrupted)
    start = time.monotonic()
    signal.alarm(scope()['limits']['wall_seconds'])
    try:
        run(result)
    except (OSError, ValueError, KeyError, RuntimeError, TypeError) as error:
        result['failure_type'] = type(error).__name__
    finally:
        signal.alarm(0)
        result['wall_seconds'] = round(time.monotonic() - start, 3)
        if result['workload_run_claimed']:
            h.save(REPORT, result)
    print(json.dumps({key: result[key] for key in ('status', 'workload_run_claimed', 'failure_type', 'fixture_stage')
                      if key in result}))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
