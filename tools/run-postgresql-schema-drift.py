#!/usr/bin/env python3
"""Validate the PostgreSQL schema contract on two disposable fixture databases."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys


ROOT = Path(__file__).resolve().parent.parent
SOURCES = (
    "schema-regression/src/main/java/dev/udak/schema/SchemaSnapshotCollector.java",
    "schema-regression/src/test/java/dev/udak/schema/SchemaSnapshotCollectorPostgreSqlTest.java",
)
COLLECTOR = "dev.udak.schema.SchemaSnapshotCollectorPostgreSqlTest"
SNAPSHOT = "SCHEMA-SNAPSHOT.json"
TARGET_COLUMN = {"table": "device", "column": "customer_id", "type": "UUID", "width": 0, "nullable": True}


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


replay = load("postgres_fixture", "tools/thingsboard-pilot/replay-upstream-count.py")
g2 = load("driver_verifier", "tools/run-g2.py")
guard = replay.guard


def driver(work):
    manifest = json.loads((ROOT / "tools/g2-dependencies.json").read_bytes())
    version = manifest["metadata_versions"]["POSTGRESQL"]
    artifact, = (item for item in manifest["artifacts"]
                 if item["coordinate"] == f"org.postgresql:postgresql:{version}")
    jar = g2.fetch(artifact["artifact_url"], artifact["jar_bytes"])
    if len(jar) != artifact["jar_bytes"] or guard.digest(jar) != artifact["jar_sha512"]:
        raise ValueError("PostgreSQL JDBC driver integrity mismatch")
    path = work / "postgresql.jar"
    path.write_bytes(jar)
    return path, version, artifact["jar_sha512"]


def compare(work, current, expected):
    launcher = ('import os,runpy,sys; os.chdir(sys.argv.pop(2)); '
                'sys.argv.pop(0); runpy.run_path(sys.argv[0],run_name="__main__")')
    command = [sys.executable, "-B", "-c", launcher, str(ROOT / "tools/schema-drift.py"), str(work),
               "--dbms", "POSTGRESQL", "--table", "device",
               "--baseline", f"baseline/{SNAPSHOT}", "--current", f"{current}/{SNAPSHOT}"]
    name = f"compare-{current}"
    proof = guard.run_step(name, command, work, timeout=10, expected=expected)
    return json.loads((work / f"{name}.output").read_bytes()), proof["exit_code"]


def verify_snapshots(work, revision):
    data = {name: (work / name / SNAPSHOT).read_bytes() for name in ("baseline", "equal", "drift")}
    baseline = json.loads(data["baseline"])
    expected = [
        ("active", "BOOLEAN", 0, False), ("balance", "DECIMAL", 0, True),
        ("created_at", "TIMESTAMP", 0, True), ("customer_id", "UUID", 0, True),
        ("description", "TEXT", 0, True), ("id", "UUID", 0, False), ("installed_on", "DATE", 0, True),
        ("label", "VARCHAR", 24, False), ("retries", "INTEGER", 0, False), ("sequence_id", "BIGINT", 0, False),
    ]
    scope = hashlib.sha256(b"udak-schema-contract-v1\nPOSTGRESQL\ndevice\n").hexdigest()
    columns = [{"table": "device", "column": name, "type": kind, "width": width, "nullable": nullable}
               for name, kind, width, nullable in expected]
    if baseline != {"schema_version": 1, "revision": revision, "scope": scope, "columns": columns}:
        raise ValueError("Unexpected PostgreSQL schema contract")
    changed = {**baseline, "columns": [column for column in columns if column != TARGET_COLUMN]}
    if data["baseline"] != data["equal"] or json.loads(data["drift"]) != changed:
        raise ValueError("Unexpected matching or missing-column snapshot")
    return scope, {name: hashlib.sha256(raw).hexdigest() for name, raw in data.items()}


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    for event in (signal.SIGINT, signal.SIGTERM):
        signal.signal(event, guard.interrupted)
    if not replay.host_ready():
        print(json.dumps({"status": "NOT RUN", "reason": "POSTGRESQL_HOST_PREFLIGHT"}))
        return 2
    java = Path(replay.inspect("/usr/libexec/java_home", "-v", "21"))
    revision = hashlib.sha256((ROOT / SOURCES[1]).read_bytes()).hexdigest()
    lock_dir = ROOT / ".git/udak-g2-managed"
    lock_dir.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(lock_dir / "RUN.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with guard.workspace("udak-postgresql-schema-drift-") as (work, cleanup):
            jdbc, version, driver_sha = driver(work)
            classes = work / "classes"
            guard.run_step("compile", [str(java / "bin/javac"), "-J-Xmx160m", "-J-XX:ActiveProcessorCount=1",
                           "--release", "17", "-d", str(classes), *SOURCES], work, timeout=20)
            for name in ("baseline", "equal", "drift"):
                (work / name).mkdir()
            with replay.postgres_fixture() as (port, password):
                if not replay.host_ready():
                    raise RuntimeError("Host resource guard stopped fixture")
                collected = guard.run_step("collect", [str(java / "bin/java"), "-Xmx160m",
                    "-XX:ActiveProcessorCount=1", "-cp", f"{classes}:{jdbc}", COLLECTOR, port, revision, str(work)],
                    work, timeout=25, private_input=(password + "\n").encode())
                if collected.get("assertions", 0) < 1:
                    raise ValueError("PostgreSQL collector assertions missing")
            scope, snapshots = verify_snapshots(work, revision)
            match, match_exit = compare(work, "equal", 0)
            drift, drift_exit = compare(work, "drift", 2)
            expected = {"table": "device", "column": "customer_id", "kind": "REMOVED",
                        "before": {"type": "UUID", "width": 0, "nullable": True}, "after": None}
            for report, status, changes in ((match, "MATCH", []), (drift, "DRIFT", [expected])):
                if report != {"schema_version": 1, "status": status, "dbms": "POSTGRESQL", "scope": scope,
                              "baseline_revision": revision, "current_revision": revision, "changes": changes}:
                    raise ValueError("Unexpected PostgreSQL drift report")
    print(json.dumps({"schema_version": 1, "requirement": "NEXT-004", "status": "PASS",
                      "recorded_at_utc": datetime.now(timezone.utc).isoformat(), "dbms": "POSTGRESQL",
                      "postgresql_image": replay.IMAGE, "image_digest": replay.INDEX,
                      "jdbc_version": version, "jdbc_sha512": driver_sha,
                      "fixture_databases": ["local", "development"], "collection_read_only": True,
                      "collector_assertions": collected["assertions"], "fixture_revision": revision,
                      "snapshot_sha256": snapshots,
                      "match": {"exit_code": match_exit, **match}, "drift": {"exit_code": drift_exit, **drift},
                      "container_cleanup": "PASS", "workspace_cleanup": cleanup}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
