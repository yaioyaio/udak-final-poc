#!/usr/bin/env python3
"""Prepare, run once, or reconstruct the instrumented three-arm PostgreSQL crossover."""
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
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
DIR = 'tools/release-performance/'
SELF = DIR + 'run-postgres-crossover.py'
MYSQL = DIR + 'run-mysql-attribution.py'
spec = importlib.util.spec_from_file_location('crossover_guards', ROOT / MYSQL)
guards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guards)
pg, performance, review, schema, h, native = guards.pg, guards.performance, guards.review, guards.schema, guards.h, guards.native
require = pg.require
RUN_ID = 'POSTGRESQL-CROSSOVER'
APPROVAL = 'evidence/PRODUCT-G5-POSTGRESQL-CROSSOVER-APPROVAL.json'
REPORT = 'evidence/PRODUCT-G5-POSTGRESQL-CROSSOVER.json'
REFERENCE = 'OBSERVE-REUSE-V2'
GENERATE = DIR + 'crossover_sources.py'
JAVA_INPUTS = (DIR + 'CrossoverProbe.java', DIR + 'CrossoverTrial.java')
PRIOR = '21aeaf2b5e60637c6be3fb173923abfeb6b583f3'
CURRENT = '80090a180670f7d3b92022f885dfcdc74dcbc85d'
EVIDENCE_REVISION = 'e1af76ce9e77ed743aef0522c008084441c51dfa'
ARMS = ('PLAIN', 'PRIOR', 'CURRENT')
METRICS = ('TOTAL', *pg.JDBC, 'HMAC', 'FINGERPRINT', 'EVENT_CREATE', 'EVENT_SINK', 'OBSERVE_PROXY', 'OTHER')
STARTS = 204
MEASURED = 60
HEADER = dict(starts=STARTS, completed=STARTS, warmup_triplets=8, measured_triplets=MEASURED,
              verified_rows=STARTS, prior_events=68, current_events=68, errors=0, max_in_flight=1)
MAX_OUTPUT = 32 * 1024


def scope():
    official = review.criteria()['performance']
    return {'arms': list(ARMS), 'warmup_triplets': 8, 'measured_triplets': MEASURED, 'starts_per_database': STARTS,
            'prior_revision': PRIOR, 'current_revision': CURRENT, 'database_sessions': 1,
            'measured_order': 'all six permutations once per block of six triplets',
            'profiles': {'POSTGRESQL': official['profiles']['POSTGRESQL']}, 'limits': official['limits']}


def input_paths():
    return (SELF, MYSQL, guards.PREDECESSOR, pg.GENERATE, GENERATE, *JAVA_INPUTS, review.CRITERIA, review.PILOT, performance.SPRING, schema.DRIVERS,
            guards.SPRING_LICENSE, *performance.run_paths('OBSERVE-REUSE'), *performance.run_paths(REFERENCE), 'tools/run-g5-performance.py',
            'tools/verify-product-g5.py', 'tools/run-schema-regression.py', 'tools/schema-native.py',
            'tools/run-g2.py', 'tools/run-sql-inventory.py', *(f'tools/run-phase{i}.py' for i in range(1, 7)))


def proposal(plan, hashes, sources):
    return {'schema_version': 1, 'run_id': RUN_ID, 'authorized_runs': 1, 'diagnostic_only': True,
            'reference_run_id': REFERENCE, 'scope': plan, 'input_sha512': hashes, 'instrumented_source_sha512': sources}


def signed_approval(plan, hashes, sources):
    signed = review.read(APPROVAL)
    expected = {**proposal(plan, hashes, sources), 'status': 'APPROVED', 'approval_basis': 'EXPLICIT_USER_REQUEST'}
    require(json.dumps(signed, sort_keys=True) == json.dumps(expected, sort_keys=True), 'APPROVAL_MISMATCH')
    return signed


def series(values):
    return ','.join(map(str, values))


def summarize(rows):
    indices = list(range(MEASURED))
    tail = sorted(indices, key=lambda i: (rows['CURRENT']['TOTAL'][i], i))[-3:]
    comparisons = {}
    for arm, base in (('CURRENT', 'PRIOR'), ('CURRENT', 'PLAIN'), ('PRIOR', 'PLAIN')):
        groups = {}
        for label, positions in (('all_triplets', indices), ('current_tail_triplets', tail)):
            stats = {}
            for metric in METRICS:
                deltas = [rows[arm][metric][i] - rows[base][metric][i] for i in positions]
                stats[metric] = {'sum_ns': sum(deltas), 'mean_ns': round(statistics.mean(deltas), 3),
                                 'median_ns': statistics.median(deltas)}
            groups[label] = stats
        comparisons[arm + '_minus_' + base] = groups
    return {'component_p95_ns': {arm: {key: pg.rank95(values) for key, values in row.items()}
                                 for arm, row in rows.items()},
            'current_tail_indices': tail, 'paired_deltas': comparisons}


def encode(measurement):
    counts, orders, rows, cache = (measurement[k] for k in ('workload', 'orders', 'samples_ns', 'cache'))
    lines = ['POSTGRES_CROSSOVER' + ''.join(f' {k}={counts[k]}' for k in (*HEADER, 'max_rolling_second', 'min_spacing_ns')),
             'CROSSOVER_ORDERS ' + series(orders)]
    lines.extend(f'CROSSOVER {arm} {key} ' + series(rows[arm][key]) for arm in ARMS for key in METRICS)
    lines.extend(f'CROSSOVER_CACHE {arm} hits={cache[arm]["hits"]} misses={cache[arm]["misses"]}'
                 for arm in ARMS[1:])
    return '\n'.join(lines) + '\n'


def decode(output, plan):
    require(len(output) <= MAX_OUTPUT and output.isascii(), 'PROTOCOL_BOUND')
    lines = output.splitlines()
    require(len(lines) == 4 + len(ARMS) * len(METRICS), 'PROTOCOL_LENGTH')
    prefix = 'POSTGRES_CROSSOVER' + ''.join(f' {k}={v}' for k, v in HEADER.items())
    match = re.fullmatch(prefix + r' max_rolling_second=([1-8]) min_spacing_ns=([0-9]{1,12})', lines[0])
    require(match is not None and plan['limits']['min_start_spacing_ns'] <= int(match[2]) <= 10**9 * plan['limits']['wall_seconds'],
            'WORKLOAD_BOUNDS')
    counts = dict(HEADER, max_rolling_second=int(match[1]), min_spacing_ns=int(match[2]))
    match = re.fullmatch(r'CROSSOVER_ORDERS ([0-5](?:,[0-5]){59})', lines[1])
    require(match is not None, 'ORDER_PROTOCOL')
    orders = list(map(int, match[1].split(',')))
    require(all(set(orders[i:i + 6]) == set(range(6)) for i in range(0, MEASURED, 6)), 'BLOCK_BALANCE')
    rows = {}
    index = 2
    for arm in ARMS:
        row = rows[arm] = {}
        for metric in METRICS:
            match = re.fullmatch(rf'CROSSOVER {arm} {metric} ([0-9]{{1,11}}(?:,[0-9]{{1,11}}){{59}})', lines[index])
            require(match is not None, 'TIMING_PROTOCOL')
            row[metric] = list(map(int, match[1].split(',')))
            index += 1
        require(all(0 < row['TOTAL'][i] <= 10**10 and row['TOTAL'][i] == sum(row[k][i] for k in METRICS[1:])
                    for i in range(MEASURED)), 'TIMING_PARTITION')
        require(not any(row['FINGERPRINT']), 'MEASURED_FINGERPRINT_MISS')
        for key in ('HMAC', 'EVENT_CREATE', 'EVENT_SINK', 'OBSERVE_PROXY'):
            require((not any(row[key])) if arm == 'PLAIN' else any(row[key]), 'OBSERVE_COMPONENTS')
    cache = {}
    for arm in ARMS[1:]:
        require(lines[index] == f'CROSSOVER_CACHE {arm} hits=67 misses=1', 'CACHE_PROTOCOL')
        cache[arm] = {'hits': 67, 'misses': 1}
        index += 1
    result = {'workload': counts, 'orders': orders, 'samples_ns': rows, 'cache': cache, 'diagnosis': summarize(rows)}
    require(encode(result) == output, 'NONCANONICAL_PROTOCOL')
    return result


def check_examples(plan):
    plain = (100, 20, 50, 10, 0, 0, 0, 0, 0, 20)
    prior = (135, 20, 50, 10, 20, 0, 8, 2, 5, 20)
    current = (129, 20, 50, 10, 14, 0, 8, 2, 5, 20)
    rows = {arm: {key: [v] * MEASURED for key, v in zip(METRICS, values)}
            for arm, values in zip(ARMS, (plain, prior, current))}
    good = encode({'workload': dict(HEADER, max_rolling_second=8, min_spacing_ns=125000000),
                   'orders': list(range(6)) * 10, 'samples_ns': rows,
                   'cache': {arm: {'hits': 67, 'misses': 1} for arm in ARMS[1:]}})
    parsed = decode(good, plan)
    require(parsed['diagnosis']['paired_deltas']['CURRENT_minus_PRIOR']['all_triplets']['TOTAL']['mean_ns'] == -6,
            'POSITIVE_PROTOCOL_EXAMPLE')
    # A single legal clock interval can be below the timer resolution.
    with_zero = good.replace('CURRENT EVENT_SINK 2,', 'CURRENT EVENT_SINK 0,', 1)
    with_zero = with_zero.replace('CURRENT OTHER 20,', 'CURRENT OTHER 22,', 1)
    require(decode(with_zero, plan)['samples_ns']['CURRENT']['EVENT_SINK'][0] == 0, 'ZERO_INTERVAL_EXAMPLE')
    mutations = [('hits=67', 'hits=68'), ('starts=204', 'starts=205'), ('prior_events=68', 'prior_events=67'),
                 ('current_events=68', 'current_events=69'), ('max_in_flight=1', 'max_in_flight=2'),
                 ('max_rolling_second=8', 'max_rolling_second=9'), ('125000000', '124999999'),
                 ('ORDERS 0,1', 'ORDERS 1,1'), ('CURRENT OTHER 20,', 'CURRENT OTHER 21,'),
                 ('CURRENT FINGERPRINT 0,', 'CURRENT FINGERPRINT 1,'), ('PRIOR HMAC 20,', 'PRIOR HMAC 020,')]
    for original, replacement in mutations:
        bad = good.replace(original, replacement, 1)
        require(bad != good, 'INVALID_MUTATION')
        try:
            decode(bad, plan)
        except ValueError:
            continue
        raise ValueError('NEGATIVE_PROTOCOL_EXAMPLE_ACCEPTED')
    return {'positive': 2, 'rejected': len(mutations)}


def render(work):
    return pg.load('postgres_crossover_sources', GENERATE).build_sources(ROOT, work)


def source_map():
    with schema.workspace() as (work, cleanup):
        _, digests = render(work)
    guards.require_cleanup(cleanup)
    return digests


def compile_fixture(work, result, plan):
    jdbc, result['jdbc_dependencies'] = schema.pinned_drivers(work)
    manifest = review.read(performance.SPRING)
    require(manifest['h2_license_file'] == guards.SPRING_LICENSE, 'SPRING_LICENSE_PATH')
    spring, result['spring_dependencies'] = schema.g2.phase2.dependencies(work, manifest)
    cp = os.pathsep.join(map(str, (*jdbc, *spring)))
    sources, result['instrumented_source_sha512'] = render(work)
    sources.extend(path for _, path in h.p5.p4.approved_paths(JAVA_INPUTS))
    classes = work / 'classes'
    classes.mkdir()
    command = schema.base.JAVAC + ['-cp', cp, '-d', str(classes), *map(str, sources)]
    result['compile'], _ = native.run_private('compile-postgres-crossover', performance.limited(command, plan), work, 30)
    verify_dependencies(result)
    return os.pathsep.join((str(classes), cp))


def verify_dependencies(proof):
    historical = review.read(performance.run_paths(REFERENCE)[1])
    for key in ('jdbc_dependencies', 'spring_dependencies'):
        require(proof[key] == historical[key], 'PINNED_DEPENDENCIES')


def identity(plan):
    digest = review.read(review.PILOT)['profiles']['POSTGRESQL']['native_runtime']['server_sha256']
    require(re.fullmatch(r'[a-f0-9]{64}', digest) is not None, 'DB_BINARY_PIN')
    return {'version': plan['profiles']['POSTGRESQL']['server_version'], 'server_sha256': digest}


def verify_runtime(proof, plan):
    runtime = proof['native_runtime']
    for receipt, name in ((proof['compile'], 'compile-postgres-crossover'), (proof['client'], 'postgres-crossover'),
                          (runtime['initialization'], 'postgresql-initdb')):
        require(receipt['name'] == name and receipt['exit_code'] == 0 and receipt['status'] == 'PASS'
                and receipt['child_reaped'] is True and receipt['process_group_quiesced'] is True, 'CHILD_LIFECYCLE')
    limits = plan['limits']
    require(runtime['profile'] == 'postgresql' and runtime['provider'] == 'native'
            and all(runtime[k] == v for k, v in identity(plan).items()) and runtime['server_groups_stopped'] == 1
            and all(runtime[k] is True for k in ('private_directory', 'loopback_listener_owned', 'server_stopped',
                                                 'process_groups_quiesced'))
            and 0 < runtime['peak_rss_bytes'] <= runtime['rss_limit_bytes'] == limits['db_rss_bytes']
            and 0 < runtime['peak_data_bytes'] <= runtime['data_limit_bytes'] == limits['db_scratch_bytes']
            and runtime['cpu_limit_seconds'] == limits['process_cpu_seconds'], 'DB_RESOURCE_OR_CLEANUP')


def prepare(result, plan):
    hashes = h.hashes(input_paths())
    result['protocol_checks'] = check_examples(plan)
    with schema.workspace() as (work, cleanup):
        result['cleanup'] = cleanup
        compile_fixture(work, result, plan)
        require(h.hashes(input_paths()) == hashes, 'INPUTS_CHANGED')
    guards.require_cleanup(cleanup)


def run(result, plan):
    hashes = h.hashes(input_paths())
    signed = signed_approval(plan, hashes, source_map())
    result['input_sha512'] = hashes
    result['approval_sha512'] = h.hashes((APPROVAL,))[APPROVAL]
    audit = ROOT / '.git/udak-product-g5'
    lock_dir = ROOT / '.git/udak-g2-managed'
    for directory in (audit, lock_dir):
        require(directory.resolve() == directory, 'AUDIT_LOCATION')
        directory.mkdir(parents=True, exist_ok=True)
    marker = audit / (RUN_ID + '.claimed')
    with os.fdopen(os.open(lock_dir / 'RUN.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(not os.path.lexists(marker) and not os.path.lexists(ROOT / REPORT), 'APPROVAL_ALREADY_USED')
        with schema.workspace() as (work, cleanup):
            result['cleanup'] = cleanup
            result['stage'] = 'COMPILE'
            cp = compile_fixture(work, result, plan)
            result['stage'] = 'PREFLIGHT'
            expected = identity(plan)
            require(native._fingerprint(native.PG / 'postgres', 'postgresql', work) == expected, 'DB_BINARY')
            require(signed_approval(plan, h.hashes(input_paths()), result['instrumented_source_sha512']) == signed
                    and h.hashes((APPROVAL,))[APPROVAL] == result['approval_sha512'], 'APPROVAL_CHANGED')
            with marker.open('x') as claim:
                claim.write(result['approval_sha512'] + '\n')
                claim.flush()
                os.fsync(claim.fileno())
            result['workload_run_claimed'] = True
            result['stage'] = 'NATIVE_RUN'
            result['native_start_attempted'] = True
            with native.instance('postgresql', work) as (port, private, runtime):
                result['native_runtime'] = runtime
                require(runtime['loopback_listener_owned'] is True and all(runtime[k] == v for k, v in expected.items()),
                        'DB_LISTENER_IDENTITY')
                command = [*schema.base.JAVA, '-cp', cp, 'ProductG5PerformanceMain', 'POSTGRESQL', str(port)]
                result['client'], output = native.run_private('postgres-crossover', performance.limited(command, plan),
                    work, performance.CLIENT_SECONDS, (private + '\n').encode('ascii'))
                require(output.stat().st_size <= MAX_OUTPUT, 'OUTPUT_BOUND')
                raw = output.read_bytes()
                result['measurement'] = decode(raw.decode('ascii'), plan)
                result['protocol_sha512'] = hashlib.sha512(raw).hexdigest()
            result['stage'] = 'CLEANUP'
            verify_runtime(result, plan)
            require(h.hashes(input_paths()) == hashes and h.hashes((APPROVAL,))[APPROVAL] == result['approval_sha512'],
                    'INPUTS_CHANGED')
        guards.require_cleanup(cleanup)
    result.pop('stage')


def verify(plan):
    proof = review.read(REPORT)
    hashes = proof['input_sha512']
    require(set(hashes) == set(input_paths()), 'INPUT_INVENTORY')
    current = h.hashes(input_paths())
    for path in hashes:
        if hashes[path] != current[path]:
            require(path in (SELF, MYSQL, 'tools/run-g5-performance.py', 'tools/verify-product-g5.py'),
                    'INPUT_DIGEST')
            archived = subprocess.run(['git', '--no-lazy-fetch', '--no-replace-objects', 'cat-file', 'blob',
                                       f'{EVIDENCE_REVISION}:{path}'], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, timeout=3, check=True)
            require(hashlib.sha512(archived.stdout).hexdigest() == hashes[path], 'ARCHIVED_INPUT_DIGEST')
    signed_approval(plan, hashes, proof['instrumented_source_sha512'])
    require(proof['schema_version'] == 1 and proof['status'] == 'PASS' and proof['run_id'] == RUN_ID
            and proof['diagnostic_only'] is True and proof['profile'] == 'POSTGRESQL'
            and proof['native_start_attempted'] is True and proof['workload_run_claimed'] is True
            and proof['docker_containers_started'] == 0 and proof['approval_sha512'] == h.hashes((APPROVAL,))[APPROVAL]
            and 0 < proof['wall_seconds'] <= plan['limits']['wall_seconds'], 'RUN_EVIDENCE')
    with schema.workspace() as (work, cleanup):
        _, digests = render(work)
        require(digests == proof['instrumented_source_sha512'], 'INSTRUMENTED_INPUTS')
    guards.require_cleanup(cleanup)
    guards.require_cleanup(proof['cleanup'])
    verify_runtime(proof, plan)
    verify_dependencies(proof)
    raw = encode(proof['measurement'])
    require(hashlib.sha512(raw.encode('ascii')).hexdigest() == proof['protocol_sha512']
            and decode(raw, plan) == proof['measurement'], 'TIMING_EVIDENCE')
    return proof['measurement']['diagnosis']


def main():
    args = sys.argv[1:]
    if args not in (['--proposal'], ['--prepare'], ['--run'], ['--verify']):
        print('usage: run-postgres-crossover.py {--proposal|--prepare|--run|--verify}', file=sys.stderr)
        return 2
    plan = scope()
    result = {'schema_version': 1, 'status': 'FAIL', 'run_id': RUN_ID, 'profile': 'POSTGRESQL', 'diagnostic_only': True,
              'workload_run_claimed': False, 'docker_containers_started': 0, 'native_start_attempted': False}
    for sig in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, schema.interrupted)
    start = time.monotonic()
    signal.alarm(plan['limits']['wall_seconds'])
    try:
        if args == ['--proposal']:
            print(json.dumps(proposal(plan, h.hashes(input_paths()), source_map()), indent=2))
            return 0
        if args == ['--verify']:
            result['diagnosis'] = verify(plan)
        elif args == ['--prepare']:
            prepare(result, plan)
        else:
            run(result, plan)
        require(time.monotonic() - start <= plan['limits']['wall_seconds'], 'WALL_LIMIT')
        result['status'] = 'PASS'
    except (OSError, KeyError, ValueError, RuntimeError, TypeError, subprocess.SubprocessError) as error:
        result['failure_type'] = type(error).__name__
        if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,60}', str(error)):
            result['reason'] = str(error)
    finally:
        signal.alarm(0)
        result['wall_seconds'] = round(time.monotonic() - start, 3)
        if result['workload_run_claimed']:
            h.p5.p4.save(ROOT / REPORT, result)
    for key in ('spring_dependencies', 'jdbc_dependencies', 'instrumented_source_sha512'):
        result.pop(key, None)
    if args == ['--run']:
        keys = ('status', 'stage', 'workload_run_claimed', 'native_start_attempted', 'failure_type', 'reason')
        result = {k: result[k] for k in keys if k in result}
    print(json.dumps(result))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
