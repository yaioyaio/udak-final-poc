#!/usr/bin/env python3
"""RELEASE-013 bounded recovery checks on the recorded Oracle Free development fixture."""
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('retained_oracle', ROOT / 'tools/release-provider/run-oracle.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
managed, h, native = oracle.managed, oracle.pool.h, oracle.pool.native
SOURCE = 'tools/release-provider/OracleRecoveryFixture.java'
ACK = 'tools/release-provider/OracleCommitAckFixture.java'
GUARD = 'consistency-core/src/main/java/dev/udak/consistency/TransactionGuard.java'
SELF = 'tools/release-provider/run-oracle-recovery.py'
REPORT = 'evidence/PRODUCT-G5-ORACLE-RECOVERY.json'
LIMITS = {**oracle.LIMITS, 'work_wall_seconds': 420, 'startup_seconds': 105, 'java_seconds': 75,
          'observer_connections': 2, 'restart_count': 1, 'disconnects': 1, 'active_waiter_limit': 1}
SCENARIOS = ('JDBC_CANCEL', 'JDBC_QUERY_TIMEOUT', 'SESSION_REPLACEMENT', 'LOST_COMMIT_ACK', 'GRACEFUL_RESTART')
READY = ("declare n number; begin select count(*) into n from v$pdbs where name='FREEPDB1' and open_mode='READ WRITE'; "
         "if n != 1 then raise_application_error(-20002,'fixture'); end if; end;\n/")
require = oracle.require


def inputs():
    return h.hashes((*oracle.INPUTS, SOURCE, ACK, GUARD, SELF))


class Trial:
    def __init__(self, cid, owner_run, retained, result, journal):
        self.cid, self.owner_run, self.retained = cid, owner_run, retained
        self.result, self.journal = result, journal
        self.engine = managed.docker.Engine()
        suffix = secrets.token_hex(12).upper()
        self.user, self.space = 'UDAKG5' + suffix, 'UDAKT5' + suffix
        self.datafile = '/tmp/udak-g5-' + suffix.lower() + '.dbf'
        self.password = 'ABab12#_' + secrets.token_hex(11)
        self.started = self.user_owned = self.space_owned = False
        self.state = {'requirement': 'RELEASE-013', 'fixture_id': suffix}
        result.update(schema_cleanup='NOT_CREATED', storage_cleanup='NOT_CREATED', retention_cleanup='UNCONFIRMED')

    def record(self, phase):
        self.state['phase'] = phase
        managed.save(self.journal, self.state)

    def check_sql(self, text, stage):
        require(oracle.sql(self.cid, text, self.result), stage)

    def start(self):
        require(oracle.snapshot() == self.retained, 'IMMEDIATE_START_STATE')
        self.record('BOUNDS_INTENT')
        bounds = subprocess.run([*managed.DOCKER, 'container', 'update', '--restart=no', '--memory=3072m',
                                 '--memory-swap=3072m', '--cpus=2', '--pids-limit=512', self.cid],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        require(bounds.returncode == 0 and bounds.stdout.strip() == self.cid.encode('ascii') and not bounds.stderr,
                'BOUNDS_UPDATE_UNCONFIRMED')
        self.record('START_INTENT')
        require(oracle.snapshot() == self.retained, 'IMMEDIATE_START_STATE')
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, (signal.SIGINT, signal.SIGTERM, signal.SIGALRM))
        try:
            with self.engine._request('POST', '/containers/' + self.cid + '/start', (204,), wall_seconds=20):
                self.started = True
                self.result['starts_of_retained_container'] += 1
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
        self.record('RUNNING')
        probe = ('set -eu; cd /sys/fs/cgroup; read -r memory <memory.max; read -r swap <memory.swap.max; '
                 'read -r pids <pids.max; read -r quota period <cpu.max; '
                 'test "$memory" = 3221225472 && test "$swap" = 0 && test "$pids" = 512 && '
                 'test "$period" -gt 0 && test "$quota" -eq "$((2 * period))" && printf OK')
        require(oracle.docker(['exec', self.cid, '/bin/sh', '-c', probe]) == 'OK', 'LIVE_CGROUP_BOUNDS')
        deadline = time.monotonic() + LIMITS['startup_seconds']
        while time.monotonic() < deadline:
            state = self.engine.state(self.cid, self.owner_run)
            require(state['state'] == 'running' and state['status'] != 'unhealthy', 'STARTUP_STATE')
            port = self.engine.endpoint(self.cid, self.owner_run)
            if port and oracle.sql(self.cid, READY):
                return port
            time.sleep(2)
        raise oracle.Gate('STARTUP_DEADLINE')

    def stop(self):
        if self.started and self.engine.state(self.cid, self.owner_run)['state'] == 'running':
            self.engine.stop(self.cid, self.owner_run, timeout=LIMITS['shutdown_grace_seconds'])
        self.started = False
        require(oracle.snapshot() == self.retained, 'RETAINED_SET_CHANGED')
        state = oracle.docker(['container', 'inspect', '--format',
                               '{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}', self.cid])
        require(state in ('exited 0 false', 'exited 143 false'), 'ORACLE_CONTAINER_STOP')

    def shutdown_database(self):
        program = ("set -o pipefail; timeout -k 2 32 sqlplus -L -s /nolog 2>/dev/null | "
                   "awk '/^ORACLE instance shut down[.]$/ {stopped=1} "
                   "/^ORA-[0-9]+:/ {failed=1} END {if (stopped && !failed) print \"OK\"; else exit 1}'")
        payload = (b'whenever oserror exit failure rollback\nwhenever sqlerror exit failure rollback\n'
                   b'connect / as sysdba\nshutdown immediate\nexit success\n')
        proc = subprocess.run([*managed.DOCKER, 'exec', '-i', '--user', 'oracle', self.cid, '/bin/bash', '-c', program],
                              input=payload, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=37)
        require(proc.returncode == 0 and proc.stdout == b'OK\n', 'ORDERLY_ORACLE_SHUTDOWN')
        self.result['oracle_shutdown_immediate_confirmed'] = True

    def allocate(self):
        self.check_sql(oracle.schema_count(self.user, 0) + '\n' + oracle.storage_count(self.space, self.datafile, 0),
                       'ABSENT_FIXTURE_NAMESPACE')
        require(oracle.datafile_absent(self.cid, self.datafile), 'ABSENT_FIXTURE_DATAFILE')
        self.record('TABLESPACE_CREATE_INTENT')
        self.result['storage_cleanup'] = 'UNCONFIRMED'
        self.check_sql(f"create tablespace {self.space} datafile '{self.datafile}' size 8M autoextend off;", 'CREATE_SPACE')
        self.space_owned = True
        self.check_sql(self.storage_identity(), 'STORAGE_IDENTITY')
        self.record('SCHEMA_CREATE_INTENT')
        self.result['schema_cleanup'] = 'UNCONFIRMED'
        self.check_sql(f'create user {self.user} identified by "{self.password}" default tablespace {self.space} '
                       f'quota 2M on {self.space};', 'CREATE_SCHEMA')
        self.user_owned = True
        self.record('OWNED_SCHEMA')
        self.check_sql(f'grant create session, create table to {self.user};\n'
                       f'grant select on sys.v_$session to {self.user};', 'GRANT_FIXTURE_PERMISSIONS')

    def storage_identity(self):
        return (oracle.storage_count(self.space, self.datafile, 1) + '\n'
                + f"declare n number; begin select count(*) into n from dba_data_files where tablespace_name='{self.space}'; "
                "if n != 1 then raise_application_error(-20007,'fixture'); end if; end;\n/")

    def disconnect(self, sid, serial):
        require(0 < sid < 2**31 and 0 < serial < 2**31, 'SESSION_ID_BOUNDS')
        self.check_sql(f"declare n number; begin select count(*) into n from v$session s where s.sid={sid} "
                       f"and s.serial#={serial} and s.username='{self.user}' and s.type='USER' and s.taddr is not null "
                       "and s.con_id=to_number(sys_context('USERENV','CON_ID')); "
                       "if n != 1 then raise_application_error(-20008,'fixture'); end if; "
                       f"execute immediate 'alter system disconnect session ''{sid},{serial}'' immediate'; end;\n/",
                       'DISCONNECT_OWNED_TRANSACTION')

    def seed_restart(self):
        table = self.user + '.G5_RESTART'
        self.check_sql(f'create table {table}(id number(9) not null);\ninsert into {table} values (1);\ncommit;\n'
                       f'insert into {table} values (2);\nrollback;', 'SEED_RESTART')

    def verify_restart(self):
        table = self.user + '.G5_RESTART'
        self.check_sql(self.storage_identity() + '\n' + verify_rows(table, 1, 0, 0)
                       + f'\ninsert into {table} values (3);\ncommit;', 'RECOVER_RESTART')
        self.check_sql(verify_rows(table, 1, 0, 1), 'VERIFY_RESTART_COMMIT')

    def cleanup(self):
        if self.user_owned and self.started:
            check = (f"declare n number; begin select count(*) into n from dba_objects where owner='{self.user}' and not "
                     "((object_type='TABLE' and object_name in ('G5_RECOVERY','G5_ACK','G5_RESTART')) or "
                     "(object_type='INDEX' and object_name in ('G5_RECOVERY_PK','G5_ACK_PK'))); "
                     "if n != 0 then raise_application_error(-20003,'fixture'); end if; end;\n/")
            if oracle.sql(self.cid, check + f'\ndrop user {self.user} cascade;\n' + oracle.schema_count(self.user, 0)):
                self.result['schema_cleanup'] = 'CONFIRMED'
        if self.space_owned and self.started and self.result['schema_cleanup'] != 'UNCONFIRMED':
            drop = (self.storage_identity() + '\n' + oracle.empty_storage(self.space)
                    + f'\ndrop tablespace {self.space} including contents and datafiles;\n'
                    + oracle.storage_count(self.space, self.datafile, 0))
            if oracle.sql(self.cid, drop) and oracle.datafile_absent(self.cid, self.datafile):
                self.result['storage_cleanup'] = 'CONFIRMED'


def verify_rows(table, committed, rolled_back, next_commit):
    return (f'declare a number; b number; c number; begin select count(*) into a from {table} where id=1; '
            f'select count(*) into b from {table} where id=2; select count(*) into c from {table} where id=3; '
            f"if a != {committed} or b != {rolled_back} or c != {next_commit} then "
            "raise_application_error(-20009,'fixture'); end if; end;\n/")


def await_line(reader, child):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        position = reader.tell()
        line = reader.readline(97)
        require(len(line) < 97, 'JDBC_PROTOCOL_SIZE')
        if line.endswith(b'\n'):
            return line
        child.check()
        reader.seek(position)
        time.sleep(0.05)
    raise oracle.Gate('JDBC_PROTOCOL_DEADLINE')


def java(cp, fixture):
    return oracle.pool.schema.base.JAVA + ['-cp', cp, fixture]


def exercise(trial, port, work, cp, result):
    payload = f'{port}\n{trial.user}\n{trial.password}\n'.encode('ascii')
    protocol = work / 'oracle-recovery.protocol'
    with protocol.open('xb') as out, protocol.open('rb') as reader:
        child = native._Child(java(cp, 'OracleRecoveryFixture'), work, LIMITS['java_seconds'], out, b'', None)
        try:
            pipe = child.process.stdin
            pipe.write(payload)
            pipe.flush()
            require(await_line(reader, child) == b'ORACLE_CANCEL PASS\n', 'JDBC_CANCEL_PROTOCOL')
            result['scenarios']['JDBC_CANCEL'] = 'PASS'
            require(await_line(reader, child) == b'ORACLE_TIMEOUT PASS\n', 'JDBC_TIMEOUT_PROTOCOL')
            result['scenarios']['JDBC_QUERY_TIMEOUT'] = 'PASS'
            match = re.fullmatch(rb'ORACLE_DISCONNECT_READY ([1-9][0-9]{0,9}) ([1-9][0-9]{0,9})\n', await_line(reader, child))
            require(match is not None, 'DISCONNECT_PROTOCOL')
            trial.disconnect(*(int(value) for value in match.groups()))
            pipe.write(b'DISCONNECTED\n')
            pipe.close()
            require(await_line(reader, child) == b'ORACLE_REPLACEMENT PASS\n', 'JDBC_REPLACEMENT_PROTOCOL')
            require(child.process.wait(timeout=6) == 0 and not reader.read(1), 'JDBC_RECOVERY_EXIT')
        finally:
            child.close(signal.SIGTERM)
            if child.process.stdin is not None:
                child.process.stdin.close()
    require(child.quiesced, 'JDBC_RECOVERY_CLEANUP')
    result['scenarios']['SESSION_REPLACEMENT'] = 'PASS'
    try:
        receipt, out = native.run_private('oracle-commit-ack', java(cp, 'OracleCommitAckFixture'), work, 25, payload)
    except RuntimeError:
        failure_path = work / 'oracle-commit-ack.output'
        if failure_path.is_file() and failure_path.stat().st_size <= 96:
            match = re.fullmatch(rb'ORACLE_LOST_ACK FAIL ([A-Z_]{1,24}) (SQL|IO|TIMEOUT|CHECK)\n', failure_path.read_bytes())
            if match:
                result['ack_failure'] = [value.decode('ascii') for value in match.groups()]
        raise
    require(out.stat().st_size <= 96 and out.read_bytes() == b'ORACLE_LOST_ACK PASS\n', 'JDBC_LOST_ACK_PROTOCOL')
    result['commit_ack_step'] = receipt
    result['scenarios']['LOST_COMMIT_ACK'] = 'PASS'


def run(result):
    lock_path = managed.PRIVATE / 'RUN.lock'
    with os.fdopen(os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        for name in ('release-012-oracle.json', 'release-013-oracle.json'):
            journal = managed.PRIVATE / name
            require(not journal.exists() or json.loads(journal.read_text()).get('phase') == 'CLOSED', 'PRIOR_TRIAL_OPEN')
        result['input_sha512'] = inputs()
        with oracle.pool.schema.workspace() as (work, cleanup):
            result['cleanup'] = cleanup
            cid, owner_run, retained, result['image'] = oracle.public_identity()
            cp = oracle.prepare_client(work, result)
            command = oracle.pool.schema.base.JAVAC + ['-cp', cp, '-d', str(work / 'classes'),
                                                       *(str(ROOT / path) for path in (SOURCE, ACK, GUARD))]
            result['compile'], _ = native.run_private('oracle-recovery-compile', command, work, 30)
            result['resource_preflight'] = managed.preflight(work, LIMITS['database_memory_mib'])
            trial = Trial(cid, owner_run, retained, result, journal)
            try:
                port = trial.start()
                trial.allocate()
                exercise(trial, port, work, cp, result)
                trial.seed_restart()
                trial.shutdown_database()
                trial.stop()
                trial.start()
                trial.verify_restart()
                result['scenarios']['GRACEFUL_RESTART'] = 'PASS'
            finally:
                signal.alarm(0)
                try:
                    trial.cleanup()
                finally:
                    trial.stop()
                    result.update(retention_cleanup='CONFIRMED', retained_instances=12, managed_running=0)
                    complete = 'UNCONFIRMED' not in (result['schema_cleanup'], result['storage_cleanup'])
                    trial.record('CLOSED' if complete else 'PRESERVE_FOR_REVIEW')
                    require(complete, 'PRESERVE_FOR_REVIEW')
        require(cleanup.get('status') == 'PASS' and cleanup.get('remaining') is False, 'WORKSPACE_CLEANUP')
        require(result['input_sha512'] == inputs() and result['scenarios'] == dict.fromkeys(SCENARIOS, 'PASS'),
                'INCOMPLETE_OR_CHANGED_EVIDENCE')
        result.update(status='PASS', scenario_count=len(SCENARIOS), server_version='23.26.4.0.0',
                      driver_version='23.26.4.0.0')
        h.save(REPORT, result)


def main():
    if sys.argv[1:] != ['--run-retained-oracle-recovery']:
        return 2
    os.umask(0o077)
    result = {'schema_version': 1, 'requirement': 'RELEASE-013', 'profile': 'ORACLE', 'status': 'FAIL',
              'started_at_utc': datetime.now(timezone.utc).isoformat(), 'limits': LIMITS, 'platform': 'linux/arm64',
              'starts_of_retained_container': 0, 'new_containers': 0, 'scenarios': {}}
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(sig, oracle.pool.schema.interrupted)
    signal.alarm(LIMITS['work_wall_seconds'])
    try:
        run(result)
    except Exception as error:
        frame = traceback.extract_tb(error.__traceback__)[-1]
        result.update(reason=str(error) if isinstance(error, oracle.Gate) else type(error).__name__,
                      failure_location=f'{Path(frame.filename).name}:{frame.name}:{frame.lineno}')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        managed.save(managed.PRIVATE / ('release-013-failure-' + stamp + '.json'), result)
    finally:
        signal.alarm(0)
    print(json.dumps({k: result[k] for k in ('status', 'scenarios', 'starts_of_retained_container', 'reason') if k in result}))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
