"""Build the optional SQL inventory schema review from local comparison inputs."""

import hashlib
import importlib.util
import json
from pathlib import Path


spec = importlib.util.spec_from_file_location("schema_migration", Path(__file__).with_name("schema-migration.py"))
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
schema = migration.schema
inventory = migration.inventory

FILENAME = "SCHEMA-REVIEW.json"
RECEIPT_FIELDS = {"schema_version", "status", "report_sha256", "test_id_hash", "target_schema_sha256",
                  "entry_point", "executed_queries", "sqlstate"}
REVIEW_FIELDS = {"schema_version", "base_schema", "head_schema", "dependencies",
                 "base_history", "manifest", "flyway_capture"}
CAPTURE_FIELDS = {"status", "revision", "scope"}


def path_parts(path, filename):
    if not isinstance(path, str):
        raise inventory.InvalidInventory()
    return schema.path_parts(path, filename)


def read_request(path):
    request = json.loads(
        inventory.read_bytes(path_parts(path, FILENAME)).decode("utf-8"),
        object_pairs_hook=inventory.unique_object, parse_constant=inventory.invalid_number,
        parse_float=inventory.invalid_number, parse_int=inventory.bounded_integer,
    )
    if not inventory.exact_fields(request, REVIEW_FIELDS) or type(request["schema_version"]) is not int \
            or request["schema_version"] != 1:
        raise inventory.InvalidInventory()
    capture = request["flyway_capture"]
    if not isinstance(capture, dict) or capture.get("status") not in (
            "VERIFIED", "EMPTY", "HISTORY_FILE_UNVERIFIED"):
        raise inventory.InvalidInventory()
    fields = CAPTURE_FIELDS if capture["status"] == "HISTORY_FILE_UNVERIFIED" else CAPTURE_FIELDS | {"history"}
    if not inventory.exact_fields(capture, fields):
        raise inventory.InvalidInventory()
    return request


def history_verdict(request, base, head):
    capture = request["flyway_capture"]
    if not all(isinstance(request[key], str) for key in ("base_history", "manifest")):
        raise inventory.InvalidInventory()
    history = migration.read_history(request["base_history"])
    manifest = migration.read_manifest(request["manifest"])
    if not (capture["revision"] == head["revision"] == manifest["revision"]
            and history["revision"] == base["revision"] == manifest["base_revision"]
            and capture["scope"] == head["scope"] == history["scope"] == manifest["scope"]):
        raise inventory.InvalidInventory()
    if capture["status"] == "HISTORY_FILE_UNVERIFIED":
        return {"status": "UNRESOLVED", "reasons": [capture["status"]]}
    if not isinstance(capture["history"], str):
        raise inventory.InvalidInventory()
    applied = migration.read_history(capture["history"])
    if len(applied["migrations"]) != (1 if capture["status"] == "VERIFIED" else 0):
        raise inventory.InvalidInventory()
    verdict = migration.build_report(base, head, history, applied, manifest)
    return {key: verdict[key] for key in ("status", "reasons")}


def build(path, base_inventory, head_inventory):
    request = read_request(path)
    base = schema.read_schema(path_parts(request["base_schema"], schema.SCHEMA_FILENAME))
    head_raw = inventory.read_bytes(path_parts(request["head_schema"], schema.SCHEMA_FILENAME))
    head = schema.parse_schema(head_raw)
    dependencies = schema.read_dependencies(path_parts(request["dependencies"], schema.DEPENDENCIES_FILENAME))
    if base["scope"] != base_inventory["profile"] or base["revision"] != base_inventory["revision"] \
            or head_inventory["schema_version"] != 2 or dependencies["schema_version"] != 2:
        raise inventory.InvalidInventory()
    impact = schema.build_report(base, head, head_inventory, dependencies)
    if len(impact["changes"]) != 1:
        raise inventory.InvalidInventory()
    history = history_verdict(request, base, head)
    complete = impact["status"] == "COMPLETE" and history["status"] == "MATCHED"
    return {"status": "COMPLETE" if complete else "INCOMPLETE", "change": impact["changes"][0],
            "head_schema_sha256": hashlib.sha256(head_raw).hexdigest(),
            "flyway_history": history, **{key: impact[key] for key in (
                "affected_queries", "impacted_test_ids", "coverage_reasons", "unresolved_queries")}}


def markdown(review):
    change, history = review["change"], review["flyway_history"]
    lines = ["", "## Schema change and Flyway history", "",
             f"Schema review **{review['status']}**",
             f"- Column change `{change['table']}.{change['column']}` `{change['kind']}`",
             f"- Flyway history **{history['status']}**"]
    if history["reasons"]:
        lines.append("- History reasons " + ", ".join(f"`{reason}`" for reason in history["reasons"]))
    lines += ["- Schema-impacted registered tests " + (
        ", ".join(f"`{test}`" for test in review["impacted_test_ids"]) or "none recorded")]
    for query in review["affected_queries"]:
        lines.append(f"  - {query['framework']} `{query['query_id_hash']}` " + (
            ", ".join(f"`{test}`" for test in query["test_ids"]) or "no verified test link"))
    reasons = sorted(set(review["coverage_reasons"]) | {
        reason for query in review["unresolved_queries"] for reason in query["reasons"]
    })
    if reasons:
        lines.append("- Impact evidence reasons " + ", ".join(f"`{reason}`" for reason in reasons))
    return lines


def replay_verdict(report, receipt, report_sha256):
    if receipt is None:
        return {"status": "UNVERIFIED", "reason": "RECEIPT_MISSING"}

    spec = importlib.util.spec_from_file_location(
        "schema_pr_regression", Path(__file__).with_name("schema-pr-regression.py"))
    registered = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(registered)
    if not (inventory.exact_fields(receipt, RECEIPT_FIELDS)
            and type(receipt["schema_version"]) is int and receipt["schema_version"] == 1
            and receipt["status"] == "PASS" and receipt["entry_point"] == registered.ENTRY_POINT
            and type(receipt["executed_queries"]) is int and receipt["executed_queries"] == 1
            and receipt["sqlstate"] == registered.EXPECTED_SQLSTATE
            and all(inventory.matches(receipt[key], inventory.HASH)
                    for key in ("report_sha256", "test_id_hash", "target_schema_sha256"))):
        return {"status": "UNVERIFIED", "reason": "INVALID_RECEIPT"}

    review = report["schema_review"]
    if not (report["status"] == review["status"] == "COMPLETE"
            and review["flyway_history"] == {"status": "MATCHED", "reasons": []}):
        return {"status": "UNVERIFIED", "reason": "INCOMPLETE_REPORT"}
    if receipt["report_sha256"] != report_sha256:
        return {"status": "UNVERIFIED", "reason": "REPORT_HASH_MISMATCH"}
    if receipt["test_id_hash"] != registered.TEST_ID_HASH or review["impacted_test_ids"] != [registered.TEST_ID_HASH]:
        return {"status": "UNVERIFIED", "reason": "TEST_HASH_MISMATCH"}
    if receipt["target_schema_sha256"] != review["head_schema_sha256"]:
        return {"status": "UNVERIFIED", "reason": "SCHEMA_HASH_MISMATCH"}
    return {"status": "VERIFIED", "result": receipt["status"],
            **{key: receipt[key] for key in RECEIPT_FIELDS - {"schema_version", "status"}}}


def replay_markdown(verdict):
    lines = ["", "## Registered replay", "", f"Replay evidence **{verdict['status']}**"]
    if verdict["status"] == "UNVERIFIED":
        lines.append(f"- Reason `{verdict['reason']}`")
        return lines
    return [*lines, f"- Result **{verdict['result']}**, SQLSTATE `{verdict['sqlstate']}`",
            f"- Executed queries {verdict['executed_queries']}",
            f"- Registered test `{verdict['test_id_hash']}`",
            f"- Entry point `{verdict['entry_point']}`",
            f"- Base report SHA-256 `{verdict['report_sha256']}`",
            f"- Target schema SHA-256 `{verdict['target_schema_sha256']}`"]


def attach_guarded_replay(base_json, base_markdown, receipt):
    """Render the base PR outputs with a receipt held by the same guarded replay."""
    report = json.loads(base_json)
    verdict = replay_verdict(report, receipt, hashlib.sha256(base_json).hexdigest())
    report["registered_replay"] = verdict
    markdown = base_markdown + "\n".join(replay_markdown(verdict)) + "\n"
    return report, markdown
