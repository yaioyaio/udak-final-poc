#!/usr/bin/env python3
"""RELEASE-011. Crash and lose an acknowledgement on two disposable loopback DBs."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import sys
import time
import traceback

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('failure_restart', ROOT / 'tools/release-pool/run-restart.py')
restart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restart)
schema, native, h = restart.schema, restart.native, restart.h
SOURCE = 'tools/release-failure/FailureFixture.java'
GUARD = 'consistency-core/src/main/java/dev/udak/consistency/TransactionGuard.java'
REPORT = 'evidence/PRODUCT-G5-FAILURE.json'
LIMITS = {'wall_seconds': 240, 'profiles_in_parallel': 1, 'crashes_per_profile': 1,
          'application_retries': 0, 'worker_seconds': 22, 'ready_seconds': 12,
          'jvm_heap_mib': 256, 'jvm_active_cpus': 2, 'db_processes': 48,
          'db_rss_bytes': native.RSS_LIMIT, 'db_scratch_bytes': native.DATA_LIMIT,
          'process_cpu_seconds': 90, 'workspace_bytes': 1024**3}


class ExpectedCrash(Exception):
    """Exit the normal-server context after proving intentional server death."""


def require(condition):
    if not condition:
        raise ValueError('Failure recovery assertion incomplete')


def inputs():
    return h.hashes((*restart.INPUTS, 'tools/release-failure/run-failure.py', SOURCE, GUARD))


@contextmanager
def capture_server(engine):
    original = native._Child
    servers = []
    binary = native.PG / 'postgres' if engine == 'postgresql' else native.MYSQL / 'mysqld'

    class CapturedChild(original):
        def __init__(self, command, *args, **kwargs):
            super().__init__(command, *args, **kwargs)
            if command[0] == binary and ('-D' in command if engine == 'postgresql'
                                         else '--bind-address=127.0.0.1' in command):
                servers.append(self)

    native._Child = CapturedChild
    try:
        yield servers
    finally:
        native._Child = original


def worker_command(profile, mode, port, cp):
    return schema.base.JAVA + ['-cp', cp, 'FailureFixture', profile, str(port), mode]


def message(profile, mode, outcome):
    return f'FAILURE {profile} {mode} {outcome}\n'.encode('ascii')


def bounded_message(stream):
    stream.seek(0)
    return stream.read(96)


@contextmanager
def seed_worker(profile, port, password, work, cp):
    mode = 'CRASH_SEED'
    output = work / f'{profile.lower()}-seed.output'
    with open(output, 'xb', opener=private_file) as stream, output.open('rb') as reader:
        child = native._Child(worker_command(profile, mode, port, cp), work, LIMITS['worker_seconds'],
                              stream, b'', None)
        try:
            with child.process.stdin as input_stream:
                input_stream.write((password + '\n').encode('ascii'))
            deadline = time.monotonic() + LIMITS['ready_seconds']
            while bounded_message(reader) != message(profile, mode, 'READY'):
                child.check()
                if time.monotonic() >= deadline:
                    raise RuntimeError('Uncommitted seed readiness deadline')
                time.sleep(0.05)
            child.check()
            yield child
        finally:
            child.close(signal.SIGTERM)


def private_file(path, flags):
    return os.open(path, flags | os.O_NOFOLLOW, 0o600)


def verify_worker(profile, mode, port, password, work, cp):
    name = f'{profile.lower()}-{mode.lower()}'
    receipt, output = native.run_private(name, worker_command(profile, mode, port, cp), work,
                                         LIMITS['worker_seconds'], (password + '\n').encode('ascii'))
    with output.open('rb') as stream:
        require(bounded_message(stream) == message(profile, mode, 'PASS'))
    return receipt


def owned_socket(path):
    info = path.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise native.PreservationRequired('Owned socket identity unconfirmed')
    return info.st_dev, info.st_ino


def reclaim_stale_socket(path, identity):
    try:
        current = owned_socket(path)
    except FileNotFoundError:
        return False
    if current != identity:
        raise native.PreservationRequired('Owned socket was replaced')
    path.unlink()
    return True


def crash(server, port, directory, seed):
    server.check()
    seed.check()
    pid = server.process.pid
    require(os.getpgid(pid) == pid and native._listeners(pid, directory) == [f'127.0.0.1:{port}'.encode()])
    server._sample()
    seed.check()
    server.process.kill()
    require(server.process.wait(timeout=8) == -signal.SIGKILL)
    raise ExpectedCrash()


def fresh_restart(engine, directory, port):
    command, sock = restart.restart_command(engine, directory, port)
    if engine == 'mysql':
        sock = directory / 'm2.sock'
        command = [f'--pid-file={directory / "mysqld2.pid"}' if str(arg).startswith('--pid-file=') else arg
                   for arg in native._mysql_command(directory, sock)]
        command.extend(['--bind-address=127.0.0.1', f'--port={port}'])
    return command, sock


def first_server(profile, work, cp, row):
    engine = profile.lower()
    directory = work / ('native-' + engine)
    with capture_server(engine) as servers:
        try:
            with native.instance(engine, work) as (port, password, runtime):
                row['crashed_runtime'] = runtime
                require(runtime['loopback_listener_owned'] and runtime['version'] == restart.VERSIONS[profile])
                require(len(servers) == 1)
                directory_ids = (restart.dir_identity(directory), restart.dir_identity(directory / 'data'))
                _, socket_path = restart.restart_command(engine, directory, port)
                socket_id = owned_socket(socket_path)
                with seed_worker(profile, port, password, work, cp) as seed:
                    row['uncommitted_write_observed'] = True
                    crash(servers[0], port, directory, seed)
        except ExpectedCrash:
            pass
        else:
            raise RuntimeError('Owned crash was never triggered')
    require(seed.quiesced and seed.process.returncode in (-signal.SIGTERM, 128 + signal.SIGTERM))
    require(servers[0].quiesced and servers[0].process.returncode == -signal.SIGKILL)
    require(runtime['server_stopped'] and runtime['process_groups_quiesced'])
    if directory_ids != (restart.dir_identity(directory), restart.dir_identity(directory / 'data')):
        raise native.PreservationRequired('Owned data directory identity changed')
    row['stale_owned_socket_reclaimed'] = reclaim_stale_socket(socket_path, socket_id)
    row.update(crash_signal='SIGKILL', crash_exit_code=-signal.SIGKILL, seed_process_reaped=True)
    return port, password, directory


def run_profile(profile, work, cp, row):
    engine = profile.lower()
    old_port, password, directory = first_server(profile, work, cp, row)
    port = next((value for value in (native._port() for _ in range(3)) if value != old_port), None)
    require(port is not None)
    command, unix_socket = fresh_restart(engine, directory, port)
    identity = native._fingerprint(command[0], engine, directory)
    require(identity == {'version': restart.VERSIONS[profile],
                         'server_sha256': row['crashed_runtime']['server_sha256']})
    runtime = dict(identity, owned_data_directory_reused=True, fresh_loopback_port=True,
                   loopback_listener_owned=False, server_stopped=False, process_groups_quiesced=False,
                   server_groups_stopped=0, peak_rss_bytes=0, peak_data_bytes=0)
    row['recovered_runtime'] = runtime
    with restart.observe_exit(engine) as exits:
        try:
            with native._server(command, engine, directory, runtime, port, unix_socket):
                runtime['loopback_listener_owned'] = True
                row['crash_recovery_step'] = verify_worker(profile, 'CRASH_VERIFY', port, password, work, cp)
                row['unknown_commit_step'] = verify_worker(profile, 'LOST_ACK', port, password, work, cp)
        finally:
            stopped = runtime['server_groups_stopped'] == 1
            runtime.update(server_stopped=stopped, process_groups_quiesced=stopped)
    restart.prove_clean_stop(runtime, exits)
    row.update(status='PASS', server_version=restart.VERSIONS[profile], driver_version=schema.PROFILES[profile],
               scenarios={'CRASH_RESTART': 'PASS', 'LOST_COMMIT_ACK': 'PASS'})


def run(result):
    lock_dir = ROOT / '.git/udak-g2-managed'
    lock_dir.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(lock_dir / 'RUN.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result['input_sha512'] = inputs()
        with schema.workspace() as (work, cleanup):
            result['cleanup'] = cleanup
            jars, result['jdbc_dependencies'] = schema.pinned_drivers(work)
            classes = work / 'classes'
            classes.mkdir()
            result['compile'], _ = native.run_private('compile-recovery', schema.base.JAVAC +
                ['-d', str(classes), str(ROOT / GUARD), str(ROOT / SOURCE)], work, 30)
            cp = os.pathsep.join(map(str, (classes, *jars)))
            for profile in restart.VERSIONS:
                row = result['profiles'][profile] = {'status': 'FAIL'}
                run_profile(profile, work, cp, row)
        require(cleanup.get('status') == 'PASS' and cleanup.get('remaining') is False)
        require(result['input_sha512'] == inputs())
        result.update(status='PASS', scenario_count=2 * len(restart.VERSIONS))
        h.save(REPORT, result)


def main():
    if len(sys.argv) != 1:
        return 2
    for event in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
        signal.signal(event, schema.interrupted)
    result = {'schema_version': 1, 'requirement': 'RELEASE-011', 'status': 'FAIL', 'limits': LIMITS,
              'started_at_utc': datetime.now(timezone.utc).isoformat(), 'profiles': {}, 'docker_containers_started': 0}
    signal.alarm(LIMITS['wall_seconds'])
    try:
        run(result)
    except Exception as error:
        archive = ROOT / '.git/udak-product-g5'
        archive.mkdir(parents=True, exist_ok=True)
        frame = traceback.extract_tb(error.__traceback__)[-1]
        result.update(status='FAIL', failure_type=type(error).__name__,
                      failure_location=f'{Path(frame.filename).name}:{frame.name}:{frame.lineno}')
        h.p5.p4.save(archive / ('failure-recovery-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
                               + '.json'), result)
    finally:
        signal.alarm(0)
    print(json.dumps({'status': result['status'], 'scenario_count': result.get('scenario_count', 0),
                      'failure_type': result.get('failure_type')}))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
