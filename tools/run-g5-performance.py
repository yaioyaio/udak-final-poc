#!/usr/bin/env python3
"""Run the authorized NFR-02 comparison on sequential owned DB fixtures."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
APPROVAL = 'evidence/PRODUCT-G5-PERFORMANCE-APPROVAL.json'
FIXTURE = 'tools/release-performance/ProductG5PerformanceMain.java'
SPRING = 'tools/phase2-dependencies.json'
OBSERVE = 'legacy-observe/src/main/java/dev/udak/observe/jdbc/ObserveDataSource.java'
CLIENT_SECONDS = 55
FILE_LIMIT_EXEC = ('import os,resource,sys; n=int(sys.argv[1]); '
                   'resource.setrlimit(resource.RLIMIT_FSIZE,(n,n)); os.execvp(sys.argv[2],sys.argv[2:])')

spec = importlib.util.spec_from_file_location('product_g5_review', ROOT / 'tools/verify-product-g5.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)
schema, h = review.schema, review.h
native = schema.native


def authorized():
    limits = review.criteria()['performance']
    token = h.hashes([review.CRITERIA])[review.CRITERIA]
    if review.read(APPROVAL) != {'schema_version': 1, 'status': 'APPROVED',
                                'approval_basis': 'EXPLICIT_USER_CONFIRMATION', 'criteria_sha512': token,
                                'authorized_runs': 1}:
        raise ValueError('Approved performance plan differs')
    return limits


def sources():
    return (FIXTURE, OBSERVE, *(p.relative_to(ROOT).as_posix()
            for p in sorted((ROOT / 'observe-core/src/main/java').rglob('*.java'))))


def input_hashes():
    return h.hashes((*sources(), APPROVAL, review.CRITERIA, SPRING, schema.DRIVERS,
                     'tools/run-g5-performance.py', 'tools/verify-product-g5.py', 'tools/run-schema-regression.py',
                     'tools/run-phase2.py', 'tools/schema-native.py', 'tools/run-phase6.py', 'tools/run-g2.py', review.PILOT))


def limited(command, limits):
    return [sys.executable, '-I', '-S', '-c', FILE_LIMIT_EXEC, str(limits['limits']['child_log_bytes']), *command]


def compile_fixture(work, cp, limits):
    classes = work / 'classes'
    classes.mkdir()
    command = schema.base.JAVAC + ['-cp', cp, '-d', str(classes), *(str(ROOT / source) for source in sources())]
    receipt, _ = native.run_private('compile-product-g5-perf', limited(command, limits), work, 30)
    return receipt


def run_profile(work, profile, limits, expected_binary, cp, result):
    name = 'observe-perf-' + profile.lower()
    item = result['profiles'][profile] = {'status': 'FAIL'}
    with native.instance(profile.lower(), work) as (port, password, runtime):
        item['native_runtime'] = runtime
        versions = limits['profiles'][profile]
        if (runtime['version'] != versions['server_version'] or runtime['server_sha256'] != expected_binary
                or runtime['loopback_listener_owned'] is not True):
            raise ValueError('Owned DB identity differs')
        command = limited(schema.base.JAVA + ['-cp', cp, 'ProductG5PerformanceMain', profile, str(port)], limits)
        step, output = native.run_private(name, command, work, CLIENT_SECONDS, (password + '\n').encode('ascii'))
        if output.stat().st_size > 8192 or not step['child_reaped'] or not step['process_group_quiesced']:
            raise ValueError('Owned client receipt incomplete')
        item.update(review.protocol(output.read_text(encoding='ascii'), profile, limits), versions=versions, step=step)
    if not runtime['server_stopped'] or not runtime['process_groups_quiesced']:
        raise native.PreservationRequired('Owned server shutdown unconfirmed')
    item['status'] = item['assessment']['status']


def run(plan, result):
    result['input_sha512'] = input_hashes()
    approval_digest = result['input_sha512'][APPROVAL]
    audit = ROOT / '.git/udak-product-g5'
    audit.mkdir(parents=True, exist_ok=True)
    lock_dir = ROOT / '.git/udak-g2-managed'
    lock_dir.mkdir(parents=True, exist_ok=True)
    marker = audit / (approval_digest + '.claimed')
    with os.fdopen(os.open(lock_dir / 'RUN.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if marker.exists() or (ROOT / review.PERFORMANCE).exists():
            raise ValueError('Approved run already claimed')
        with schema.workspace() as (work, cleanup):
            result['cleanup'] = cleanup
            jdbc, result['jdbc_dependencies'] = schema.pinned_drivers(work)
            spring, result['spring_dependencies'] = schema.g2.phase2.dependencies(work, review.read(SPRING))
            cp = os.pathsep.join(map(str, [*jdbc, *spring]))
            classes = work / 'classes'
            result['compile'] = compile_fixture(work, cp, plan)
            prior = review.read(review.PILOT)['profiles']
            binaries = {name: prior[name]['native_runtime']['server_sha256'] for name in plan['profiles']}
            for name, path in (('POSTGRESQL', native.PG / 'postgres'), ('MYSQL', native.MYSQL / 'mysqld')):
                found = native._fingerprint(path, name.lower(), work)
                if found['server_sha256'] != binaries[name] or found['version'] != plan['profiles'][name]['server_version']:
                    raise ValueError('Native binary preflight differs')
            with marker.open('x') as receipt:
                receipt.write(approval_digest + '\n')
                receipt.flush()
                os.fsync(receipt.fileno())
            result['workload_run_claimed'] = True
            for name in plan['profiles']:
                run_profile(work, name, plan, binaries[name], os.pathsep.join((str(classes), cp)), result)
            if input_hashes() != result['input_sha512']:
                raise ValueError('Measurement inputs changed')
        if cleanup.get('status') != 'PASS' or cleanup.get('remaining') is not False:
            raise ValueError('Owned performance scratch cleanup unconfirmed')


def main():
    if sys.argv[1:]:
        return 2
    result = {'schema_version': 1, 'status': 'FAIL', 'profiles': {}, 'workload_run_claimed': False,
              'containers_started': 0}
    try:
        plan = authorized()
    except (ValueError, OSError, KeyError, TypeError):
        print('PRODUCT_G5_PERFORMANCE NOT AUTHORIZED')
        return 2
    start = time.monotonic()
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, schema.interrupted)
    signal.alarm(plan['limits']['wall_seconds'])
    try:
        run(plan, result)
        result['status'] = 'PASS' if all(row['status'] == 'PASS' for row in result['profiles'].values()) else 'FAIL'
    except Exception as error:
        result['failure_type'] = type(error).__name__
    finally:
        signal.alarm(0)
        result['wall_seconds'] = round(time.monotonic() - start, 3)
        if result['workload_run_claimed']:
            h.p5.p4.save(ROOT / review.PERFORMANCE, result)
    print(json.dumps({'status': result['status'], 'profiles': {k: v['status'] for k, v in result['profiles'].items()},
                      'workload_run_claimed': result['workload_run_claimed']}))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
