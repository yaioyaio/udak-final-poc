"""Single-use, loopback-only native providers for the schema regression fixture."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time


MIB = 1024**2
DATA_LIMIT = 768 * MIB
RSS_LIMIT = 1024 * MIB
FILE_LIMIT = 12000
STARTUP_SECONDS = 60
SERVER_SECONDS = 150
PG = Path('/opt/homebrew/opt/postgresql@17/bin')
MYSQL = Path('/opt/homebrew/opt/mysql@8.0/bin')
_ACTIVE = threading.Lock()

# exec preserves the owned session leader. Apply limits without a preexec_fn
# (unsafe when the native server and the Java client have concurrent monitors).
_LIMITED_EXEC = """
import os, resource, sys
for kind, limit in [(resource.RLIMIT_CPU,90),(resource.RLIMIT_FSIZE,268435456),(resource.RLIMIT_CORE,0)]:
    resource.setrlimit(kind,(limit,limit))
os.umask(0o077)
os.execvp(sys.argv[1],sys.argv[1:])
"""


class PreservationRequired(RuntimeError):
    """The caller must retain the scratch directory for ownership review."""


def _private_dir(path):
    path = Path(path)
    info = path.lstat()
    if (path != path.resolve() or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError('Private native workspace required')
    return path


def _environment(work):
    java = Path(shutil.which('java') or '/usr/bin/java').resolve()
    return {
        'PATH': f'{java.parent}:/usr/bin:/bin:/usr/sbin:/sbin',
        'JAVA_HOME': str(java.parent.parent), 'TMPDIR': str(work),
        'LANG': 'C', 'LC_ALL': 'C', 'MYSQL_HISTFILE': '/dev/null',
        'PGPASSFILE': str(work / 'unused-login-directory' / 'no-file'), 'PGSSLMODE': 'disable',
        # MySQL 8.0 clients look for a login file even with --no-defaults.
        'MYSQL_TEST_LOGIN_FILE': str(work / 'unused-login-directory' / 'no-file'),
    }


def _system(command, work, timeout=3):
    try:
        return subprocess.run(command, env=_environment(work), cwd=work,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('Native inspection unavailable') from None


def _process_table(work):
    probe = _system(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,rss='], work)
    if probe.returncode or not 0 < len(probe.stdout) <= 2 * MIB:
        raise RuntimeError('Native process inventory unavailable')
    table = {}
    for line in probe.stdout.splitlines():
        pid, parent, group, rss = map(int, line.split())
        table[pid] = (parent, group, rss * 1024)
    return table


def _disk_usage(work):
    size = count = 0
    directories = [work]
    while directories:
        try:
            entries = os.scandir(directories.pop())
        except FileNotFoundError:
            continue
        with entries:
            for entry in entries:
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                count += 1
                if stat.S_ISDIR(info.st_mode):
                    directories.append(entry.path)
                elif stat.S_ISREG(info.st_mode):
                    size += info.st_size
                elif not stat.S_ISSOCK(info.st_mode):
                    raise PreservationRequired('Unexpected native scratch entry')
                if size > DATA_LIMIT or count > FILE_LIMIT:
                    raise RuntimeError('Native scratch limit exceeded')
    return size


class _Child:
    def __init__(self, command, work, timeout, stdout, input_data, data_root):
        self.work = work
        self.data_root = data_root
        self.deadline = time.monotonic() + timeout
        self.done = threading.Event()
        self.failed = None
        self.seen = set()
        self.peak_rss = self.peak_bytes = 0
        self.process = subprocess.Popen(
            [sys.executable, '-I', '-S', '-c', _LIMITED_EXEC, *map(str, command)],
            cwd=work, env=_environment(work), start_new_session=True,
            stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
            stdout=stdout, stderr=subprocess.DEVNULL)
        self.watcher = threading.Thread(target=self._watch, daemon=True)
        self.watcher.start()

    def _sample(self):
        table = _process_table(self.work)
        owned = {pid for pid, (_, group, _) in table.items() if group == self.process.pid}
        parents = owned
        while parents:
            parents = {pid for pid, (parent, _, _) in table.items()
                       if parent in parents and pid not in owned}
            owned.update(parents)
        self.seen.update(owned)
        rss = sum(table[pid][2] for pid in owned)
        self.peak_rss = max(self.peak_rss, rss)
        if rss > RSS_LIMIT or len(owned) > 48:
            raise RuntimeError('Native process resource limit exceeded')
        if self.data_root is not None:
            self.peak_bytes = max(self.peak_bytes, _disk_usage(self.data_root))

    def _signal_group(self, signum):
        try:
            os.killpg(self.process.pid, signum)
        except ProcessLookupError:
            pass

    def _watch(self):
        try:
            while not self.done.is_set():
                if time.monotonic() >= self.deadline:
                    raise RuntimeError('Private process deadline exceeded')
                self._sample()
                self.done.wait(0.75)
        except Exception as error:
            self.failed = error
            self._signal_group(signal.SIGTERM)
            if not self.done.wait(3):
                self._signal_group(signal.SIGKILL)

    def check(self):
        if self.failed:
            raise self.failed
        if self.process.poll() is not None:
            raise RuntimeError('Native server exited before fixture completion')

    def close(self, stop_signal):
        try:
            try:
                self._stop_and_confirm(stop_signal)
            except (KeyboardInterrupt, InterruptedError):
                self._stop_and_confirm(stop_signal)
                raise
        except PreservationRequired:
            raise
        except BaseException:
            if not getattr(self, 'quiesced', False):
                raise PreservationRequired('Native shutdown interrupted or unconfirmed') from None
            raise
        if self.failed:
            raise self.failed

    def _stop_and_confirm(self, stop_signal):
        self.done.set()
        self.watcher.join(timeout=5)
        if self.watcher.is_alive():
            raise PreservationRequired('Native resource monitor shutdown unconfirmed')
        if self.process.poll() is None:
            self.process.send_signal(stop_signal)
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self._signal_group(signal.SIGKILL)
                try:
                    self.process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    raise PreservationRequired('Native process shutdown unconfirmed') from None
        # PostgreSQL children may lead their own groups. Signal only our group,
        # and require all observed descendants to exit before reclaiming data.
        deadline = time.monotonic() + 4
        while True:
            try:
                table = _process_table(self.work)
            except Exception:
                raise PreservationRequired('Native shutdown inventory unavailable') from None
            if not any(pid in self.seen or group == self.process.pid
                       for pid, (_, group, _) in table.items()):
                break
            if time.monotonic() >= deadline:
                raise PreservationRequired('Native descendants remain unconfirmed')
            time.sleep(0.2)
        self.quiesced = True


def _run(name, command, work, timeout, input_data, stream, data_root=None):
    if not 0 < timeout <= 180 or (input_data is not None and
            (not isinstance(input_data, bytes) or len(input_data) > 4096)):
        raise ValueError('Private step limits denied')
    child = _Child(command, work, timeout, stream, input_data, data_root)
    try:
        if child.process.stdin is not None:
            try:
                child.process.stdin.write(input_data)
            except BrokenPipeError:
                pass
            finally:
                try:
                    child.process.stdin.close()
                except BrokenPipeError:
                    pass
        try:
            code = child.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f'{name} deadline exceeded') from None
    finally:
        child.close(signal.SIGTERM)
    if code:
        raise RuntimeError(f'{name} failed (exit {code})')
    return {'name': name, 'status': 'PASS', 'exit_code': code, 'child_reaped': True,
            'process_group_quiesced': True, 'peak_rss_bytes': child.peak_rss,
            'peak_data_bytes': child.peak_bytes}


def run_private(name, command, work, timeout, input_data=None):
    """Return (safe receipt, exclusive stdout file). Caller validates stdout protocol."""
    work = _private_dir(work)
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,72}', name):
        raise ValueError('Invalid private step name')
    output = work / (name + '.output')
    with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
        receipt = _run(name, command, work, timeout, input_data, stream)
    if output.stat().st_size > MIB:
        raise ValueError('Private protocol output limit exceeded')
    return receipt, output


def _fingerprint(binary, profile, work):
    options = ['--no-defaults'] if profile == 'mysql' else []
    probe = _system([binary, *options, '--version'], work)
    pattern = rb'\bVer (8\.0\.\d+)\b' if profile == 'mysql' else rb'\(PostgreSQL\) (17\.\d+)\b'
    match = re.search(pattern, probe.stdout)
    if probe.returncode or not match:
        raise RuntimeError('Native database version outside supported fixture range')
    digest = hashlib.sha256()
    with binary.open('rb') as source:
        for chunk in iter(lambda: source.read(MIB), b''):
            digest.update(chunk)
    return {'version': match[1].decode('ascii'), 'server_sha256': digest.hexdigest()}


def _port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def _listeners(pid, work):
    probe = _system(['/usr/sbin/lsof', '-nP', '-a', '-p', str(pid), '-iTCP',
                     '-sTCP:LISTEN', '-Fpn'], work, 4)
    if probe.returncode not in (0, 1):
        raise RuntimeError('Native listener inspection failed')
    return [line[1:] for line in probe.stdout.splitlines() if line.startswith(b'n')]


def _ready(child, profile, work, port, unix_socket):
    deadline = time.monotonic() + STARTUP_SECONDS
    while time.monotonic() < deadline:
        child.check()
        if unix_socket.is_socket():
            listeners = _listeners(child.process.pid, work)
            if port is None:
                if listeners:
                    raise RuntimeError('Private bootstrap unexpectedly opened TCP')
                pidfile = work / 'mysqld.pid'
                if (pidfile.is_file() and pidfile.stat().st_size < 24
                        and pidfile.read_bytes().strip() == str(child.process.pid).encode()):
                    ping = _system([MYSQL / 'mysqladmin', '--no-defaults', '--protocol=SOCKET',
                                    f'--socket={unix_socket}', '--user=root',
                                    '--connect-timeout=1', '--silent', 'ping'], work)
                    if ping.returncode == 0:
                        return
            elif listeners == [f'127.0.0.1:{port}'.encode()]:
                if profile == 'postgresql':
                    ping = _system([PG / 'pg_isready', '-q', '-h', work, '-p', str(port),
                                    '-d', 'postgres', '-U', 'udak_fixture', '-t', '1'], work)
                    if ping.returncode == 0:
                        return
                else:
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=1) as client:
                            # The unauthenticated MySQL v10 greeting follows its 4-byte header.
                            header = client.makefile('rb')
                            with header:
                                if len(header.read(4)) == 4 and header.read(1) == b'\x0a':
                                    return
                    except (TimeoutError, ConnectionError):
                        pass
        time.sleep(0.25)
    raise RuntimeError('Owned native listener readiness deadline exceeded')


@contextmanager
def _server(command, profile, work, receipt, port, unix_socket):
    child = _Child(command, work, SERVER_SECONDS, subprocess.DEVNULL, None, work)
    try:
        _ready(child, profile, work, port, unix_socket)
        child.check()
        yield
        child.check()
    finally:
        try:
            child.close(signal.SIGINT if profile == 'postgresql' else signal.SIGTERM)
        finally:
            if getattr(child, 'quiesced', False):
                receipt['server_groups_stopped'] += 1
            receipt['peak_rss_bytes'] = max(receipt['peak_rss_bytes'], child.peak_rss)
            receipt['peak_data_bytes'] = max(receipt['peak_data_bytes'], child.peak_bytes)


def _mysql_command(work, unix_socket):
    return [MYSQL / 'mysqld', '--no-defaults', f'--basedir={MYSQL.parent}',
            f'--datadir={work / "data"}', f'--pid-file={work / "mysqld.pid"}',
            f'--socket={unix_socket}', f'--tmpdir={work}',
            '--mysqlx=OFF', '--ssl=OFF', '--auto-generate-certs=OFF',
            '--sha256-password-auto-generate-rsa-keys=OFF',
            '--caching-sha2-password-auto-generate-rsa-keys=OFF',
            '--skip-name-resolve', '--skip-log-bin', '--general-log=OFF', '--slow-query-log=OFF',
            '--performance-schema=OFF', '--log-error-verbosity=1', '--secure-file-priv=NULL',
            '--innodb-buffer-pool-size=32M', '--innodb-redo-log-capacity=16M',
            '--innodb-log-buffer-size=4M', '--max-connections=8', '--table-open-cache=32']


@contextmanager
def instance(profile, work):
    """Yield (loopback TCP port, fresh fixture password, mutable public receipt)."""
    if profile not in ('postgresql', 'mysql'):
        raise ValueError('Unknown native profile')
    work = _private_dir(work) / ('native-' + profile)
    if not _ACTIVE.acquire(blocking=False):
        raise RuntimeError('Only one native fixture may be active')
    try:
        work.mkdir(mode=0o700)
        data = work / 'data'
        data.mkdir(mode=0o700)
        unix_socket = work / 'm.sock'
        if len(os.fsencode(work / '.s.PGSQL.65535')) >= 104:
            raise ValueError('Private native socket path too long')
        if shutil.disk_usage(work).free < DATA_LIMIT:
            raise RuntimeError('Insufficient native scratch capacity')
        binary = PG / 'postgres' if profile == 'postgresql' else MYSQL / 'mysqld'
        receipt = dict(_fingerprint(binary, profile, work), profile=profile, provider='native',
                       private_directory=True, data_limit_bytes=DATA_LIMIT, rss_limit_bytes=RSS_LIMIT,
                       cpu_limit_seconds=90, startup_limit_seconds=STARTUP_SECONDS,
                       server_limit_seconds=SERVER_SECONDS, peak_data_bytes=0, peak_rss_bytes=0,
                       server_groups_stopped=0, server_stopped=False, process_groups_quiesced=False)
        password = secrets.token_hex(24)
        if profile == 'postgresql':
            initialization = _run('postgresql-initdb',
                [PG / 'initdb', '--no-locale', '-E', 'UTF8', '--auth=scram-sha-256',
                 '--username=udak_fixture', '--pwfile=/dev/stdin', '-D', data], work,
                STARTUP_SECONDS, (password + '\n').encode(), subprocess.DEVNULL, work)
            port = _port()
            command = [binary, '-D', data, '-h', '127.0.0.1', '-p', str(port), '-k', work,
                       '-c', 'max_connections=10', '-c', 'shared_buffers=16MB', '-c', 'work_mem=1MB',
                       '-c', 'ssl=off', '-c', 'logging_collector=off', '-c', 'log_statement=none',
                       '-c', 'log_min_error_statement=panic', '-c', 'autovacuum=off']
            unix_socket = work / ('.s.PGSQL.' + str(port))
        else:
            common = _mysql_command(work, unix_socket)
            initialization = _run('mysql-initialize', [*common, '--skip-networking', '--initialize-insecure'], work,
                                  STARTUP_SECONDS, None, subprocess.DEVNULL, work)
            with _server([*common, '--skip-networking'], profile, work, receipt, None, unix_socket):
                root_password = secrets.token_hex(24)
                # Only generated hexadecimal strings enter this bootstrap on a private socket.
                sql = ("ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '"
                       + root_password + "';\nCREATE DATABASE udak_fixture;\n"
                       "CREATE USER 'udak_fixture'@'127.0.0.1' IDENTIFIED WITH mysql_native_password BY '"
                       + password + "';\nGRANT ALL ON udak_fixture.* TO 'udak_fixture'@'127.0.0.1';\n")
                _run('mysql-private-bootstrap',
                     [MYSQL / 'mysql', '--no-defaults', '--protocol=SOCKET', f'--socket={unix_socket}',
                      '--user=root', '--connect-timeout=2', '--skip-reconnect', '--batch', '--silent'],
                     work, 15, sql.encode(), subprocess.DEVNULL, work)
            port = _port()
            command = [*common, '--bind-address=127.0.0.1', f'--port={port}']
        receipt['initialization'] = initialization
        groups_stopped = receipt['server_groups_stopped']
        try:
            with _server(command, profile, work, receipt, port, unix_socket):
                receipt['loopback_listener_owned'] = True
                yield port, password, receipt
        finally:
            stopped = receipt['server_groups_stopped'] == groups_stopped + 1
            receipt.update(server_stopped=stopped, process_groups_quiesced=stopped)
    finally:
        _ACTIVE.release()
