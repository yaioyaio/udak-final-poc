#!/usr/bin/env python3
"""Run the recorded one-time bounded G5 pilot against owned native fixtures."""
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
AUDIT = ROOT / '.git/udak-g5-pilot'
REPORT = ROOT / 'evidence/RELEASE-G5-PILOT.json'
DECISION = 'evidence/RELEASE-G0-G5-DECISION.json'
SOURCE = 'tools/release-g5/G5PilotMain.java'
FIELDS = ('starts', 'completed', 'reads', 'commits', 'rollbacks', 'verified', 'errors', 'max_in_flight',
          'max_rolling_second', 'min_spacing_us', 'p50_us', 'p95_us', 'max_us')
PROFILES = ('POSTGRESQL', 'MYSQL')
CLIENT_SECONDS = 45


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


schema = load('g5_native_baseline', 'tools/run-schema-regression.py')
approval = load('g5_approval_scope', 'tools/verify-release-approval-scope.py')
native, h = schema.native, schema.h
INPUTS = (*approval.INPUTS, DECISION, SOURCE, 'tools/run-g5-pilot.py', schema.DRIVERS,
          'evidence/RELEASE-APPROVAL-SCOPE.json')


def approval_record():
    cli = approval.cli
    with cli.directory(ROOT.parts[1:]) as fd:
        scope = cli.read_report(fd, approval.SCOPE)
        candidate = cli.read_report(fd, approval.CANDIDATE)
        baseline = cli.read_report(fd, approval.SUPPORT)
        proposal = cli.read_report(fd, 'evidence/RELEASE-APPROVAL-SCOPE.json')
        decision = cli.read_report(fd, DECISION)
    approval.verify_scope(scope, candidate, baseline)
    hashes = h.hashes((approval.SCOPE, 'evidence/RELEASE-APPROVAL-SCOPE.json'))
    if (decision.get('schema_version') != 1 or decision.get('candidate_version') != scope['candidate_version']
            or decision.get('approval_basis') != 'EXPLICIT_USER_CONFIRMATION' or decision.get('authorize_publish') is not False
            or decision.get('scope_sha512') != hashes[approval.SCOPE]
            or decision.get('scope_verification_sha512') != hashes['evidence/RELEASE-APPROVAL-SCOPE.json']
            or proposal.get('status') != 'PASS' or proposal['input_sha512'][approval.SCOPE] != decision['scope_sha512']
            or decision.get('g5') != {'decision': 'APPROVED', 'approved_runs': 1, 'scope': scope['g5']}):
        raise ValueError('Approved pilot scope missing or changed')
    return scope['g5'], baseline['profiles']


def parse_protocol(output, profile, limits):
    prefix = f'G5_RESULT profile={profile}'
    pattern = re.escape(prefix) + ''.join(r' ' + field + r'=([0-9]{1,9})' for field in FIELDS) + r'\n'
    response = re.fullmatch(pattern, output)
    if not response:
        raise ValueError('Invalid G5 fixture proof')
    counts = dict(zip(FIELDS, map(int, response.groups())))
    expected = {'starts': 48, 'completed': 48, 'reads': 16, 'commits': 16, 'rollbacks': 16,
                'verified': 48, 'errors': 0, 'max_in_flight': limits['max_in_flight']}
    if (any(counts[key] != value for key, value in expected.items())
            or not 1 <= counts['max_rolling_second'] <= limits['max_starts_per_second']
            or counts['min_spacing_us'] < limits['min_start_spacing_ms'] * 1000
            or not 0 <= counts['p50_us'] <= counts['p95_us'] <= counts['max_us'] <= CLIENT_SECONDS * 1_000_000):
        raise ValueError('Workload or latency proof differs from approved bounds')
    return counts


def claim_run(marker, decision_digest):
    with os.fdopen(os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'w') as stream:
        json.dump({'decision_sha512': decision_digest, 'status': 'STARTED',
                   'started_at_utc': datetime.now(timezone.utc).isoformat()}, stream)
        stream.flush()
        os.fsync(stream.fileno())


def run_profile(profile, work, classpath, limits, baseline, result, before_workload):
    item = result['profiles'][profile] = {'status': 'FAIL'}
    label = 'g5-' + profile.lower()
    with native.instance(profile.lower(), work) as (port, password, receipt):
        item['native_runtime'] = receipt
        versions = limits['profiles'][profile]
        if (receipt.get('loopback_listener_owned') is not True or receipt['version'] != versions['server_version']
                or receipt['server_sha256'] != baseline['native_runtime']['server_sha256']):
            raise ValueError('Native fixture differs from approved identity')
        # The server suppresses its stdout/stderr. Limit the client file outputs separately from data files.
        cap_logs = 'import os,resource,sys; n=int(sys.argv[1]); resource.setrlimit(resource.RLIMIT_FSIZE,(n,n)); os.execvp(sys.argv[2],sys.argv[2:])'
        command = [sys.executable, '-I', '-S', '-c', cap_logs, str(limits['child_log_bytes']),
                   *schema.base.JAVA, '-cp', classpath, 'G5PilotMain', profile, str(port)]
        before_workload()
        try:
            step, output = native.run_private(label, command, work, CLIENT_SECONDS, (password + '\n').encode('ascii'))
        except RuntimeError:
            output = work / (label + '.output')
            if output.is_file() and output.stat().st_size <= 2048:
                error = re.fullmatch(r'G5_ERROR stage=(INPUT|CONNECT|IDENTITY|SETUP|WORKLOAD|VERIFY|CLOSE)\n',
                                     output.read_text(encoding='ascii', errors='replace'))
                if error:
                    item['fixture_error_stage'] = error[1]
            raise
        if output.stat().st_size > 2048 or not step['process_group_quiesced'] or not step['child_reaped']:
            raise ValueError('Owned client proof incomplete')
        item.update(versions=versions, observations=parse_protocol(output.read_text(encoding='ascii'), profile, limits),
                    client_step=step, retained_client_output_bytes=output.stat().st_size)
    if not receipt['server_stopped'] or not receipt['process_groups_quiesced']:
        raise native.PreservationRequired('Owned G5 fixture shutdown unconfirmed')
    item['status'] = 'PASS'


def execute(work, limits, baseline, result, before_workload):
    result['stage'] = 'native-preflight'
    for profile, binary in (('POSTGRESQL', native.PG / 'postgres'), ('MYSQL', native.MYSQL / 'mysqld')):
        identity = native._fingerprint(binary, profile.lower(), work)
        if (identity['version'] != limits['profiles'][profile]['server_version']
                or identity['server_sha256'] != baseline[profile]['native_runtime']['server_sha256']):
            raise ValueError('Native binary preflight failed')
    result['stage'] = 'pinned-drivers'
    jars, result['jdbc_dependencies'] = schema.pinned_drivers(work)
    classes = work / 'classes'
    result['stage'] = 'compile'
    result['compile_step'] = h.step('compile-g5-pilot', schema.base.JAVAC + ['-d', str(classes), str(ROOT / SOURCE)], work)
    cp = os.pathsep.join(map(str, [classes, *jars]))
    for profile in PROFILES:
        result['stage'] = profile
        run_profile(profile, work, cp, limits, baseline[profile], result, before_workload)


def main():
    if sys.argv[1:]:
        print('G5_PILOT INVALID_ARGUMENTS')
        return 2
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, schema.interrupted)
    started = time.monotonic()
    result = {'schema_version': 1, 'status': 'FAIL', 'scope': 'approved bounded initial G5 pilot',
              'started_at_utc': datetime.now(timezone.utc).isoformat(), 'profiles': {},
              'docker_containers_started': 0, 'product_performance_certification': 'NOT GRANTED',
              'latency_scope': 'prepared JDBC work and transaction outcome, excluding pacing and intentional synchronization',
              'not_run': ['production workload', 'connection pools', 'SQL Server', 'Oracle', 'unknown commit recovery',
                          'new cancellation and session-loss tests (separate functional evidence)']}
    run_claimed = False
    signal.alarm(approval.G5_LIMITS['max_wall_seconds'])
    try:
        AUDIT.mkdir(parents=True, exist_ok=True)
        lock_dir = ROOT / '.git/udak-g2-managed'
        lock_dir.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(lock_dir / 'RUN.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result['stage'] = 'approval'
            result['input_sha512'] = h.hashes(INPUTS)
            decision_digest = result['input_sha512'][DECISION]
            marker = AUDIT / (decision_digest + '.started')
            if marker.exists() or REPORT.exists():
                raise ValueError('Recorded pilot has already been claimed')
            limits, baseline = approval_record()
            result.update(approval_decision_sha512=decision_digest, limits=limits)

            def before_workload():
                nonlocal run_claimed
                if not run_claimed:
                    claim_run(marker, decision_digest)
                    run_claimed = True

            with schema.workspace() as (work, cleanup):
                result['cleanup'] = cleanup
                execute(work, limits, baseline, result, before_workload)
                result['stage'] = 'final-verification'
                if result['input_sha512'] != h.hashes(INPUTS):
                    raise ValueError('Pilot inputs changed')
            if cleanup.get('status') != 'PASS' or cleanup.get('remaining') is not False:
                raise ValueError('G5 scratch cleanup incomplete')
            result['status'] = 'PASS'
            del result['stage']
    except Exception as error:
        result['failure_type'] = type(error).__name__
        if isinstance(error, RuntimeError):
            try:
                receipt = json.loads(str(error))
                if isinstance(receipt, dict) and 'exit_code' in receipt:
                    result['failed_step'] = receipt
            except ValueError:
                pass
    finally:
        signal.alarm(0)
        result['workload_run_claimed'] = run_claimed
        result['wall_seconds'] = round(time.monotonic() - started, 3)
        if run_claimed:
            h.p5.p4.save(REPORT, result)
        elif AUDIT.is_dir():
            suffix = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
            h.p5.p4.save(AUDIT / ('preflight-' + suffix + '.json'), result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('input_sha512', 'jdbc_dependencies')}))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
