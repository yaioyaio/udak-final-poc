#!/usr/bin/env python3
"""Validate schema contracts with bounded, isolated H2 fixtures and the local drift CLI."""

import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import sys
import traceback


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "evidence/SCHEMA-DRIFT-VALIDATION.json"
spec = importlib.util.spec_from_file_location("phase2", ROOT / "tools/run-phase2.py")
phase2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phase2)
guard = phase2.guard
LIMITS = ["-Xmx256m", "-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2"]
COLLECTOR = "dev.udak.schema.SchemaSnapshotCollectorContractTest"
SOURCES = [
    "schema-regression/src/main/java/dev/udak/schema/SchemaSnapshotCollector.java",
    "schema-regression/src/test/java/dev/udak/schema/SchemaSnapshotCollectorContractTest.java",
]
INPUTS = SOURCES + [
    "tools/phase2-dependencies.json", "tools/run-phase1.py", "tools/run-phase2.py",
    "tools/run-core-smoke.sh", "tools/run-schema-drift.py", "tools/schema-drift.py", "tools/schema-impact.py",
    "tools/sql-inventory.py", "tools/test-schema-drift.py", "tools/test-schema-impact.py",
]
EXPECTED = [
    ("added_col", "ADDED", None, {"type": "DATE", "width": 0, "nullable": True}),
    ("label", "WIDTH", {"type": "VARCHAR", "width": 32, "nullable": True},
     {"type": "VARCHAR", "width": 64, "nullable": True}),
    ("legacy_col", "REMOVED", {"type": "DATE", "width": 0, "nullable": True}, None),
    ("note", "NULLABILITY", {"type": "VARCHAR", "width": 16, "nullable": False},
     {"type": "VARCHAR", "width": 16, "nullable": True}),
    ("quantity", "TYPE", {"type": "INTEGER", "width": 0, "nullable": False},
     {"type": "BIGINT", "width": 0, "nullable": False}),
]


def cli(work, current):
    launcher = "import os,runpy,sys; os.chdir(sys.argv.pop(2)); sys.argv.pop(0); runpy.run_path(sys.argv[0],run_name='__main__')"
    return [sys.executable, "-B", "-c", launcher, str(ROOT / "tools/schema-drift.py"), str(work),
            "--dbms", "H2", "--table", "contract_item", "--baseline", "baseline/SCHEMA-SNAPSHOT.json",
            "--current", f"{current}/SCHEMA-SNAPSHOT.json"]


def validate(result):
    with guard.workspace("udak-schema-drift-") as (work, cleanup):
        result["cleanup"] = cleanup
        os.environ["TMPDIR"] = str(work)
        for key in ("_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS"):
            os.environ.pop(key, None)

        def step(name, command, expected=0):
            proof = guard.run_step(name, command, work, expected=expected)
            if not proof["child_reaped"] or not proof["process_group_quiesced"]:
                raise ValueError("Child cleanup incomplete")
            result["steps"].append(proof)
            return (work / (name + ".output")).read_text(encoding="utf-8")

        manifest = json.loads((ROOT / "tools/phase2-dependencies.json").read_text())
        manifest["artifacts"] = [item for item in manifest["artifacts"]
                                 if item["coordinate"] == "com.h2database:h2:2.3.232"]
        jar, dependencies = phase2.dependencies(work, manifest)
        h2, = jar
        result["h2"] = dependencies["artifacts"][0]
        classes = work / "classes"
        step("compile", ["javac", *("-J" + limit for limit in LIMITS), "--release", "17",
                         "-d", str(classes), *SOURCES])
        snapshots = []
        for label in ("baseline", "equal", "drift"):
            path = work / label / "SCHEMA-SNAPSHOT.json"
            path.parent.mkdir()
            snapshots.append(str(path))
        output = step("collect-h2", ["java", *LIMITS, "-cp", os.pathsep.join((str(classes), str(h2))),
                                    COLLECTOR, *snapshots])
        result["collector_checks"] = int(re.fullmatch(r"Schema snapshot collector contract checks: ([1-9][0-9]*)\n",
                                                       output)[1])
        same = json.loads(step("compare-equal", cli(work, "equal")))
        changed = json.loads(step("compare-drift", cli(work, "drift"), expected=2))
        for comparison, status in ((same, "MATCH"), (changed, "DRIFT")):
            if (comparison["status"] != status or comparison["dbms"] != "H2"
                    or comparison["baseline_revision"] != "a" * 40 or comparison["current_revision"] != "a" * 40):
                raise ValueError("Comparison protocol invalid")
        differences = [(item["column"], item["kind"], item["before"], item["after"]) for item in changed["changes"]
                       if item["table"] == "contract_item"]
        if same["changes"] or differences != EXPECTED or len(changed["changes"]) != len(EXPECTED):
            raise ValueError("Unexpected change detected")
        result["comparison"] = {"match": same["status"], "changed": changed["status"],
                                "change_kinds": sorted(row[1] for row in EXPECTED)}
        for name in ("schema-drift", "schema-impact"):
            output = step(name, [sys.executable, "-B", f"tools/test-{name}.py"])
            result[name + "-tests"] = int(re.search(r"\nRan ([1-9][0-9]*) tests? in .*\n\nOK\n$", output)[1])
        step("core-smoke", ["/usr/bin/env", "_JAVA_OPTIONS=" + " ".join(LIMITS), "./tools/run-core-smoke.sh"])
        result["input_sha512"] = {name: guard.digest((ROOT / name).read_bytes()) for name in INPUTS}
    if cleanup["status"] != "PASS" or cleanup["temporary_directory_remaining"]:
        raise ValueError("Workspace cleanup incomplete")


def main():
    if sys.argv[1:]:
        return 2
    result = {"schema_version": 1, "requirement": "NEXT-004", "status": "FAIL", "steps": [],
              "java_compile_release": 17, "external_db_integration": "NOT RUN", "containers_started": 0,
              "limits": {"wall_seconds": 120, "child_cpu_seconds": 30, "heap_mib": 256, "active_cpus": 2}}
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, guard.interrupted)
    signal.alarm(120)
    try:
        validate(result)
    except Exception as error:
        result["failure_type"] = type(error).__name__
        result["failure_locations"] = [
            {"file": Path(frame.filename).name, "line": frame.lineno}
            for frame in traceback.extract_tb(error.__traceback__)
        ]
    else:
        result["status"] = "PASS"
        REPORT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    finally:
        signal.alarm(0)
    print(json.dumps({key: value for key, value in result.items() if key != "input_sha512"}))
    return int(result["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
