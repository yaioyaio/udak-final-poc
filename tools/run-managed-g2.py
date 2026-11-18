#!/usr/bin/env python3
"""Prepare owned bounded databases and execute the minimal real G2 contracts."""
import argparse
import fcntl
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
import traceback
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "evidence/G2-MANAGED-VALIDATION.json"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


g2 = module("g2_harness", "tools/run-g2.py")
guard = g2.guard
docker = module("g2_docker", "tools/g2-docker.py")
PRIVATE = ROOT / ".git/udak-g2-managed"
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]


class ManagedInterrupted(BaseException):
    pass


def interrupted(_signum, _frame):
    guard.stop_child()
    raise ManagedInterrupted()
BOOTSTRAP = '''import dev.udak.testkit.*;
import java.io.*;
import java.sql.*;
import java.util.logging.*;
public final class G2Health {
 public static void main(String[] args) {
  PrintStream approved = System.out;
  System.setOut(new PrintStream(OutputStream.nullOutputStream()));
  System.setErr(new PrintStream(OutputStream.nullOutputStream()));
  LogManager.getLogManager().reset();
  Logger.getLogger("").setLevel(Level.OFF);
  try {
   RealDatabaseProvider p = switch(args[0]) {
    case "POSTGRESQL" -> new DedicatedRuntimeProvider.Postgresql();
    case "MYSQL" -> new DedicatedRuntimeProvider.MySql();
    case "SQLSERVER" -> new DedicatedRuntimeProvider.SqlServer();
    case "ORACLE" -> new DedicatedRuntimeProvider.Oracle();
    default -> throw new IllegalArgumentException();
   };
   if (!p.dedicatedSchemaApproved()) throw new IllegalArgumentException();
   try(Connection c=p.dataSource().getConnection(); Statement s=c.createStatement()) {
    s.setQueryTimeout(5);
    try(ResultSet r=s.executeQuery(args[0].equals("ORACLE")?"SELECT 1 FROM DUAL":"SELECT 1")) {
     if(!r.next() || r.getInt(1)!=1) throw new IllegalStateException();
    }
    if(args.length==2 && args[1].equals("create-database")) s.executeUpdate("CREATE DATABASE udak_g2");
   }
   approved.println("HEALTH=PASS");
  } catch(Throwable e) { approved.println("HEALTH=WAIT"); System.exit(3); }
 }
}
'''


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("x") as stream:
        stream.write(json.dumps(value, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def private_frame(profile, port, database, username, password, run_id):
    result = bytearray(struct.pack(">iii", 0x5544414B, 1, 1))
    def field(value):
        data = value.encode("ascii")
        if len(data) > 256:
            raise ValueError("Private input bounds exceeded")
        result.extend(struct.pack(">H", len(data)))
        result.extend(data)
    field(profile)
    result.extend(struct.pack(">i", port))
    for value in (database, username, password, run_id):
        field(value)
    return bytes(result)


def preflight(work, memory_mib):
    if shutil.disk_usage(ROOT).free < 40 * 1024**3:
        raise RuntimeError("DISK_PREFLIGHT_FAILED")
    step = guard.run_step("docker-capacity", DOCKER + ["info", "--format", "{{.MemTotal}} {{.NCPU}}"], work, timeout=10)
    total, cpus = map(int, (work / "docker-capacity.output").read_text().split())
    # Statistics contain only resource quantities; no names, addresses or environment values.
    guard.run_step("docker-usage", DOCKER + ["stats", "--no-stream", "--format", "{{.MemUsage}}"], work, timeout=15)
    factors = {"B": 1, "kB": 1000, "KiB": 1024, "MB": 1000**2, "MiB": 1024**2,
               "GB": 1000**3, "GiB": 1024**3}
    import re
    usage = 0
    for line in (work / "docker-usage.output").read_text().splitlines():
        match = re.match(r"([0-9.]+)([A-Za-z]+) /", line)
        if not match or match[2] not in factors:
            raise RuntimeError("RESOURCE_STATISTICS_UNRECOGNIZED")
        usage += float(match[1]) * factors[match[2]]
    if cpus < 2 or total - usage < (memory_mib + 1024) * 1024**2:
        raise RuntimeError("MEMORY_PREFLIGHT_FAILED")
    return {"status": "PASS", "docker_memory_mib": total // 1024**2, "docker_cpus": cpus,
            "observed_used_mib": round(usage / 1024**2), "new_container_mib": memory_mib}


def checked_step(name, command, work, timeout=30, private_input=None):
    try:
        return guard.run_step(name, command, work, timeout=timeout, private_input=private_input)
    except RuntimeError as error:
        try:
            value = json.loads(str(error))
        except (ValueError, TypeError):
            raise RuntimeError("GUARDED_STEP_UNCONFIRMED") from None
        if not isinstance(value, dict) or "exit_code" not in value:
            raise RuntimeError("GUARDED_STEP_UNCONFIRMED") from None
        return value


def connection_config(profile):
    # Newly generated task-only values never enter files, argv, environment of the client, or reports.
    password = "Aa1_" + secrets.token_urlsafe(24)
    username = "udak_" + secrets.token_hex(5)
    database = "udak_g2"
    if profile == "POSTGRESQL":
        env = {"POSTGRES_USER": username, "POSTGRES_PASSWORD": password, "POSTGRES_DB": database}
    elif profile == "MYSQL":
        env = {"MYSQL_USER": username, "MYSQL_PASSWORD": password, "MYSQL_DATABASE": database,
               "MYSQL_ROOT_PASSWORD": "Aa1_" + secrets.token_urlsafe(24)}
    elif profile == "SQLSERVER":
        username = "sa"
        database = "master"
        env = {"ACCEPT_EULA": "Y", "MSSQL_PID": "Developer", "MSSQL_SA_PASSWORD": password,
               "MSSQL_MEMORY_LIMIT_MB": "3072"}
    else:
        username = "system"
        database = "FREEPDB1"
        env = {"ORACLE_PWD": password}
    return username, password, database, env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", nargs="+", choices=g2.PROFILES, default=list(g2.PROFILES))
    args = parser.parse_args()
    if len(set(args.profiles)) != len(args.profiles):
        parser.error("Duplicate profiles")
    started = time.monotonic()
    PRIVATE.mkdir(exist_ok=True)
    lock = (PRIVATE / "RUN.lock").open("a")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        print(json.dumps({"status": "BLOCKED", "reason": "MANAGED_RUN_ALREADY_ACTIVE"}))
        return 2
    run_id = uuid.uuid4().hex
    state = {"run_id": run_id, "started_at_utc": datetime.now(timezone.utc).isoformat(), "containers": []}
    journal = PRIVATE / "runs" / (run_id + ".json")
    save(journal, state)
    result = {"schema_version": 1, "gate": "G2", "scope": "minimal functional CRUD/Query/Spring JDBC transaction validation",
              "status": "INCOMPLETE", "run_id": run_id, "steps": [], "containers_started": 0,
              "existing_containers_modified": 0, "worktrees_created": 0, "worktrees_removed": 0,
              "server_vendor_platform_certification": "NOT RUN; SQL Server is emulated on ARM64",
              "product_distribution_approval": "NOT GRANTED", "gradle_boot_orm_performance": "NOT RUN",
              "limits": {"wall_seconds": 1800, "active_db_containers": 1, "child_cpu_seconds": 30,
                         "jvm_heap_mib": 256, "jvm_metaspace_mib": 128, "jvm_active_cpus": 2,
                         "workspace_files": 2000, "workspace_bytes": 134217728, "retained_managed_container_limit": 8},
              "profiles": {name: {"status": "NOT RUN", "reason": "NOT_SELECTED_OR_NOT_REACHED"} for name in g2.PROFILES}}
    engine = docker.Engine()
    active = None
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, interrupted)
    signal.alarm(1800)
    try:
        for key in ("_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS"):
            os.unsetenv(key)
        with guard.workspace("udak-managed-g2-") as (work, cleanup):
            result["cleanup"] = cleanup
            os.putenv("TMPDIR", str(work))
            server_manifest = json.loads((ROOT / "tools/g2-server-images.json").read_text())
            images = {v["profile"]: v for v in server_manifest["images"]}
            manifest = json.loads((ROOT / "tools/g2-dependencies.json").read_text())
            jars, result["driver_dependencies"] = g2.dependencies(work, manifest)
            spring, result["spring_dependencies"] = g2.phase2.dependencies(work, json.loads((ROOT / "tools/phase2-dependencies.json").read_text()))
            jars += [p for p in spring if p.name != "h2.jar"]
            classes = work / "classes"
            classes.mkdir()
            bootstrap = work / "G2Health.java"
            bootstrap.write_text(BOOTSTRAP)
            sources = [p for name in ("core", "udak-api", "jdbc-spring", "db-testkit")
                       for p in sorted((ROOT / name / "src/main/java").rglob("*.java"))]
            dependencies = os.pathsep.join(str(p) for p in jars)
            result["steps"].append(guard.run_step("compile-managed", ["javac", "-J-Xmx256m", "--release", "17", "-cp", dependencies,
                                         "-d", str(classes)] + [str(p) for p in sources] + [str(bootstrap)], work))
            classpath = os.pathsep.join([str(classes), str(ROOT / "db-testkit/src/main/resources"), dependencies])
            java = ["java", "-Xmx256m", "-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2",
                    "-Dudak.g2.dedicatedPipe=true", "-cp", classpath]
            for profile in args.profiles:
                item = images[profile]
                record = {"profile": profile, "status": "FAIL", "reason": "START_OR_EXECUTION_UNCONFIRMED",
                          "image": item["image"], "platform": item["platform"], "cleanup": "UNCONFIRMED"}
                result["profiles"][profile] = record
                result["resource_preflight"] = preflight(work, item["memory_mib"])
                owned = subprocess.run(DOCKER + ["ps", "-a", "--filter", "label=dev.udak.g2.managed=true", "--format", "{{.State}}"],
                                       capture_output=True, text=True, timeout=10)
                if owned.returncode or len(owned.stdout.splitlines()) >= 8:
                    raise RuntimeError("MANAGED_CONTAINER_LIMIT")
                if any(state in ("running", "paused", "restarting") for state in owned.stdout.splitlines()):
                    raise RuntimeError("PREVIOUS_MANAGED_RUNTIME_ACTIVE")
                print(json.dumps({"stage": "image-pull", "profile": profile}), flush=True)
                record["pull"] = engine.pull(item["image"], item["platform"], wall_seconds=180)
                username, password, database, env = connection_config(profile)
                fixture = "udak_p2_" + uuid.uuid4().hex[:12]
                intent = {"profile": profile, "fixture": fixture, "state": "CREATE_INTENT", "cleanup": "UNCONFIRMED"}
                state["containers"].append(intent)
                save(journal, state)
                container = engine.create(item["image"], item["platform"], env, item["internal_port"],
                                          item["memory_mib"] * 1024**2, item["cpus"] * 10**9, run_id, profile)
                active = container
                intent.update(container_id=container, state="CREATED")
                save(journal, state)
                try:
                    engine.start(container)
                    result["containers_started"] += 1
                    print(json.dumps({"stage": "database-started", "profile": profile}), flush=True)
                    intent["state"] = "STARTED"
                    record.update(container_id=container, fixture=fixture, execution_started=True)
                    save(journal, state)
                    deadline = time.monotonic() + item["startup_seconds"]
                    attempts = 0
                    ready = False
                    while time.monotonic() < deadline:
                        status = engine.state(container, run_id)
                        if status["state"] != "running" or status["status"] == "unhealthy":
                            raise RuntimeError("DATABASE_STARTUP_FAILED")
                        port = engine.endpoint(container, run_id)
                        if port is not None:
                            try:
                                with socket.create_connection(("127.0.0.1", port), timeout=1):
                                    pass
                            except OSError:
                                time.sleep(2)
                                continue
                            packet = private_frame(profile, port, database, username, password, run_id)
                            attempts += 1
                            step = checked_step("health-" + profile, java + ["G2Health", profile], work, timeout=15, private_input=packet)
                            if step["exit_code"] == 0 and (work / ("health-" + profile + ".output")).read_text().strip() == "HEALTH=PASS":
                                ready = True
                                break
                            if step["exit_code"] != 3:
                                raise RuntimeError("DATABASE_HEALTH_UNCONFIRMED")
                        time.sleep(3)
                    record["health_attempts"] = attempts
                    if not ready:
                        raise RuntimeError("DATABASE_READINESS_TIMEOUT")
                    if profile == "SQLSERVER":
                        step = checked_step("bootstrap-" + profile, java + ["G2Health", profile, "create-database"],
                                            work, timeout=15, private_input=packet)
                        if step["exit_code"] != 0 or (work / ("bootstrap-" + profile + ".output")).read_text().strip() != "HEALTH=PASS":
                            raise RuntimeError("DATABASE_BOOTSTRAP_UNCONFIRMED")
                        database = "udak_g2"
                    packet = private_frame(profile, port, database, username, password, run_id)
                    step = checked_step("live-" + profile, java + ["dev.udak.testkit.RealDatabaseContractRunner", "--run", profile,
                                        "--driver-version", manifest["metadata_versions"][profile], "--fixture", fixture],
                                        work, timeout=45, private_input=packet)
                    result["steps"].append(step)
                    parsed = g2.parse_profile(profile, (work / ("live-" + profile + ".output")).read_text(), step["exit_code"])
                    record.update(parsed)
                    print(json.dumps({"stage": "contract-result", "profile": profile, "status": parsed["status"]}), flush=True)
                    intent["fixture_cleanup"] = parsed.get("cleanup", "UNCONFIRMED")
                    intent["test_status"] = parsed["status"]
                except Exception as error:
                    record.update(status="FAIL", reason=type(error).__name__)
                    record["failure_locations"] = [{"file": Path(f.filename).name, "line": f.lineno} for f in traceback.extract_tb(error.__traceback__)]
                finally:
                    intent["stop"] = engine.stop(container, run_id, timeout=30)
                    intent.update(state="STOPPED_PRESERVED", data_preserved=True)
                    record.update(container_stopped=True, container_and_data_preserved=True)
                    save(journal, state)
                    active = None
                # Independent owned instances can proceed after a stopped failed profile.
                save(journal, state)
            result["source_sha512"] = {str(p.relative_to(ROOT)): guard.digest(p.read_bytes()) for p in sources}
            statuses = [v["status"] for v in result["profiles"].values()]
            result["status"] = "PASS" if statuses == ["PASS"] * 4 else ("FAIL" if "FAIL" in statuses else "INCOMPLETE")
    except ManagedInterrupted:
        result.update(status="FAIL", failure_type="INTERRUPTED")
    except Exception as error:
        result.update(status="FAIL", failure_type=type(error).__name__,
                      failure_locations=[{"file": Path(f.filename).name, "line": f.lineno} for f in traceback.extract_tb(error.__traceback__)])
    finally:
        signal.alarm(0)
        if active is not None:
            try:
                result["emergency_stop"] = engine.stop(active, run_id, timeout=30)
            except Exception:
                result["emergency_stop"] = "UNCONFIRMED; preserve and investigate before further runtime"
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["harness_sha512"] = {name: guard.digest((ROOT / name).read_bytes()) for name in
                                    ("tools/run-managed-g2.py", "tools/g2-docker.py", "tools/run-g2.py", "tools/run-phase1.py")}
        result["manifest_sha512"] = {name: guard.digest((ROOT / name).read_bytes()) for name in
                                    ("tools/g2-server-images.json", "tools/g2-dependencies.json")}
        if REPORT.exists():
            old = REPORT.read_bytes()
            archive = PRIVATE / "previous-reports" / (hashlib.sha256(old).hexdigest() + ".json")
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(old)
        save(REPORT, result)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
    print(json.dumps({"status": result["status"], "containers_started": result["containers_started"],
                      "profiles": {k: {n: v[n] for n in ("status", "reason", "checks") if n in v} for k, v in result["profiles"].items()},
                      "cleanup": result.get("cleanup"), "failure_type": result.get("failure_type")}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
