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


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
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
    java = Path(replay.inspect("/usr/libexec/java_home", "-v", "21"))
    lock_dir = ROOT / ".git/udak-g2-managed"
    lock_dir.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(lock_dir / "RUN.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with guard.workspace("udak-flyway-history-") as (work, cleanup):
            classpath, version, jdbc_digest = java_classpath(work)
            classes = work / "classes"
            guard.run_step("compile", [str(java / "bin/javac"), "-J-Xmx160m", "-J-XX:ActiveProcessorCount=1",
                           "--release", "17", "-cp", classpath, "-d", str(classes), *SOURCES], work, timeout=20)
            for case in (*CAPTURES, "empty", "reviewed", "alternate"):
                (work / case).mkdir()
            (work / "reviewed" / pilot.SQL.name).write_bytes(approved)
            (work / "alternate" / pilot.SQL.name).write_bytes(alternate)
            with replay.postgres_fixture() as (port, password):
                if not replay.host_ready():
                    raise RuntimeError("Host resource guard stopped fixture")
                result = guard.run_step("collect", [str(java / "bin/java"), "-Xmx160m", "-XX:ActiveProcessorCount=1",
                    "-cp", f"{classes}{os.pathsep}{classpath}", CLASS, port, str(work), *revisions,
                    pilot.SCOPE, pilot.CHECKSUM], work, timeout=32, private_input=(password + "\n").encode())
            protocol = (work / "collect.output").read_text()
            proof = re.fullmatch(r"native_checksum=(-?[0-9]{1,10})\nassertions=([1-9][0-9]*)\n", protocol)
            if not proof or result.get("assertions") != int(proof[2]):
                raise ValueError("Flyway evidence protocol did not pass")
            cases = verify_capture(work, revisions)
            compare(work, revisions, cases)
    print(json.dumps({"schema_version": 1, "requirement": "NEXT-004", "status": "PASS",
                      "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                      "flyway_version": "11.20.3", "postgresql_image": replay.IMAGE, "image_digest": replay.INDEX,
                      "jdbc_version": version, "jdbc_sha512": jdbc_digest, "scope": pilot.SCOPE,
                      "base_revision": revisions[0], "head_revision": revisions[1], "jdbc_read_only_capture": True,
                      "reviewed_migration": pilot.EXPECTED_MIGRATION, "flyway_native_checksum": int(proof[1]),
                      "alternate_file_sha256": hashlib.sha256(alternate).hexdigest(),
                      "alternate_native_validation_passed": True, "fixture_assertions": int(proof[2]), "cases": cases,
                      "container_cleanup": "PASS", "workspace_cleanup": cleanup}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
