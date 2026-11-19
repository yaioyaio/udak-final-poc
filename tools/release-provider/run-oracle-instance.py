#!/usr/bin/env python3
"""RELEASE-014 isolated Oracle concurrency and instance recovery entry point."""
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import signal
import sys
import time
from urllib.parse import urlencode

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('g5_oracle_base', ROOT / 'tools/release-provider/run-oracle.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
managed, h, native = oracle.managed, oracle.pool.h, oracle.pool.native
SELF = 'tools/release-provider/run-oracle-instance.py'
SOURCE = 'tools/release-provider/OracleInstanceG5Fixture.java'
PREPARATION = 'evidence/PRODUCT-G5-ORACLE-INSTANCE-PREPARATION.json'
APPROVAL = 'evidence/PRODUCT-G5-ORACLE-INSTANCE-APPROVAL.json'
REPORT = 'evidence/PRODUCT-G5-ORACLE-INSTANCE.json'
LIMITS = {'wall_seconds': 600, 'startup_seconds': 180, 'active_instances': 1, 'instance_cpus': 2,
          'instance_memory_mib': 3072, 'instance_pids': 512, 'persistent_writable_bytes': 3 * 1024**3,
          'workload_starts': 48, 'max_in_flight': 2, 'max_starts_per_second': 4,
          'min_spacing_ns': 250_000_000, 'instance_crashes': 1, 'automatic_retries': 0, 'container_logging': 'none'}
require = oracle.require


def sources():
    return (*oracle.INPUTS, SELF, SOURCE)


def get_pin():
    return next(item for item in oracle.read('tools/g2-server-images.json')['images'] if item['profile'] == 'ORACLE')


def protected_document(path):
    file = h.p5.p4.approved_paths([path])[0][1]
    require(file.stat().st_size <= 32 * 1024, 'REPORT_SIZE')
    return json.loads(file.read_text())


def authorized():
    approval = protected_document(APPROVAL)
    cap = approval.get('approved_total_managed_instances')
    require(type(cap) is int and cap in (1, 13), 'RETENTION_APPROVAL')
    require(approval == {'schema_version': 1, 'approval_basis': 'EXPLICIT_USER_CONFIRMATION',
                        'disposable_instance_and_cleanup': True, 'authorized_runs': 1,
                        'approved_total_managed_instances': cap, 'limits': LIMITS,
                        'runner_sha512': h.hashes((SELF, SOURCE))}, 'ORACLE_APPROVAL_SCOPE')
    return cap


def platform_checks():
    info = oracle.docker(['info', '--format', '{{.OSType}} {{.Architecture}} {{.CgroupVersion}} {{.Driver}} '
                         '{{range .DriverStatus}}{{if eq (index . 0) "Backing Filesystem"}}{{index . 1}}{{end}}{{end}}'])
    fields = info.split()
    require(len(fields) in (4, 5) and all(re.fullmatch(r'[A-Za-z0-9_.-]{1,48}', v) for v in fields), 'DOCKER_FACTS')
    pin = get_pin()
    identity = oracle.docker(['image', 'inspect', '--format', '{{.Id}} {{.Os}}/{{.Architecture}}', pin['image']])
    exact = re.fullmatch(r'(sha256:[0-9a-f]{64}) linux/arm64', identity)
    archived = oracle.read('evidence/PHASE5-CONTAINER-RETENTION.json')['profiles']['ORACLE']
    volume_free = exact is not None and exact[1] == archived['image_id'] and archived['mount_count'] == 0
    return {'native_arm64_engine': fields[:3] in (['linux', 'aarch64', '2'], ['linux', 'arm64', '2']),
            'local_pinned_image_without_volumes': volume_free,
            'writable_quota_prerequisite': fields[3:] == ['overlay2', 'xfs']}, exact[1] if exact else None


def inventory():
    rows = oracle.docker(['ps', '-a', '--no-trunc', '--filter', 'label=dev.udak.g2.managed=true',
                         '--format', '{{.ID}} {{.State}}']).splitlines()
    require(all(re.fullmatch(r'[a-f0-9]{64} exited', line) for line in rows), 'MANAGED_INSTANCES_NOT_STOPPED')
    return {line.split()[0] for line in rows}


def allowed_baseline(cap):
    original = inventory()
    if cap == 13:
        require(original == oracle.snapshot(), 'RETENTION_BASELINE')
    else:
        require(not original, 'DEDICATED_HOST_BASELINE')
    return original


def protocol(output):
    match = re.fullmatch(rb'ORACLE_INSTANCE CONCURRENCY PASS (48) (2) ([1-4]) ([0-9]{9,12})\n', output)
    require(match is not None and int(match[4]) >= LIMITS['min_spacing_ns'], 'ORACLE_CONCURRENCY_PROTOCOL')
    return dict(zip(('starts', 'max_in_flight', 'max_rolling_second', 'min_spacing_ns'), map(int, match.groups())))


def compile_fixture(work, result):
    cp = oracle.prepare_client(work, result)
    command = oracle.pool.schema.base.JAVAC + ['-cp', cp, '-d', str(work / 'classes'), str(ROOT / SOURCE)]
    result['compile'], _ = native.run_private('oracle-instance-compile', command, work, 30)
    return cp


def worker(cp, mode):
    return oracle.pool.schema.base.JAVA + ['-cp', cp, 'OracleInstanceG5Fixture', mode]


def live_port(engine, cid, run):
    probe = ('set -eu; cd /sys/fs/cgroup; read -r m <memory.max; read -r s <memory.swap.max; '
             'read -r p <pids.max; read -r q t <cpu.max; '
             'test "$m" = 3221225472 && test "$s" = 0 && test "$p" = 512 && '
             'test "$t" -gt 0 && test "$q" -eq "$((2 * t))" && printf OK')
    require(oracle.docker(['exec', cid, '/bin/sh', '-c', probe]) == 'OK', 'ORACLE_CGROUP_LIMITS')
    deadline = time.monotonic() + LIMITS['startup_seconds']
    while time.monotonic() < deadline:
        state = engine.state(cid, run)
        require(state['state'] == 'running' and state['status'] != 'unhealthy', 'ORACLE_STARTUP_STATE')
        port = engine.endpoint(cid, run)
        if port and oracle.sql(cid, 'select 1 from dual;'):
            return port
        time.sleep(2)
    raise oracle.Gate('ORACLE_STARTUP_TIMEOUT')


def owned_stopped(cid, exit_code):
    fields = '{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}} {{len .Mounts}}'
    return oracle.docker(['container', 'inspect', '--format', fields, cid]) == f'exited {exit_code} false 0'


def seed_and_crash(engine, cid, run, cp, frame, work):
    path = work / 'oracle-instance-seed.output'
    with path.open('xb') as out, path.open('rb') as reader:
        child = native._Child(worker(cp, 'SEED'), work, 55, out, b'', None)
        try:
            with child.process.stdin as pipe:
                pipe.write(frame)
            deadline = time.monotonic() + 18
            while True:
                reader.seek(0)
                if reader.read(80) == b'ORACLE_INSTANCE SEED READY\n':
                    break
                child.check()
                require(time.monotonic() < deadline, 'ORACLE_SEED_TIMEOUT')
                time.sleep(0.05)
            child.check()
            require(engine._owned(cid, run)['State'] == 'running', 'ORACLE_CRASH_OWNERSHIP')
            with engine._request('POST', f'/containers/{cid}/kill?signal=SIGKILL', (204,)):
                pass
            require(owned_stopped(cid, 137), 'ORACLE_CRASH_EXIT')
        finally:
            child.close(signal.SIGTERM)
    require(child.quiesced, 'ORACLE_SEED_PROCESS_CLEANUP')


def run_db(work, cp, image_id, cap, result):
    engine, pin = managed.docker.Engine(), get_pin()
    original, run = allowed_baseline(cap), secrets.token_hex(16)
    name = 'udak-g5-instance-' + run
    user = 'UDAKG5' + secrets.token_hex(12).upper()
    secret = 'ABab12#_' + secrets.token_hex(11)
    cfg = {'Image': pin['image'], 'Env': ['ORACLE_PWD=ABab12#_' + secrets.token_hex(11)],
           'Labels': {'dev.udak.g2.managed': 'true', 'dev.udak.g2.run': run, 'dev.udak.g2.profile': 'ORACLE'},
           'ExposedPorts': {'1521/tcp': {}},
           'HostConfig': {'NetworkMode': 'bridge', 'PortBindings': {'1521/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '0'}]},
                          'RestartPolicy': {'Name': 'no'}, 'Memory': 3 * 1024**3, 'MemorySwap': 3 * 1024**3,
                          'NanoCpus': 2_000_000_000, 'PidsLimit': 512, 'ShmSize': 1024**3, 'LogConfig': {'Type': 'none'},
                          'StorageOpt': {'size': '3G'}, 'AutoRemove': False, 'Privileged': False}}
    journal = managed.PRIVATE / 'release-014-oracle.json'
    planned = {'run': run, 'phase': 'CREATE_INTENT'}
    managed.save(journal, planned)
    # Docker overlay2 rejects StorageOpt.size at creation when XFS project quota is unavailable.
    created = engine._json('POST', '/containers/create?' + urlencode({'name': name, 'platform': 'linux/arm64'}),
                           (201,), json.dumps(cfg).encode('ascii'))
    cid = created.get('Id')
    require(isinstance(cid, str) and re.fullmatch(r'[0-9a-f]{64}', cid) and cid not in original, 'ORACLE_CREATED_IDENTITY')
    planned.update(container=cid, phase='CREATED')
    managed.save(journal, planned)
    try:
        require(not created.get('Warnings') and engine._owned(cid, run)['State'] == 'created', 'ORACLE_QUOTA_CREATION')
        inspect = '{{.Image}} {{len .Mounts}}'
        require(oracle.docker(['container', 'inspect', '--format', inspect, cid]) == f'{image_id} 0', 'ORACLE_IMAGE_MOUNTS')
        with engine._request('POST', f'/containers/{cid}/start', (204,), wall_seconds=20):
            pass
        port = live_port(engine, cid, run)
        setup = ("create tablespace UDAKG5_STORAGE datafile '/tmp/udak-g5-instance.dbf' size 8M autoextend off;\n"
                 f'create user {user} identified by "{secret}" default tablespace UDAKG5_STORAGE quota 2M on UDAKG5_STORAGE;\n'
                 f'grant create session, create table to {user};\n'
                 f'create table {user}.G5_INSTANCE_ID(dbid number, started date);\n'
                 f'insert into {user}.G5_INSTANCE_ID select d.dbid,i.startup_time from v$database d cross join v$instance i;\ncommit;')
        require(oracle.sql(cid, setup, result), 'ORACLE_FIXTURE_SETUP')
        frame = f'{port}\n{user}\n{secret}\n'.encode('ascii')
        result['concurrency_step'], out = native.run_private('oracle-instance-concurrency', worker(cp, 'CONCURRENCY'),
                                                             work, 75, frame)
        require(out.stat().st_size <= 100, 'OUT_SIZE')
        result['concurrency'] = protocol(out.read_bytes())
        seed_and_crash(engine, cid, run, cp, frame, work)
        require(owned_stopped(cid, 137) and engine._owned(cid, run)['State'] == 'exited', 'ORACLE_RESTART_IDENTITY')
        with engine._request('POST', f'/containers/{cid}/start', (204,), wall_seconds=20):
            pass
        port = live_port(engine, cid, run)
        verify = (f'declare n number; begin select count(*) into n from {user}.G5_INSTANCE_ID s '
                  'cross join v$database d cross join v$instance i where d.dbid=s.dbid and i.startup_time>s.started; '
                  "if n != 1 then raise_application_error(-20010,'fixture'); end if; end;\n/")
        require(oracle.sql(cid, verify, result), 'ORACLE_RESTART_DATA_IDENTITY')
        proof, out = native.run_private('oracle-instance-recovery', worker(cp, 'RECOVER'), work, 25,
                                        f'{port}\n{user}\n{secret}\n'.encode('ascii'))
        require(out.stat().st_size < 80 and out.read_bytes() == b'ORACLE_INSTANCE RECOVER PASS\n', 'ORACLE_RECOVERY_PROTOCOL')
        result.update(crash_recovery='PASS', recovery_step=proof, crash_exit_code=137,
                      matching_dbid_and_new_startup=True, cgroup_limits_confirmed=True,
                      storage_quota_creation_confirmed=True, retained_before=len(original))
    finally:
        signal.alarm(0)
        engine.stop(cid, run, timeout=45)
        # Never remove a retained or unverified instance. This trial's data is the disposable fixture.
        require(cid not in original and engine._owned(cid, run)['State'] in ('created', 'exited'), 'ORACLE_RECLAIM_OWNERSHIP')
        with engine._request('DELETE', f'/containers/{cid}?force=false&v=false', (204,)):
            pass
        require(engine._owned(cid, run) is None and inventory() == original, 'ORACLE_RECLAIM_PROOF')
        result['retention_cleanup'] = 'PASS'
        result['retained_after'] = len(original)
        planned['phase'] = 'CLOSED'
        managed.save(journal, planned)


def main():
    args = sys.argv[1:]
    if args not in (['--prepare'], ['--run']):
        return 2
    perform = args == ['--run']
    result = {'schema_version': 1, 'requirement': 'RELEASE-014', 'status': 'BLOCKED', 'oracle_instance_g5': 'NOT RUN'}
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(sig, oracle.pool.schema.interrupted)
    signal.alarm(LIMITS['wall_seconds'] if perform else 100)
    try:
        result['input_sha512'] = h.hashes(sources())
        facts, image_id = platform_checks()
        result['provider_checks'] = facts
        result['stopped_managed_instances'] = len(inventory())
        if perform:
            require(all(facts.values()), 'ORACLE_PROVIDER_PRECONDITIONS')
            cap = authorized()
            result['approval_sha512'] = h.hashes((APPROVAL,))[APPROVAL]
            result.update(image=get_pin()['image'], platform='linux/arm64', server_version='23.26.4.0.0',
                          driver_version='23.26.4.0.0', limits=LIMITS)
        with oracle.pool.schema.workspace() as (work, cleanup):
            result['cleanup'] = cleanup
            cp = compile_fixture(work, result)
            if perform:
                with os.fdopen(os.open(managed.PRIVATE / 'RUN.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    for name in ('release-012-oracle.json', 'release-013-oracle.json', 'release-014-oracle.json'):
                        journal = managed.PRIVATE / name
                        require(not journal.exists() or json.loads(journal.read_text()).get('phase') == 'CLOSED',
                                'PRIOR_TRIAL_OPEN')
                    managed.preflight(work, LIMITS['instance_memory_mib'])
                    allowed_baseline(cap)
                    permitted = result['approval_sha512']
                    require(h.hashes((APPROVAL,))[APPROVAL] == permitted, 'ORACLE_APPROVAL_CHANGED')
                    with (managed.PRIVATE / f'release-014-{permitted}.claim').open('x') as claim:
                        claim.write(datetime.now(timezone.utc).isoformat() + '\n')
                        claim.flush()
                        os.fsync(claim.fileno())
                    run_db(work, cp, image_id, cap, result)
        require(cleanup.get('status') == 'PASS' and cleanup.get('remaining') is False, 'WORKSPACE_CLEANUP')
        require(result['input_sha512'] == h.hashes(sources()), 'INPUTS_CHANGED')
        result.update(status='PASS', oracle_instance_g5='PASS' if perform else 'NOT RUN')
        h.save(REPORT if perform else PREPARATION, result)
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        result['reason'] = str(error) if isinstance(error, oracle.Gate) else type(error).__name__
        if perform:
            managed.save(managed.PRIVATE / ('release-014-failure-' + secrets.token_hex(10) + '.json'), result)
    finally:
        signal.alarm(0)
    print(json.dumps({key: result[key] for key in ('status', 'oracle_instance_g5', 'provider_checks', 'reason') if key in result}))
    return 0 if result['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
