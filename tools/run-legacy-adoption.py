#!/usr/bin/env python3
"""Run the bounded, internal Hibernate/MyBatis/JdbcTemplate adoption rehearsal."""

import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import traceback


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "evidence/LEGACY-ADOPTION-VALIDATION.json"
spec = importlib.util.spec_from_file_location("inventory_runner", ROOT / "tools/run-sql-inventory.py")
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)
phase3 = inventory.phase3
guard = inventory.guard
COMPATIBILITY = "dev.udak.compat.LegacyCompatibilityTest"
INSPECTOR = ("EXISTING_INSPECTOR", "BUSINESS_RESULT", "MIXED_ROLLBACK", "EFFECTIVE_SQL_OBSERVATION")
INTEGRATION = ROOT / "sql-inventory/src/integrationTest/java/dev/udak/inventory/InventoryIntegrationTest.java"


def report_command(work, candidate):
    launcher = "import os,runpy,sys; os.chdir(sys.argv.pop(2)); sys.argv.pop(0); runpy.run_path(sys.argv[0],run_name='__main__')"
    return [sys.executable, "-B", "-c", launcher, str(ROOT / "tools/sql-inventory.py"), str(work),
            "--base", "base/SQL-INVENTORY.json", "--head", f"{candidate}/SQL-INVENTORY.json", "--fail-on-change"]


def compare_control(base, control, report):
    if (control["revision"] != "3" * 40 or base["entries"] != control["entries"]
            or report["status"] != "COMPLETE" or report["changes_detected"] is not False
            or any(query["changes"] for query in report["queries"])):
        raise ValueError("Unchanged control generated a finding")
    return {"reviewed_entries": len(control["entries"]), "false_positive_findings": 0}


def compare_gap(base, gap, report):
    base_keys = {(entry["framework"], entry["query_id_hash"]) for entry in base["entries"]}
    retained = [entry for entry in gap["entries"] if (entry["framework"], entry["query_id_hash"]) in base_keys]
    added = [entry for entry in gap["entries"] if (entry["framework"], entry["query_id_hash"]) not in base_keys]
    reason = {"UNSUPPORTED_SYNTAX": 1}
    if (gap["revision"] != "4" * 40 or retained != base["entries"] or len(added) != 1
            or report["status"] != "INCOMPLETE" or report["head"]["unavailable_reasons"] != reason
            or gap["dropped"] != 0):
        raise ValueError("Coverage gap protocol invalid")
    entry, = added
    if (entry["framework"] != "JDBC" or entry["identity"] != "SCOPED" or entry["observed"] != 1
            or entry["unavailable"] != 1 or entry["shapes"] or entry["unavailable_reasons"] != reason):
        raise ValueError("Coverage reason missing")
    return {"status": "INCOMPLETE", "unavailable_reasons": reason, "successful_fixture_queries": 1}


def execute(result):
    with guard.workspace("udak-legacy-adoption-") as (work, cleanup):
        result["cleanup"] = cleanup
        os.environ["TMPDIR"] = str(work)
        for key in ("_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS"):
            os.environ.pop(key, None)

        def run(name, command, timeout=30, expected=0):
            try:
                proof = guard.run_step(name, command, work, timeout=timeout, expected=expected)
            except RuntimeError:
                result["failed_step"] = name
                raise
            if not proof["child_reaped"] or not proof["process_group_quiesced"]:
                raise ValueError("Child cleanup incomplete")
            result["steps"].append(proof)
            return (work / (name + ".output")).read_text(encoding="utf-8")

        run("core-smoke", ["/usr/bin/env", "_JAVA_OPTIONS=" + " ".join(inventory.JAVA[1:]),
                           "./tools/run-core-smoke.sh"])
        phase3.fetch = inventory.h.fetch
        classpath, sources, dependencies, compile_step = phase3.build(work)
        result["steps"].append(compile_step)
        legacy = [*inventory.JAVA, "-cp", classpath, COMPATIBILITY]
        result["compatibility"] = phase3.protocol("H2", run("legacy-off-on", legacy, timeout=45), 0)
        inspector = run("existing-hibernate-inspector", [*legacy, "--hibernate-inspector"], timeout=45)
        if result["compatibility"]["status"] != "PASS" or inspector.splitlines() != [
            "H2_INSPECTOR PASS", f"CHECKS={len(INSPECTOR)}", "CLEANUP=CONFIRMED",
            *(f"SCENARIO={scenario}:PASS" for scenario in INSPECTOR),
        ]:
            raise ValueError("Legacy contract evidence invalid")
        result["hibernate_inspector_checks"] = len(INSPECTOR)

        inventory_sources = sorted((ROOT / "sql-inventory/src/main/java").rglob("*.java"))
        classes = work / "inventory-classes"
        run("compile-adoption-captures", [*inventory.JAVAC, "-cp", classpath, "-d", str(classes),
                                         *(str(path) for path in inventory_sources), str(INTEGRATION)])
        snapshots = {name: work / name / "SQL-INVENTORY.json" for name in ("base", "head", "control", "gap")}
        for path in snapshots.values():
            path.parent.mkdir()
        capture = [*inventory.JAVA, "-cp", os.pathsep.join((str(classes), classpath)),
                   "dev.udak.inventory.InventoryIntegrationTest"]
        output = run("adoption-captures", [*capture, *(str(path) for path in snapshots.values())], timeout=45)
        result["inventory_integration_assertions"] = inventory.contract(output, "INVENTORY_INTEGRATION")
        original = [work / ("original-" + name) for name in ("base", "head")]
        output = run("inventory-two-output-regression", [*capture, *(str(path) for path in original)], timeout=45)
        original_count = inventory.contract(output, "INVENTORY_INTEGRATION")
        if original_count != 14 or any(
            path.read_bytes() != snapshots[name].read_bytes() for name, path in zip(("base", "head"), original)
        ):
            raise ValueError("Original capture contract changed")
        result["original_capture_assertions"] = original_count
        captures = {name: json.loads(path.read_bytes()) for name, path in snapshots.items()}
        reports = {name: json.loads(run(f"compare-{name}", report_command(work, name), expected=code))
                   for name, code in (("head", 3), ("control", 0), ("gap", 2))}
        result["known_changes"] = inventory.validate_pair(captures["base"], captures["head"], reports["head"])
        result["unchanged_control"] = compare_control(captures["base"], captures["control"], reports["control"])
        result["coverage_gap"] = compare_gap(captures["base"], captures["gap"], reports["gap"])
        result["setup"] = {
            "framework_hook_count": 3,
            "framework_hooks": ["HIBERNATE_INSPECTOR", "MYBATIS_INTERCEPTOR", "SHARED_JDBC_DATASOURCE"],
            "shared_datasource_verified": result["compatibility"]["scenarios"]["SHARED_RESOURCE"] == "PASS",
            "same_demo_sources_off_and_on": True,
            "operator_setup_time": "NOT MEASURED",
        }
        result["dependency_manifest_sha512"] = dependencies["manifest_sha512"]
        inputs = [*sources, *inventory_sources, INTEGRATION, Path(__file__),
                  *(ROOT / path for path in inventory.SCRIPTS)]
        result["input_sha512"] = {
            str(path.relative_to(ROOT)): guard.digest(path.read_bytes()) for path in sorted(set(inputs))
        }
    if cleanup.get("status") != "PASS" or cleanup.get("temporary_directory_remaining") is not False:
        raise ValueError("Workspace cleanup incomplete")


def main():
    if sys.argv[1:]:
        return 2
    result = {"schema_version": 1, "requirement": "NEXT-005", "status": "FAIL",
              "scope": "IN_REPOSITORY_H2_REHEARSAL", "steps": [], "compile_target": 17,
              "external_legacy_pilot": "NOT RUN", "containers_started": 0,
              "limits": {"wall_seconds": 150, "child_cpu_seconds": 30, "heap_mib": 256,
                         "metaspace_mib": 128, "active_cpus": 2}}
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, guard.interrupted)
    signal.alarm(150)
    try:
        execute(result)
    except Exception as error:
        result["failure_type"] = type(error).__name__
        result["failure_locations"] = [
            {"file": Path(frame.filename).name, "line": frame.lineno}
            for frame in traceback.extract_tb(error.__traceback__)
        ]
    else:
        result["status"] = "PASS"
        REPORT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    finally:
        signal.alarm(0)
    print(json.dumps({key: value for key, value in result.items() if key != "input_sha512"}))
    return int(result["status"] != "PASS")


if __name__ == "__main__":
    sys.exit(main())
