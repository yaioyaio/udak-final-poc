#!/usr/bin/env python3
"""Verify MySQL Flyway history with an owned fixture and the guarded PR report."""
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
ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "evidence/MYSQL-FLYWAY-HISTORY-VALIDATION.json"
SOURCES = (
    "schema-regression/src/main/java/dev/udak/schema/FlywayHistoryCollector.java",
    "schema-regression/src/main/java/dev/udak/schema/SchemaSnapshotCollector.java",
    "schema-regression/src/test/java/dev/udak/schema/FlywayHistoryMySqlTest.java",
    "sql-inventory/src/main/java/dev/udak/inventory/InventoryCapture.java",
)
COLLECTOR = "dev.udak.schema.FlywayHistoryMySqlTest"
FLYWAY_LOCK = "tools/flyway-test-dependencies.json"
FLYWAY = "11.20.3"
MYSQL_MODULE = {
    "coordinate": f"org.flywaydb:flyway-mysql:{FLYWAY}",
    "jar_bytes": 29641,
    "jar_sha512": "f52b0e19cae811daa22590e882447f5ca8409c23d3e5f3dd911cdbd72ea1aa54465e53723cf445dfdad7a1f36534321cd9456ed2f316f09cefee1fe9dc1bd5a0",
}
SCRIPT = "V002__DROP_DEVICE_CUSTOMER_ID.sql"
REVIEWED = b"ALTER TABLE device DROP COLUMN customer_id;\n"
ALTERNATE = b"-- Different applied migration bytes.\n" + REVIEWED
SCOPE = hashlib.sha256(b"udak-schema-contract-v1\nMYSQL\ndevice\n").hexdigest()
CASES = {
    "matched": ("VERIFIED", "MATCHED", [], 0),
    "missing": ("EMPTY", "UNRESOLVED", ["HISTORY_MISSING"], 2),
    "wrong-checksum": ("VERIFIED", "UNRESOLVED", ["CHECKSUM_MISMATCH"], 2),
    "unverified": ("HISTORY_FILE_UNVERIFIED", "UNRESOLVED", ["HISTORY_FILE_UNVERIFIED"], 2),
}
CHANGE = {"table": "device", "column": "customer_id", "kind": "REMOVED",
          "before": {"type": "INTEGER", "width": 0, "nullable": True}, "after": None}
SNAPSHOT = "SCHEMA-SNAPSHOT.json"
INVENTORY = "SQL-INVENTORY.json"


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


schema = load("mysql_flyway_guard", "tools/run-schema-regression.py")
pressure = load("mysql_flyway_pressure", "tools/release-performance/jmh-process-guard.py")
migration = load("mysql_flyway_migration", "tools/schema-migration.py")
guard = schema.guard


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def classpath(work):
    jdbc, proof = schema.pinned_drivers(work)
    connector, = (item for item in proof["artifacts"] if item["coordinate"] == "com.mysql:mysql-connector-j:26.10.0")
    lock = json.loads((ROOT / FLYWAY_LOCK).read_bytes())
    shared = [item for item in lock["artifacts"] if not item["coordinate"].startswith("org.flywaydb:flyway-database-")]
    expected = {f"org.flywaydb:flyway-core:{FLYWAY}", *(f"com.fasterxml.jackson.core:{name}:2.19.1"
                for name in ("jackson-core", "jackson-annotations", "jackson-databind"))}
    if lock["schema_version"] != 1 or lock["license"] != "Apache-2.0" \
            or len(shared) != 4 or {item["coordinate"] for item in shared} != expected:
        raise ValueError("FLYWAY_LOCK")
    jars = list(jdbc)
    for artifact in [*shared, MYSQL_MODULE]:
        group, name, version = artifact["coordinate"].split(":")
        filename = f"{name}-{version}.jar"
        size = artifact["jar_bytes"]
        if not 0 < size <= 4_000_000:
            raise ValueError("FLYWAY_ARTIFACT_SIZE")
        url = f"https://repo.maven.apache.org/maven2/{group.replace('.', '/')}/{name}/{version}/{filename}"
        data = schema.h.fetch(url, size)
        if len(data) != size or guard.digest(data) != artifact["jar_sha512"]:
            raise ValueError("FLYWAY_ARTIFACT_DIGEST")
        path = work / filename
        with path.open("xb") as stream:
            stream.write(data)
        jars.append(path)
    return os.pathsep.join(map(str, jars)), connector, MYSQL_MODULE


def host_ready():
    if pressure.memory_pressure(Path("/tmp")) != 1:
        raise schema.RuntimeUnavailable("HOST_MEMORY_PRESSURE")


def run_capture(work, revisions, source_paths, result):
    jars, connector, flyway = classpath(work)
    classes = work / "classes"
    compiled = guard.run_step("compile", [*schema.base.JAVAC, "-cp", jars, "-d", str(classes),
                                         *source_paths], work, timeout=25)
    for case in ("empty", "reviewed", "alternate", "baseline", *CASES):
        (work / case).mkdir(mode=0o700)
    (work / "reviewed" / SCRIPT).write_bytes(REVIEWED)
    (work / "alternate" / SCRIPT).write_bytes(ALTERNATE)
    host_ready()
    with schema.native.instance("mysql", work) as (port, password, native):
        result["native_runtime"] = native
        host_ready()
        command = [*schema.base.JAVA, "-cp", f"{classes}{os.pathsep}{jars}", COLLECTOR,
                   str(port), str(work), *revisions, SCOPE, sha256(REVIEWED), sha256(ALTERNATE)]
        try:
            capture, output = schema.native.run_private("mysql-flyway-collect", command, work, 45,
                                                        input_data=(password + "\n").encode("ascii"))
        except RuntimeError:
            output = work / "mysql-flyway-collect.output"
            if output.is_file() and output.stat().st_size <= 40:
                marker = re.fullmatch(rb"fixture_failure_line=([0-9]{1,5})\n", output.read_bytes())
                if marker:
                    result["fixture_failure_line"] = int(marker[1])
            raise
        protocol = re.fullmatch(r"assertions=([1-9][0-9]{0,2})\nserver_version=(8\.0\.46)\n",
                                output.read_text(encoding="ascii"))
        if not protocol or protocol[2] != native["version"]:
            raise ValueError("FLYWAY_FIXTURE_PROTOCOL")
    if not all(native.get(key) for key in ("server_stopped", "process_groups_quiesced", "loopback_listener_owned")):
        raise schema.native.PreservationRequired("NATIVE_CLEANUP")
    result.update(assertions=int(protocol[1]), jdbc_artifact=connector["coordinate"],
                  jdbc_sha512=connector["jar_sha512"], flyway_module=flyway, steps=[compiled, capture])


def capture_status(work, case, status, revision, checksum=None):
    folder = work / case
    history = folder / migration.HISTORY_FILENAME
    if (folder / "status").read_text(encoding="ascii").strip() != status:
        raise ValueError("CAPTURE_STATUS")
    if status == "HISTORY_FILE_UNVERIFIED":
        if history.exists():
            raise ValueError("UNVERIFIED_HISTORY_EXPORTED")
    else:
        rows = [{"version": "2", "checksum_sha256": checksum}] if checksum else []
        if json.loads(history.read_bytes()) != {"schema_version": 1, "revision": revision,
                                                "scope": SCOPE, "migrations": rows}:
            raise ValueError("CAPTURE_CONTENT")
    return history.exists()


def verify_reports(work, revisions):
    base, head = revisions
    capture_status(work, "baseline", "EMPTY", base)
    approved = sha256(REVIEWED)
    write_json(work / migration.MANIFEST_FILENAME, {"schema_version": 1, "base_revision": base,
               "revision": head, "scope": SCOPE, "version": "2", "checksum_sha256": approved,
               "expected_changes_sha256": migration.changes_digest([CHANGE])})
    inventory = json.loads((work / "baseline" / INVENTORY).read_bytes())
    entry, = inventory["entries"]
    shape, = entry["shapes"]
    query = schema.identifier("query", "mysql-flyway-device-query")
    test = schema.identifier("test", "mysql-flyway-device-contract")
    if (inventory["schema_version"], inventory["revision"], inventory["profile"], inventory["dropped"],
            entry["framework"], entry["query_id_hash"], entry["observed"], entry["unavailable"],
            entry["test_ids"], shape["test_ids"], shape["statement_kind"]) != (
            2, base, SCOPE, 0, "JDBC", query, 1, 0, [test], [test], "SELECT"):
        raise ValueError("MYSQL_OBSERVATION")
    write_json(work / INVENTORY, {**inventory, "revision": head})
    dependencies = migration.schema.DEPENDENCIES_FILENAME
    write_json(work / dependencies, {"schema_version": 2, "revision": head, "scope": SCOPE, "dependencies": [{
        "framework": "JDBC", "query_id_hash": query, "test_ids": [test], "fingerprint_hash": shape["fingerprint_hash"],
        "columns": [{"table": "device", "column": column} for column in ("customer_id", "id")],
    }]})
    head_schema = (work / "matched" / SNAPSHOT).read_bytes()
    outcomes = {}
    launcher = ('import os,runpy,sys; os.chdir(sys.argv.pop(2)); '
                'sys.argv.pop(0); runpy.run_path(sys.argv[0],run_name="__main__")')
    for case, (capture_state, verdict, reasons, code) in CASES.items():
        if (work / case / SNAPSHOT).read_bytes() != head_schema:
            raise ValueError("SCHEMA_CONTROLS_DIFFER")
        digest = {"matched": approved, "wrong-checksum": sha256(ALTERNATE)}.get(case)
        exported = capture_status(work, case, capture_state, head, digest)
        capture = {"status": capture_state, "revision": head, "scope": SCOPE}
        if exported:
            capture["history"] = f"{case}/{migration.HISTORY_FILENAME}"
        request = f"{case}/SCHEMA-REVIEW.json"
        write_json(work / request, {"schema_version": 1, "base_schema": f"baseline/{SNAPSHOT}",
                   "head_schema": f"{case}/{SNAPSHOT}", "dependencies": dependencies,
                   "base_history": f"baseline/{migration.HISTORY_FILENAME}", "manifest": migration.MANIFEST_FILENAME,
                   "flyway_capture": capture})
        args = [sys.executable, "-B", "-c", launcher, str(ROOT / "tools/run-sql-inventory.py"), str(work),
                "--pr-report", "--base", f"baseline/{INVENTORY}", "--head", INVENTORY,
                "--schema-review", request, "--fail-on-change"]
        guard.run_step(f"{case}-json", args, work, timeout=12, expected=code)
        guard.run_step(f"{case}-md", [*args, "--format", "markdown"], work, timeout=12, expected=code)
        raw = (work / f"{case}-json.output").read_bytes()
        markdown = (work / f"{case}-md.output").read_bytes()
        report = json.loads(raw)
        status = "COMPLETE" if code == 0 else "INCOMPLETE"
        expected = {"status": status, "change": CHANGE, "head_schema_sha256": sha256(head_schema),
                    "flyway_history": {"status": verdict, "reasons": reasons}, "impacted_test_ids": [test],
                    "coverage_reasons": [], "unresolved_queries": [],
                    "affected_queries": [{"framework": "JDBC", "query_id_hash": query, "test_ids": [test]}]}
        if (report["schema_review"] != expected or report["status"] != status
                or report["changes_detected"] is not False or report["impacted_test_ids"]):
            raise ValueError("MYSQL_PR_JSON")
        labels = ("Schema change and Flyway history", "device.customer_id", verdict, test, *reasons)
        if not all(label.encode("ascii") in markdown for label in labels):
            raise ValueError("MYSQL_PR_MARKDOWN")
        outcomes[case] = {"exit_code": code, "capture_status": capture_state, "history_exported": exported,
                          "status": status, "verdict": verdict, "reasons": reasons, "impacted_tests": 1,
                          "json_sha256": sha256(raw), "markdown_sha256": sha256(markdown)}
    return {"cases": outcomes, "test_id_hash": test, "schema_sha256": sha256(head_schema)}


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    for event in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
        signal.signal(event, schema.interrupted)
    result = {"schema_version": 1, "requirement": "NEXT-004", "status": "FAIL", "dbms": "MYSQL",
              "recorded_at_utc": datetime.now(timezone.utc).isoformat(), "flyway_version": FLYWAY,
              "docker_containers_started": 0}
    signal.alarm(210)
    phase = "preflight"
    try:
        host_ready()
        lock_dir = ROOT / ".git/udak-g2-managed"
        lock_dir.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(lock_dir / "RUN.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), "w") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise schema.RuntimeUnavailable("RUN_LOCK_BUSY") from None
            observe = [*sorted((ROOT / "observe-core/src/main/java").rglob("*.java")),
                       *sorted((ROOT / "legacy-observe/src/main/java/dev/udak/observe/jdbc").glob("*.java"))]
            sources = (*SOURCES, *(str(path.relative_to(ROOT)) for path in observe))
            inputs = (*sources, FLYWAY_LOCK, schema.DRIVERS, "tools/run-mysql-flyway-history.py",
                      "tools/run-schema-regression.py", "tools/schema-native.py", "tools/release-performance/jmh-process-guard.py",
                      "tools/run-sql-inventory.py", "tools/sql-inventory.py", "tools/pr-schema-review.py",
                      "tools/schema-impact.py", "tools/schema-migration.py")
            hashes = schema.h.hashes(inputs)
            fixture = (ROOT / SOURCES[2]).read_bytes()
            revisions = (sha256(fixture), sha256(fixture + REVIEWED))
            with schema.workspace() as (work, cleanup):
                result["workspace_cleanup"] = cleanup
                phase = "capture"
                run_capture(work, revisions, sources, result)
                phase = "reports"
                result["pr_schema_review"] = verify_reports(work, revisions)
            phase = "cleanup"
            if cleanup["status"] != "PASS" or cleanup["remaining"] or schema.h.hashes(inputs) != hashes:
                raise ValueError("CLEANUP_OR_INPUTS")
            result.update(status="PASS", input_sha512=hashes, jdbc_read_only_capture=True,
                          reviewed_sha256=sha256(REVIEWED), alternate_sha256=sha256(ALTERNATE))
            phase = "evidence"
            try:
                write_json(REPORT, result)
            except FileExistsError:
                pass
    except schema.RuntimeUnavailable as error:
        result.update(status="NOT RUN", phase=phase, reason=str(error))
    except (Exception, KeyboardInterrupt) as error:
        result.update(status="FAIL", phase=phase, error_type=type(error).__name__)
        if isinstance(error, ValueError) and re.fullmatch(r"[A-Z_]{1,40}", str(error)):
            result["reason"] = str(error)
    finally:
        signal.alarm(0)
    print(json.dumps(result, sort_keys=True))
    return {"PASS": 0, "FAIL": 1, "NOT RUN": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
