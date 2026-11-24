#!/usr/bin/env python3
"""Apply one reviewed Flyway migration and validate its PostgreSQL history export."""
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


ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("pg_migration", ROOT / "tools/run-postgresql-schema-migration.py")
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)
postgres, migration, replay, guard = pilot.postgres, pilot.migration, pilot.replay, pilot.guard
SOURCES = (postgres.SOURCES[0],
           "schema-regression/src/main/java/dev/udak/schema/FlywayHistoryCollector.java",
           "schema-regression/src/test/java/dev/udak/schema/FlywayHistoryPostgreSqlTest.java")
CLASS = "dev.udak.schema.FlywayHistoryPostgreSqlTest"
DEPENDENCIES = ROOT / "tools/flyway-test-dependencies.json"
CAPTURES = {"baseline": "EMPTY", "matched": "VERIFIED", "missing": "EMPTY",
            "missing-proof": "HISTORY_FILE_UNVERIFIED", "same-crc-different-file": "HISTORY_FILE_UNVERIFIED"}
DEVICE_PROOF = ROOT / "evidence/THINGSBOARD-DEVICE-DAO-FOLLOWUP-VALIDATION.json"


def java_classpath(work):
    jdbc, version, digest = postgres.driver(work)
    lock = json.loads(DEPENDENCIES.read_bytes())
    if lock["schema_version"] != 1 or lock["license"] != "Apache-2.0" or len(lock["artifacts"]) != 5:
        raise ValueError("Unexpected Flyway test dependency lock")
    classpath = [str(jdbc)]
    for artifact in lock["artifacts"]:
        group, name, pinned = artifact["coordinate"].split(":")
        if not all(re.fullmatch(r"[a-zA-Z0-9._-]+", value) for value in (group, name, pinned)):
            raise ValueError("Invalid Flyway test coordinates")
        filename = f"{name}-{pinned}.jar"
        url = f"https://repo.maven.apache.org/maven2/{group.replace('.', '/')}/{name}/{pinned}/{filename}"
        if not 0 < artifact["jar_bytes"] <= 4_000_000:
            raise ValueError("Flyway test artifact size exceeded")
        data = postgres.g2.fetch(url, artifact["jar_bytes"])
        if len(data) != artifact["jar_bytes"] or guard.digest(data) != artifact["jar_sha512"]:
            raise ValueError("Flyway test artifact integrity mismatch")
        path = work / filename
        with path.open("xb") as stream:
            stream.write(data)
        classpath.append(str(path))
    return os.pathsep.join(classpath), version, digest


def verify_capture(work, revisions):
    heads = [(work / case / postgres.SNAPSHOT).read_bytes() for case in CAPTURES if case != "baseline"]
    if any(raw != heads[0] for raw in heads[1:]):
        raise ValueError("Flyway controls did not observe the same schema change")
    results = {}
    for case, expected in CAPTURES.items():
        directory = work / case
        status = (directory / "status").read_text().strip()
        history = directory / migration.HISTORY_FILENAME
        if status != expected:
            raise ValueError("Unexpected Flyway export status")
        results[case] = {"capture_status": status, "history_exported": history.exists()}
        if status == "HISTORY_FILE_UNVERIFIED":
            if history.exists():
                raise ValueError("Unverified Flyway file produced comparison input")
            results[case].update(status="UNRESOLVED", reasons=[status])
            continue
        rows = [pilot.EXPECTED_MIGRATION] if status == "VERIFIED" else []
        revision = revisions[0] if case == "baseline" else revisions[1]
        if json.loads(history.read_bytes()) != {"schema_version": 1, "scope": pilot.SCOPE,
                                               "revision": revision, "migrations": rows}:
            raise ValueError("Unexpected Flyway history export")
    return results


def compare(work, revisions, cases):
    base, head = revisions
    change_digest = migration.changes_digest([pilot.REMOVED])
    manifest = {"schema_version": 1, "base_revision": base, "revision": head, "scope": pilot.SCOPE,
                **pilot.EXPECTED_MIGRATION, "expected_changes_sha256": change_digest}
    (work / migration.MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    launcher = ('import os,runpy,sys; os.chdir(sys.argv.pop(2)); '
                'sys.argv.pop(0); runpy.run_path(sys.argv[0],run_name="__main__")')
    for case, status, expected in (("matched", "MATCHED", 0), ("missing", "UNRESOLVED", 2)):
        name = f"compare-{case}"
        result = guard.run_step(name, [sys.executable, "-B", "-c", launcher,
            str(ROOT / "tools/schema-migration.py"), str(work),
            "--base", f"baseline/{postgres.SNAPSHOT}", "--head", f"{case}/{postgres.SNAPSHOT}",
            "--base-history", f"baseline/{migration.HISTORY_FILENAME}",
            "--head-history", f"{case}/{migration.HISTORY_FILENAME}",
            "--manifest", migration.MANIFEST_FILENAME], work, timeout=10, expected=expected)
        raw = (work / f"{name}.output").read_bytes()
        report = json.loads(raw)
        reasons = ["HISTORY_MISSING"] if expected else []
        applied = [] if expected else [pilot.EXPECTED_MIGRATION]
        if report != {"schema_version": 1, "status": status, "reasons": reasons, "base_revision": base,
                      "head_revision": head, "scope": pilot.SCOPE, "expected_migration": pilot.EXPECTED_MIGRATION,
                      "newly_applied": applied, "observed_changes": [pilot.REMOVED],
                      "observed_changes_sha256": change_digest, "expected_changes_sha256": change_digest}:
            raise ValueError("Flyway history comparison did not match the approved change")
        cases[case].update(status=status, exit_code=result["exit_code"], reasons=reasons,
                           observed_changes=report["observed_changes"], report_sha256=hashlib.sha256(raw).hexdigest())


def registered_device(upstream):
    data = DEVICE_PROOF.read_bytes()
    registration = json.loads(data)
    if (registration["status"] != "PASS" or registration["upstream_pr"] != 14036 or registration["impacted_tests"] != 1
            or registration["head"] != {"revision": upstream.HEAD[0], "blob": upstream.HEAD[1]}
            or registration["profile"] != upstream.PROFILE):
        raise ValueError("The registered ThingsBoard replay evidence is missing")
    return registration, hashlib.sha256(data).hexdigest()


def verify_pr_reports(work, revisions, cases, registration):
    base = json.loads((work / "baseline/SQL-INVENTORY.json").read_bytes())
    entry, = base["entries"]
    shape, = entry["shapes"]
    query_hash, test_hash = registration["query_id_hash"], registration["test_id_hash"]
    fingerprint = registration["head_fingerprint_hash"]
    if (base["schema_version"] != 2 or base["revision"] != revisions[0] or base["profile"] != pilot.SCOPE
            or base["dropped"] != 0 or entry["framework"] != "JDBC" or entry["identity"] != "SCOPED"
            or entry["query_id_hash"] != query_hash or entry["observed"] != 1 or entry["unavailable"] != 0
            or entry["test_ids"] != [test_hash] or shape != {
                "fingerprint_hash": fingerprint, "statement_kind": "SELECT", "test_ids": [test_hash]}):
        raise ValueError("Observed ThingsBoard query does not match the registered replay")
    # The candidate uses the same code. Reuse its successful baseline observations for the impact forecast.
    (work / "SQL-INVENTORY.json").write_text(json.dumps({**base, "revision": revisions[1]}), encoding="utf-8")
    row = {"framework": "JDBC", "query_id_hash": query_hash, "fingerprint_hash": fingerprint, "test_ids": [test_hash],
           "columns": [{"table": "device", "column": name} for name in (
               "created_time", "customer_id", "device_profile_id", "id", "tenant_id")]}
    dependencies = {"schema_version": 2, "revision": revisions[1], "scope": pilot.SCOPE, "dependencies": [row]}
    (work / "QUERY-DEPENDENCIES.json").write_text(json.dumps(dependencies), encoding="utf-8")
    launcher = ('import os,runpy,sys; os.chdir(sys.argv.pop(2)); '
                'sys.argv.pop(0); runpy.run_path(sys.argv[0],run_name="__main__")')
    reports = {}
    for case, outcome in cases.items():
        if case == "baseline":
            continue
        capture = {"status": outcome["capture_status"], "revision": revisions[1], "scope": pilot.SCOPE}
        if outcome["history_exported"]:
            capture["history"] = f"{case}/{migration.HISTORY_FILENAME}"
        request = {"schema_version": 1, "base_schema": f"baseline/{postgres.SNAPSHOT}",
                   "head_schema": f"{case}/{postgres.SNAPSHOT}", "dependencies": "QUERY-DEPENDENCIES.json",
                   "base_history": f"baseline/{migration.HISTORY_FILENAME}", "manifest": migration.MANIFEST_FILENAME,
                   "flyway_capture": capture}
        (work / case / "SCHEMA-REVIEW.json").write_text(json.dumps(request), encoding="utf-8")
        args = [sys.executable, "-B", "-c", launcher, str(ROOT / "tools/run-sql-inventory.py"), str(work),
                "--pr-report", "--base", "baseline/SQL-INVENTORY.json", "--head", "SQL-INVENTORY.json",
                "--schema-review", f"{case}/SCHEMA-REVIEW.json", "--fail-on-change"]
        code = 0 if outcome["status"] == "MATCHED" else 2
        status = "COMPLETE" if code == 0 else "INCOMPLETE"
        guard.run_step(f"pr-{case}-json", args, work, timeout=25, expected=code)
        guard.run_step(f"pr-{case}-markdown", [*args, "--format", "markdown"], work, timeout=25, expected=code)
        raw = (work / f"pr-{case}-json.output").read_bytes()
        markdown = (work / f"pr-{case}-markdown.output").read_bytes()
        report = json.loads(raw)
        history = {key: outcome[key] for key in ("status", "reasons")}
        head_sha = hashlib.sha256((work / case / postgres.SNAPSHOT).read_bytes()).hexdigest()
        expected = {"status": status, "change": pilot.REMOVED, "flyway_history": history,
                    "head_schema_sha256": head_sha,
                    "impacted_test_ids": [test_hash], "coverage_reasons": [], "unresolved_queries": [],
                    "affected_queries": [{"framework": "JDBC", "query_id_hash": query_hash, "test_ids": [test_hash]}]}
        if report["schema_review"] != expected or report["status"] != status \
                or report["changes_detected"] is not False or report["impacted_test_ids"]:
            raise ValueError("PR report did not bind the Flyway verdict to the schema-impacted replay")
        for label in ("## Schema change and Flyway history", "device.customer_id", history["status"],
                      "Schema-impacted registered tests", test_hash, *history["reasons"]):
            if label.encode() not in markdown:
                raise ValueError("Markdown PR review is incomplete")
        reports[case] = {"exit_code": code, **expected,
                         "json_sha256": hashlib.sha256(raw).hexdigest(),
                         "markdown_sha256": hashlib.sha256(markdown).hexdigest()}
    return {"query_id_hash": query_hash, "fingerprint_hash": fingerprint, "test_id_hash": test_hash,
            "observation_origin": "SUCCESSFUL_POSTGRESQL_BASELINE", "entrypoint": "tools/run-sql-inventory.py --pr-report",
            "reports": reports}


def verify_registered_replay(work, registration, run_registered):
    planner = postgres.load("schema_pr_regression", "tools/schema-pr-regression.py")
    reports = {case: json.loads((work / f"pr-{case}-json.output").read_bytes())
               for case in CAPTURES if case != "baseline"}
    target = (work / "matched" / postgres.SNAPSHOT).read_bytes()
    baseline = (work / "baseline" / postgres.SNAPSHOT).read_bytes()
    matched = reports["matched"]
    decisions = {case: planner.plan(report, (work / case / postgres.SNAPSHOT).read_bytes(), registration, pilot.REMOVED)
                 for case, report in reports.items()}
    changed = {**matched, "schema_review": {**matched["schema_review"], "impacted_test_ids": ["f" * 64]}}
    decisions["unregistered"] = planner.plan(changed, target, registration, pilot.REMOVED)
    decisions["snapshot-mismatch"] = planner.plan(matched, baseline, registration, pilot.REMOVED)
    expected_reasons = {"missing": "HISTORY_UNRESOLVED", "missing-proof": "HISTORY_UNRESOLVED",
                        "same-crc-different-file": "HISTORY_UNRESOLVED", "unregistered": "UNKNOWN_TEST_HASH",
                        "snapshot-mismatch": "SCHEMA_MISMATCH"}
    for case, reason in expected_reasons.items():
        decision = decisions[case]
        if (decision["status"] != "REVIEW_REQUIRED" or reason not in decision["reasons"]
                or decision["entry_point"] is not None):
            raise ValueError("Unsafe schema replay selection")
    selected = decisions["matched"]
    if selected["status"] != "READY" or selected["entry_point"] != planner.ENTRY_POINT:
        raise ValueError("The registered schema replay was not selected")
    replayed = run_registered("registered-replay", selected["head_schema_sha256"])
    mismatch = run_registered("runtime-schema-mismatch", hashlib.sha256(baseline).hexdigest())
    digest = selected["head_schema_sha256"]
    if (replayed != f"PASS SQLSTATE=42703 query_executions=1 schema_sha256={digest}"
            or mismatch != f"REVIEW_REQUIRED SCHEMA_MISMATCH query_executions=0 schema_sha256={digest}"):
        raise ValueError("Registered schema replay or pre-query schema rejection did not pass")
    return {"selection": selected, "executed_queries": 1, "sqlstate": "42703", "schema_sha256": digest,
            "guarded_report_sha256": hashlib.sha256((work / "pr-matched-json.output").read_bytes()).hexdigest(),
            "blocked_before_dispatch": {case: {"status": decision["status"], "reasons": decision["reasons"],
                                               "query_executions": 0} for case, decision in decisions.items()
                                        if case != "matched"},
            "runtime_schema_mismatch": {"status": "REVIEW_REQUIRED", "reason": "SCHEMA_MISMATCH",
                                        "query_executions": 0, "actual_schema_sha256": digest,
                                        "expected_schema_sha256": hashlib.sha256(baseline).hexdigest()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--pr-report", action="store_true", help="verify the Flyway schema review in the PR report")
    mode.add_argument("--pr-replay", action="store_true", help="verify the PR report and replay its registered test")
    args = parser.parse_args()
    for event in (signal.SIGINT, signal.SIGTERM):
        signal.signal(event, guard.interrupted)
    if not replay.host_ready():
        print(json.dumps({"status": "NOT RUN", "reason": "POSTGRESQL_HOST_PREFLIGHT"}))
        return 2
    approved = pilot.SQL.read_bytes()
    if hashlib.sha256(approved).hexdigest() != pilot.CHECKSUM:
        raise ValueError("Reviewed migration bytes changed")
    alternate = approved.replace(b"\n", b"\r\n")
    fixture = (ROOT / SOURCES[-1]).read_bytes()
    revisions = (hashlib.sha256(fixture).hexdigest(), hashlib.sha256(fixture + approved).hexdigest())
    query_input = ()
    registration = None
    if args.pr_report or args.pr_replay:
        upstream = postgres.load("device_profile", "tools/thingsboard-pilot/replay-upstream-device-profile.py")
        registration, registration_sha = registered_device(upstream)
        _, _, _, query, test, tenant, _, _, sql, _ = upstream.replay_input()
        query_input = (sql, tenant, query, test)
    java = Path(replay.inspect("/usr/libexec/java_home", "-v", "21"))
    lock_dir = ROOT / ".git/udak-g2-managed"
    lock_dir.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(lock_dir / "RUN.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with guard.workspace("udak-flyway-history-") as (work, cleanup):
            classpath, version, jdbc_digest = java_classpath(work)
            classes = work / "classes"
            observe = sorted((ROOT / "observe-core/src/main/java").rglob("*.java"))
            observe += sorted((ROOT / "legacy-observe/src/main/java/dev/udak/observe/jdbc").glob("*.java"))
            guard.run_step("compile", [str(java / "bin/javac"), "-J-Xmx160m", "-J-XX:ActiveProcessorCount=1",
                           "--release", "17", "-cp", classpath, "-d", str(classes), *SOURCES, *map(str, observe),
                           "sql-inventory/src/main/java/dev/udak/inventory/InventoryCapture.java"], work, timeout=20)
            for case in (*CAPTURES, "empty", "reviewed", "alternate"):
                (work / case).mkdir()
            (work / "reviewed" / pilot.SQL.name).write_bytes(approved)
            (work / "alternate" / pilot.SQL.name).write_bytes(alternate)
            with replay.postgres_fixture() as (port, password):
                if not replay.host_ready():
                    raise RuntimeError("Host resource guard stopped fixture")
                result = guard.run_step("collect", [str(java / "bin/java"), "-Xmx160m", "-XX:ActiveProcessorCount=1",
                    "-cp", f"{classes}{os.pathsep}{classpath}", CLASS, port, str(work), *revisions,
                    pilot.SCOPE, pilot.CHECKSUM], work, timeout=32,
                    private_input=("\n".join((password, *query_input)) + "\n").encode())
                protocol = (work / "collect.output").read_text()
                proof = re.fullmatch(r"native_checksum=(-?[0-9]{1,10})\nassertions=([1-9][0-9]*)\n", protocol)
                if not proof or result.get("assertions") != int(proof[2]):
                    raise ValueError("Flyway evidence protocol did not pass")
                cases = verify_capture(work, revisions)
                compare(work, revisions, cases)
                pr_review = {}
                if registration is not None:
                    pr_review["pr_schema_review"] = verify_pr_reports(work, revisions, cases, registration)
                if args.pr_replay:
                    def run_registered(name, expected_schema):
                        if not replay.host_ready():
                            raise RuntimeError("Host resource guard stopped replay")
                        guard.run_step(name, [str(java / "bin/java"), "-Xmx160m", "-XX:ActiveProcessorCount=1",
                            "-cp", f"{classes}{os.pathsep}{classpath}", CLASS, "--replay-registered",
                            port, revisions[1], pilot.SCOPE, expected_schema], work, timeout=15,
                            private_input=(password + "\n" + query_input[0] + "\n").encode())
                        return (work / f"{name}.output").read_text().strip()

                    registered = verify_registered_replay(work, registration, run_registered)
                    pr_review["registered_replay"] = {**registered, "registration_sha256": registration_sha}
    print(json.dumps({"schema_version": 1, "requirement": "NEXT-004", "status": "PASS",
                      "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                      "flyway_version": "11.20.3", "postgresql_image": replay.IMAGE, "image_digest": replay.INDEX,
                      "jdbc_version": version, "jdbc_sha512": jdbc_digest, "scope": pilot.SCOPE,
                      "base_revision": revisions[0], "head_revision": revisions[1], "jdbc_read_only_capture": True,
                      "reviewed_migration": pilot.EXPECTED_MIGRATION, "flyway_native_checksum": int(proof[1]),
                      "alternate_file_sha256": hashlib.sha256(alternate).hexdigest(),
                      "alternate_native_validation_passed": True, "fixture_assertions": int(proof[2]), "cases": cases,
                      "container_cleanup": "PASS", "workspace_cleanup": cleanup, **pr_review}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
