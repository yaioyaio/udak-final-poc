#!/usr/bin/env python3
"""Bounded policy/parser/JDBC contracts and H2 equivalence; never starts Docker."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
MODULES = ("rewrite-core", "rewrite-jsqlparser", "rewrite-jdbc", "rewrite-testkit")
CHECKS = ("BASELINE", "PAGING", "NULL_MAPPING", "BIND_ORDER", "LABELS_TYPES", "TRANSACTION", "DEFAULT_DENY", "EVIDENCE")
REPORT = ROOT / "evidence/PHASE5-VALIDATION.json"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


p4 = module("phase5_predecessor", "tools/run-phase4.py")
guard = p4.guard
JAVA = ["java", "-Xmx256m", "-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2"]
JAVAC = ["javac", "-J-Xmx256m", "-J-XX:MaxMetaspaceSize=128m", "-J-XX:ActiveProcessorCount=2", "--release", "17"]
HARNESS = ("tools/run-phase5.py", "tools/run-phase5-real.py", "tools/verify-phase5.py", "tools/test-phase5-verifier.py",
           "tools/run-phase4.py", "tools/verify-phase4.py", "tools/run-phase3.py", "tools/run-phase1.py",
           "tools/run-managed-g2.py", "tools/g2-docker.py", "tools/run-g2.py", "tools/run-phase2.py")
MANIFESTS = ("tools/phase1-dependencies.json", "tools/phase3-dependencies.json", "tools/g2-dependencies.json", "tools/g2-server-images.json")
CONFIGURATION = ("settings.gradle.kts",) + tuple(m + "/build.gradle.kts" for m in MODULES) + (
    "db-testkit/src/main/resources/META-INF/services/dev.udak.testkit.RealDatabaseProvider",
    "sql-jsqlparser/src/main/resources/META-INF/LICENSE-jsqlparser.txt",
    "sql-jsqlparser/src/main/resources/META-INF/NOTICE-jsqlparser.txt")
BASELINES = ("evidence/G2-REAL-VALIDATION.json", "evidence/PHASE3-REAL-VALIDATION.json")


def source_paths():
    sources = p4.source_paths()
    for m in MODULES + ("sql-jsqlparser", "udak-api", "jdbc-spring", "db-testkit"):
        sources |= {str(p.relative_to(ROOT)) for p in (ROOT / m / "src").rglob("*.java")}
    p4.approved_paths(sources)
    return sources


def prior_gate():
    verifier = module("phase5_previous_verifier", "tools/verify-phase4.py")
    report = json.loads((ROOT / verifier.REPORT).read_text())
    expected = verifier.verify(report)
    verifier.verify_unit(json.loads((ROOT / verifier.UNIT).read_text()))
    gate = json.loads((ROOT / "evidence/PHASE4-GATE.json").read_text())
    if any(gate.get(k) != v for k, v in expected.items()) or set(gate.get("execution_reports_sha512", {})) != {verifier.REPORT, verifier.UNIT}:
        raise ValueError("Prior gate incomplete")
    verifier.prior.check_files(gate["execution_reports_sha512"], {verifier.REPORT, verifier.UNIT}, ROOT)
    if gate.get("verifier_sha512") != guard.digest((ROOT / "tools/verify-phase4.py").read_bytes()):
        raise ValueError("Prior verifier changed")
    return {"status": "PASS", "phase4_gate_sha512": guard.digest((ROOT / "evidence/PHASE4-GATE.json").read_bytes()),
            "previous_real_g3": "PRESERVED; not rerun"}


def build(work):
    cp, _, deps, step = p4.phase3.build(work)
    parser, parser_evidence = guard.dependency_checks(json.loads((ROOT / "tools/phase1-dependencies.json").read_text()), work)
    cp += os.pathsep + str(parser)
    sources = [ROOT / n for n in sorted(source_paths()) if n.split("/")[0] in MODULES + ("consistency-core", "consistency-spring", "consistency-testkit", "sql-jsqlparser", "udak-api", "jdbc-spring", "db-testkit")]
    compile_step = guard.run_step("compile-phase5", JAVAC + ["-cp", cp, "-d", str(work / "classes")] + [str(p) for p in sources], work)
    isolated = work / "rewrite-jdk-only"
    isolated.mkdir()
    pure = [str(p) for p in sources if "rewrite-core" in p.parts]
    isolated_step = guard.run_step("compile-rewrite-jdk-only", JAVAC + ["-d", str(isolated)] + pure, work)
    return cp, deps, parser_evidence, [step, compile_step, isolated_step]


def protocol(label, output, exit_code):
    lines = output.splitlines()
    expected = [label + " PASS", "CHECKS=8", "CLEANUP=CONFIRMED"] + ["SCENARIO=" + n + ":PASS" for n in CHECKS]
    if exit_code != 0 or len(lines) != 15 or lines[:11] != expected:
        raise ValueError("Equivalence protocol incomplete")
    patterns = (r"ASSERTIONS=([1-9][0-9]*)", r"EVIDENCE_SHA256=([a-f0-9]{64})", r"RESULT_SHA256=([a-f0-9]{64})", r"SOURCE_SQL_EXECUTED=(true|false)")
    matches = [re.fullmatch(pattern, line) for pattern, line in zip(patterns, lines[11:])]
    if not all(matches):
        raise ValueError("Equivalence identity missing")
    return {"status": "PASS", "checks": 8, "cleanup": "CONFIRMED", "assertions": int(matches[0][1]),
            "evidence_digest": matches[1][1], "result_digest": matches[2][1], "source_sql_executed": matches[3][1] == "true",
            "scenarios": {n: "PASS" for n in CHECKS}}


def hashes(names):
    return p4.hashes(names)


def archive_save(path, value):
    if path.exists():
        old = path.read_bytes()
        previous = ROOT / ".git/udak-phase5/previous-reports" / (guard.digest(old) + ".json")
        previous.parent.mkdir(parents=True, exist_ok=True)
        previous.write_bytes(old)
    p4.save(path, value)


def main():
    start = time.monotonic()
    result = {"schema_version": 1, "phase": 5, "status": "FAIL", "steps": [], "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "explicit approved canonical SELECT pagination; H2 only in this report", "compile_release": 17,
              "containers_started": 0, "limits": {"wall_seconds": 300, "heap_mib": 256, "metaspace_mib": 128, "active_cpus": 2,
              "child_cpu_seconds": 30, "workspace_files": 2000, "workspace_bytes": 134217728},
              "not_run": ["four real databases (separate runner)", "automatic JPA/MyBatis rewrite", "general SQL equivalence",
                          "Gradle/Boot certification", "performance/load", "production approval issuance"]}
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, guard.interrupted)
    signal.alarm(300)
    try:
        result["documentation"] = guard.verify_documents()
        result["prior_gate"] = prior_gate()
        result["source_sha512"] = hashes(source_paths())
        result["harness_sha512"] = hashes(HARNESS)
        result["manifest_sha512"] = hashes(MANIFESTS)
        result["configuration_sha512"] = hashes(CONFIGURATION)
        result["preservation_baseline_sha512"] = hashes(BASELINES)
        with guard.workspace("udak-phase5-") as (work, cleanup):
            result["cleanup"] = cleanup
            os.putenv("TMPDIR", str(work))
            for key in ("_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS"):
                os.unsetenv(key)
            os.putenv("_JAVA_OPTIONS", "-Xmx256m -XX:MaxMetaspaceSize=128m -XX:ActiveProcessorCount=2")
            result["steps"].append(guard.run_step("core-smoke", ["./tools/run-core-smoke.sh"], work))
            os.unsetenv("_JAVA_OPTIONS")
            cp, result["framework_dependencies"], result["parser_dependency"], steps = build(work)
            result["steps"].extend(steps)
            cases = (("core-regression", "dev.udak.core.CompilerContractTest"),
                     ("parser-regression", "dev.udak.jsqlparser.JSqlParserCompilerTest"),
                     ("api-regression", "dev.udak.api.CrudApiContractTest"),
                     ("legacy-h2-regression", "dev.udak.compat.LegacyCompatibilityTest"),
                     ("tx-policy-regression", "dev.udak.consistency.TransactionGuardContractTest"),
                     ("rewrite-policy", "dev.udak.rewrite.RewritePolicyContractTest"),
                     ("rewrite-parser", "dev.udak.rewrite.jsqlparser.PaginationRewriteContractTest"),
                     ("rewrite-jdbc", "dev.udak.rewrite.jdbc.SelectiveJdbcContractTest"),
                     ("equivalence-h2", "dev.udak.rewrite.testkit.RewriteEquivalenceTest"))
            for name, cls in cases:
                selected_cp = str(work / "rewrite-jdk-only") if name == "rewrite-policy" else cp
                try:
                    step = guard.run_step(name, JAVA + ["-cp", selected_cp, cls], work, timeout=90)
                except RuntimeError:
                    safe = re.compile(r"(?:H2 FAIL: [A-Z_]+|DIAGNOSTIC=[A-Za-z0-9_.$]+(?::[0-9]+| at dev\.udak\.[A-Za-z0-9_.$]+:[0-9]+)?)$")
                    result["safe_diagnostics"] = [line for line in (work / (name + ".output")).read_text().splitlines() if safe.fullmatch(line)][:5]
                    raise
                output = (work / (name + ".output")).read_text()
                count = re.search(r"(?:assertions|checks)\s*[:=]\s*([0-9]+)", output)
                if count:
                    step["assertions"] = int(count[1])
                result["steps"].append(step)
                if name == "legacy-h2-regression":
                    result["legacy_h2"] = p4.phase3.protocol("H2", output, 0)
                    if result["legacy_h2"]["status"] != "PASS":
                        raise ValueError("Legacy regression incomplete")
                if name == "equivalence-h2":
                    result["h2"] = protocol("H2", output, 0)
            for field, names in (("source_sha512", source_paths()), ("harness_sha512", HARNESS),
                                 ("manifest_sha512", MANIFESTS), ("configuration_sha512", CONFIGURATION),
                                 ("preservation_baseline_sha512", BASELINES)):
                if result[field] != hashes(names):
                    raise ValueError("Execution inputs changed during validation")
            result["status"] = "PASS"
    except Exception as error:
        result["failure_type"] = type(error).__name__
        if isinstance(error, RuntimeError):
            try:
                detail = json.loads(str(error))
                if isinstance(detail, dict) and "exit_code" in detail:
                    result["failed_step"] = detail
            except (ValueError, TypeError):
                pass
    finally:
        signal.alarm(0)
        result["elapsed_seconds"] = round(time.monotonic() - start, 3)
        archive_save(REPORT, result)
    print(json.dumps({k: result[k] for k in ("status", "steps", "h2", "cleanup", "failure_type", "failed_step", "safe_diagnostics") if k in result}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
