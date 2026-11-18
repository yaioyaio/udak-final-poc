#!/usr/bin/env python3
"""Fail closed on stale or incomplete Phase 4 execution and verifier evidence."""
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("phase4_execution", ROOT / "tools/run-phase4.py")
execution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(execution)
prior = execution.module("phase4_file_checks", "tools/verify-phase3.py")
UNIT = "evidence/PHASE4-VERIFIER-VALIDATION.json"
REPORT = "evidence/PHASE4-VALIDATION.json"


def verify(report, root=ROOT):
    inventories = (("source_sha512", execution.source_paths()), ("harness_sha512", set(execution.HARNESS)),
                   ("configuration_sha512", set(execution.CONFIGURATION)),
                   ("manifest_sha512", {"tools/phase3-dependencies.json"}))
    # Check all path inventories before reading any report-supplied path.
    if any(set(report.get(field, {})) != expected for field, expected in inventories):
        raise ValueError("Unexpected execution inputs")
    for field, expected in inventories:
        prior.check_files(report[field], expected, root)
    cleanup = report.get("cleanup", {})
    if (report.get("status") != "PASS" or report.get("phase") != 4 or report.get("compile_release") != 17
            or report.get("failure_type") or report.get("failed_step") or cleanup.get("status") != "PASS"
            or cleanup.get("temporary_directory_remaining") is not False
            or cleanup.get("temporary_files_removed", 0) < 1 or cleanup.get("temporary_bytes_removed", 0) < 1
            or report.get("containers_started") != 0 or report.get("existing_managed_instances_modified") != 0):
        raise ValueError("Execution, cleanup or preservation incomplete")
    names = ("core-smoke", "compile-phase3", "compile-phase4", "compile-consistency-jdk-only", "core-contract",
             "observe-contract", "adapter-contract", "legacy-h2-regression", "transaction-core-contract",
             "spring-guard-contract", "transaction-h2")
    steps = report.get("steps", [])
    if [s.get("name") for s in steps] != list(names):
        raise ValueError("Execution steps incomplete")
    for step in steps + [steps[1].get("observe_jdk_only_compile", {})]:
        if (step.get("status") != "PASS" or step.get("exit_code") != 0 or step.get("child_reaped") is not True
                or step.get("process_group_quiesced") is not True):
            raise ValueError("Child execution incomplete")
    counts = {step["name"]: step.get("assertions", 0) for step in steps}
    for name, minimum in (("core-contract", 74), ("observe-contract", 202), ("adapter-contract", 188),
                          ("transaction-core-contract", 30), ("spring-guard-contract", 15)):
        if not isinstance(counts[name], int) or counts[name] < minimum:
            raise ValueError("Contract evidence incomplete")
    for field, expected in (("h2", execution.CHECKS), ("legacy_h2", execution.phase3.CHECKS)):
        result = report.get(field, {})
        if (result.get("status") != "PASS" or result.get("checks") != 10 or result.get("cleanup") != "CONFIRMED"
                or result.get("scenarios") != {name: "PASS" for name in expected}):
            raise ValueError("Transaction compatibility incomplete")
    if report["h2"].get("assertions", 0) < 30:
        raise ValueError("Insufficient transaction assertions")
    recorded = report.get("prior_g3", {})
    current = execution.prior_gate()
    if recorded != current:
        raise ValueError("Prior four-DB G3 no longer matches")
    dependencies = report.get("dependencies", {})
    manifest = json.loads((root / "tools/phase3-dependencies.json").read_text())
    expected = {item["coordinate"]: {"coordinate": item["coordinate"], "jar_sha512": item["jar_sha512"],
                "pom_sha512": item["pom_sha512"], "effective_licenses": item["effective_licenses"],
                "notice_entries_verified": len(item["license_entries"]), "published_checksum_verified": True}
                for item in manifest["artifacts"]}
    artifacts = dependencies.get("artifacts", [])
    if (dependencies.get("status") != "PASS" or len(expected) != 36 or len(artifacts) != 36
            or any(not isinstance(item, dict) or item.get("published_checksum_verified") is not True
                   or item != expected.get(item.get("coordinate")) for item in artifacts)
            or len({item["coordinate"] for item in artifacts}) != 36
            or dependencies.get("jar_bytes") != sum(item["jar_bytes"] for item in manifest["artifacts"])
            or dependencies.get("redistribution_approval") != "NOT GRANTED"
            or dependencies.get("manifest_sha512") != report["manifest_sha512"]["tools/phase3-dependencies.json"]):
        raise ValueError("Pinned dependency evidence incomplete")
    return {"schema_version": 1, "phase": 4, "status": "PASS",
            "scope": "explicit configuration/current-thread diagnostics and actual Spring/H2 transaction contracts",
            "core_guard_assertions": counts["transaction-core-contract"],
            "spring_guard_assertions": counts["spring-guard-contract"], "h2_scenarios": 10,
            "h2_assertions": report["h2"]["assertions"], "legacy_h2_regression_scenarios": 10,
            "previous_four_db_g3": "PRESERVED; 40 scenarios, not rerun in Phase 4",
            "compile_release": 17, "containers_started": 0, "existing_managed_instances_modified": 0,
            "automatic_cleanup_files": cleanup["temporary_files_removed"],
            "automatic_cleanup_bytes": cleanup["temporary_bytes_removed"],
            "new_vendor_tx_matrix_boot_gradle_xa_recovery_performance": "NOT RUN",
            "product_distribution_approval": "NOT GRANTED"}


def verify_unit(unit):
    prior.check_files(unit.get("source_sha512", {}), {"tools/verify-phase4.py", "tools/test-phase4-verifier.py"}, ROOT)
    step = unit.get("step", {})
    if (unit.get("status") != "PASS" or unit.get("tests", 0) < 13 or step.get("exit_code") != 0
            or not step.get("child_reaped") or not step.get("process_group_quiesced")
            or unit.get("cleanup", {}).get("status") != "PASS"
            or unit["cleanup"].get("temporary_directory_remaining") is not False):
        raise ValueError("Verifier negative tests incomplete")


def main():
    try:
        result = verify(json.loads((ROOT / REPORT).read_text()))
        verify_unit(json.loads((ROOT / UNIT).read_text()))
        result["verifier_negative_tests"] = "PASS"
        result["execution_reports_sha512"] = execution.hashes([REPORT, UNIT])
        result["verifier_sha512"] = execution.guard.digest(Path(__file__).read_bytes())
        execution.save(ROOT / "evidence/PHASE4-GATE.json", result)
        print(json.dumps({k: result[k] for k in ("phase", "status", "core_guard_assertions", "spring_guard_assertions", "h2_scenarios")}))
        return 0
    except Exception as error:
        print(json.dumps({"phase": 4, "status": "FAIL", "failure_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
