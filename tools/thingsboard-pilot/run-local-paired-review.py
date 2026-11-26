#!/usr/bin/env python3
"""Compare Git review and Observe on the same pinned ThingsBoard SQL cases."""
from contextlib import nullcontext
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).resolve().relative_to(ROOT)
CLASS = "PairedDeviceCount"
REPORT = ROOT / "evidence/T-001-LOCAL-PAIRED-REVIEW.json"
POSTGRES_REPORT = REPORT.with_name("T-001-LOCAL-PAIRED-REVIEW-POSTGRESQL.json")
REGISTRATION = ROOT / "tools/thingsboard-pilot/dev/udak/pilot/UpstreamDeviceCount.java"
CLASS_SOURCE = REGISTRATION.with_name(CLASS + ".java")
DRIVER_COORDINATE = "org.postgresql:postgresql:42.7.14"
EXPECTED = {"shape": "CHANGED", "control": "UNCHANGED"}
FIXTURE_LIMIT = 180
spec = importlib.util.spec_from_file_location("count_replay", ROOT / SOURCE.with_name("replay-upstream-count.py"))
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)
guard = replay.guard


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def elapsed(start):
    return round((time.monotonic_ns() - start) / 1e9, 6)


def inputs():
    before, after = replay.upstream(replay.BASE), replay.upstream(replay.HEAD)
    original = re.findall(r'"(SELECT count\(id\) FROM device;)"', before)
    changed = re.findall(r'String\.format\("(SELECT count\(id\) FROM device WHERE tenant_id = \'%s\';)", tenantId\)', after)
    if len(original) != 1 or len(changed) != 1:
        raise ValueError("UPSTREAM_DECLARATION")
    # Run the same tenant predicate with an actual JDBC bind for both UUID cases.
    target = changed[0].replace("'%s'", "?")
    return str(uuid.uuid4()), str(uuid.uuid4()), original[0], target


def driver():
    cache = ROOT.parent / "thingsboard-ce-v4.3.1.8-pilot/dao-reactor-maven-cache"
    path = cache / "org/postgresql/postgresql/42.7.14/postgresql-42.7.14.jar"
    dependency, = (artifact for artifact in read(ROOT / "tools/g2-dependencies.json")["artifacts"]
                   if artifact["coordinate"] == DRIVER_COORDINATE)
    if (path.resolve(strict=True) != path or not path.is_file() or path.stat().st_size >= 5_000_000
            or hashlib.sha512(path.read_bytes()).hexdigest() != dependency["jar_sha512"]):
        raise ValueError("DRIVER_CHECKSUM")
    return path


def embedded_driver():
    manifest = read(ROOT / "tools/phase2-dependencies.json")
    dependency, = (item for item in manifest["artifacts"] if item["coordinate"] == "com.h2database:h2:2.3.232")
    cache = Path.home() / ".gradle/caches/modules-2/files-2.1/com.h2database/h2/2.3.232"
    for path in sorted(cache.glob("*/h2-2.3.232.jar")):
        if (path.resolve(strict=True) == path and path.is_file() and path.stat().st_size < 5_000_000
                and hashlib.sha512(path.read_bytes()).hexdigest() == dependency["jar_sha512"]):
            return path
    raise ValueError("VERIFIED_H2_DRIVER_MISSING")


def git_diff(before, after):
    result = subprocess.run(["git", "diff", "--no-index", "--no-ext-diff", "--no-textconv",
                             "--quiet", "--", str(before), str(after)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    if result.returncode not in (0, 1):
        raise ValueError("DIFF_FAILED")
    return "CHANGED" if result.returncode == 1 else "UNCHANGED"


def register_hash():
    labels = re.findall(r'private static final String TEST = "([a-z0-9-]+)";', REGISTRATION.read_text())
    if len(labels) != 1:
        raise ValueError("REGISTRATION_CONTRACT")
    return hashlib.sha256(("udak-inventory-test-id-v1\0" + labels[0]).encode()).hexdigest()


def baseline_review(work, values, execute):
    setup = time.monotonic_ns()
    first, second, base, head = values
    inputs = {"base.sql": base, "head.sql": head, "control.sql": head, "head.bind": first, "control.bind": second}
    for name, text in inputs.items():
        (work / name).write_text(text + "\n")
    execute("plain")
    setup_seconds = elapsed(setup)
    start = time.monotonic_ns()
    decisions = {"shape": git_diff(work / "base.sql", work / "head.sql"),
                 "control": git_diff(work / "head.sql", work / "control.sql")}
    distinct_values = git_diff(work / "head.bind", work / "control.bind") == "CHANGED"
    tests = [register_hash()] if decisions["shape"] == "CHANGED" else []
    return ({"setup_seconds": setup_seconds, "review_seconds": elapsed(start),
             "decisions": decisions, "value_control_inputs_differ": distinct_values, "selected_tests": tests})


def observed_review(work, execute):
    setup = time.monotonic_ns()
    execute("observe")
    for mode in ("base", "head", "control"):
        folder = work / mode
        folder.mkdir()
        (work / (mode.upper() + ".json")).rename(folder / "SQL-INVENTORY.json")
    setup_seconds = elapsed(setup)
    start = time.monotonic_ns()
    launcher = ("import os,runpy,sys; os.chdir(sys.argv.pop(2)); "
                "sys.argv.pop(0); runpy.run_path(sys.argv[0],run_name='__main__')")
    command = [sys.executable, "-B", "-c", launcher, str(ROOT / "tools/sql-inventory.py"), str(work)]
    for name, before, after in (("shape", "base", "head"), ("control", "head", "control")):
        guard.run_step(name, [*command, "--base", f"{before}/SQL-INVENTORY.json",
                              "--head", f"{after}/SQL-INVENTORY.json"], work, timeout=10)
    decisions, tests = {}, []
    for name in ("shape", "control"):
        report = read(work / (name + ".output"))
        query, = report["queries"]
        if (report["status"] != "COMPLETE" or query["framework"] != "JDBC"
                or report["changes_detected"] != (name == "shape")):
            raise ValueError("INVENTORY_COVERAGE")
        decisions[name] = {"DIFFERENT": "CHANGED", "UNCHANGED": "UNCHANGED"}.get(query["shape_status"], "UNKNOWN")
        tests.extend(query["impacted_test_ids"])
    return {"setup_seconds": setup_seconds, "review_seconds": elapsed(start),
            "decisions": decisions, "selected_tests": tests}


def score(result, regression):
    decisions = result["decisions"]
    result["outcomes"] = {
        "actual_findings": int(decisions["shape"] == "CHANGED"),
        "false_positives": int(decisions["control"] == "CHANGED"),
        "missed_findings": int(decisions["shape"] == "UNCHANGED"),
        "unknown": sum(decision == "UNKNOWN" for decision in decisions.values()),
        "total": len(decisions),
    }
    if decisions != EXPECTED or result["selected_tests"] != [regression]:
        raise ValueError("REVIEW_COMPARISON")


def input_hashes():
    files = [
        ROOT / SOURCE, ROOT / "tools/thingsboard-pilot/replay-upstream-count.py", CLASS_SOURCE, REGISTRATION,
        ROOT / "tools/sql-inventory.py", ROOT / "tools/g2-dependencies.json", ROOT / "tools/run-phase1.py",
        ROOT / "tools/phase2-dependencies.json",
        ROOT / "evidence/THINGSBOARD-NEXT-005-MAINTAINER-REVIEW.json",
        ROOT / "sql-inventory/src/main/java/dev/udak/inventory/InventoryCapture.java",
    ]
    files.extend(sorted((ROOT / "observe-core/src/main/java").rglob("*.java")))
    files.extend(sorted((ROOT / "legacy-observe/src/main/java/dev/udak/observe/jdbc").glob("*.java")))
    if any(path.resolve(strict=True) != path or any(".env" in part.lower() for part in path.relative_to(ROOT).parts)
           for path in files):
        raise ValueError("UNSAFE_INPUT_PATH")
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in files}


def compare(result, use_postgres, path):
    if use_postgres and not replay.host_ready():
        raise ValueError("HOST_RESOURCES")
    if path.exists():
        raise ValueError("EVIDENCE_ALREADY_EXISTS")
    lock_path = ROOT / ".git/udak-g2-managed/RUN.lock"
    with os.fdopen(os.open(lock_path, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600), "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        expected_inputs = input_hashes()
        start = time.monotonic_ns()
        values = inputs()
        jdbc = os.pathsep.join(map(str, (driver(), embedded_driver())))
        java = Path(replay.inspect("/usr/libexec/java_home", "-v", "21"))
        with guard.workspace("udak-local-paired-review-") as (work, cleanup):
            result["cleanup"] = cleanup
            classes = replay.compile_replay(work, jdbc, java, CLASS)
            baseline = work / "baseline-review"
            baseline.mkdir()
            observed = work / "observed-review"
            observed.mkdir()
            with (replay.postgres_fixture() if use_postgres else nullcontext()) as fixture:
                result["container_started"] = use_postgres
                result["shared_setup_seconds"] = elapsed(start)

                def execute(mode):
                    target = baseline if mode == "plain" else observed
                    if use_postgres:
                        step = replay.run_jdbc("verify-" + mode, target, classes, jdbc, java,
                                               values, fixture, CLASS, mode)
                    else:
                        step = guard.run_step("verify-" + mode, [str(java / "bin/java"), "-Xmx96m",
                            "-XX:MaxMetaspaceSize=64m", "-XX:ActiveProcessorCount=1",
                            "-cp", f"{classes}{os.pathsep}{jdbc}", f"dev.udak.pilot.{CLASS}", str(target), "h2", mode],
                            target, timeout=15, private_input=("\n".join(values) + "\n").encode())
                    if (not step["child_reaped"] or not step["process_group_quiesced"]
                            or (target / ("verify-" + mode + ".output")).read_bytes() != b"PAIRED_DEVICE_COUNT PASS\n"):
                        raise ValueError("COUNT_CONTRACT")
                    result["steps"].append(step)

                result["baseline"] = baseline_review(baseline, values, execute)
                result["udak"] = observed_review(observed, execute)
            result["container_cleanup"] = "PASS" if use_postgres else "NOT APPLICABLE"
            if not result["baseline"]["value_control_inputs_differ"]:
                raise ValueError("VALUE_CONTROL")
            regression = read(ROOT / "evidence/THINGSBOARD-NEXT-005-MAINTAINER-REVIEW.json")["verification"]["impacted_test_hash"]
            score(result["baseline"], regression)
            score(result["udak"], regression)
    if cleanup["status"] != "PASS" or cleanup["temporary_directory_remaining"]:
        raise ValueError("WORKSPACE_CLEANUP")
    if input_hashes() != expected_inputs:
        raise ValueError("INPUTS_CHANGED")
    result["input_sha256"] = expected_inputs


def main():
    if sys.argv[1:] not in ([], ["--h2"]):
        return 2
    use_postgres = not sys.argv[1:]
    report = POSTGRES_REPORT if use_postgres else REPORT
    result = {"schema_version": 1, "requirement": "T-001-S2", "status": "FAIL", "steps": [],
              "scope": "local scripted proxy on two fixed, pre-disclosed cases",
              "customer_participation": "NOT RUN", "operator": "LOCAL_AGENT_PROXY", "blinded": False,
              "procedure_order": ["GIT_DIFF", "UDAK"], "container_started": False,
              "dbms": "PostgreSQL" if use_postgres else "H2",
              "counts_asserted_per_procedure": 3,
              "fixture": "one isolated PostgreSQL instance" if use_postgres else "fresh in-memory H2 per arm",
              "upstream_git_blob_sha1": {"base": replay.BASE[1], "head": replay.HEAD[1]},
              "upstream_pr": 14858}
    for event in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
        signal.signal(event, guard.interrupted)
    signal.alarm(FIXTURE_LIMIT)
    try:
        compare(result, use_postgres, report)
        result["status"] = "PASS"
        with report.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    except Exception as error:
        code = str(error)
        result.update(status="NOT RUN" if code == "HOST_RESOURCES" else "FAIL",
                      reason=code if re.fullmatch("[A-Z_]+", code) else type(error).__name__)
        if isinstance(error, RuntimeError):
            try:
                step = json.loads(code)
            except ValueError:
                pass
            else:
                if isinstance(step, dict) and "exit_code" in step:
                    result["failed_step"] = {key: step[key] for key in ("name", "exit_code", "diagnostics")
                                             if key in step}
    finally:
        signal.alarm(0)
    print(json.dumps({key: value for key, value in result.items() if key != "input_sha256"}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
