#!/usr/bin/env python3
"""Run the approved PostgreSQL A/A diagnostic without a CPU idle floor."""

import importlib.util
from pathlib import Path
import sys


RUN_ID = "OBSERVE-PG-BASELINE-AA-ACTIVE-HOST-01"
SOURCE = "tools/release-performance/run-pg-baseline-aa-active-host.py"
BASELINE = Path(__file__).with_name("run-pg-baseline-aa.py")


def main():
    spec = importlib.util.spec_from_file_location("pg_baseline", BASELINE)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    standard_proposal = baseline.proposal
    original = standard_proposal()
    baseline.approval_sha(original)

    def active_host_proposal():
        plan = standard_proposal()
        plan["input_sha512"].update(baseline.h.hashes((SOURCE,)))
        plan.update(acceptance_eligible=False, cpu_idle_floor_required=False,
                    standard_plan_sha512=baseline.guard.digest(original))
        return plan

    stem = f"evidence/PRODUCT-G5-{RUN_ID}"
    baseline.RUN_ID = RUN_ID
    baseline.PREPARATION, baseline.APPROVAL, baseline.PREFLIGHT, baseline.RESULT = (
        stem + suffix + ".json" for suffix in ("-PREPARATION", "-APPROVAL", "-PREFLIGHT", "-RESULT")
    )
    baseline.FLOOR = {**baseline.FLOOR, "preflight_idle_permille": 0, "live_idle_permille": 0}
    baseline.proposal = active_host_proposal
    if sys.argv[1:] == ["register-approval"]:
        plan = active_host_proposal()
        baseline.guard.save_once(baseline.ROOT / baseline.APPROVAL, baseline.authorization(plan))
        print(f"{RUN_ID} approval registered")
        return 0
    return baseline.main()


if __name__ == "__main__":
    sys.exit(main())
