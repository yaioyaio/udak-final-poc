#!/usr/bin/env python3
"""Compare the pinned Observe cache-miss baseline with one approved commit."""

import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import statistics
import subprocess
import sys


TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parents[1]
RUN_ID = "IMPLICIT-QUERY-ID-AB-01"
APPROVAL = ROOT / "evidence" / f"OBSERVE-L1-{RUN_ID}-APPROVAL.json"
RESULT = ROOT / "evidence" / f"OBSERVE-L1-{RUN_ID}-RESULT.json"
ORDER = (("BASELINE", "CANDIDATE"), ("CANDIDATE", "BASELINE"), ("BASELINE", "CANDIDATE"))
MIN_BYTES_SAVED = 16

spec = importlib.util.spec_from_file_location("observe_jmh", TOOLS / "run-jmh-local-observe.py")
jmh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jmh)
TARGET = jmh.TARGETS["cache-miss"]
BASELINE = TARGET.measure_variant


def proposal(candidate):
    plan = jmh.proposal(RUN_ID, TARGET)
    if (re.fullmatch("[0-9a-f]{40}", candidate) is None or candidate == plan["source"]
            or jmh.git("rev-parse", candidate + "^{commit}").decode("ascii").strip() != candidate):
        raise ValueError("Candidate must identify a distinct commit")
    path = Path(__file__).resolve()
    plan["inputs_sha256"][path.relative_to(ROOT).as_posix()] = jmh.digest(jmh.file_bytes(path, 128 * 1024))
    return {**plan, "phase": "A/B", "source_revisions": {"BASELINE": plan["source"], "CANDIDATE": candidate},
            "order": [list(block) for block in ORDER], "min_bytes_saved_per_block": MIN_BYTES_SAVED}


def approved_hash(plan):
    data = jmh.file_bytes(APPROVAL, 32 * 1024)
    expected = {**plan, "status": "APPROVED", "approval_basis": "EXPLICIT_USER_CONFIRMATION"}
    if json.loads(data) != expected:
        raise jmh.Stopped("APPROVAL_REQUIRED")
    return jmh.digest(data)


def assess(blocks):
    if len(blocks) != len(ORDER):
        raise ValueError("Missing A/B block")
    for block in blocks:
        if set(block) != {"BASELINE", "CANDIDATE"}:
            raise ValueError("Invalid A/B block")
        for sample in block.values():
            if (len(sample) != 2 or not all(jmh.diagnosis.finite_number(value, minimum=0.000001)
                                           for value in sample)):
                raise ValueError("Invalid A/B sample")
    saved = [row["BASELINE"][1] - row["CANDIDATE"][1] for row in blocks]
    metrics = {arm: {"ns_per_op": statistics.median(row[arm][0] for row in blocks),
                     "bytes_per_op": statistics.median(row[arm][1] for row in blocks)}
               for arm in ("BASELINE", "CANDIDATE")}
    return {"status": "PASS" if min(saved) >= MIN_BYTES_SAVED else "FAIL",
            "baseline": metrics["BASELINE"], "candidate": metrics["CANDIDATE"], "bytes_saved_per_block": saved,
            "median_bytes_saved_per_op": statistics.median(saved),
            "median_percent_saved": statistics.median(100 * delta / row["BASELINE"][1]
                                                       for delta, row in zip(saved, blocks, strict=True))}


def execute(plan, report, cancelled):
    try:
        approval = approved_hash(plan)
    except (OSError, ValueError):
        raise jmh.Stopped("APPROVAL_REQUIRED") from None
    report["approval_sha256"] = approval
    if jmh.guard.memory_pressure(Path("/tmp").resolve()) != 1:
        raise jmh.Stopped("HOST_MEMORY_NOT_READY")
    schema = jmh.diagnosis.g5_verifier().schema
    marker = jmh.git_private("udak-observe-l1") / f"{RUN_ID}.claimed"
    lock = jmh.git_private("udak-g2-managed") / "RUN.lock"
    with os.fdopen(os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), "w") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if marker.exists() or RESULT.exists():
            raise jmh.Stopped("APPROVAL_ALREADY_CLAIMED")
        candidate = plan["source_revisions"]["CANDIDATE"]
        jmh.VARIANTS["CANDIDATE"] = candidate
        batch = None
        try:
            with schema.workspace() as (work, cleanup):
                report["cleanup"] = cleanup
                batch = jmh.Batch(work, report, True, cancelled)
                try:
                    jars = jmh.dependencies(work, batch)
                    paths = {"BASELINE": jmh.link(batch, BASELINE, jars, TARGET),
                             "CANDIDATE": jmh.link(batch, "CANDIDATE", jars, TARGET)}
                    if jmh.guard.memory_pressure(work) != 1:
                        raise jmh.Stopped("HOST_MEMORY_NOT_READY")
                    if proposal(candidate) != plan or approved_hash(plan) != approval:
                        raise jmh.Stopped("INPUTS_CHANGED")
                    batch.available()
                    with marker.open("x") as claim:
                        claim.write(approval + "\n")
                        claim.flush()
                        os.fsync(claim.fileno())
                    report["workload_run_claimed"] = True
                    for index, order in enumerate(ORDER):
                        measurements = {}
                        for lane, arm in enumerate(order):
                            measurements[arm] = jmh.sample(batch, paths[arm], 2 * index + lane, TARGET)
                        report["blocks"].append(measurements)
                    report["assessment"] = assess(report["blocks"])
                except jmh.guard.CleanupUnconfirmed:
                    raise schema.native.PreservationRequired("Query ID comparison cleanup unconfirmed") from None
        finally:
            if batch is not None:
                report["resources"] = batch.resources(cleanup)
    if not jmh.diagnosis.resource_receipt_passes(report["resources"]):
        raise jmh.Stopped("RESOURCE_EVIDENCE")
    report["status"] = report["assessment"]["status"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--proposal", metavar="CANDIDATE_COMMIT")
    modes.add_argument("--run", metavar="CANDIDATE_COMMIT")
    args = parser.parse_args()
    try:
        plan = proposal(args.proposal or args.run)
    except (OSError, ValueError, subprocess.SubprocessError):
        print(json.dumps({"status": "NOT RUN", "reason": "PLAN_INPUT_REJECTED"}))
        return 1
    if args.proposal:
        print(json.dumps({**plan, "approval": "PENDING"}))
        return 0

    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    for event in (signal.SIGINT, signal.SIGTERM):
        signal.signal(event, stop)
    report = {"schema_version": 1, "run_id": RUN_ID, "status": "NOT RUN", "source_revisions": plan["source_revisions"],
              "benchmark": plan["benchmark"], "workload_started": False, "workload_run_claimed": False,
              "real_database_starts": 0, "steps": {}, "blocks": []}
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
