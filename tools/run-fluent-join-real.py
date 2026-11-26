#!/usr/bin/env python3
"""Verify Fluent JOIN through Spring JDBC on owned PostgreSQL and MySQL fixtures."""
from contextlib import contextmanager
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import sys


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "evidence/FLUENT-JOIN-REAL-DB-VALIDATION.json"
PROFILES = {"POSTGRESQL": "17.11", "MYSQL": "8.0.46"}
MAIN = "dev.udak.jdbc.FluentJoinRealJdbcTest"
CHECKS = 11


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sys.dont_write_bytecode = True
fluent = load("fluent_local", "tools/run-fluent-join.py")
schema = load("fluent_native_workspace", "tools/run-schema-regression.py")
native = schema.native


def inputs():
    sources = sorted(path.relative_to(ROOT).as_posix() for module in fluent.MODULES
                     for path in (ROOT / module / "src").rglob("*.java"))
    support = ("tools/run-fluent-join-real.py", "tools/run-fluent-join.py", "tools/run-schema-regression.py",
               "tools/schema-native.py", "tools/run-phase2.py", "tools/run-phase1.py", "tools/run-g2.py",
               "tools/run-sql-inventory.py", "tools/run-core-smoke.sh", fluent.DEPENDENCIES, schema.DRIVERS)
    manifest = json.loads((ROOT / fluent.DEPENDENCIES).read_text())
    return sources, schema.h.hashes((*sources, *support, manifest["h2_license_file"]))


@contextmanager
def watch_memory():
    base = native._Child

    class MemoryCheckedChild(base):
        def _sample(self):
            fluent.check_host()
            super()._sample()

    native._Child = MemoryCheckedChild
    try:
        yield
    finally:
        native._Child = base


def checked_step(result, name, args, work, timeout=30, private_input=None):
    fluent.check_host()
    proof, output = native.run_private(name, args, work, timeout, private_input)
    if not proof["child_reaped"] or not proof["process_group_quiesced"]:
        raise native.PreservationRequired("JOIN child cleanup unconfirmed")
    result["steps"].append(proof)
    return output


def run_local(result, work, classpath):
    checked_step(result, "core-smoke", ["/usr/bin/env", "_JAVA_OPTIONS=" + " ".join(fluent.LIMITS),
                                        str(ROOT / "tools/run-core-smoke.sh")], work)
    for name, entry, label in fluent.TESTS:
        output = checked_step(result, name, [*schema.base.JAVA, "-cp", classpath, entry], work)
        if label:
            count = re.fullmatch(re.escape(label) + r": ([1-9][0-9]*)\n", output.read_text(encoding="ascii"))
            if not count:
                raise ValueError("LOCAL_PROTOCOL")
            result["assertions"][name] = int(count[1])
    if result["assertions"] != {"fluent-join": 52, "fluent-join-h2": CHECKS}:
        raise ValueError("LOCAL_ASSERTION_COUNTS")


def run_profile(result, profile, work, classpath):
    fluent.check_host()
    scenario = {"status": "NOT RUN"}
    result["profiles"][profile] = scenario
    scenario["startup_attempted"] = True
    with native.instance(profile.lower(), work) as (port, password, runtime):
        scenario["native_runtime"] = runtime
        if not runtime["loopback_listener_owned"] or runtime["version"] != PROFILES[profile]:
            raise ValueError("DB_RUNTIME_IDENTITY")
        output = checked_step(result, "join-" + profile.lower(),
                              [*schema.base.JAVA, "-cp", classpath, MAIN, profile, str(port)],
                              work, private_input=(password + "\n").encode("ascii"))
        expected = f"FLUENT_JOIN_REAL {profile} {PROFILES[profile]} {schema.PROFILES[profile]} {CHECKS}\n"
        if output.read_bytes() != expected.encode("ascii"):
            raise ValueError("JDBC_IDENTITY_OR_ASSERTIONS")
        scenario.update(server_version=PROFILES[profile], driver_version=schema.PROFILES[profile], assertions=CHECKS)
    if not runtime["server_stopped"] or not runtime["process_groups_quiesced"]:
        raise native.PreservationRequired("JOIN server cleanup unconfirmed")
    scenario["status"] = "PASS"


def verify(result):
    fluent.check_host()
    lock_path = ROOT / ".git" / "udak-g2-managed" / "RUN.lock"
    lock_path.parent.mkdir(exist_ok=True)
    with os.fdopen(os.open(lock_path, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600), "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        sources, expected = inputs()
        with schema.workspace() as (work, cleanup):
            result["cleanup"] = cleanup
            spring, result["spring_dependencies"] = fluent.phase2.dependencies(
                work, json.loads((ROOT / fluent.DEPENDENCIES).read_text()))
            drivers, result["jdbc_dependencies"] = schema.pinned_drivers(work)
            classes = work / "classes"
            classes.mkdir()
            cp = os.pathsep.join(map(str, (classes, *spring, *drivers)))
            with watch_memory():
                checked_step(result, "compile", [*schema.base.JAVAC, "-cp", cp, "-d", str(classes),
                                                  *(str(ROOT / source) for source in sources)], work)
                run_local(result, work, cp)
                for profile in PROFILES:
                    run_profile(result, profile, work, cp)
            if inputs() != (sources, expected):
                raise ValueError("INPUTS_CHANGED")
            result["input_sha512"] = expected
        if cleanup["status"] != "PASS" or cleanup["remaining"]:
            raise ValueError("WORKSPACE_CLEANUP")


def main():
    if sys.argv[1:]:
        return 2
    for event in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
        signal.signal(event, schema.interrupted)
    signal.alarm(260)
    result = {"schema_version": 1, "requirement": "T-007", "status": "FAIL", "profiles": {}, "steps": [],
              "assertions": {}, "compile_release": 17, "docker_containers_started": 0,
              "limits": {"wall_seconds": 260, "database_parallelism": 1, "client_timeout_seconds": 30,
                         "jvm_heap_mib": 256, "jvm_active_cpus": 2}}
    try:
        verify(result)
        result["status"] = "PASS"
        try:
            with REPORT.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(result, indent=2) + "\n")
        except FileExistsError:
            # A repeat reports its current outcome on stdout and preserves the recorded receipt.
            pass
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        result.update(status="FAIL", failure_type=type(error).__name__)
        reason = str(error)
        if reason in ("HOST_MEMORY_PRESSURE", "LOCAL_PROTOCOL", "LOCAL_ASSERTION_COUNTS",
                      "DB_RUNTIME_IDENTITY", "JDBC_IDENTITY_OR_ASSERTIONS", "INPUTS_CHANGED",
                      "WORKSPACE_CLEANUP") or re.fullmatch(r"[a-z0-9-]+ (?:deadline exceeded|failed \(exit -?\d+\))", reason):
            result["reason"] = reason
        if reason == "HOST_MEMORY_PRESSURE" and not result["profiles"]:
            result["status"] = "NOT RUN"
    finally:
        signal.alarm(0)
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("input_sha512", "spring_dependencies", "jdbc_dependencies")}))
    return int(result["status"] != "PASS")


if __name__ == "__main__":
    sys.exit(main())
