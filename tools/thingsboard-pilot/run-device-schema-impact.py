#!/usr/bin/env python3
"""Verify schema impact for the pinned ThingsBoard PR #14036 device query."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import signal
import sys

spec = importlib.util.spec_from_file_location(
    "device_profile", Path(__file__).with_name("replay-upstream-device-profile.py"))
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)
replay = profile.count_replay
guard = replay.guard
PR_EVIDENCE = replay.ROOT / "evidence/THINGSBOARD-DEVICE-DAO-FOLLOWUP-VALIDATION.json"
FIXTURE_CLASS = "DeviceProfileSchemaImpact"
COLUMNS = ("created_time", "customer_id", "device_profile_id", "id", "tenant_id")
CASES = ("baseline", "missing", "unused")
REVISIONS = {case: hashlib.sha256(f"{profile.HEAD[0]}:device-schema-impact-v1:{case}".encode()).hexdigest()
             for case in CASES}
SCHEMA_FILE = "SCHEMA-SNAPSHOT.json"
INVENTORY_FILE = "SQL-INVENTORY.json"
DEPENDENCIES_FILE = "QUERY-DEPENDENCIES.json"
UUID_COLUMN = {"type": "UUID", "width": 0, "nullable": False}
MISSING_CHANGE = {"table": "device", "column": "customer_id", "kind": "REMOVED",
                  "before": UUID_COLUMN, "after": None}
UNUSED_CHANGE = {"table": "device", "column": "fixture_note", "kind": "WIDTH",
                 "before": {"type": "VARCHAR", "width": 16, "nullable": True},
                 "after": {"type": "VARCHAR", "width": 32, "nullable": True}}


def load_registration():
    data = PR_EVIDENCE.read_bytes()
    receipt = json.loads(data)
    if (receipt["status"] != "PASS" or receipt["upstream_pr"] != 14036 or receipt["impacted_tests"] != 1
            or receipt["head"] != {"revision": profile.HEAD[0], "blob": profile.HEAD[1]}
            or receipt["profile"] != profile.PROFILE):
        raise ValueError("The registered upstream replay does not match the schema pilot")
    return receipt, hashlib.sha256(data).hexdigest()


def arrange_inputs(work, receipt):
    for case in CASES:
        (work / case).mkdir()
        (work / f"{case.upper()}-SCHEMA.json").rename(work / case / SCHEMA_FILE)
    query_hash, test_hash = receipt["query_id_hash"], receipt["test_id_hash"]
    for case in ("baseline", "unused"):
        (work / f"{case.upper()}-INVENTORY.json").rename(work / case / INVENTORY_FILE)
        actual = profile.snapshot_shape(work, case, REVISIONS[case], query_hash, test_hash)
        if actual != receipt["head_fingerprint_hash"]:
            raise ValueError("Observed device query differs from the registered fingerprint")

    # The missing environment runs the same code. Use its successfully observed baseline inventory
    # to predict impact, then separately execute the selected query on the missing schema.
    baseline = json.loads((work / "baseline" / INVENTORY_FILE).read_bytes())
    missing = {**baseline, "revision": REVISIONS["missing"]}
    (work / "missing" / INVENTORY_FILE).write_text(json.dumps(missing), encoding="utf-8")
    for case in ("missing", "unused"):
        row = {"framework": "JDBC", "query_id_hash": query_hash, "test_ids": [test_hash],
               "fingerprint_hash": receipt["head_fingerprint_hash"],
               "columns": [{"table": "device", "column": name} for name in COLUMNS]}
        manifest = {"schema_version": 2, "revision": REVISIONS[case], "scope": profile.PROFILE,
                    "dependencies": [row]}
        (work / case / DEPENDENCIES_FILE).write_text(json.dumps(manifest), encoding="utf-8")


def impact(work, case, expected_change, affected):
    launcher = ('import os,runpy,sys; os.chdir(sys.argv.pop(2)); '
                'sys.argv.pop(0); runpy.run_path(sys.argv[0],run_name="__main__")')
    command = [sys.executable, "-B", "-c", launcher, str(replay.ROOT / "tools/schema-impact.py"), str(work),
               "--base", f"baseline/{SCHEMA_FILE}", "--head", f"{case}/{SCHEMA_FILE}",
               "--inventory", f"{case}/{INVENTORY_FILE}", "--dependencies", f"{case}/{DEPENDENCIES_FILE}"]
    guard.run_step(f"impact-{case}", command, work, timeout=10)
    data = (work / f"impact-{case}.output").read_bytes()
    report = json.loads(data)
    selected = [test for row in affected for test in row["test_ids"]]
    if (report["status"] != "COMPLETE" or report["changes"] != [expected_change]
            or report["affected_queries"] != affected or report["impacted_test_ids"] != selected
            or report["coverage_reasons"] or report["unresolved_queries"]):
        raise ValueError("Unexpected schema impact or test selection")
    return {"status": report["status"], "change": expected_change,
            "impacted_test_ids": selected, "report_sha256": hashlib.sha256(data).hexdigest()}


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, guard.interrupted)
    if not replay.host_ready():
        print(json.dumps({"status": "NOT RUN", "reason": "POSTGRESQL_HOST_PREFLIGHT"}))
        return 2
    receipt, registration_hash = load_registration()
    jdbc = profile.PILOT / "dao-reactor-maven-cache/org/postgresql/postgresql/42.7.14/postgresql-42.7.14.jar"
    if not jdbc.is_file():
        raise ValueError("The pilot PostgreSQL JDBC JAR is missing")
    java = Path(replay.inspect("/usr/libexec/java_home", "-v", "21"))
    _, _, scope, query, test, tenant, other_tenant, _, sql, _ = profile.replay_input()
    fixture_input = (scope, sql, *(REVISIONS[case] for case in CASES))
    with (profile.PILOT / ".dao-reactor.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with guard.workspace("udak-device-schema-impact-") as (work, cleanup):
            classes = replay.compile_replay(work, jdbc, java, FIXTURE_CLASS,
                                            support_classes=(profile.REPLAY_CLASS,))
            with replay.postgres_fixture() as fixture:
                prepare = replay.run_jdbc("schema-fixtures", work, classes, jdbc, java,
                                          (*fixture_input, query, test, tenant, other_tenant),
                                          fixture, FIXTURE_CLASS, "prepare")
                if prepare.get("assertions") != 2:
                    raise ValueError("Expected both baseline and unused-column query results")
                arrange_inputs(work, receipt)
                affected = [{"framework": "JDBC", "query_id_hash": receipt["query_id_hash"],
                             "test_ids": [receipt["test_id_hash"]]}]
                missing = impact(work, "missing", MISSING_CHANGE, affected)
                unused = impact(work, "unused", UNUSED_CHANGE, [])
                schema_bytes = (work / "missing" / SCHEMA_FILE).read_bytes()
                replay.run_jdbc("selected-replay", work, classes, jdbc, java, fixture_input, fixture,
                                FIXTURE_CLASS, "replay", hashlib.sha256(schema_bytes).hexdigest())
                if ((work / "selected-replay.output").read_text().strip() != "SQLSTATE=42703"
                        or (work / "MISSING-REPLAY-SCHEMA.json").read_bytes() != schema_bytes):
                    raise ValueError("Selected replay or schema identity did not match")
            snapshots = {case: hashlib.sha256((work / case / SCHEMA_FILE).read_bytes()).hexdigest()
                         for case in CASES}
    print(json.dumps({"schema_version": 1, "requirement": "NEXT-004", "status": "PASS",
                      "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                      "upstream_pr": 14036, "upstream_revision": profile.HEAD[0],
                      "registered_replay_evidence_sha256": registration_hash,
                      "query_id_hash": receipt["query_id_hash"], "fingerprint_hash": receipt["head_fingerprint_hash"],
                      "test_id_hash": receipt["test_id_hash"], "profile": scope,
                      "postgresql_image": replay.IMAGE, "image_digest": replay.INDEX, "jdbc_version": "42.7.14",
                      "fixture_schema_sha256": snapshots, "baseline_and_control_query_assertions": 2,
                      "missing_customer_id": missing, "unused_column": unused, "selected_replay_sqlstate": "42703",
                      "selected_replay_schema_sha256": snapshots["missing"],
                      "container_cleanup": "PASS", "workspace_cleanup": cleanup}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
