#!/usr/bin/env python3
"""Validate the MySQL schema collector and existing drift CLI on an owned native fixture."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import sys


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
SOURCES = (
    "schema-regression/src/main/java/dev/udak/schema/SchemaSnapshotCollector.java",
    "schema-regression/src/test/java/dev/udak/schema/SchemaSnapshotCollectorMySqlTest.java",
)
REPORT = ROOT / "evidence/MYSQL-SCHEMA-DRIFT-VALIDATION.json"
SNAPSHOT = "SCHEMA-SNAPSHOT.json"
TABLE = "stock_item"
COLLECTOR = "dev.udak.schema.SchemaSnapshotCollectorMySqlTest"
SCOPE = hashlib.sha256(f"udak-schema-contract-v1\nMYSQL\n{TABLE}\n".encode("ascii")).hexdigest()
BASELINE = {
    "balance": ("DECIMAL", 0, True),
    "description": ("TEXT", 0, True),
    "label": ("VARCHAR", 32, True),
    "legacy_col": ("DATE", 0, True),
    "note": ("VARCHAR", 16, False),
    "quantity": ("INTEGER", 0, False),
    "sequence_id": ("BIGINT", 0, False),
    "updated_at": ("TIMESTAMP", 0, True),
}
EXPECTED_CHANGES = {
    "added_col": ("ADDED", None, ("DATE", 0, True)),
    "label": ("WIDTH", BASELINE["label"], ("VARCHAR", 64, True)),
    "legacy_col": ("REMOVED", BASELINE["legacy_col"], None),
    "note": ("NULLABILITY", BASELINE["note"], ("VARCHAR", 16, True)),
    "quantity": ("TYPE", BASELINE["quantity"], ("BIGINT", 0, False)),
}


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


schema = load("mysql_schema_guard", "tools/run-schema-regression.py")
pressure = load("mysql_host_pressure", "tools/release-performance/jmh-process-guard.py")


def column(details):
    return dict(zip(("type", "width", "nullable"), details)) if details is not None else None


def verify_snapshots(work, revision):
    observed = {name: (work / name / SNAPSHOT).read_bytes() for name in ("baseline", "equal", "drift")}
    contract = {"schema_version": 1, "revision": revision, "scope": SCOPE}
    changed = dict(BASELINE)
    for name, (_, _, after) in EXPECTED_CHANGES.items():
        if after is None:
            del changed[name]
        else:
            changed[name] = after
    for name, columns in (("baseline", BASELINE), ("drift", changed)):
        expected = [{"table": TABLE, "column": field, **column(details)} for field, details in sorted(columns.items())]
        if json.loads(observed[name]) != {**contract, "columns": expected}:
            raise ValueError("Unexpected MySQL snapshot")
    if observed["baseline"] != observed["equal"]:
        raise ValueError("Equivalent MySQL snapshots differ")
    return {name: hashlib.sha256(data).hexdigest() for name, data in observed.items()}


def compare(work, revision, dbms, current, expected_exit):
    launcher = ('import os,runpy,sys; os.chdir(sys.argv.pop(2)); '
                'sys.argv.pop(0); runpy.run_path(sys.argv[0],run_name="__main__")')
    command = [sys.executable, "-B", "-c", launcher, str(ROOT / "tools/schema-drift.py"), str(work),
               "--dbms", dbms, "--table", TABLE, "--baseline", f"baseline/{SNAPSHOT}",
               "--current", f"{current}/{SNAPSHOT}"]
    name = f"compare-{dbms.lower()}-{current}"
    proof = schema.guard.run_step(name, command, work, timeout=10, expected=expected_exit)
    output = (work / f"{name}.output").read_bytes()
    if expected_exit == 1:
        if output != b"ERROR: invalid schema drift input or scope\n":
            raise ValueError("Cross-DBMS scope rejection differs")
        return {"dbms": dbms, "exit_code": proof["exit_code"], "status": "REJECTED"}
    status = "MATCH" if expected_exit == 0 else "DRIFT"
    changes = [] if expected_exit == 0 else [
        {"table": TABLE, "column": name, "kind": kind, "before": column(before), "after": column(after)}
        for name, (kind, before, after) in EXPECTED_CHANGES.items()
    ]
    report = json.loads(output)
    if report != {"schema_version": 1, "status": status, "dbms": dbms, "scope": SCOPE,
                  "baseline_revision": revision, "current_revision": revision, "changes": changes}:
        raise ValueError("Unexpected MySQL drift report")
    return {"exit_code": proof["exit_code"], **report}


def run_fixture(work, revision, result):
    classes = work / "classes"
    classes.mkdir(mode=0o700)
    compile_command = schema.base.JAVAC + ["-d", str(classes), *(str(ROOT / path) for path in SOURCES)]
    compilation = schema.guard.run_step("compile", compile_command, work, timeout=20)
    jars, dependencies = schema.pinned_drivers(work)
    driver_version = schema.PROFILES["MYSQL"]
    driver, = (item for item in dependencies["artifacts"]
               if item["coordinate"] == f"com.mysql:mysql-connector-j:{driver_version}")
    classpath = os.pathsep.join(map(str, [classes, *jars]))
    for name in ("baseline", "equal", "drift"):
        (work / name).mkdir(mode=0o700)
    if pressure.memory_pressure(work) != 1:
        raise schema.RuntimeUnavailable("HOST_MEMORY_PRESSURE")
    with schema.native.instance("mysql", work) as (port, password, native):
        result["native_runtime"] = native
        if pressure.memory_pressure(work) != 1:
            raise schema.RuntimeUnavailable("HOST_MEMORY_PRESSURE")
        command = schema.base.JAVA + ["-cp", classpath, COLLECTOR, str(port), revision, str(work)]
        collected, output = schema.native.run_private("collect-mysql", command, work, 35,
                                                      input_data=(password + "\n").encode("ascii"))
        protocol = re.fullmatch(r"assertions=([1-9][0-9]{0,2})\nserver_version=(8\.0\.[0-9]{1,3})\n"
                                r"driver_version=([0-9.]{1,20})\n", output.read_text(encoding="ascii"))
        if not protocol or protocol[2] != native["version"] or protocol[3] != driver_version:
            raise ValueError("Unexpected MySQL fixture protocol")
    if not native.get("server_stopped") or not native.get("process_groups_quiesced"):
        raise schema.native.PreservationRequired("Native MySQL shutdown unconfirmed")
    if not native.get("loopback_listener_owned"):
        raise ValueError("Native loopback listener ownership missing")
    result.update(collector_assertions=int(protocol[1]), jdbc_version=driver_version, jdbc_sha512=driver["jar_sha512"],
                  collection_read_only=True, fixture_scope="one isolated catalog, two physical tables",
                  steps=[compilation, collected])


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    for event in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
        signal.signal(event, schema.interrupted)
    result = {"schema_version": 1, "requirement": "NEXT-004", "dbms": "MYSQL", "status": "FAIL",
              "recorded_at_utc": datetime.now(timezone.utc).isoformat(), "docker_containers_started": 0}
    phase = "preflight"
    signal.alarm(240)
    try:
        if pressure.memory_pressure(Path("/tmp")) != 1:
            raise schema.RuntimeUnavailable("HOST_MEMORY_PRESSURE")
        lock_dir = ROOT / ".git/udak-g2-managed"
        lock_dir.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(lock_dir / "RUN.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), "w") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise schema.RuntimeUnavailable("RUN_LOCK_BUSY") from None
            inputs = (*SOURCES, "tools/run-mysql-schema-drift.py", "tools/schema-drift.py", "tools/schema-impact.py",
                      "tools/schema-native.py", "tools/g2-dependencies.json",
                      "tools/release-performance/jmh-process-guard.py")
            hashes = schema.h.hashes(inputs)
            revision = hashlib.sha256((ROOT / SOURCES[1]).read_bytes()).hexdigest()
            with schema.workspace() as (work, cleanup):
                result["workspace_cleanup"] = cleanup
                phase = "collect"
                run_fixture(work, revision, result)
                phase = "compare"
                result.update(fixture_revision=revision, snapshot_sha256=verify_snapshots(work, revision),
                              match=compare(work, revision, "MYSQL", "equal", 0),
                              drift=compare(work, revision, "MYSQL", "drift", 2),
                              scope_rejections=[compare(work, revision, dbms, "equal", 1)
                                                for dbms in ("H2", "POSTGRESQL")])
            phase = "cleanup"
            if cleanup["status"] != "PASS" or cleanup["remaining"] or hashes != schema.h.hashes(inputs):
                raise ValueError("Owned workspace cleanup or input verification failed")
            result.update(status="PASS", input_sha512=hashes)
            phase = "evidence"
            try:
                with REPORT.open("x", encoding="utf-8") as report:
                    json.dump(result, report, indent=2, sort_keys=True)
                    report.write("\n")
                result["evidence_written"] = True
            except FileExistsError:
                result["evidence_written"] = False
    except schema.RuntimeUnavailable as error:
        result.update(status="NOT RUN", failed_phase=phase, reason=str(error))
    except (Exception, KeyboardInterrupt) as error:
        result.update(status="FAIL", failed_phase=phase, failure_type=type(error).__name__)
    finally:
        signal.alarm(0)
    print(json.dumps(result, sort_keys=True))
    return {"PASS": 0, "FAIL": 1, "NOT RUN": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
