#!/usr/bin/env python3
"""Prepare, run, or reconstruct the one-run MySQL Observe reuse diagnostic."""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
SELF = 'tools/release-performance/run-mysql-attribution.py'
PREDECESSOR = 'tools/release-performance/run-postgres-attribution.py'
spec = importlib.util.spec_from_file_location('postgres_attribution', ROOT / PREDECESSOR)
pg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pg)
build_reuse_sources = pg.load('mysql_attribution_sources', pg.GENERATE).build_reuse_sources
performance, review, schema, h, native = pg.performance, pg.review, pg.schema, pg.h, pg.native
require, rank95, sum_at, relative_ratio = pg.require, pg.rank95, pg.sum_at, pg.relative_ratio
ARMS, JDBC = pg.ARMS, pg.JDBC

RUN_ID = 'MYSQL-ATTRIBUTION'
PROFILE = 'MYSQL'
REFERENCE = 'OBSERVE-REUSE'
APPROVAL = 'evidence/PRODUCT-G5-MYSQL-ATTRIBUTION-APPROVAL.json'
REPORT = 'evidence/PRODUCT-G5-MYSQL-ATTRIBUTION.json'
APPROVAL_BASIS = 'EXPLICIT_USER_REQUEST'
SOURCE_REVISION = '21aeaf2b5e60637c6be3fb173923abfeb6b583f3'
EVIDENCE_REVISION = '69616f69c589f107f1d2f6ce85be211bbf2462e9'
ARCHIVED_RUNNERS = (SELF, 'tools/run-g5-performance.py')
OBSERVE_PACKAGE = 'observe-core/src/main/java/dev/udak/observe/'
ARCHIVED_INPUTS = (performance.OBSERVE, OBSERVE_PACKAGE + 'SqlObserver.java', OBSERVE_PACKAGE + 'ObservationDigest.java',
                   'tools/verify-product-g5.py', *ARCHIVED_RUNNERS)
SPRING_LICENSE = 'jdbc-spring/src/test/resources/META-INF/LICENSE-H2.txt'
OBSERVATION = ('FINGERPRINT', 'EVENT_CREATE', 'EVENT_SINK')
HMAC = 'JDBC_TAG_HMAC'
METRICS = ('TOTAL', *JDBC, HMAC, *OBSERVATION, 'OBSERVE_PROXY', 'OTHER')
MAX_PROTOCOL_BYTES = 32 * 1024


def scope():
    limits = review.criteria()['performance']
    return {**limits, 'profiles': {PROFILE: limits['profiles'][PROFILE]}}


def input_paths():
    return (*performance.performance_inputs(), *performance.run_paths(REFERENCE), SELF, PREDECESSOR, pg.GENERATE,
            pg.PROBE, SPRING_LICENSE, 'tools/run-sql-inventory.py', 'tools/run-phase1.py', 'tools/run-phase3.py',
            'tools/run-phase4.py', 'tools/run-phase5.py')


def proposal(plan, hashes):
    return {'schema_version': 1, 'run_id': RUN_ID, 'authorized_runs': 1, 'diagnostic_only': True,
            'reference_run_id': REFERENCE, 'scope': plan, 'input_sha512': hashes}


def require_approval(hashes):
    signed = review.read(APPROVAL)
    expected = {**proposal(scope(), hashes), 'status': 'APPROVED', 'approval_basis': APPROVAL_BASIS}
    require(json.dumps(signed, sort_keys=True) == json.dumps(expected, sort_keys=True), 'APPROVAL_MISMATCH')
    return signed


def source_blob(path):
    require(path in ARCHIVED_INPUTS, 'ARCHIVE_PATH')
    revision = EVIDENCE_REVISION if path in ARCHIVED_RUNNERS else SOURCE_REVISION
    blob = subprocess.run(
        ['git', '--no-lazy-fetch', '--no-replace-objects', 'cat-file', 'blob', f'{revision}:{path}'],
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3,
    )
    require(blob.returncode == 0 and 0 < len(blob.stdout) <= 1024**2, 'ARCHIVE_BLOB')
    return blob.stdout


def require_original_sources(hashes):
    for path in ARCHIVED_INPUTS:
        require(hashlib.sha512(source_blob(path)).hexdigest() == hashes[path], 'ARCHIVE_INPUT_DIGEST')


def reference():
    row = review.performance_result(review.criteria()['performance'], REFERENCE)[PROFILE]
    require(row['status'] == 'FAIL', 'REFERENCE_EXPECTED_FAIL')
    return row


def binary_identity(plan):
    pinned = review.read(review.PILOT)['profiles'][PROFILE]['native_runtime']['server_sha256']
    require(re.fullmatch(r'[0-9a-f]{64}', pinned) is not None, 'DB_BINARY_PIN')
    return {'version': plan['profiles'][PROFILE]['server_version'], 'server_sha256': pinned}


def summarize(samples, plan):
    count = plan['measured_per_arm']
    indices = range(count)
    for row in samples.values():
        require(row.keys() == set(METRICS), 'TIMING_COLUMNS')
        require(all(len(values) == count and all(type(value) is int and 0 <= value <= 10**10 for value in values)
                    for values in row.values()), 'TIMING_SAMPLES')
        require(all(row['TOTAL'][i] > 0 and row['TOTAL'][i] == sum_at(row, METRICS[1:], i) for i in indices),
                'TIMING_PARTITION')
    plain, observe = (samples[arm] for arm in ARMS)
    require(all(not any(plain[key]) for key in (HMAC, *OBSERVATION, 'OBSERVE_PROXY')), 'PLAIN_OBSERVE_COMPONENTS')
    require(not any(observe['FINGERPRINT']), 'MEASURED_FINGERPRINT_MISS')
    require(all(all(observe[key]) for key in (HMAC, 'EVENT_CREATE', 'EVENT_SINK', 'OBSERVE_PROXY')),
            'MISSING_OBSERVE_COMPONENTS')

    assessment = review.compare(plain['TOTAL'], observe['TOTAL'], plan)
    plain95 = assessment['baseline_p95_ns']
    exclusions = {'all_components': (), 'without_hmac': (HMAC,), 'without_fingerprint_and_events': OBSERVATION,
                  'without_hmac_fingerprint_and_events': (HMAC, *OBSERVATION)}
    sensitivity = {}
    for name, removed in exclusions.items():
        adjusted95 = rank95([observe['TOTAL'][i] - sum_at(observe, removed, i) for i in indices])
        sensitivity[name] = {'observe_p95_ns': adjusted95, 'relative_to_plain_p95_percent': relative_ratio(adjusted95, plain95)}

    tail_count = (5 * count + 99) // 100
    groups = {'all_pairs': list(indices)}
    for arm in ARMS:
        groups[arm.lower() + '_tail_pairs'] = sorted(indices, key=lambda i: (samples[arm]['TOTAL'][i], i))[-tail_count:]
    paired = {}
    for name, positions in groups.items():
        deltas = {key: sum(observe[key][i] - plain[key][i] for i in positions) for key in METRICS}
        paired[name] = {'indices': positions, 'signed_delta_sums_ns': deltas,
                        'jdbc_delta_sum_ns': sum(deltas[key] for key in JDBC),
                        'total_delta_without_hmac_ns': deltas['TOTAL'] - deltas[HMAC],
                        'total_delta_without_hmac_fingerprint_and_events_ns':
                            deltas['TOTAL'] - sum(deltas[key] for key in (HMAC, *OBSERVATION))}
    return {'instrumented_p95': assessment,
            'component_p95_ns': {arm: {key: rank95(samples[arm][key]) for key in METRICS} for arm in ARMS},
            'p95_arithmetic_sensitivity': sensitivity, 'paired_deltas': paired}


def encode(measurement):
    counts, rows, cache = (measurement[key] for key in ('workload', 'samples_ns', 'cache'))
    header = f'PRODUCT_PERF profile={PROFILE}' + ''.join(f' {key}={counts[key]}' for key in review.EXPECTED_FIELDS)

    def series(arm, key):
        return ','.join(map(str, rows[arm][key]))

    lines = [header, *(f'{arm}_NS ' + series(arm, 'TOTAL') for arm in ARMS)]
    lines.extend(f'ATTRIBUTION {arm} {key} ' + series(arm, key) for arm in ARMS for key in METRICS)
    lines.append(f'ATTRIBUTION_CACHE hits={cache["hits"]} misses={cache["misses"]}')
    return '\n'.join(lines) + '\n'


def decode(output, plan):
    require(len(output) <= MAX_PROTOCOL_BYTES and output.isascii(), 'PROTOCOL_BOUND')
    lines = output.splitlines()
    require(len(lines) == 4 + len(ARMS) * len(METRICS), 'PROTOCOL_LENGTH')
    query = review.protocol('\n'.join(lines[:3]), PROFILE, plan)
    rows = {arm: {} for arm in ARMS}
    index = 3
    for arm in ARMS:
        for key in METRICS:
            match = re.fullmatch(rf'ATTRIBUTION {arm} {key} ([0-9]{{1,11}}(?:,[0-9]{{1,11}})*)', lines[index])
            require(match is not None, 'TIMING_PROTOCOL')
            rows[arm][key] = list(map(int, match[1].split(',')))
            index += 1
    require(rows['PLAIN']['TOTAL'] == query['plain_ns'] and rows['OBSERVE']['TOTAL'] == query['observe_ns'],
            'QUERY_TIMING_BOUNDS')
    match = re.fullmatch(r'ATTRIBUTION_CACHE hits=([0-9]{1,3}) misses=([0-9]{1,3})', lines[-1])
    require(match is not None, 'CACHE_PROTOCOL')
    hits, misses = map(int, match.groups())
    require(hits == query['workload']['events'] - 1 and misses == 1, 'CACHE_COUNTS')
    result = {'workload': query['workload'], 'samples_ns': rows, 'cache': {'hits': hits, 'misses': misses},
              'diagnosis': summarize(rows, plan)}
    require(encode(result) == output, 'NONCANONICAL_PROTOCOL')
    return result


def verify_protocol_examples(plan):
    n = plan['measured_per_arm']
    plain = dict(zip(METRICS, (100, 20, 50, 10, 0, 0, 0, 0, 0, 20)))
    observe = dict(zip(METRICS, (135, 20, 50, 10, 20, 0, 8, 2, 5, 20)))
    starts = plan['starts_per_database']
    sample = {'workload': dict(starts=starts, completed=starts, warmup_per_arm=plan['warmup_per_arm'],
                                measured_per_arm=n, verified_rows=starts, events=starts // 2, errors=0, max_in_flight=1,
                                max_rolling_second=8, min_spacing_ns=125000000),
              'samples_ns': {arm: {key: [value] * n for key, value in row.items()}
                             for arm, row in zip(ARMS, (plain, observe))},
              'cache': {'hits': 103, 'misses': 1}}
    good = encode(sample)
    checked = decode(good, plan)
    sensitivity = checked['diagnosis']['p95_arithmetic_sensitivity']
    require(encode(checked) == good and [v['observe_p95_ns'] for v in sensitivity.values()] == [135, 115, 125, 105],
            'POSITIVE_PROTOCOL_EXAMPLE')
    mutations = (('hits=103 misses=1', 'hits=102 misses=2'), ('starts=208', 'starts=207'),
                 ('max_in_flight=1', 'max_in_flight=2'), ('max_rolling_second=8', 'max_rolling_second=9'),
                 ('min_spacing_ns=125000000', 'min_spacing_ns=124999999'),
                 ('PLAIN_NS 100,', 'PLAIN_NS 99,'), ('ATTRIBUTION OBSERVE OTHER 20,', 'ATTRIBUTION OBSERVE OTHER 21,'),
                 ('ATTRIBUTION OBSERVE JDBC_TAG_HMAC 20,', 'ATTRIBUTION OBSERVE JDBC_TAG_HMAC 020,'),
                 ('ATTRIBUTION OBSERVE EVENT_SINK 2,', 'ATTRIBUTION OBSERVE EVENT_SINK 0,'),
                 ('ATTRIBUTION OBSERVE FINGERPRINT 0,', 'ATTRIBUTION OBSERVE FINGERPRINT 1,'),
                 ('ATTRIBUTION OBSERVE JDBC_PREPARE', 'ATTRIBUTION PLAIN JDBC_PREPARE'))
    invalid = [good.replace(old, new, 1) for old, new in mutations]
    invalid.extend((good[:-1], good + 'EXTRA\n'))
    for bad in invalid:
        require(bad != good, 'NEGATIVE_PROTOCOL_EXAMPLE_UNCHANGED')
        try:
            decode(bad, plan)
        except ValueError:
            continue
        raise ValueError('NEGATIVE_PROTOCOL_EXAMPLE_ACCEPTED')
    return {'positive': 1, 'rejected': len(invalid)}


def render(source_root, work):
    return build_reuse_sources(source_root, work, (*performance.sources(), pg.PROBE))


def compile_fixture(work, result, plan):
    jdbc, result['jdbc_dependencies'] = schema.pinned_drivers(work)
    manifest = review.read(performance.SPRING)
    require(manifest['h2_license_file'] == SPRING_LICENSE, 'SPRING_LICENSE_PATH')
    spring, result['spring_dependencies'] = schema.g2.phase2.dependencies(work, manifest)
    cp = os.pathsep.join(map(str, (*jdbc, *spring)))
    sources, result['instrumented_source_sha512'] = render(ROOT, work)
    classes = work / 'classes'
    classes.mkdir()
    command = schema.base.JAVAC + ['-cp', cp, '-d', str(classes), *map(str, sources)]
    result['compile'], _ = native.run_private('compile-mysql-attribution', performance.limited(command, plan), work, 30)
    return os.pathsep.join((str(classes), cp))


def require_cleanup(cleanup):
    require(cleanup['status'] == 'PASS' and cleanup['remaining'] is False
            and 0 < cleanup['files'] <= 5000 and 0 < cleanup['bytes'] <= 1024**3, 'WORKSPACE_CLEANUP')


def verify_dependencies(receipts):
    historical = review.read(performance.run_paths(REFERENCE)[1])
    for key in ('jdbc_dependencies', 'spring_dependencies'):
        require(receipts[key] == historical[key], 'PINNED_DEPENDENCIES')


def verify_runtime(proof, plan, expected):
    runtime = proof['native_runtime']
    for job, name in ((proof['compile'], 'compile-mysql-attribution'), (proof['client'], 'mysql-attribution'),
                      (runtime['initialization'], 'mysql-initialize')):
        require(job['name'] == name and job['status'] == 'PASS' and job['exit_code'] == 0 and job['child_reaped'] is True
                and job['process_group_quiesced'] is True, 'CHILD_LIFECYCLE')
    require(runtime['profile'] == 'mysql' and runtime['provider'] == 'native' and runtime['private_directory'] is True
            and all(runtime[key] == value for key, value in expected.items())
            and all(runtime[key] is True for key in ('loopback_listener_owned', 'server_stopped', 'process_groups_quiesced'))
            and runtime['server_groups_stopped'] == 2
            and 0 < runtime['peak_rss_bytes'] <= runtime['rss_limit_bytes'] == plan['limits']['db_rss_bytes']
            and 0 < runtime['peak_data_bytes'] <= runtime['data_limit_bytes'] == plan['limits']['db_scratch_bytes']
            and runtime['cpu_limit_seconds'] == plan['limits']['process_cpu_seconds'], 'DB_RESOURCE_OR_CLEANUP')


def prepare(result, plan):
    result['protocol_checks'] = verify_protocol_examples(plan)
    hashes = h.hashes(input_paths())
    require_original_sources(hashes)
    with schema.workspace() as (work, cleanup):
        result['cleanup'] = cleanup
        compile_fixture(work, result, plan)
        verify_dependencies(result)
        require(h.hashes(input_paths()) == hashes, 'INPUTS_CHANGED')
    require_cleanup(cleanup)


def run(result, plan):
    hashes = h.hashes(input_paths())
    signed = require_approval(hashes)
    require_original_sources(hashes)
    result['reference_assessment'] = reference()
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
            verify_dependencies(result)
            result['stage'] = 'PREFLIGHT'
            expected = binary_identity(plan)
            require(native._fingerprint(native.MYSQL / 'mysqld', 'mysql', work) == expected, 'DB_BINARY')
            require(require_approval(h.hashes(input_paths())) == signed
                    and h.hashes((APPROVAL,))[APPROVAL] == result['approval_sha512'], 'APPROVAL_CHANGED')
            with marker.open('x') as claim:
                claim.write(result['approval_sha512'] + '\n')
                claim.flush()
                os.fsync(claim.fileno())
            result['workload_run_claimed'] = True
            result['stage'] = 'NATIVE_RUN'
            result['native_start_attempted'] = True
            with native.instance('mysql', work) as (port, private, runtime):
                result['native_runtime'] = runtime
                require(runtime['loopback_listener_owned'] is True and all(runtime[key] == value for key, value in expected.items()),
                        'DB_LISTENER_IDENTITY')
                command = [*schema.base.JAVA, '-cp', cp, 'ProductG5PerformanceMain', PROFILE, str(port)]
                result['client'], output = native.run_private('mysql-attribution', performance.limited(command, plan), work,
                    performance.CLIENT_SECONDS, (private + '\n').encode('ascii'))
                require(output.stat().st_size <= MAX_PROTOCOL_BYTES, 'OUTPUT_BOUND')
                raw = output.read_bytes()
                result['measurement'] = decode(raw.decode('ascii'), plan)
                result['protocol_sha512'] = hashlib.sha512(raw).hexdigest()
            result['stage'] = 'CLEANUP'
            verify_runtime(result, plan, expected)
            require(h.hashes(input_paths()) == hashes and h.hashes((APPROVAL,))[APPROVAL] == result['approval_sha512'],
                    'INPUTS_CHANGED')
        require_cleanup(cleanup)
    result.pop('stage')


def verify_instrumented_sources(hashes, proof):
    require(hashes.keys() == set(input_paths()), 'INPUT_INVENTORY')
    require_original_sources(hashes)
    files = [path for path in input_paths() if path not in ARCHIVED_INPUTS]
    require(h.hashes(files) == {path: hashes[path] for path in files}, 'INPUT_DIGESTS')
    originals = (*performance.sources(), pg.PROBE)
    with schema.workspace() as (work, cleanup):
        source_root = work / 'original'
        for path, live in h.p5.p4.approved_paths(originals):
            target = source_root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source_blob(path) if path in ARCHIVED_INPUTS else live.read_bytes())
        _, generated = render(source_root, work)
        require(generated == proof, 'INSTRUMENTED_SOURCE_HASHES')
    require_cleanup(cleanup)


def verify():
    proof = review.read(REPORT)
    signed = require_approval(proof['input_sha512'])
    plan = signed['scope']
    require(proof['schema_version'] == 1 and proof['status'] == 'PASS' and proof['run_id'] == RUN_ID
            and proof['diagnostic_only'] is True and proof['profile'] == PROFILE
            and proof['workload_run_claimed'] is True and proof['docker_containers_started'] == 0
            and proof['native_start_attempted'] is True
            and proof['approval_sha512'] == h.hashes((APPROVAL,))[APPROVAL]
            and proof['reference_assessment'] == reference()
            and 0 < proof['wall_seconds'] <= plan['limits']['wall_seconds'], 'RUN_EVIDENCE')
    verify_instrumented_sources(signed['input_sha512'], proof['instrumented_source_sha512'])
    require_cleanup(proof['cleanup'])
    verify_runtime(proof, plan, binary_identity(plan))
    verify_dependencies(proof)
    measurement = proof['measurement']
    reconstructed = encode(measurement)
    require(hashlib.sha512(reconstructed.encode('ascii')).hexdigest() == proof['protocol_sha512']
            and decode(reconstructed, plan) == measurement, 'TIMING_EVIDENCE')
    return {'reference_assessment': proof['reference_assessment'], 'measurement': measurement['diagnosis'],
            'cache': measurement['cache']}


def main():
    args = sys.argv[1:]
    if args not in (['--proposal'], ['--prepare'], ['--run'], ['--verify']):
        print('usage: run-mysql-attribution.py {--proposal|--prepare|--run|--verify}', file=sys.stderr)
        return 2
    plan = scope()
    result = {'schema_version': 1, 'status': 'FAIL', 'run_id': RUN_ID, 'profile': PROFILE, 'diagnostic_only': True,
              'workload_run_claimed': False, 'docker_containers_started': 0, 'native_start_attempted': False}
    for sig in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, schema.interrupted)
    start = time.monotonic()
    signal.alarm(plan['limits']['wall_seconds'])
    try:
        if args == ['--proposal']:
            hashes = h.hashes(input_paths())
            require_original_sources(hashes)
            print(json.dumps(proposal(plan, hashes), indent=2))
            return 0
        if args == ['--verify']:
            result.update(verify())
        elif args == ['--prepare']:
            prepare(result, plan)
        else:
            run(result, plan)
        require(time.monotonic() - start <= plan['limits']['wall_seconds'], 'WALL_LIMIT')
        result['status'] = 'PASS'
    except (OSError, KeyError, ValueError, RuntimeError, TypeError, subprocess.TimeoutExpired) as error:
        result['failure_type'] = type(error).__name__
    finally:
        signal.alarm(0)
        result['wall_seconds'] = round(time.monotonic() - start, 3)
        if result['workload_run_claimed']:
            h.p5.p4.save(ROOT / REPORT, result)
    if args == ['--run']:
        keys = ('status', 'stage', 'workload_run_claimed', 'native_start_attempted', 'failure_type')
        result = {key: result[key] for key in keys if key in result}
    if args == ['--prepare']:
        result.pop('jdbc_dependencies', None)
        result.pop('spring_dependencies', None)
    print(json.dumps(result))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
