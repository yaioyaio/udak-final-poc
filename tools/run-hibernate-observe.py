#!/usr/bin/env python3
"""Run the protected Hibernate inspector composition and compatibility checks."""

import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import sys
import traceback

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "evidence/HIBERNATE-INSPECTOR-VALIDATION.json"
SPEC = importlib.util.spec_from_file_location("phase3", ROOT / "tools/run-phase3.py")
phase3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(phase3)
guard = phase3.guard
JAVA_LIMITS = ["-Xmx256m", "-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2"]
CHECKS = ("EXISTING_INSPECTOR", "BUSINESS_RESULT", "MIXED_ROLLBACK", "EFFECTIVE_SQL_OBSERVATION")
COMPATIBILITY = "dev.udak.compat.LegacyCompatibilityTest"


def output(work, step):
    return (work / (step + ".output")).read_text(encoding="utf-8")


def execute(result):
    with guard.workspace("udak-hibernate-inspector-") as (work, cleanup):
        result["cleanup"] = cleanup
        os.putenv("TMPDIR", str(work))
        for key in ("_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS"):
            os.unsetenv(key)
        os.putenv("_JAVA_OPTIONS", " ".join(JAVA_LIMITS))
        steps = result["steps"]
        steps.append(guard.run_step("core-smoke", ["./tools/run-core-smoke.sh"], work))
        os.unsetenv("_JAVA_OPTIONS")
        classpath, sources, dependencies, compile_step = phase3.build(work)
        steps.append(compile_step)
        java = ["java", *JAVA_LIMITS, "-cp", classpath]

        adapter = "adapter-contract"
        steps.append(guard.run_step(adapter, [*java, "dev.udak.observe.LegacyObserveAdapterContractTest"], work))
        count = re.fullmatch(r"Legacy Observe adapter contract checks: ([1-9][0-9]{0,4})\n", output(work, adapter))
        if count is None:
            raise ValueError("Adapter evidence protocol invalid")
        result["adapter_checks"] = int(count[1])

        legacy = "compatibility-h2"
        steps.append(guard.run_step(legacy, [*java, COMPATIBILITY], work, timeout=45))
        result["legacy_h2"] = phase3.protocol("H2", output(work, legacy), 0)
        if result["legacy_h2"]["status"] != "PASS":
            raise ValueError("Legacy H2 evidence protocol invalid")

        inspector = "inspector-h2"
        steps.append(guard.run_step(inspector, [*java, COMPATIBILITY, "--hibernate-inspector"], work, timeout=45))
        expected = ["H2_INSPECTOR PASS", f"CHECKS={len(CHECKS)}", "CLEANUP=CONFIRMED",
                    *(f"SCENARIO={name}:PASS" for name in CHECKS)]
        if output(work, inspector).splitlines() != expected:
            raise ValueError("Inspector H2 evidence protocol invalid")
        result["inspector_h2"] = {"status": "PASS", "scenarios": dict.fromkeys(CHECKS, "PASS")}
        result["dependency_manifest_sha512"] = dependencies["manifest_sha512"]
        result["input_sha512"] = {
            str(path.relative_to(ROOT)): guard.digest(path.read_bytes())
            for path in sorted([*sources, Path(__file__), ROOT / "tools/run-phase3.py",
                                ROOT / "tools/run-phase1.py", ROOT / "tools/run-core-smoke.sh"])
        }


def main():
    if len(sys.argv) != 1:
        return 2
    result = {"schema_version": 1, "requirement": "NEXT-003", "scope": "Hibernate inspector composition",
              "status": "FAIL", "steps": [], "java_compile_release": 17,
              "external_db_integration": "NOT RUN", "containers_started": 0,
              "limits": {"wall_seconds": 180, "child_cpu_seconds": 30, "heap_mib": 256, "active_cpus": 2}}
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, guard.interrupted)
    signal.alarm(180)
    try:
        execute(result)
    except Exception as error:
        result["failure_type"] = type(error).__name__
        result["failure_locations"] = [
            {"file": Path(frame.filename).name, "line": frame.lineno}
            for frame in traceback.extract_tb(error.__traceback__)
        ]
    else:
        result["status"] = "PASS"
        REPORT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    finally:
        signal.alarm(0)
    print(json.dumps({key: value for key, value in result.items() if key != "input_sha512"}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
