#!/usr/bin/env python3
"""Bounded inventory and PR report checks with the existing protected runners."""
from datetime import datetime, timezone
import hashlib
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
FINGERPRINT_REPORT = ROOT / 'evidence/INVENTORY-FINGERPRINT-TEST-CHANGES-VALIDATION.json'
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
FINGERPRINT_STAGES = ('fingerprint-integration', 'fingerprint-report-json', 'fingerprint-report-markdown',
                      'fingerprint-report-mixed', 'fingerprint-report-incomplete')
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


def report_command(work, *options, base='base/SQL-INVENTORY.json', head='head/SQL-INVENTORY.json'):
    # The same CLI entry point runs with a scratch directory as its checkout root.
    launcher = 'import os,runpy,sys; os.chdir(sys.argv.pop(2)); sys.argv.pop(0); runpy.run_path(sys.argv[0],run_name="__main__")'
    return [sys.executable, '-B', '-c', launcher, str(ROOT / 'tools/sql-inventory.py'), str(work),
            '--base', base, '--head', head, *options]


def guarded_report(options):
    # Keep reports within the guard's file-size cap, outside its smaller diagnostic log.
    launcher = """
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import os
import runpy
import sys

script, cwd, scratch, *options = sys.argv[1:]
os.chdir(cwd)
work = Path(scratch)
with (work / 'report.stdout').open('x', encoding='utf-8') as out:
    with (work / 'report.stderr').open('x', encoding='utf-8') as err, redirect_stdout(out), redirect_stderr(err):
        try:
            code = runpy.run_path(script)['main'](options)
        except SystemExit as error:
            code = error.code
(work / 'report.exit').write_text(str(code), encoding='ascii')
"""
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, guard.interrupted)
    try:
        with guard.workspace('udak-local-pr-report-') as (work, cleanup):
            result = guard.run_step('report', [sys.executable, '-B', '-c', launcher,
                str(ROOT / 'tools/sql-inventory.py'), str(Path.cwd()), str(work), *options], work, timeout=10)
            code = (work / 'report.exit').read_text(encoding='ascii')
            if code not in ('0', '1', '2', '3') or not result['child_reaped'] or not result['process_group_quiesced']:
                raise ValueError('Protected report status incomplete')
            report = (work / 'report.stdout').read_bytes()
            error = (work / 'report.stderr').read_bytes()
            if code == '1':
                if report or error != b'ERROR: invalid SQL inventory input or arguments\n':
                    raise ValueError('Unexpected invalid-input diagnostic')
            elif not report or error:
                raise ValueError('Protected report output incomplete')
        if cleanup.get('status') != 'PASS' or cleanup.get('temporary_directory_remaining') is not False:
            raise ValueError('Protected report cleanup incomplete')
    except (OSError, RuntimeError, ValueError):
        print('ERROR: guarded SQL inventory report failed', file=sys.stderr)
        return 1
    sys.stdout.buffer.write(report)
    sys.stderr.buffer.write(error)
    return int(code)


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


def inventory_hash(kind, name):
    return hashlib.sha256(f'udak-inventory-{kind}-id-v1\0{name}'.encode('utf-8')).hexdigest()


def verify_fingerprint_report(base, head, report):
    if (base['schema_version'], head['schema_version'], base['revision'], head['revision']) != (2, 2, '5' * 40, '6' * 40):
        raise ValueError('Fingerprint fixture version or revision mismatch')
    if base['profile'] != head['profile'] or base['dropped'] or head['dropped']:
        raise ValueError('Fingerprint fixture observations incomplete')
    query_id = inventory_hash('query', 'UserJdbc.fingerprintTestLinks')
    tests = {inventory_hash('test', name) for name in ('UserJdbc.fingerprintById', 'UserJdbc.fingerprintByIdAndName')}
    key = ('JDBC', 'SCOPED', query_id)
    before, after = ({(row['framework'], row['identity'], row['query_id_hash']): row for row in snapshot['entries']}
                     for snapshot in (base, head))
    if before.keys() != after.keys() or {entry for entry in before if before[entry] != after[entry]} != {key}:
        raise ValueError('Unexpected fingerprint fixture entries')
    old, new = before[key], after[key]
    if any(entry['unavailable'] or entry['observed'] != 2 or set(entry['test_ids']) != tests or len(entry['shapes']) != 2
           for entry in (old, new)):
        raise ValueError('Expected two independently scoped SQL shapes')
    previous = {(shape['fingerprint_hash'], shape['statement_kind']): shape['test_ids'] for shape in old['shapes']}
    current = {(shape['fingerprint_hash'], shape['statement_kind']): shape['test_ids'] for shape in new['shapes']}
    if (previous.keys() != current.keys() or {kind for _, kind in previous} != {'SELECT'}
            or any(len(previous[shape]) != 1 or set(current[shape]) != tests - set(previous[shape]) for shape in previous)
            or {ids[0] for ids in previous.values()} != tests):
        raise ValueError('Fingerprint fixture did not swap both test links')
    expected = [
        {'fingerprint_hash': fingerprint, 'statement_kind': kind,
         'gained_test_ids': current[fingerprint, kind], 'lost_test_ids': previous[fingerprint, kind]}
        for fingerprint, kind in sorted(previous)
    ]
    changed = [query for query in report['queries'] if query['changes']]
    if (report['status'] != 'COMPLETE' or report['fingerprint_test_status'] != 'COMPARABLE'
            or report['changes_detected'] is not True or report['impacted_test_ids'] != sorted(tests)
            or report.get('shared_shape_changes') or len(changed) != 1):
        raise ValueError('Unexpected fingerprint change report')
    query, = changed
    if ((query['framework'], query['identity'], query['query_id_hash']) != key
            or query['shape_status'] != 'UNCHANGED' or query['added_observed_shapes'] or query['absent_observed_shapes']
            or query['gained_test_ids'] or query['lost_test_ids']
            or query['changes'] != ['FINGERPRINT_TEST_LINKS_CHANGED']
            or query['fingerprint_test_changes'] != expected or query['impacted_test_ids'] != sorted(tests)):
        raise ValueError('Fingerprint test delta was not separated from SQL shape changes')
    return query


def run_fingerprint_comparison(result, run, work, command):
    base, head, mixed, incomplete = (work / name / 'SQL-INVENTORY.json'
                                     for name in ('links-base', 'links-head', 'links-legacy', 'links-incomplete'))
    for file in (base, head, mixed, incomplete):
        file.parent.mkdir()
    output = run('fingerprint-integration', [*command, '--fingerprint-test-links', str(base), str(head)], timeout=60)
    checks = {'h2_assertions': contract(output, 'INVENTORY_INTEGRATION')}
    old, new = (json.loads(file.read_bytes()) for file in (base, head))
    report_args = {'base': base.relative_to(work).as_posix(), 'head': head.relative_to(work).as_posix()}
    output = run('fingerprint-report-json', report_command(work, '--fail-on-change', **report_args), expected=3)
    query = verify_fingerprint_report(old, new, json.loads(output))
    markdown = run('fingerprint-report-markdown', report_command(work, '--format', 'markdown', **report_args))
    expected_groups = [
        f"- Fingerprint test links `{row['statement_kind']}` `{row['fingerprint_hash']}`\n"
        f"  - Gained test references `{row['gained_test_ids'][0]}`\n"
        f"  - Lost test references `{row['lost_test_ids'][0]}`"
        for row in query['fingerprint_test_changes']
    ]
    if (any(group not in markdown for group in expected_groups) or 'FINGERPRINT_TEST_LINKS_CHANGED' not in markdown
            or 'Shape status `UNCHANGED`' not in markdown):
        raise ValueError('Fingerprint test changes missing from Markdown')
    legacy = {**old, 'schema_version': 1, 'entries': [
        {**entry, 'shapes': [{k: v for k, v in shape.items() if k != 'test_ids'} for shape in entry['shapes']]}
        for entry in old['entries']
    ]}
    mixed.write_text(json.dumps(legacy), encoding='utf-8')
    output = run('fingerprint-report-mixed', report_command(
        work, '--fail-on-change', **{**report_args, 'base': mixed.relative_to(work).as_posix()}))
    mixed_report = json.loads(output)
    incomplete.write_text(json.dumps({**new, 'dropped': 1}), encoding='utf-8')
    output = run('fingerprint-report-incomplete', report_command(
        work, '--fail-on-change', **{**report_args, 'head': incomplete.relative_to(work).as_posix()}), expected=2)
    incomplete_report = json.loads(output)
    if (mixed_report['status'] != 'COMPLETE' or mixed_report['fingerprint_test_status'] != 'MIXED_VERSIONS'
            or mixed_report['changes_detected'] is not False or incomplete_report['status'] != 'INCOMPLETE'
            or incomplete_report['fingerprint_test_status'] != 'INCOMPLETE'
            or incomplete_report['changes_detected'] is not None
            or any(row.get('fingerprint_test_changes') for report in (mixed_report, incomplete_report)
                   for row in report['queries'])):
        raise ValueError('Missing data produced misleading fingerprint deltas')
    checks.update(markdown='PASS', change_gate=3, mixed_version_status='MIXED_VERSIONS', incomplete_status='INCOMPLETE',
                  fingerprint_changes=query['fingerprint_test_changes'], impacted_test_ids=query['impacted_test_ids'],
                  unchanged_shapes=len(query['head']['shapes']), query_id_hash=query['query_id_hash'])
    result['fingerprint_test_checks'] = checks


def save(result, report):
    if report.exists():
        previous = h.p5.p4.approved_paths([str(report.relative_to(ROOT))])[0][1].read_bytes()
        archive = ROOT / '.git/udak-inventory/previous-reports'
        if (ROOT / '.git').is_dir():
            archive.mkdir(parents=True, exist_ok=True)
            target = archive / (guard.digest(previous) + '.json')
            if not target.exists():
                with target.open('xb') as stream:
                    stream.write(previous)
    h.p5.p4.save(report, result)


def main():
    if sys.argv[1:2] == ['--pr-report']:
        return guarded_report(sys.argv[2:])
    fingerprint_links = sys.argv[1:] == ['--fingerprint-test-links']
    if sys.argv[1:] and not fingerprint_links:
        print('SQL_INVENTORY INVALID_ARGUMENTS')
        return 2
    start = time.monotonic()
    result = {'schema_version': 1, 'status': 'FAIL', 'scope': 'product expansion Phase 1',
              'started_at_utc': datetime.now(timezone.utc).isoformat(), 'steps': [],
              'limits': {'wall_seconds': 300, 'jvm_heap_mib': 256, 'jvm_metaspace_mib': 128,
                         'active_cpus': 2, 'scratch_bytes': 128 * 1024**2, 'scratch_entries': 2000},
              'docker_containers_started': 0, 'network_database_connections': 0,
              'not_run': ['live four DBMS rerun', 'load/performance', 'production capture', 'external publication']}
    expected_stages = STAGES + FINGERPRINT_STAGES if fingerprint_links else STAGES
    if fingerprint_links:
        result['scope'] = 'NEXT-004 observed fingerprint test links in PR reports'
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
            fixture_command = JAVA + ['-cp', fixture_cp, 'dev.udak.inventory.InventoryIntegrationTest']
            integration = ROOT / 'sql-inventory/src/integrationTest/java/dev/udak/inventory/InventoryIntegrationTest.java'
            run('compile-integration', JAVAC + ['-cp', fixture_cp, '-d', str(classes), str(integration)])
            base, head = (work / label / 'SQL-INVENTORY.json' for label in ('base', 'head'))
            base.parent.mkdir()
            head.parent.mkdir()
            result['adapter_assertions'] = contract(run('inventory-integration', [*fixture_command, str(base), str(head)],
                timeout=60), 'INVENTORY_INTEGRATION')
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
            if fingerprint_links:
                run_fingerprint_comparison(result, run, work, fixture_command)
            if tuple(step['name'] for step in result['steps']) != expected_stages or result['input_sha512'] != inputs():
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
                if isinstance(failure, dict) and failure.get('name') in expected_stages:
                    result['failed_step'] = failure
            except ValueError:
                pass
    finally:
        signal.alarm(0)
        result['elapsed_seconds'] = round(time.monotonic() - start, 3)
        save(result, FINGERPRINT_REPORT if fingerprint_links else REPORT)
    print(json.dumps({k: v for k, v in result.items() if k not in ('input_sha512', 'example_report')}))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
