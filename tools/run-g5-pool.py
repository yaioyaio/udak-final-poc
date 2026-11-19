#!/usr/bin/env python3
"""RELEASE-009: bounded HikariCP functional checks on two owned native databases."""
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import signal
import sys
import zipfile
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('pool_guard', ROOT / 'tools/run-schema-regression.py')
schema = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schema)
h, native = schema.h, schema.native

REPORT = 'evidence/PRODUCT-G5-POOL.json'
SOURCE = 'tools/release-pool/PoolFixture.java'
INPUTS = ('tools/run-g5-pool.py', SOURCE, 'tools/run-schema-regression.py', 'tools/schema-native.py',
          'tools/run-sql-inventory.py', 'tools/run-phase6.py', 'tools/run-phase5.py', 'tools/run-phase4.py',
          'tools/run-phase3.py', 'tools/run-phase2.py', 'tools/run-phase1.py', 'tools/run-g2.py',
          'tools/g2-dependencies.json', 'tools/phase3-dependencies.json')
VERSIONS = {'POSTGRESQL': '17.11', 'MYSQL': '8.0.46'}
SCENARIOS = ('ROLLBACK_RESET_REUSE', 'PRECOMMIT_REPLACEMENT')
HIKARI = 'com.zaxxer:HikariCP:6.3.3'
SLF4J = 'org.slf4j:slf4j-api:2.0.18'
HIKARI_HASHES = {
    'jar': '3492605dca124c4fb7a06111e6b1a92408c796d7f4fc3991395c27f060bb45a10edc5f3dacf1563ba7f982fd2589a140fef6f6fe97d0df666a9e56d3dbe10527',
    'pom': 'fda9639bd05a37804950d731254770fa39ef0e636f92457338cf42e50e1afd5b64b90575c977b824f6657127f5a7cff35e88805c553fb7a5b888124a91f9a3d1',
}
LIMITS = {'wall_seconds': 240, 'profiles_in_parallel': 1, 'pool_size': 1, 'observer_connections': 1,
          'application_retries': 0, 'borrow_timeout_ms': 3000, 'validation_timeout_ms': 1500,
          'socket_timeout_ms': 5000, 'java_seconds_per_profile': 30, 'java_heap_mib': 256,
          'java_active_cpus': 2, 'workspace_bytes': 1024**3, 'workspace_entries': 5000}


def input_hashes():
    return h.hashes(INPUTS)


def require(condition):
    if not condition:
        raise ValueError('Pool fixture evidence mismatch')


def fetch_artifact(coordinate, pins, algorithm):
    group, name, version = coordinate.split(':')
    base = 'https://repo.maven.apache.org/maven2/' + group.replace('.', '/') + '/' + name + '/' + version
    files = {}
    for ext in ('jar', 'pom'):
        url = f'{base}/{name}-{version}.{ext}'
        raw = h.fetch(url, 256 * 1024)
        require(hashlib.sha512(raw).hexdigest() == pins[ext])
        published = h.fetch(url + '.' + algorithm, 1024).decode('ascii').split()[0]
        require(hashlib.new(algorithm, raw).hexdigest() == published)
        files[ext] = raw
    return files


def pool_dependencies(work):
    manifest = json.loads((ROOT / 'tools/phase3-dependencies.json').read_text())
    slf = next(a for a in manifest['artifacts'] if a['coordinate'] == SLF4J)
    require(slf['effective_licenses'] == [{'name': 'MIT', 'url': 'https://opensource.org/license/mit'}])
    jars, evidence = [], []
    for coordinate, pins, algorithm, license_id in (
            (HIKARI, HIKARI_HASHES, 'sha1', 'Apache-2.0'),
            (SLF4J, {ext: slf[ext + '_sha512'] for ext in ('jar', 'pom')}, 'sha512', 'MIT')):
        files = fetch_artifact(coordinate, pins, algorithm)
        with zipfile.ZipFile(io.BytesIO(files['jar'])) as archive:
            version = coordinate.split(':')[2]
            require(f'Bundle-Version: {version}' in archive.read('META-INF/MANIFEST.MF').decode().splitlines())
            if coordinate == SLF4J:
                name = 'META-INF/LICENSE.txt'
                require(hashlib.sha512(archive.read(name)).hexdigest() == slf['license_entries'][name])
            else:
                pom = ET.fromstring(files['pom'])
                namespace = {'m': 'http://maven.apache.org/POM/4.0.0'}
                require(pom.findtext('m:licenses/m:license/m:url', namespaces=namespace)
                        == 'https://www.apache.org/licenses/LICENSE-2.0.txt')
        path = work / (coordinate.split(':')[1] + '.jar')
        path.write_bytes(files['jar'])
        jars.append(path)
        evidence.append({'coordinate': coordinate, 'jar_sha512': pins['jar'], 'pom_sha512': pins['pom'],
                         'published_checksum_algorithm': algorithm, 'license': license_id})
    return jars, evidence


def run_database(profile, work, classpath, result):
    name = 'pool-' + profile.lower()
    with native.instance(profile.lower(), work) as (port, password, runtime):
        result['native_runtime'] = runtime
        require(runtime['version'] == VERSIONS[profile] and runtime['loopback_listener_owned'] is True)
        command = schema.base.JAVA + ['-cp', classpath, 'PoolFixture', profile, str(port)]
        try:
            step, path = native.run_private(name, command, work, LIMITS['java_seconds_per_profile'],
                                            (password + '\n').encode('ascii'))
        except RuntimeError:
            output = work / (name + '.output')
            if output.is_file() and output.stat().st_size <= 80:
                match = re.fullmatch(rb'POOL FAIL (INPUT|SETUP|ROLLBACK_RESET_REUSE|PRECOMMIT_LOSS|TERMINATE_OWNED|'
                                     rb'BROKEN_CONNECTION|REPLACEMENT|CLEANUP)\n', output.read_bytes())
                if match:
                    result['failed_stage'] = match[1].decode('ascii')
            raise
        require(path.stat().st_size < 256)
        lines = path.read_bytes().decode('ascii').splitlines()
        require(lines == [f'POOL PASS {profile} {VERSIONS[profile]} {schema.PROFILES[profile]}',
                          *(scenario + ' PASS' for scenario in SCENARIOS)])
        result.update(step=step, server_version=VERSIONS[profile], driver_version=schema.PROFILES[profile],
                      scenarios={scenario: 'PASS' for scenario in SCENARIOS})
    if not (runtime['server_stopped'] is True and runtime['process_groups_quiesced'] is True):
        raise native.PreservationRequired('Native fixture shutdown unconfirmed')
    result['status'] = 'PASS'


def run(result):
    lock_dir = ROOT / '.git/udak-g2-managed'
    lock_dir.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(lock_dir / 'RUN.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result['input_sha512'] = input_hashes()
        with schema.workspace() as (work, cleanup):
            result['cleanup'] = cleanup
            jvm = '_JAVA_OPTIONS=-Xmx256m -XX:MaxMetaspaceSize=128m -XX:ActiveProcessorCount=2'
            result['core_smoke'] = h.step('core-smoke', ['/usr/bin/env', jvm, './tools/run-core-smoke.sh'], work)
            jdbc, result['jdbc_dependencies'] = schema.pinned_drivers(work)
            pool_jars, result['pool_dependencies'] = pool_dependencies(work)
            classes = work / 'classes'
            classes.mkdir()
            jars = os.pathsep.join(map(str, [*jdbc, *pool_jars]))
            command = schema.base.JAVAC + ['-cp', jars, '-d', str(classes), str(ROOT / SOURCE)]
            result['compile'], _ = native.run_private('compile-pool', command, work, 30)
            classpath = str(classes) + os.pathsep + jars
            for profile in VERSIONS:
                item = {'status': 'FAIL'}
                result['profiles'][profile] = item
                run_database(profile, work, classpath, item)
        require(cleanup.get('status') == 'PASS' and cleanup.get('remaining') is False)
        require(result['input_sha512'] == input_hashes())
        result.update(status='PASS', scenario_count=len(SCENARIOS) * len(VERSIONS))
        h.save(REPORT, result)


def main():
    if len(sys.argv) != 1:
        return 2
    for event in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT):
        signal.signal(event, schema.interrupted)
    result = {'schema_version': 1, 'requirement': 'RELEASE-009', 'status': 'FAIL',
              'started_at_utc': datetime.now(timezone.utc).isoformat(), 'pool': HIKARI,
              'limits': LIMITS, 'profiles': {}, 'docker_containers_started': 0,
              'not_run': ['SQL Server', 'Oracle', 'unknown commit outcome', 'production failover', 'performance/load']}
    signal.alarm(LIMITS['wall_seconds'])
    try:
        run(result)
    except Exception as error:
        result.update(status='FAIL', failure_type=type(error).__name__)
        folder = ROOT / '.git/udak-product-g5'
        folder.mkdir(parents=True, exist_ok=True)
        name = 'pool-failed-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.json'
        h.p5.p4.save(folder / name, result)
    finally:
        signal.alarm(0)
    print(json.dumps({'status': result['status'], 'scenario_count': result.get('scenario_count', 0),
                      'failed_stages': [p['failed_stage'] for p in result['profiles'].values() if 'failed_stage' in p],
                      'failure_type': result.get('failure_type')}))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
