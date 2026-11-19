#!/usr/bin/env python3
"""RELEASE-025 guarded, single-use trial on a dedicated native Linux SQL Server host."""
from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import time
from urllib.parse import urlencode

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BASE = 'tools/release-provider/'
host = load('sqlserver_host', BASE + 'check-sqlserver-host.py')
pool = load('sqlserver_pool', 'tools/run-g5-pool.py')
managed = load('sqlserver_managed', 'tools/run-managed-g2.py')
schema, native, h = pool.schema, pool.native, pool.h
SOURCE = BASE + 'SqlServerG5Fixture.java'
GUARD = 'consistency-core/src/main/java/dev/udak/consistency/TransactionGuard.java'
APPROVAL = 'evidence/PRODUCT-G5-SQLSERVER-APPROVAL.json'
REPORT = 'evidence/PRODUCT-G5-SQLSERVER.json'
DRIVER = 'com.microsoft.sqlserver:mssql-jdbc:13.6.2.jre11'
DRIVER_VERSION = '13.6.2.0'
HOST_PRIVATE = Path('/var/lib/udak-sqlserver-g5')
LIMITS = {'wall_seconds': 600, 'startup_seconds': 70, 'active_instances': 1, 'instance_cpus': 2,
          'instance_memory_mib': 4096, 'instance_pids': 512, 'persistent_writable_bytes': 4 * 1024**3,
          'workload_starts': 48, 'max_in_flight': 2, 'max_starts_per_second': 4,
          'min_spacing_ns': 250_000_000, 'instance_crashes': 1, 'clean_restarts': 1,
          'automatic_retries': 0, 'container_logging': 'none'}
CHECKS = ('native_host', 'dedicated_empty_baseline', 'pinned_image', 'quota_before_start',
          'cgroup_limits', 'loopback_only', 'functional', 'commit_ack_loss', 'seed_disconnect',
          'crash_recovery', 'clean_restart', 'owned_cleanup')


class Gate(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise Gate(reason)


def sources():
    return tuple(dict.fromkeys((*pool.INPUTS, BASE + 'run-sqlserver-g5.py', BASE + 'check-sqlserver-host.py',
                                SOURCE, GUARD, 'tools/run-managed-g2.py', 'tools/g2-docker.py',
                                'tools/g2-server-images.json', 'tools/schema-impact.py')))


def get_pin():
    pin = host.sqlserver_pin()
    require(pin['internal_port'] == 1433, 'SQLSERVER_PIN')
    return pin


def expected_approval():
    return {'schema_version': 1, 'requirement': 'RELEASE-025', 'profile': 'SQLSERVER',
            'platform': 'linux/amd64', 'approval_basis': 'EXPLICIT_USER_CONFIRMATION',
            'dedicated_native_intel_or_amd_host_without_translation': True,
            'empty_local_daemon_disposable_instance_and_cleanup': True, 'accept_sqlserver_developer_eula': True,
            'authorized_runs': 1, 'image': get_pin()['image'], 'limits': LIMITS, 'input_sha512': h.hashes(sources())}


def authorized():
    try:
        file = h.p5.p4.approved_paths([APPROVAL])[0][1]
    except FileNotFoundError:
        raise Gate('APPROVAL_REQUIRED') from None
    with file.open('rb') as stream:
        data = stream.read(65537)
    require(len(data) <= 65536, 'APPROVAL_SCOPE')
    expected = canonical(expected_approval())
    require(canonical(json.loads(data)) == expected, 'APPROVAL_SCOPE')
    return hashlib.sha512(data).hexdigest()


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def private_dir(path):
    require(path.parent.resolve() == path.parent, 'PRIVATE_PATH')
    path.mkdir(mode=0o700, exist_ok=True)
    s = path.lstat()
    require(stat.S_ISDIR(s.st_mode) and s.st_uid == os.geteuid() and not s.st_mode & 0o077, 'PRIVATE_PATH')


def claim_once(digest):
    require(re.fullmatch('[a-f0-9]{128}', digest), 'APPROVAL_DIGEST')
    # The claim key is canonical so whitespace in an approval cannot grant another trial.
    key = hashlib.sha512(canonical(expected_approval())).hexdigest()
    with (HOST_PRIVATE / (key + '.claim')).open('xb') as stream:
        stream.write((digest + '\n').encode('ascii'))
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(HOST_PRIVATE, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


@contextmanager
def locked(path):
    with os.fdopen(os.open(path, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def inventory():
    # Only the existence of a foreign container matters.
    return host.docker_fields('ps', '-a', '--no-trunc', '--latest', '--format', '{{.ID}}')


def preconditions():
    failures = host.probe()
    require(not failures, failures[0] if failures else 'HOST_CHECK')
    require(not inventory(), 'DEDICATED_HOST_BASELINE')
    storage = host.docker_fields('info', '--format', '{{.Driver}} {{range .DriverStatus}}'
                                '{{if eq (index . 0) "Backing Filesystem"}}{{index . 1}}{{end}}{{end}}')
    require(storage == 'overlay2 xfs', 'STORAGE_QUOTA_PREREQUISITE')
    data_root = Path(host.docker_fields('info', '--format', '{{.DockerRootDir}}'))
    require(data_root.is_absolute() and data_root.is_dir(), 'DOCKER_DATA_ROOT')
    require(shutil.disk_usage(data_root).free >= 40 * host.GIB, 'DOCKER_DATA_DISK')
    options = subprocess.run(['findmnt', '-n', '-T', str(data_root), '-o', 'FSTYPE,OPTIONS'],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=5, check=True, text=True).stdout.split()
    require(len(options) == 2 and options[0] == 'xfs' and {'prjquota', 'pquota'}.intersection(options[1].split(',')),
            'XFS_PROJECT_QUOTA')
    # nsenter only changes the disposable child process network namespace.
    # Confirm permission before creating a daemon resource.
    subprocess.run(['/usr/bin/nsenter', '--net=/proc/self/ns/net', '--', '/bin/true'],
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=5, check=True)
    pin = get_pin()
    image = host.docker_fields('image', 'inspect', '--format', '{{.Id}} {{len .Config.Volumes}}', pin['image'])
    match = re.fullmatch(r'(sha256:[0-9a-f]{64}) 0', image)
    require(match, 'IMAGE_VOLUME_OR_IDENTITY')
    return match[1]


def compile_fixture(work):
    manifest = json.loads((ROOT / 'tools/g2-dependencies.json').read_text())
    items = [item for item in manifest['artifacts'] if item['coordinate'] == DRIVER]
    require(len(items) == 1 and not items[0]['runtime_dependencies']
            and manifest['metadata_versions']['SQLSERVER'] == DRIVER_VERSION, 'DRIVER_PIN')
    licenses = [item for item in manifest['upstream_license_checks'] if item['coordinate'] == DRIVER]
    require(len(licenses) == 1, 'DRIVER_LICENSE')
    jdbc, _ = managed.g2.dependencies(work, {'artifacts': items, 'upstream_license_checks': licenses})
    jars, _ = pool.pool_dependencies(work)
    classes = work / 'classes'
    classes.mkdir()
    cp = os.pathsep.join(map(str, [classes, *jdbc, *jars]))
    native.run_private('sqlserver-compile', schema.base.JAVAC + ['-cp', cp, '-d', str(classes),
                       str(ROOT / GUARD), str(ROOT / SOURCE)], work, 30)
    return cp


def worker(cp, mode, namespace):
    return ['/usr/bin/nsenter', '--net=' + namespace, '--'] + schema.base.JAVA + ['-cp', cp, 'SqlServerG5Fixture', mode]


def phase(work, cp, mode, frame, label, timeout, namespace):
    _, out = native.run_private(label, worker(cp, mode, namespace), work, timeout, frame)
    require(out.stat().st_size <= 128, 'FIXTURE_PROTOCOL_SIZE')
    return out.read_bytes()


def parse_functional(output):
    match = re.fullmatch(rb'SQLSERVER_G5 FUNCTIONAL PASS (48) (2) ([1-4]) ([0-9]{9,12})\n', output)
    require(match and int(match[4]) >= LIMITS['min_spacing_ns'], 'FUNCTIONAL_PROTOCOL')
    return dict(zip(('starts', 'max_in_flight', 'max_rolling_second', 'min_spacing_ns'), map(int, match.groups())))


def owned(engine, cid, run, states):
    info = engine._owned(cid, run)
    require(info and info['Profile'] == 'SQLSERVER' and info['State'] in states, 'OWNERSHIP_OR_STATE')


def action(engine, method, path, accepted, seconds=15):
    with engine._request(method, path, accepted, wall_seconds=seconds):
        pass


def seed_and_crash(engine, cid, run, cp, frame, work, namespace):
    path = work / 'seed.output'
    ready = b'SQLSERVER_G5 SEED READY\n'
    with path.open('xb') as out, path.open('rb') as stream:
        child = native._Child(worker(cp, 'SEED', namespace), work, 95, out, b'', None)
        try:
            with child.process.stdin as pipe:
                pipe.write(frame)
            deadline = time.monotonic() + 25
            while True:
                child.check()
                stream.seek(0)
                data = stream.read(128)
                if data == ready:
                    break
                require(ready.startswith(data) and time.monotonic() < deadline, 'SEED_TIMEOUT_OR_PROTOCOL')
                time.sleep(0.1)
            owned(engine, cid, run, ('running',))
            action(engine, 'POST', f'/containers/{cid}/kill?signal=SIGKILL', (204,))
            code = child.process.wait(timeout=25)
            stream.seek(0)
            require(code == 0 and stream.read(128) == ready + b'SQLSERVER_G5 SEED DISCONNECTED\n',
                    'SEED_DISCONNECT')
        finally:
            child.close(signal.SIGTERM)
        require(child.quiesced, 'SEED_CLEANUP')
    stopped(cid, 137)


def stopped(cid, code):
    require(host.docker_fields('container', 'inspect', '--format',
            '{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}} {{len .Mounts}}', cid)
            == f'exited {code} false 0', 'STOPPED_STATE')


def start(engine, cid, run, cp, password, work, label, previous, handles):
    owned(engine, cid, run, (previous,))
    action(engine, 'POST', f'/containers/{cid}/start', (204,), 20)
    owned(engine, cid, run, ('running',))
    template = ('{{.State.Pid}} {{.HostConfig.NetworkMode}} {{len .HostConfig.PortBindings}} '
                '{{len .NetworkSettings.Networks}} {{range $n,$v := .NetworkSettings.Networks}}{{$n}}{{end}}')
    identity = host.docker_fields('container', 'inspect', '--format', template, cid)
    match = re.fullmatch(r'([1-9][0-9]{0,8}) none 0 1 none', identity)
    require(match, 'LOOPBACK_NAMESPACE')
    # Pin the namespace inode throughout the JDBC process lifetime, including
    # the connection-loss observation after the server process is killed.
    fd = os.open('/proc/' + match[1] + '/ns/net', os.O_RDONLY)
    handles.callback(os.close, fd)
    require(os.fstat(fd).st_ino != os.stat('/proc/self/ns/net').st_ino and
            host.docker_fields('container', 'inspect', '--format', template, cid) == identity, 'NAMESPACE_IDENTITY')
    namespace = f'/proc/{os.getpid()}/fd/{fd}'
    subprocess.run(['/usr/bin/nsenter', '--net=' + namespace, '--', sys.executable, '-I', '-S', '-c',
                    'import socket,sys;sys.exit([name for _,name in socket.if_nameindex()] != ["lo"])'],
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=True)
    script = ('set -eu; cd /sys/fs/cgroup; read -r m <memory.max; read -r s <memory.swap.max; '
              'read -r p <pids.max; read -r q t <cpu.max; test "$m" = 4294967296 && test "$s" = 0 && '
              'test "$p" = 512 && test "$t" -gt 0 && test "$q" -eq "$((2 * t))" && printf OK')
    require(host.docker_fields('exec', cid, '/bin/sh', '-c', script) == 'OK', 'CGROUP_LIMITS')
    frame = f'1433\n{password}\n'.encode('ascii')
    result = phase(work, cp, 'READY', frame, 'ready-' + label, LIMITS['startup_seconds'], namespace)
    match = re.fullmatch(rb'SQLSERVER_G5 READY PASS (16\.0\.[0-9]{1,5}\.[0-9]{1,5})\n', result)
    require(match, 'SERVER_VERSION')
    return frame, match[1].decode('ascii'), namespace


def container_config(run, password):
    return {'Image': get_pin()['image'],
            'Env': ['ACCEPT_EULA=Y', 'MSSQL_PID=Developer', 'MSSQL_SA_PASSWORD=' + password],
            'Labels': {'dev.udak.g2.managed': 'true', 'dev.udak.g2.run': run, 'dev.udak.g2.profile': 'SQLSERVER'},
            'ExposedPorts': {'1433/tcp': {}},
            'HostConfig': {'NetworkMode': 'none', 'PortBindings': {},
                           'RestartPolicy': {'Name': 'no'}, 'Memory': 4 * host.GIB, 'MemorySwap': 4 * host.GIB,
                           'NanoCpus': 2_000_000_000, 'PidsLimit': 512, 'ShmSize': 64 * 1024**2,
                           'LogConfig': {'Type': 'none'}, 'StorageOpt': {'size': '4G'},
                           'AutoRemove': False, 'Privileged': False}}


def run_db(work, cp, image_id, result):
    require(not inventory(), 'DEDICATED_HOST_BASELINE')
    engine = managed.docker.Engine(socket_path=str(host.SOCKET))
    run = secrets.token_hex(16)
    name = 'udak-g5-sqlserver-' + run
    journal = HOST_PRIVATE / 'trial.json'
    record = {'run': run, 'phase': 'CONTAINER_CREATE_INTENT'}
    managed.save(journal, record)
    cid = None
    handles = ExitStack()
    password = 'Aa1!' + secrets.token_hex(24)
    try:
        created = engine._json('POST', '/containers/create?' + urlencode({'name': name, 'platform': 'linux/amd64'}),
                               (201,), json.dumps(container_config(run, password)).encode('ascii'))
        candidate = created.get('Id')
        require(isinstance(candidate, str) and re.fullmatch('[a-f0-9]{64}', candidate), 'CREATED_IDENTITY')
        cid = candidate
        record.update(phase='CREATED', container=cid)
        managed.save(journal, record)
        owned(engine, cid, run, ('created',))
        require(not created.get('Warnings'), 'CREATE_WARNINGS')
        fields = '{{.Image}} {{len .Mounts}} {{index .HostConfig.StorageOpt "size"}} {{.HostConfig.NetworkMode}}'
        require(host.docker_fields('container', 'inspect', '--format', fields, cid) == f'{image_id} 0 4G none',
                'PRESTART_IMAGE_MOUNTS_QUOTA')
        frame, version, ns = start(engine, cid, run, cp, password, work, 'initial', 'created', handles)
        functional = phase(work, cp, 'FUNCTIONAL', frame, 'functional', 85, ns)
        concurrency = parse_functional(functional)
        seed_and_crash(engine, cid, run, cp, frame, work, ns)
        frame, restarted_version, ns = start(engine, cid, run, cp, password, work, 'crash', 'exited', handles)
        require(restarted_version == version, 'CRASH_SERVER_IDENTITY')
        recovery = phase(work, cp, 'RECOVER', frame, 'crash-recover', 35, ns)
        require(recovery == b'SQLSERVER_G5 RECOVER PASS\n', 'CRASH_RECOVERY')
        owned(engine, cid, run, ('running',))
        engine.stop(cid, run, timeout=30)
        stopped(cid, 0)
        frame, restarted_version, ns = start(engine, cid, run, cp, password, work, 'clean', 'exited', handles)
        require(restarted_version == version, 'CLEAN_SERVER_IDENTITY')
        graceful = phase(work, cp, 'GRACEFUL', frame, 'clean-recover', 35, ns)
        require(graceful == b'SQLSERVER_G5 GRACEFUL PASS\n', 'CLEAN_RECOVERY')
        result.update(server_version=version, concurrency=concurrency, crash_exit_code=137,
                      fixture_receipts={k: v.decode('ascii').rstrip('\n') for k, v in (
                          ('functional', functional), ('crash_recover', recovery), ('clean_recover', graceful))})
    finally:
        handles.close()
        # A lost create response leaves the intent open. Never look up by name
        # and delete an object whose exact returned ID was not received.
        require(cid is not None, 'CREATE_OUTCOME_UNCONFIRMED')
        owned(engine, cid, run, ('created', 'running', 'exited'))
        engine.stop(cid, run, timeout=30)
        owned(engine, cid, run, ('created', 'exited'))
        require(host.docker_fields('container', 'inspect', '--format', '{{len .Mounts}}', cid) == '0',
                'RECLAIM_MOUNTS')
        action(engine, 'DELETE', f'/containers/{cid}?force=false&v=false', (204,))
        require(engine._owned(cid, run) is None and not inventory(), 'RECLAIM_PROOF')
        record['phase'] = 'CLOSED'
        managed.save(journal, record)


def closed_journal(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_size > 2048:
        return False
    try:
        return json.loads(path.read_bytes()).get('phase') == 'CLOSED'
    except (AttributeError, ValueError, OSError):
        return False


def publish_once(path, result):
    require(path.parent.resolve() == path.parent, 'REPORT_PATH')
    temporary = path.with_name('.sqlserver-g5-' + secrets.token_hex(16) + '.tmp')
    with temporary.open('x', encoding='ascii') as stream:
        try:
            json.dump(result, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
            # A concurrent writer cannot have its evidence replaced.
            os.link(temporary, path)
        finally:
            temporary.unlink()
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def perform(deadline, outcome):
    approval_digest = authorized()
    image = preconditions()
    private_dir(HOST_PRIVATE)
    require(managed.PRIVATE.parent.resolve() == managed.PRIVATE.parent, 'MANAGED_PATH')
    managed.PRIVATE.mkdir(mode=0o700, exist_ok=True)
    require(managed.PRIVATE.resolve() == managed.PRIVATE, 'MANAGED_PATH')
    with locked(HOST_PRIVATE / 'RUN.lock'), locked(managed.PRIVATE / 'RUN.lock'):
        journal = HOST_PRIVATE / 'trial.json'
        require(not os.path.lexists(ROOT / REPORT), 'EXISTING_REPORT')
        require(not os.path.lexists(journal) or closed_journal(journal), 'PRIOR_TRIAL_OPEN')
        require(not inventory(), 'DEDICATED_HOST_BASELINE')
        result = {'schema_version': 1, 'requirement': 'RELEASE-025', 'profile': 'SQLSERVER',
                  'platform': 'linux/amd64', 'image': get_pin()['image'], 'driver_version': DRIVER_VERSION,
                  'limits': LIMITS, 'approval_sha512': approval_digest, 'input_sha512': h.hashes(sources())}
        with schema.workspace() as (work, cleanup):
            cp = compile_fixture(work)
            require(preconditions() == image, 'HOST_CHANGED')
            require(authorized() == approval_digest, 'APPROVAL_CHANGED')
            claim_once(approval_digest)
            require(authorized() == approval_digest, 'APPROVAL_CHANGED')
            # Keep a cleanup reserve inside the wall budget. On expiry the workload
            # unwinds into its ownership-checked finalizer under the remaining time.
            def work_timeout(_signum, _frame):
                signal.signal(signal.SIGALRM, schema.interrupted)
                signal.setitimer(signal.ITIMER_REAL, max(0.001, deadline - time.monotonic()))
                raise Gate('WORK_TIMEOUT')
            signal.signal(signal.SIGALRM, work_timeout)
            signal.setitimer(signal.ITIMER_REAL, max(0.001, deadline - time.monotonic() - 70))
            outcome.update(status='FAIL', sqlserver_g5='UNCONFIRMED')
            try:
                run_db(work, cp, image, result)
            except BaseException:
                if not closed_journal(journal):
                    raise native.PreservationRequired('SQLSERVER_TRIAL_CLEANUP_UNCONFIRMED') from None
                raise
        require(cleanup.get('status') == 'PASS' and cleanup.get('remaining') is False, 'WORKSPACE_CLEANUP')
        require(result['input_sha512'] == h.hashes(sources()) and approval_digest == authorized(), 'INPUTS_CHANGED')
        result.update(status='PASS', sqlserver_g5='PASS', checks=dict.fromkeys(CHECKS, True),
                      cleanup={'status': 'PASS', 'remaining': False})
        publish_once(ROOT / REPORT, result)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args == ['--proposal']:
        approval = expected_approval()
        print(json.dumps({key: approval[key] for key in ('schema_version', 'requirement', 'profile', 'platform',
                                                        'image', 'limits', 'input_sha512')}))
        return 0
    if args not in (['--prepare'], ['--run']):
        return 2
    perform_run = args == ['--run']
    result = {'status': 'BLOCKED', 'sqlserver_g5': 'NOT RUN'}
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(sig, schema.interrupted)
    seconds = LIMITS['wall_seconds'] if perform_run else 75
    deadline = time.monotonic() + seconds
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        require(sys.platform == 'linux' and os.uname().machine == 'x86_64', 'HOST_LINUX_X86_64')
        if perform_run:
            perform(deadline, result)
            result['sqlserver_g5'] = 'PASS'
        else:
            preconditions()
        result['status'] = 'PASS'
    except (RuntimeError, ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        result['reason'] = str(error) if isinstance(error, Gate) else type(error).__name__
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    print(json.dumps(result))
    return 0 if result['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
