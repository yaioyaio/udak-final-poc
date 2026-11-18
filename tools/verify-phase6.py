#!/usr/bin/env python3
"""Verify a bounded local candidate and its provenance without launching Gradle."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cli = load("phase6_cli_contract", "udak-cli/udak_cli.py")
h = load("phase6_candidate_runner", "tools/run-phase6.py")
REPORT = "evidence/PHASE6-VALIDATION.json"
UNIT = "evidence/PHASE6-VERIFIER-VALIDATION.json"
GATE = "evidence/PHASE6-GATE.json"
BASELINE = "evidence/PHASE5-VALIDATION.json"
G4 = "evidence/PHASE5-GATE.json"
VERIFIER = "tools/verify-phase6.py"
TESTS = "tools/test-phase6-verifier.py"
STEPS = ("java-version", "resolve", "prior-g4", "core-smoke", "package", "repackage",
         "consumer-BOOT3", "consumer-BOOT4", "consumer-BOOT4-bom", "consumer-BOOT4-mixed", "consumer-BOOT3-wrong",
         "consumer-BOOT4-wrong", "cli-contract")
SCENARIOS = ("DISCOVERY", "DISABLED", "USER_BEANS", "CUSTOM_SINK", "JDBC_OPT_IN",
             "NO_DATASOURCE", "AMBIGUOUS_DATASOURCES", "JDBC_TRANSACTION", "VENDOR_REQUIRED",
             "INVALID_LIMITS", "UNSAFE_SETTINGS")
NEGATIVES = (("BOOT4", "mixed"), ("BOOT3", "wrong"), ("BOOT4", "wrong"))
VERSIONS = {"BOOT3": ("3.5.16", "6.2.19"), "BOOT4": ("4.1.2", "7.0.10")}
LEGACY_MODULES = ("core", "udak-api", "jdbc-spring", "observe-core")
PACKAGED = {p + ext for p in cli.ARTIFACT_PREFIXES
            for ext in (".jar", ".pom", ".module", "-sources.jar", "-javadoc.jar")}
EXTRAS = {"build/phase6/" + name for name in
          ("SBOM.json", "NOTICE.txt", "API-COMPATIBILITY.json", "CANDIDATE.json", "CHECKSUMS.sha512")}
UNEXECUTED = {"performance/load", "cancellation/recovery certification", "external publication",
              "production license approval", "full legacy demo Gradle build"}
LIMITS = {"wall_seconds": 1800, "gradle_heap_mib": 512, "gradle_metaspace_mib": 256,
          "active_cpus": 2, "workers": 1, "consumer_heap_mib": 256, "child_cpu_seconds": 120,
          "workspace_files": 20000, "workspace_bytes": 2 * 1024**3,
          "candidate_files": 500, "candidate_bytes": 200 * 1024**2}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def root_dir():
    return cli.directory(ROOT.parts[1:])


def digest_file(fd, path):
    with cli.regular_file(fd, path, cli.MAX_JSON_BYTES) as (stream, size):
        raw = stream.read(size + 1)
        require(len(raw) == size, "INPUT_CHANGED")
        return hashlib.sha512(raw).hexdigest()


def check_input_names(report):
    inventory = {"source_sha512": h.sources(), "harness_sha512": h.HARNESS,
                 "configuration_sha512": h.CONFIG, "manifest_sha512": (h.MANIFEST, cli.POLICY)}
    for key, allowed in inventory.items():
        group = report.get(key)
        require(isinstance(group, dict) and set(group) == set(allowed)
                and all(cli.valid_digest(value) for value in group.values()), "INPUT_INVENTORY")


def check_step(step, name):
    require(isinstance(step, dict) and step.get("name") == name and step.get("status") == "PASS"
            and integer(step.get("exit_code"), 0, 0) and step.get("child_reaped") is True
            and step.get("process_group_quiesced") is True and cli.valid_digest(step.get("output_sha512")),
            "EXECUTION_STEP")


def check_runtime(report):
    require("failure_type" not in report and "failed_step" not in report
            and report.get("status") == "PASS" and integer(report.get("schema_version"), 1, 1)
            and integer(report.get("phase"), 6, 6) and integer(report.get("containers_started"), 0, 0)
            and integer(report.get("external_publications"), 0, 0) and report.get("authorize_publish") is False
            and UNEXECUTED.issubset(report.get("not_run", [])), "EXECUTION_SCOPE")
    require(all(type(report["limits"].get(k)) is int and report["limits"][k] == v for k,v in LIMITS.items())
            and type(report.get("elapsed_seconds")) in (int, float)
            and 0 < report["elapsed_seconds"] <= LIMITS["wall_seconds"], "EXECUTION_LIMITS")
    steps = report.get("steps")
    require(isinstance(steps, list) and len(steps) == len(STEPS), "STEP_COUNT")
    for name, step in zip(STEPS, steps):
        check_step(step, name)
    documents = report.get("documentation", {})
    require(documents.get("status") == "PASS" and documents.get("id_version_structure_parity") == "PASS"
            and integer(documents.get("paired_documents"), 1, 1000)
            and integer(documents.get("local_links_checked"), 1, 100000), "DOCUMENT_CHECK")


def cleanup(record, files, size):
    require(record.get("status") == "PASS" and record.get("temporary_directory_remaining") is False
            and integer(record.get("temporary_files_removed"), 1, files)
            and integer(record.get("temporary_bytes_removed"), 1, size), "CLEANUP")


def dependencies(report, manifest):
    lanes = manifest.get("lanes")
    require(manifest.get("approval") == "DECLARED LICENSES VERIFIED; redistribution NOT GRANTED"
            and manifest.get("gradle") == {"version": "8.14.3", "distribution_sha256": h.GRADLE_SHA256}
            and isinstance(lanes, dict) and set(lanes) == {"starter-boot3", "starter-boot4", "h2"}
            and lanes["h2"] == ["com.h2database:h2:2.3.232"], "DEPENDENCY_MANIFEST")
    consumer_lanes = manifest.get("consumer_lanes")
    require(isinstance(consumer_lanes, dict) and set(consumer_lanes) == {"starter-boot3","starter-boot4"},
            "CONSUMER_LANES")
    coords = set()
    for items in [*lanes.values(), *consumer_lanes.values()]:
        require(cli.valid_coordinates(items), "LANE_INVENTORY")
        coords.update(items)
    rows = manifest.get("artifacts")
    require(isinstance(rows, list) and len(rows) == len(coords) == 29, "DEPENDENCY_COUNT")
    for graphs in (lanes, consumer_lanes):
        for lane,(boot,spring) in VERSIONS.items():
            items = set(graphs["starter-"+lane.lower()])
            require(items.isdisjoint(lanes["h2"]) and all(not a.startswith("dev.udak:") for a in items)
                    and {"org.springframework.boot:spring-boot:"+boot,
                         "org.springframework.boot:spring-boot-autoconfigure:"+boot,
                         "org.springframework:spring-jdbc:"+spring} <= items, "EXTERNAL_GRAPH")
            modules = [coord.rsplit(":",1)[0] for coord in items]
            require(len(modules) == len(set(modules)), "MULTIPLE_MODULE_VERSIONS")
    require({cli.verify_dependency_record(row) for row in rows} == coords, "ARTIFACT_PINS")
    proof = report.get("dependencies", {})
    require(proof.get("status") == "PASS" and proof.get("lanes") == lanes
            and proof.get("consumer_lanes") == consumer_lanes
            and integer(proof.get("artifacts"), len(coords), len(coords))
            and proof.get("sha512") == report["manifest_sha512"][h.MANIFEST], "DEPENDENCY_PROOF")


def check_lane(proof, lane, mode, manifest):
    expected_refusal = mode in ("mixed", "wrong")
    scenarios = ("MIXED_STARTERS",) if mode == "mixed" else ("WRONG_BOOT_MAJOR",) if mode == "wrong" else SCENARIOS
    protocol = proof if mode is None else proof.get("protocol", {})
    require(proof.get("status") == "PASS" and protocol.get("status") == "PASS"
            and protocol.get("scenarios") == list(scenarios)
            and integer(protocol.get("assertions"), len(scenarios), 100000), "CONSUMER_PROTOCOL")
    wire = [lane+" PASS", "ASSERTIONS="+str(protocol["assertions"])]
    wire.extend("SCENARIO="+scenario+":PASS" for scenario in scenarios)
    require(hashlib.sha512(("\n".join(wire)+"\n").encode()).hexdigest() == protocol.get("protocol_sha512"),
            "PROTOCOL_DIGEST")
    if expected_refusal:
        require(protocol.get("startup_refused") is True, "STARTUP_NOT_REFUSED")
    else:
        require(protocol.get("application_started") is True and protocol.get("application_closed") is True,
                "CONSUMER_LIFECYCLE")
    r = proof.get("resolution", {})
    boot, spring = VERSIONS[lane]
    require(r.get("status") == "PASS" and r.get("pom_only") is True and r.get("boot_version") == boot
            and r.get("spring_versions") == [spring], "CONSUMER_VERSION")
    artifacts = r.get("artifacts")
    require(isinstance(artifacts, list) and 1 <= len(artifacts) <= 256
            and len(set(artifacts)) == len(artifacts), "CONSUMER_COORDINATES")
    own = {"dev.udak:"+n+":"+cli.VERSION for n in LEGACY_MODULES}
    major = lane[-1]
    opposite = "4" if major == "3" else "3"
    selected = (major, opposite) if mode == "mixed" else ((opposite,) if mode == "wrong" else (major,))
    own.update("dev.udak:starter-boot"+number+":"+cli.VERSION for number in selected)
    graph = manifest["consumer_lanes"] if mode is None else manifest["lanes"]
    expected = own | set(manifest["lanes"]["h2"]) | set(graph["starter-boot"+major])
    require(set(artifacts) == expected and "org.springframework.boot:spring-boot:"+boot in expected
            and "org.springframework:spring-jdbc:"+spring in expected, "CONSUMER_GRAPH")


def consumers(report, manifest):
    lines = report.get("boot_lines")
    require(isinstance(lines, dict) and set(lines) == {"boot3","boot4"}, "POSITIVE_LANES")
    for lane in VERSIONS:
        check_lane(lines[lane.lower()], lane, None, manifest)
    bom = report.get("bom_consumer", {})
    require(bom.get("lane") == "BOOT4", "BOM_CONSUMER")
    check_lane(bom, "BOOT4", "bom", manifest)
    require(bom["protocol"]["assertions"] == lines["boot4"]["assertions"] == 79, "BOM_ASSERTIONS")
    negatives = report.get("negative_consumers")
    require(isinstance(negatives, list) and len(negatives) == len(NEGATIVES), "NEGATIVE_LANES")
    for record, (lane, mode) in zip(negatives, NEGATIVES):
        require(record.get("lane") == lane and record.get("mode") == mode, "NEGATIVE_ORDER")
        check_lane(record, lane, mode, manifest)


def consumed_bytes(report, manifest):
    external = {a["group"]+":"+a["name"]+":"+a["version"]:a["sha512"] for a in manifest["artifacts"]}
    packages = report["reproducibility"]["artifact_sha512"]
    own = {"dev.udak:"+module+":"+cli.VERSION:packages[prefix+".jar"]
           for module,prefix in zip(cli.RELEASE_MODULES,cli.ARTIFACT_PREFIXES)}
    expected = external | own
    for proof in [*report["boot_lines"].values(), report["bom_consumer"], *report["negative_consumers"]]:
        resolution = proof["resolution"]
        require(resolution.get("artifact_sha512") == {coord:expected[coord] for coord in resolution["artifacts"]},
                "CONSUMED_BYTES")


def reproduction(report):
    rows = report.get("artifacts")
    require(isinstance(rows, list) and len(rows) == len(PACKAGED | EXTRAS)
            and {r["path"] for r in rows} == PACKAGED | EXTRAS, "PACKAGE_INVENTORY")
    sums = {r["path"]:r["sha512"] for r in rows if r["path"] in PACKAGED}
    proof = report.get("reproducibility", {})
    require(proof.get("status") == "PASS" and integer(proof.get("repackaged_artifacts"),len(PACKAGED),len(PACKAGED))
            and all(cli.valid_digest(v) for v in sums.values()) and proof.get("artifact_sha512") == sums,
            "REPRODUCTION")


def baseline(report, previous, gate, baseline_digest):
    require(gate.get("gate") == "G4" and gate.get("status") == "PASS"
            and gate.get("execution_reports_sha512", {}).get(BASELINE) == baseline_digest
            and previous.get("status") == "PASS", "G4_BASELINE")
    def public_source(path):
        return any(path.startswith(m+"/src/main/java/") for m in LEGACY_MODULES)
    latest = {p:v for p,v in report["source_sha512"].items() if public_source(p)}
    old = {p:v for p,v in previous["source_sha512"].items() if public_source(p)}
    require(len(old) == 22 and latest == old, "PUBLIC_SOURCE_CHANGE")
    proof = report.get("api_compatibility", {})
    require(proof.get("status") == "PASS" and proof.get("baseline") == BASELINE
            and integer(proof.get("preserved_sources"), len(old), len(old))
            and proof.get("prior_published_release") == "NONE"
            and proof.get("binary_backward_compatibility") == "NOT RUN; no prior published release", "API_BASELINE")


def verify(fd, report):
    check_input_names(report)
    cli.verify_inputs(fd, report)
    check_runtime(report)
    manifest = cli.read_report(fd, h.MANIFEST, expected_digest=report["manifest_sha512"][h.MANIFEST])
    dependencies(report, manifest)
    consumers(report, manifest)
    reproduction(report)
    consumed_bytes(report, manifest)
    available = cli.verify_candidate(fd, cli.artifact_inventory(report))
    baseline(report, cli.read_report(fd, BASELINE), cli.read_report(fd, G4), digest_file(fd, BASELINE))
    policy = cli.read_report(fd, cli.POLICY, expected_digest=report["manifest_sha512"][cli.POLICY])
    require(all(policy.get(k) == v for k,v in cli.BLOCKING_POLICY.items()) and policy.get("publication_authority") == "NONE"
            and policy.get("github_actions") == "FORBIDDEN" and policy.get("candidate_version") == cli.VERSION,
            "RELEASE_POLICY")
    work = report["cleanup"]
    cleanup(work, LIMITS["workspace_files"], LIMITS["workspace_bytes"])
    check_step(work.get("gradle_stop"), "cleanup-gradle-stop")
    require(work.get("gradle_daemons_quiesced") is True, "DAEMON_REMAINING")
    candidate = report["candidate_cleanup"]
    cleanup(candidate, LIMITS["candidate_files"], LIMITS["candidate_bytes"])
    for dimension, bound in (("files","workspace_files"),("bytes","workspace_bytes")):
        removed = "temporary_"+dimension+"_removed"
        require(work.get("candidate_"+dimension+"_removed") == candidate[removed] <= work[removed]
                and integer(work.get("peak_"+dimension), 1, LIMITS[bound]), "CLEANUP_ACCOUNTING")
    return {"schema_version":1, "phase":6, "gate":"G6", "status":"PASS", "scope":"local private candidate",
            "candidate_artifacts":available,"repackaged_artifacts":len(PACKAGED),"consumer_executions":6,
            "formal_release":"BLOCKED","authorize_publish":False,"g0":"NOT GRANTED","g5":"NOT RUN"}


def verify_unit(fd, unit, validation_digest):
    require(unit.get("status") == "PASS" and integer(unit.get("tests"), 50, 256)
            and integer(unit.get("skipped"), 0, 0) and unit.get("validation_sha512") == validation_digest
            and unit.get("source_sha512") == {p:digest_file(fd,p) for p in (TESTS,VERIFIER)},
            "VERIFIER_CONTRACTS")
    step = unit["step"]
    check_step(step, "phase6-verifier-tests")
    probes = unit.get("synthetic_cleanup")
    require(isinstance(probes,dict) and set(probes) == {"failure","timeout","interrupt"}, "SYNTHETIC_CLEANUP")
    for record in probes.values():
        require(isinstance(record,dict) and integer(record.get("temporary_files_removed"),1,1)
                and integer(record.get("temporary_bytes_removed"),0,1024)
                and record.get("temporary_directory_remaining") is False, "SYNTHETIC_CLEANUP")
    marker = ("VERIFIER_TESTS="+str(unit["tests"])+"\nSKIPPED=0\nSYNTHETIC_CLEANUP="
              +json.dumps(probes,sort_keys=True,separators=(",",":"))+"\n").encode()
    require(step["output_sha512"] == hashlib.sha512(marker).hexdigest(), "TEST_PROTOCOL")
    cleanup(unit["cleanup"], 2000, 128*1024**2)


def save_report(path, data):
    """Write only known evidence names and archive the prior public report by digest."""
    require(path in (GATE, UNIT), "OUTPUT_PATH")
    with root_dir() as fd:
        try:
            with cli.regular_file(fd,path,cli.MAX_JSON_BYTES) as (stream,size):
                old = stream.read(size + 1)
                require(len(old) == size, "INPUT_CHANGED")
        except FileNotFoundError:
            old = None
        if old is not None:
            with cli.directory([".git"],root_fd=fd) as git:
                try:
                    os.mkdir("udak-phase6", mode=0o700,dir_fd=git)
                except FileExistsError:
                    pass
                with cli.directory(["udak-phase6"],root_fd=git) as archive:
                    target = hashlib.sha512(old).hexdigest()+".json"
                    try:
                        dest = os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=archive)
                    except FileExistsError:
                        cli.verify_digest(archive,target,hashlib.sha512(old).hexdigest(),len(old),expected_size=len(old))
                    else:
                        with os.fdopen(dest,"wb") as writer:
                            writer.write(old)
        with cli.directory(["evidence"],root_fd=fd) as out:
            name = Path(path).name
            temp = name+"."+os.urandom(8).hex()+".tmp"
            dest = os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=out)
            try:
                with os.fdopen(dest,"w",encoding="utf-8") as writer:
                    json.dump(data,writer,indent=2)
                    writer.write("\n")
                os.replace(temp,name,src_dir_fd=out,dst_dir_fd=out)
            finally:
                try:
                    os.unlink(temp,dir_fd=out)
                except FileNotFoundError:
                    pass


def main():
    try:
        require(len(sys.argv) == 1, "ARGUMENTS")
        with root_dir() as fd:
            initial = {p:digest_file(fd,p) for p in (REPORT,UNIT)}
            gate = verify(fd, cli.read_report(fd,REPORT))
            verify_unit(fd,cli.read_report(fd,UNIT),initial[REPORT])
            require(initial == {p:digest_file(fd,p) for p in initial}, "EXECUTION_REPORT_CHANGED")
            gate["execution_reports_sha512"] = initial
            gate["verifier_sha512"] = digest_file(fd,VERIFIER)
        save_report(GATE,gate)
        print("PHASE6 LOCAL_CANDIDATE PASS; FORMAL_RELEASE BLOCKED")
        return 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError, RecursionError):
        print("PHASE6 LOCAL_CANDIDATE NOT_VERIFIED; FORMAL_RELEASE BLOCKED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
