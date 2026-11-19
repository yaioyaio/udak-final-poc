#!/usr/bin/env python3
"""Verify detached OpenPGP signatures in a disposable, offline local fixture."""
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / 'evidence/RELEASE-SIGNING-VALIDATION.json'
AUDIT = ROOT / '.git/udak-release-support'
POLICY = 'tools/phase6-release-policy.json'
CANDIDATE = 'evidence/PHASE6-VALIDATION.json'
SOURCES = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / 'core/src/main/java').rglob('*.java'))
INPUTS = (*SOURCES, 'tools/run-core-smoke.sh', 'tools/run-release-signing.py', 'tools/run-phase6.py',
          'tools/release-gate.py', 'udak-cli/udak_cli.py', POLICY, CANDIDATE, 'evidence/PHASE6-GATE.json')

spec = importlib.util.spec_from_file_location('release_signing_guard', ROOT / 'tools/run-phase6.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def read_output(work, name):
    path = work / (name + '.output')
    if path.stat().st_size > 16_384:
        raise ValueError('Signing output bound exceeded')
    return path.read_text(encoding='utf-8')


def check_gate(work, result):
    result['steps'].append(h.step('publication-gate', [sys.executable, '-B', 'tools/release-gate.py', '--format', 'json'],
                                  work, timeout=25, expected=2))
    gate = json.loads(read_output(work, 'publication-gate'))
    if (gate.get('status') != 'BLOCKED' or gate.get('authorize_publish') is not False
            or gate.get('phase6_evidence') != 'VERIFIED_EVIDENCE' or not isinstance(gate.get('blockers'), dict)):
        raise ValueError('Publication prerequisites were not verified')
    return {key: gate[key] for key in ('status', 'authorize_publish', 'phase6_evidence', 'operator_approvals', 'blockers')}


def fixtures(work, result):
    steps = result['steps']
    jvm = '_JAVA_OPTIONS=-Xmx256m -XX:MaxMetaspaceSize=128m -XX:ActiveProcessorCount=2'
    steps.append(h.step('core-smoke', ['/usr/bin/env', jvm, './tools/run-core-smoke.sh'], work, timeout=25))
    classes = work / 'classes'
    steps.append(h.step('compile-signing-fixture', h.p5.JAVAC + ['-d', str(classes), *SOURCES], work, timeout=25))
    artifact = work / 'core-signing-fixture.jar'
    steps.append(h.step('package-signing-fixture', ['jar', '-J-Xmx128m', '-J-XX:ActiveProcessorCount=2',
                        '--create', '--file', str(artifact), '-C', str(classes), '.'], work, timeout=15))
    release = json.loads((ROOT / CANDIDATE).read_text())
    manifest = work / 'signing-fixture-manifest.json'
    manifest.write_text(json.dumps({'scope': 'offline signing fixture', 'fixture_jar_sha512': h.guard.digest(artifact.read_bytes()),
                                    'historical_candidate_report_sha512': result['input_sha512'][CANDIDATE],
                                    'candidate_artifact_count': len(release['artifacts'])}, sort_keys=True) + '\n')
    return artifact, manifest


def agent_pid(output):
    matches = re.findall(r'^D ([0-9]{1,10})$', output, re.M)
    if len(matches) != 1 or int(matches[0]) <= 1:
        raise ValueError('Owned GnuPG agent identity unavailable')
    return int(matches[0])


def stopped(pid):
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def gpg_verify(work, result, inputs):
    tools = {name: shutil.which(name) for name in ('gpg', 'gpgconf', 'gpg-connect-agent')}
    if not all(tools.values()):
        raise ValueError('Local OpenPGP tools unavailable')
    signer, verifier = work / 'signer', work / 'verifier'
    for home in (signer, verifier):
        home.mkdir(mode=0o700)

    def run(name, binary, args, expected=0):
        result['steps'].append(h.step(name, [tools[binary], *map(str, args)], work,
                                      timeout=15, expected=expected, monitor=False))

    for label, home in (('signer', signer), ('verifier', verifier)):
        name = label + '-socket'
        run(name, 'gpgconf', ['--homedir', home, '--list-dirs', 'agent-socket'])
        if Path(read_output(work, name).strip()) != home / 'S.gpg-agent':
            raise ValueError('GnuPG agent socket outside owned scratch')

    def gpg(home):
        return ['--no-options', '--homedir', home, '--batch', '--no-tty', '--no-auto-key-retrieve', '--no-auto-key-locate']

    identity = 'UDAK Offline Signing Fixture'
    pid = None
    try:
        run('generate-fixture-signer', 'gpg', gpg(signer) + ['--pinentry-mode', 'loopback', '--passphrase', '',
                                                           '--quick-generate-key', identity, 'ed25519', 'sign', '1d'])
        run('fixture-agent-identity', 'gpg-connect-agent', ['--homedir', signer, '--no-autostart', 'GETINFO pid', '/bye'])
        pid = agent_pid(read_output(work, 'fixture-agent-identity'))
        public = work / 'fixture-pub.asc'
        run('export-fixture-public', 'gpg', gpg(signer) + ['--armor', '--output', public, '--export', identity])
        verify_base = gpg(verifier) + ['--no-autostart', '--status-fd', '1']
        run('import-fixture-public', 'gpg', verify_base + ['--import', public])
        proofs = {}
        for label, artifact in zip(('jar', 'manifest'), inputs):
            signature = work / (label + '.asc')
            run('sign-' + label, 'gpg', gpg(signer) + ['--pinentry-mode', 'loopback', '--passphrase', '',
                                                      '--local-user', identity, '--armor', '--output', signature,
                                                      '--detach-sign', artifact])
            if not signature.read_bytes().startswith(b'-----BEGIN PGP SIGNATURE-----\n'):
                raise ValueError('Detached OpenPGP signature missing')
            run('verify-' + label, 'gpg', verify_base + ['--verify', signature, artifact])
            if not re.search(r'^\[GNUPG:\] VALIDSIG [0-9A-F]{40,64} ', read_output(work, 'verify-' + label), re.M):
                raise ValueError('Independent public-key verification missing')
            changed = work / (label + '.modified')
            changed.write_bytes(artifact.read_bytes() + b'\nchanged\n')
            run('reject-modified-' + label, 'gpg', verify_base + ['--verify', signature, changed], expected=1)
            test = read_output(work, 'reject-modified-' + label)
            if '[GNUPG:] BADSIG ' not in test or '[GNUPG:] VALIDSIG ' in test:
                raise ValueError('Artifact alteration did not give a signature failure')
            proofs[label] = {'sha512': h.guard.digest(artifact.read_bytes()),
                             'detached_signature_verified': True, 'changed_bytes_rejected': True}
        result['signature_proofs'] = proofs
    finally:
        if (signer / 'S.gpg-agent').exists():
            run('stop-fixture-agent', 'gpgconf', ['--homedir', signer, '--kill', 'gpg-agent'])
        deadline = time.monotonic() + 3
        while pid is not None and not stopped(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        result['fixture_agent_stopped'] = stopped(pid) and not any(signer.glob('S.gpg-agent*'))
        if pid is not None and not result['fixture_agent_stopped']:
            raise ValueError('Owned GnuPG agent shutdown unconfirmed')


def main():
    if sys.argv[1:]:
        print('RELEASE_SIGNING INVALID_ARGUMENTS')
        return 2
    for event in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
        signal.signal(event, h.guard.interrupted)
    signal.alarm(150)
    result = {'schema_version': 1, 'scope': 'local OpenPGP fixture and publication gate only', 'status': 'FAIL',
              'started_at_utc': datetime.now(timezone.utc).isoformat(), 'steps': [], 'external_publications': 0,
              'production_keys_used': 0, 'containers_started': 0}
    AUDIT.mkdir(parents=True, exist_ok=True)
    try:
        with os.fdopen(os.open(AUDIT / 'SIGNING.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result['input_sha512'] = h.hashes(INPUTS)
            with h.workspace() as (work, cleanup):
                result['cleanup'] = cleanup
                result['publication_gate'] = check_gate(work, result)
                gpg_verify(work, result, fixtures(work, result))
                if result['input_sha512'] != h.hashes(INPUTS):
                    raise ValueError('Execution inputs changed')
            if not result.get('fixture_agent_stopped') or cleanup.get('temporary_directory_remaining') is not False:
                raise ValueError('Signing scratch cleanup incomplete')
            result['status'] = 'PASS'
            h.save(REPORT, result)
    except Exception as error:
        result['status'] = 'FAIL'
        result['failure_type'] = type(error).__name__
        if isinstance(error, RuntimeError):
            try:
                receipt = json.loads(str(error))
                if isinstance(receipt, dict) and 'exit_code' in receipt:
                    result['failed_step'] = receipt
            except ValueError:
                pass
        h.save(AUDIT / ('signing-failed-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.json'), result)
    finally:
        signal.alarm(0)
    print(json.dumps({key: value for key, value in result.items() if key != 'input_sha512'}))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
