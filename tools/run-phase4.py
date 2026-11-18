#!/usr/bin/env python3
"""Bounded explicit transaction diagnostics and actual Spring/H2 contracts."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "evidence/PHASE4-VALIDATION.json"
CHECKS = ("CONFIGURATION", "REQUIRED_ROLLBACK_ONLY", "REQUIRES_NEW_BOUNDARY", "NESTED_SAVEPOINT",
          "JPA_NESTED_GUARD", "READ_ONLY_WRITE", "ISOLATION_PARTICIPATION", "TIMEOUT_BOUNDARY",
          "MISSING_AND_FOREIGN_TRANSACTION", "UNKNOWN_OUTCOME_NO_RETRY")
MODULES = ("consistency-core", "consistency-spring", "consistency-testkit")
HARNESS = ("tools/run-phase4.py", "tools/verify-phase4.py", "tools/test-phase4-verifier.py",
           "tools/run-phase3.py", "tools/run-phase1.py", "tools/verify-phase3.py")
CONFIGURATION = ("settings.gradle.kts",) + tuple(m + "/build.gradle.kts" for m in MODULES)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


phase3 = module("phase4_dependencies", "tools/run-phase3.py")
guard = phase3.guard


def save(path, value):
    data = json.dumps(value, indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(data)
    temporary.replace(path)


def approved_paths(names, root=ROOT):
    approved = []
    for name in sorted(names):
        path = Path(name)
        if (path.is_absolute() or ".." in path.parts or any(".env" in part.lower() for part in path.parts)
                or any(part in (".git", ".g2-local", ".secrets", ".credentials", ".aws", ".ssh") for part in path.parts)):
            raise ValueError("Unsafe execution input path")
        candidate = root / path
        if (candidate.is_symlink() or candidate.resolve() != candidate or not candidate.resolve().is_relative_to(root.resolve())
                or not stat.S_ISREG(candidate.lstat().st_mode)):
            raise ValueError("Unsafe execution input file")
        approved.append((name, candidate))
    return approved


def hashes(names):
    # Validate the complete inventory, including symlink components, before reading.
    return {name: guard.digest(path.read_bytes()) for name, path in approved_paths(names)}


def source_paths():
    sources = {str(p.relative_to(ROOT)) for m in ("core", "observe-core", "legacy-observe", "legacy-compat-testkit") + MODULES
               for p in (ROOT / m / "src").rglob("*.java")}
    sources |= {"spring-boot-demo/src/main/java/dev/udak/demo/" + n + ".java"
                for n in ("UserEntity", "UserJpaRepository", "UserMapper", "MixedUserService")}
    approved_paths(sources)
    return sources


def protocol(text, code):
    expected = ["H2 PASS", "CHECKS=10", "CLEANUP=CONFIRMED"] + ["SCENARIO=" + n + ":PASS" for n in CHECKS]
    lines = text.splitlines()
    count = re.fullmatch(r"ASSERTIONS=([1-9][0-9]*)", lines[-1]) if lines else None
    if code != 0 or len(lines) != 14 or lines[:-1] != expected or not count:
        raise ValueError("Incomplete transaction protocol")
    return {"status": "PASS", "checks": 10, "cleanup": "CONFIRMED", "assertions": int(count[1]),
            "scenarios": {name: "PASS" for name in CHECKS}}


def prior_gate(existing=None):
    verifier = module("phase4_prior_gate", "tools/verify-phase3.py")
    if existing is None:
        existing = json.loads((ROOT / "evidence/PHASE3-GATE.json").read_text())
    # Validate the entire report-path map before reading any report-supplied path.
    records = existing.get("execution_reports_sha512", {})
    if (not isinstance(records, dict) or set(records) != set(verifier.INPUTS)
            or any(not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{128}", sha) for sha in records.values())):
        raise ValueError("Unexpected prior execution report paths")
    for name in verifier.INPUTS:
        path = ROOT / name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError("Unsafe prior execution report")
    reports = [json.loads((ROOT / name).read_text()) for name in verifier.INPUTS]
    expected = verifier.verify(*reports)
    if any(existing.get(k) != value for k, value in expected.items()):
        raise ValueError("Prior G3 evidence differs")
    for name in verifier.INPUTS:
        if guard.digest((ROOT / name).read_bytes()) != records[name]:
            raise ValueError("Prior execution proof changed")
    if existing["verifier_sha512"] != guard.digest((ROOT / "tools/verify-phase3.py").read_bytes()):
        raise ValueError("Prior verifier changed")
    return {"status": "PASS", "real_database_scenarios": 40, "rerun": False,
            "gate_sha512": guard.digest((ROOT / "evidence/PHASE3-GATE.json").read_bytes())}


def main():
    started = time.monotonic()
    result = {"schema_version": 1, "phase": 4, "status": "FAIL", "steps": [],
              "scope": "explicit configuration and current-thread policy diagnostics; actual Spring/H2 transactions",
              "limits": {"wall_seconds": 300, "child_cpu_seconds": 30, "heap_mib": 256, "metaspace_mib": 128,
                         "active_cpus": 2, "workspace_files": 2000, "workspace_bytes": 134217728},
              "compile_release": 17, "containers_started": 0, "existing_managed_instances_modified": 0,
              "not_run": ["new four-vendor propagation/readOnly/isolation/timeout matrix", "XA/distributed transactions",
                          "Spring Boot autoconfiguration", "Gradle tasks", "Boot 3/4 certification",
                          "server query cancellation and ambiguous-commit recovery", "performance/load"]}
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, guard.interrupted)
    signal.alarm(300)
    try:
        result["documentation"] = guard.verify_documents()
        result["prior_g3"] = prior_gate()
        result["source_sha512"] = hashes(source_paths())
        result["harness_sha512"] = hashes(HARNESS)
        result["configuration_sha512"] = hashes(CONFIGURATION)
        result["manifest_sha512"] = hashes(["tools/phase3-dependencies.json"])
        with guard.workspace("udak-phase4-") as (work, cleanup):
            result["cleanup"] = cleanup
            os.putenv("TMPDIR", str(work))
            for key in ("_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS"):
                os.unsetenv(key)
            os.putenv("_JAVA_OPTIONS", "-Xmx256m -XX:MaxMetaspaceSize=128m -XX:ActiveProcessorCount=2")
            result["steps"].append(guard.run_step("core-smoke", ["./tools/run-core-smoke.sh"], work))
            os.unsetenv("_JAVA_OPTIONS")
            classpath, _, result["dependencies"], step = phase3.build(work)
            result["steps"].append(step)
            sources = sorted(ROOT / name for name in source_paths() if name.split("/")[0] in MODULES)
            javac = ["javac", "-J-Xmx256m", "-J-XX:MaxMetaspaceSize=128m", "-J-XX:ActiveProcessorCount=2", "--release", "17"]
            result["steps"].append(guard.run_step("compile-phase4", javac + ["-cp", classpath, "-d", str(work / "classes")]
                                                  + [str(p) for p in sources], work))
            isolated = work / "consistency-jdk-only"
            isolated.mkdir()
            result["steps"].append(guard.run_step("compile-consistency-jdk-only", javac + ["-d", str(isolated)]
                                                  + [str(p) for p in sources if "consistency-core" in p.parts], work))
            java = ["java", "-Xmx256m", "-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2", "-cp", classpath]
            cases = (("core-contract", "dev.udak.core.CompilerContractTest"),
                     ("observe-contract", "dev.udak.observe.ObserveContractTest"),
                     ("adapter-contract", "dev.udak.observe.LegacyObserveAdapterContractTest"),
                     ("legacy-h2-regression", "dev.udak.compat.LegacyCompatibilityTest"),
                     ("transaction-core-contract", "dev.udak.consistency.TransactionGuardContractTest"),
                     ("spring-guard-contract", "dev.udak.consistency.spring.SpringGuardContractTest"),
                     ("transaction-h2", "dev.udak.consistency.Phase4TransactionTest"))
            for name, cls in cases:
                command = java + [cls]
                if name == "transaction-core-contract":
                    command = java[:4] + ["-cp", str(isolated), cls]
                try:
                    step = guard.run_step(name, command, work, timeout=90 if name in ("legacy-h2-regression", "transaction-h2") else 30)
                except RuntimeError:
                    # Retain only fixed protocol codes and project frames, never log text.
                    safe = re.compile(r"(?:H2 FAIL: [A-Z_]+|DIAGNOSTIC=[A-Za-z0-9_.$]+(?: at dev\.udak\.[A-Za-z0-9_.$]+:[0-9]+)?)$")
                    result["safe_diagnostics"] = [line for line in (work / (name + ".output")).read_text().splitlines()
                                                  if safe.fullmatch(line)][:5]
                    raise
                output = (work / (name + ".output")).read_text()
                count = re.search(r"(?:assertions|checks): ([0-9]+)", output)
                if count:
                    step["assertions"] = int(count[1])
                result["steps"].append(step)
                if name == "legacy-h2-regression":
                    result["legacy_h2"] = phase3.protocol("H2", output, step["exit_code"])
                    if result["legacy_h2"]["status"] != "PASS":
                        raise ValueError("Legacy compatibility incomplete")
                if name == "transaction-h2":
                    result["h2"] = protocol(output, step["exit_code"])
            result["status"] = "PASS"
    except Exception as error:
        result["failure_type"] = type(error).__name__
        # run_step errors carry only bounded safe categories/locations, never the raw log.
        if isinstance(error, RuntimeError):
            try:
                detail = json.loads(str(error))
                if isinstance(detail, dict) and "exit_code" in detail and "name" in detail:
                    result["failed_step"] = detail
            except (ValueError, TypeError):
                pass
    finally:
        signal.alarm(0)
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if REPORT.exists():
            old = REPORT.read_bytes()
            previous = ROOT / ".git/udak-phase4/previous-reports" / (hashlib.sha256(old).hexdigest() + ".json")
            previous.parent.mkdir(parents=True, exist_ok=True)
            previous.write_bytes(old)
        save(REPORT, result)
    print(json.dumps({k: result[k] for k in ("status", "steps", "h2", "cleanup", "failure_type", "failed_step") if k in result}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
