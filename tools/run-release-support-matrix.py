#!/usr/bin/env python3
"""Verify and consolidate existing release evidence without starting a database."""
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / 'evidence/RELEASE-SUPPORT-MATRIX.json'
HISTORICAL = ('evidence/G2-REAL-VALIDATION.json', 'evidence/PHASE3-GATE.json', 'evidence/PHASE5-GATE.json')
DEMO = 'evidence/RELEASE-DEMO-VALIDATION.json'
APPROVAL = 'evidence/RELEASE-SUPPORT-APPROVAL.json'
SIGNING = 'evidence/RELEASE-SIGNING-VALIDATION.json'
RECOVERY = 'evidence/DB-RECOVERY-VALIDATION.json'
SCHEMA = 'evidence/SCHEMA-REGRESSION-VALIDATION.json'


def load(path):
    spec = importlib.util.spec_from_file_location('matrix_' + Path(path).stem, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


support = load('tools/run-release-support.py')
demo = load('tools/run-release-demo.py')
signing = load('tools/run-release-signing.py')
hashes = support.approval.h.hashes


def read(path):
    return support.approval.read_report(path)


def require(condition, code):
    if not condition:
        raise ValueError(code)


def historical_gate(verifier_path, report_path, aggregate):
    verifier = load(verifier_path)
    recorded = read(report_path)
    require(recorded['execution_reports_sha512'] == hashes(verifier.INPUTS)
            and recorded['verifier_sha512'] == hashes([verifier_path])[verifier_path], 'HISTORICAL_HASH_MISMATCH')
    actual = aggregate(verifier, [read(name) for name in verifier.INPUTS])
    require(all(recorded.get(k) == v for k, v in actual.items()), 'HISTORICAL_GATE_MISMATCH')
    return actual


def verify_g2(verifier, batches):
    for batch in batches:
        for field in ('source_sha512', 'harness_sha512', 'manifest_sha512'):
            require(batch[field] == hashes(batch[field]), 'G2_INPUT_MISMATCH')
    return verifier.verify(batches)


def matrix():
    evidence = hashes((*HISTORICAL, DEMO, APPROVAL, SIGNING, RECOVERY, SCHEMA, 'tools/run-release-support-matrix.py'))
    g2 = historical_gate('tools/verify-real-g2.py', HISTORICAL[0], verify_g2)
    g3 = historical_gate('tools/verify-phase3.py', HISTORICAL[1], lambda verifier, batches: verifier.verify(*batches))
    support.approval.preserved_gates()  # Frozen G4, G6 local CI and expansion recovery evidence.
    g4 = read('evidence/PHASE5-REAL-VALIDATION.json')
    existing = {}
    for name, profile in g2['profiles'].items():
        existing[name] = {'scope': 'fixed image functional checks', 'server_version': profile['server_version'],
                          'driver_version': profile['driver_version'], 'platform': profile['platform'],
                          'crud_transaction_cases': profile['checks'], 'observe_cases': g3['profiles'][name]['checks'],
                          'selective_rewrite_cases': g4['profiles'][name]['checks']}

    live = read(APPROVAL)
    recovery = read(RECOVERY)
    schema = read(SCHEMA)
    require(live['status'] == 'PASS' and live['input_sha512'] == support.input_hashes()
            and live['cleanup']['remaining'] is False and live['docker_containers_started'] == 0
            and schema['status'] == 'PASS' and schema['input_sha512'] == support.schema.input_hashes(),
            'LIVE_EVIDENCE_MISMATCH')
    require(set(live['profiles']) == {'POSTGRESQL', 'MYSQL'} and
            live['profiles']['POSTGRESQL']['result_sha256'] == live['profiles']['MYSQL']['result_sha256'],
            'LIVE_PROFILE_MISMATCH')
    additions = {}
    for name, row in live['profiles'].items():
        require(row['status'] == 'PASS' and row['native_runtime']['server_stopped'] is True
                and row['native_runtime']['process_groups_quiesced'] is True and
                all(row['scenarios'].get(key) == {'status': 'PASS', 'connections_acquired': count, 'statements_prepared': count}
                    for key, count in support.SCENARIOS.items()), 'LIVE_SCENARIO_INCOMPLETE')
        bases = (recovery['profiles'][name], schema['profiles'][name]['identity'])
        require(all(base['server_version'] == row['server_version'] and base['driver_version'] == row['driver_version']
                    for base in bases), 'NATIVE_VERSION_MISMATCH')
        additions[name] = {'server_version': row['server_version'], 'driver_version': row['driver_version'],
                           'approval_history_cases': len(support.SCENARIOS), 'schema_query_cases': len(schema['profiles'][name]['queries']),
                           'cancel_and_recovery_cases': len(recovery['profiles'][name]['scenarios'])}

    tested = read(DEMO)
    require(tested['status'] == 'PASS' and tested['inputs_sha512'] == hashes(demo.source_paths())
            and tested['harness_sha512'] == hashes(('tools/run-release-demo.py', 'tools/run-phase6.py'))
            and tested['prior_evidence_sha512'] == hashes(demo.BASELINES)
            and tested['junit']['test_count'] == len(demo.TESTS) and tested['startup']['application_closed'] is True
            and tested['java_version'].startswith('17.') and tested['cleanup']['temporary_directory_remaining'] is False,
            'DEMO_EVIDENCE_MISMATCH')
    signed = read(SIGNING)
    gate = signed['publication_gate']
    require(signed['status'] == 'PASS' and signed['input_sha512'] == hashes(signing.INPUTS)
            and signed['external_publications'] == signed['production_keys_used'] == 0
            and set(signed['signature_proofs']) == {'jar', 'manifest'}
            and all(proof['detached_signature_verified'] and proof['changed_bytes_rejected']
                    for proof in signed['signature_proofs'].values())
            and gate['status'] == 'BLOCKED' and gate['authorize_publish'] is False,
            'SIGNING_OR_GATE_MISMATCH')
    require(evidence == hashes(evidence), 'EVIDENCE_CHANGED_DURING_REVIEW')
    return {'schema_version': 1, 'evidence_review': 'PASS', 'production_release': gate['status'],
            'authorize_publish': False, 'product_support': 'NOT CERTIFIED', 'release_blockers': gate['blockers'],
            'historical_profiles': existing, 'native_additions': additions,
            'jdk17_demo': {'java_version': tested['java_version'], 'junit_cases': tested['junit']['test_count'],
                           'packaged_startup': tested['startup']['status']},
            'local_signing': {'verified_signatures': 2, 'changed_inputs_rejected': 2},
            'not_run': ['G5 performance and concurrency', 'SQL Server and Oracle expanded native scenarios',
                        'production signing and publication', 'vendor platform certification'],
            'evidence_sha512': evidence}


def main():
    if sys.argv[1:]:
        print('RELEASE_SUPPORT_MATRIX INVALID_ARGUMENTS')
        return 2
    try:
        result = matrix()
        if not REPORT.exists() or read(REPORT.relative_to(ROOT)) != result:
            signing.h.save(REPORT, result)
        print(json.dumps({key: value for key, value in result.items() if key != 'evidence_sha512'}))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'evidence_review': 'FAIL', 'failure_type': type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
