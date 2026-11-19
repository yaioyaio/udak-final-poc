#!/usr/bin/env python3
"""Prepare, run once, or reconstruct the paired PostgreSQL execute diagnostic."""
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
SELF = DIR + 'run-postgres-execute-detail.py'
MYSQL = DIR + 'run-mysql-attribution.py'
spec = importlib.util.spec_from_file_location('execute_guards', ROOT / MYSQL)
guards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guards)
pg, performance, review, schema, h, native = guards.pg, guards.performance, guards.review, guards.schema, guards.h, guards.native
require = pg.require
RUN_ID = 'POSTGRESQL-EXECUTE-DETAIL'
APPROVAL = 'evidence/PRODUCT-G5-POSTGRESQL-EXECUTE-DETAIL-APPROVAL.json'
REPORT = 'evidence/PRODUCT-G5-POSTGRESQL-EXECUTE-DETAIL.json'
REFERENCE = 'OBSERVE-REUSE-V2'
GENERATE = DIR + 'execute_sources.py'
JAVA_INPUTS = tuple(DIR + name + '.java' for name in ('ExecuteTrial', 'ExecuteIntervals', 'ExecuteSocketFactory'))
CURRENT = 'e1af76ce9e77ed743aef0522c008084441c51dfa'
EVIDENCE_REVISION = '69cb837895a12f943998e8c53ed25c4bb5584897'
CROSSOVER = DIR + 'run-postgres-crossover.py'
NATIVE = 'tools/schema-native.py'
LIB = Path('/opt/homebrew/opt/postgresql@17/lib/postgresql/pg_stat_statements.dylib')
LIB_SHA256 = '91928b728710875cc080bfdf651d43ec1937fa6210beb56898916e573d2c15cf'
GUC = ('shared_preload_libraries=pg_stat_statements', 'compute_query_id=on',
       'pg_stat_statements.track_planning=on', 'pg_stat_statements.save=off')
ARMS = ('PLAIN', 'CURRENT')
METRICS = ('QUERY_WALL', 'JDBC_WALL', 'THREAD_CPU', 'READ_NS', 'WRITE_NS', 'READ_CALLS', 'WRITE_CALLS',
           'READ_BYTES', 'WRITE_BYTES', 'SERVER_PLAN', 'SERVER_EXEC', 'SERVER_PLANS')
MEASURED = 32
HEADER = dict(target_starts=76, snapshot_reads=77, warmup_pairs=6, measured_pairs=MEASURED,
              verified_rows=76, events=38, errors=0, max_in_flight=1)
MAX_OUTPUT = 32 * 1024


def scope():
    official = review.criteria()['performance']
    profile = official['profiles']['POSTGRESQL']
    require(profile['server_version'] == '17.11' and profile['driver_version'] == '42.7.14', 'PROFILE_PIN')
    return {'arms': list(ARMS), 'warmup_pairs': 6, 'measured_pairs': MEASURED, 'target_starts': 76,
            'snapshot_reads': 77, 'paced_starts': 153, 'database_sessions': 1,
            'extra_setup_requests': ['CREATE EXTENSION', 'EXPLAIN without ANALYZE'],
            'measurement': 'one baseline snapshot and one snapshot after each target, outside measured intervals',
            'measured_order': 'alternating plain-first and current-first', 'current_revision': CURRENT,
            'native_identity': identity({'profiles': {'POSTGRESQL': profile}}),
            'extension': {'library': str(LIB), 'sha256': LIB_SHA256, 'settings': list(GUC)},
            'profiles': {'POSTGRESQL': profile}, 'limits': official['limits']}


def input_paths():
    predecessor = pg.load('execute_crossover', CROSSOVER)
    return (*predecessor.input_paths(), predecessor.APPROVAL, predecessor.REPORT, SELF, GENERATE, *JAVA_INPUTS)


def proposal(plan, hashes, sources):
    return {'schema_version': 1, 'run_id': RUN_ID, 'authorized_runs': 1, 'diagnostic_only': True,
            'reference_run_id': 'POSTGRESQL-CROSSOVER', 'scope': plan, 'input_sha512': hashes, 'instrumented_source_sha512': sources}


def signed_approval(plan, hashes, sources):
    signed = review.read(APPROVAL)
    expected = {**proposal(plan, hashes, sources), 'status': 'APPROVED', 'approval_basis': 'EXPLICIT_USER_REQUEST'}
    require(json.dumps(signed, sort_keys=True) == json.dumps(expected, sort_keys=True), 'APPROVAL_MISMATCH')
    return signed


def series(values):
    return ','.join(map(str, values))


def summarize(rows):
    indices = list(range(MEASURED))
    tail = sorted(indices, key=lambda i: (-rows['CURRENT']['JDBC_WALL'][i], i))[:3]
    query_tail = sorted(indices, key=lambda i: (-rows['CURRENT']['QUERY_WALL'][i], i))[:3]
    paired = {}
    for label, group in (('all_pairs', indices), ('current_jdbc_top_three', tail), ('current_query_top_three', query_tail)):
        paired[label] = {}
        for metric in METRICS:
            deltas = [rows['CURRENT'][metric][i] - rows['PLAIN'][metric][i] for i in group]
            paired[label][metric] = {'mean': round(statistics.mean(deltas), 3), 'median': statistics.median(deltas),
                                     'sum': sum(deltas)}
    return {'units': {k: ('calls' if k.endswith('_CALLS') else 'bytes' if k.endswith('_BYTES')
                          else 'plans' if k == 'SERVER_PLANS' else 'ns') for k in METRICS},
            'component_p95': {arm: {metric: pg.rank95(values) for metric, values in row.items()}
                              for arm, row in rows.items()},
            'current_jdbc_top_three_indices': tail, 'current_query_top_three_indices': query_tail,
            'paired_current_minus_plain': paired,
            'interpretation': 'JDBC wall includes caller CPU and socket intervals. Server intervals can overlap client '
                              'socket intervals. These measures do not form an additive partition.'}


def encode(measurement):
    counts = measurement['workload']
    lines = ['PG_EXECUTE_DETAIL' + ''.join(f' {k}={counts[k]}' for k in (*HEADER, 'max_rolling_second', 'min_spacing_ns')),
             'PG_EXECUTE_ORDERS ' + series(measurement['orders'])]
    lines.extend(f'PG_EXECUTE {arm} {key} ' + series(measurement['samples'][arm][key])
                 for arm in ARMS for key in METRICS)
    return '\n'.join(lines) + '\n'


def decode(output, plan):
    require(len(output) <= MAX_OUTPUT and output.isascii(), 'PROTOCOL_BOUND')
    lines = output.splitlines()
    require(len(lines) == 2 + len(ARMS) * len(METRICS), 'PROTOCOL_LENGTH')
    prefix = 'PG_EXECUTE_DETAIL' + ''.join(f' {k}={v}' for k, v in HEADER.items())
    match = re.fullmatch(prefix + r' max_rolling_second=([1-8]) min_spacing_ns=([0-9]{1,12})', lines[0])
    require(match and plan['limits']['min_start_spacing_ns'] <= int(match[2]) <= 10**9 * plan['limits']['wall_seconds'],
            'WORKLOAD_BOUNDS')
    counts = dict(HEADER, max_rolling_second=int(match[1]), min_spacing_ns=int(match[2]))
    orders = [i % 2 for i in range(MEASURED)]
    require(lines[1] == 'PG_EXECUTE_ORDERS ' + series(orders), 'ORDER_PROTOCOL')
    rows = {}
    index = 2
    for arm in ARMS:
        row = rows[arm] = {}
        for metric in METRICS:
            match = re.fullmatch(rf'PG_EXECUTE {arm} {metric} ([0-9]{{1,11}}(?:,[0-9]{{1,11}}){{31}})', lines[index])
            require(match, 'TIMING_PROTOCOL')
            row[metric] = list(map(int, match[1].split(',')))
            index += 1
        for i in range(MEASURED):
            require(0 < row['JDBC_WALL'][i] <= row['QUERY_WALL'][i] <= 10**10
                    and row['THREAD_CPU'][i] <= row['JDBC_WALL'][i]
                    and row['READ_NS'][i] + row['WRITE_NS'][i] <= row['JDBC_WALL'][i], 'CLIENT_INTERVALS')
            require(all(row[k][i] > 0 for k in ('READ_CALLS', 'WRITE_CALLS', 'READ_BYTES', 'WRITE_BYTES')),
                    'SOCKET_COUNTERS')
            require(row['SERVER_PLANS'][i] <= 1, 'SERVER_PLAN_COUNT')
    result = {'workload': counts, 'orders': orders, 'samples': rows, 'diagnosis': summarize(rows)}
    require(encode(result) == output, 'NONCANONICAL_PROTOCOL')
    return result


def check_examples(plan):
    rows = {arm: {k: [v] * MEASURED for k, v in zip(METRICS, (120, 100, 50, 60, 30, 1, 1, 128, 80, 8, 65, 1))}
            for arm in ARMS}
    rows['CURRENT']['JDBC_WALL'][:3] = [102, 108, 104]
    good = encode({'workload': dict(HEADER, max_rolling_second=8, min_spacing_ns=125000000),
                   'orders': [0, 1] * 16, 'samples': rows})
    stats = decode(good, plan)['diagnosis']
    require(stats['current_jdbc_top_three_indices'] == [1, 2, 0]
            and stats['paired_current_minus_plain']['all_pairs']['JDBC_WALL']['median'] == 0
            and stats['paired_current_minus_plain']['current_jdbc_top_three']['JDBC_WALL']['sum'] == 14,
            'POSITIVE_PROTOCOL_EXAMPLE')
    mutations = [('target_starts=76', 'target_starts=77'), ('snapshot_reads=77', 'snapshot_reads=76'),
                 ('events=38', 'events=39'), ('max_in_flight=1', 'max_in_flight=2'),
                 ('errors=0', 'errors=1'), ('max_rolling_second=8', 'max_rolling_second=9'),
                 ('125000000', '124999999'), ('ORDERS 0,1', 'ORDERS 1,1'),
                 ('PLAIN READ_NS 60,', 'PLAIN READ_NS 71,'), ('CURRENT THREAD_CPU 50,', 'CURRENT THREAD_CPU 103,'),
                 ('PLAIN QUERY_WALL 120,', 'PLAIN QUERY_WALL 99,'), ('PLAIN READ_CALLS 1,', 'PLAIN READ_CALLS 0,'),
                 ('PLAIN SERVER_PLANS 1,', 'PLAIN SERVER_PLANS 2,'),
                 ('PLAIN READ_BYTES 128,', 'PLAIN READ_BYTES 0128,')]
    for before, after in mutations:
        bad = good.replace(before, after, 1)
        require(good != bad, 'INVALID_MUTATION')
        try:
            decode(bad, plan)
        except ValueError:
            continue
        raise ValueError('NEGATIVE_PROTOCOL_EXAMPLE_ACCEPTED')
    return {'positive': 1, 'rejected': len(mutations)}


def render(work):
    sources, digests = pg.load('postgres_execute_sources', GENERATE).build_sources(ROOT, work)
    original = (ROOT / NATIVE).read_text(encoding='utf8')
    anchor = "'-c', 'log_min_error_statement=panic', '-c', 'autovacuum=off']"
    require(original.count(anchor) == 1, 'POSTGRES_COMMAND_ANCHOR')
    expanded = anchor[:-1] + ', ' + ', '.join("'-c', " + repr(setting) for setting in GUC) + ']'
    specialized = original.replace(anchor, expanded).encode('utf8')
    with (work / 'execute_native.py').open('xb') as output:
        output.write(specialized)
    digests['GENERATED_NATIVE_PROVIDER'] = hashlib.sha512(specialized).hexdigest()
    return sources, digests


def provider(work):
    module_spec = importlib.util.spec_from_file_location('execute_native', work / 'execute_native.py')
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    # The workspace catches this exact exception to preserve an unconfirmed process group.
    module.PreservationRequired = native.PreservationRequired
    module._ACTIVE = native._ACTIVE
    return module


def check_library():
    resolved = LIB.resolve(strict=True)
    installed = (native.PG / 'postgres').resolve(strict=True).parent.parent
    require(resolved == installed / 'lib/postgresql/pg_stat_statements.dylib'
            and resolved.is_file() and not resolved.stat().st_mode & 0o022
            and 0 < resolved.stat().st_size <= 4 * 1024**2
            and hashlib.sha256(resolved.read_bytes()).hexdigest() == LIB_SHA256, 'EXTENSION_IDENTITY')


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
    result['compile'], _ = native.run_private('compile-postgres-execute-detail', performance.limited(command, plan), work, 30)
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
    for receipt, name in ((proof['compile'], 'compile-postgres-execute-detail'), (proof['client'], 'postgres-execute-detail'),
                          (runtime['initialization'], 'postgresql-initdb')):
        require(receipt['name'] == name and receipt['exit_code'] == 0 and receipt['status'] == 'PASS'
                and receipt['child_reaped'] is True and receipt['process_group_quiesced'] is True, 'CHILD_LIFECYCLE')
    limits = plan['limits']
    require(runtime['extension_sha256'] == LIB_SHA256 and runtime['profile'] == 'postgresql' and runtime['provider'] == 'native'
            and all(runtime[k] == v for k, v in identity(plan).items()) and runtime['server_groups_stopped'] == 1
            and all(runtime[k] is True for k in ('private_directory', 'loopback_listener_owned', 'server_stopped',
                                                 'process_groups_quiesced'))
            and 0 < runtime['peak_rss_bytes'] <= runtime['rss_limit_bytes'] == limits['db_rss_bytes']
            and 0 < runtime['peak_data_bytes'] <= runtime['data_limit_bytes'] == limits['db_scratch_bytes']
            and runtime['cpu_limit_seconds'] == limits['process_cpu_seconds'], 'DB_RESOURCE_OR_CLEANUP')


def prepare(result, plan):
    hashes = h.hashes(input_paths())
    check_library()
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
            diag_native = provider(work)
            check_library()
            with marker.open('x') as claim:
                claim.write(result['approval_sha512'] + '\n')
                claim.flush()
                os.fsync(claim.fileno())
            result['workload_run_claimed'] = True
            result['stage'] = 'NATIVE_RUN'
            result['native_start_attempted'] = True
            with diag_native.instance('postgresql', work) as (port, private, runtime):
                result['native_runtime'] = runtime
                runtime['extension_sha256'] = LIB_SHA256
                require(runtime['loopback_listener_owned'] is True and all(runtime[k] == v for k, v in expected.items()),
                        'DB_LISTENER_IDENTITY')
                command = [*schema.base.JAVA, '-cp', cp, 'ProductG5PerformanceMain', 'POSTGRESQL', str(port)]
                try:
                    result['client'], output = native.run_private('postgres-execute-detail',
                        performance.limited(command, plan), work, performance.CLIENT_SECONDS,
                        (private + '\n').encode('ascii'))
                except RuntimeError:
                    output = work / 'postgres-execute-detail.output'
                    if output.is_file() and output.stat().st_size < 96:
                        failure = re.fullmatch(rb'PRODUCT_PERF_ERROR stage=([A-Z]{1,20})\n', output.read_bytes())
                        if failure:
                            result['fixture_stage'] = failure[1].decode('ascii')
                    raise
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
            require(path in (SELF, CROSSOVER, DIR + 'run-mysql-attribution.py', 'tools/run-g5-performance.py',
                             'tools/verify-product-g5.py'), 'INPUT_DIGEST')
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
        print('usage: run-postgres-execute-detail.py {--proposal|--prepare|--run|--verify}', file=sys.stderr)
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
