#!/usr/bin/env python3
"""Run and time the verified NEXT-005 adoption procedure at a maintainer's terminal."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools/thingsboard-pilot"
PILOT = ROOT.parent / "thingsboard-ce-v4.3.1.8-pilot"
LAYOUT = PILOT / "published-dao-baseline-4.3.1.8"
CACHE = PILOT / "dao-reactor-maven-cache"
TEST_CLASS = Path("target/test-classes/org/thingsboard/server/dao/service/DeviceServiceTest.class")
REVIEW = ROOT / "evidence/THINGSBOARD-NEXT-005-ADOPTION-REVIEW.json"
spec = importlib.util.spec_from_file_location("count_replay", TOOLS / "replay-upstream-count.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)
guard = replay.guard


def require(condition):
    if not condition:
        raise ValueError("Pilot verification did not pass")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seconds_since(start):
    return round((time.monotonic_ns() - start) / 1e9, 3)


def setup_overlay(java):
    supplier = read_json(PILOT / "published-thingsboard-4.3.1.8/PUBLISHED-DAO-ARTIFACTS.json")
    tb1 = read_json(PILOT / "official-tb1-maven-8u12swc8/OFFICIAL-TB1-ARTIFACTS.json")
    require(supplier["status"] == tb1["status"] == "PASS")
    records = supplier["files"] + tb1["artifacts"]
    require(len(supplier["files"]) == 26 and len(tb1["artifacts"]) == 6)
    for row in records:
        relative = Path(row.get("path") or row["maven_path"])
        require(not relative.is_absolute() and ".." not in relative.parts)
        item = LAYOUT / "mirror" / relative
        require(item.is_file() and not item.is_symlink() and digest(item) == row["sha256"])

    jars = []
    for group, modules, version in (
        ("org/springframework", ("spring-test", "spring-beans", "spring-context", "spring-core",
                               "spring-jcl", "spring-orm", "spring-tx"), "6.2.19"),
        ("org/hibernate/orm", ("hibernate-core",), "6.6.53.Final"),
        ("jakarta/persistence", ("jakarta.persistence-api",), "3.1.0"),
    ):
        jars.extend(CACHE / group / name / version / f"{name}-{version}.jar" for name in modules)
    require(all(path.is_file() for path in jars))
    sources = sorted((ROOT / "observe-core/src/main/java").rglob("*.java"))
    sources.extend((
        ROOT / "legacy-observe/src/main/java/dev/udak/observe/hibernate/HibernateObserveInspector.java",
        ROOT / "sql-inventory/src/main/java/dev/udak/inventory/InventoryCapture.java",
        TOOLS / "dev/udak/pilot/ThingsBoardObserve.java",
    ))
    with guard.workspace("udak-maintainer-setup-") as (work, cleanup):
        classes = work / "overlay"
        classes.mkdir()
        guard.run_step("compile", [str(java / "bin/javac"), "-J-Xmx160m", "-J-XX:+UseSerialGC",
                                   "-J-XX:ActiveProcessorCount=1", "--release", "17", "-cp",
                                   ":".join(map(str, jars)), "-d", str(classes), *map(str, sources)],
                       work, timeout=20)
        (classes / "META-INF").mkdir()
        shutil.copyfile(TOOLS / "META-INF/spring.factories", classes / "META-INF/spring.factories")
        project = work / "project"
        shutil.copytree(LAYOUT / "project", project)
        expected = digest(LAYOUT / "project" / TEST_CLASS)
        archive = LAYOUT / "mirror/org/thingsboard/dao/4.3.1.8/dao-4.3.1.8-tests.jar"
        with ZipFile(archive) as published_tests:
            entry = TEST_CLASS.relative_to("target/test-classes").as_posix()
            require(hashlib.sha256(published_tests.read(entry)).hexdigest() == expected)
        files = [file for file in classes.rglob("*") if file.is_file()]
        require(len(files) == 28)
        for source in files:
            target = project / "target/test-classes" / source.relative_to(classes)
            require(not target.exists())
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        require(digest(project / TEST_CLASS) == expected)
    return {"supplier_artifacts": len(records), "overlay_files": len(files),
            "official_test_class_unchanged": True, "cleanup": cleanup["status"]}


def verify(java):
    expected = read_json(REVIEW)
    findings = expected["timing"]["postgresql_replay_and_report_review"]["findings"]
    require(expected["technical_review_status"] == "PASS")
    driver = CACHE / "org/postgresql/postgresql/42.7.14/postgresql-42.7.14.jar"
    require(driver.is_file())
    values = replay.count_sql()
    with guard.workspace("udak-maintainer-verify-") as (work, cleanup):
        classes = replay.compile_replay(work, driver, java)
        replay.replay(work, classes, driver, java, values)
        replay.check_reports(work)
        before = read_json(work / "base/SQL-INVENTORY.json")
        after = read_json(work / "head/SQL-INVENTORY.json")
        report = read_json(work / "change.output")
        report_hash = digest(work / "change.output")
        control = read_json(work / "control.output")
        query, = report["queries"]
        test = findings["test_id_hash"]
        require(query["query_id_hash"] == findings["query_id_hash"] and query["impacted_test_ids"] == [test])
        for snapshot, expected_hash in (
            (before, findings["removed_fingerprint_hash"]), (after, findings["added_fingerprint_hash"]),
        ):
            require(snapshot["schema_version"] == 2)
            entry, = snapshot["entries"]
            shape, = entry["shapes"]
            require(shape["fingerprint_hash"] == expected_hash and shape["test_ids"] == [test])
        require(control["impacted_test_ids"] == [])
        regression = guard.run_step("inventory-regression",
            [sys.executable, "-B", str(ROOT / "tools/test-sql-inventory.py")], work, timeout=12)
        require(regression["status"] == "PASS")
    return {"postgresql_assertions": 3, "changed_queries": 1, "uuid_only_changes": 0,
            "impacted_test_hash": test, "change_report_sha256": report_hash,
            "inventory_regression": "PASS", "fixture_cleanup": "PASS", "workspace_cleanup": cleanup["status"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--role", choices=("thingsboard-maintainer", "udak-maintainer"))
    mode.add_argument("--rehearsal", action="store_true")
    args = parser.parse_args()
    if args.role and not (sys.stdin.isatty() and sys.stdout.isatty()):
        parser.error("The maintainer session requires an interactive terminal")
    if not replay.host_ready():
        print("호스트 자원 조건 미충족 / Host resource preflight did not pass.")
        return 2

    signal.signal(signal.SIGTERM, guard.interrupted)
    signal.signal(signal.SIGINT, guard.interrupted)
    report = {"status": "INCOMPLETE", "operator_role": args.role, "identity_verified": False,
              "measurement_origin": "REHEARSAL" if args.rehearsal else "OPERATOR_SELF_DECLARED",
              "input_scope": "VERIFIED_WARM_CACHE", "manual_review_recorded": False}
    java = Path(replay.inspect("/usr/libexec/java_home", "-v", "21"))
    stage = "setup"
    try:
        with (PILOT / ".dao-reactor.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.role:
                input("설정 시작 / Start artifact and Observe setup (Enter): ")
            start = time.monotonic_ns()
            report["setup"] = setup_overlay(java)
            if args.role:
                print(json.dumps(report["setup"], ensure_ascii=False))
                require(input("원본 테스트 보존과 정리 확인 / Review test integrity and cleanup (CONFIRM): ").strip()
                        == "CONFIRM")
            report["setup_elapsed_seconds"] = seconds_since(start)

            stage = "verification"
            if args.role:
                input("검증 시작 / Replay PR #14858 and the UUID control on PostgreSQL (Enter): ")
            start = time.monotonic_ns()
            report["verification"] = verify(java)
            if args.role:
                print(json.dumps(report["verification"], ensure_ascii=False))
                require(input("보고서 변경 수, 대조군 변경 수 / Enter the change and control counts: ").split()
                        == ["1", "0"])
                report["manual_review_recorded"] = True
            report["verification_elapsed_seconds"] = seconds_since(start)
            report["status"] = "PASS"
    except (EOFError, KeyboardInterrupt, OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        report.update(stopped_at=stage, stop_category=type(error).__name__)
    report["recorded_at_utc"] = datetime.now(timezone.utc).isoformat()
    output = LAYOUT / f"NEXT-005-MAINTAINER-{uuid.uuid4().hex[:12]}.json"
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False))
    print(f"기록 파일: {output.name}")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
