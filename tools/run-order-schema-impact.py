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
MIGRATION_REPORT = ROOT / "evidence/ORDER-MIGRATION-HISTORY-VALIDATION.json"
DEPENDENCY_REPORT = ROOT / "evidence/ORDER-DEPENDENCY-EXTRACTION-VALIDATION.json"
PILOT_EVIDENCE = ROOT / "evidence/ORDER-ADOPTION-PILOT-VALIDATION.json"
COLLECTOR = ROOT / "schema-regression/src/main/java/dev/udak/schema/SchemaSnapshotCollector.java"
FIXTURE = ROOT / "schema-regression/src/test/java/dev/udak/pilot/OrderSchemaImpactMain.java"
MIGRATION_FIXTURE = FIXTURE.with_name("OrderMigrationHistoryMain.java")
MIGRATION_SQL = ROOT / "schema-regression/src/test/resources/order-migrations/V002-WIDEN-AUDIT-EVENT-CODE.sql"
MIGRATION_SHA256 = "073902185c299e63faa30d98263cfc5407b7d463492189e66c8cf1aab84d3737"
MIGRATION_CLI = ROOT / "tools/schema-migration.py"
MIGRATION_TEST = ROOT / "tools/test-schema-migration.py"
DEPENDENCY_CLI = ROOT / "tools/sql-dependencies.py"
DEPENDENCY_TEST = ROOT / "tools/test-sql-dependencies.py"
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


def verify_migration_history(result, pilot, run, work, classpath):
    fixture = pilot.compile_sources(run, work, "compile-migration-history-fixture", [MIGRATION_FIXTURE], classpath)
    if hashlib.sha256(MIGRATION_SQL.read_bytes()).hexdigest() != MIGRATION_SHA256:
        raise ValueError("Migration bytes differ from the reviewed file")
    snapshots = {"base": "base", "matched": "related", "missing": "related", "unrelated": "control"}
    for name in snapshots:
        (work / f"history-{name}").mkdir()
    output = run("capture-migration-history", pilot.java_command(work, [fixture, *classpath],
                 "dev.udak.pilot.OrderMigrationHistoryMain", work, MIGRATION_SQL), timeout=45, capture=True)
    count = assertions(output, "ORDER_MIGRATION_HISTORY")
    for name, reference in snapshots.items():
        filename = "SCHEMA-SNAPSHOT.json"
        if (work / f"history-{name}" / filename).read_bytes() != (work / reference / filename).read_bytes():
            raise ValueError("Migration scenario differs from the prior schema comparison")
    # Build the reviewed digest from the order-impact oracle, independently of the history scenarios.
    reviewed = [result["comparisons"]["related"]["change"]]
    encoded = json.dumps(reviewed, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    expected_changes = hashlib.sha256(encoded).hexdigest()
    expected = {"version": "2", "checksum_sha256": MIGRATION_SHA256}
    outcomes = {}
    for name, reasons in (("matched", []), ("missing", ["HISTORY_MISSING"]), ("unrelated", ["CHANGE_MISMATCH"])):
        head = f"history-{name}"
        schema = json.loads((work / head / "SCHEMA-SNAPSHOT.json").read_bytes())
        manifest = {"schema_version": 1, "base_revision": "1" * 40, "revision": schema["revision"],
                    "scope": schema["scope"], **expected, "expected_changes_sha256": expected_changes}
        (work / head / "MIGRATION-MANIFEST.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        output = run(f"migration-{name}", [sys.executable, "-B", str(MIGRATION_CLI),
                     "--base", "history-base/SCHEMA-SNAPSHOT.json", "--head", f"{head}/SCHEMA-SNAPSHOT.json",
                     "--base-history", "history-base/MIGRATION-HISTORY.json",
                     "--head-history", f"{head}/MIGRATION-HISTORY.json",
                     "--manifest", f"{head}/MIGRATION-MANIFEST.json"], expected=2 if reasons else 0, capture=True)
        report = json.loads(output)
        if (report["status"] != ("UNRESOLVED" if reasons else "MATCHED") or report["reasons"] != reasons
                or report["observed_changes"] != [result["comparisons"][snapshots[name]]["change"]]
                or report["expected_migration"] != expected
                or report["expected_changes_sha256"] != expected_changes
                or report["newly_applied"] != ([] if name == "missing" else [expected])):
            raise ValueError("Unexpected migration attribution result")
        outcomes[name] = report
    output = run("schema-migration-contract", [sys.executable, "-B", str(MIGRATION_TEST)], capture=True)
    return {
        "capture_assertions": count, "cases": outcomes,
        "contract_tests": int(re.search(r"\nRan ([1-9][0-9]*) tests? in .*\n\nOK\n$", output)[1]),
    }


def declared_sql(path, pattern):
    matches = re.findall(pattern, path.read_text(encoding="utf-8"), re.DOTALL)
    if len(matches) != 1:
        raise ValueError("Expected one SQL declaration in the verified source")
    return matches[0]


def dependency_inputs(pilot):
    spec = importlib.util.spec_from_file_location("sql_dependencies", DEPENDENCY_CLI)
    extractor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extractor)
    service = pilot.ROOT / "src/main/java/dev/udak/pilot/OrderService.java"
    return extractor, {
        "audit_count": declared_sql(FIXTURE, r'jdbc\(observed\)\.queryForObject\(\s*"([^"\\\r\n]+)"'),
        "audit_insert": declared_sql(service, r'jdbc\.update\(\s*"([^"\\\r\n]+)"'),
        "mybatis_template": declared_sql(service, r'@Update\(\s*"""(.*?)"""\)'),
        "ambiguous_join": ("SELECT COUNT(order_id) FROM placed_order JOIN order_audit "
                           "ON placed_order.order_id = order_audit.order_id"),
    }


def impact_command(candidate, dependencies):
    return [sys.executable, "-B", str(ROOT / "tools/schema-impact.py"),
            "--base", "base/SCHEMA-SNAPSHOT.json", "--head", f"{candidate}/SCHEMA-SNAPSHOT.json",
            "--inventory", f"{candidate}/SQL-INVENTORY.json", "--dependencies", dependencies]


def verify_dependency_extraction(pilot, run, work, candidate, manifest, inputs):
    extractor, statements = inputs
    directory = work / candidate
    schema = json.loads((directory / "SCHEMA-SNAPSHOT.json").read_bytes())
    known = {(column["table"], column["column"]) for column in schema["columns"]}
    extracted = {key: extractor.extract_dependencies(sql, known) for key, sql in statements.items()}
    placement_id = pilot.inventory_hash("query", PLACEMENT)
    audit_count_id = pilot.inventory_hash("query", AUDIT_COUNT)
    rows = {(entry["framework"], entry["query_id_hash"]): entry for entry in manifest["dependencies"]}
    count = rows["JDBC", audit_count_id]
    placement = rows["JDBC", placement_id]

    def column_pairs(columns):
        return {(column["table"], column["column"]) for column in columns}

    carried_columns = column_pairs(rows["JPA", placement_id]["columns"]) | column_pairs(
        rows["MYBATIS", placement_id]["columns"])
    for key, expected in (("audit_count", column_pairs(count["columns"])),
                          ("audit_insert", column_pairs(placement["columns"]) - carried_columns)):
        if extracted[key]["status"] != "RESOLVED" or column_pairs(extracted[key]["columns"]) != expected:
            raise ValueError("Static dependency differs from the reviewed manifest")
    for key, reason in (("mybatis_template", "DYNAMIC_SQL"), ("ambiguous_join", "UNSUPPORTED_SQL")):
        if extracted[key] != {"status": "UNRESOLVED", "reason": reason, "columns": []}:
            raise ValueError("Unverified SQL received dependencies")

    count["columns"] = extracted["audit_count"]["columns"]
    automatic = directory / "automatic-only"
    automatic.mkdir()
    (automatic / "QUERY-DEPENDENCIES.json").write_text(json.dumps({**manifest, "dependencies": [count]}) + "\n")
    output = run(f"automatic-only-{candidate}", impact_command(
        candidate, f"{candidate}/automatic-only/QUERY-DEPENDENCIES.json"), expected=2, capture=True)
    incomplete = json.loads(output)
    expected_unresolved = [{"framework": framework, "identity": "SCOPED", "query_id_hash": placement_id,
                            "reasons": ["MISSING_DEPENDENCIES"]} for framework in ("JDBC", "JPA", "MYBATIS")]
    if (incomplete["status"] != "INCOMPLETE" or incomplete["unresolved_queries"] != expected_unresolved
            or incomplete["coverage_reasons"] or incomplete["affected_queries"] or incomplete["impacted_test_ids"]):
        raise ValueError("Automatic-only coverage was overstated")

    # Add the verified audit write to the already reviewed order and stock dependencies.
    placement["columns"] = [{"table": table, "column": column}
                            for table, column in sorted(carried_columns | column_pairs(extracted["audit_insert"]["columns"]))]
    return {"resolved_static_statements": 2, "static_statements_checked": 2,
            "fully_automatic_entries": 1, "inventory_entries": len(rows),
            "automatic_only_status": incomplete["status"], "automatic_only_unresolved_queries": len(expected_unresolved),
            "statement_results": extracted}


def validate(result, pilot, phase3, approved, *, migration_history=False, dependency_extraction=False):
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
        if migration_history:
            files += [MIGRATION_FIXTURE, MIGRATION_SQL, MIGRATION_CLI, MIGRATION_TEST]
        if dependency_extraction:
            files += [DEPENDENCY_CLI, DEPENDENCY_TEST]
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
        extraction = dependency_inputs(pilot) if dependency_extraction else None
        if extraction is not None:
            result["dependency_extraction"] = {}
        for candidate in ("related", "control"):
            directory = work / candidate
            manifest = contracts(pilot, directory)
            if extraction is not None:
                result["dependency_extraction"][candidate] = verify_dependency_extraction(
                    pilot, run, work, candidate, manifest, extraction)
            result["dependency_manifests"][candidate] = manifest
            (directory / "QUERY-DEPENDENCIES.json").write_text(json.dumps(manifest) + "\n")
            output = run(f"impact-{candidate}", impact_command(candidate, f"{candidate}/QUERY-DEPENDENCIES.json"), capture=True)
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
        if migration_history:
            result["migration_history"] = verify_migration_history(result, pilot, run, work, dependencies)
        if dependency_extraction:
            output = run("sql-dependency-contract", [sys.executable, "-B", str(DEPENDENCY_TEST)], capture=True)
            result["sql_dependency_contract_tests"] = int(re.search(r"\nRan ([1-9][0-9]*) tests? in .*\n\nOK\n$", output)[1])
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
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--migration-history", action="store_true", help="Verify migration history and observed changes")
    modes.add_argument("--dependency-extraction", action="store_true", help="Compare extracted and reviewed dependencies")
    args = parser.parse_args()
    result = {"schema_version": 1, "requirement": "NEXT-004", "status": "FAIL", "stage": "load-pilot", "steps": [],
              "scope": "INDEPENDENT_SYNTHETIC_H2_ORDER_SCHEMA_IMPACT", "external_db_integration": "NOT RUN",
              "containers_started": 0, "java_compile_release": 17}
    report = MIGRATION_REPORT if args.migration_history else REPORT
    if args.migration_history:
        result["scope"] = "INDEPENDENT_SYNTHETIC_H2_ORDER_MIGRATION_HISTORY"
    if args.dependency_extraction:
        report = DEPENDENCY_REPORT
        result["scope"] = "INDEPENDENT_SYNTHETIC_H2_ORDER_DEPENDENCY_EXTRACTION"
    try:
        approved = json.loads(PILOT_EVIDENCE.read_bytes())
        pilot = load_pilot(args.pilot_root.resolve(strict=True), approved)
        phase3 = pilot.load_phase3(ROOT)
        result["limits"] = pilot.LIMITS
        for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
            signal.signal(event, phase3.guard.interrupted)
        signal.alarm(pilot.LIMITS["wall_seconds"])
        validate(result, pilot, phase3, approved, migration_history=args.migration_history,
                 dependency_extraction=args.dependency_extraction)
        result["stage"] = "save-evidence"
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=report.parent, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                json.dump({**result, "status": "PASS", "stage": "complete"}, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.close()
                temporary.replace(report)
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
