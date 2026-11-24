#!/usr/bin/env python3
"""Run and time the verified NEXT-005 adoption procedure at a maintainer's terminal."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
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
SETUP_CONTRACT = "THINGSBOARD_OBSERVE_SETUP_V1"
SETUP_RESULT = {"supplier_artifacts": 32, "overlay_files": 28,
                "official_test_class_unchanged": True, "cleanup": "PASS"}
SETUP_WAIT_SECONDS = 60
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


class SetupResourceTimeout(RuntimeError):
    """Setup is still blocked after the bounded readiness wait."""


def setup_resources():
    pressure = replay.inspect("/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level")
    swap = replay.inspect("/usr/sbin/sysctl", "-n", "vm.swapusage")
    match = re.search(r"\bfree = (\d+(?:\.\d+)?)M", swap)
    free = float(match[1]) if match else None
    return {"memory_pressure_level": int(pressure) if pressure.isdecimal() else None,
            "free_swap_mib": free,
            "ready": pressure in {"1", "2"} and free is not None and free >= 768}


def wait_for_setup():
    sample = setup_resources()
    if sample["ready"]:
        return sample
    print(f"설정 자원 대기, 계측 전 / Waiting for setup resources, up to {SETUP_WAIT_SECONDS}s.",
          flush=True)
    deadline = time.monotonic() + SETUP_WAIT_SECONDS
    while not sample["ready"]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(remaining, 3))
        sample = setup_resources()
    return sample


def resume_setup(name, role):
    require(re.fullmatch(r"NEXT-005-MAINTAINER-[a-f0-9]{12}\.json", name) is not None)
    path = LAYOUT / name
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_size <= 8192)
        content = stream.read(8193)
        require(len(content) <= 8192)
        record = json.loads(content)
    require(isinstance(record, dict))
    require(record.get("status") in ("PENDING_VERIFICATION", "INCOMPLETE")
            and record.get("measurement_origin") == "OPERATOR_SELF_DECLARED"
            and record.get("operator_role") == role
            and record.get("setup_contract") == SETUP_CONTRACT
            and record.get("setup_confirmed") is True
            and record.get("setup") == SETUP_RESULT)
    elapsed = record.get("setup_elapsed_seconds")
    require(type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0)
    return {"setup": record["setup"], "setup_elapsed_seconds": elapsed, "setup_confirmed": True,
            "resumed_from": name}


def save_receipt(path, report):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                        prefix=".maintainer-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({**report, "recorded_at_utc": datetime.now(timezone.utc).isoformat()}, stream, indent=2)
            stream.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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
    parser.add_argument("--resume", metavar="RECEIPT_NAME")
    args = parser.parse_args()
    if args.role and not (sys.stdin.isatty() and sys.stdout.isatty()):
        parser.error("The maintainer session requires an interactive terminal")
    if args.resume and not args.role:
        parser.error("Resuming requires the maintainer's declared role")

    signal.signal(signal.SIGTERM, guard.interrupted)
    signal.signal(signal.SIGINT, guard.interrupted)
    report = {"status": "INCOMPLETE", "operator_role": args.role, "identity_verified": False,
              "measurement_origin": "REHEARSAL" if args.rehearsal else "OPERATOR_SELF_DECLARED",
              "input_scope": "VERIFIED_WARM_CACHE", "manual_review_recorded": False,
              "setup_contract": SETUP_CONTRACT}
    if args.resume:
        try:
            report.update(resume_setup(args.resume, args.role))
        except (OSError, ValueError, OverflowError):
            parser.error("Invalid, completed or mismatched setup receipt")
    java = Path(replay.inspect("/usr/libexec/java_home", "-v", "21"))
    output = LAYOUT / f"NEXT-005-MAINTAINER-{uuid.uuid4().hex[:12]}.json"
    stage = "setup"
    try:
        with (PILOT / ".dao-reactor.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if not args.resume:
                if args.role:
                    input("설정 시작 / Start artifact and Observe setup (Enter): ")
                resources = wait_for_setup()
                report["setup_preflight"] = resources
                if not resources["ready"]:
                    raise SetupResourceTimeout()
                start = time.monotonic_ns()
                report["setup"] = setup_overlay(java)
                require(report["setup"] == SETUP_RESULT)
                if args.role:
                    print(json.dumps(report["setup"], ensure_ascii=False))
                    require(input("원본 테스트 보존과 정리 확인 / Review test integrity and cleanup (CONFIRM): ").strip()
                            == "CONFIRM")
                    report["setup_confirmed"] = True
                report["setup_elapsed_seconds"] = seconds_since(start)

            stage = "verification"
            report["status"] = "PENDING_VERIFICATION"
            if args.role and not args.resume:
                save_receipt(output, report)
                print(f"설정 시간 저장 / Setup timing saved: {output.name}", flush=True)
            ready = replay.host_ready()
            if ready and args.role:
                input("검증 시작 / Replay PR #14858 and the UUID control on PostgreSQL (Enter): ")
                ready = replay.host_ready()
            if ready:
                start = time.monotonic_ns()
                report["verification"] = verify(java)
                require(report["verification"]["fixture_cleanup"] ==
                        report["verification"]["workspace_cleanup"] == "PASS")
                if args.role:
                    print(json.dumps(report["verification"], ensure_ascii=False))
                    require(input("보고서 변경 수, 대조군 변경 수 / Enter the change and control counts: ").split()
                            == ["1", "0"])
                    report["manual_review_recorded"] = True
                report["verification_elapsed_seconds"] = seconds_since(start)
                report["status"] = "PASS"
            else:
                report["stop_category"] = "POSTGRESQL_HOST_PREFLIGHT"
                print("검증 대기. 메모리 압력 1단계 및 스왑 여유 768 MiB 이상이 필요합니다. / PostgreSQL preflight did not pass.")
    except SetupResourceTimeout:
        report.update(status="NOT RUN", stopped_at="setup", stop_category="SETUP_HOST_PREFLIGHT")
        sample = report["setup_preflight"]
        pressure = sample["memory_pressure_level"]
        swap = sample["free_swap_mib"]
        print(f"마지막 자원 점검 / Last sample: pressure={pressure}, free swap={swap} MiB.")
        print("설정 자원 대기 종료. 메모리 압력 1·2단계 및 스왑 여유 768 MiB 이상이 필요합니다. / Setup preflight did not pass.")
    except (EOFError, KeyboardInterrupt, OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        report.update(status="INCOMPLETE", stopped_at=stage, stop_category=type(error).__name__)
    save_receipt(output, report)
    print(json.dumps(report, ensure_ascii=False))
    print(f"기록 파일: {output.name}")
    if args.role and report["status"] != "PASS" and report.get("setup_confirmed"):
        command = [sys.executable, "-B", str(Path(__file__).resolve()), "--role", args.role, "--resume", output.name]
        print(f"검증 이어서 실행 / Resume verification:\n{shlex.join(command)}")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
