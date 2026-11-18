#!/usr/bin/env python3
"""Bounded approval-history contracts and an embedded H2 SELECT integration check."""
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import time
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
MODULE = 'approval-history'
REPORT = ROOT / 'evidence/APPROVAL-HISTORY-VALIDATION.json'
AUDIT = ROOT / '.git/udak-approval-history'
PARSER = 'tools/phase1-dependencies.json'
LIBRARIES = ('rewrite-core', 'rewrite-jdbc', 'rewrite-jsqlparser')
FIXTURES = 'rewrite-testkit/src/test/java'
TESTS = {
    'history-core': ('dev.udak.rewrite.ApprovalHistoryContractTest', 'APPROVAL_HISTORY_CORE'),
    'history-h2': ('dev.udak.rewrite.testkit.ApprovalHistoryJdbcTest', 'APPROVAL_HISTORY_H2'),
}

spec = importlib.util.spec_from_file_location('approval_guard', ROOT / 'tools/run-phase6.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
guard = h.guard
p5 = h.p5


def java_paths(directory):
    return {p.relative_to(ROOT).as_posix() for p in (ROOT / directory).rglob('*.java')}


def build_inputs():
    paths = set().union(*(java_paths(directory + '/src') for directory in (MODULE, *LIBRARIES)), java_paths(FIXTURES))
    return paths | {directory + '/build.gradle.kts' for directory in (MODULE, *LIBRARIES)} | {
        MODULE + '/settings.gradle.kts',
        'sql-jsqlparser/src/main/resources/META-INF/LICENSE-jsqlparser.txt',
        'sql-jsqlparser/src/main/resources/META-INF/NOTICE-jsqlparser.txt',
    }


def input_hashes():
    return h.hashes(build_inputs() | {
        'tools/run-approval-history.py', 'tools/run-phase6.py', 'tools/run-core-smoke.sh',
        'tools/verify-phase5.py', *p5.HARNESS, *p5.MANIFESTS,
        'evidence/PHASE5-GATE.json', 'evidence/PHASE6-LOCAL-CI.json', 'evidence/PHASE6-VALIDATION.json',
        'evidence/DB-RECOVERY-VALIDATION.json',
    })


def read_report(path):
    return json.loads((ROOT / path).read_text())


def preserved_gates():
    verifier = p5.module('approval_prior_g4', 'tools/verify-phase5.py')
    local, real, _ = map(read_report, verifier.INPUTS)
    actual = verifier.verify(real, local)
    recorded = read_report('evidence/PHASE5-GATE.json')
    if (any(recorded.get(field) != value for field, value in actual.items())
            or recorded.get('execution_reports_sha512') != h.hashes(verifier.INPUTS)
            or recorded.get('verifier_sha512') != guard.digest((ROOT / 'tools/verify-phase5.py').read_bytes())):
        raise ValueError('Prior G4 evidence differs')
    ci = read_report('evidence/PHASE6-LOCAL-CI.json')
    previous = read_report('evidence/PHASE6-VALIDATION.json')
    if (ci['status'] != 'PASS' or ci['source_sha512'] != h.hashes(('tools/local-ci.py', 'tools/run-phase6.py'))
            or ci['evidence_sha512'] != h.hashes(('evidence/PHASE6-VALIDATION.json',
                                                 'evidence/PHASE6-VERIFIER-VALIDATION.json', 'evidence/PHASE6-GATE.json'))
            or previous['status'] != 'PASS' or previous['source_sha512'] != h.hashes(h.sources())
            or previous['configuration_sha512'] != h.hashes(h.CONFIG)):
        raise ValueError('Prior G6 local CI inputs differ')
    recovery = p5.module('approval_prior_recovery', 'tools/run-db-recovery.py')
    baseline = read_report('evidence/DB-RECOVERY-VALIDATION.json')
    if baseline['status'] != 'PASS' or baseline['input_sha512'] != recovery.input_hashes():
        raise ValueError('Prior recovery evidence differs')
    return {'g4_real_database_scenarios': actual['real_database_scenarios'],
            'g6_local_ci_inputs_match': True, 'recovery_inputs_match': True, 'live_db_rerun': False}


def protocol(output, label):
    match = re.fullmatch(re.escape(label) + r' PASS\nASSERTIONS=([1-9][0-9]{0,3})\n', output)
    if not match:
        raise ValueError('Approval history protocol incomplete')
    return int(match[1])


def compile_sources(work, name, sources, output, classpath=None):
    options = ['-cp', classpath] if classpath else []
    return h.step(name, p5.JAVAC + options + ['-d', str(output), *sorted(sources)], work)


def java_contract(work, name, classpath, class_name, arguments=()):
    return h.step(name, p5.JAVA + ['-cp', classpath, class_name, *arguments], work, timeout=25)


def classpath_checks(work, result):
    steps = result['steps']
    smoke_env = '_JAVA_OPTIONS=-Xmx256m -XX:MaxMetaspaceSize=128m -XX:ActiveProcessorCount=2'
    steps.append(h.step('core-smoke', ['/usr/bin/env', smoke_env, './tools/run-core-smoke.sh'], work))
    pure = work / 'pure'
    core = java_paths('rewrite-core/src') | {MODULE + '/src/main/java/dev/udak/rewrite/ApprovalHistory.java',
                                           MODULE + '/src/test/java/dev/udak/rewrite/ApprovalHistoryContractTest.java'}
    steps.append(compile_sources(work, 'compile-history-jdk-only', core, pure))
    steps.append(java_contract(work, 'rewrite-policy-regression', str(pure), 'dev.udak.rewrite.RewritePolicyContractTest'))
    class_name, label = TESTS['history-core']
    steps.append(java_contract(work, 'history-core', str(pure), class_name, [str(work)]))
    result['assertions']['history-core'] = protocol((work / 'history-core.output').read_text(), label)

    jars, result['framework_dependencies'] = p5.p4.phase3.dependencies(work)
    parser, result['parser_dependency'] = guard.dependency_checks(read_report(PARSER), work)
    classes = work / 'jdbc'
    dependencies = os.pathsep.join(map(str, [pure, *jars, parser]))
    sources = {p for p in build_inputs() if p.endswith('.java')} - core
    steps.append(compile_sources(work, 'compile-history-jdbc', sources, classes, dependencies))
    classpath = os.pathsep.join([str(classes), dependencies])
    class_name, label = TESTS['history-h2']
    steps.append(java_contract(work, 'history-h2', classpath, class_name, [str(work)]))
    result['assertions']['history-h2'] = protocol((work / 'history-h2.output').read_text(), label)
    steps.append(java_contract(work, 'rewrite-jdbc-regression', classpath, 'dev.udak.rewrite.jdbc.SelectiveJdbcContractTest'))
    steps.append(java_contract(work, 'rewrite-equivalence-h2', classpath, 'dev.udak.rewrite.testkit.RewriteEquivalenceTest'))
    result['existing_h2_equivalence'] = p5.protocol('H2', (work / 'rewrite-equivalence-h2.output').read_text(), 0)


def package_check(work, result):
    checkout = work / 'package'
    for name, source in p5.p4.approved_paths(build_inputs()):
        destination = checkout / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    binary = h.gradle_distribution(work)
    project = checkout / MODULE
    active_jdk = Path(shutil.which('java') or '/usr/bin/java').resolve().parent.parent
    installed_17 = sorted(p for p in (Path.home() / '.sdkman/candidates/java').glob('17.*')
                          if (p / 'bin/javac').is_file())
    locations = ','.join(map(str, [active_jdk, *installed_17]))
    command = [binary, '--no-daemon', '--console=plain', '--max-workers=1', '--no-watch-fs',
               '--gradle-user-home', str(work / 'home'), '--project-cache-dir', str(work / 'cache'),
               '-Dorg.gradle.jvmargs=-Xmx512m -XX:MaxMetaspaceSize=256m -XX:ActiveProcessorCount=2',
               '-Porg.gradle.java.installations.auto-download=false', '-Porg.gradle.java.installations.paths=' + locations,
               '-p', str(project), 'jar', 'testClasses']
    result['steps'].append(h.step('package-approval-history', command, work, timeout=100))
    jar = project / 'build/libs/approval-history-0.1.0-poc.jar'
    expected = {'dev/udak/rewrite/ApprovalHistory.class', 'dev/udak/rewrite/jdbc/ApprovalHistoryJdbcClient.class'}
    with zipfile.ZipFile(jar) as archive:
        if (not expected <= set(archive.namelist())
                or any(int.from_bytes(archive.read(name)[6:8], 'big') != 61 for name in expected)):
            raise ValueError('Approval history JAR class inventory differs')
    result['package'] = {'classes_verified': len(expected), 'class_major': 61, 'sha512': guard.digest(jar.read_bytes())}


def save(result):
    AUDIT.mkdir(parents=True, exist_ok=True)
    if result['status'] != 'PASS':
        target = AUDIT / ('failed-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.json')
    else:
        target = REPORT
        if target.exists():
            old = target.read_bytes()
            archive = AUDIT / ('prior-' + guard.digest(old) + '.json')
            if not archive.exists():
                with archive.open('xb') as saved:
                    saved.write(old)
    p5.p4.save(target, result)


def main():
    if sys.argv[1:]:
        print('APPROVAL_HISTORY INVALID_ARGUMENTS')
        return 2
    for event in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
        signal.signal(event, guard.interrupted)
    started = time.monotonic()
    result = {'schema_version': 1, 'status': 'FAIL', 'scope': 'product expansion Phase 5',
              'steps': [], 'assertions': {}, 'started_at_utc': datetime.now(timezone.utc).isoformat(),
              'compile_release': 17, 'docker_containers_started': 0, 'external_db_processes_started': 0,
              'not_run': ['real DB approval-history matrix', 'multihost journal', 'production approval issuance', 'G5'],
              'limits': {'wall_seconds': 300, 'jvm_heap_mib': 256, 'jvm_active_cpus': 2, 'database_parallelism': 1,
                         'gradle_heap_mib': 512, 'gradle_workers': 1, 'workspace_entries': 20000, 'workspace_bytes': 2 * 1024**3}}
    signal.alarm(300)
    try:
        AUDIT.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(AUDIT / 'RUN.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result['input_sha512'] = input_hashes()
            result['baseline'] = preserved_gates()
            with h.workspace() as (work, cleanup):
                result['cleanup'] = cleanup
                classpath_checks(work, result)
                package_check(work, result)
                if result['input_sha512'] != input_hashes():
                    raise ValueError('Execution inputs changed')
            if cleanup.get('status') != 'PASS' or cleanup.get('temporary_directory_remaining') is not False:
                raise ValueError('Owned scratch cleanup incomplete')
            result['documentation'] = guard.verify_documents()
            result['status'] = 'PASS'
            save(result)
    except Exception as error:
        result['status'] = 'FAIL'
        result['failure_type'] = type(error).__name__
        if isinstance(error, RuntimeError):
            try:
                receipt = json.loads(str(error))
                if isinstance(receipt, dict) and 'exit_code' in receipt:
                    result['failed_step'] = receipt
            except ValueError:
                pass
        save(result)
    finally:
        signal.alarm(0)
    print(json.dumps({k: v for k, v in result.items() if k not in ('input_sha512', 'framework_dependencies', 'parser_dependency')}))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
