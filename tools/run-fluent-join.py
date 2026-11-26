#!/usr/bin/env python3
"""Verify the Fluent JOIN contract with a bounded local Spring/H2 run."""
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "evidence/FLUENT-JOIN-VALIDATION.json"
DEPENDENCIES = "tools/phase2-dependencies.json"
LIMITS = ("-Xmx256m", "-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2")
MODULES = ("core", "udak-api", "jdbc-spring")
TESTS = (
    ("compiler", "dev.udak.core.CompilerContractTest", None),
    ("crud", "dev.udak.api.CrudApiContractTest", None),
    ("spring-jdbc", "dev.udak.jdbc.SpringJdbcExecutorTest", None),
    ("fluent-join", "dev.udak.api.FluentJoinContractTest", "Fluent JOIN contract checks"),
    ("fluent-join-h2", "dev.udak.jdbc.FluentJoinJdbcTest", "Fluent JOIN Spring/H2 checks"),
)

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("phase2", ROOT / "tools/run-phase2.py")
phase2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phase2)
guard = phase2.guard


def check_host():
    if sys.platform == "darwin":
        pressure = subprocess.check_output(
            ["/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
            stderr=subprocess.DEVNULL, timeout=3,
        )
        if pressure.strip() != b"1":
            raise RuntimeError("HOST_MEMORY_PRESSURE")


def verify(result):
    check_host()
    result["documentation"] = guard.verify_documents()
    sources = sorted(str(path.relative_to(ROOT)) for module in MODULES
                     for path in (ROOT / module / "src").rglob("*.java"))
    inputs = (*sources, DEPENDENCIES, "tools/run-phase1.py", "tools/run-phase2.py",
              "tools/run-core-smoke.sh", "tools/run-fluent-join.py")
    hashes = {path: guard.digest((ROOT / path).read_bytes()) for path in inputs}
    with guard.workspace("udak-fluent-join-") as (work, cleanup):
        result["cleanup"] = cleanup
        for key in ("_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS"):
            if key in os.environ:
                del os.environ[key]
        os.environ["TMPDIR"] = str(work)

        def step(name, command):
            check_host()
            proof = guard.run_step(name, command, work)
            if not proof["child_reaped"] or not proof["process_group_quiesced"]:
                raise RuntimeError("CHILD_CLEANUP")
            result["steps"].append(proof)

        step("core-smoke", ["/usr/bin/env", "_JAVA_OPTIONS=" + " ".join(LIMITS), "./tools/run-core-smoke.sh"])
        classpath, result["dependencies"] = phase2.dependencies(
            work, json.loads((ROOT / DEPENDENCIES).read_text())
        )
        classes = work / "classes"
        classpath = os.pathsep.join(map(str, (classes, *classpath)))
        step("compile", ["javac", *("-J" + limit for limit in LIMITS), "--release", "17",
                         "-cp", classpath, "-d", str(classes), *sources])
        for name, main_class, protocol in TESTS:
            step(name, ["java", *LIMITS, "-cp", classpath, main_class])
            if protocol is not None:
                output = (work / (name + ".output")).read_text()
                count = re.fullmatch(re.escape(protocol) + r": ([1-9][0-9]*)\n", output)
                if not count:
                    raise ValueError("TEST_PROTOCOL")
                result["assertions"][name] = int(count.group(1))
    if cleanup["status"] != "PASS" or cleanup["temporary_directory_remaining"]:
        raise RuntimeError("WORKSPACE_CLEANUP")
    if any(guard.digest((ROOT / path).read_bytes()) != digest for path, digest in hashes.items()):
        raise RuntimeError("INPUTS_CHANGED")
    result.update(status="PASS", input_sha512=hashes)


def main():
    if sys.argv[1:]:
        return 2
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, guard.interrupted)
    signal.alarm(150)
    result = {"schema_version": 1, "requirement": "T-007", "status": "FAIL", "steps": [],
              "assertions": {}, "java_compile_release": 17, "containers_started": 0,
              "render_profiles": ["POSTGRESQL", "MYSQL", "SQLSERVER", "ORACLE_19", "ORACLE_11"],
              "external_database_execution": "NOT RUN",
              "limits": {"wall_seconds": 150, "child_cpu_seconds": 30, "heap_mib": 256, "active_cpus": 2}}
    try:
        verify(result)
        if not REPORT.exists():
            with REPORT.open("x", encoding="utf-8") as report:
                report.write(json.dumps(result, indent=2) + "\n")
    except Exception as error:
        result.update(status="FAIL", failure_type=type(error).__name__)
        if str(error) in ("HOST_MEMORY_PRESSURE", "TEST_PROTOCOL", "INPUTS_CHANGED"):
            result["reason"] = str(error)
        else:
            try:
                detail = json.loads(str(error))
            except ValueError:
                pass
            else:
                if isinstance(detail, dict):
                    result["failed_step"] = {key: detail[key] for key in
                                             ("name", "exit_code", "diagnostics") if key in detail}
    finally:
        signal.alarm(0)
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("input_sha512", "dependencies")}))
    return int(result["status"] != "PASS")


if __name__ == "__main__":
    sys.exit(main())
