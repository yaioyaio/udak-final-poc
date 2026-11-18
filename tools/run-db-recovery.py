#!/usr/bin/env python3
"""Validate JDBC cancellation and pre-commit recovery on owned, bounded DB fixtures."""
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / 'evidence/DB-RECOVERY-VALIDATION.json'
AUDIT = ROOT / '.git/udak-db-recovery'
SOURCE = 'db-recovery/src/main/java/dev/udak/recovery/DatabaseRecoveryMain.java'
INPUTS = ('tools/run-db-recovery.py', 'tools/test-db-recovery.py', SOURCE)
SCENARIOS = ('JDBC_CANCEL', 'JDBC_TIMEOUT', 'SESSION_LOSS')
WALL_SECONDS = 300
JAVA_SECONDS = 30

spec = importlib.util.spec_from_file_location('recovery_parent', ROOT / 'tools/run-schema-regression.py')
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)
h, guard, native = prior.h, prior.guard, prior.native

OBSERVATIONS = {
    'POSTGRESQL': {
        'JDBC_CANCEL': {'57014'}, 'JDBC_TIMEOUT': {'57014'},
        'SESSION_LOSS': {'57P01', '08006', '08003'},
    },
    'MYSQL': {
        'JDBC_CANCEL': {'70100', 'NONE'}, 'JDBC_TIMEOUT': {'S1T00', '70100', 'NONE'},
        'SESSION_LOSS': {'08S01', '08003', '08006'},
    },
}
MYSQL_DRIVER_EXCEPTIONS = {'JDBC_CANCEL': 'MySQLStatementCancelledException', 'JDBC_TIMEOUT': 'MySQLTimeoutException'}
BOOLEAN = r'true|false'
RESULT = re.compile(
    r'RECOVERY_RESULT profile=(?P<profile>POSTGRESQL|MYSQL) scenario=(?P<scenario>[A-Z_]+) status=PASS'
    r' sqlstate=(?P<sqlstate>[A-Z0-9]{5}|NONE) exception=(?P<exception>[A-Za-z][A-Za-z0-9]{0,63})'
    rf' blocked_observed=(?P<blocked_observed>{BOOLEAN})'
    rf' statement_gone_while_blocked=(?P<statement_gone_while_blocked>{BOOLEAN})'
    rf' failed_write_absent=(?P<failed_write_absent>{BOOLEAN})'
    r' transaction_state=(?P<transaction_state>ABORTED|ACTIVE|DISCONNECTED)'
    rf' rollback_verified=(?P<rollback_verified>{BOOLEAN}) session_reused=(?P<session_reused>{BOOLEAN})'
    rf' new_session_verified=(?P<new_session_verified>{BOOLEAN}) followup_committed=(?P<followup_committed>{BOOLEAN})'
    r' assertions=(?P<assertions>[1-9][0-9]{0,2})'
)
FAILURE = re.compile(
    r'RECOVERY_ERROR profile=(?P<profile>POSTGRESQL|MYSQL) scenario=(?P<scenario>[A-Z_]{1,24})'
    r' stage=(?P<stage>[A-Za-z0-9_-]{1,60}) sqlstate=(?P<sqlstate>[A-Z0-9]{5}|NONE)'
    r' exception=(?P<exception>[A-Za-z][A-Za-z0-9]{0,63})'
)


def input_hashes():
    return {**prior.input_hashes(), **h.hashes(INPUTS)}


def protocol_text(path):
    if path.stat().st_size > 4096:
        raise ValueError('JDBC fixture protocol exceeded its bound')
    return path.read_text(encoding='ascii')


def parse_protocol(output, profile):
    lines = output.splitlines()
    if len(lines) != 1 + len(SCENARIOS):
        raise ValueError('Incomplete JDBC fixture results')
    header = re.fullmatch(r'RECOVERY_VERSION profile=(POSTGRESQL|MYSQL) database=([0-9]{1,3}\.[0-9]{1,3}(?:\.[0-9]{1,3})?)'
                          r' driver=([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})', lines[0])
    if not header or header[1] != profile or header[3] != prior.PROFILES[profile]:
        raise ValueError('Runtime JDBC identity differs from the pinned profile')
    proof = []
    for scenario, line in zip(SCENARIOS, lines[1:]):
        match = RESULT.fullmatch(line)
        if not match or (match['profile'], match['scenario']) != (profile, scenario):
            raise ValueError('Missing, duplicate or unexpected JDBC scenario')
        row = match.groupdict()
        loss = scenario == 'SESSION_LOSS'
        transaction = 'DISCONNECTED' if loss else {'POSTGRESQL': 'ABORTED', 'MYSQL': 'ACTIVE'}[profile]
        expected = dict(blocked_observed=not loss, statement_gone_while_blocked=not loss,
                        failed_write_absent=True, rollback_verified=True, session_reused=not loss,
                        new_session_verified=loss, followup_committed=True)
        driver_signal = row['sqlstate'] in {'S1T00', 'NONE'}
        if driver_signal and row['exception'] != MYSQL_DRIVER_EXCEPTIONS.get(scenario):
            raise ValueError('Unrecognized driver cancellation or timeout type')
        if (row['sqlstate'] not in OBSERVATIONS[profile][scenario] or row['transaction_state'] != transaction
                or any(row[field] != str(value).lower() for field, value in expected.items())):
            raise ValueError('JDBC cancellation or recovery observation did not pass')
        proof.append({**row, **expected, 'assertions': int(row['assertions'])})
    return {'server_version': header[2], 'driver_version': header[3], 'scenarios': proof}


def run_database(profile, work, classpath, result):
    step_name = 'jdbc-recovery-' + profile.lower()
    with native.instance(profile.lower(), work) as (port, password, runtime):
        result['native_runtime'] = runtime
        command = prior.base.JAVA + ['-cp', classpath, 'dev.udak.recovery.DatabaseRecoveryMain', profile, str(port)]
        try:
            step, path = native.run_private(step_name, command, work, JAVA_SECONDS, (password + '\n').encode('ascii'))
        except RuntimeError:
            path = work / (step_name + '.output')
            if path.is_file():
                try:
                    lines = protocol_text(path).splitlines()
                    match = FAILURE.fullmatch(lines[-1]) if lines else None
                    if match and match['profile'] == profile:
                        result['failure'] = match.groupdict()
                except (ValueError, OSError):
                    pass
            raise
        result['step'] = step
        result.update(parse_protocol(protocol_text(path), profile))
    if (runtime.get('server_stopped') is not True or runtime.get('process_groups_quiesced') is not True
            or runtime.get('loopback_listener_owned') is not True):
        raise native.PreservationRequired('Native fixture ownership or shutdown unconfirmed')
    if runtime['version'] != result['server_version']:
        raise ValueError('Native executable and JDBC server versions differ')
    result['status'] = 'PASS'


def save(result):
    # Only a complete run publishes new evidence. Keep failed attempts and prior reports in Git-local audit storage.
    AUDIT.mkdir(parents=True, exist_ok=True)
    if result['status'] != 'PASS':
        target = AUDIT / ('failed-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.json')
    else:
        target = REPORT
        if REPORT.exists():
            old = h.p5.p4.approved_paths([str(REPORT.relative_to(ROOT))])[0][1].read_bytes()
            archive = AUDIT / ('prior-' + guard.digest(old) + '.json')
            if not archive.exists():
                with archive.open('xb') as stream:
                    stream.write(old)
    h.p5.p4.save(target, result)


def run_checks(work, result):
    steps = result['steps']
    java_limits = '_JAVA_OPTIONS=-Xmx256m -XX:MaxMetaspaceSize=128m -XX:ActiveProcessorCount=2'
    steps.append(h.step('core-smoke', ['/usr/bin/env', java_limits, './tools/run-core-smoke.sh'], work))
    steps.append(h.step('recovery-contract', [sys.executable, '-B', 'tools/test-db-recovery.py'], work, timeout=20))
    match = re.search(r'^Ran ([1-9][0-9]{0,2}) tests? in [0-9.]+s\n\nOK\n$',
                      (work / 'recovery-contract.output').read_text(), re.M)
    if not match:
        raise ValueError('Recovery protocol contract proof incomplete')
    result['protocol_tests'] = int(match[1])
    jars, result['jdbc_dependencies'] = prior.pinned_drivers(work)
    classes = work / 'classes'
    steps.append(h.step('compile-recovery', prior.base.JAVAC + ['-d', str(classes), str(ROOT / SOURCE)], work))
    classpath = os.pathsep.join(map(str, [classes, *jars]))
    for profile in prior.PROFILES:
        item = {'status': 'FAIL'}
        result['profiles'][profile] = item
        run_database(profile, work, classpath, item)


def main():
    if sys.argv[1:]:
        print('DB_RECOVERY INVALID_ARGUMENTS')
        return 2
    for event in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
        signal.signal(event, prior.interrupted)
    start = time.monotonic()
    result = {'schema_version': 1, 'status': 'FAIL', 'scope': 'product expansion Phase 4', 'profiles': {}, 'steps': [],
              'started_at_utc': datetime.now(timezone.utc).isoformat(), 'compile_release': 17,
              'docker_containers_started': 0,
              'not_run': ['SQL Server', 'Oracle', 'connection pool behavior', 'unknown commit recovery', 'G5'],
              'limits': {'wall_seconds': WALL_SECONDS, 'java_seconds_per_profile': JAVA_SECONDS,
                         'workspace_bytes': 1024**3, 'workspace_entries': 5000,
                         'database_parallelism': 1, 'blocked_write_parallelism': 1,
                         'jvm_heap_mib': 256, 'jvm_active_cpus': 2}}
    signal.alarm(WALL_SECONDS)
    try:
        lock_parent = ROOT / '.git/udak-g2-managed'
        lock_parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(lock_parent / 'RUN.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result['input_sha512'] = input_hashes()
            with prior.workspace() as (work, cleanup):
                result['cleanup'] = cleanup
                run_checks(work, result)
                if result['input_sha512'] != input_hashes():
                    raise ValueError('Execution inputs changed')
            if cleanup.get('status') != 'PASS' or cleanup.get('remaining') is not False:
                raise ValueError('Owned scratch cleanup incomplete')
        result['status'] = 'PASS'
    except Exception as error:
        result['failure_type'] = type(error).__name__
        # h.step failures already contain an allowlisted diagnostic receipt.
        if isinstance(error, RuntimeError):
            try:
                receipt = json.loads(str(error))
                if isinstance(receipt, dict) and receipt.get('status') == 'FAIL' and 'exit_code' in receipt:
                    result['failed_step'] = receipt
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
