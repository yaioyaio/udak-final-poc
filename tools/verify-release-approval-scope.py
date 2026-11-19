#!/usr/bin/env python3
"""Verify the bounds of the proposed G0 and G5 scopes using local evidence."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
SCOPE = "tools/phase6-approval-scope.json"
CANDIDATE = "evidence/PHASE6-VALIDATION.json"
SUPPORT = "evidence/RELEASE-SUPPORT-APPROVAL.json"
REPORT = "evidence/RELEASE-APPROVAL-SCOPE.json"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = load("approval_scope_cli", "udak-cli/udak_cli.py")
h = load("approval_scope_harness", "tools/run-phase6.py")
INPUTS = (
    SCOPE, CANDIDATE, SUPPORT, cli.POLICY, cli.DEPENDENCY_PINS,
    "tools/schema-native.py", "tools/run-schema-regression.py", "tools/run-release-support.py",
    "tools/run-core-smoke.sh", "tools/run-phase6.py", "tools/release-gate.py",
    "tools/verify-release-approval-scope.py", "udak-cli/udak_cli.py",
)
EXCLUSIONS = ["database-images", "demo-fat-jar", "jdbc-drivers", "testkits", "third-party-jars"]
EXTENSIONS = (".jar", ".pom", ".module", "-sources.jar", "-javadoc.jar")
METADATA = ("SBOM.json", "NOTICE.txt", "API-COMPATIBILITY.json", "CANDIDATE.json", "CHECKSUMS.sha512")
SERVER_VERSIONS = {"POSTGRESQL": r"17\.[0-9]+", "MYSQL": r"8\.0\.[0-9]+"}
G5_LIMITS = {
    "max_active_databases": 1,
    "max_in_flight": 2,
    "max_starts_per_second": 4,
    "min_start_spacing_ms": 250,
    "max_starts_per_database": 48,
    "max_wall_seconds": 300,
    "startup_seconds": 60,
    "server_seconds": 150,
    "db_processes": 48,
    "db_rss_bytes": 1024 * 1024**2,
    "db_scratch_bytes": 768 * 1024**2,
    "child_cpu_seconds": 90,
    "jvm_heap_mib": 256,
    "jvm_active_cpus": 2,
    "child_log_bytes": 16 * 1024**2,
}
RUNTIME_LIMITS = {
    "startup_limit_seconds": "startup_seconds", "server_limit_seconds": "server_seconds",
    "rss_limit_bytes": "db_rss_bytes", "data_limit_bytes": "db_scratch_bytes",
    "cpu_limit_seconds": "child_cpu_seconds",
}
SUPPORT_LIMITS = {
    "database_parallelism": "max_active_databases", "wall_seconds": "max_wall_seconds",
    "jvm_heap_mib": "jvm_heap_mib", "jvm_active_cpus": "jvm_active_cpus",
}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def exact_integer(value, expected):
    return type(value) is int and value == expected


def match_limits(baseline, names, limits):
    return isinstance(baseline, dict) and all(
        exact_integer(baseline.get(field), limits[limit]) for field, limit in names.items()
    )


def verify_g0(g0, version, candidate):
    modules = sorted(cli.RELEASE_MODULES)
    require(g0 == {
        "proposed_license": "Apache-2.0", "group": "dev.udak", "modules": modules,
        "binary_exclusions": EXCLUSIONS, "source_scope": "UDAK-OWNED-WITH-THIRD-PARTY-NOTICES",
    }, "G0_SCOPE")
    group_path = g0["group"].replace(".", "/")
    packages = {
        f"build/phase6/repository/{group_path}/{module}/{version}/{module}-{version}{extension}"
        for module in g0["modules"] for extension in EXTENSIONS
    }
    metadata = {f"build/phase6/{name}" for name in METADATA}
    inventory = cli.artifact_inventory(candidate)
    require(len(packages) == 30 and len(metadata) == 5 and len(inventory) == 35
            and inventory.keys() == packages | metadata, "CANDIDATE_ARTIFACTS")
    return {
        "decision": "PENDING", "proposed_license": g0["proposed_license"],
        "coordinates": [f"{g0['group']}:{module}:{version}" for module in modules],
        "source_scope": g0["source_scope"], "binary_exclusions": list(EXCLUSIONS),
        "package_artifacts": len(packages), "metadata_artifacts": len(metadata),
    }


def verify_g5(g5, support):
    require(isinstance(g5, dict) and g5.keys() == G5_LIMITS.keys() | {"profiles"}
            and all(exact_integer(g5[field], limit) for field, limit in G5_LIMITS.items()), "G5_SCOPE")
    require(g5["min_start_spacing_ms"] * g5["max_starts_per_second"] == 1000
            and g5["max_in_flight"] <= g5["max_starts_per_database"]
            and (g5["max_starts_per_database"] - 1) * g5["min_start_spacing_ms"] < 1000 * g5["server_seconds"]
            and g5["startup_seconds"] < g5["server_seconds"] <= g5["max_wall_seconds"], "G5_WORKLOAD_RELATION")
    require(support.get("status") == "PASS" and support.get("requirement") == "RELEASE-002"
            and exact_integer(support.get("docker_containers_started"), 0)
            and isinstance(support.get("not_run"), list) and "G5" in support["not_run"]
            and match_limits(support.get("limits"), SUPPORT_LIMITS, g5), "NATIVE_SUPPORT")
    cleanup = support.get("cleanup")
    require(isinstance(cleanup, dict) and cleanup.get("status") == "PASS"
            and cleanup.get("remaining") is False, "NATIVE_CLEANUP")
    profiles = g5["profiles"]
    baseline = support.get("profiles")
    require(isinstance(profiles, dict) and isinstance(baseline, dict)
            and profiles.keys() == baseline.keys() == SERVER_VERSIONS.keys(), "NATIVE_PROFILES")
    for name, server_pattern in SERVER_VERSIONS.items():
        row = baseline[name]
        require(isinstance(row, dict) and row.get("status") == "PASS"
                and row.get("fixture_table_cleanup") == "CONFIRMED", "NATIVE_PROFILE")
        server, driver = row.get("server_version"), row.get("driver_version")
        require(isinstance(server, str) and re.fullmatch(server_pattern, server)
                and isinstance(driver, str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", driver)
                and profiles[name] == {"server_version": server, "driver_version": driver}, "NATIVE_VERSION")
        runtime = row.get("native_runtime")
        require(match_limits(runtime, RUNTIME_LIMITS, g5)
                and runtime.get("version") == server and runtime.get("profile") == name.lower()
                and runtime.get("provider") == "native"
                and all(runtime.get(field) is True for field in (
                    "private_directory", "loopback_listener_owned", "server_stopped", "process_groups_quiesced",
                )), "NATIVE_RUNTIME")
    return {
        "decision": "PENDING", "execution": "NOT RUN",
        "profiles": {name: dict(profiles[name]) for name in SERVER_VERSIONS},
        "limits": dict(G5_LIMITS),
    }


def verify_scope(scope, candidate, support):
    """Return the verified metadata or raise ValueError for an invalid scope."""
    require(all(isinstance(data, dict) and exact_integer(data.get("schema_version"), 1)
                for data in (scope, candidate, support)), "SCHEMA")
    require(scope.keys() == {"schema_version", "candidate_version", "g0", "g5"}
            and scope["candidate_version"] == cli.VERSION, "PROPOSAL")
    require(candidate.get("status") == "PASS" and exact_integer(candidate.get("phase"), 6)
            and candidate.get("authorize_publish") is False
            and exact_integer(candidate.get("containers_started"), 0)
            and exact_integer(candidate.get("external_publications"), 0), "CANDIDATE_STATUS")
    return {
        "candidate_version": cli.VERSION, "candidate_artifacts": 35,
        "g0": verify_g0(scope["g0"], cli.VERSION, candidate), "g5": verify_g5(scope["g5"], support),
    }


def input_hashes(root_fd):
    result = {}
    for path in INPUTS:
        with cli.regular_file(root_fd, path, cli.MAX_JSON_BYTES) as (stream, size):
            raw = stream.read(size + 1)
            require(len(raw) == size, "INPUT_CHANGED")
        result[path] = hashlib.sha512(raw).hexdigest()
    return result


def check_step(receipt, expected):
    require(receipt.get("status") == "PASS" and exact_integer(receipt.get("exit_code"), expected)
            and receipt.get("child_reaped") is True and receipt.get("process_group_quiesced") is True
            and cli.valid_digest(receipt.get("output_sha512")), "FIXTURE_STEP")


def check_gate(work):
    receipt = h.step("publication-gate", [sys.executable, "-B", "tools/release-gate.py", "--format", "json"],
                     work, timeout=25, expected=2)
    check_step(receipt, 2)
    with cli.directory(work.parts[1:]) as fd:
        with cli.regular_file(fd, "publication-gate.output", 16 * 1024) as (stream, size):
            raw = stream.read(size + 1)
            require(len(raw) == size and hashlib.sha512(raw).hexdigest() == receipt["output_sha512"],
                    "GATE_OUTPUT_CHANGED")
    gate = json.loads(raw, object_pairs_hook=cli.unique_object)
    require(isinstance(gate, dict) and gate.get("status") == "BLOCKED"
            and gate.get("authorize_publish") is False and gate.get("phase6_evidence") == "VERIFIED_EVIDENCE"
            and gate.get("candidate_artifacts") in ("NOT AVAILABLE", "VERIFIED")
            and gate.get("operator_approvals") in ("MISSING", "UNVERIFIED")
            and gate.get("blockers") == cli.BLOCKING_POLICY and "error" not in gate, "RELEASE_GATE")
    return receipt, {key: gate[key] for key in (
        "status", "authorize_publish", "phase6_evidence", "candidate_artifacts", "operator_approvals", "blockers",
    )}


def save_report(root_fd, report):
    """Atomically replace this verifier's receipt after every check passes."""
    try:
        with cli.regular_file(root_fd, REPORT, cli.MAX_JSON_BYTES):
            pass
    except FileNotFoundError:
        pass
    with cli.directory(["evidence"], root_fd=root_fd) as out:
        name = Path(REPORT).name
        temporary = name + "." + os.urandom(8).hex() + ".tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=out)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as writer:
                json.dump(report, writer, indent=2)
                writer.write("\n")
            os.replace(temporary, name, src_dir_fd=out, dst_dir_fd=out)
        finally:
            try:
                os.unlink(temporary, dir_fd=out)
            except FileNotFoundError:
                pass


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args:
        print("RELEASE_APPROVAL_SCOPE INVALID_ARGUMENTS")
        return 2
    events = (signal.SIGINT, signal.SIGTERM, signal.SIGALRM)
    previous_handlers = {event: signal.signal(event, h.guard.interrupted) for event in events}
    signal.alarm(90)
    try:
        with cli.directory(ROOT.parts[1:]) as root_fd:
            inputs = input_hashes(root_fd)
            baseline = cli.read_report(root_fd, SUPPORT, expected_digest=inputs[SUPPORT])
            native_inputs = baseline.get("input_sha512")
            require(isinstance(native_inputs, dict) and all(native_inputs.get(path) == inputs[path] for path in (
                "tools/schema-native.py", "tools/run-schema-regression.py", "tools/run-release-support.py",
            )), "NATIVE_BASELINE_CHANGED")
            verified = verify_scope(cli.read_report(root_fd, SCOPE, expected_digest=inputs[SCOPE]),
                                    cli.read_report(root_fd, CANDIDATE, expected_digest=inputs[CANDIDATE]), baseline)
            with h.workspace() as (work, cleanup):
                gate_step, gate = check_gate(work)
                jvm = "_JAVA_OPTIONS=-Xmx256m -XX:MaxMetaspaceSize=128m -XX:ActiveProcessorCount=2"
                core_step = h.step("core-smoke", ["/usr/bin/env", jvm, "./tools/run-core-smoke.sh"], work, timeout=25)
                check_step(core_step, 0)
            require(cleanup.get("status") == "PASS" and cleanup.get("temporary_directory_remaining") is False,
                    "FIXTURE_CLEANUP")
            require(input_hashes(root_fd) == inputs, "INPUT_CHANGED")
            save_report(root_fd, {
                "schema_version": 1, "status": "PASS", **verified, "formal_release": "BLOCKED",
                "authorize_publish": False, "external_publications": 0, "containers_started": 0,
                "native_databases_started": 0, "g5_workloads_started": 0, "performance_or_load_tests_started": 0,
                "publication_gate": gate, "steps": [gate_step, core_step], "cleanup": cleanup,
                "input_sha512": inputs,
            })
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError):
        print("RELEASE_APPROVAL_SCOPE NOT_VERIFIED")
        return 1
    finally:
        signal.alarm(0)
        for event, handler in previous_handlers.items():
            signal.signal(event, handler)
    print("RELEASE_APPROVAL_SCOPE PASS | G0 PENDING | G5 PENDING | FORMAL_RELEASE BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
