#!/usr/bin/env python3
"""Attribute allocation on the fixed Observe JDBC cache-miss path without a database."""

import argparse
import fcntl
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

from comparison_sources import replace


TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parents[1]
RUN_ID = "JDBC-ALLOCATION-ATTRIBUTION-01"
PROBE = TOOLS / "ObserveAllocationProbe.java"
CLASS = "dev.udak.observe.ObserveAllocationProbe"
APPROVAL = ROOT / "evidence" / f"OBSERVE-L1-{RUN_ID}-APPROVAL.json"
RESULT = ROOT / "evidence" / f"OBSERVE-L1-{RUN_ID}-RESULT.json"
STEP_LIMIT_SECONDS = 25
BLOCKS = 3
OPS_PER_BLOCK = 200_000
MAX_BASELINE_DIFFERENCE_PERCENT = 10
MAX_UNATTRIBUTED_BYTES_PER_OP = 16

spec = importlib.util.spec_from_file_location("observe_jmh", TOOLS / "run-jmh-local-observe.py")
jmh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jmh)
TARGET = jmh.TARGETS["cache-miss"]


def proposal():
    plan = jmh.proposal(RUN_ID, TARGET)
    for path in (Path(__file__).resolve(), PROBE, TOOLS / "comparison_sources.py"):
        plan["inputs_sha256"][path.relative_to(ROOT).as_posix()] = jmh.digest(jmh.file_bytes(path, 128 * 1024))
    return {**plan, "phase": "ALLOCATION_ATTRIBUTION", "sequence": ["JMH", "ATTRIBUTION", "JMH"],
            "attribution_warmup_ops": OPS_PER_BLOCK, "attribution_blocks": BLOCKS,
            "attribution_ops_per_block": OPS_PER_BLOCK, "attribution_step_limit_seconds": STEP_LIMIT_SECONDS,
            "max_baseline_difference_percent": MAX_BASELINE_DIFFERENCE_PERCENT,
            "max_unattributed_bytes_per_op": MAX_UNATTRIBUTED_BYTES_PER_OP}


def approved_hash(plan):
    data = jmh.file_bytes(APPROVAL, 32 * 1024)
    if json.loads(data) != {**plan, "status": "APPROVED", "approval_basis": "EXPLICIT_USER_CONFIRMATION"}:
        raise jmh.Stopped("APPROVAL_REQUIRED")
    return jmh.digest(data)


def instrument_shape(source):
    return replace(replace(source,
        "        return new Lexer(sql).scan(digest);",
        """        ObserveAllocationProbe.begin(ObserveAllocationProbe.NORMALIZATION);
        return new Lexer(sql).scan(digest);"""),
        "            return new SqlShape(ObservationDigest.SQL_SHAPE.hash(digest, tokens, tokenBytes), kind, NONE);",
        """            ObserveAllocationProbe.end(ObserveAllocationProbe.NORMALIZATION);
            ObserveAllocationProbe.begin(ObserveAllocationProbe.FINGERPRINT);
            String fingerprint = ObservationDigest.SQL_SHAPE.hash(digest, tokens, tokenBytes);
            ObserveAllocationProbe.end(ObserveAllocationProbe.FINGERPRINT);
            ObserveAllocationProbe.begin(ObserveAllocationProbe.NORMALIZATION);
            SqlShape shape = new SqlShape(fingerprint, kind, NONE);
            ObserveAllocationProbe.end(ObserveAllocationProbe.NORMALIZATION);
            return shape;""")


def instrument_observer(source):
    changes = (
        ("            MessageDigest digest = ObservationDigest.newSha256();",
         """            ObserveAllocationProbe.begin(ObserveAllocationProbe.FINGERPRINT);
            MessageDigest digest = ObservationDigest.newSha256();
            ObserveAllocationProbe.end(ObserveAllocationProbe.FINGERPRINT);"""),
        ("            sink.accept(event, shape.reason());",
         """            sink.accept(event, shape.reason());
            ObserveAllocationProbe.end(ObserveAllocationProbe.EVENT);"""),
        ("""        String id = sameSource ? cached.queryIdHash()
                : ObservationDigest.SOURCE_SHAPE.hash(digest, framework.name() + ":" + shape.hash());
        SqlObservation event""",
         """        ObserveAllocationProbe.begin(ObserveAllocationProbe.FINGERPRINT);
        String id = sameSource ? cached.queryIdHash()
                : ObservationDigest.SOURCE_SHAPE.hash(digest, framework.name() + ":" + shape.hash());
        ObserveAllocationProbe.end(ObserveAllocationProbe.FINGERPRINT);
        ObserveAllocationProbe.begin(ObserveAllocationProbe.EVENT);
        SqlObservation event"""),
    )
    for original, patched in changes:
        source = replace(source, original, patched)
    return source


def compile_probe(batch, original_classpath):
    location = batch.work / "allocation"
    location.mkdir()
    classes = location / "classes"
    classes.mkdir()
    sources = jmh.sources(jmh.VARIANTS[TARGET.measure_variant], location)
    for name, instrument in (("SqlShape.java", instrument_shape), ("SqlObserver.java", instrument_observer)):
        source = location / name
        source.write_text(instrument(source.read_text(encoding="utf-8")), encoding="utf-8")
    probe = location / PROBE.name
    probe.write_bytes(jmh.file_bytes(PROBE, 32 * 1024))
    batch.step("compile-attribution", [jmh.executable("javac"), "-J-Xmx256m", "-J-XX:MaxMetaspaceSize=128m",
               "-J-XX:ActiveProcessorCount=2", "--release", "17", "-proc:none",
               "-cp", original_classpath, "-d", str(classes), str(probe), *sources], 30)
    return os.pathsep.join((str(classes), original_classpath))


def parse_blocks(output):
    header, *rows = output.splitlines()
    if header != "OBSERVE_ALLOCATION PASS" or len(rows) != BLOCKS:
        raise ValueError("Attribution receipt incomplete")
    blocks = []
    for row in rows:
        match = re.fullmatch(r"BLOCK ([0-9]{1,9}) ([0-9]{1,12}) ([0-9]{1,12}) ([0-9]{1,12}) ([0-9]{1,12})", row)
        if not match:
            raise ValueError("Invalid attribution block")
        ops, normalization, fingerprint, event, total = map(int, match.groups())
        residual = total - normalization - fingerprint - event
        if ops != OPS_PER_BLOCK or min(normalization, fingerprint, event) <= 0 or residual < 0 or total > ops * 10_000:
            raise ValueError("Invalid allocation partition")
        blocks.append(dict(ops=ops, normalization=normalization, fingerprint=fingerprint,
                           event=event, residual=residual, total=total))
    return blocks


def assess(blocks, baseline):
    stages = ("normalization", "fingerprint", "event")
    median = {key: statistics.median(row[key] / row["ops"] for row in blocks)
              for key in (*stages, "residual", "total")}
    reference = statistics.median(pair[1] for pair in baseline)
    if not jmh.diagnosis.finite_number(reference, minimum=1):
        raise ValueError("Invalid reference allocation")
    difference = 100 * (median["total"] - reference) / reference
    top = max(stages, key=median.__getitem__)
    uncertainty = max(abs(row["total"] / row["ops"] - reference) + row["residual"] / row["ops"] for row in blocks)
    stable_rank = all(row[top] / row["ops"] > max(row[k] / row["ops"] for k in stages if k != top) + uncertainty
                      for row in blocks)
    concordant = all(
        abs(100 * (row["total"] / row["ops"] - sample[1]) / sample[1]) <= MAX_BASELINE_DIFFERENCE_PERCENT
        and row["residual"] <= MAX_UNATTRIBUTED_BYTES_PER_OP * row["ops"]
        for row in blocks for sample in baseline
    )
    return {"status": "PASS" if stable_rank and concordant else "INCONCLUSIVE",
            "baseline_bytes_per_op": reference, "instrumented_median_bytes_per_op": median,
            "instrumented_difference_percent": difference,
            "priority_stage": top if stable_rank and concordant else None}


def execute(plan, report, cancelled):
    try:
        approval = approved_hash(plan)
    except (OSError, ValueError):
        raise jmh.Stopped("APPROVAL_REQUIRED") from None
    report["approval_sha256"] = approval
    if RESULT.exists() or jmh.guard.memory_pressure(Path("/tmp").resolve()) != 1:
        raise jmh.Stopped("RESULT_EXISTS_OR_HOST_MEMORY_NOT_READY")
    schema = jmh.diagnosis.g5_verifier().schema
    marker = jmh.git_private("udak-observe-l1") / f"{RUN_ID}.claimed"
    lock = jmh.git_private("udak-g2-managed") / "RUN.lock"
    with os.fdopen(os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), "w") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if marker.exists() or RESULT.exists():
            raise jmh.Stopped("APPROVAL_ALREADY_CLAIMED")
        batch = None
        try:
            with schema.workspace() as (work, cleanup):
                report["cleanup"] = cleanup
                batch = jmh.Batch(work, report, True, cancelled)
                try:
                    jars = jmh.dependencies(work, batch)
                    original = jmh.link(batch, TARGET.measure_variant, jars, TARGET)
                    instrumented = compile_probe(batch, original)
                    if jmh.guard.memory_pressure(work) != 1 or proposal() != plan or approved_hash(plan) != approval:
                        raise jmh.Stopped("HOST_MEMORY_OR_INPUTS_CHANGED")
                    batch.available()
                    with marker.open("x") as claim:
                        claim.write(approval + "\n")
                        claim.flush()
                        os.fsync(claim.fileno())
                    report["workload_run_claimed"] = True
                    report["baseline_samples"] = [jmh.sample(batch, original, 0, TARGET)]
                    output = batch.step("sample-attribution", jmh.java_command(instrumented, jmh.plan["heap_mib"], CLASS),
                                        STEP_LIMIT_SECONDS)
                    report["blocks"] = parse_blocks(jmh.file_bytes(output, 8192).decode("ascii"))
                    report["baseline_samples"].append(jmh.sample(batch, original, 1, TARGET))
                    report["assessment"] = assess(report["blocks"], report["baseline_samples"])
                except jmh.guard.CleanupUnconfirmed:
                    raise schema.native.PreservationRequired("Allocation cleanup unconfirmed") from None
        finally:
            if batch is not None:
                report["resources"] = batch.resources(cleanup)
    if not jmh.diagnosis.resource_receipt_passes(report["resources"]):
        raise jmh.Stopped("RESOURCE_EVIDENCE")
    report["status"] = report["assessment"]["status"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--proposal", action="store_true")
    modes.add_argument("--run", action="store_true")
    args = parser.parse_args()
    plan = proposal()
    if args.proposal:
        print(json.dumps({**plan, "approval": "PENDING"}))
        return 0

    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    for event in (signal.SIGINT, signal.SIGTERM):
        signal.signal(event, stop)
    report = {"schema_version": 1, "run_id": RUN_ID, "status": "NOT RUN", "source": plan["source"],
              "workload_started": False, "workload_run_claimed": False, "real_database_starts": 0, "steps": {}}
    try:
        execute(plan, report, lambda: stopping)
    except jmh.Stopped as error:
        report.update(status="INCONCLUSIVE" if report["workload_run_claimed"] else "NOT RUN", reason=str(error))
    except (ValueError, KeyError, TypeError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        report.update(status="INCONCLUSIVE" if report["workload_run_claimed"] else "FAIL", reason=type(error).__name__)
    if report["workload_run_claimed"]:
        with RESULT.open("x", encoding="utf-8") as output:
            output.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, allow_nan=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
