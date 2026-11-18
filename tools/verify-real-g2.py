#!/usr/bin/env python3
"""Verify two identical-code execution batches cover all four real G2 profiles."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
INPUTS = ("evidence/G2-RUN-SQLSERVER.json", "evidence/G2-RUN-OTHER-DATABASES.json")
OUTPUT = ROOT / "evidence/G2-REAL-VALIDATION.json"
PROFILES = ("POSTGRESQL", "MYSQL", "SQLSERVER", "ORACLE")
SCENARIOS = ("INSERT_NULL", "READ_NULL", "UPDATE", "INSERT_SECOND", "INSERT_THIRD", "PAGE", "BIND", "COMMIT", "ROLLBACK", "DELETE")


def digest(data):
    return hashlib.sha512(data).hexdigest()


def verify(batches, root=ROOT):
    if len(batches) != 2:
        raise ValueError("Two execution batches required")
    for key in ("source_sha512", "harness_sha512", "manifest_sha512"):
        if not batches[0].get(key) or batches[0][key] != batches[1].get(key):
            raise ValueError("Execution inputs differ")
        for name, expected in batches[0][key].items():
            path = root / name
            if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != expected:
                raise ValueError("Execution source or dependency manifest changed")
    for batch in batches:
        if (batch.get("gate") != "G2" or batch.get("failure_type")
                or batch.get("existing_containers_modified") != 0
                or batch.get("cleanup", {}).get("status") != "PASS"
                or batch["cleanup"].get("temporary_directory_remaining") is not False):
            raise ValueError("Batch cleanup or execution unconfirmed")
        passed = [v for v in batch["profiles"].values() if v.get("status") == "PASS"]
        if batch.get("containers_started") != len(passed):
            raise ValueError("Unaccounted database runtime")
    server_manifest = json.loads((root / "tools/g2-server-images.json").read_text())
    images = {item["profile"]: item for item in server_manifest["images"]}
    profiles = {}
    containers, fixtures = set(), set()
    for name in PROFILES:
        matched = [batch for batch in batches if batch["profiles"][name].get("status") == "PASS"]
        if len(matched) != 1:
            raise ValueError("Every real profile must have one verified execution")
        batch = matched[0]
        record = batch["profiles"][name]
        steps = [step for step in batch["steps"] if step["name"] == "live-" + name]
        if (len(steps) != 1 or steps[0].get("exit_code") != 0 or not steps[0].get("child_reaped")
                or not steps[0].get("process_group_quiesced") or record.get("checks") != 10
                or record.get("scenarios") != {s: "PASS" for s in SCENARIOS}
                or record.get("cleanup") != "CONFIRMED" or record.get("container_stopped") is not True
                or record.get("container_and_data_preserved") is not True
                or not re.fullmatch(r"[0-9]+\.[0-9]+", record.get("server_version", ""))
                or not re.fullmatch(r"[0-9]+\.[0-9]+", record.get("driver_version", ""))
                or record.get("image") != images[name]["image"] or record.get("platform") != images[name]["platform"]
                or not re.fullmatch(r"[0-9a-f]{64}", record.get("container_id", ""))
                or not re.fullmatch(r"udak_p2_[0-9a-f]{12}", record.get("fixture", ""))):
            raise ValueError("Real execution evidence incomplete")
        if record["container_id"] in containers or record["fixture"] in fixtures:
            raise ValueError("Database isolation identity duplicated")
        containers.add(record["container_id"])
        fixtures.add(record["fixture"])
        profiles[name] = {k: record[k] for k in ("status", "server_version", "driver_version", "checks", "scenarios", "cleanup",
                                                "container_stopped", "container_and_data_preserved", "image", "platform", "container_id", "fixture")}
        profiles[name]["execution_run_id"] = batch["run_id"]
    phase2 = json.loads((root / "evidence/PHASE2-VALIDATION.json").read_text())
    if phase2.get("status") != "PASS":
        raise ValueError("API and executor regression failed")
    return {"schema_version": 1, "gate": "G2", "status": "PASS", "scope": "minimal functional CRUD/Query/Spring JDBC transaction contracts",
            "profiles": profiles, "checks": 40, "actual_database_instances": 4, "maximum_active_instances": 1,
            "adjacent_regression_java_runtime_version": phase2["java_runtime_version"], "compile_release": 17,
            "runtime_version_evidence": {"path": "evidence/PHASE2-VALIDATION.json",
                                         "sha512": digest((root / "evidence/PHASE2-VALIDATION.json").read_bytes()),
                                         "scope": "adjacent regression runtime; no separate G2 JVM version probe"},
            "native_sqlserver_platform_validation": "NOT RUN", "vendor_platform_certification": "NOT GRANTED; SQL Server uses x86 emulation",
            "product_distribution_approval": "NOT GRANTED", "boot_orm_performance_validation": "NOT RUN",
            "source_sha512": batches[0]["source_sha512"], "harness_sha512": batches[0]["harness_sha512"],
            "manifest_sha512": batches[0]["manifest_sha512"],
            "temporary_files_removed": sum(b["cleanup"]["temporary_files_removed"] for b in batches),
            "temporary_bytes_removed": sum(b["cleanup"]["temporary_bytes_removed"] for b in batches)}


def main():
    try:
        batches = [json.loads((ROOT / name).read_text()) for name in INPUTS]
        result = verify(batches)
        result["execution_reports_sha512"] = {name: digest((ROOT / name).read_bytes()) for name in INPUTS}
        result["verifier_sha512"] = digest(Path(__file__).read_bytes())
        spec = importlib.util.spec_from_file_location("managed_atomic_report", ROOT / "tools/run-managed-g2.py")
        managed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(managed)
        managed.save(OUTPUT, result)
        print(json.dumps({"gate": "G2", "status": "PASS", "real_profiles": 4, "checks": 40}))
        return 0
    except Exception as error:
        print(json.dumps({"gate": "G2", "status": "FAIL", "failure_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
