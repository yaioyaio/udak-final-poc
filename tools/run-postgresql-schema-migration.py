#!/usr/bin/env python3
"""Validate the reviewed migration history contract on isolated PostgreSQL."""
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
spec = importlib.util.spec_from_file_location("postgres_drift", ROOT / "tools/run-postgresql-schema-drift.py")
postgres = importlib.util.module_from_spec(spec)
spec.loader.exec_module(postgres)
replay, guard = postgres.replay, postgres.guard
migration = postgres.load("schema_migration", "tools/schema-migration.py")

FIXTURE = "schema-regression/src/test/java/dev/udak/schema/SchemaMigrationPostgreSqlTest.java"
SQL = ROOT / "schema-regression/src/test/resources/postgresql/migration/V002__DROP_DEVICE_CUSTOMER_ID.sql"
CHECKSUM = "efbd814d553a33d7cc5a587c37fd867e6c2be9f16e60c316c6e355f8d724c928"
CLASS = "dev.udak.schema.SchemaMigrationPostgreSqlTest"
SCOPE = hashlib.sha256(b"udak-schema-contract-v1\nPOSTGRESQL\ndevice\n").hexdigest()
EXPECTED_MIGRATION = {"version": "2", "checksum_sha256": CHECKSUM}
REMOVED = {"table": "device", "column": "customer_id", "kind": "REMOVED",
           "before": {"type": "UUID", "width": 0, "nullable": True}, "after": None}
EXTRA = {"table": "device", "column": "fixture_note", "kind": "WIDTH",
         "before": {"type": "VARCHAR", "width": 16, "nullable": True},
         "after": {"type": "VARCHAR", "width": 32, "nullable": True}}
CASES = {
    "matched": [],
    "missing": ["HISTORY_MISSING"],
    "wrong_version": ["VERSION_MISMATCH"],
    "wrong_checksum": ["CHECKSUM_MISMATCH"],
    "extra_change": ["CHANGE_MISMATCH"],
}


def collect(work, sql, revisions):
    jdbc, driver_version, driver_digest = postgres.driver(work)
    java = Path(replay.inspect("/usr/libexec/java_home", "-v", "21"))
    classes = work / "classes"
    guard.run_step("compile", [str(java / "bin/javac"), "-J-Xmx160m", "-J-XX:ActiveProcessorCount=1",
                   "--release", "17", "-d", str(classes), postgres.SOURCES[0], FIXTURE], work, timeout=20)
    pinned_sql = work / SQL.name
    pinned_sql.write_bytes(sql)
    for case in ("baseline", *CASES):
        (work / case).mkdir()
    with replay.postgres_fixture() as (port, password):
        if not replay.host_ready():
            raise RuntimeError("Host resource guard stopped fixture")
        result = guard.run_step("collect", [str(java / "bin/java"), "-Xmx160m", "-XX:ActiveProcessorCount=1",
            "-cp", f"{classes}:{jdbc}", CLASS, port, str(work), str(pinned_sql), *revisions, SCOPE, CHECKSUM],
            work, timeout=25, private_input=(password + "\n").encode())
        if result.get("assertions", 0) < 1:
            raise ValueError("PostgreSQL fixture assertions missing")
    return result["assertions"], driver_version, driver_digest


def verify_cases(work, alternate_checksum, revisions):
    base, head = revisions
    expected_changes = migration.changes_digest([REMOVED])
    manifest = {"schema_version": 1, "base_revision": base, "revision": head, "scope": SCOPE,
                **EXPECTED_MIGRATION, "expected_changes_sha256": expected_changes}
    (work / migration.MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    baseline = json.loads((work / "baseline" / migration.HISTORY_FILENAME).read_bytes())["migrations"]
    if len(baseline) != 1 or baseline[0]["version"] != "1":
        raise ValueError("PostgreSQL baseline migration is missing")
    launcher = ('import os,runpy,sys; os.chdir(sys.argv.pop(2)); '
                'sys.argv.pop(0); runpy.run_path(sys.argv[0],run_name="__main__")')
    outcomes = {}
    for case, reasons in CASES.items():
        applied = {
            "missing": [],
            "wrong_version": [{**EXPECTED_MIGRATION, "version": "3"}],
            "wrong_checksum": [{**EXPECTED_MIGRATION, "checksum_sha256": alternate_checksum}],
        }.get(case, [EXPECTED_MIGRATION])
        observed = [REMOVED, EXTRA] if case == "extra_change" else [REMOVED]
        exit_code = 2 if reasons else 0
        name = f"compare-{case}"
        proof = guard.run_step(name, [sys.executable, "-B", "-c", launcher,
            str(ROOT / "tools/schema-migration.py"), str(work),
            "--base", f"baseline/{postgres.SNAPSHOT}", "--head", f"{case}/{postgres.SNAPSHOT}",
            "--base-history", f"baseline/{migration.HISTORY_FILENAME}",
            "--head-history", f"{case}/{migration.HISTORY_FILENAME}",
            "--manifest", migration.MANIFEST_FILENAME], work, timeout=10, expected=exit_code)
        data = (work / f"{name}.output").read_bytes()
        result = json.loads(data)
        status = "UNRESOLVED" if reasons else "MATCHED"
        if result != {"schema_version": 1, "status": status, "reasons": reasons, "base_revision": base,
                      "head_revision": head, "scope": SCOPE, "expected_migration": EXPECTED_MIGRATION,
                      "newly_applied": applied, "observed_changes": observed,
                      "observed_changes_sha256": migration.changes_digest(observed),
                      "expected_changes_sha256": expected_changes}:
            raise ValueError("Unexpected PostgreSQL migration comparison")
        outcomes[case] = {"status": status, "exit_code": proof["exit_code"], "reasons": reasons,
                          "newly_applied": applied, "observed_changes": observed,
                          "report_sha256": hashlib.sha256(data).hexdigest()}
    return outcomes, expected_changes


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    for event in (signal.SIGINT, signal.SIGTERM):
        signal.signal(event, guard.interrupted)
    if not replay.host_ready():
        print(json.dumps({"status": "NOT RUN", "reason": "POSTGRESQL_HOST_PREFLIGHT"}))
        return 2
    sql = SQL.read_bytes()
    if hashlib.sha256(sql).hexdigest() != CHECKSUM:
        raise ValueError("Reviewed PostgreSQL migration bytes changed")
    fixture_source = (ROOT / FIXTURE).read_bytes()
    revisions = (hashlib.sha256(fixture_source).hexdigest(), hashlib.sha256(fixture_source + sql).hexdigest())
    alternate_checksum = hashlib.sha256(sql + b"-- alternate fixture bytes\n").hexdigest()
    lock_dir = ROOT / ".git/udak-g2-managed"
    lock_dir.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(lock_dir / "RUN.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with guard.workspace("udak-postgresql-schema-migration-") as (work, cleanup):
            assertions, driver_version, driver_digest = collect(work, sql, revisions)
            outcomes, expected_changes = verify_cases(work, alternate_checksum, revisions)
    print(json.dumps({"schema_version": 1, "requirement": "NEXT-004", "status": "PASS",
                      "recorded_at_utc": datetime.now(timezone.utc).isoformat(), "dbms": "POSTGRESQL",
                      "postgresql_image": replay.IMAGE, "image_digest": replay.INDEX, "jdbc_version": driver_version,
                      "jdbc_sha512": driver_digest, "fixture_assertions": assertions, "scope": SCOPE,
                      "base_revision": revisions[0], "head_revision": revisions[1], "read_only_capture": True,
                      "reviewed_migration": {"file": str(SQL.relative_to(ROOT)), **EXPECTED_MIGRATION},
                      "expected_changes_sha256": expected_changes, "cases": outcomes,
                      "container_cleanup": "PASS", "workspace_cleanup": cleanup}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
