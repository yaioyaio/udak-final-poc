#!/usr/bin/env python3
"""RELEASE-012. Borrow only the recorded Phase 5 Oracle Free ARM64 fixture."""
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

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


managed = load('oracle_managed', 'tools/run-managed-g2.py')
pool = load('oracle_pool', 'tools/run-g5-pool.py')
REPORT = 'evidence/PRODUCT-G5-ORACLE.json'
SOURCE = 'tools/release-provider/OraclePoolFixture.java'
INPUTS = tuple(dict.fromkeys((*pool.INPUTS, SOURCE, 'tools/release-provider/run-oracle.py',
                            'tools/run-managed-g2.py', 'tools/g2-docker.py', 'tools/g2-server-images.json',
                            'evidence/PHASE5-REAL-VALIDATION.json', 'evidence/PHASE5-CONTAINER-RETENTION.json')))
COORDINATE = 'com.oracle.database.jdbc:ojdbc17:23.26.4.0.0'
LIMITS = {'work_wall_seconds': 420, 'startup_seconds': 180, 'shutdown_grace_seconds': 45,
          'database_memory_mib': 3072, 'database_cpus': 2, 'database_pids': 512, 'managed_instances': 12,
          'java_seconds': 35, 'pool_size': 1, 'observer_connections': 1, 'schema_quota_mib': 2,
          'fixture_datafile_mib': 8,
          'database_instances_in_parallel': 1, 'application_retries': 0}


class Gate(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise Gate(reason)


def read(path):
    return json.loads((ROOT / path).read_text())


def docker(args, timeout=10):
    proc = subprocess.run([*managed.DOCKER, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, timeout=timeout)
    require(proc.returncode == 0 and len(proc.stdout) <= 8192, 'DOCKER_COMMAND_FAILED')
    return proc.stdout.decode('ascii').strip()


def snapshot():
    rows = docker(['ps', '-a', '--no-trunc', '--filter', 'label=dev.udak.g2.managed=true',
                   '--format', '{{.ID}} {{.State}}']).splitlines()
    require(len(rows) == 12 and all(re.fullmatch(r'[a-f0-9]{64} exited', row) for row in rows), 'RETAINED_SET')
    return {row.split()[0] for row in rows}


def public_identity():
    record = read('evidence/PHASE5-CONTAINER-RETENTION.json')
    previous = read('evidence/PHASE5-REAL-VALIDATION.json')
    retained = record['profiles']['ORACLE']
    prior = previous['profiles']['ORACLE']
    pin = next(i for i in read('tools/g2-server-images.json')['images'] if i['profile'] == 'ORACLE')
    cid, run = retained['container_id'], previous['run_id']
    require(re.fullmatch(r'[a-f0-9]{64}', cid) and re.fullmatch(r'[a-f0-9]{32}', run), 'PUBLIC_RECEIPT')
    require(previous['status'] == 'PASS' and prior['container_id'] == cid and prior['status'] == 'PASS'
            and retained['state'] == 'exited' and retained['oom_killed'] is False and retained['mount_count'] == 0
            and retained['fixture_cleanup'] == 'CONFIRMED' and retained['image_id'] == prior['image_config_id']
            and pin['image'] == prior['image'] and pin['platform'] == prior['platform'] == 'linux/arm64',
            'PUBLIC_RECEIPT')
    expected = set(record['original_ids']) | {item['container_id'] for item in record['profiles'].values()}
    require(snapshot() == expected, 'RETAINED_RECEIPTS')
    filters = ['--filter', 'id=' + cid, '--filter', 'label=dev.udak.g2.profile=ORACLE',
               '--filter', 'label=dev.udak.g2.managed=true', '--filter', 'label=dev.udak.g2.run=' + run]
    require(docker(['ps', '-a', '--no-trunc', *filters, '--format', '{{.ID}}']) == cid, 'OWNERSHIP')
    require(docker(['info', '--format', '{{.OSType}}/{{.Architecture}}']) in ('linux/aarch64', 'linux/arm64'),
            'DAEMON_PLATFORM')
    require(docker(['info', '--format', '{{.CgroupVersion}}']) == '2', 'CGROUP_V2')
    require(docker(['image', 'inspect', '--format', '{{.Id}} {{.Os}}/{{.Architecture}}', pin['image']])
            == retained['image_id'] + ' linux/arm64', 'PLATFORM_PIN')
    # The original creation code fixes immutable privilege, log, mount and port configuration.
    # Check its execution receipt, while limiting live inspect to state/image/mount fields.
    creators = ('tools/g2-docker.py', 'tools/run-managed-g2.py', 'tools/run-phase5-real.py')
    require(all(previous['harness_sha512'][p] == digest for p, digest in pool.h.hashes(creators).items())
            and pool.h.hashes(['tools/g2-server-images.json']) == {
                'tools/g2-server-images.json': previous['manifest_sha512']['tools/g2-server-images.json']},
            'RECORDED_CREATOR_CHANGED')
    fields = '{{.State.Status}} {{.State.OOMKilled}} {{.Image}} {{len .Mounts}}'
    expected_fields = ['exited', 'false', retained['image_id'], '0']
    require(docker(['container', 'inspect', '--format', fields, cid]).split() == expected_fields, 'CONTAINER_STATE')
    require(docker(['ps', '-a', *filters, '--format', '{{eq .Networks "bridge"}}']) == 'true', 'NETWORK_MEMBERSHIP')
    return cid, run, expected, pin['image']


def sql(cid, script, diagnostic=None):
    # SQLPlus output stays in the container. Only a fixed token or a numeric ORA code crosses the boundary.
    # The command, invocation options and match token are constant; SQL and fresh fixture inputs travel on stdin.
    program = ("set -o pipefail; timeout -k 2 10 sqlplus -L -s /nolog 2>/dev/null | "
               "awk '$0 == \"UDAK_SQL_OK\" {seen=1} "
               "!code && $0 ~ /^ORA-[0-9][0-9][0-9][0-9][0-9]:/ {code=substr($0,1,9)} "
               "END {if (seen) print \"OK\"; else if (code) print code; exit !seen}'")
    payload = ('whenever oserror exit failure rollback\nwhenever sqlerror exit failure rollback\n'
               'set echo off verify off feedback off heading off define off\nconnect / as sysdba\n'
               'alter session set container = FREEPDB1;\n' + script + '\nprompt UDAK_SQL_OK\nexit success\n')
    proc = subprocess.run([*managed.DOCKER, 'exec', '-i', '--user', 'oracle', cid, '/bin/bash', '-c', program],
                          input=payload.encode('ascii'), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15)
    if diagnostic is not None and re.fullmatch(rb'ORA-[0-9]{5}\n', proc.stdout):
        diagnostic['sql_error_code'] = proc.stdout.strip().decode('ascii')
    return proc.returncode == 0 and proc.stdout == b'OK\n'


def schema_count(name, count):
    return (f"declare n number; begin select count(*) into n from dba_users where username='{name}'; "
            f"if n != {count} then raise_application_error(-20001,'fixture'); end if; end;\n/")


def storage_count(space, path, count):
    return (f"declare n number; m number; begin select count(*) into n from dba_tablespaces where tablespace_name='{space}'; "
            f"select count(*) into m from dba_data_files where file_name='{path}' and tablespace_name='{space}'; "
            f"if n != {count} or m != {count} then raise_application_error(-20004,'fixture'); end if; end;\n/")


def empty_storage(space):
    return (f"declare n number; begin select count(*) into n from dba_segments where tablespace_name='{space}'; "
            f"if n != 0 then raise_application_error(-20005,'fixture'); end if; end;\n/")


def datafile_absent(cid, path):
    return docker(['exec', cid, '/bin/sh', '-c', 'test ! -e "$1" && test ! -L "$1" && printf OK',
                   'fixture-path', path]) == 'OK'


def prepare_client(work, result):
    manifest = read('tools/g2-dependencies.json')
    items = [i for i in manifest['artifacts'] if i['coordinate'] == COORDINATE]
    require(len(items) == 1 and not items[0]['runtime_dependencies'], 'ORACLE_DRIVER_PIN')
    subset = {'artifacts': items, 'upstream_license_checks': [
        i for i in manifest['upstream_license_checks'] if i['coordinate'] == COORDINATE]}
    jdbc, result['jdbc_dependencies'] = managed.g2.dependencies(work, subset)
    jars, result['pool_dependencies'] = pool.pool_dependencies(work)
    classes = work / 'classes'
    classes.mkdir()
    cp = os.pathsep.join(map(str, [classes, *jdbc, *jars]))
    pool.native.run_private('oracle-compile', pool.schema.base.JAVAC + ['-cp', cp, '-d', str(classes), str(ROOT / SOURCE)],
                            work, 30)
    return cp


def run_fixture(work, cp, cid, run, expected, result, journal):
    engine = managed.docker.Engine()
    name = 'UDAKG5' + secrets.token_hex(12).upper()
    secret = 'ABab12#_' + secrets.token_hex(11)
    space = 'UDAKT5' + name[6:]
    datafile = '/tmp/udak-g5-' + name[6:].lower() + '.dbf'
    # The run token identifies this trial for recovery. Never persist its password or connection properties.
    recovery = {'requirement': 'RELEASE-012', 'fixture_id': name[6:], 'phase': 'BOUNDS_UPDATE_INTENT'}
    owned = False
    attempted_create = False
    attempted_storage = False
    storage_owned = False
    started = False
    result.update(schema_cleanup='NOT_CREATED', storage_cleanup='NOT_CREATED', retention_cleanup='UNCONFIRMED')
    require(snapshot() == expected, 'IMMEDIATE_RETAINED_SET')
    managed.save(journal, recovery)
    try:
        bounds = subprocess.run([*managed.DOCKER, 'container', 'update', '--restart=no', '--memory=3072m',
                                 '--memory-swap=3072m', '--cpus=2', '--pids-limit=512', cid],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        require(bounds.returncode == 0 and bounds.stdout.strip() == cid.encode('ascii') and not bounds.stderr,
                'BOUNDS_UPDATE_UNCONFIRMED')
        result['retained_bounds_reapplied'] = True
        recovery['phase'] = 'START_INTENT'
        managed.save(journal, recovery)
        require(snapshot() == expected, 'IMMEDIATE_START_STATE')
        # A 204 acknowledges our own transition. An already-running instance returns 304;
        # never stop one on an ambiguous response, concurrent start or transport error.
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, (signal.SIGINT, signal.SIGTERM, signal.SIGALRM))
        try:
            with engine._request('POST', '/containers/' + cid + '/start', (204,), wall_seconds=20):
                started = True
                result['docker_containers_started'] = 1
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
        verify_bounds = ('set -eu; cd /sys/fs/cgroup; read -r memory <memory.max; '
                         'read -r swap <memory.swap.max; read -r pids <pids.max; read -r quota period <cpu.max; '
                         'test "$memory" = 3221225472 && test "$swap" = 0 && test "$pids" = 512 && '
                         'test "$period" -gt 0 && test "$quota" -eq "$((2 * period))"')
        proc = subprocess.run([*managed.DOCKER, 'exec', cid, '/bin/sh', '-c', verify_bounds],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        require(proc.returncode == 0, 'LIVE_CGROUP_BOUNDS')
        result['live_cgroup_verified'] = True
        deadline = time.monotonic() + LIMITS['startup_seconds']
        ready = ("declare n number; begin select count(*) into n from v$pdbs where name='FREEPDB1' "
                 "and open_mode='READ WRITE'; if n != 1 then raise_application_error(-20002,'pdb'); end if; end;\n/")
        port = None
        while time.monotonic() < deadline:
            state = engine.state(cid, run)
            require(state['state'] == 'running' and state['status'] != 'unhealthy', 'STARTUP_STATE')
            port = engine.endpoint(cid, run)
            if port and sql(cid, ready):
                break
            time.sleep(2)
        else:
            raise Gate('STARTUP_DEADLINE')
        require(sql(cid, schema_count(name, 0)), 'SCHEMA_ABSENCE')
        require(sql(cid, storage_count(space, datafile, 0)) and datafile_absent(cid, datafile), 'STORAGE_ABSENCE')
        recovery['phase'] = 'STORAGE_CREATE_INTENT'
        managed.save(journal, recovery)
        attempted_storage = True
        result['storage_cleanup'] = 'UNCONFIRMED'
        require(sql(cid, f"create tablespace {space} datafile '{datafile}' size 8M autoextend off;", result),
                'STORAGE_CREATE')
        storage_owned = True
        require(sql(cid, storage_count(space, datafile, 1)), 'STORAGE_IDENTITY')
        recovery['phase'] = 'CREATE_INTENT'
        managed.save(journal, recovery)
        attempted_create = True
        result['schema_cleanup'] = 'UNCONFIRMED'
        require(sql(cid, f'create user {name} identified by "{secret}" default tablespace {space} quota 2M on {space};',
                    result), 'SCHEMA_CREATE')
        owned = True
        recovery['phase'] = 'SCHEMA_CREATED'
        managed.save(journal, recovery)
        require(sql(cid, f'grant create session, create table to {name};'), 'SCHEMA_GRANT')
        data = f'{port}\n{name}\n{secret}\n'.encode('ascii')
        command = pool.schema.base.JAVA + ['-cp', cp, 'OraclePoolFixture']
        _, output = pool.native.run_private('oracle-pool', command, work, LIMITS['java_seconds'], data)
        match = re.fullmatch(rb'ORACLE_POOL_PASS (23\.26(?:\.[0-9]{1,3}){3})\n', output.read_bytes())
        require(match, 'JDBC_PROTOCOL')
        result.update(server_version=match[1].decode('ascii'), driver_version='23.26.4.0.0',
                      scenarios={'ROLLBACK_RESET_REUSE': 'PASS', 'INDEPENDENT_COMMIT_VISIBILITY': 'PASS'})
    finally:
        # The wall limit interrupts workload and reserves bounded time for cleanup.
        signal.alarm(0)
        try:
            if owned:
                before_drop = (f"declare n number; begin select count(*) into n from dba_objects where owner='{name}' "
                               "and not (object_type='TABLE' and object_name='G5_POOL'); "
                               "if n != 0 then raise_application_error(-20003,'fixture'); end if; end;\n/")
                if sql(cid, before_drop + f'\ndrop user {name} cascade;\n' + schema_count(name, 0)):
                    result['schema_cleanup'] = 'CONFIRMED'
            elif attempted_create and sql(cid, schema_count(name, 0)):
                result['schema_cleanup'] = 'NOT_CREATED'
            if storage_owned and result['schema_cleanup'] != 'UNCONFIRMED':
                drop = (storage_count(space, datafile, 1) + '\n' + empty_storage(space)
                        + f'\ndrop tablespace {space} including contents and datafiles;\n'
                        + storage_count(space, datafile, 0))
                if sql(cid, drop) and datafile_absent(cid, datafile):
                    result['storage_cleanup'] = 'CONFIRMED'
            elif attempted_storage and not storage_owned and sql(cid, storage_count(space, datafile, 0)):
                if datafile_absent(cid, datafile):
                    result['storage_cleanup'] = 'NOT_CREATED'
        finally:
            if started and engine.state(cid, run)['state'] == 'running':
                engine.stop(cid, run, timeout=LIMITS['shutdown_grace_seconds'])
            post = docker(['container', 'inspect', '--format', '{{.State.Status}} {{.State.OOMKilled}}', cid])
            if snapshot() == expected and post == 'exited false':
                result.update(retention_cleanup='CONFIRMED', retained_instances=12, managed_running=0)
            complete = ('UNCONFIRMED' not in (result['schema_cleanup'], result['storage_cleanup'])
                        and result['retention_cleanup'] == 'CONFIRMED')
            recovery['phase'] = 'CLOSED' if complete else 'PRESERVE_FOR_REVIEW'
            managed.save(journal, recovery)
            require(complete, 'PRESERVE_FOR_REVIEW')


def run(result):
    with os.fdopen(os.open(managed.PRIVATE / 'RUN.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        journal = managed.PRIVATE / 'release-012-oracle.json'
        if journal.exists():
            require(json.loads(journal.read_text()).get('phase') == 'CLOSED', 'PREVIOUS_TRIAL_REQUIRES_REVIEW')
        result['input_sha512'] = pool.h.hashes(INPUTS)
        with pool.schema.workspace() as (work, cleanup):
            result['cleanup'] = cleanup
            cid, owner_run, expected, result['image'] = public_identity()
            cp = prepare_client(work, result)
            result['resource_preflight'] = managed.preflight(work, LIMITS['database_memory_mib'])
            result['stage'] = 'RUNTIME'
            run_fixture(work, cp, cid, owner_run, expected, result, journal)
        require(cleanup.get('status') == 'PASS' and cleanup.get('remaining') is False, 'WORKSPACE_CLEANUP')
        require(result['input_sha512'] == pool.h.hashes(INPUTS), 'INPUTS_CHANGED')
        result.update(status='PASS', stage='COMPLETE')
        pool.h.save(REPORT, result)


def main():
    if sys.argv[1:] == ['--check-retained-oracle']:
        try:
            public_identity()
            print('ORACLE_RETAINED_IDENTITY_PASS')
            return 0
        except Exception as error:
            print(str(error) if isinstance(error, Gate) else type(error).__name__)
            return 1
    if sys.argv[1:] != ['--run-retained-oracle']:
        return 2
    os.umask(0o077)
    result = {'schema_version': 1, 'requirement': 'RELEASE-012', 'profile': 'ORACLE', 'status': 'FAIL',
              'started_at_utc': datetime.now(timezone.utc).isoformat(), 'stage': 'PREFLIGHT', 'limits': LIMITS,
              'platform': 'linux/arm64', 'pool': pool.HIKARI, 'docker_containers_started': 0,
              'docker_containers_created': 0, 'scenarios': {}}
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(sig, pool.schema.interrupted)
    signal.alarm(LIMITS['work_wall_seconds'])
    try:
        run(result)
    except BaseException as failure:
        result.update(status='FAIL', reason=str(failure) if isinstance(failure, Gate) else type(failure).__name__)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        managed.save(managed.PRIVATE / ('release-012-failure-' + stamp + '.json'), result)
    finally:
        signal.alarm(0)
    print(json.dumps({k: result[k] for k in ('status', 'stage', 'docker_containers_started', 'reason') if k in result}))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
