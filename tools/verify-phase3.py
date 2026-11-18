#!/usr/bin/env python3
"""Verify Phase 3 contracts, matching sources and four real framework matrices."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
CHECKS = ("SHARED_RESOURCE", "EXISTING_SERVICE", "FLUSH_VISIBILITY", "JPA_CACHE", "MYBATIS_CACHE",
          "MIXED_COMMIT", "MIXED_ROLLBACK", "RESULT_MAPPING", "OBSERVATION_METADATA", "LISTENER_FAILURE")
PROFILES = ("POSTGRESQL", "MYSQL", "SQLSERVER", "ORACLE")
HARNESS = {"tools/run-phase3-real.py", "tools/run-phase3.py", "tools/run-managed-g2.py", "tools/g2-docker.py", "tools/run-phase1.py"}
MANIFESTS = {"tools/phase3-dependencies.json", "tools/g2-dependencies.json", "tools/g2-server-images.json"}
INPUTS = ("evidence/PHASE3-VALIDATION.json", "evidence/PHASE3-REAL-VALIDATION.json", "evidence/PHASE3-CONTAINER-RETENTION.json")


def digest(data):
    return hashlib.sha512(data).hexdigest()


def check_files(records, allowed, root):
    if set(records) != set(allowed):
        raise ValueError("Unapproved or incomplete execution input inventory")
    for name, value in records.items():
        p = Path(name)
        if p.is_absolute() or ".." in p.parts or any(".env" in part.lower() for part in p.parts):
            raise ValueError("Unsafe execution input path")
        path = root / p
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or not re.fullmatch(r"[0-9a-f]{128}", value):
            raise ValueError("Unsafe execution input")
        if digest(path.read_bytes()) != value:
            raise ValueError("Execution inputs changed")


def verify(base, real, retention, root=ROOT):
    expected_base = {str(p.relative_to(root)) for module in ("core", "observe-core", "legacy-observe", "legacy-compat-testkit")
                     for p in (root / module / "src").rglob("*.java")}
    expected_base |= {"spring-boot-demo/src/main/java/dev/udak/demo/" + n + ".java"
                      for n in ("UserEntity", "UserJpaRepository", "UserMapper", "MixedUserService")}
    extra = {str(p.relative_to(root)) for module in ("udak-api", "jdbc-spring", "db-testkit")
             for p in (root / module / "src/main/java").rglob("*.java")}
    # Validate the complete allowlist before opening any path supplied by a report.
    if set(base.get("source_sha512", {})) != expected_base or set(real.get("source_sha512", {})) != expected_base | extra:
        raise ValueError("Unexpected execution source paths")
    check_files(base["source_sha512"], expected_base, root)
    check_files(real["source_sha512"], expected_base | extra, root)
    check_files(real.get("harness_sha512", {}), HARNESS, root)
    check_files(real.get("manifest_sha512", {}), MANIFESTS, root)
    if base.get("harness_sha512") != real["harness_sha512"]["tools/run-phase3.py"]:
        raise ValueError("Contract and real execution harness differ")
    for report in (base, real):
        if (report.get("status") != "PASS" or report.get("failure_type") or report.get("cleanup", {}).get("status") != "PASS"
                or report["cleanup"].get("temporary_directory_remaining") is not False):
            raise ValueError("Execution or automatic cleanup incomplete")
    if base.get("h2", {}).get("scenarios") != {n: "PASS" for n in CHECKS} or base["h2"].get("checks") != 10:
        raise ValueError("H2 compatibility incomplete")
    for name, minimum in (("core-contract", 74), ("observe-contract", 202), ("adapter-contract", 188)):
        found = [s for s in base["steps"] if s["name"] == name]
        if len(found) != 1 or found[0]["exit_code"] != 0 or found[0].get("assertions", 0) < minimum:
            raise ValueError("Observe regression incomplete")
    if set(real.get("profiles", {})) != set(PROFILES) or real.get("checks") != 40 or real.get("containers_started") != 4:
        raise ValueError("Four actual databases required")
    if retention.get("status") != "PASS" or retention.get("active_managed_instances") != 0 or retention.get("new_phase3_instances") != 4:
        raise ValueError("Runtime reclamation unconfirmed")
    images = {v["profile"]: v for v in json.loads((root / "tools/g2-server-images.json").read_text())["images"]}
    versions = json.loads((root / "tools/g2-dependencies.json").read_text())["metadata_versions"]
    ids = set()
    for name in PROFILES:
        r = real["profiles"][name]
        steps = [s for s in real["steps"] if s["name"] == "compatibility-" + name]
        if (r.get("status") != "PASS" or r.get("checks") != 10 or r.get("cleanup") != "CONFIRMED"
                or r.get("scenarios") != {n: "PASS" for n in CHECKS} or r.get("container_stopped") is not True
                or r.get("data_preserved") is not True or r.get("image") != images[name]["image"]
                or r.get("platform") != images[name]["platform"] or len(steps) != 1 or steps[0]["exit_code"] != 0
                or not steps[0].get("child_reaped") or not steps[0].get("process_group_quiesced")
                or not re.fullmatch(r"[0-9]+\.[0-9]+", r.get("server_version", ""))
                or r.get("driver_version") != ".".join(versions[name].split(".")[:2])
                or not re.fullmatch(r"[0-9a-f]{64}", r.get("container_id", ""))):
            raise ValueError("Real framework or identity evidence incomplete")
        if r["container_id"] in ids:
            raise ValueError("Isolation identities duplicate")
        ids.add(r["container_id"])
        saved = retention["profiles"][name]
        if saved.get("container_id") != r["container_id"] or saved.get("state") != "exited" or saved.get("oom_killed") is not False:
            raise ValueError("Database retention unconfirmed")
    return {"schema_version": 1, "phase": 3, "gate": "G3", "status": "PASS", "scope": "selected Hibernate/MyBatis/JdbcTemplate Observe and same-DataSource compatibility",
            "observe_contract_assertions": 202, "adapter_contract_assertions": 188, "h2_scenarios": 10, "real_database_scenarios": 40,
            "profiles": {name: {"status": "PASS", "checks": 10, "server_version": real["profiles"][name]["server_version"],
                                "driver_version": real["profiles"][name]["driver_version"]} for name in PROFILES},
            "execution_started_at_utc": real["started_at_utc"], "compile_release": 17,
            "native_platform_shutdown_recovery_performance_boot_autoconfig": "NOT RUN",
            "preserved_managed_instances": retention["total_preserved_managed_instances"], "active_managed_instances": 0,
            "automatic_cleanup_files": base["cleanup"]["temporary_files_removed"] + real["cleanup"]["temporary_files_removed"],
            "automatic_cleanup_bytes": base["cleanup"]["temporary_bytes_removed"] + real["cleanup"]["temporary_bytes_removed"],
            "product_distribution_approval": "NOT GRANTED"}


def main():
    try:
        loaded = [json.loads((ROOT / name).read_text()) for name in INPUTS]
        result = verify(*loaded)
        result["execution_reports_sha512"] = {name: digest((ROOT / name).read_bytes()) for name in INPUTS}
        result["verifier_sha512"] = digest(Path(__file__).read_bytes())
        spec = importlib.util.spec_from_file_location("atomic_report", ROOT / "tools/run-managed-g2.py")
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        runtime.save(ROOT / "evidence/PHASE3-GATE.json", result)
        print(json.dumps({"gate": "G3", "status": "PASS", "h2_scenarios": 10, "real_database_scenarios": 40}))
        return 0
    except Exception as failure:
        print(json.dumps({"gate": "G3", "status": "FAIL", "failure_type": type(failure).__name__}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
