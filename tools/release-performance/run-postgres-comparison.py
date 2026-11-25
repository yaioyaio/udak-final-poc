#!/usr/bin/env python3
"""Prepare, run once, and verify the bounded PostgreSQL Observe diagnostic."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import statistics
import subprocess
import sys
import tempfile
import time

import comparison_sources as sources

ROOT = Path(__file__).resolve().parents[2]
SELF = 'tools/release-performance/run-postgres-comparison.py'
ARCHIVED_ID = 'POSTGRES-OBSERVE-ABBA-01'
RUN_ID = 'POSTGRES-OBSERVE-ABBA-02'
RUN_IDS = (ARCHIVED_ID, RUN_ID)
AUDIT = ROOT / '.git/udak-product-g5'
PROFILE = 'POSTGRESQL'
ARMS = ('PLAIN', 'OBSERVE')
METRICS = ('TOTAL', 'JDBC_PREPARE', 'JDBC_EXECUTE', 'JDBC_OTHER', 'SHAPE', 'FINGERPRINT_AND_ID',
           'EVENT_CREATE', 'EVENT_SINK', 'OBSERVE_PROXY', 'OTHER')
OBSERVE_ONLY = ('SHAPE', 'FINGERPRINT_AND_ID', 'EVENT_CREATE', 'EVENT_SINK', 'OBSERVE_PROXY')
LOCAL_PLAN = 'tools/release-performance/assess-local-observe.py'
HOST_PROBE = 'tools/release-performance/jmh-process-guard.py'
TEST = 'tools/release-performance/test-postgres-comparison.py'
# Preserve ABBA-01's proposal across changes to these two harness files.
ARCHIVED_HARNESS_PINS = {
    SELF: '826c4f24f56571887dbd478b6844eada9f2289c73c64da8dfdb1439659ff0553285d9235afb82a7a0ad8811457e5c7a0ad037bc03739e7bc876665ca7de1d8f5',
    TEST: '725a31618d9ae29e7fa915e5334c61f1b10a5a2ac559f2a44b190691c28bd2dbde54fe0cd43d46aa1397925789c78cd21edca25d40c8ed92a2fa0c8208eb24c2',
}
STABILITY = {'samples': 7, 'interval_seconds': 5}
PROTOCOL_BYTES = 16 * 1024
BUILD_PINS = ('database_binary', 'jdbc_dependencies', 'spring_dependencies', 'instrumented_source_sha512')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


performance = load('comparison_performance', 'tools/run-g5-performance.py')
review, schema, native, h = performance.review, performance.schema, performance.native, performance.h
local_plan = load('comparison_plan', LOCAL_PLAN)
host = load('comparison_host', HOST_PROBE)


def require(condition, code):
    if not condition:
        raise ValueError(code)


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def digest(data):
    return hashlib.sha512(canonical(data)).hexdigest()


def run_paths(run_id):
    require(run_id in RUN_IDS, 'INVALID_RUN_ID')
    stem = 'evidence/PRODUCT-G5-' + run_id
    return stem + '-APPROVAL.json', stem + '-RESULT.json', AUDIT / (run_id + '.claimed')


def proposal(run_id=ARCHIVED_ID):
    run_paths(run_id)
    comparison = local_plan.postgres_comparison_plan()
    variants = {key: {field: value[field] for field in ('run_id', 'revision')}
                for key, value in comparison['variants'].items()}
    evidence = [path for variant in variants.values() for path in performance.run_paths(variant['run_id'])]
    h2_license = review.read(performance.SPRING)['h2_license_file']
    pinned = h.hashes((*performance.performance_inputs(), *evidence, SELF, sources.PROBE, TEST, HOST_PROBE, LOCAL_PLAN,
                       h2_license, 'tools/run-phase1.py', 'tools/run-phase4.py', 'tools/run-phase5.py',
                       'tools/release-performance/comparison_sources.py',
                       'tools/release-performance/attribution_sources.py',
                       'tools/release-performance/run-postgres-attribution.py',
                       'evidence/PRODUCT-G5-POSTGRESQL-ATTRIBUTION.json',
                       'evidence/PRODUCT-G5-POSTGRESQL-ATTRIBUTION-APPROVAL.json'))
    scope = comparison['plan']
    scope['block_order'] = list(scope['block_order'])
    binary = review.read(review.PILOT)['profiles'][PROFILE]['native_runtime']['server_sha256']
    plan = {'schema_version': 1, 'run_id': run_id, 'profile': PROFILE, 'diagnostic_only': True,
            'variants': variants, 'scope': scope, 'server_sha256': binary, 'input_sha512': pinned,
            'host_pressure_required': 1}
    if run_id == ARCHIVED_ID:
        pinned.update(ARCHIVED_HARNESS_PINS)
    else:
        plan['host_stability'] = dict(STABILITY)
    return plan


def authorization(plan):
    return {'schema_version': 1, 'status': 'APPROVED', 'run_id': plan['run_id'], 'authorized_runs': 1,
            'approval_basis': 'EXPLICIT_USER_CONFIRMATION', 'proposal_sha512': digest(plan)}


def require_approval(plan):
    approval, _, _ = run_paths(plan['run_id'])
    require((ROOT / approval).is_file(), 'SEPARATE_APPROVAL_REQUIRED')
    approved = review.read(approval)
    require(canonical(approved) == canonical(authorization(plan)), 'APPROVAL_SCOPE_MISMATCH')
    return h.hashes((approval,))[approval]


def numbers(line, prefix, count):
    match = re.fullmatch(re.escape(prefix) + r' ([0-9]{1,11}(?:,[0-9]{1,11})*)', line)
    require(match is not None, 'PROTOCOL_FIELD')
    values = [int(value) for value in match[1].split(',')]
    require(len(values) == count, 'PROTOCOL_SAMPLE_COUNT')
    return values


def pacing(gaps, limits):
    require(bool(gaps) and all(type(gap) is int for gap in gaps), 'INVALID_START_GAPS')
    require(min(gaps) >= limits['min_start_spacing_ns'], 'MIN_START_SPACING')
    maximum = 1
    window = [0]
    stamp = 0
    for gap in gaps:
        stamp += gap
        window = [previous for previous in window if stamp - previous < 1_000_000_000]
        window.append(stamp)
        maximum = max(maximum, len(window))
    require(maximum <= limits['max_starts_per_second'], 'MAX_START_RATE')
    return maximum


def expected_schedule(block):
    schedule = []
    for pair in range(20):
        row = 1 + (pair + (4 if block >= 2 else 0)) % 8
        first = (pair ^ (pair >> 3) ^ block) & 1
        schedule.extend((2 * row + first, 2 * row + 1 - first))
    return schedule


def decode_block(protocol, block, limits):
    lines = protocol.splitlines()
    require(len(lines) == 6 + len(ARMS) * len(METRICS), 'PROTOCOL_LENGTH')
    header = re.fullmatch(
        r'PRODUCT_PERF profile=POSTGRESQL starts=40 completed=40 warmup_per_arm=4 measured_per_arm=16'
        r' verified_rows=40 events=20 errors=0 max_in_flight=1 max_rolling_second=([1-8])'
        r' min_spacing_ns=([0-9]{1,11})', lines[0])
    require(header is not None, 'WORKLOAD_INVARIANT')
    event = re.fullmatch(r'EVENT_KEY ([0-9a-f]{64}) ([0-9a-f]{64})', lines[-3])
    require(event is not None, 'EVENT_KEY')
    gaps = numbers(lines[-1], 'GAPS_NS', 39)
    require((pacing(gaps, limits), min(gaps)) == (int(header[1]), int(header[2])), 'PACING_RECEIPT')
    schedule = numbers(lines[-2], 'SCHEDULE', 40)
    require(schedule == expected_schedule(block)
            and sorted(schedule[8::2]) == list(range(2, 18)), 'ROW_ORDER_INVARIANT')
    samples = {arm: {} for arm in ARMS}
    index = 3
    for arm in ARMS:
        for metric in METRICS:
            samples[arm][metric] = numbers(lines[index], f'ATTRIBUTION {arm} {metric}', 16)
            index += 1
        require(samples[arm]['TOTAL'] == numbers(lines[1 + ARMS.index(arm)], arm + '_NS', 16), 'TOTAL_RECEIPT')
        for total, *segments in zip(*(samples[arm][key] for key in METRICS), strict=True):
            require(total > 0 and total == sum(segments), 'EXCLUSIVE_ACCOUNTING')
        if arm == 'PLAIN':
            require(not any(value for metric in OBSERVE_ONLY for value in samples[arm][metric]), 'PLAIN_HAS_EVENTS')
    return {'starts': 40, 'verified_rows': 40, 'events': 20, 'event_key': list(event.groups()), 'schedule': schedule,
            'gaps_ns': gaps, 'samples_ns': samples}


def summarize(blocks, boundaries, plan):
    scope = plan['scope']
    require(len(blocks) == 4 and len(boundaries) == 3, 'BLOCK_COUNT')
    require(all(block['event_key'] == blocks[0]['event_key'] for block in blocks), 'EVENT_METADATA_CHANGED')
    combined_gaps = list(blocks[0]['gaps_ns'])
    for gap, block in zip(boundaries, blocks[1:], strict=True):
        combined_gaps.extend((gap, *block['gaps_ns']))
    require(len(combined_gaps) == scope['query_starts'] - 1, 'TOTAL_STARTS')
    rates = pacing(combined_gaps, scope['limits'])
    order = scope['block_order']
    per_block = []
    for block, variant in zip(blocks, order, strict=True):
        plain, observe = (block['samples_ns'][arm] for arm in ARMS)
        deltas = {key: [b - a for a, b in zip(plain[key], observe[key], strict=True)] for key in METRICS}
        first = block['schedule'][8::2]
        by_order = {arm: [i for i, code in enumerate(first) if (code % 2 != 0) == (arm == 'OBSERVE')]
                    for arm in ARMS}
        tail = sorted(range(len(first)), key=lambda i: (-observe['TOTAL'][i], i))[:2]
        per_block.append({'variant': variant,
                          'median_paired_delta_ns': {key: statistics.median(values) for key, values in deltas.items()},
                          'p95_total_paired_delta_ns': max(deltas['TOTAL']),
                          'median_paired_delta_ns_by_first_arm': {
                              arm: {key: statistics.median(values[i] for i in cohort) for key, values in deltas.items()}
                              for arm, cohort in by_order.items()},
                          'slowest_observe_pairs': {'count': len(tail), 'mean_paired_delta_ns': {
                              key: statistics.mean(values[i] for i in tail) for key, values in deltas.items()}}})
    return {'starts': 160, 'verified_rows': 160, 'events': 80, 'measured_pairs': 64,
            'max_rolling_second_conservative': rates, 'min_start_spacing_ns_lower_bound': min(combined_gaps),
            'blocks': per_block}


def save_once(path, data):
    """Atomically publish a completed receipt without replacing existing evidence."""
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.postgres-comparison-', delete=False) as temporary:
        staging = Path(temporary.name)
        try:
            temporary.write(canonical(data) + b'\n')
            temporary.flush()
            os.fsync(temporary.fileno())
            os.link(staging, path)
        finally:
            staging.unlink()


@contextmanager
def protected_workspace():
    require((ROOT / '.git').is_dir(), 'PRIMARY_CHECKOUT_REQUIRED')
    lock_dir = ROOT / '.git/udak-g2-managed'
    lock_dir.mkdir(exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(lock_dir / 'RUN.lock', flags, 0o600), 'w') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with schema.workspace() as (work, cleanup):
            yield work, cleanup


def check_host(work):
    require(host.memory_pressure(work) == 1, 'HOST_MEMORY_PRESSURE')


def stable_host(work, policy, readings):
    for index in range(policy['samples']):
        if index:
            time.sleep(policy['interval_seconds'])
        level = host.memory_pressure(work)
        readings.append(level)
        require(level == 1, 'HOST_MEMORY_PRESSURE')


@contextmanager
def watch_host(work):
    base = native._Child

    class PressureCheckedChild(base):
        def _sample(self):
            check_host(work)
            super()._sample()

    native._Child = PressureCheckedChild
    try:
        yield
    finally:
        native._Child = base


def build(work, plan, result):
    scope = plan['scope']
    driver_manifest = review.read(schema.DRIVERS)
    needed = {item for item in schema.NATIVE_COORDS if item.startswith(('org.postgresql:', 'org.checkerframework:'))}
    subset = {key: [item for item in driver_manifest[key] if item['coordinate'] in needed]
              for key in ('artifacts', 'upstream_license_checks')}
    require({item['coordinate'] for item in subset['artifacts']} == needed, 'DRIVER_PINS')
    jdbc, result['jdbc_dependencies'] = schema.g2.dependencies(work, subset)
    spring, result['spring_dependencies'] = schema.g2.phase2.dependencies(work, review.read(performance.SPRING))
    deps = os.pathsep.join(map(str, (*jdbc, *spring)))
    classpaths = {}
    probe = (ROOT / sources.PROBE).read_bytes()
    result['compile'], result['instrumented_source_sha512'] = {}, {}
    for key, variant in plan['variants'].items():
        approval, _ = performance.run_paths(variant['run_id'])
        signed = review.read(approval)['candidate_sha512']
        inputs, generated = sources.materialize(ROOT, work / key, variant['revision'],
            {**signed, sources.PROBE: plan['input_sha512'][sources.PROBE]}, performance.sources(), probe)
        result['instrumented_source_sha512'][key] = generated
        classes = work / (key + '-classes')
        classes.mkdir()
        javac = [*schema.base.JAVAC, '-cp', deps, '-d', str(classes), *map(str, inputs)]
        result['compile'][key], _ = native.run_private('compile-' + key, performance.limited(javac, scope), work, 30)
        classpaths[key] = os.pathsep.join((str(classes), deps))
    return classpaths


def binary_check(work, plan):
    expected = {'version': plan['scope']['profile_versions']['server_version'], 'server_sha256': plan['server_sha256']}
    require(native._fingerprint(native.PG / 'postgres', 'postgresql', work) == expected, 'DB_BINARY')
    return expected


def clean(receipt):
    return receipt.get('status') == 'PASS' and receipt.get('remaining') is False


def receipt_path(plan):
    return AUDIT / ('comparison-prepared-' + digest(plan) + '.json')


def prepared(plan):
    name = receipt_path(plan).relative_to(ROOT)
    if not (ROOT / name).is_file():
        raise ValueError('PREPARATION_REQUIRED')
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(ROOT / name, flags), 'rb') as stream:
        data = stream.read(128 * 1024 + 1)
    require(len(data) <= 128 * 1024, 'PREPARATION_BACKUP_BOUND')
    saved = json.loads(data)
    require(saved['status'] == 'PASS' and saved['proposal_sha512'] == digest(plan) and clean(saved['cleanup'])
            and saved['database_started'] is False and saved['timing_started'] is False
            and set(saved['compile']) == set(plan['variants'])
            and all(reaped(step) for step in saved['compile'].values()), 'PREPARATION_INCOMPLETE')
    return saved


def reaped(step):
    return (step['status'] == 'PASS' and step['child_reaped'] is True and step['process_group_quiesced'] is True)


def prepare(plan, result):
    require(plan['run_id'] == RUN_ID, 'ARCHIVED_RUN')
    with protected_workspace() as (work, cleanup):
        check_host(work)
        result['cleanup'] = cleanup
        result['database_binary'] = binary_check(work, plan)
        build(work, plan, result)
        check_host(work)
        require(proposal(plan['run_id']) == plan, 'INPUTS_CHANGED')
    require(clean(cleanup), 'WORKSPACE_CLEANUP')
    result['status'] = 'PASS'
    AUDIT.mkdir(exist_ok=True)
    path = receipt_path(plan)
    if not path.exists():
        save_once(path, result)
    prepared(plan)


def claim(path, approval_sha):
    with path.open('x') as marker:
        marker.write(approval_sha + '\n')
        marker.flush()
        os.fsync(marker.fileno())


def failure_code(error):
    if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]+', str(error)):
        return str(error)
    return type(error).__name__


def measurement(work, plan, classpaths, result):
    scope = plan['scope']
    result['blocks'], result['between_blocks_min_ns'] = [], []
    result['database_initialization_attempted'] = True
    with native.instance('postgresql', work) as (port, private, runtime):
        result['native_runtime'] = runtime
        require(runtime['loopback_listener_owned'] is True and
                all(runtime[key] == value for key, value in result['database_binary'].items()), 'DB_LISTENER_IDENTITY')
        result['database_started'] = True
        previous_end = None
        for index, key in enumerate(scope['block_order']):
            if previous_end is not None:
                gap = scope['limits']['min_start_spacing_ns']
                while (remaining := gap - (time.monotonic_ns() - previous_end)) > 0:
                    time.sleep(remaining / 1_000_000_000)
                result['between_blocks_min_ns'].append(time.monotonic_ns() - previous_end)
            check_host(work)
            result['timing_started'] = True
            command = [*schema.base.JAVA, '-cp', classpaths[key], 'ProductG5PerformanceMain', PROFILE, str(port), str(index)]
            step, output = native.run_private('measure-' + str(index), performance.limited(command, scope),
                work, performance.CLIENT_SECONDS, (private + '\n').encode('ascii'))
            previous_end = time.monotonic_ns()
            require(reaped(step) and output.stat().st_size <= PROTOCOL_BYTES, 'CLIENT_RECEIPT')
            protocol = output.read_text(encoding='ascii')
            decode_block(protocol, index, scope['limits'])
            check_host(work)
            result['blocks'].append({'client': step, 'protocol': protocol, 'variant': key})
    require(runtime['server_stopped'] is True and runtime['process_groups_quiesced'] is True, 'DB_CLEANUP')
    result['summary'] = measurement_summary(result, plan)


def measurement_summary(result, plan):
    blocks = result['blocks']
    require([block['variant'] for block in blocks] == plan['scope']['block_order'], 'BLOCK_ORDER')
    parsed = []
    for index, block in enumerate(blocks):
        require(reaped(block['client']) and 0 < len(block['protocol']) <= PROTOCOL_BYTES, 'CLIENT_RECEIPT')
        parsed.append(decode_block(block['protocol'], index, plan['scope']['limits']))
    return summarize(parsed, result['between_blocks_min_ns'], plan)


def run(plan, result):
    run_id = plan['run_id']
    require(run_id == RUN_ID, 'ARCHIVED_RUN')
    _, report, marker = run_paths(run_id)
    approval_sha = require_approval(plan)
    preparation = prepared(plan)
    try:
        with protected_workspace() as (work, cleanup):
            result['cleanup'] = cleanup
            require(not marker.exists() and not (ROOT / report).exists(), 'APPROVAL_ALREADY_USED')
            check_host(work)
            result['database_binary'] = binary_check(work, plan)
            classpaths = build(work, plan, result)
            require(all(result[field] == preparation[field] for field in BUILD_PINS),
                    'PREPARED_INPUTS_CHANGED')
            result['host_pressure_readings'] = []
            stable_host(work, plan['host_stability'], result['host_pressure_readings'])
            require(proposal(run_id) == plan and require_approval(plan) == approval_sha, 'INPUTS_CHANGED')
            check_host(work)
            claim(marker, approval_sha)
            result.update(status='INCONCLUSIVE', approval_sha512=approval_sha, workload_run_claimed=True)
            with watch_host(work):
                measurement(work, plan, classpaths, result)
        require(clean(cleanup), 'WORKSPACE_CLEANUP')
        result['status'] = 'PASS'
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        if result.get('workload_run_claimed'):
            result['stop_reason'] = failure_code(error)
        raise
    finally:
        if result.get('workload_run_claimed'):
            save_once(ROOT / report, result)


def verify(plan):
    run_id = plan['run_id']
    _, report, _ = run_paths(run_id)
    result = review.read(report)
    runtime = result['native_runtime']
    require(result['run_id'] == run_id and result['status'] == 'PASS' and result['diagnostic_only'] is True
            and result['proposal_sha512'] == digest(plan) and result['approval_sha512'] == require_approval(plan)
            and result['workload_run_claimed'] is True and result['database_started'] is True
            and result['timing_started'] is True and clean(result['cleanup'])
            and runtime['server_stopped'] is True and runtime['process_groups_quiesced'] is True
            and runtime['loopback_listener_owned'] is True and runtime['version'] == plan['scope']['profile_versions']['server_version']
            and runtime['server_sha256'] == plan['server_sha256']
            and all(reaped(step) for step in result['compile'].values())
            and ('host_stability' not in plan
                 or canonical(result['host_pressure_readings']) == canonical([1] * plan['host_stability']['samples']))
            and result['summary'] == measurement_summary(result, plan), 'DIAGNOSTIC_RESULT_UNVERIFIED')
    return result['summary']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('proposal', 'prepare', 'run', 'verify'))
    parser.add_argument('--run-id', choices=RUN_IDS, default=ARCHIVED_ID)
    args = parser.parse_args()
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, schema.interrupted)
    result = {'status': 'NOT RUN', 'run_id': args.run_id, 'diagnostic_only': True,
              'workload_run_claimed': False, 'database_started': False, 'timing_started': False}
    signal.alarm(300)
    try:
        plan = proposal(args.run_id)
        result['proposal_sha512'] = digest(plan)
        if args.mode == 'prepare':
            prepare(plan, result)
            print(json.dumps({key: result[key] for key in ('status', 'proposal_sha512', 'database_started',
                             'timing_started', 'compile', 'cleanup')}, sort_keys=True))
        elif args.mode == 'run':
            run(plan, result)
            print(json.dumps(result['summary'], sort_keys=True))
        elif args.mode == 'verify':
            print(json.dumps(verify(plan), sort_keys=True))
        else:
            print(json.dumps({'status': 'PENDING', 'scope': plan['scope'], 'variants': plan['variants'],
                              'host_stability': plan.get('host_stability'),
                              'proposal_sha512': result['proposal_sha512']}, sort_keys=True))
        return 0
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'INCONCLUSIVE' if result['workload_run_claimed'] else
                          ('NOT RUN' if args.mode == 'run' else 'FAIL'),
                          'reason': failure_code(error), 'run_id': args.run_id,
                          'workload_run_claimed': result['workload_run_claimed'],
                          'host_pressure_readings': result.get('host_pressure_readings'),
                          'database_started': result['database_started'], 'timing_started': result['timing_started'],
                          'cleanup': result.get('cleanup')}))
        return 1
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    sys.exit(main())
