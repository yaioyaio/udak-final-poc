#!/usr/bin/env python3
"""Verify repeatability of the same PostgreSQL baseline on an observed quiet host."""
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import statistics
import subprocess
import sys
import time

from comparison_sources import replace
from lexer_crossover_sources import pinned_source
from macos_cpu_window import CpuWindow, cpu_reader, quiet, sample

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = 'OBSERVE-PG-BASELINE-AA-01'
STEM = f'evidence/PRODUCT-G5-{RUN_ID}'
PREPARATION, APPROVAL, PREFLIGHT, RESULT = (STEM + suffix + '.json' for suffix in
                                          ('-PREPARATION', '-APPROVAL', '-PREFLIGHT', '-RESULT'))
PRIOR_RUNNER = 'tools/release-performance/run-postgres-comparison.py'
REFERENCE = 'OBSERVE-LEXER-WORDS-02'
CANDIDATE = 'OBSERVE-JDBC-HOTPATH-01'
REVISION = '4d1bc0bfeac7c08ff83fea70a2e48550fb08d097'
FLOOR = {'preflight_idle_permille': 900, 'live_idle_permille': 800, 'samples': 7, 'seconds': 5}
STARTS = 80

spec = importlib.util.spec_from_file_location('aa_guard', ROOT / PRIOR_RUNNER)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
performance, review, schema, native, h = guard.performance, guard.review, guard.schema, guard.native, guard.h
require = guard.require


def proposal():
    c = review.criteria()['performance']
    ref = review.performance_result(c, REFERENCE)['POSTGRESQL']
    require(ref['status'] == 'FAIL' and review.candidate_status(CANDIDATE)['status'] == 'PASS', 'REFERENCE_UNVERIFIED')
    approval, result = performance.run_paths(REFERENCE)
    files = (*performance.performance_inputs(), approval, result, review.candidate_evidence_path(CANDIDATE),
             PRIOR_RUNNER, guard.HOST_PROBE, 'tools/run-phase1.py', 'tools/run-phase4.py', 'tools/run-phase5.py',
             review.read(performance.SPRING)['h2_license_file'], 'tools/release-performance/lexer_crossover_sources.py',
             'tools/release-performance/comparison_sources.py', 'tools/release-performance/attribution_sources.py',
             'tools/release-performance/macos_cpu_window.py', 'tools/release-performance/run-pg-baseline-aa.py',
             'tools/release-performance/test-pg-baseline-aa.py')
    percent = c['max_observe_p95_increase_percent']
    return {'schema_version': 1, 'run_id': RUN_ID, 'candidate': CANDIDATE, 'revision': REVISION, 'diagnostic_only': True,
            'reference': REFERENCE, 'absolute_noise_budget_ns': ref['baseline_p95_ns'] * percent // 100,
            'arm_p95_gap_budget_percent': percent, 'limit': dict(FLOOR), 'limits': c['limits'],
            'binary': {'version': c['profiles']['POSTGRESQL']['server_version'], 'server_sha256':
                       review.read(review.PILOT)['profiles']['POSTGRESQL']['native_runtime']['server_sha256']},
            'starts': STARTS, 'pairs': 32, 'connection_count': 1, 'input_sha512': h.hashes(files)}


def authorization(plan):
    return {'schema_version': 1, 'run_id': RUN_ID, 'authorized_runs': 1, 'status': 'APPROVED',
            'approval_basis': 'EXPLICIT_USER_CONFIRMATION', 'proposal_sha512': guard.digest(plan)}


def approval_sha(plan):
    require((ROOT / APPROVAL).is_file(), 'SEPARATE_APPROVAL_REQUIRED')
    require(guard.canonical(review.read(APPROVAL)) == guard.canonical(authorization(plan)), 'APPROVAL_SCOPE_CHANGED')
    return h.hashes((APPROVAL,))[APPROVAL]


def fixture(java):
    original = ('''import dev.udak.observe.FingerprintStatus;
import dev.udak.observe.Framework;
import dev.udak.observe.ObservationPoint;
import dev.udak.observe.ObservationSink;
import dev.udak.observe.SqlObservation;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.StatementKind;
import dev.udak.observe.jdbc.ObserveDataSource;
''')
    changes = (
        (original, ''),
        ('            require(args.length == 2 &&', '''            if (args.length == 1 && args[0].equals("--contract")) {
                try (Connection connection = DriverManager.getConnection("jdbc:h2:mem:udak_pg_aa_contract")) {
                    seed(connection, Engine.POSTGRESQL);
                    Trial trial = new Trial(connection);
                    trial.sample(false, 1, 0);
                    trial.sample(true, 1, 0);
                    require(trial.completed == 2 && trial.plainSamples[0] > 0 && trial.observedSamples[0] > 0);
                }
                report.println("PG_BASELINE_AA_CONTRACT PASS");
                return;
            }
            require(args.length == 2 &&'''),
        ('args.length == 2 &&', 'args.length == 2 && args[0].equals("POSTGRESQL") &&'),
        ('int MEASURED = 96;', 'int MEASURED = 32;'),
        ('''    private static final class EventCounter implements ObservationSink {
        private int count;
        private SqlObservation last;

        @Override
        public void accept(SqlObservation event) {
            count++;
            last = event;
        }
    }

''', ''),
        ('        private final EventCounter events = new EventCounter();\n', ''),
        ('        private final JdbcTemplate observed;\n', ''),
        ('        private SqlObservation firstEvent;','        private final StringJoiner schedule = new StringJoiner(",");'),
        ('            observed = new JdbcTemplate(new ObserveDataSource(shared, new SqlObserver(events)));\n', ''),
        ('            observed.setQueryTimeout(TIMEOUT_SECONDS);\n', ''),
        ('''                int id = 1 + pair % ROWS;
                boolean observedFirst = pair % 2 != 0;
                sample(observedFirst, id, pair - WARMUP);
                sample(!observedFirst, id, pair - WARMUP);''', '''                int block = pair / 10;
                int slot = pair % 10;
                int id = 1 + (slot + 2 * block) % ROWS;
                boolean bFirst = ((id - 1 + block) & 1) != 0;
                int index = slot < 2 ? -1 : block * 8 + slot - 2;
                sample(bFirst, id, index);
                sample(!bFirst, id, index);'''),
        ('''            JdbcTemplate template = observe ? observed : plain;
            int previousEvents = events.count;
''',''),
        ('            template.query(SELECT,','            plain.query(SELECT,'),
        ('''            require(elapsed > 0 && events.count == previousEvents + (observe ? 1 : 0));
            if (observe) {
                SqlObservation event = events.last;
                require(event.framework() == Framework.JDBC && event.point() == ObservationPoint.JDBC_EXECUTE);
                require(event.statementKind() == StatementKind.SELECT && event.fingerprintStatus() == FingerprintStatus.NORMALIZED);
                if (firstEvent == null) firstEvent = event;
                require(firstEvent.equals(event));
            }''','            require(elapsed > 0);'),
        ('            starts[completed++] = started;', '            starts[completed++] = started;\n'
         '            schedule.add(Integer.toString(2 * id + (observe ? 1 : 0)));'),
        ('completed == TOTAL && events.count == WARMUP + MEASURED', 'completed == TOTAL'),
        ('"PLAIN_NS"', '"A_NS"'),
        ('"OBSERVE_NS"', '"B_NS"'),
        ('"PRODUCT_PERF profile="', '"PG_BASELINE_AA profile="'),
        ('" events=" + events.count + " errors=0', '" events=0 errors=0'),
        ('            report.println(observedLine);','''            report.println(observedLine);
            report.println("SCHEDULE " + schedule);
            long[] gaps = new long[TOTAL - 1];
            for (int i = 1; i < TOTAL; i++) gaps[i - 1] = starts[i] - starts[i - 1];
            report.println(samplesLine("GAPS_NS", gaps));'''),
    )
    for old, new in changes:
        java = replace(java, old, new)
    return java


def workload_order():
    for block in range(4):
        for slot in range(10):
            row = 1 + (slot + 2 * block) % 8
            first = (row - 1 + block) & 1
            yield 2 * row + first
            yield 2 * row + 1 - first


def assess(protocol, plan):
    lines = protocol.splitlines()
    require(len(lines) == 5, 'PROTOCOL_LENGTH')
    header = re.fullmatch(
        r'PG_BASELINE_AA profile=POSTGRESQL starts=80 completed=80 warmup_per_arm=8 measured_per_arm=32'
        r' verified_rows=80 events=0 errors=0 max_in_flight=1 max_rolling_second=([1-8]) min_spacing_ns=([0-9]{1,11})',
        lines[0])
    require(header and guard.numbers(lines[3], 'SCHEDULE', STARTS) == list(workload_order()), 'COUNTS_OR_ORDER')
    gaps = guard.numbers(lines[4], 'GAPS_NS', STARTS - 1)
    require((guard.pacing(gaps, plan['limits']), min(gaps)) == (int(header[1]), int(header[2])), 'PACING_RECEIPT')
    a, b = guard.numbers(lines[1], 'A_NS', 32), guard.numbers(lines[2], 'B_NS', 32)
    require(min(a + b) > 0, 'INVALID_TIMING')
    p95_a, p95_b = sorted(a)[30], sorted(b)[30]
    paired = [abs(y - x) for x, y in zip(a, b, strict=True)]
    tail = sorted(paired)[30]
    allowance = plan['absolute_noise_budget_ns']
    pct = plan['arm_p95_gap_budget_percent']
    passed = 200 * abs(p95_b - p95_a) <= pct * (p95_a + p95_b) and tail <= allowance
    return {'status': 'PASS' if passed else 'NOT REPRODUCIBLE', 'a_p95_ns': p95_a, 'b_p95_ns': p95_b,
            'p95_gap_percent_of_mean': round(200 * abs(p95_a - p95_b) / (p95_a + p95_b), 4),
            'paired_abs_median_ns': statistics.median(paired), 'paired_abs_p95_ns': tail,
            'pairs_above_reference_allowance': sum(delta > allowance for delta in paired),
            'starts': STARTS, 'measured_pairs': 32, 'max_rolling_second': int(header[1]), 'min_spacing_ns': int(header[2])}


def preflight(plan, probe, work):
    policy = plan['limit']
    rows = []
    stamp, ticks = time.monotonic_ns(), probe()
    for _ in range(policy['samples']):
        time.sleep(policy['seconds'])
        now, current = time.monotonic_ns(), probe()
        rows.append({'cpu': sample(ticks, current, now - stamp), 'memory_pressure': guard.host.memory_pressure(work)})
        stamp, ticks = now, current
    return rows


def ready(rows, policy):
    return (len(rows) == policy['samples'] and
            all(row['memory_pressure'] == 1 and type(row['memory_pressure']) is int
                and 5_000_000_000 <= row['cpu']['interval_ns']
                and quiet(row['cpu'], policy['preflight_idle_permille'], 7_000_000_000) for row in rows))


def build(work, plan, result):
    result['binary'] = native._fingerprint(native.PG / 'postgres', 'postgresql', work)
    require(result['binary'] == plan['binary'], 'DB_BINARY')
    jdbc, result['jdbc_dependencies'] = schema.pinned_drivers(work)
    spring, result['spring_dependencies'] = schema.g2.phase2.dependencies(work, review.read(performance.SPRING))
    source = fixture(pinned_source(ROOT, plan['revision'], performance.FIXTURE, plan['input_sha512'][performance.FIXTURE]))
    result['fixture_sha512'] = hashlib.sha512(source.encode()).hexdigest()
    path = work / 'ProductG5PerformanceMain.java'
    path.write_text(source)
    classes = work / 'classes'
    classes.mkdir()
    cp = os.pathsep.join(map(str, (*jdbc, *spring)))
    result['compile'], _ = native.run_private('aa-compile', performance.limited(
        [*schema.base.JAVAC, '-cp', cp, '-d', str(classes), str(path)], plan), work, 30)
    classpath = os.pathsep.join((str(classes), cp))
    command = [*schema.base.JAVA, '-cp', classpath, 'ProductG5PerformanceMain', '--contract']
    result['contract'], output = native.run_private('aa-contract', performance.limited(command, plan), work, 15)
    expect = b'PG_BASELINE_AA_CONTRACT PASS\n'
    require(guard.reaped(result['compile']) and guard.reaped(result['contract'])
            and output.stat().st_size == len(expect) and output.read_bytes() == expect, 'OFFLINE_CONTRACT')
    return classpath


def prepare(plan, result):
    with guard.protected_workspace() as (work, cleanup):
        result['cleanup'] = cleanup
        guard.check_host(work)
        with guard.watch_host(work):
            build(work, plan, result)
        require(proposal() == plan, 'INPUTS_CHANGED')
    require(guard.clean(cleanup), 'WORKSPACE_CLEANUP')
    result['status'] = 'PASS'
    guard.save_once(ROOT / PREPARATION, result)


def preparation(plan):
    proof = review.read(PREPARATION)
    require(proof['status'] == 'PASS' and proof['run_id'] == RUN_ID
            and proof['proposal_sha512'] == guard.digest(plan) and proof['workload_run_claimed'] is False
            and proof['postgresql_initialized'] is False and guard.reaped(proof['compile'])
            and guard.reaped(proof['contract'])
            and guard.clean(proof['cleanup']), 'PREPARATION_UNVERIFIED')
    return proof


@contextmanager
def watch_cpu(window):
    base = native._Child

    class QuietChild(base):
        def _sample(self):
            window.observe()
            super()._sample()

    native._Child = QuietChild
    try:
        yield
    finally:
        native._Child = base


def run(plan, result):
    approval = approval_sha(plan)
    prep = preparation(plan)
    probe = cpu_reader()
    marker = ROOT / '.git/udak-product-g5' / (RUN_ID + '.claimed')
    require(not marker.exists() and not (ROOT / RESULT).exists(), 'APPROVAL_ALREADY_USED')
    # Read-only quiet window first, before entering scratch or compiling.
    first = preflight(plan, probe, Path('/tmp'))
    result['initial_host_samples'] = first
    require(ready(first, plan['limit']), 'HOST_NOT_QUIET')
    try:
        with guard.protected_workspace() as (work, cleanup):
            result['cleanup'] = cleanup
            require(not marker.exists() and not (ROOT / RESULT).exists(), 'APPROVAL_ALREADY_USED')
            guard.check_host(work)
            with guard.watch_host(work):
                cp = build(work, plan, result)
                require(all(result[key] == prep[key] for key in
                            ('binary', 'jdbc_dependencies', 'spring_dependencies', 'fixture_sha512')), 'INPUTS_CHANGED')
                result['host_samples'] = preflight(plan, probe, work)
                require(ready(result['host_samples'], plan['limit']), 'HOST_NOT_QUIET')
                require(proposal() == plan and approval_sha(plan) == approval, 'INPUTS_CHANGED')
                guard.check_host(work)
                guard.claim(marker, approval)
                result.update(workload_run_claimed=True, approval_sha512=approval, status='INCONCLUSIVE')
                window = CpuWindow(result.setdefault('live_host_samples', []), plan['limit']['live_idle_permille'], probe)
                with watch_cpu(window):
                    result['postgresql_initialization_attempted'] = True
                    with native.instance('postgresql', work) as (port, private, runtime):
                        result.update(native_runtime=runtime, postgresql_initialized=True)
                        require(runtime['loopback_listener_owned'] is True
                                and all(runtime[k] == v for k, v in plan['binary'].items()), 'DB_LISTENER_IDENTITY')
                        command = [*schema.base.JAVA, '-cp', cp, 'ProductG5PerformanceMain', 'POSTGRESQL', str(port)]
                        result['client'], output = native.run_private('aa-measure', performance.limited(command, plan), work,
                            performance.CLIENT_SECONDS, (private + '\n').encode())
                        require(guard.reaped(result['client']) and 0 < output.stat().st_size <= guard.PROTOCOL_BYTES,
                                'CLIENT_RECEIPT')
                        protocol = output.read_text(encoding='ascii')
                        result['assessment'] = assess(protocol, plan)
                        result['protocol'] = protocol
                        result['live_window'] = window.finish()
                require(runtime['server_stopped'] is True and runtime['process_groups_quiesced'] is True, 'DB_CLEANUP')
        require(guard.clean(cleanup) and live_quiet(result, plan), 'CLEANUP_OR_CPU_COVERAGE')
        result['status'] = result['assessment']['status']
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        if result['workload_run_claimed']:
            result['stop_reason'] = guard.failure_code(error)
        raise
    finally:
        if result['workload_run_claimed']:
            guard.save_once(ROOT / RESULT, result)


def live_quiet(result, plan):
    rows = result['live_host_samples']
    coverage = result['live_window']
    span = sum(row['interval_ns'] for row in rows)
    return (all(quiet(row, plan['limit']['live_idle_permille'], 3_000_000_000) for row in rows)
            and 0 <= coverage['tail_ns'] <= 1_100_000_000
            and span + coverage['tail_ns'] == coverage['elapsed_ns']
            and span >= 9_000_000_000)


def verify(plan):
    result = review.read(RESULT)
    prep = preparation(plan)
    runtime = result['native_runtime']
    require(result['run_id'] == RUN_ID and result['status'] in ('PASS', 'NOT REPRODUCIBLE')
            and result['diagnostic_only'] is True and result['workload_run_claimed'] is True
            and result['postgresql_initialized'] is True and result['approval_sha512'] == approval_sha(plan)
            and result['proposal_sha512'] == guard.digest(plan) and guard.clean(result['cleanup'])
            and all(guard.reaped(result[key]) for key in ('client', 'compile', 'contract'))
            and result['fixture_sha512'] == prep['fixture_sha512']
            and runtime['server_stopped'] is True and runtime['process_groups_quiesced'] is True
            and runtime['loopback_listener_owned'] is True and all(runtime[k] == v for k, v in plan['binary'].items())
            and ready(result['initial_host_samples'], plan['limit']) and ready(result['host_samples'], plan['limit'])
            and live_quiet(result, plan) and 0 < len(result['protocol']) <= guard.PROTOCOL_BYTES, 'RESULT_UNVERIFIED')
    outcome = assess(result['protocol'], plan)
    require(outcome == result['assessment'] and outcome['status'] == result['status'], 'ASSESSMENT_CHANGED')
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('proposal', 'preflight', 'prepare', 'run', 'verify'))
    args = parser.parse_args()
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, schema.interrupted)
    result = {'status': 'NOT RUN', 'run_id': RUN_ID, 'diagnostic_only': True,
              'workload_run_claimed': False, 'postgresql_initialized': False}
    signal.alarm(300)
    try:
        plan = proposal()
        result['proposal_sha512'] = guard.digest(plan)
        if args.mode == 'proposal':
            result.update({key: val for key, val in plan.items() if key != 'input_sha512'})
        elif args.mode == 'preflight':
            rows = preflight(plan, cpu_reader(), Path('/tmp'))
            result.update(host_samples=rows, status='READY' if ready(rows, plan['limit']) else 'NOT RUN')
            guard.save_once(ROOT / PREFLIGHT, result)
        elif args.mode == 'prepare':
            prepare(plan, result)
        elif args.mode == 'run':
            run(plan, result)
        else:
            result = verify(plan)
        info = {k: result[k] for k in ('run_id', 'status', 'proposal_sha512', 'postgresql_initialized',
                    'host_samples', 'workload_run_claimed', 'assessment', 'cleanup') if k in result}
        print(json.dumps(info if args.mode != 'verify' else result, sort_keys=True))
        return 0 if result['status'] in ('PASS', 'READY') or args.mode == 'proposal' else 1
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'INCONCLUSIVE' if result['workload_run_claimed'] else 'NOT RUN',
                          'reason': guard.failure_code(error), 'workload_run_claimed': result['workload_run_claimed'],
                          'postgresql_initialized': result['postgresql_initialized'],
                          'host_samples': result.get('host_samples', result.get('initial_host_samples')),
                          'cleanup': result.get('cleanup')}, sort_keys=True))
        return 1
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    sys.exit(main())
