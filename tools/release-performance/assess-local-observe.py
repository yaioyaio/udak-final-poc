#!/usr/bin/env python3
"""Read-only preparation and evidence analysis for local Observe diagnostics."""

import argparse
import importlib.util
import json
import math
from pathlib import Path
import statistics
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
MAX_INPUT_BYTES = 128 * 1024
MAX_BLOCKS = 128
L1_FORK_PLAN = {
    "active_forks": 1,
    "benchmark_threads": 1,
    "paired_blocks_proposed": 3,
    "warmup_iterations": 5,
    "measurement_iterations": 5,
    "iteration_seconds": 1,
    "heap_mib": 512,
    "active_processor_count": 2,
}
# Proposed limits for the entire pilot batch, including A/A. No approval is implied.
L1_RESOURCE_PLAN = {
    "wall_seconds": 600,
    "peak_tree_rss_bytes": 1024**3,
    "tree_cpu_seconds": 180,
    "peak_process_cpu_seconds": 90,
    "peak_active_forks": L1_FORK_PLAN["active_forks"],
}


def g5_verifier():
    spec = importlib.util.spec_from_file_location("g5", ROOT / "tools/verify-product-g5.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    return verifier


def finite_number(value, minimum=0, maximum=10**12):
    return type(value) in (int, float) and minimum <= value <= maximum and math.isfinite(value)


def median_interval(differences):
    """Conservative two-sided 95% sign interval for independent paired blocks."""
    values = sorted(differences)
    count = len(values)
    # With a smaller sample even [min, max] may cover less than 95%.
    index = None
    tail = 0
    for rank in range(count // 2):
        tail += math.comb(count, rank)
        if 40 * tail > 2**count:
            break
        index = rank
    return None if index is None else [values[index], values[count - 1 - index]]


def paired_summary(pairs, relative=False):
    if not isinstance(pairs, list) or len(pairs) > MAX_BLOCKS:
        raise ValueError("Invalid block count")
    differences = []
    for row in pairs:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError("Invalid pair")
        baseline, observed = row
        if (not finite_number(baseline) or not finite_number(observed)
                or (relative and (baseline <= 0 or observed <= 0))):
            raise ValueError("Invalid sample")
        delta = observed - baseline
        if relative:
            delta = 100 * delta / baseline
        if not math.isfinite(delta):
            raise ValueError("Invalid difference")
        differences.append(delta)
    return {
        "blocks": len(differences),
        "median": statistics.median(differences) if differences else None,
        "confidence_interval": median_interval(differences),
    }


def resource_receipt_passes(receipt):
    if not isinstance(receipt, dict):
        return False
    for key, limit in L1_RESOURCE_PLAN.items():
        measurement = receipt.get(key)
        if not finite_number(measurement) or not 0 < measurement <= limit:
            return False
    if any(type(receipt[key]) is not int for key in ("peak_tree_rss_bytes", "peak_active_forks")):
        return False
    if receipt["tree_cpu_seconds"] < receipt["peak_process_cpu_seconds"]:
        return False
    return receipt.get("memory_warning_observed") is False and receipt.get("cleanup_confirmed") is True


def assess_l1(data):
    started = data["workload_started"]
    if type(started) is not bool:
        raise ValueError("Invalid workload state")
    if not started:
        return {"status": "NOT RUN"}
    if not resource_receipt_passes(data.get("resources")):
        return {"status": "INCONCLUSIVE", "reason": "RESOURCE_EVIDENCE"}

    aa = paired_summary(data["aa_ns_per_op"], relative=True)
    ab = paired_summary(data["ab_ns_per_op"], relative=True)
    absolute = paired_summary(data["ab_ns_per_op"])
    allocation_pairs = data["ab_alloc_bytes_per_op"]
    if len(allocation_pairs) != ab["blocks"]:
        raise ValueError("Allocation block count differs")
    allocation = paired_summary(allocation_pairs)
    result = {"status": "INCONCLUSIVE", "aa_percent": aa, "ab_percent": ab,
              "ab_ns_per_op": absolute, "ab_bytes_per_op": allocation}
    limit = data["regression_limit_percent"]
    if limit is None:
        return {**result, "reason": "REGRESSION_LIMIT_UNSET"}
    if not finite_number(limit, maximum=100) or limit <= 0:
        raise ValueError("Invalid regression limit")

    # Use one policy: A/A may account for at most half of the declared A/B margin.
    noise_limit = limit / 2
    result["aa_limit_percent"] = noise_limit
    if aa["confidence_interval"] is None or ab["confidence_interval"] is None:
        return {**result, "reason": "INSUFFICIENT_BLOCKS"}
    aa_low, aa_high = aa["confidence_interval"]
    if aa_low < -noise_limit or aa_high > noise_limit:
        return {**result, "reason": "AA_NOISE"}
    low, high = ab["confidence_interval"]
    if high <= limit:
        result["status"] = "PASS"
    elif low > limit:
        result["status"] = "FAIL"
    else:
        result["reason"] = "REGRESSION_LIMIT_OVERLAP"
    return result


def assess_l2_progress(report):
    """Classify an interrupted attempt without issuing an official p95 assessment."""
    claimed = report["workload_run_claimed"]
    profiles = report["profiles"]
    verifier = g5_verifier()
    performance = verifier.criteria()["performance"]
    if type(claimed) is not bool or not isinstance(profiles, dict) or profiles.keys() - performance["profiles"].keys():
        raise ValueError("Invalid trial state")
    if profiles and not claimed:
        raise ValueError("Unclaimed workload")
    rows = {}
    for name in performance["profiles"]:
        if name not in profiles:
            rows[name] = {"status": "NOT RUN"}
        else:
            row = profiles[name]
            has_measurement = {"assessment", "plain_ns", "observe_ns"} <= row.keys()
            rows[name] = {"status": "INCONCLUSIVE", "assessment_recorded": has_measurement}
            if has_measurement:
                recorded = verifier.compare(row["plain_ns"], row["observe_ns"], performance)
                if recorded != row["assessment"]:
                    raise ValueError("Recorded p95 differs")
                rows[name]["recorded_p95"] = recorded
                differences = [observed - baseline for baseline, observed
                               in zip(row["plain_ns"], row["observe_ns"], strict=True)]
                rows[name]["paired_delta_ns"] = {"pairs": len(differences),
                                                  "median": statistics.median(differences)}
    if all(row.get("assessment_recorded") for row in rows.values()):
        raise ValueError("Use the official G5 verifier for complete trials")
    return {"status": "INCONCLUSIVE" if profiles else "NOT RUN", "profiles": rows}


def local_plan():
    performance = g5_verifier().criteria()["performance"]
    return {
        "l1": {"execution": "NOT RUN", "approval": "PENDING", "target": "JDBC cache hit",
               "jmh": L1_FORK_PLAN, "resource_limits_proposed": L1_RESOURCE_PLAN,
               "regression_limit_percent": None},
        "l2": {"starts_per_database": performance["starts_per_database"], "limits": performance["limits"],
               "max_observe_p95_increase_percent": performance["max_observe_p95_increase_percent"]},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "l1", "l2-progress"))
    mode = parser.parse_args(argv).mode
    try:
        if mode == "plan":
            result = local_plan()
        else:
            raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
            if len(raw) > MAX_INPUT_BYTES:
                raise ValueError("Input exceeds bound")
            data = json.loads(raw)
            result = assess_l1(data) if mode == "l1" else assess_l2_progress(data)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, RecursionError):
        print(json.dumps({"error": "INVALID_EVIDENCE_OR_MODE"}))
        return 2
    print(json.dumps({"scope": "LOCAL_DIAGNOSTIC", **result}, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
