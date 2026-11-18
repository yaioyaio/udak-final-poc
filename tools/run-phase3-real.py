#!/usr/bin/env python3
"""Run the same Observe compatibility suite on four owned real databases."""
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


phase3 = module("phase3", "tools/run-phase3.py")
runtime = module("managed_runtime", "tools/run-managed-g2.py")
guard = phase3.guard
runtime.guard = guard
REPORT = ROOT / "evidence/PHASE3-REAL-VALIDATION.json"
PRIVATE = ROOT / ".git/udak-phase3/real"
REAL_MAIN = '''package dev.udak.testkit;
import dev.udak.compat.LegacyCompatibilityTest;
import java.io.PrintStream;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.util.*;
import javax.sql.DataSource;
public final class Phase3DatabaseMain {
 public static void main(String[] args) {
  PrintStream out=LegacyCompatibilityTest.suppressRuntimeOutput();
  String label="UNKNOWN";
  try {
   if(args.length!=2) throw new IllegalArgumentException();
   DatabaseProfile profile=DatabaseProfile.valueOf(args[0]);label=profile.name();
   Class.forName(profile.driverClass());
   List<RealDatabaseProvider> matched=new ArrayList<>();
   for(RealDatabaseProvider p:ServiceLoader.load(RealDatabaseProvider.class)) if(p.profile()==profile) matched.add(p);
   if(matched.size()!=1 || !matched.get(0).dedicatedSchemaApproved()) throw new IllegalStateException();
   DataSource ds=matched.get(0).dataSource();
   int major,minor,driverMajor,driverMinor;
   try(Connection c=ds.getConnection()) {
    DatabaseMetaData m=c.getMetaData();
    if(!profile.matchesProduct(m.getDatabaseProductName()) || !profile.matchesDriver(m.getDriverName())
      || !args[1].equals(profile.numericDriverVersion(m.getDriverVersion()))) throw new IllegalStateException();
    major=m.getDatabaseMajorVersion();minor=m.getDatabaseMinorVersion();
    driverMajor=m.getDriverMajorVersion();driverMinor=m.getDriverMinorVersion();
    if(major<0 || minor<0 || driverMajor<0 || driverMinor<0) throw new IllegalStateException();
   }
   int checks=LegacyCompatibilityTest.run(ds,label);
   out.println(label+" PASS");out.println("CHECKS="+checks);out.println("CLEANUP=CONFIRMED");
   for(String name:LegacyCompatibilityTest.CHECKS) out.println("SCENARIO="+name+":PASS");
   out.println("SERVER_VERSION="+major+"."+minor);out.println("DRIVER_VERSION="+driverMajor+"."+driverMinor);
  }catch(LegacyCompatibilityTest.Failure failure) {
   out.println(label+" FAIL: "+failure.code());
   for(String diagnostic:failure.diagnostics()) out.println("DIAGNOSTIC="+diagnostic);
   System.exit(1);
  }catch(Throwable failure) { out.println(label+" FAIL: IDENTITY_OR_EXECUTION_ERROR"); System.exit(1); }
 }
}
'''


def main():
    started = time.monotonic()
    prerequisite = json.loads((ROOT / "evidence/PHASE3-VALIDATION.json").read_text())
    if prerequisite.get("status") != "PASS" or any(guard.digest((ROOT / path).read_bytes()) != digest
                                                     for path, digest in prerequisite.get("source_sha512", {}).items()):
        print(json.dumps({"status": "FAIL", "reason": "H2_CONTRACT_PREREQUISITE"}))
        return 1
    PRIVATE.mkdir(parents=True, exist_ok=True)
    lock = (runtime.PRIVATE / "RUN.lock").open("a")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        print(json.dumps({"status": "BLOCKED", "reason": "MANAGED_RUNTIME_ACTIVE"}))
        return 2
    run_id = uuid.uuid4().hex
    state = {"run_id": run_id, "phase": 3, "started_at_utc": datetime.now(timezone.utc).isoformat(), "containers": []}
    journal = PRIVATE / (run_id + ".json")
    runtime.save(journal, state)
    result = {"schema_version": 1, "phase": 3, "gate": "G3", "status": "FAIL", "run_id": run_id,
              "started_at_utc": state["started_at_utc"], "scope": "actual Hibernate/MyBatis/JdbcTemplate same-DataSource Observe compatibility",
              "profiles": {}, "containers_started": 0, "existing_resources_modified": 0, "steps": [],
              "limits": {"wall_seconds": 1800, "active_databases": 1, "max_container_memory_mib": 4096,
                         "max_container_cpus": 2, "max_container_pids": 512, "jvm_heap_mib": 256,
                         "jvm_metaspace_mib": 128, "jvm_cpus": 2, "jvm_wall_seconds": 90,
                         "workspace_entries": 2000, "workspace_bytes": 134217728, "managed_container_retention_cap": 8},
              "not_run": ["native SQL Server platform certification", "Spring Boot autoconfiguration", "Gradle tasks",
                          "performance/load testing", "product redistribution approval", "graceful shutdown/restart recovery"]}
    engine = runtime.docker.Engine()
    active = None
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, runtime.interrupted)
    signal.alarm(1800)
    try:
        for key in ("_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS"):
            os.unsetenv(key)
        with guard.workspace("udak-phase3-real-") as (work, cleanup):
            result["cleanup"] = cleanup
            os.putenv("TMPDIR", str(work))
            classpath, sources, result["framework_dependencies"], step = phase3.build(work)
            result["steps"].append(step)
            manifest = json.loads((ROOT / "tools/g2-dependencies.json").read_text())
            drivers, result["driver_dependencies"] = runtime.g2.dependencies(work, manifest)
            classpath += os.pathsep + os.pathsep.join(str(p) for p in drivers)
            health = work / "G2Health.java"
            health.write_text(runtime.BOOTSTRAP)
            actual = work / "Phase3DatabaseMain.java"
            actual.write_text(REAL_MAIN)
            extra = [p for name in ("udak-api", "jdbc-spring", "db-testkit") for p in sorted((ROOT / name / "src/main/java").rglob("*.java"))]
            result["steps"].append(guard.run_step("compile-real-phase3", ["javac", "-J-Xmx256m", "-J-XX:MaxMetaspaceSize=128m", "-J-XX:ActiveProcessorCount=2",
                                   "--release", "17", "-cp", classpath, "-d", str(work / "classes")] + [str(p) for p in extra + [health, actual]], work))
            classpath += os.pathsep + str(ROOT / "db-testkit/src/main/resources")
            java = ["java", "-Xmx256m", "-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2", "-Dudak.g2.dedicatedPipe=true", "-cp", classpath]
            images = json.loads((ROOT / "tools/g2-server-images.json").read_text())["images"]
            for item in images:
                name = item["profile"]
                record = {"status": "FAIL", "cleanup": "UNCONFIRMED", "image": item["image"], "platform": item["platform"]}
                result["profiles"][name] = record
                record["resource_preflight"] = runtime.preflight(work, item["memory_mib"])
                states = subprocess.run(runtime.DOCKER + ["ps", "-a", "--filter", "label=dev.udak.g2.managed=true", "--format", "{{.State}}"], capture_output=True, text=True, timeout=10)
                if states.returncode or len(states.stdout.splitlines()) >= 8 or any(v in ("running", "paused", "restarting") for v in states.stdout.splitlines()):
                    raise RuntimeError("MANAGED_RETENTION_OR_OWNERSHIP_GATE")
                print(json.dumps({"stage": "prepare-database", "profile": name}), flush=True)
                record["pull"] = engine.pull(item["image"], item["platform"], wall_seconds=180)
                username, password, database, env = runtime.connection_config(name)
                intent = {"profile": name, "fixture": "app_user", "state": "CREATE_INTENT", "fixture_cleanup": "UNCONFIRMED"}
                state["containers"].append(intent)
                runtime.save(journal, state)
                container = engine.create(item["image"], item["platform"], env, item["internal_port"], item["memory_mib"] * 1024**2,
                                          item["cpus"] * 10**9, run_id, name)
                active = container
                record.update(container_id=container, fixture="app_user")
                intent.update(container_id=container, state="CREATED")
                runtime.save(journal, state)
                try:
                    engine.start(container)
                    result["containers_started"] += 1
                    record["execution_started"] = True
                    intent["state"] = "STARTED"
                    runtime.save(journal, state)
                    print(json.dumps({"stage": "database-started", "profile": name}), flush=True)
                    deadline = time.monotonic() + item["startup_seconds"]
                    ready = False
                    while time.monotonic() < deadline:
                        state_now = engine.state(container, run_id)
                        if state_now["state"] != "running" or state_now["status"] == "unhealthy":
                            raise RuntimeError("DATABASE_STARTUP_FAILED")
                        port = engine.endpoint(container, run_id)
                        if port is not None:
                            packet = runtime.private_frame(name, port, database, username, password, run_id)
                            health_step = runtime.checked_step("health-" + name, java + ["G2Health", name], work, timeout=15, private_input=packet)
                            if health_step["exit_code"] == 0 and (work / ("health-" + name + ".output")).read_text().strip() == "HEALTH=PASS":
                                ready = True
                                break
                            if health_step["exit_code"] != 3:
                                raise RuntimeError("DATABASE_HEALTH_UNCONFIRMED")
                        time.sleep(3)
                    if not ready:
                        raise RuntimeError("DATABASE_READINESS_TIMEOUT")
                    if name == "SQLSERVER":
                        bootstrap = runtime.checked_step("bootstrap-" + name, java + ["G2Health", name, "create-database"], work, timeout=15, private_input=packet)
                        if bootstrap["exit_code"] != 0:
                            raise RuntimeError("DATABASE_BOOTSTRAP_FAILED")
                        database = "udak_g2"
                    packet = runtime.private_frame(name, port, database, username, password, run_id)
                    tested = runtime.checked_step("compatibility-" + name, java + ["dev.udak.testkit.Phase3DatabaseMain", name, manifest["metadata_versions"][name]],
                                                   work, timeout=90, private_input=packet)
                    result["steps"].append(tested)
                    lines = (work / ("compatibility-" + name + ".output")).read_text().splitlines()
                    parsed = phase3.protocol(name, "\n".join(lines[:13]), tested["exit_code"])
                    if parsed["status"] == "PASS" and len(lines) == 15:
                        import re
                        server = re.fullmatch(r"SERVER_VERSION=([0-9]+\.[0-9]+)", lines[13])
                        driver = re.fullmatch(r"DRIVER_VERSION=([0-9]+\.[0-9]+)", lines[14])
                        if not server or not driver:
                            raise RuntimeError("VERSION_EVIDENCE_INVALID")
                        record.update(parsed, server_version=server[1], driver_version=driver[1])
                    else:
                        record.update(parsed)
                        record["diagnostics"] = [line for line in lines if line.startswith("DIAGNOSTIC=")][:5]
                    intent["fixture_cleanup"] = record["cleanup"]
                    print(json.dumps({"stage": "compatibility-result", "profile": name, "status": record["status"]}), flush=True)
                except Exception as failure:
                    record.update(status="FAIL", failure_type=type(failure).__name__, locations=[{"file": Path(f.filename).name, "line": f.lineno} for f in traceback.extract_tb(failure.__traceback__)])
                finally:
                    record["stop"] = engine.stop(container, run_id, timeout=30)
                    record.update(container_stopped=True, data_preserved=True)
                    intent["state"] = "STOPPED_PRESERVED"
                    runtime.save(journal, state)
                    active = None
                if record["status"] != "PASS" or record["cleanup"] != "CONFIRMED":
                    break
            result["source_sha512"] = {str(p.relative_to(ROOT)): guard.digest(p.read_bytes()) for p in sources + extra}
            result["status"] = "PASS" if len(result["profiles"]) == 4 and all(p["status"] == "PASS" for p in result["profiles"].values()) else "FAIL"
            result["checks"] = sum(p.get("checks", 0) for p in result["profiles"].values())
    except runtime.ManagedInterrupted:
        result.update(failure_type="INTERRUPTED")
    except Exception as failure:
        result.update(failure_type=type(failure).__name__, locations=[{"file": Path(f.filename).name, "line": f.lineno} for f in traceback.extract_tb(failure.__traceback__)])
    finally:
        signal.alarm(0)
        if active is not None:
            try:
                result["emergency_stop"] = engine.stop(active, run_id, timeout=30)
            except Exception:
                result["emergency_stop"] = "UNCONFIRMED; preserve and investigate"
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["harness_sha512"] = {name: guard.digest((ROOT / name).read_bytes()) for name in
                                    ("tools/run-phase3-real.py", "tools/run-phase3.py", "tools/run-managed-g2.py", "tools/g2-docker.py", "tools/run-phase1.py")}
        result["manifest_sha512"] = {name: guard.digest((ROOT / name).read_bytes()) for name in
                                     ("tools/phase3-dependencies.json", "tools/g2-dependencies.json", "tools/g2-server-images.json")}
        if REPORT.exists():
            old = REPORT.read_bytes()
            archive = PRIVATE / "previous-reports" / (hashlib.sha256(old).hexdigest() + ".json")
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(old)
        runtime.save(REPORT, result)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
    print(json.dumps({"status": result["status"], "profiles": {k: {n: v[n] for n in ("status", "reason", "checks", "failure_type", "diagnostics", "locations") if n in v} for k, v in result["profiles"].items()},
                      "cleanup": result.get("cleanup"), "failure_type": result.get("failure_type")}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
