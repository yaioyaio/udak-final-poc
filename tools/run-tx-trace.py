#!/usr/bin/env python3
"""Bounded Spring transaction trace checks on an embedded H2 fixture."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import signal
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / 'evidence/TX-TRACE-VALIDATION.json'
spec = importlib.util.spec_from_file_location('trace_guard', ROOT / 'tools/run-sql-inventory.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
h, guard, p4, phase3 = base.h, base.guard, base.h.p5.p4, base.phase3

TRACE_CASES = ('MIXED_COMMIT', 'REQUIRED_ROLLBACK', 'REQUIRES_NEW', 'SAVEPOINT',
               'CONTEXT_ISOLATION', 'COMPLETION_REENTRY', 'UNKNOWN_OUTCOME', 'REDACTION_AND_LIMIT')
CONTRACTS = {
    'observe-contract': 'dev.udak.observe.ObserveContractTest',
    'adapter-contract': 'dev.udak.observe.LegacyObserveAdapterContractTest',
    'spring-guard-contract': 'dev.udak.consistency.spring.SpringGuardContractTest',
}
STAGES = ('core-smoke', 'compile-legacy', 'compile-trace', *CONTRACTS,
          'legacy-h2-regression', 'guard-h2-regression', 'trace-h2')
PINS = ('tools/run-tx-trace.py', 'tx-trace-spring/build.gradle.kts', 'tx-trace-spring/settings.gradle.kts',
        'evidence/SQL-INVENTORY-VALIDATION.json', 'evidence/PHASE4-GATE.json')


def inputs():
    prior = base.inputs()
    sources = p4.source_paths()
    sources.update(str(p.relative_to(ROOT)) for p in (ROOT / 'tx-trace-spring/src').rglob('*.java'))
    return {**prior, **h.hashes(sources | set(PINS))}


def report(path, data):
    if path.exists():
        approved = p4.approved_paths([str(path.relative_to(ROOT))])[0][1]
        previous = approved.read_bytes()
        if (ROOT / '.git').is_dir():
            archive = ROOT / '.git/udak-tx-trace/previous-reports'
            archive.mkdir(parents=True, exist_ok=True)
            target = archive / (guard.digest(previous) + '.json')
            if not target.exists():
                with target.open('xb') as stream:
                    stream.write(previous)
    p4.save(path, data)


def trace_protocol(output):
    lines = output.splitlines()
    match = re.fullmatch(r'ASSERTIONS=([1-9][0-9]{0,4})', lines[1]) if len(lines) > 1 else None
    if (not match or lines[0] != 'TX_TRACE PASS'
            or lines[2:2 + len(TRACE_CASES)] != ['SCENARIO=' + name + ':PASS' for name in TRACE_CASES]):
        raise ValueError('Trace scenario protocol incomplete')
    proof = {'assertions': int(match[1]), 'scenarios': {name: 'PASS' for name in TRACE_CASES}}
    extra = lines[2 + len(TRACE_CASES):]
    if extra:
        if len(extra) != 1 or not extra[0].startswith('TIMELINE='):
            raise ValueError('Unknown trace protocol field')
        timeline = extra[0][9:].split(',')
        chosen_kinds = ('ATTACHED', 'CHECKPOINT_REUSED', 'FLUSH_COMPLETED', 'BEFORE_COMMIT', 'BEFORE_COMPLETION')
        pattern = re.compile(r'(?:(?:' + '|'.join(chosen_kinds)
                             + r')/1|SQL/(?:JPA|MYBATIS|JDBC)/1|COMPLETED/COMMITTED/1)')
        if not 5 <= len(timeline) <= 32 or any(not pattern.fullmatch(event) for event in timeline):
            raise ValueError('Trace timeline format rejected')
        if (timeline[0] != 'ATTACHED/1' or timeline[-1] != 'COMPLETED/COMMITTED/1'
                or {item.split('/')[1] for item in timeline if item.startswith('SQL/')} != {'JPA', 'MYBATIS', 'JDBC'}):
            raise ValueError('Trace timeline evidence incomplete')
        proof['mixed_commit_timeline'] = timeline
    return proof


def main():
    if sys.argv[1:]:
        print('TX_TRACE INVALID_ARGUMENTS')
        return 2
    started = time.monotonic()
    result = {'schema_version': 1, 'status': 'FAIL', 'scope': 'product expansion Phase 2',
              'started_at_utc': datetime.now(timezone.utc).isoformat(), 'steps': [],
              'limits': {'wall_seconds': 300, 'jvm_heap_mib': 256, 'jvm_metaspace_mib': 128,
                         'active_cpus': 2, 'scratch_bytes': 128 * 1024**2, 'scratch_entries': 2000},
              'compile_release': 17, 'docker_containers_started': 0, 'network_database_connections': 0,
              'not_run': ['four DBMS rerun', 'Boot auto-configuration', 'standalone Gradle build', 'load/performance', 'production tracing']}
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, guard.interrupted)
    signal.alarm(300)
    try:
        result['input_sha512'] = inputs()
        old_inventory = json.loads((ROOT / 'evidence/SQL-INVENTORY-VALIDATION.json').read_text())
        if old_inventory.get('status') != 'PASS' or old_inventory.get('input_sha512') != base.inputs():
            raise ValueError('Inventory validation inputs changed')
        result['previous_inventory_inputs'] = 'VERIFIED'
        with guard.workspace('udak-tx-trace-') as (temporary, cleanup):
            work = temporary.resolve()
            result['cleanup'] = cleanup

            def step(name, command, timeout=45):
                try:
                    proof = h.step(name, command, work, timeout=timeout)
                except RuntimeError:
                    log = work / (name + '.output')
                    if log.is_file() and log.stat().st_size <= 1024**2:
                        safe = re.compile(r'(?:H2 FAIL: [A-Z_]+|TX_TRACE FAIL(?:: [A-Z_]+)?|SCENARIO=[A-Z_]+:FAIL|DIAGNOSTIC=[A-Za-z0-9_.$]+(?:(?::| at dev\.udak\.[A-Za-z0-9_.$]+:)[0-9]+)?)')
                        result['safe_diagnostics'] = [line for line in log.read_text(errors='replace').splitlines()
                                                      if safe.fullmatch(line)][:12]
                    raise
                result['steps'].append(proof)
                if not proof['child_reaped'] or not proof['process_group_quiesced']:
                    raise ValueError('Owned test process remained active')
                return (work / (name + '.output')).read_text()

            step('core-smoke', ['/usr/bin/env', '_JAVA_OPTIONS=-Xmx256m -XX:MaxMetaspaceSize=128m -XX:ActiveProcessorCount=2', './tools/run-core-smoke.sh'])
            old_fetch, old_step = phase3.fetch, guard.run_step
            try:
                phase3.fetch, guard.run_step = h.fetch, h.step
                classpath, _, deps, legacy_compile = phase3.build(work)
            finally:
                phase3.fetch, guard.run_step = old_fetch, old_step
            result['steps'].append({'name': 'compile-legacy', **{k: v for k, v in legacy_compile.items() if k != 'name'}})
            result['frozen_legacy_artifacts'] = len(deps['artifacts'])
            source_modules = set(p4.MODULES) | {'tx-trace-spring'}
            paths = [str(ROOT / path) for path in result['input_sha512']
                     if path.split('/')[0] in source_modules and path.endswith('.java')]
            step('compile-trace', base.JAVAC + ['-cp', classpath, '-d', str(work / 'classes'), *sorted(paths)])
            def java(class_name):
                return base.JAVA + ['-cp', classpath, class_name]

            result['contract_assertions'] = {}
            for name, main_class in CONTRACTS.items():
                output = step(name, java(main_class))
                match = re.search(r'(?:assertions|checks)\s*[:=]\s*([1-9][0-9]*)', output)
                if not match:
                    raise ValueError('Regression assertion count missing')
                result['contract_assertions'][name] = int(match[1])
            output = step('legacy-h2-regression', java('dev.udak.compat.LegacyCompatibilityTest'), timeout=60)
            result['legacy_h2'] = phase3.protocol('H2', output, 0)
            if result['legacy_h2']['status'] != 'PASS':
                raise ValueError('Legacy H2 checks incomplete')
            output = step('guard-h2-regression', java('dev.udak.consistency.Phase4TransactionTest'), timeout=60)
            result['guard_h2'] = p4.protocol(output, 0)
            result['trace'] = trace_protocol(step('trace-h2', java('dev.udak.trace.spring.TransactionTraceIntegrationTest'), timeout=60))
            if tuple(s['name'] for s in result['steps']) != STAGES or result['input_sha512'] != inputs():
                raise ValueError('Validation inputs or step inventory changed')
            result['documentation'] = guard.verify_documents()
        if cleanup.get('status') != 'PASS' or cleanup.get('temporary_directory_remaining') is not False:
            raise ValueError('Cleanup incomplete')
        result['status'] = 'PASS'
    except Exception as failure:
        result['failure_type'] = type(failure).__name__
        if isinstance(failure, RuntimeError):
            try:
                detail = json.loads(str(failure))
                if isinstance(detail, dict) and detail.get('name') in set(STAGES) | {'compile-phase3', 'compile-observe-jdk-only'}:
                    result['failed_step'] = detail
            except ValueError:
                pass
    finally:
        signal.alarm(0)
        result['elapsed_seconds'] = round(time.monotonic() - started, 3)
        report(REPORT, result)
    print(json.dumps({k: v for k, v in result.items() if k != 'input_sha512'}))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
