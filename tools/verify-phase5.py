#!/usr/bin/env python3
"""Reject partial or altered selective-rewrite and four-DB equivalence evidence."""
import importlib.util
import hashlib
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("phase5_verification", ROOT / "tools/run-phase5.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
old = h.module("phase5_safe_files", "tools/verify-phase3.py")
PROFILES = ("POSTGRESQL", "MYSQL", "SQLSERVER", "ORACLE")
INPUTS = ("evidence/PHASE5-VALIDATION.json", "evidence/PHASE5-REAL-VALIDATION.json", "evidence/PHASE5-VERIFIER-VALIDATION.json")


def inputs(report):
    expected = (("source_sha512", h.source_paths()), ("harness_sha512", set(h.HARNESS)),
                ("manifest_sha512", set(h.MANIFESTS)), ("configuration_sha512", set(h.CONFIGURATION)),
                ("preservation_baseline_sha512", set(h.BASELINES)))
    if any(set(report.get(field, {})) != names for field, names in expected):
        raise ValueError("Unsafe or incomplete input inventory")
    for field, names in expected:
        old.check_files(report[field], names, ROOT)


def clean(report):
    if (report.get("status") != "PASS" or report.get("failure_type") or report.get("failed_step")
            or report.get("cleanup", {}).get("status") != "PASS"
            or report["cleanup"].get("temporary_directory_remaining") is not False
            or report["cleanup"].get("temporary_files_removed", 0) <= 0):
        raise ValueError("Execution or cleanup incomplete")


def dependencies(report):
    manifest = json.loads((ROOT / "tools/phase3-dependencies.json").read_text())
    expected = {a["coordinate"]: {"coordinate": a["coordinate"], "jar_sha512": a["jar_sha512"],
                "pom_sha512": a["pom_sha512"], "effective_licenses": a["effective_licenses"],
                "notice_entries_verified": len(a["license_entries"]), "published_checksum_verified": True}
                for a in manifest["artifacts"]}
    proof = report.get("framework_dependencies", {})
    rows = proof.get("artifacts", [])
    if (proof.get("status") != "PASS" or len(rows) != 36
            or any(not isinstance(a, dict) or a.get("published_checksum_verified") is not True or a != expected.get(a.get("coordinate")) for a in rows)
            or len({a["coordinate"] for a in rows}) != 36
            or proof.get("jar_bytes") != sum(a["jar_bytes"] for a in manifest["artifacts"])
            or proof.get("manifest_sha512") != report["manifest_sha512"]["tools/phase3-dependencies.json"]):
        raise ValueError("Framework dependency proof incomplete")
    parser = report.get("parser_dependency", {})
    pin = json.loads((ROOT / "tools/phase1-dependencies.json").read_text())
    if (parser.get("status") != "PASS" or parser.get("coordinate") != pin["coordinate"]
            or parser.get("jar_sha512") != pin["jar_sha512"] or parser.get("pom_sha512") != pin["pom_sha512"]
            or parser.get("license_sha512") != pin["license_sha512"] or parser.get("bundled_license_verified") is not True
            or parser.get("selected_license") != "Apache-2.0" or parser.get("runtime_dependencies") != []):
        raise ValueError("Parser artifact proof incomplete")


def verify_driver_proof(driver_proof):
    driver_manifest = json.loads((ROOT / "tools/g2-dependencies.json").read_text())
    driver_expected = {a["coordinate"]: {"coordinate": a["coordinate"], "jar_sha512": a["jar_sha512"], "pom_sha512": a["pom_sha512"],
                       "runtime_dependencies": a["runtime_dependencies"], "license_entries_verified": len(a["license_entries"]),
                       "base_class_major_versions": a["base_class_major_versions"], "published_checksum_verified": True}
                       for a in driver_manifest["artifacts"]}
    driver_rows = driver_proof.get("artifacts", [])
    if (driver_proof.get("status") != "PASS" or driver_proof.get("redistribution_approval") != "NOT GRANTED"
            or driver_proof.get("download_bytes") != sum(a["jar_bytes"] + a["pom_bytes"] for a in driver_manifest["artifacts"]) or len(driver_rows) != 6
            or any(not isinstance(a, dict) or a.get("published_checksum_verified") is not True or a != driver_expected.get(a.get("coordinate")) for a in driver_rows)
            or len({a["coordinate"] for a in driver_rows}) != 6
            or driver_proof.get("upstream_license_checks") != [{"url": v["url"], "sha512": v["sha512"], "status": "PASS"} for v in driver_manifest["upstream_license_checks"]]):
        raise ValueError("Actual JDBC driver artifacts unverified")


def scenario(r):
    if (r.get("status") != "PASS" or r.get("checks") != 8 or r.get("cleanup") != "CONFIRMED"
            or r.get("scenarios") != {n: "PASS" for n in h.CHECKS} or r.get("assertions", 0) < 30
            or not re.fullmatch(r"[a-f0-9]{64}", r.get("evidence_digest", ""))
            or not re.fullmatch(r"[a-f0-9]{64}", r.get("result_digest", ""))):
        raise ValueError("Equivalence scenarios incomplete")


def output_hash(label, record, real=False):
    lines = [label + " PASS", "CHECKS=8", "CLEANUP=CONFIRMED"] + ["SCENARIO=" + n + ":PASS" for n in h.CHECKS]
    lines += ["ASSERTIONS=" + str(record["assertions"]), "EVIDENCE_SHA256=" + record["evidence_digest"],
              "RESULT_SHA256=" + record["result_digest"], "SOURCE_SQL_EXECUTED=" + str(record["source_sql_executed"]).lower()]
    if real:
        lines += ["SERVER_VERSION=" + record["server_version"], "DRIVER_VERSION=" + record["driver_version"],
                  "SERVER_RELEASE_SHA256=" + record["server_release_hash"], "DRIVER_RELEASE_SHA256=" + record["driver_release_hash"]]
    return hashlib.sha512(("\n".join(lines) + "\n").encode()).hexdigest()


def verify_local(report):
    inputs(report)
    clean(report)
    dependencies(report)
    if report.get("phase") != 5 or report.get("compile_release") != 17 or report.get("containers_started") != 0:
        raise ValueError("Local execution identity differs")
    names = ("core-smoke", "compile-phase3", "compile-phase5", "compile-rewrite-jdk-only", "core-regression", "parser-regression",
             "api-regression", "legacy-h2-regression", "tx-policy-regression", "rewrite-policy", "rewrite-parser", "rewrite-jdbc", "equivalence-h2")
    steps = report.get("steps", [])
    if [s.get("name") for s in steps] != list(names):
        raise ValueError("Local contract inventory incomplete")
    for s in steps + [steps[1].get("observe_jdk_only_compile", {})]:
        if s.get("exit_code") != 0 or s.get("status") != "PASS" or s.get("child_reaped") is not True or s.get("process_group_quiesced") is not True:
            raise ValueError("Local child execution incomplete")
    counts = {s["name"]: s.get("assertions", 0) for s in steps}
    for name, minimum in (("core-regression", 74), ("parser-regression", 83), ("api-regression", 313),
                          ("tx-policy-regression", 123), ("rewrite-policy", 330), ("rewrite-parser", 147), ("rewrite-jdbc", 67)):
        if counts[name] < minimum:
            raise ValueError("Insufficient contract evidence")
    scenario(report.get("h2", {}))
    if report["h2"].get("source_sql_executed") is not False or steps[-1].get("output_sha512") != output_hash("H2", report["h2"]):
        raise ValueError("H2 protocol fields differ from executed output")
    legacy = report.get("legacy_h2", {})
    if (legacy.get("status") != "PASS" or legacy.get("checks") != 10 or legacy.get("cleanup") != "CONFIRMED"
            or legacy.get("scenarios") != {n: "PASS" for n in h.p4.phase3.CHECKS}):
        raise ValueError("Legacy regression incomplete")
    if report.get("prior_gate") != h.prior_gate():
        raise ValueError("Prior phase evidence changed")
    return {"status": "PASS", "policy_assertions": counts["rewrite-policy"], "parser_assertions": counts["rewrite-parser"],
            "jdbc_assertions": counts["rewrite-jdbc"], "h2_assertions": report["h2"]["assertions"]}


def verify(real, local):
    validated = verify_local(local)
    inputs(real)
    clean(real)
    dependencies(real)
    for field in ("source_sha512", "harness_sha512", "manifest_sha512", "configuration_sha512", "preservation_baseline_sha512"):
        if real[field] != local[field]:
            raise ValueError("Local and real inputs differ")
    expected_steps = ["compile-phase3", "compile-phase5", "compile-rewrite-jdk-only", "compile-real-phase5"]
    expected_steps += [step + n for n in PROFILES for step in ("image-config-", "equivalence-")]
    expected_steps += ["retention-" + n for n in PROFILES]
    if [s.get("name") for s in real.get("steps", [])] != expected_steps:
        raise ValueError("Actual compile/execution/retention steps incomplete")
    for s in real["steps"] + [real["steps"][0].get("observe_jdk_only_compile", {})]:
        if s.get("status") != "PASS" or s.get("exit_code") != 0 or s.get("child_reaped") is not True or s.get("process_group_quiesced") is not True:
            raise ValueError("Actual bounded child execution incomplete")
    extras = real.get("previous_phase5_retained_ids", [])
    required = 12 + len(extras)
    if (set(real.get("profiles", {})) != set(PROFILES) or real.get("checks") != 32 or real.get("containers_started") != 4
            or real.get("existing_resources_modified") != 0 or real.get("preserved_managed_instances") != required
            or not required <= real.get("retention_cap", 0) <= 16 or real.get("minimum_required_retention_cap") != required
            or len(real.get("existing_managed_ids", [])) != 8
            or len(set(real["existing_managed_ids"])) != 8):
        raise ValueError("Four actual dedicated targets required")
    images = {v["profile"]: v for v in json.loads((ROOT / "tools/g2-server-images.json").read_text())["images"]}
    driver_versions = json.loads((ROOT / "tools/g2-dependencies.json").read_text())["metadata_versions"]
    verify_driver_proof(real.get("driver_dependencies", {}))
    baseline_ids = {r["container_id"] for p in h.BASELINES for r in json.loads((ROOT / p).read_text())["profiles"].values()}
    if set(real["existing_managed_ids"]) != baseline_ids or set(extras) & baseline_ids or len(set(extras)) != len(extras):
        raise ValueError("Original preserved resource set differs")
    if any(not re.fullmatch(r"[a-f0-9]{64}", item) for item in real["existing_managed_ids"] + extras):
        raise ValueError("Original resource identities malformed")
    ids = set(); source = real["profiles"]["POSTGRESQL"].get("server_release_hash")
    for name in PROFILES:
        r = real["profiles"][name];scenario(r)
        steps = [s for s in real["steps"] if s.get("name") == "equivalence-" + name]
        if (len(steps) != 1 or steps[0].get("exit_code") != 0 or not steps[0].get("child_reaped") or not steps[0].get("process_group_quiesced")
                or r.get("container_stopped") is not True or r.get("data_preserved") is not True
                or r.get("image") != images[name]["image"] or r.get("platform") != images[name]["platform"]
                or not re.fullmatch(r"[a-f0-9]{64}", r.get("container_id", ""))
                or not re.fullmatch(r"[0-9]+\.[0-9]+", r.get("server_version", ""))
                or r.get("driver_version") != ".".join(driver_versions[name].split(".")[:2])
                or not re.fullmatch(r"[a-f0-9]{64}", r.get("server_release_hash", ""))
                or not re.fullmatch(r"[a-f0-9]{64}", r.get("driver_release_hash", ""))
                or r.get("source_release_hash") != source or r.get("source_sql_executed") is not (name == "POSTGRESQL")
                or r.get("retention", {}).get("state") != "exited" or r["retention"].get("oom_killed") is not False):
            raise ValueError("Target identity, source or retention incomplete")
        if steps[0].get("output_sha512") != output_hash(name, r, True):
            raise ValueError("Real protocol fields differ from executed output")
        health = r.get("health", {})
        if (health.get("exit_code") != 0 or not health.get("child_reaped") or not health.get("process_group_quiesced")
                or health.get("output_sha512") != hashlib.sha512(b"HEALTH=PASS\n").hexdigest()):
            raise ValueError("Actual JVM health proof missing")
        if name == "SQLSERVER":
            boot = r.get("bootstrap", {})
            if (boot.get("exit_code") != 0 or not boot.get("child_reaped") or not boot.get("process_group_quiesced")
                    or boot.get("output_sha512") != hashlib.sha512(b"HEALTH=PASS\n").hexdigest()):
                raise ValueError("SQL Server dedicated database bootstrap missing")
        retention_steps = [s for s in real["steps"] if s.get("name") == "retention-" + name]
        saved = r["retention"]
        transcript = f"{saved['state']} {saved['exit_code']} false {saved['image_id']} {saved['mount_count']}\n".encode()
        image_steps = [s for s in real["steps"] if s.get("name") == "image-config-" + name]
        image_output = f"{r.get('image_config_id')} {r.get('image_config_platform')}\n".encode()
        if (len(retention_steps) != 1 or retention_steps[0].get("exit_code") != 0 or not retention_steps[0].get("process_group_quiesced")
                or not retention_steps[0].get("child_reaped") or retention_steps[0].get("output_sha512") != hashlib.sha512(transcript).hexdigest()
                or not re.fullmatch(r"sha256:[a-f0-9]{64}", r.get("image_config_id", ""))
                or r.get("image_config_platform") != images[name]["platform"] or len(image_steps) != 1
                or image_steps[0].get("output_sha512") != hashlib.sha512(image_output).hexdigest()
                or saved["image_id"] != r["image_config_id"]):
            raise ValueError("Stopped resource proof differs")
        ids.add(r["container_id"])
    if (len(ids) != 4 or ids & (set(real["existing_managed_ids"]) | set(extras)) or len({r["result_digest"] for r in real["profiles"].values()}) != 1
            or real["profiles"]["POSTGRESQL"]["result_digest"] != local["h2"]["result_digest"]):
        raise ValueError("Source/target row equivalence differs")
    return {"schema_version": 1, "phase": 5, "gate": "G4", "status": "PASS", **{k: v for k, v in validated.items() if k != "status"},
            "real_database_scenarios": 32, "source": "POSTGRESQL", "targets": list(PROFILES),
            "result_digest": real["profiles"]["POSTGRESQL"]["result_digest"], "production_approval_issuance": "NOT GRANTED; test authority only",
            "preserved_stopped_instances": required, "automatic_cleanup_files": local["cleanup"]["temporary_files_removed"] + real["cleanup"]["temporary_files_removed"],
            "automatic_cleanup_bytes": local["cleanup"]["temporary_bytes_removed"] + real["cleanup"]["temporary_bytes_removed"],
            "scope": "fixed-fixture approved canonical equality/unique-key pagination; not general SQL or input equivalence",
            "native_sqlserver_boot_gradle_recovery_performance": "NOT RUN"}


def main():
    try:
        local, real, unit = [json.loads((ROOT / p).read_text()) for p in INPUTS]
        result = verify(real, local)
        old.check_files(unit.get("source_sha512", {}), {"tools/verify-phase5.py", "tools/test-phase5-verifier.py"}, ROOT)
        step = unit.get("step", {})
        if (unit.get("status") != "PASS" or unit.get("tests", 0) < 20 or unit.get("skipped", -1) != 0
                or step.get("exit_code") != 0 or not step.get("child_reaped") or not step.get("process_group_quiesced")
                or unit.get("cleanup", {}).get("status") != "PASS" or unit["cleanup"].get("temporary_directory_remaining") is not False):
            raise ValueError("Verifier contracts incomplete")
        result["execution_reports_sha512"] = h.hashes(INPUTS)
        result["verifier_sha512"] = h.guard.digest(Path(__file__).read_bytes())
        h.archive_save(ROOT / "evidence/PHASE5-GATE.json", result)
        print(json.dumps({"gate": "G4", "status": "PASS", "real_database_scenarios": 32}))
        return 0
    except Exception as error:
        print(json.dumps({"gate": "G4", "status": "NOT VERIFIED", "failure_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
