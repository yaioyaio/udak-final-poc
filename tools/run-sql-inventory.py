#!/usr/bin/env python3
"""Bounded inventory and PR report checks with the existing protected runners."""
from datetime import datetime, timezone
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
REPORT = ROOT / 'evidence/SQL-INVENTORY-VALIDATION.json'
spec = importlib.util.spec_from_file_location('inventory_guard', ROOT / 'tools/run-phase6.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
phase3 = h.p5.p4.phase3
guard = h.guard
JAVA = ['java', '-Xmx256m', '-XX:MaxMetaspaceSize=128m', '-XX:ActiveProcessorCount=2']
JAVAC = ['javac', '-J-Xmx256m', '-J-XX:MaxMetaspaceSize=128m', '-J-XX:ActiveProcessorCount=2', '--release', '17']
SCRIPTS = (
    'tools/run-sql-inventory.py', 'tools/sql-inventory.py', 'tools/test-sql-inventory.py',
    'tools/run-phase1.py', 'tools/run-phase3.py', 'tools/run-phase4.py', 'tools/run-phase5.py',
    'tools/run-phase6.py', 'tools/run-core-smoke.sh', 'tools/phase3-dependencies.json',
    'sql-inventory/settings.gradle.kts', 'sql-inventory/build.gradle.kts',
)
BASELINE = ('evidence/PHASE3-GATE.json', 'evidence/PHASE6-GATE.json')
STAGES = ('core-smoke', 'compile-legacy', 'legacy-h2', 'compile-inventory', 'inventory-contract',
          'compile-integration', 'inventory-integration', 'report-tests', 'report-json', 'report-markdown',
          'report-change-gate', 'report-incomplete', 'report-invalid')
CORES = ('core', 'observe-core', 'legacy-observe', 'legacy-compat-testkit', 'sql-inventory')


def inputs():
    java = {str(p.relative_to(ROOT)) for name in CORES for p in (ROOT / name / 'src').rglob('*.java')}
    java |= {'spring-boot-demo/src/main/java/dev/udak/demo/' + name + '.java'
             for name in ('UserEntity', 'UserJpaRepository', 'UserMapper', 'MixedUserService')}
    return h.hashes(java | set(SCRIPTS) | set(BASELINE))


def contract(output, label):
    match = re.fullmatch(re.escape(label) + r' PASS\nASSERTIONS=([1-9][0-9]{0,4})\n', output)
    if match is None:
        raise ValueError('Test protocol incomplete')
    return int(match[1])


def report_command(work, *options):
    # The same CLI entry point runs with a scratch directory as its checkout root.
    launcher = 'import os,runpy,sys; os.chdir(sys.argv.pop(2)); sys.argv.pop(0); runpy.run_path(sys.argv[0],run_name="__main__")'
    return [sys.executable, '-B', '-c', launcher, str(ROOT / 'tools/sql-inventory.py'), str(work),
            '--base', 'base/SQL-INVENTORY.json', '--head', 'head/SQL-INVENTORY.json', *options]


def validate_pair(base, head, report):
    if base['profile'] != head['profile'] or base['dropped'] or head['dropped']:
        raise ValueError('Fixture observations incomplete')
    if (base['revision'], head['revision']) != ('1' * 40, '2' * 40):
        raise ValueError('Fixture revision mismatch')
    for snapshot, is_head in ((base, False), (head, True)):
        observed = [row for row in snapshot['entries'] if row['observed'] > 0]
        if {row['framework'] for row in observed} != {'JPA', 'MYBATIS', 'JDBC'} or len(observed) != (4 if is_head else 3):
            raise ValueError('All adapter observations required')
        if any(row['identity'] != 'SCOPED' or row['unavailable'] or not row['test_ids'] for row in observed):
            raise ValueError('Fixture test references missing')
    # Match by fixture identity and reason, without using the diff implementation to derive expectations.
    old = {(row['framework'], row['query_id_hash']): row for row in base['entries']}
    new = {(row['framework'], row['query_id_hash']): row for row in head['entries']}
    if len(old) != 5 or old.keys() != new.keys():
        raise ValueError('Fixture entry inventory mismatch')
    mybatis = [key for key, row in old.items() if key[0] == 'MYBATIS' and row['observed']]
    jdbc = [key for key, row in old.items() if key[0] == 'JDBC' and row['declared']]
    if len(mybatis) != 1 or len(jdbc) != 1:
        raise ValueError('Fixture named cases missing')
    shape_key, coverage_key = mybatis[0], jdbc[0]
    if old[shape_key]['shapes'] == new[shape_key]['shapes'] or not (old[coverage_key]['observed'] == 0 < new[coverage_key]['observed']):
        raise ValueError('Fixture change not exercised')
    if any(old[key] != new[key] for key in old.keys() - {shape_key, coverage_key}):
        raise ValueError('Unexpected fixture differences')
    if report.get('status') != 'COMPLETE' or report.get('changes_detected') is not True:
        raise ValueError('Comparable change report expected')
    expected_tests = sorted(set(new[shape_key]['test_ids'] + new[coverage_key]['test_ids']))
    if len(expected_tests) != 2 or report.get('impacted_test_ids') != expected_tests:
        raise ValueError('Impacted test references mismatch')
    changed = {(row['framework'], row['query_id_hash']): row for row in report['queries'] if row['changes']}
    if set(changed) != {shape_key, coverage_key}:
        raise ValueError('Report query changes mismatch')
    shape = changed[shape_key]
    if (set(shape['changes']) != {'OBSERVED_SHAPES_ADDED', 'OBSERVED_SHAPES_ABSENT'}
            or shape['added_observed_shapes'] != new[shape_key]['shapes']
            or shape['absent_observed_shapes'] != old[shape_key]['shapes']):
        raise ValueError('Changed MyBatis shape not reported')
    coverage = changed[coverage_key]
    if 'NEWLY_OBSERVED' not in coverage['changes'] or coverage['base']['observed'] != 0 or coverage['head']['observed'] != 1:
        raise ValueError('New JDBC observation not reported')
    return {'observed_frameworks': ['JDBC', 'JPA', 'MYBATIS'], 'stable_entries': 5,
            'shape_changed_queries': 1, 'newly_observed_queries': 1, 'impacted_tests': 2}


def save(result):
    if REPORT.exists():
        previous = h.p5.p4.approved_paths([str(REPORT.relative_to(ROOT))])[0][1].read_bytes()
        archive = ROOT / '.git/udak-inventory/previous-reports'
        if (ROOT / '.git').is_dir():
            archive.mkdir(parents=True, exist_ok=True)
            target = archive / (guard.digest(previous) + '.json')
            if not target.exists():
                with target.open('xb') as stream:
                    stream.write(previous)
    h.p5.p4.save(REPORT, result)


def main():
    if sys.argv[1:]:
        print('SQL_INVENTORY INVALID_ARGUMENTS')
        return 2
    start = time.monotonic()
    result = {'schema_version': 1, 'status': 'FAIL', 'scope': 'product expansion Phase 1',
              'started_at_utc': datetime.now(timezone.utc).isoformat(), 'steps': [],
              'limits': {'wall_seconds': 300, 'jvm_heap_mib': 256, 'jvm_metaspace_mib': 128,
                         'active_cpus': 2, 'scratch_bytes': 128 * 1024**2, 'scratch_entries': 2000},
              'docker_containers_started': 0, 'network_database_connections': 0,
              'not_run': ['live four DBMS rerun', 'load/performance', 'production capture', 'external publication']}
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(sig, guard.interrupted)
    signal.alarm(300)
    try:
        result['input_sha512'] = inputs()
        with guard.workspace('udak-sql-inventory-') as (temporary, cleanup):
            work = temporary.resolve()
            result['cleanup'] = cleanup

            def run(name, command, *, timeout=45, expected=0):
                proof = h.step(name, command, work, timeout=timeout, expected=expected)
                if not proof['child_reaped'] or not proof['process_group_quiesced']:
                    raise ValueError('Child process cleanup incomplete')
                result['steps'].append(proof)
                return (work / (name + '.output')).read_text()

            run('core-smoke', ['/usr/bin/env', '_JAVA_OPTIONS=-Xmx256m -XX:MaxMetaspaceSize=128m -XX:ActiveProcessorCount=2', './tools/run-core-smoke.sh'])
            # Reuse the previously pinned dependency verification and strip proxy configuration from fetches.
            phase3.fetch = h.fetch
            prior_step = guard.run_step
            try:
                guard.run_step = h.step
                old_cp, _, dependency, compile_step = phase3.build(work)
            finally:
                guard.run_step = prior_step
            compile_step['name'] = 'compile-legacy'
            result['steps'].append(compile_step)
            result['frozen_legacy_artifacts'] = len(dependency['artifacts'])
            output = run('legacy-h2', JAVA + ['-cp', old_cp, 'dev.udak.compat.LegacyCompatibilityTest'], timeout=60)
            result['legacy_h2'] = phase3.protocol('H2', output, 0)
            if result['legacy_h2']['status'] != 'PASS':
                raise ValueError('Legacy H2 checks incomplete')
            inventory_java = [str(path) for directory in ('main', 'test')
                              for path in sorted((ROOT / 'sql-inventory/src' / directory).rglob('*.java'))]
            classes = work / 'inventory-classes'
            isolated = os.pathsep.join((str(classes), str(work / 'observe-jdk-only')))
            run('compile-inventory', JAVAC + ['-cp', str(work / 'observe-jdk-only'), '-d', str(classes)] + inventory_java)
            result['java_contract_assertions'] = contract(run('inventory-contract', JAVA + ['-cp', isolated,
                'dev.udak.inventory.InventoryContractTest']), 'INVENTORY_CONTRACT')
            fixture_cp = os.pathsep.join((str(classes), old_cp))
            integration = ROOT / 'sql-inventory/src/integrationTest/java/dev/udak/inventory/InventoryIntegrationTest.java'
            run('compile-integration', JAVAC + ['-cp', fixture_cp, '-d', str(classes), str(integration)])
            base, head = (work / label / 'SQL-INVENTORY.json' for label in ('base', 'head'))
            base.parent.mkdir()
            head.parent.mkdir()
            result['adapter_assertions'] = contract(run('inventory-integration', JAVA + ['-cp', fixture_cp,
                'dev.udak.inventory.InventoryIntegrationTest', str(base), str(head)], timeout=60), 'INVENTORY_INTEGRATION')
            output = run('report-tests', [sys.executable, '-B', 'tools/test-sql-inventory.py'])
            match = re.search(r'^Ran ([1-9][0-9]{0,3}) tests? in .*\n\nOK\n$', output, re.M)
            if not match:
                raise ValueError('Report test suite incomplete')
            result['cli_tests'] = int(match[1])
            report = json.loads(run('report-json', report_command(work, '--format', 'json')))
            base_json, head_json = json.loads(base.read_bytes()), json.loads(head.read_bytes())
            result['report_checks'] = validate_pair(base_json, head_json, report)
            markdown = run('report-markdown', report_command(work, '--format', 'markdown'))
            if not markdown.startswith('# ') or base_json['revision'] not in markdown or head_json['revision'] not in markdown:
                raise ValueError('Markdown report incomplete')
            run('report-change-gate', report_command(work, '--fail-on-change'), expected=3)
            result['fixture_sha512'] = {'base': guard.digest(base.read_bytes()), 'head': guard.digest(head.read_bytes())}
            head_json['dropped'] = 1
            head.write_text(json.dumps(head_json))
            incomplete = json.loads(run('report-incomplete', report_command(work, '--fail-on-change'), expected=2))
            if incomplete.get('status') != 'INCOMPLETE':
                raise ValueError('Incomplete observations accepted')
            head.write_text('{"fixture":"INVALID_INVENTORY_FIXTURE"}')
            invalid = run('report-invalid', report_command(work), expected=1)
            if 'INVALID_INVENTORY_FIXTURE' in invalid:
                raise ValueError('Input content leaked')
            if tuple(step['name'] for step in result['steps']) != STAGES or result['input_sha512'] != inputs():
                raise ValueError('Execution inventory changed')
            # Capture only the sanitized report projection. Live app events and scratch artifacts stay local.
            result['example_report'] = report
            result['documentation'] = guard.verify_documents()
        if cleanup.get('status') != 'PASS' or cleanup.get('temporary_directory_remaining') is not False:
            raise ValueError('Workspace cleanup incomplete')
        result['status'] = 'PASS'
    except Exception as error:
        result['failure_type'] = type(error).__name__
        if isinstance(error, RuntimeError):
            try:
                failure = json.loads(str(error))
                if isinstance(failure, dict) and failure.get('name') in STAGES:
                    result['failed_step'] = failure
            except ValueError:
                pass
    finally:
        signal.alarm(0)
        result['elapsed_seconds'] = round(time.monotonic() - start, 3)
        save(result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('input_sha512', 'example_report')}))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
