#!/usr/bin/env python3
"""RELEASE-010: verify a clean restart on the same two disposable native databases."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('restart_schema', ROOT / 'tools/run-schema-regression.py')
schema = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schema)
native, h = schema.native, schema.h
SOURCE = 'tools/release-pool/RestartFixture.java'
REPORT = 'evidence/PRODUCT-G5-RESTART.json'
INPUTS = ('tools/release-pool/run-restart.py', SOURCE, 'tools/run-schema-regression.py', 'tools/schema-native.py',
          'tools/run-sql-inventory.py', 'tools/run-phase6.py', 'tools/run-phase5.py', 'tools/run-phase4.py',
          'tools/run-phase3.py', 'tools/run-phase2.py', 'tools/run-phase1.py', 'tools/run-g2.py',
          'tools/g2-dependencies.json')
VERSIONS = {'POSTGRESQL': '17.11', 'MYSQL': '8.0.46'}
LIMITS = {'wall_seconds': 240, 'profiles_in_parallel': 1, 'application_retries': 0,
          'restart_count_per_profile': 1, 'worker_seconds': 20, 'socket_timeout_ms': 5000,
          'jvm_heap_mib': 256, 'jvm_active_cpus': 2, 'workspace_bytes': 1024**3, 'workspace_entries': 5000}


def input_hashes():
    return h.hashes(INPUTS)


def require(condition):
    if not condition:
        raise ValueError('Native restart proof incomplete')


@contextmanager
def observe_exit(profile):
    # The existing guard may escalate to SIGKILL after eight seconds. Capture its
    # Popen exit status so this check can only certify actual orderly shutdown.
    # This process owns an isolated native module and the global managed-run lock.
    original = native._Child
    exits = []
    binary = native.PG / 'postgres' if profile == 'postgresql' else native.MYSQL / 'mysqld'

    class ObservedChild(original):
        def __init__(self, command, *args, **kwargs):
            self.is_target = command[0] == binary and (
                '-D' in command if profile == 'postgresql' else '--bind-address=127.0.0.1' in command)
            super().__init__(command, *args, **kwargs)

        def close(self, stop_signal):
            super().close(stop_signal)
            if self.is_target:
                exits.append((self.process.returncode, self.quiesced))

    native._Child = ObservedChild
    try:
        yield exits
    finally:
        native._Child = original


def prove_clean_stop(receipt, exits):
    if exits != [(0, True)] or not receipt['server_stopped'] or not receipt['process_groups_quiesced']:
        raise native.PreservationRequired('Orderly native stop unconfirmed')
    receipt.update(server_exit_code=0, graceful_stop=True)


def dir_identity(path):
    try:
        stat = native._private_dir(path).stat()
    except (OSError, ValueError) as error:
        raise native.PreservationRequired('Owned native data directory unconfirmed') from error
    return stat.st_dev, stat.st_ino


def run_worker(profile, mode, port, password, work, classpath):
    name = f'restart-{profile.lower()}-{mode.lower()}'
    command = schema.base.JAVA + ['-cp', classpath, 'RestartFixture', profile, str(port), mode]
    receipt, output = native.run_private(name, command, work, LIMITS['worker_seconds'], (password + '\n').encode('ascii'))
    require(output.stat().st_size < 64 and output.read_bytes() == f'RESTART {profile} {mode} PASS\n'.encode('ascii'))
    return receipt


def restart_command(engine, workspace, port):
    if engine == 'mysql':
        sock = workspace / 'm.sock'
        command = native._mysql_command(workspace, sock) + ['--bind-address=127.0.0.1', f'--port={port}']
    else:
        sock = workspace / ('.s.PGSQL.' + str(port))
        command = [native.PG / 'postgres', '-D', workspace / 'data', '-h', '127.0.0.1', '-p', str(port),
                   '-k', workspace, '-c', 'max_connections=10', '-c', 'shared_buffers=16MB', '-c', 'work_mem=1MB',
                   '-c', 'ssl=off', '-c', 'logging_collector=off', '-c', 'log_statement=none',
                   '-c', 'log_min_error_statement=panic', '-c', 'autovacuum=off']
    return command, sock


def run_profile(profile, work, classpath, row):
    engine = profile.lower()
    directory = work / ('native-' + engine)
    data = directory / 'data'
    with observe_exit(engine) as first_exit:
        with native.instance(engine, work) as (old_port, password, first):
            row['native_runtime'] = first
            require(first['version'] == VERSIONS[profile] and first['loopback_listener_owned'] is True)
            initial_identity = (dir_identity(directory), dir_identity(data))
            row['seed_step'] = run_worker(profile, 'SEED', old_port, password, work, classpath)
    prove_clean_stop(first, first_exit)
    if initial_identity != (dir_identity(directory), dir_identity(data)):
        raise native.PreservationRequired('Native data directory identity changed')
    port = next((candidate for candidate in (native._port() for _ in range(3)) if candidate != old_port), None)
    require(port is not None)
    command, unix_socket = restart_command(engine, directory, port)
    identity = native._fingerprint(command[0], engine, directory)
    require(identity == {'version': VERSIONS[profile], 'server_sha256': first['server_sha256']})
    second = dict(identity, owned_data_directory_reused=True, fresh_loopback_port=True,
                  loopback_listener_owned=False, server_stopped=False, process_groups_quiesced=False,
                  server_groups_stopped=0, peak_rss_bytes=0, peak_data_bytes=0)
    row['restart_runtime'] = second
    with observe_exit(engine) as second_exit:
        try:
            with native._server(command, engine, directory, second, port, unix_socket):
                second['loopback_listener_owned'] = True
                row['verify_step'] = run_worker(profile, 'VERIFY', port, password, work, classpath)
        finally:
            stopped = second['server_groups_stopped'] == 1
            second.update(server_stopped=stopped, process_groups_quiesced=stopped)
    prove_clean_stop(second, second_exit)
    row.update(status='PASS', server_version=VERSIONS[profile], driver_version=schema.PROFILES[profile],
               scenarios={'GRACEFUL_RESTART': 'PASS'})


def run(result):
    lock_dir = ROOT / '.git/udak-g2-managed'
    lock_dir.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(lock_dir / 'RUN.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result['input_sha512'] = input_hashes()
        with schema.workspace() as (work, cleanup):
            result['cleanup'] = cleanup
            jars, result['jdbc_dependencies'] = schema.pinned_drivers(work)
            classes = work / 'classes'
            classes.mkdir()
            result['compile'], _ = native.run_private('compile-restart', schema.base.JAVAC +
                                                       ['-d', str(classes), str(ROOT / SOURCE)], work, 30)
            classpath = os.pathsep.join(map(str, [classes, *jars]))
            for profile in VERSIONS:
                item = {'status': 'FAIL'}
                result['profiles'][profile] = item
                run_profile(profile, work, classpath, item)
        require(cleanup.get('status') == 'PASS' and cleanup.get('remaining') is False)
        require(result['input_sha512'] == input_hashes())
        result.update(status='PASS', scenario_count=len(VERSIONS))
        h.save(REPORT, result)


def main():
    if len(sys.argv) != 1:
        return 2
    for event in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
        signal.signal(event, schema.interrupted)
    result = {'schema_version': 1, 'requirement': 'RELEASE-010', 'status': 'FAIL', 'limits': LIMITS,
              'started_at_utc': datetime.now(timezone.utc).isoformat(), 'profiles': {}, 'docker_containers_started': 0,
              'not_run': ['crash recovery', 'unknown commit outcome', 'high availability failover',
                          'SQL Server', 'Oracle', 'performance/load']}
    signal.alarm(LIMITS['wall_seconds'])
    try:
        run(result)
    except Exception as error:
        result.update(status='FAIL', failure_type=type(error).__name__)
        archive = ROOT / '.git/udak-product-g5'
        archive.mkdir(parents=True, exist_ok=True)
        h.p5.p4.save(archive / ('restart-failed-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
                                + '.json'), result)
    finally:
        signal.alarm(0)
    print(json.dumps({'status': result['status'], 'scenario_count': result.get('scenario_count', 0),
                      'failure_type': result.get('failure_type')}))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
