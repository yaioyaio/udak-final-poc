#!/usr/bin/env python3
"""Install or report the one approved local PostgreSQL A/A LaunchAgent."""
import argparse
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
import fcntl
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).resolve()
RUN_ID = 'OBSERVE-PG-BASELINE-AA-01'
LABEL = 'local.udak.observe-pg-baseline-aa-01'
APPROVED_DATE = date(2026, 11, 27)
SEOUL = ZoneInfo('Asia/Seoul')
SLOTS = tuple(time(hour, minute) for hour in (1, 2, 3) for minute in (0, 30))
WINDOW = timedelta(minutes=5)
DEADLINE = datetime.combine(APPROVED_DATE, SLOTS[-1], SEOUL) + WINDOW
SYSTEM_PATH = '/usr/bin:/bin:/usr/sbin:/sbin'
STATE = ROOT / '.git' / 'udak-pg-baseline-aa-schedule'
CLAIM = ROOT / '.git' / 'udak-product-g5' / f'{RUN_ID}.claimed'
RESULT = ROOT / 'evidence' / f'PRODUCT-G5-{RUN_ID}-RESULT.json'
RETRY = frozenset(('HOST_NOT_QUIET', 'HOST_MEMORY_PRESSURE', 'RUNNER_LOCKED'))
TERMINAL = frozenset(('APPROVAL_USED', 'RUNNER_STOPPED'))
OUTCOMES = RETRY | TERMINAL


class ScheduleError(Exception):
    """A fixed code safe to include in the schedule status."""


def local_slot(now):
    current = now.astimezone(SEOUL)
    for slot in SLOTS:
        start = datetime.combine(APPROVED_DATE, slot, SEOUL)
        if start <= current < start + WINDOW:
            return slot.strftime('%H%M')
    return None


def exists(path):
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False


def approval_used():
    return exists(CLAIM) or exists(RESULT)


def check_private(info, is_type, mode):
    if (not is_type(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != mode):
        raise ScheduleError('STATE_NOT_PRIVATE')


def private_state(create=False):
    if not (ROOT / '.git').is_dir() or (ROOT / '.git').is_symlink():
        raise ScheduleError('PRIMARY_CHECKOUT_REQUIRED')
    if create:
        STATE.mkdir(mode=0o700, exist_ok=True)
    check_private(STATE.lstat(), stat.S_ISDIR, 0o700)


@contextmanager
def state_lock():
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(STATE / 'schedule.lock', flags, 0o600), 'wb') as lock:
        check_private(os.fstat(lock.fileno()), stat.S_ISREG, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ScheduleError('SCHEDULE_LOCKED') from None
        yield


def save_once(path, data):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags, 0o600), 'wb') as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def outcome_at(slot):
    path = STATE / f'{slot}.outcome'
    if not exists(path):
        return 'INTERRUPTED' if exists(STATE / f'{slot}.started') else 'PENDING'
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), 'rb') as receipt:
        check_private(os.fstat(receipt.fileno()), stat.S_ISREG, 0o600)
        data = receipt.read(64)
    for outcome in OUTCOMES:
        if data == (outcome + '\n').encode('ascii') and exists(STATE / f'{slot}.started'):
            return outcome
    return 'INVALID_RECEIPT'


def history():
    return {slot.strftime('%H%M'): outcome_at(slot.strftime('%H%M')) for slot in SLOTS}


def job_plist(executable, java_home):
    return {
        'Label': LABEL,
        'ProgramArguments': [str(executable), '-I', '-B', str(SCRIPT), '--dispatch'],
        'WorkingDirectory': str(ROOT),
        'StartCalendarInterval': [
            {'Month': APPROVED_DATE.month, 'Day': APPROVED_DATE.day, 'Hour': slot.hour, 'Minute': slot.minute}
            # The deadline trigger removes a missed schedule and never starts the runner.
            for slot in (*SLOTS, DEADLINE.time())
        ],
        'EnvironmentVariables': {'JAVA_HOME': str(java_home), 'PATH': f'{java_home}/bin:{SYSTEM_PATH}'},
        'StandardOutPath': '/dev/null',
        'StandardErrorPath': '/dev/null',
    }


def launchctl(*args):
    return subprocess.run(['/bin/launchctl', *args], stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          timeout=10, check=False).returncode


def service_domain():
    if sys.platform != 'darwin' or os.getuid() == 0:
        raise ScheduleError('MACOS_GUI_USER_REQUIRED')
    return f'gui/{os.getuid()}'


def service_loaded():
    return launchctl('print', f'{service_domain()}/{LABEL}') == 0


def jdk_home():
    java = Path(shutil.which('java') or '/usr/bin/java').resolve()
    if java == Path('/usr/bin/java'):
        raise ScheduleError('JDK_PATH_REQUIRED')
    home = java.parent.parent
    if (':' in str(home) or not (home / 'bin/java').is_file()
            or not os.access(home / 'bin/javac', os.X_OK)):
        raise ScheduleError('JDK_PATH_REQUIRED')
    return home


def install(requested_date, now):
    domain = service_domain()
    if requested_date != APPROVED_DATE.isoformat():
        raise ScheduleError('DATE_NOT_APPROVED')
    if now >= datetime.combine(APPROVED_DATE, SLOTS[0], SEOUL):
        raise ScheduleError('INSTALL_WINDOW_CLOSED')
    for slot in SLOTS:
        scheduled = datetime.combine(APPROVED_DATE, slot, SEOUL)
        if scheduled.astimezone().replace(tzinfo=None) != scheduled.replace(tzinfo=None):
            raise ScheduleError('HOST_CLOCK_NOT_SEOUL')
    private_state(create=True)
    with state_lock():
        if approval_used():
            raise ScheduleError('APPROVAL_USED')
        plist = STATE / f'{LABEL}.plist'
        if service_loaded():
            raise ScheduleError('SERVICE_ALREADY_LOADED')
        if any(value != 'PENDING' for value in history().values()):
            raise ScheduleError('SCHEDULE_ALREADY_STARTED')
        config = plistlib.dumps(job_plist(Path(sys.executable).resolve(), jdk_home()))
        if exists(plist):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            with os.fdopen(os.open(plist, flags), 'rb') as file:
                check_private(os.fstat(file.fileno()), stat.S_ISREG, 0o600)
                if file.read(len(config) + 1) != config:
                    raise ScheduleError('CONFIG_CHANGED')
        else:
            save_once(plist, config)
        if launchctl('bootstrap', domain, str(plist)) != 0:
            raise ScheduleError('BOOTSTRAP_FAILED')
        if not service_loaded():
            raise ScheduleError('SERVICE_NOT_LOADED')


def runner_outcome(returncode, output, used):
    if used:
        return 'APPROVAL_USED'
    if returncode != 1 or len(output) > 65536:
        return 'RUNNER_STOPPED'
    try:
        payload = json.loads(output)
    except (UnicodeError, ValueError):
        return 'RUNNER_STOPPED'
    if (not isinstance(payload, dict) or payload.get('status') != 'NOT RUN'
            or payload.get('workload_run_claimed') is not False
            or payload.get('postgresql_initialized') is not False):
        return 'RUNNER_STOPPED'
    reason, cleanup = payload.get('reason'), payload.get('cleanup')
    if reason == 'BlockingIOError' and cleanup is None and payload.get('host_samples'):
        return 'RUNNER_LOCKED'
    safe_cleanup = (cleanup is None or (isinstance(cleanup, dict)
                    and cleanup.get('status') == 'PASS' and cleanup.get('remaining') is False))
    if reason in ('HOST_NOT_QUIET', 'HOST_MEMORY_PRESSURE') and safe_cleanup:
        return reason
    return 'RUNNER_STOPPED'


def run_existing():
    java_home = jdk_home()
    env = {'PATH': f'{java_home}/bin:{SYSTEM_PATH}', 'LANG': 'C', 'LC_ALL': 'C', 'JAVA_HOME': str(java_home)}
    try:
        result = subprocess.run([sys.executable, '-B', str(SCRIPT.with_name('run-pg-baseline-aa.py')), 'run'],
                                cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=320, check=False)
    except subprocess.TimeoutExpired:
        return 'APPROVAL_USED' if approval_used() else 'RUNNER_STOPPED'
    return runner_outcome(result.returncode, result.stdout, approval_used())


def dispatch(now, run=run_existing):
    slot = local_slot(now)
    if slot is None:
        return 'OUTSIDE_WINDOW'
    private_state()
    with state_lock():
        if approval_used():
            return 'APPROVAL_USED'
        states = history()
        if states[slot] != 'PENDING':
            return 'SLOT_ALREADY_RECORDED'
        if any(value not in RETRY and value != 'PENDING' for value in states.values()):
            return 'SCHEDULE_STOPPED'
        # If the clock moves backwards, a previously started later slot closes earlier slots.
        if any(key > slot and value != 'PENDING' for key, value in states.items()):
            return 'SLOT_ALREADY_PASSED'
        save_once(STATE / f'{slot}.started', b'STARTED\n')
        result = run()
        save_once(STATE / f'{slot}.outcome', (result + '\n').encode('ascii'))
        return result


def report(now):
    slots = dict.fromkeys((slot.strftime('%H%M') for slot in SLOTS), 'PENDING')
    if exists(STATE):
        private_state()
        slots = history()
    return {'label': LABEL, 'loaded': service_loaded(), 'date': APPROVED_DATE.isoformat(),
            'timezone': SEOUL.key, 'approval_used': approval_used(), 'expired': now >= DEADLINE, 'slots': slots}


def retire_due(now, outcome):
    if now >= DEADLINE or outcome in TERMINAL or outcome == 'SCHEDULE_STOPPED':
        return True
    return local_slot(now) == SLOTS[-1].strftime('%H%M') and outcome in RETRY


def retire():
    # Replacing the current process lets launchd terminate its own job during bootout.
    # The caller has already synchronized the receipt and released the scheduler lock.
    target = f'{service_domain()}/{LABEL}'
    os.execve('/bin/launchctl', ['launchctl', 'bootout', target], {'PATH': SYSTEM_PATH})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--install', action='store_true')
    modes.add_argument('--status', action='store_true')
    modes.add_argument('--dispatch', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--date')
    args = parser.parse_args()
    if not args.install and args.date is not None:
        parser.error('--date requires --install')
    os.umask(0o077)
    now = datetime.now(SEOUL)
    try:
        if args.install:
            install(args.date, now)
        if args.dispatch:
            service_domain()
            if os.getppid() != 1:
                raise ScheduleError('LAUNCHD_REQUIRED')
            if local_slot(now) is not None and not service_loaded():
                raise ScheduleError('SERVICE_NOT_LOADED')
            now = datetime.now(SEOUL)
            outcome = dispatch(now)
            if retire_due(now, outcome):
                retire()
            status = {'status': outcome}
        else:
            status = report(now)
        print(json.dumps(status, sort_keys=True))
        return 0
    except ScheduleError as error:
        print(json.dumps({'status': str(error)}))
    except (OSError, subprocess.SubprocessError):
        print(json.dumps({'status': 'SCHEDULE_UNAVAILABLE'}))
    return 1


if __name__ == '__main__':
    sys.exit(main())
