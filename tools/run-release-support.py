#!/usr/bin/env python3
"""Exercise durable SELECT approval on two isolated native database releases."""
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / 'evidence/RELEASE-SUPPORT-APPROVAL.json'
AUDIT = ROOT / '.git/udak-release-support'
FIXTURE = 'tools/release-support/ApprovalLiveSupportMain.java'
SPRING = 'tools/phase2-dependencies.json'
WALL_SECONDS = 300
JAVA_SECONDS = 45

spec = importlib.util.spec_from_file_location('release_schema', ROOT / 'tools/run-schema-regression.py')
schema = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schema)
approval = schema.load('release_approval', 'tools/run-approval-history.py')
native = schema.native

SCENARIOS = {'MISSING': 0, 'FIRST_GRANT': 1, 'REVOKED': 0, 'REOPENED': 0, 'FRESH_GRANT': 1}
IDENTITY = re.compile(r'IDENTITY (POSTGRESQL|MYSQL) ([0-9]{1,3}(?:\.[0-9]{1,3}){1,2})'
                      r' ([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}) ([a-f0-9]{64}) ([a-f0-9]{64})')
EQUIVALENCE = re.compile(r'EQUIVALENCE ([a-f0-9]{64}) ([a-f0-9]{64}) (true|false)')


def sources():
    main = set().union(*(approval.java_paths(module + '/src/main/java')
                         for module in (approval.MODULE, *approval.LIBRARIES)))
    return main | approval.java_paths(approval.FIXTURES) | {FIXTURE}


def input_hashes():
    harness = {'tools/run-release-support.py', 'tools/run-schema-regression.py', 'tools/schema-native.py',
               'tools/run-approval-history.py', 'tools/run-sql-inventory.py', 'tools/run-phase6.py',
               'tools/run-g2.py', 'tools/run-phase2.py', 'tools/run-phase1.py',
               'tools/run-phase3.py', 'tools/run-phase4.py', 'tools/run-phase5.py', approval.PARSER, SPRING,
               schema.DRIVERS, 'jdbc-spring/src/test/resources/META-INF/LICENSE-H2.txt',
               'sql-jsqlparser/src/main/resources/META-INF/LICENSE-jsqlparser.txt',
               'sql-jsqlparser/src/main/resources/META-INF/NOTICE-jsqlparser.txt'}
    return approval.h.hashes(sources() | harness)


def compile_fixture(work, result):
    spring, result['spring_dependencies'] = schema.g2.phase2.dependencies(work, approval.read_report(SPRING))
    parser, result['parser_dependency'] = approval.guard.dependency_checks(approval.read_report(approval.PARSER), work)
    drivers, result['jdbc_dependencies'] = schema.pinned_drivers(work)
    dependencies = os.pathsep.join(map(str, [parser, *spring, *drivers]))
    classes = work / 'classes'
    result['steps'].append(approval.compile_sources(work, 'compile-release-support', sources(), classes, dependencies))
    return os.pathsep.join([str(classes), dependencies])


def protocol(path, profile):
    if path.stat().st_size > 2048:
        raise ValueError('Fixture response exceeded protocol bound')
    lines = path.read_text(encoding='ascii').splitlines()
    if len(lines) != len(SCENARIOS) + 3 or lines[-1] != 'CLEANUP CONFIRMED':
        raise ValueError('Incomplete approval history receipt')
    scenarios = {}
    for line, (name, expected) in zip(lines, SCENARIOS.items()):
        if line != f'SCENARIO {name} {expected} {expected}':
            raise ValueError('JDBC admission differs')
        _, _, connections, prepares = line.split()
        scenarios[name] = {'status': 'PASS', 'connections_acquired': int(connections),
                           'statements_prepared': int(prepares)}
    identity, proof = IDENTITY.fullmatch(lines[-3]), EQUIVALENCE.fullmatch(lines[-2])
    if (not identity or identity[1] != profile or identity[3] != schema.PROFILES[profile] or not proof
            or (proof[3] == 'true') != (profile == 'POSTGRESQL')):
        raise ValueError('JDBC identity or source equivalence differs')
    return {'server_version': identity[2], 'driver_version': identity[3],
            'server_release_sha256': identity[4], 'driver_release_sha256': identity[5],
            'result_sha256': proof[1], 'equivalence_evidence_sha256': proof[2],
            'postgresql_source_sql_executed': proof[3] == 'true', 'scenarios': scenarios,
            'fixture_table_cleanup': 'CONFIRMED'}


def run_profile(profile, work, classpath, result):
    name = 'approval-' + profile.lower()
    item = result['profiles'][profile] = {'status': 'FAIL'}
    source = result['profiles'].get('POSTGRESQL', {})
    with native.instance(profile.lower(), work) as (port, password, runtime):
        item['native_runtime'] = runtime
        command = approval.p5.JAVA + ['-cp', classpath, 'dev.udak.rewrite.testkit.ApprovalLiveSupportMain',
                profile, str(port), str(work / (name + '.journal')),
                source.get('server_release_sha256', 'local'), source.get('result_sha256', 'local')]
        try:
            step, output = native.run_private(name, command, work, JAVA_SECONDS, (password + '\n').encode('ascii'))
        except RuntimeError:
            output = work / (name + '.output')
            if output.is_file() and output.stat().st_size <= 2048:
                match = re.search(rb'^FIXTURE_ERROR line=([0-9]{1,4})$', output.read_bytes(), re.M)
                if match:
                    item['fixture_error_line'] = int(match[1])
            raise
        item['step'] = step
        item.update(protocol(output, profile))
    if not runtime.get('server_stopped') or not runtime.get('process_groups_quiesced'):
        raise native.PreservationRequired('Native fixture shutdown unconfirmed')
    if not runtime.get('loopback_listener_owned') or item['server_version'] != runtime['version']:
        raise ValueError('Native and JDBC server identity differ')
    if profile == 'MYSQL' and item['result_sha256'] != source['result_sha256']:
        raise ValueError('Translated pages differ from PostgreSQL source results')
    item['source_server_release_sha256'] = source['server_release_sha256']
    item['status'] = 'PASS'


def save(result):
    AUDIT.mkdir(parents=True, exist_ok=True)
    if result['status'] == 'PASS':
        approval.p5.archive_save(REPORT, result)
    else:
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        approval.p5.p4.save(AUDIT / ('failed-' + timestamp + '.json'), result)


def main():
    if sys.argv[1:]:
        print('RELEASE_SUPPORT INVALID_ARGUMENTS')
        return 2
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, schema.interrupted)
    started = time.monotonic()
    result = {'schema_version': 1, 'status': 'FAIL', 'requirement': 'RELEASE-002',
              'scope': 'durable approval on isolated PostgreSQL and MySQL',
              'compile_release': 17, 'docker_containers_started': 0, 'steps': [], 'profiles': {},
              'started_at_utc': datetime.now(timezone.utc).isoformat(),
              'not_run': ['SQL Server approval history', 'Oracle approval history', 'G5',
                          'performance/load', 'production approval issuance', 'multihost journal'],
              'limits': {'wall_seconds': WALL_SECONDS, 'java_seconds_per_profile': JAVA_SECONDS,
                         'jvm_heap_mib': 256, 'jvm_active_cpus': 2, 'database_parallelism': 1,
                         'workspace_entries': 5000, 'workspace_bytes': 1024**3}}
    signal.alarm(WALL_SECONDS)
    try:
        lock_dir = ROOT / '.git/udak-g2-managed'
        lock_dir.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(lock_dir / 'RUN.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result['input_sha512'] = input_hashes()
            with schema.workspace() as (work, cleanup):
                result['cleanup'] = cleanup
                classpath = compile_fixture(work, result)
                for profile in ('POSTGRESQL', 'MYSQL'):
                    run_profile(profile, work, classpath, result)
                if result['input_sha512'] != input_hashes():
                    raise ValueError('Fixture inputs changed during execution')
            if cleanup.get('status') != 'PASS' or cleanup.get('remaining') is not False:
                raise ValueError('Scratch cleanup unconfirmed')
            result['status'] = 'PASS'
            result['elapsed_seconds'] = round(time.monotonic() - started, 3)
            save(result)
    except Exception as error:
        result['status'] = 'FAIL'
        result['failure_type'] = type(error).__name__
        if isinstance(error, RuntimeError):
            try:
                step = json.loads(str(error))
                if isinstance(step, dict) and 'exit_code' in step:
                    result['failed_step'] = step
            except ValueError:
                pass
        result['elapsed_seconds'] = round(time.monotonic() - started, 3)
        save(result)
    finally:
        signal.alarm(0)
    print(json.dumps({'status': result['status'], 'profiles': {p: v['status'] for p, v in result['profiles'].items()},
                      'cleanup': result.get('cleanup', {}), 'failure_type': result.get('failure_type')}))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
