#!/usr/bin/env python3
"""Verify explicit order-column dependencies and replay the selected test on H2."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import sys
import tempfile


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "evidence/ORDER-SCHEMA-IMPACT-VALIDATION.json"
PILOT_EVIDENCE = ROOT / "evidence/ORDER-ADOPTION-PILOT-VALIDATION.json"
COLLECTOR = ROOT / "schema-regression/src/main/java/dev/udak/schema/SchemaSnapshotCollector.java"
FIXTURE = ROOT / "schema-regression/src/test/java/dev/udak/pilot/OrderSchemaImpactMain.java"
MAIN = "dev.udak.pilot.OrderSchemaImpactMain"
PLACEMENT = "order.place"
PLACEMENT_TEST = "case.order.place"
AUDIT_COUNT = "order.audit-count"
AUDIT_COUNT_TEST = "case.order.audit-count"
PLACED_ORDER_COLUMNS = tuple(("placed_order", column) for column in ("order_id", "sku_id", "units", "warehouse_id"))
STOCK_COLUMNS = tuple(("order_stock", column) for column in ("available", "sku_id", "warehouse_id"))
AUDIT_COLUMNS = (("order_audit", "event_code"), ("order_audit", "order_id"))
# ObserveDataSource also sees the order and stock statements beneath JPA and MyBatis.
DEPENDENCIES = {
    ("JPA", PLACEMENT): PLACED_ORDER_COLUMNS,
    ("MYBATIS", PLACEMENT): STOCK_COLUMNS,
    ("JDBC", PLACEMENT): PLACED_ORDER_COLUMNS + STOCK_COLUMNS + AUDIT_COLUMNS,
    ("JDBC", AUDIT_COUNT): (("order_audit", "order_id"),),
}


def load_pilot(pilot_root, approved):
    path = pilot_root / "tools/run-order-pilot.py"
    if path.resolve() != path or not path.is_file() or path.stat().st_size > 128 * 1024:
        raise ValueError("Unexpected pilot runner location")
    if hashlib.sha512(path.read_bytes()).hexdigest() != approved["pilot"]["runner_sha512"]:
        raise ValueError("Pilot runner differs from the verified revision")
    spec = importlib.util.spec_from_file_location("order_pilot", path)
    pilot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pilot)
    return pilot


def contracts(pilot, directory):
    schema = json.loads((directory / "SCHEMA-SNAPSHOT.json").read_bytes())
    inventory = json.loads((directory / "SQL-INVENTORY.json").read_bytes())
    if (inventory["profile"], inventory["revision"], inventory["dropped"]) != (
        schema["scope"], schema["revision"], 0,
    ):
        raise ValueError("Inventory capture does not match schema")
    expected = {
        (framework, pilot.inventory_hash("query", query)): [
            pilot.inventory_hash("test", PLACEMENT_TEST if query == PLACEMENT else AUDIT_COUNT_TEST)
        ]
        for framework, query in DEPENDENCIES
    }
    entries = inventory["entries"]
    observed = {(entry["framework"], entry["query_id_hash"]): entry["test_ids"] for entry in entries
                if entry["identity"] == "SCOPED" and entry["observed"] > 0
                and entry["unavailable"] == 0 and entry["shapes"]}
    if len(entries) != len(expected) or observed != expected:
        raise ValueError("Unexpected order query or test coverage")
    return {
        "schema_version": 1, "revision": schema["revision"], "scope": schema["scope"],
        "dependencies": [
            {"framework": framework, "query_id_hash": pilot.inventory_hash("query", query),
             "columns": [{"table": table, "column": column} for table, column in sorted(columns)]}
            for (framework, query), columns in sorted(DEPENDENCIES.items())
        ],
    }


def verify_report(pilot, payload, candidate):
    related = candidate == "related"
    expected_column = "event_code" if related else "fixture_note"
    width = {"type": "VARCHAR", "width": 16, "nullable": not related}
    if (payload["status"] != "COMPLETE" or payload["coverage_reasons"] or payload["unresolved_queries"]
            or payload["inventory_dropped"] != 0 or payload["base_revision"] != "1" * 40
            or payload["head_revision"] != ("2" if related else "3") * 40
            or payload["changes"] != [{"table": "order_audit", "column": expected_column, "kind": "WIDTH",
                                       "before": width, "after": {**width, "width": 32}}]):
        raise ValueError("Unexpected column comparison")
    selected = [pilot.inventory_hash("test", PLACEMENT_TEST)] if related else []
    affected = [{"framework": "JDBC", "query_id_hash": pilot.inventory_hash("query", PLACEMENT), "test_ids": selected}]
    if payload["impacted_test_ids"] != selected or payload["affected_queries"] != (affected if related else []):
        raise ValueError("Unexpected test selection")
    return {"status": payload["status"], "change": payload["changes"][0], "affected_queries": payload["affected_queries"],
            "impacted_test_ids": selected}


def assertions(output, protocol):
    if (count := re.fullmatch(protocol + r" PASS\nASSERTIONS=([1-9][0-9]{0,4})\n", output)) is None:
        raise ValueError("Fixture protocol invalid")
    return int(count[1])


def validate(result, pilot, phase3, approved):
    guard = phase3.guard
    with guard.workspace("udak-order-schema-impact-") as (work, cleanup):
        result["cleanup"] = cleanup
        guard.ROOT = work
        os.environ["TMPDIR"] = str(work)
        for key in ("_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "JDK_JAVAC_OPTIONS", "CLASSPATH"):
            os.environ.pop(key, None)
        (work / "empty").mkdir()

        def run(name, command, **options):
            return pilot.run_step(guard, result, work, name, command, **options)

        sources = pilot.java_sources(pilot.ROOT, pilot.BASELINE_ROOTS)
        recorded = approved["baseline"]
        result["pilot_revision"] = pilot.git_baseline(run, sources, recorded["baseline_revision"])
        result["pilot_source_sha512"] = pilot.hashes(pilot.ROOT, sources)
        if result["pilot_source_sha512"] != recorded["application_input_sha512"]:
            raise ValueError("Order source differs from the verified baseline")
        observe_sources = pilot.java_sources(ROOT, (pilot.OBSERVE_ROOT,))
        adapters = pilot.java_sources(ROOT, pilot.ADAPTER_ROOTS)
        cli = ROOT / "tools/schema-impact.py"
        files = [COLLECTOR, FIXTURE, cli, Path(__file__), *observe_sources, *adapters,
                 *(ROOT / name for name in ("tools/run-phase1.py", "tools/run-phase3.py", "tools/run-core-smoke.sh",
                                             "tools/sql-inventory.py", "tools/test-schema-impact.py",
                                             "tools/phase3-dependencies.json"))]
        result["udak_input_sha512"] = pilot.hashes(ROOT, files)
        result["stage"] = "pinned-dependencies"
        jars, dependencies = phase3.dependencies(work)
        result["dependency_manifest_sha512"] = dependencies["manifest_sha512"]
        if result["dependency_manifest_sha512"] != recorded["dependency_manifest_sha512"]:
            raise ValueError("Dependencies differ from the verified baseline")

        app = pilot.compile_sources(run, work, "compile-order-baseline", sources, jars)
        observe = pilot.compile_sources(run, work, "compile-observe-core", observe_sources, [])
        product = pilot.compile_sources(run, work, "compile-inventory-and-collector", [*adapters, COLLECTOR], [observe, *jars])
        dependencies = [app, observe, product, *jars]
        fixture = pilot.compile_sources(run, work, "compile-schema-impact-fixture", [FIXTURE], dependencies)
        for name in ("base", "related", "control"):
            (work / name).mkdir()
        output = run("capture-order-schema", pilot.java_command(work, [fixture, *dependencies], MAIN, "capture", work),
                     timeout=45, capture=True)
        result["capture_assertions"] = assertions(output, "ORDER_SCHEMA_CAPTURE")
        result["comparisons"] = {}
        result["dependency_manifests"] = {}
        for candidate in ("related", "control"):
            directory = work / candidate
            manifest = contracts(pilot, directory)
            result["dependency_manifests"][candidate] = manifest
            (directory / "QUERY-DEPENDENCIES.json").write_text(json.dumps(manifest) + "\n")
            output = run(f"impact-{candidate}", [sys.executable, "-B", str(cli),
                         "--base", "base/SCHEMA-SNAPSHOT.json", "--head", f"{candidate}/SCHEMA-SNAPSHOT.json",
                         "--inventory", f"{candidate}/SQL-INVENTORY.json",
                         "--dependencies", f"{candidate}/QUERY-DEPENDENCIES.json"], capture=True)
            result["comparisons"][candidate] = verify_report(pilot, json.loads(output), candidate)

        # Dispatch the single verified, allowlisted selection on a fresh related schema.
        schema_hash = hashlib.sha512((work / "related/SCHEMA-SNAPSHOT.json").read_bytes()).hexdigest()
        output = run("replay-selected-order-test",
                     pilot.java_command(work, [fixture, *dependencies], MAIN, "replay-related", schema_hash),
                     timeout=45, capture=True)
        result["selected_order_test"] = {"status": "PASS", "assertions": assertions(output, "ORDER_SCHEMA_REPLAY"),
                                         "test_ids": result["comparisons"]["related"]["impacted_test_ids"],
                                         "matched_schema_sha512": schema_hash}
        output = run("reject-replay-schema-mismatch",
                     pilot.java_command(work, [fixture, *dependencies], MAIN, "replay-related", "0" * 128),
                     expected=1, capture=True)
        if output.splitlines() != ["ORDER_SCHEMA_REPLAY FAIL", "CATEGORY=AssertionError", "CHECK=REPLAY_SCHEMA"]:
            raise ValueError("Replay schema mismatch was not rejected")
        output = run("schema-impact-contract", [sys.executable, "-B", str(ROOT / "tools/test-schema-impact.py")], capture=True)
        result["schema_impact_contract_tests"] = int(re.search(r"\nRan ([1-9][0-9]*) tests? in .*\n\nOK\n$", output)[1])
        run("core-smoke", ["/usr/bin/env", "_JAVA_OPTIONS=" + " ".join(pilot.JAVA_OPTIONS),
                           str(ROOT / "tools/run-core-smoke.sh")])
        if (result["pilot_source_sha512"] != pilot.hashes(pilot.ROOT, sources)
                or result["udak_input_sha512"] != pilot.hashes(ROOT, files)):
            raise ValueError("Execution inputs changed during the run")
    if cleanup.get("status") != "PASS" or cleanup.get("temporary_directory_remaining") is not False:
        raise ValueError("Workspace cleanup incomplete")


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--pilot-root", type=Path, default=ROOT.parent / "udak-legacy-order-service-test")
    args = parser.parse_args()
    result = {"schema_version": 1, "requirement": "NEXT-004", "status": "FAIL", "stage": "load-pilot", "steps": [],
              "scope": "INDEPENDENT_SYNTHETIC_H2_ORDER_SCHEMA_IMPACT", "external_db_integration": "NOT RUN",
              "containers_started": 0, "java_compile_release": 17}
    try:
        approved = json.loads(PILOT_EVIDENCE.read_bytes())
        pilot = load_pilot(args.pilot_root.resolve(strict=True), approved)
        phase3 = pilot.load_phase3(ROOT)
        result["limits"] = pilot.LIMITS
        for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
            signal.signal(event, phase3.guard.interrupted)
        signal.alarm(pilot.LIMITS["wall_seconds"])
        validate(result, pilot, phase3, approved)
        result["stage"] = "save-evidence"
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=REPORT.parent, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                json.dump({**result, "status": "PASS", "stage": "complete"}, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.close()
                temporary.replace(REPORT)
            finally:
                temporary.unlink(missing_ok=True)
        result.update(status="PASS", stage="complete")
    except Exception as failure:
        result["failure_type"] = type(failure).__name__
    finally:
        signal.alarm(0)
    print(json.dumps({key: value for key, value in result.items() if not key.endswith("_sha512") and
                      key not in ("steps", "dependency_manifests")}))
    return int(result["status"] != "PASS")


if __name__ == "__main__":
    sys.exit(main())
