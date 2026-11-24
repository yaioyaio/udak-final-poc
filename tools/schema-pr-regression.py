"""Plan the registered ThingsBoard replay from a guarded schema review in the pilot."""

import hashlib


ENTRY_POINT = "THINGSBOARD_14036_DEVICE_PROFILE"


def plan(report, head_snapshot, registration, expected_change):
    review = report["schema_review"]
    affected = review["impacted_test_ids"]
    registered_test = registration["test_id_hash"]
    registered_query = registration["query_id_hash"]
    reasons = []
    if report["status"] != "COMPLETE" or review["status"] != "COMPLETE":
        reasons.append("INCOMPLETE_REPORT")
    if review["flyway_history"] != {"status": "MATCHED", "reasons": []}:
        reasons.append("HISTORY_UNRESOLVED")
    if report.get("fingerprint_test_status") != "COMPARABLE" or review["coverage_reasons"] or review["unresolved_queries"]:
        reasons.append("INCOMPLETE_IMPACT_EVIDENCE")
    if affected != [registered_test]:
        reasons.append("UNKNOWN_TEST_HASH" if any(test != registered_test for test in affected)
                       else "REGISTRATION_MISMATCH")
    queries = [query for query in report["queries"]
               if (query["framework"], query["identity"], query["query_id_hash"]) == (
                   "JDBC", "SCOPED", registered_query)]
    head = queries[0].get("head") if len(queries) == 1 else None
    expected_query = {"framework": "JDBC", "query_id_hash": registered_query, "test_ids": [registered_test]}
    if affected == [registered_test] and (
            review["affected_queries"] != [expected_query] or not head
            or head["test_ids"] != [registered_test]
            or head["shapes"] != [{"fingerprint_hash": registration["head_fingerprint_hash"], "statement_kind": "SELECT"}]
            or head["observed"] < 1 or head["unavailable"] != 0):
        reasons.append("REGISTRATION_MISMATCH")
    if review["change"] != expected_change:
        reasons.append("SCHEMA_CHANGE_MISMATCH")
    schema_sha256 = hashlib.sha256(head_snapshot).hexdigest()
    if schema_sha256 != review["head_schema_sha256"]:
        reasons.append("SCHEMA_MISMATCH")
    return {"status": "REVIEW_REQUIRED" if reasons else "READY",
            "reasons": reasons, "test_id_hash": registered_test if not reasons else None,
            "entry_point": ENTRY_POINT if not reasons else None,
            "head_schema_sha256": review["head_schema_sha256"]}
