#!/usr/bin/env python3
"""Plan and run bounded per-query schema regressions on owned PostgreSQL/MySQL instances."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import tempfile
import time
import urllib.request

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / 'evidence/SCHEMA-REGRESSION-VALIDATION.json'
DRIVERS = 'tools/g2-dependencies.json'
PROFILES = {'POSTGRESQL': '42.7.14', 'MYSQL': '26.10.0'}
NATIVE_COORDS = {'org.postgresql:postgresql:42.7.14', 'org.checkerframework:checker-qual:3.55.1',
                 'com.mysql:mysql-connector-j:26.10.0', 'com.google.protobuf:protobuf-java:4.36.1'}
SOURCE = 'schema-regression/src/main/java/dev/udak/schema/SchemaRegressionMain.java'
HARNESS_INPUTS = ('tools/run-schema-regression.py', 'tools/schema-native.py', 'tools/schema-impact.py',
                  'tools/test-schema-impact.py', 'tools/run-g2.py', 'tools/run-phase2.py', DRIVERS, SOURCE,
                  'evidence/SQL-INVENTORY-VALIDATION.json', 'evidence/TX-TRACE-VALIDATION.json')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load('schema_guard', 'tools/run-sql-inventory.py')
h, guard = base.h, base.guard
native = load('schema_native', 'tools/schema-native.py')
g2 = load('schema_driver_verifier', 'tools/run-g2.py')


class RuntimeUnavailable(RuntimeError):
    pass


@contextmanager
def workspace():
    temporary = tempfile.TemporaryDirectory(prefix='udak-schema-', dir=Path('/tmp').resolve())
    work = Path(temporary.name).resolve()
    receipt = {}
    try:
        yield work, receipt
    except native.PreservationRequired:
        temporary._finalizer.detach()
        receipt.update(status='PRESERVED_UNKNOWN', remaining=True, preservation_id=work.name)
        raise
    finally:
        if receipt.get('status') != 'PRESERVED_UNKNOWN':
            try:
                guard.stop_child()
                inventory = h.bounded_inventory(work, 5000, 1024**3)
                sizes = [item.st_size for _, item in inventory if stat.S_ISREG(item.st_mode)]
                temporary.cleanup()
                receipt.update(status='PASS', remaining=work.exists(), files=len(sizes), bytes=sum(sizes))
            except BaseException:
                temporary._finalizer.detach()
                receipt.update(status='PRESERVED_UNKNOWN', remaining=True, preservation_id=work.name)
                raise


def input_hashes():
    return {**base.inputs(), **h.hashes(HARNESS_INPUTS)}


def pinned_drivers(work):
    manifest = json.loads((ROOT / DRIVERS).read_text())
    chosen = {'artifacts': [a for a in manifest['artifacts'] if a['coordinate'] in NATIVE_COORDS],
              'upstream_license_checks': [a for a in manifest['upstream_license_checks'] if a['coordinate'] in NATIVE_COORDS]}
    if {a['coordinate'] for a in chosen['artifacts']} != NATIVE_COORDS:
        raise ValueError('Pinned driver graph incomplete')
    licenses = {item['url'] for item in chosen['upstream_license_checks']}

    def fetch(url, maximum):
        if url.startswith('https://repo.maven.apache.org/maven2/'):
            return h.fetch(url, maximum)
        if url not in licenses or url != 'https://raw.githubusercontent.com/protocolbuffers/protobuf/v36.1/LICENSE':
            raise ValueError('License origin rejected')
        # The single upstream license mirrors the existing pinned G2 verifier. Disable proxies and redirects.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(url, timeout=12) as stream:
            raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError('License bound exceeded')
        return raw

    previous = g2.fetch
    try:
        g2.fetch = fetch
        return g2.dependencies(work, chosen)
    finally:
        g2.fetch = previous


def identifier(kind, logical_id):
    return hashlib.sha256(('udak-inventory-' + kind + '-id-v1\0' + logical_id).encode('ascii')).hexdigest()


def expected_queries():
    names = ('schema.fixture.label-by-id', 'schema.fixture.labels-ordered')
    return {identifier('query', name): identifier('test', name + '.regression') for name in names}


def select(plan):
    if plan.get('status') != 'COMPLETE' or plan.get('unresolved_queries') != [] or plan.get('coverage_reasons') != []:
        raise ValueError('Impact coverage incomplete')
    changes = plan.get('changes', [])
    if len(changes) != 1 or changes[0].get('kind') != 'WIDTH' or changes[0].get('table') != 'udak_entry' or changes[0].get('column') != 'label':
        raise ValueError('Fixture schema change mismatch')
    before, after = changes[0]['before'], changes[0]['after']
    if before['width'] != 32 or after['width'] != 64:
        raise ValueError('Actual schema widths differ from the planned migration')
    selected = expected_queries()
    rows = plan.get('affected_queries', [])
    if (len(rows) != len(selected) or any(row['framework'] != 'JDBC'
            or row['test_ids'] != [selected.get(row['query_id_hash'])] for row in rows)
            or {row['query_id_hash'] for row in rows} != selected.keys()
            or plan.get('impacted_test_ids') != sorted(selected.values())):
        raise ValueError('Affected query/test schedule mismatch')
    return sorted(selected)


def parse_protocol(output, kind, profile, selected):
    lines = output.splitlines()
    if len(lines) != 5 + len(selected) or lines[0] != kind + ' PASS':
        raise ValueError('Database protocol incomplete')
    names = ('SERVER_VERSION', 'DRIVER_VERSION', 'SERVER_RELEASE_SHA256', 'DRIVER_RELEASE_SHA256')
    patterns = (r'[0-9]{1,3}(?:\.[0-9]{1,4}){1,3}', re.escape(PROFILES[profile]), r'[a-f0-9]{64}', r'[a-f0-9]{64}')
    proof = {}
    for name, pattern, line in zip(names, patterns, lines[1:5]):
        item = re.fullmatch(name + '=(' + pattern + ')', line)
        if not item:
            raise ValueError('Database identity proof incomplete')
        proof[name.lower()] = item[1]
    queries = []
    expected = expected_queries()
    for query, line in zip(selected, lines[5:]):
        row = re.fullmatch(r'QUERY=([a-f0-9]{64}):([a-f0-9]{64}):([1-9][0-9]{0,2}):([a-f0-9]{64})', line)
        if not row or row[1] != query or row[2] != expected[query]:
            raise ValueError('Unverified or unexpected query/test result')
        queries.append({'query_id_hash': row[1], 'test_id_hash': row[2], 'assertions': int(row[3]), 'result_sha256': row[4]})
    return proof, queries


def plan_command(work):
    launcher = 'import os,runpy,sys; os.chdir(sys.argv.pop(2)); sys.argv.pop(0); runpy.run_path(sys.argv[0],run_name="__main__")'
    return [sys.executable, '-B', '-c', launcher, str(ROOT / 'tools/schema-impact.py'), str(work),
            '--base', 'base/SCHEMA-SNAPSHOT.json', '--head', 'head/SCHEMA-SNAPSHOT.json',
            '--inventory', 'head/SQL-INVENTORY.json', '--dependencies', 'head/QUERY-DEPENDENCIES.json']


def run_database(profile, work, classpath, result):
    fixture = work / ('fixture-' + profile.lower())
    fixture.mkdir(mode=0o700)
    for side in ('base', 'head'):
        (fixture / side).mkdir(mode=0o700)
    steps = result['steps']
    with native.instance(profile.lower(), work) as (port, password, runtime):
        result['native_runtime'] = runtime
        private_input = (password + '\n').encode('ascii')
        command = base.JAVA + ['-cp', classpath, 'dev.udak.schema.SchemaRegressionMain']
        args = [profile, str(port), str(fixture)]
        for mode in ('prepare', 'verify'):
            selected = []
            if mode == 'verify':
                step, plan_output = native.run_private('impact-' + profile.lower(), plan_command(fixture), work, 12)
                steps.append(step)
                plan = json.loads(plan_output.read_text())
                selected = select(plan)
                result['impact'] = plan
            step, path = native.run_private(mode + '-' + profile.lower(), command + [mode] + args + selected, work, 30, private_input)
            steps.append(step)
            identity, queries = parse_protocol(path.read_text(), mode.upper(), profile, selected)
            if mode == 'prepare':
                result['identity'] = identity
            elif result['identity'] != identity:
                raise ValueError('Engine or driver changed before query execution')
            else:
                result['queries'] = queries
        result['snapshot_sha512'] = {side: guard.digest((fixture / side / 'SCHEMA-SNAPSHOT.json').read_bytes())
                                     for side in ('base', 'head')}
    if runtime.get('server_stopped') is not True or runtime.get('process_groups_quiesced') is not True:
        raise native.PreservationRequired('Native shutdown unconfirmed')
    if runtime.get('loopback_listener_owned') is not True or runtime.get('version') != result['identity']['server_version']:
        raise ValueError('Native executable and JDBC identity differ')
    result['status'] = 'PASS'


def save(result):
    if REPORT.exists():
        old = h.p5.p4.approved_paths([str(REPORT.relative_to(ROOT))])[0][1].read_bytes()
        archive = ROOT / '.git/udak-schema-regression/previous-reports'
        archive.mkdir(parents=True, exist_ok=True)
        target = archive / (guard.digest(old) + '.json')
        if not target.exists():
            with target.open('xb') as stream:
                stream.write(old)
    h.p5.p4.save(REPORT, result)


def interrupted(_signal, _frame):
    raise InterruptedError('Schema regression interrupted')


def main():
    if sys.argv[1:]:
        print('SCHEMA_REGRESSION INVALID_ARGUMENTS')
        return 2
    for event in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
        signal.signal(event, interrupted)
    start = time.monotonic()
    result = {'schema_version': 1, 'status': 'FAIL', 'scope': 'product expansion Phase 3', 'profiles': {}, 'steps': [],
              'started_at_utc': datetime.now(timezone.utc).isoformat(), 'compile_release': 17,
              'docker_containers_started': 0, 'not_run': ['SQL Server', 'Oracle', 'production schema', 'performance/load'],
              'limits': {'wall_seconds': 300, 'workspace_bytes': 1024**3, 'workspace_entries': 5000,
                         'database_parallelism': 1, 'jvm_heap_mib': 256, 'jvm_active_cpus': 2}}
    signal.alarm(300)
    try:
        lock_parent = ROOT / '.git/udak-g2-managed'
        lock_parent.mkdir(parents=True, exist_ok=True)
        lock_path = lock_parent / 'RUN.lock'
        with os.fdopen(os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeUnavailable('Another protected DB run is active') from exc
            result['input_sha512'] = input_hashes()
            with workspace() as (work, cleanup):
                result['cleanup'] = cleanup
                steps = result['steps']
                steps.append(h.step('core-smoke', ['/usr/bin/env', '_JAVA_OPTIONS=-Xmx256m -XX:MaxMetaspaceSize=128m -XX:ActiveProcessorCount=2', './tools/run-core-smoke.sh'], work))
                steps.append(h.step('impact-contract', [sys.executable, '-B', 'tools/test-schema-impact.py'], work))
                output = (work / 'impact-contract.output').read_text()
                match = re.search(r'^Ran ([1-9][0-9]{0,3}) tests? in .*\n\nOK\n$', output, re.M)
                if not match:
                    raise ValueError('Impact contract test output incomplete')
                result['impact_tests'] = int(match[1])
                jars, result['jdbc_dependencies'] = pinned_drivers(work)
                classes = work / 'classes'
                sources = sorted(str(ROOT / path) for path in result['input_sha512'] if path == SOURCE or
                                 re.fullmatch(r'(?:observe-core|sql-inventory)/src/(?:main|test)/java/.+\.java', path))
                steps.append(h.step('compile-schema-regression', base.JAVAC + ['-d', str(classes), *sources], work))
                steps.append(h.step('inventory-regression', base.JAVA + ['-cp', str(classes), 'dev.udak.inventory.InventoryContractTest'], work))
                result['inventory_assertions'] = base.contract((work / 'inventory-regression.output').read_text(), 'INVENTORY_CONTRACT')
                cp = os.pathsep.join(map(str, [classes, *jars]))
                for profile in PROFILES:
                    profile_result = {'status': 'FAIL', 'steps': []}
                    result['profiles'][profile] = profile_result
                    run_database(profile, work, cp, profile_result)
                first, second = (result['profiles'][p]['queries'] for p in PROFILES)
                if [(q['query_id_hash'], q['result_sha256']) for q in first] != [(q['query_id_hash'], q['result_sha256']) for q in second]:
                    raise ValueError('Cross-engine fixture mapping differs')
                result['documentation'] = guard.verify_documents()
                if result['input_sha512'] != input_hashes():
                    raise ValueError('Execution inputs changed')
            if cleanup['status'] != 'PASS' or cleanup['remaining']:
                raise ValueError('Owned scratch cleanup incomplete')
        result['status'] = 'PASS'
    except Exception as error:
        result['failure_type'] = type(error).__name__
        if isinstance(error, RuntimeError):
            try:
                detail = json.loads(str(error))
                if isinstance(detail, dict) and detail.get('status') == 'FAIL' and 'exit_code' in detail:
                    result['failed_step'] = detail
            except ValueError:
                pass
    finally:
        signal.alarm(0)
        result['elapsed_seconds'] = round(time.monotonic() - start, 3)
        save(result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('input_sha512', 'jdbc_dependencies')}))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
