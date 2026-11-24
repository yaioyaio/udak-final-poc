#!/usr/bin/env python3
"""Replay the tenant-scoped Device DAO projection change from ThingsBoard PR #14036."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import signal
import sys
import uuid

spec = importlib.util.spec_from_file_location("count_replay", Path(__file__).with_name("replay-upstream-count.py"))
count_replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(count_replay)
guard = count_replay.guard
PILOT = count_replay.ROOT.parent / "thingsboard-ce-v4.3.1.8-pilot"
BASE = ("0aac17e7d6a811c576328a0d4cb7d1587b3f478a", "78ee2795b04c744f0a786f721337bbe45c632331")
HEAD = ("7b7a91df202f5e795d4e8fc2a4275326dcc6762e", "49062f829f9043ec396fa05fe2a81fab9bb28a97")
PROFILE = "8cb56304849d88c66145d48c1c689a11da10a40f5bbb45b5f07ac7ddb6b4d821"
METHOD = "findProfileEntityIdInfosByTenantId"
QUERY = "thingsboard-tenant-device-profile-info"
TEST = "thingsboard-14036-device-profile-replay"
REPLAY_CLASS = "UpstreamDeviceProfile"


def query_template(source):
    pattern = (rf'\b{METHOD}\(UUID tenantId, Pageable pageable\) \{{\s*'
               r'String PROFILE_DEVICE_ID_INFO_QUERY = String\.format\("([^"\n]+)", tenantId\);')
    matches = re.findall(pattern, source)
    if len(matches) != 1:
        raise ValueError("Expected one tenant-scoped device profile query")
    return matches[0]


def replay_input():
    before = query_template(count_replay.upstream(BASE))
    after = query_template(count_replay.upstream(HEAD))
    added_column = ", customer_id as customerId"
    if (after.count(added_column) != 1 or after.replace(added_column, "", 1) != before
            or not before.endswith("WHERE tenant_id = '%s' ORDER BY created_time ASC LIMIT %%s OFFSET %%s")):
        raise ValueError("Unexpected pinned projection change")
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    return (BASE[0], HEAD[0], PROFILE, QUERY, TEST, first, second,
            (before % first) % (1, 0), (after % first) % (1, 0), (after % second) % (1, 0))


def snapshot_shape(work, name, revision, query_hash, test_hash):
    snapshot = json.loads((work / name / "SQL-INVENTORY.json").read_bytes())
    entry, = snapshot["entries"]
    shape, = entry["shapes"]
    if (snapshot["schema_version"] != 2 or snapshot["revision"] != revision or snapshot["profile"] != PROFILE
            or snapshot["dropped"] != 0 or entry["query_id_hash"] != query_hash
            or entry["observed"] != 1 or entry["unavailable"] != 0 or entry["test_ids"] != [test_hash]
            or shape["statement_kind"] != "SELECT" or shape["test_ids"] != [test_hash]):
        raise ValueError("Snapshot does not match the registered replay test")
    return shape["fingerprint_hash"]


def check_evidence(work):
    count_replay.check_reports(work)
    test_hash = hashlib.sha256(b"udak-inventory-test-id-v1\0" + TEST.encode()).hexdigest()
    query_hash = hashlib.sha256(b"udak-inventory-query-id-v1\0" + QUERY.encode()).hexdigest()
    before = snapshot_shape(work, "base", BASE[0], query_hash, test_hash)
    after = snapshot_shape(work, "head", HEAD[0], query_hash, test_hash)
    control = snapshot_shape(work, "control", HEAD[0], query_hash, test_hash)
    change_file = (work / "change.output").read_bytes()
    control_file = (work / "control.output").read_bytes()
    changed, unchanged = json.loads(change_file), json.loads(control_file)
    query, = changed["queries"]
    added, = query["added_observed_shapes"]
    absent, = query["absent_observed_shapes"]
    if (before == after or after != control or query["query_id_hash"] != query_hash
            or added["fingerprint_hash"] != after or absent["fingerprint_hash"] != before
            or changed["impacted_test_ids"] != [test_hash] or query["impacted_test_ids"] != [test_hash]
            or unchanged["queries"][0]["query_id_hash"] != query_hash
            or unchanged["queries"][0]["changes"] or unchanged["impacted_test_ids"]):
        raise ValueError("PR report does not match the observed replay")
    return {"profile": PROFILE, "query_id_hash": query_hash, "test_id_hash": test_hash,
            "base_fingerprint_hash": before, "head_fingerprint_hash": after, "control_fingerprint_hash": control,
            "change_report_status": changed["status"], "control_report_status": unchanged["status"],
            "change_report_sha256": hashlib.sha256(change_file).hexdigest(),
            "control_report_sha256": hashlib.sha256(control_file).hexdigest(),
            "markdown_report_sha256": hashlib.sha256((work / "pr-markdown.output").read_bytes()).hexdigest(),
            "changed_queries": 1, "impacted_tests": 1, "uuid_only_changes": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, guard.interrupted)
    jdbc = PILOT / "dao-reactor-maven-cache/org/postgresql/postgresql/42.7.14/postgresql-42.7.14.jar"
    if not jdbc.is_file():
        raise ValueError("The pilot PostgreSQL JDBC JAR is missing")
    java = Path(count_replay.inspect("/usr/libexec/java_home", "-v", "21"))
    if not count_replay.host_ready():
        print(json.dumps({"status": "NOT RUN", "reason": "POSTGRESQL_HOST_PREFLIGHT"}))
        return 2
    data = replay_input()
    with (PILOT / ".dao-reactor.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with guard.workspace("udak-thingsboard-device-profile-") as (work, cleanup):
            classes = count_replay.compile_replay(work, jdbc, java, REPLAY_CLASS)
            count_replay.replay(work, classes, jdbc, java, data, REPLAY_CLASS)
            assertions = (work / "jdbc-replay.output").read_text().strip()
            if assertions != "assertions=3":
                raise ValueError("Expected all PostgreSQL result assertions")
            report = check_evidence(work)
    print(json.dumps({"schema_version": 1, "status": "PASS", "requirement": "NEXT-005",
                      "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                      "upstream_pr": 14036, "source": count_replay.SOURCE, "method": METHOD,
                      "base": {"revision": BASE[0], "blob": BASE[1]},
                      "head": {"revision": HEAD[0], "blob": HEAD[1]},
                      "postgresql_image": count_replay.IMAGE, "image_digest": count_replay.INDEX,
                      "jdbc_version": "42.7.14", "postgresql_result_assertions": 3,
                      "container_cleanup": "PASS", "workspace_cleanup": cleanup, **report}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
