#!/usr/bin/env python3
"""Four dedicated DB equivalence checks; retention changes require explicit opt-in."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
import importlib.util
import re

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


local = module("phase5_local", "tools/run-phase5.py")
runtime = module("phase5_managed", "tools/run-managed-g2.py")
guard = local.guard
runtime.guard = guard
REPORT = ROOT / "evidence/PHASE5-REAL-VALIDATION.json"
PRIVATE = ROOT / ".git/udak-phase5/real"


class CapacityBlocked(RuntimeError):
    pass


def required_capacity(current_count, new_count=4):
    if current_count < 8 or new_count != 4:
        raise ValueError("Resource accounting invalid")
    return current_count + new_count


def baseline_receipts():
    receipts = {}
    for name in local.BASELINES:
        local.p4.approved_paths([name])
        report = json.loads((ROOT / name).read_text())
        if report.get("status") != "PASS" or set(report.get("profiles", {})) != {"POSTGRESQL", "MYSQL", "SQLSERVER", "ORACLE"}:
            raise ValueError("Original evidence incomplete")
        for r in report["profiles"].values():
            identity = r.get("container_id", "")
            run = r.get("execution_run_id", report.get("run_id", ""))
            if not re.fullmatch(r"[a-f0-9]{64}", identity) or not re.fullmatch(r"[a-f0-9]{32}", run) or identity in receipts:
                raise ValueError("Original ownership evidence invalid")
            receipts[identity] = run
    if len(receipts) != 8:
        raise ValueError("Original resource set incomplete")
    return receipts


def extra_receipts(identities):
    found = {}
    if not identities:
        return found
    journals = [p for p in PRIVATE.glob("*.json") if re.fullmatch(r"[a-f0-9]{32}\.json", p.name)]
    if len(journals) > 32:
        raise ValueError("Recovery journal bound exceeded")
    for path in journals:
        if path.is_symlink() or path.stat().st_size > 256000:
            raise ValueError("Recovery journal unsafe")
        saved = json.loads(path.read_text())
        if saved.get("phase") != 5 or saved.get("run_id") != path.stem:
            raise ValueError("Recovery journal identity invalid")
        for r in saved.get("containers", []):
            if r.get("container_id") in identities:
                found[r["container_id"]] = saved["run_id"]
    if set(found) != set(identities):
        raise ValueError("Unknown retained resources; preserve and investigate")
    return found
REAL_MAIN = '''package dev.udak.testkit;
import dev.udak.rewrite.Rewrite;
import dev.udak.rewrite.testkit.RewriteEquivalenceTest;
import java.io.PrintStream;
import java.sql.*;
import java.util.*;
import javax.sql.DataSource;
public final class Phase5DatabaseMain {
 public static void main(String[] args) {
  PrintStream out=RewriteEquivalenceTest.suppressRuntimeOutput();
  String label="UNKNOWN";
  try {
   if(args.length!=3) throw new IllegalArgumentException();
   DatabaseProfile profile=DatabaseProfile.valueOf(args[0]); label=profile.name();
   Class.forName(profile.driverClass());
   List<RealDatabaseProvider> matched=new ArrayList<>();
   for(RealDatabaseProvider p:ServiceLoader.load(RealDatabaseProvider.class)) if(p.profile()==profile) matched.add(p);
   if(matched.size()!=1 || !matched.get(0).dedicatedSchemaApproved()) throw new IllegalStateException();
   DataSource ds=matched.get(0).dataSource();
   String server,driver,serverRelease,driverRelease;
   try(Connection c=ds.getConnection()) {
    DatabaseMetaData m=c.getMetaData();
    if(!profile.matchesProduct(m.getDatabaseProductName()) || !profile.matchesDriver(m.getDriverName())
      || !args[1].equals(profile.numericDriverVersion(m.getDriverVersion()))) throw new IllegalStateException();
    server=m.getDatabaseMajorVersion()+"."+m.getDatabaseMinorVersion();
    driver=m.getDriverMajorVersion()+"."+m.getDriverMinorVersion();
    serverRelease=Rewrite.fingerprint(m.getDatabaseProductVersion());
    driverRelease=Rewrite.fingerprint(m.getDriverVersion());
   }
   String sourceRelease=label.equals("POSTGRESQL")?serverRelease:args[2];
   if(!sourceRelease.matches("[a-f0-9]{64}")) throw new IllegalArgumentException();
   var summary=RewriteEquivalenceTest.run(ds,Rewrite.Dialect.valueOf(label),serverRelease,driverRelease,sourceRelease);
   out.println(label+" PASS");out.println("CHECKS="+summary.checks());out.println("CLEANUP=CONFIRMED");
   for(String name:List.of("BASELINE","PAGING","NULL_MAPPING","BIND_ORDER","LABELS_TYPES","TRANSACTION","DEFAULT_DENY","EVIDENCE")) out.println("SCENARIO="+name+":PASS");
   out.println("ASSERTIONS="+summary.assertions());out.println("EVIDENCE_SHA256="+summary.evidenceDigest());
   out.println("RESULT_SHA256="+summary.resultDigest());out.println("SOURCE_SQL_EXECUTED="+summary.sourceSqlExecuted());
   out.println("SERVER_VERSION="+server);out.println("DRIVER_VERSION="+driver);
   out.println("SERVER_RELEASE_SHA256="+serverRelease);out.println("DRIVER_RELEASE_SHA256="+driverRelease);
  }catch(RewriteEquivalenceTest.Failure failure) {
   out.println(label+" FAIL: "+failure.code());
   for(String diagnostic:failure.diagnostics()) out.println("DIAGNOSTIC="+diagnostic);
   System.exit(1);
  }catch(Throwable failure) {out.println(label+" FAIL: IDENTITY_OR_EXECUTION_ERROR");System.exit(1);}
 }
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--retention-cap", type=int, choices=range(8, 17), default=8)
    args = parser.parse_args()
    if args.retention_cap == 8:
        print(json.dumps({"status": "NOT RUN", "reason": "EXPLICIT_BOUNDED_RETENTION_AUTHORIZATION_REQUIRED"}))
        return 2
    verifier = module("phase5_prerequisite", "tools/verify-phase5.py")
    prerequisite = json.loads(local.REPORT.read_text())
    verifier.verify_local(prerequisite)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    lock = (runtime.PRIVATE / "RUN.lock").open("a")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        print(json.dumps({"status": "NOT RUN", "reason": "MANAGED_RUNTIME_ACTIVE"}))
        return 2
    started = time.monotonic()
    run_id = uuid.uuid4().hex
    state = {"run_id": run_id, "phase": 5, "started_at_utc": datetime.now(timezone.utc).isoformat(), "containers": []}
    journal = PRIVATE / (run_id + ".json")
    runtime.save(journal, state)
    result = {"schema_version": 1, "phase": 5, "status": "FAIL", "run_id": run_id, "started_at_utc": state["started_at_utc"],
              "profiles": {}, "steps": [], "containers_started": 0, "existing_resources_modified": 0,
              "retention_cap": args.retention_cap, "resource_authorization": "explicit --retention-cap " + str(args.retention_cap),
              "limits": {"wall_seconds": 1800, "active_databases": 1, "container_cpus": 2, "container_memory_mib": 4096,
                         "container_pids": 512, "jvm_heap_mib": 256, "jvm_metaspace_mib": 128, "jvm_cpus": 2,
                         "jvm_wall_seconds": 90, "workspace_files": 2000, "workspace_bytes": 134217728},
              "not_run": ["general SQL equivalence", "native SQL Server certification", "graceful shutdown/restart recovery",
                          "Gradle/Boot certification", "performance/load", "production approval issuance"]}
    engine = runtime.docker.Engine()
    active = None
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, runtime.interrupted)
    signal.alarm(1800)
    try:
        for field, names in (("source_sha512", local.source_paths()), ("harness_sha512", local.HARNESS),
                             ("manifest_sha512", local.MANIFESTS), ("configuration_sha512", local.CONFIGURATION),
                             ("preservation_baseline_sha512", local.BASELINES)):
            result[field] = local.hashes(names)
        for key in ("_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS"):
            os.unsetenv(key)
        with guard.workspace("udak-phase5-real-") as (work, cleanup):
            result["cleanup"] = cleanup
            os.putenv("TMPDIR", str(work))
            cp, result["framework_dependencies"], result["parser_dependency"], steps = local.build(work)
            result["steps"].extend(steps)
            drivers, result["driver_dependencies"] = runtime.g2.dependencies(work, json.loads((ROOT / "tools/g2-dependencies.json").read_text()))
            cp += os.pathsep + os.pathsep.join(str(p) for p in drivers)
            health = work / "G2Health.java"; health.write_text(runtime.BOOTSTRAP)
            actual = work / "Phase5DatabaseMain.java"; actual.write_text(REAL_MAIN)
            result["steps"].append(guard.run_step("compile-real-phase5", local.JAVAC + ["-cp", cp, "-d", str(work / "classes"), str(health), str(actual)], work))
            cp += os.pathsep + str(ROOT / "db-testkit/src/main/resources")
            java = local.JAVA + ["-Dudak.g2.dedicatedPipe=true", "-cp", cp]
            images = json.loads((ROOT / "tools/g2-server-images.json").read_text())["images"]
            if [item["profile"] for item in images] != ["POSTGRESQL", "MYSQL", "SQLSERVER", "ORACLE"]:
                raise RuntimeError("SOURCE_FIRST_PROFILE_ORDER_REQUIRED")
            listing = runtime.DOCKER + ["ps", "-a", "--no-trunc", "--filter", "label=dev.udak.g2.managed=true", "--format", "{{.ID}} {{.State}}"]
            initial = subprocess.run(listing, capture_output=True, text=True, timeout=10, check=True).stdout.splitlines()
            existing = {line.split()[0]: line.split()[1] for line in initial}
            originals = baseline_receipts()
            extras = extra_receipts(set(existing) - set(originals))
            if not set(originals).issubset(existing) or any(s != "exited" for s in existing.values()):
                raise RuntimeError("INITIAL_PRESERVED_INSTANCES_UNCONFIRMED")
            for identity, owner_run in (originals | extras).items():
                if engine.state(identity, owner_run)["state"] != "exited":
                    raise RuntimeError("PRESERVED_OWNERSHIP_UNCONFIRMED")
            result["existing_managed_ids"] = sorted(originals)
            result["previous_phase5_retained_ids"] = sorted(extras)
            result["minimum_required_retention_cap"] = required_capacity(len(existing))
            if result["minimum_required_retention_cap"] > args.retention_cap:
                raise CapacityBlocked("NEW_APPROVED_CAPACITY_OR_EQUIVALENT_PROVIDER_REQUIRED")
            for item in images:
                name = item["profile"]
                record = {"status": "FAIL", "cleanup": "UNCONFIRMED", "image": item["image"], "platform": item["platform"]}
                result["profiles"][name] = record
                record["resource_preflight"] = runtime.preflight(work, item["memory_mib"])
                states = subprocess.run(runtime.DOCKER + ["ps", "-a", "--filter", "label=dev.udak.g2.managed=true", "--format", "{{.State}}"], capture_output=True, text=True, timeout=10)
                if states.returncode or len(states.stdout.splitlines()) >= args.retention_cap or any(s in ("running", "paused", "restarting") for s in states.stdout.splitlines()):
                    raise RuntimeError("MANAGED_RETENTION_OR_ACTIVITY_GATE")
                print(json.dumps({"stage": "prepare-database", "profile": name}), flush=True)
                record["pull"] = engine.pull(item["image"], item["platform"], wall_seconds=180)
                image_step = guard.run_step("image-config-" + name, runtime.DOCKER + ["image", "inspect", "--format", "{{.Id}} {{.Os}}/{{.Architecture}}", item["image"]], work, timeout=10)
                image_parts = (work / ("image-config-" + name + ".output")).read_text().split()
                if len(image_parts) != 2 or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_parts[0]) or image_parts[1] != item["platform"]:
                    raise RuntimeError("PINNED_IMAGE_CONFIG_UNCONFIRMED")
                record.update(image_config_id=image_parts[0], image_config_platform=image_parts[1])
                result["steps"].append(image_step)
                record["resource_preflight_before_create"] = runtime.preflight(work, item["memory_mib"])
                latest = subprocess.run(runtime.DOCKER + ["ps", "-a", "--filter", "label=dev.udak.g2.managed=true", "--format", "{{.State}}"], capture_output=True, text=True, timeout=10)
                if latest.returncode or len(latest.stdout.splitlines()) >= args.retention_cap or any(s != "exited" for s in latest.stdout.splitlines()):
                    raise RuntimeError("IMMEDIATE_CREATE_CAPACITY_OR_ACTIVITY_GATE")
                username, password, database, env = runtime.connection_config(name)
                intent = {"profile": name, "fixture": "udak_p5_entry", "state": "CREATE_INTENT", "fixture_cleanup": "UNCONFIRMED"}
                state["containers"].append(intent); runtime.save(journal, state)
                active = engine.create(item["image"], item["platform"], env, item["internal_port"], item["memory_mib"] * 1024**2, item["cpus"] * 10**9, run_id, name)
                record["container_id"] = active
                intent.update(container_id=active, state="CREATED"); runtime.save(journal, state)
                engine.start(active); result["containers_started"] += 1
                deadline = time.monotonic() + item["startup_seconds"]
                ready = False
                while time.monotonic() < deadline:
                    state_now = engine.state(active, run_id)
                    if state_now["state"] != "running" or state_now["status"] == "unhealthy":
                        raise RuntimeError("DATABASE_STARTUP_FAILED")
                    port = engine.endpoint(active, run_id)
                    if port is not None:
                        frame = runtime.private_frame(name, port, database, username, password, run_id)
                        health_step = runtime.checked_step("health-" + name, java + ["G2Health", name], work, timeout=15, private_input=frame)
                        if health_step["exit_code"] == 0 and (work / ("health-" + name + ".output")).read_text().strip() == "HEALTH=PASS":
                            ready = True
                            break
                        if health_step["exit_code"] != 3:
                            raise RuntimeError("DATABASE_HEALTH_UNCONFIRMED")
                    time.sleep(3)
                if not ready:
                    raise RuntimeError("DATABASE_READINESS_TIMEOUT")
                record["health"] = health_step
                if name == "SQLSERVER":
                    bootstrap = runtime.checked_step("bootstrap-" + name, java + ["G2Health", name, "create-database"], work, timeout=15, private_input=frame)
                    if bootstrap["exit_code"] != 0:
                        raise RuntimeError("DATABASE_BOOTSTRAP_FAILED")
                    record["bootstrap"] = bootstrap
                    database = "udak_g2"
                frame = runtime.private_frame(name, port, database, username, password, run_id)
                username = password = env = None
                version = json.loads((ROOT / "tools/g2-dependencies.json").read_text())["metadata_versions"][name]
                source_release = "SOURCE" if name == "POSTGRESQL" else result["profiles"]["POSTGRESQL"]["server_release_hash"]
                record["source_release_hash"] = source_release
                step = runtime.checked_step("equivalence-" + name, java + ["dev.udak.testkit.Phase5DatabaseMain", name, version, source_release], work, timeout=90, private_input=frame)
                frame = None
                result["steps"].append(step)
                output = (work / ("equivalence-" + name + ".output")).read_text().splitlines()
                if len(output) != 19:
                    raise RuntimeError("REAL_EQUIVALENCE_PROTOCOL_FAILED")
                record.update(local.protocol(name, "\n".join(output[:15]), step["exit_code"]))
                for field, line, prefix in (("server_version", output[15], "SERVER_VERSION="), ("driver_version", output[16], "DRIVER_VERSION=")):
                    match = re.fullmatch(re.escape(prefix) + r"([0-9]+\.[0-9]+)", line)
                    if not match:
                        raise RuntimeError("REAL_IDENTITY_PROTOCOL_FAILED")
                    record[field] = match[1]
                for field, line, prefix in (("server_release_hash", output[17], "SERVER_RELEASE_SHA256="), ("driver_release_hash", output[18], "DRIVER_RELEASE_SHA256=")):
                    match = re.fullmatch(re.escape(prefix) + r"([a-f0-9]{64})", line)
                    if not match:
                        raise RuntimeError("REAL_RELEASE_IDENTITY_FAILED")
                    record[field] = match[1]
                if name == "POSTGRESQL":
                    record["source_release_hash"] = record["server_release_hash"]
                intent["fixture_cleanup"] = record["cleanup"]
                record["stop"] = engine.stop(active, run_id, timeout=30)
                record.update(container_stopped=True, data_preserved=True)
                intent.update(state="STOPPED_DATA_PRESERVED");runtime.save(journal, state)
                active = None
                print(json.dumps({"stage": "database-finished", "profile": name, "status": record["status"], "checks": record["checks"]}), flush=True)
            final = subprocess.run(listing, capture_output=True, text=True, timeout=10, check=True).stdout.splitlines()
            retained = {line.split()[0]: line.split()[1] for line in final}
            if set(retained) != set(existing) | {r["container_id"] for r in result["profiles"].values()} or any(s != "exited" for s in retained.values()):
                raise RuntimeError("FINAL_PRESERVATION_UNCONFIRMED")
            result["preserved_managed_instances"] = len(retained)
            for name, record in result["profiles"].items():
                step = guard.run_step("retention-" + name, runtime.DOCKER + ["inspect", "--format", "{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}} {{.Image}} {{len .Mounts}}", record["container_id"]], work, timeout=10)
                parts = (work / ("retention-" + name + ".output")).read_text().split()
                if len(parts) != 5 or parts[0] != "exited" or parts[2] != "false":
                    raise RuntimeError("DATABASE_STOP_STATE_UNCONFIRMED")
                record["retention"] = {"state": parts[0], "exit_code": int(parts[1]), "oom_killed": False, "image_id": parts[3], "mount_count": int(parts[4])}
                result["steps"].append(step)
            for field, names in (("source_sha512", local.source_paths()), ("harness_sha512", local.HARNESS),
                                 ("manifest_sha512", local.MANIFESTS), ("configuration_sha512", local.CONFIGURATION),
                                 ("preservation_baseline_sha512", local.BASELINES)):
                if result[field] != local.hashes(names):
                    raise RuntimeError("EXECUTION_INPUTS_CHANGED")
            if len({v["result_digest"] for v in result["profiles"].values()}) != 1 or not result["profiles"]["POSTGRESQL"]["source_sql_executed"]:
                raise RuntimeError("SOURCE_TARGET_RESULT_MISMATCH")
            result.update(status="PASS", checks=32)
    except CapacityBlocked:
        result.update(status="NOT RUN", reason="NEW_APPROVED_CAPACITY_OR_EQUIVALENT_PROVIDER_REQUIRED")
    except BaseException as error:
        result["failure_type"] = type(error).__name__
    finally:
        signal.alarm(0)
        try:
            guard.stop_child()
        except Exception:
            result.update(status="FAIL", process_cleanup="UNCONFIRMED")
        if active is not None:
            try:
                result["emergency_stop"] = engine.stop(active, run_id, timeout=30)
                for record in result["profiles"].values():
                    if record.get("container_id") == active:
                        record.update(container_stopped=True, data_preserved=True)
                state["containers"][-1]["state"] = "STOPPED_DATA_PRESERVED_AFTER_FAILURE"
            except Exception:
                result["stop_status"] = "UNCONFIRMED"
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["remaining_profiles"] = 4 - sum(r.get("status") == "PASS" for r in result["profiles"].values())
        username = password = env = frame = None
        state["status"] = result["status"];runtime.save(journal, state)
        local.archive_save(REPORT, result)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN);lock.close()
    print(json.dumps({k: result[k] for k in ("status", "checks", "cleanup", "failure_type", "stop_status") if k in result}), flush=True)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
