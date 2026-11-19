#!/usr/bin/env python3
"""Run the Observe contracts and H2 compatibility without rewriting historical evidence."""
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
SELF = 'tools/release-performance/verify-observe-candidate.py'
REPORT = 'evidence/PRODUCT-G5-OBSERVE-JDBC-WRAPPER-CANDIDATE.json'
REQUIREMENT = 'RELEASE-023'
spec = importlib.util.spec_from_file_location('candidate_phase3', ROOT / 'tools/run-phase3.py')
phase3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phase3)
guard = phase3.guard
JVM = ['java', '-Xmx256m', '-XX:MaxMetaspaceSize=128m', '-XX:ActiveProcessorCount=2']
CONTRACTS = {'observe-contract': 'dev.udak.observe.ObserveContractTest',
             'adapter-contract': 'dev.udak.observe.LegacyObserveAdapterContractTest',
             'compatibility-h2': 'dev.udak.compat.LegacyCompatibilityTest'}


def input_hashes():
    sources = [p for module in ('core', 'observe-core', 'legacy-observe', 'legacy-compat-testkit')
               for p in (ROOT / module / 'src').rglob('*.java')]
    demo = ROOT / 'spring-boot-demo/src/main/java/dev/udak/demo'
    sources.extend(demo / (name + '.java') for name in ('UserEntity', 'UserJpaRepository', 'UserMapper', 'MixedUserService'))
    sources.extend(ROOT / path for path in (SELF, 'tools/run-phase3.py', 'tools/run-phase1.py',
                                           'tools/run-core-smoke.sh', 'tools/phase3-dependencies.json'))
    if any(p.resolve() != p or not p.is_file() or p.stat().st_size > 1024**2 for p in sources):
        raise ValueError('Candidate source outside expected bounds')
    return {p.relative_to(ROOT).as_posix(): guard.digest(p.read_bytes()) for p in sorted(sources)}


def execute(result):
    result['input_sha512'] = input_hashes()
    with guard.workspace('udak-observe-candidate-') as (work, cleanup):
        result['cleanup'] = cleanup
        os.putenv('TMPDIR', str(work))
        for key in ('_JAVA_OPTIONS', 'JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS'):
            os.unsetenv(key)
        os.putenv('_JAVA_OPTIONS', ' '.join(JVM[1:]))
        try:
            result['steps']['core-smoke'] = guard.run_step('core-smoke', ['./tools/run-core-smoke.sh'], work)
        finally:
            os.unsetenv('_JAVA_OPTIONS')
        classpath, _, _, compile_step = phase3.build(work)
        result['steps']['compile-phase3'] = compile_step
        for name, entry_point in CONTRACTS.items():
            cp = str(work / 'observe-jdk-only') if name == 'observe-contract' else classpath
            result['steps'][name] = guard.run_step(name, [*JVM, '-cp', cp, entry_point], work,
                                                  timeout=90 if name == 'compatibility-h2' else 30)
            output = (work / (name + '.output')).read_text()
            if name == 'compatibility-h2':
                result['h2'] = phase3.protocol('H2', output, 0)
                if result['h2']['status'] != 'PASS':
                    raise ValueError('H2 fixture protocol differs')
            else:
                count = re.search(r'(?:assertions|checks): ([0-9]+)', output)
                if count is None:
                    raise ValueError('Contract assertion count missing')
                result['steps'][name]['assertions'] = int(count[1])
    if (result['cleanup']['temporary_directory_remaining'] or result['cleanup']['status'] != 'PASS'
            or result['input_sha512'] != input_hashes()):
        raise ValueError('Candidate verification inputs or cleanup differ')
    result['status'] = 'PASS'


def main():
    if sys.argv[1:]:
        return 2
    result = {'schema_version': 1, 'requirement': REQUIREMENT, 'status': 'FAIL', 'steps': {},
              'real_database_trials': 0, 'performance_trials': 0}
    for signum in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, guard.interrupted)
    signal.alarm(240)
    try:
        execute(result)
    except (ValueError, RuntimeError, OSError) as error:
        result['failure_type'] = type(error).__name__
        if isinstance(error, RuntimeError):
            try:
                detail = json.loads(str(error))
                result['failed_step'] = {'name': detail['name'], 'exit_code': detail['exit_code']}
            except (ValueError, KeyError, TypeError):
                pass
    finally:
        signal.alarm(0)
    if result['status'] == 'PASS':
        report = ROOT / REPORT
        temp = report.with_suffix('.json.tmp')
        temp.write_text(json.dumps(result, indent=2) + '\n')
        temp.replace(report)
    print(json.dumps({key: value for key, value in result.items() if key != 'input_sha512'}))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
