"""Inspect the local Phase 6 candidate without running application code."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys


ROOT = Path(os.path.abspath(__file__)).parent.parent
VALIDATION = "evidence/PHASE6-CURRENT-VALIDATION.json"
POLICY = "tools/phase6-release-policy.json"
APPROVALS = "evidence/PHASE6-APPROVALS.json"
DEPENDENCY_PINS = "tools/phase6-dependencies.json"
BASELINE_PINS = "tools/phase6-current-baseline.json"
HISTORICAL = {
    "G2": "evidence/G2-REAL-VALIDATION.json",
    "G3": "evidence/PHASE3-GATE.json",
    "G4": "evidence/PHASE5-GATE.json",
}

RELEASE_MODULES = ("core", "udak-api", "jdbc-spring", "observe-core", "starter-boot3", "starter-boot4")
SOURCE_MODULES = frozenset(RELEASE_MODULES + (
    "consistency-core", "consistency-spring", "consistency-testkit", "legacy-observe",
    "legacy-compat-testkit", "sql-jsqlparser", "db-testkit", "rewrite-core", "rewrite-jsqlparser",
    "rewrite-jdbc", "rewrite-testkit", "spring-boot-demo", "starter-testkit",
))
REQUIRED_SOURCE_MODULES = frozenset(("core", "starter-boot3", "starter-boot4", "starter-testkit"))
SOURCE_PATH = re.compile(r"[a-z0-9-]+/src/(?:main|test)/java/(?:[A-Za-z_][A-Za-z_0-9]*/)*[A-Za-z_][A-Za-z_0-9]*\.java")
REQUIRED_HARNESS = frozenset((
    "tools/run-phase6.py", "tools/verify-phase6.py", "tools/test-phase6-verifier.py",
    "tools/local-ci.py", "tools/udak-cli.py", "tools/release-gate.py",
    "tools/test-phase6-cli.py", "udak-cli/udak_cli.py",
))
HARNESS = REQUIRED_HARNESS | {
    "tools/run-phase1.py", "tools/run-phase3.py", "tools/run-phase4.py",
    "tools/run-phase5.py", "tools/verify-phase5.py",
}
REQUIRED_CONFIGURATION = frozenset((
    "settings.gradle.kts", "build.gradle.kts", "starter-testkit/settings.gradle",
    "starter-testkit/build.gradle", "starter-boot3/build.gradle.kts", "starter-boot4/build.gradle.kts",
)) | {
    f"{starter}/src/main/resources/META-INF/{entry}"
    for starter in ("starter-boot3", "starter-boot4")
    for entry in (
        "spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports",
        "spring-configuration-metadata.json",
    )
}
CONFIGURATION = REQUIRED_CONFIGURATION | {f"{module}/build.gradle.kts" for module in SOURCE_MODULES}
MANIFESTS = frozenset((DEPENDENCY_PINS, BASELINE_PINS, POLICY))

VERSION = "0.1.0-poc"
BOOT_VERSIONS = {"BOOT3": ("3.5.16", "6.2.19"), "BOOT4": ("4.1.2", "7.0.10")}
GRADLE_PIN = {
    "version": "8.14.3",
    "distribution_sha256": "bd71102213493060956ec229d946beee57158dbd89d0e62b91bca0fa2c5f3531",
}
VALIDATION_STEPS = (
    "java-version", "resolve", "prior-g4", "core-smoke", "package", "repackage",
    "consumer-BOOT3", "consumer-BOOT4", "consumer-BOOT4-bom", "consumer-BOOT4-mixed",
    "consumer-BOOT3-wrong", "consumer-BOOT4-wrong", "cli-contract",
)
POSITIVE_SCENARIOS = (
    "DISCOVERY", "DISABLED", "USER_BEANS", "CUSTOM_SINK", "JDBC_OPT_IN",
    "NO_DATASOURCE", "AMBIGUOUS_DATASOURCES", "JDBC_TRANSACTION", "VENDOR_REQUIRED",
    "INVALID_LIMITS", "UNSAFE_SETTINGS",
)
NEGATIVE_SCENARIOS = {
    ("BOOT4", "mixed"): "MIXED_STARTERS",
    ("BOOT3", "wrong"): "WRONG_BOOT_MAJOR",
    ("BOOT4", "wrong"): "WRONG_BOOT_MAJOR",
}
PIN_LANES = frozenset(("starter-boot3", "starter-boot4", "h2"))
CONSUMER_PIN_LANES = PIN_LANES - {"h2"}
PINNED_DEPENDENCIES = 29
COORDINATE = re.compile(r"[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+")
MAVEN_CENTRAL = "https://repo.maven.apache.org/maven2/"
MAVEN_POM = re.compile(re.escape(MAVEN_CENTRAL) + r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.pom")
LICENSE_RESOURCE = re.compile(r"(?:META-INF/)?(?:LICENSE|NOTICE)(?:[._-][A-Za-z0-9-]+)?(?:\.txt)?", re.I)
ARTIFACT_PREFIXES = tuple(
    f"build/phase6/repository/dev/udak/{module}/{VERSION}/{module}-{VERSION}"
    for module in RELEASE_MODULES
)
REQUIRED_ARTIFACTS = frozenset(
    prefix + extension for prefix in ARTIFACT_PREFIXES for extension in (".jar", ".pom")
) | {
    f"build/phase6/{entry}" for entry in (
        "SBOM.json", "NOTICE.txt", "CHECKSUMS.sha512", "CANDIDATE.json", "API-COMPATIBILITY.json",
    )
}
ARTIFACTS = REQUIRED_ARTIFACTS | {
    prefix + extension for prefix in ARTIFACT_PREFIXES
    for extension in (".module", "-sources.jar", "-javadoc.jar")
}
REPOSITORY_ARTIFACTS = frozenset(path for path in ARTIFACTS if path.startswith("build/phase6/repository/"))
RELEASE_POLICY = {
    "github_actions": "FORBIDDEN",
    "publication_authority": "NONE",
    "candidate_version": VERSION,
}

BLOCKING_POLICY = {
    "commercial_license_approval": "NOT GRANTED",
    "project_license": "NOT GRANTED",
    "performance_and_cancellation_recovery": "NOT RUN",
    "formal_publisher": "NOT IMPLEMENTED",
}
SHA512 = re.compile(r"[0-9a-f]{128}")
SECRET_NAME = re.compile(
    r"(?:^|[._-])(?:env|private|secret|secrets|credentials?|passwords?|tokens?|id_rsa|id_ed25519)(?:[._-]|$)"
    r"|\.(?:key|pem|p12|pfx|jks|keystore)(?:\.|$)",
    re.IGNORECASE,
)
MAX_JSON_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 1024 * 1024
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_SOURCE_FILES = 512
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_ARTIFACT_TOTAL_BYTES = 200 * 1024 * 1024
MAX_PATH_LENGTH = 255
MAX_DEPENDENCIES = 512


class InvalidEvidence(ValueError):
    """Carries a fixed, public reason code."""


def public_path(path):
    return (
        isinstance(path, str) and 0 < len(path) <= MAX_PATH_LENGTH
        and all(
            re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", part) and not SECRET_NAME.search(part)
            for part in path.split("/")
        )
    )


@contextmanager
def directory(parts, *, root_fd=None):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags) if root_fd is None else os.dup(root_fd)
    try:
        for part in parts:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@contextmanager
def regular_file(root_fd, path, limit, *, expected_size=None):
    if not public_path(path):
        raise InvalidEvidence("UNSAFE_PATH")
    parts = path.split("/")
    with directory(parts[:-1], root_fd=root_fd) as parent:
        info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise InvalidEvidence("UNSAFE_FILE")
        if info.st_size > limit or (expected_size is not None and info.st_size != expected_size):
            raise InvalidEvidence("INVALID_FILE_SIZE")
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            if file_identity(os.fstat(fd)) != file_identity(info):
                raise InvalidEvidence("INPUT_CHANGED")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                yield stream, info.st_size
                if file_identity(os.fstat(fd)) != file_identity(info):
                    raise InvalidEvidence("INPUT_CHANGED")
        finally:
            os.close(fd)


def file_identity(info):
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
        info.st_mtime_ns, info.st_ctime_ns,
    )


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidEvidence("INVALID_JSON")
        result[key] = value
    return result


def invalid_number(_value):
    raise InvalidEvidence("INVALID_JSON")


def finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        invalid_number(value)
    return number


def bounded_int(value):
    if len(value) > 20:
        invalid_number(value)
    return int(value)


def read_report(root_fd, path, *, expected_digest=None):
    with regular_file(root_fd, path, MAX_JSON_BYTES) as (stream, size):
        raw = stream.read(size + 1)
        if len(raw) != size:
            raise InvalidEvidence("INPUT_CHANGED")
    if expected_digest is not None and hashlib.sha512(raw).hexdigest() != expected_digest:
        raise InvalidEvidence("HASH_MISMATCH")
    try:
        report = json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique_object,
            parse_constant=invalid_number, parse_float=finite_float, parse_int=bounded_int,
        )
    except (ValueError, RecursionError) as error:
        raise InvalidEvidence("INVALID_JSON") from error
    if not isinstance(report, dict) or type(report.get("schema_version")) is not int or report["schema_version"] != 1:
        raise InvalidEvidence("UNKNOWN_SCHEMA")
    return report


def verify_digest(root_fd, path, digest, budget, expected_size=None):
    with regular_file(root_fd, path, min(budget, MAX_ARTIFACT_BYTES), expected_size=expected_size) as (stream, size):
        sha512 = hashlib.sha512()
        remaining = size
        while remaining:
            chunk = stream.read(min(remaining, 65536))
            if not chunk:
                raise InvalidEvidence("INPUT_CHANGED")
            sha512.update(chunk)
            remaining -= len(chunk)
        if stream.read(1):
            raise InvalidEvidence("INPUT_CHANGED")
    if sha512.hexdigest() != digest:
        raise InvalidEvidence("HASH_MISMATCH")
    return size


def valid_digest(value):
    return isinstance(value, str) and SHA512.fullmatch(value)


def positive_int(value, limit):
    return type(value) is int and 0 < value <= limit


def successful_step(step):
    return (
        isinstance(step, dict) and step.get("status") == "PASS"
        and type(step.get("exit_code")) is int and step["exit_code"] == 0
        and step.get("child_reaped") is True and step.get("process_group_quiesced") is True
        and valid_digest(step.get("output_sha512"))
    )


def successful_cleanup(cleanup, maximum_files, maximum_bytes):
    return (
        isinstance(cleanup, dict) and cleanup.get("status") == "PASS"
        and cleanup.get("temporary_directory_remaining") is False
        and positive_int(cleanup.get("temporary_files_removed"), maximum_files)
        and positive_int(cleanup.get("temporary_bytes_removed"), maximum_bytes)
    )


def valid_coordinates(coordinates):
    return (
        isinstance(coordinates, list) and 0 < len(coordinates) <= MAX_DEPENDENCIES
        and all(
            isinstance(coordinate, str) and len(coordinate) <= MAX_PATH_LENGTH
            and COORDINATE.fullmatch(coordinate)
            for coordinate in coordinates
        )
        and len(set(coordinates)) == len(coordinates)
    )


def verify_consumer_resolution(resolution, lane, mode, dependencies):
    boot, spring = BOOT_VERSIONS[lane]
    if (
        not isinstance(resolution, dict) or resolution.get("status") != "PASS"
        or resolution.get("pom_only") is not True or resolution.get("boot_version") != boot
        or resolution.get("spring_versions") != [spring]
        or not valid_coordinates(resolution.get("artifacts"))
    ):
        raise InvalidEvidence("INVALID_CONSUMER_RESOLUTION")
    coordinates = set(resolution["artifacts"])
    hashes = resolution.get("artifact_sha512")
    starters = {"starter-boot3", "starter-boot4"}
    if mode != "mixed":
        use_boot3 = (lane == "BOOT3") != (mode == "wrong")
        starters = {"starter-boot3" if use_boot3 else "starter-boot4"}
    expected_udak = {f"dev.udak:{module}:{VERSION}" for module in (*RELEASE_MODULES[:4], *starters)}
    graph = dependencies["consumer_lanes" if mode == "positive" else "lanes"]
    expected_external = set(graph["starter-" + lane.lower()]) | set(dependencies["lanes"]["h2"])
    if (
        coordinates != expected_udak | expected_external
        or not isinstance(hashes, dict) or hashes.keys() != coordinates
        or any(not valid_digest(digest) for digest in hashes.values())
    ):
        raise InvalidEvidence("INVALID_CONSUMER_RESOLUTION")


def valid_protocol(protocol, lane, expected):
    if (
        not isinstance(protocol, dict) or protocol.get("status") != "PASS"
        or protocol.get("scenarios") != list(expected)
        or not positive_int(protocol.get("assertions"), 10000)
        or protocol["assertions"] < len(expected)
    ):
        return False
    lines = (f"{lane} PASS", f"ASSERTIONS={protocol['assertions']}",
             *(f"SCENARIO={scenario}:PASS" for scenario in expected))
    digest = hashlib.sha512(("\n".join(lines) + "\n").encode("ascii")).hexdigest()
    return protocol.get("protocol_sha512") == digest


def verify_boot_contracts(report):
    dependencies = report["dependencies"]
    boot_lines = report.get("boot_lines")
    if not isinstance(boot_lines, dict) or boot_lines.keys() != {"boot3", "boot4"}:
        raise InvalidEvidence("PHASE6_INCOMPLETE")
    for lane, proof in boot_lines.items():
        if (
            not valid_protocol(proof, lane.upper(), POSITIVE_SCENARIOS)
            or proof.get("application_started") is not True or proof.get("application_closed") is not True
        ):
            raise InvalidEvidence("INVALID_BOOT_CONTRACT")
        verify_consumer_resolution(proof.get("resolution"), lane.upper(), "positive", dependencies)
    bom = report.get("bom_consumer")
    if not isinstance(bom, dict) or bom.get("status") != "PASS" or bom.get("lane") != "BOOT4":
        raise InvalidEvidence("INVALID_BOM_CONTRACT")
    protocol = bom.get("protocol")
    if (
        not valid_protocol(protocol, "BOOT4", POSITIVE_SCENARIOS)
        or protocol.get("application_started") is not True or protocol.get("application_closed") is not True
        or protocol["assertions"] != boot_lines["boot4"]["assertions"]
    ):
        raise InvalidEvidence("INVALID_BOM_CONTRACT")
    verify_consumer_resolution(bom.get("resolution"), "BOOT4", "bom", dependencies)
    negative = report.get("negative_consumers")
    if not isinstance(negative, list) or len(negative) != len(NEGATIVE_SCENARIOS):
        raise InvalidEvidence("INVALID_NEGATIVE_CONTRACT")
    modes = set()
    for proof in negative:
        if not isinstance(proof, dict) or proof.get("status") != "PASS":
            raise InvalidEvidence("INVALID_NEGATIVE_CONTRACT")
        lane, mode = proof.get("lane"), proof.get("mode")
        if not isinstance(lane, str) or not isinstance(mode, str):
            raise InvalidEvidence("INVALID_NEGATIVE_CONTRACT")
        scenario = NEGATIVE_SCENARIOS.get((lane, mode))
        protocol = proof.get("protocol")
        if (
            not scenario or (lane, mode) in modes
            or not valid_protocol(protocol, lane, (scenario,))
            or protocol.get("startup_refused") is not True
        ):
            raise InvalidEvidence("INVALID_NEGATIVE_CONTRACT")
        modes.add((lane, mode))
        verify_consumer_resolution(proof.get("resolution"), lane, mode, dependencies)


def dependency_coordinates(dependencies):
    return {
        coordinate
        for graph in (dependencies["lanes"], dependencies["consumer_lanes"])
        for lane in graph.values()
        for coordinate in lane
    }


def valid_dependency_graph(graph, expected_lanes):
    if not isinstance(graph, dict) or graph.keys() != expected_lanes:
        return False
    if any(not valid_coordinates(coordinates) for coordinates in graph.values()):
        return False
    for lane, (boot, spring) in BOOT_VERSIONS.items():
        coordinates = set(graph["starter-" + lane.lower()])
        required = {
            f"org.springframework.boot:spring-boot:{boot}",
            f"org.springframework.boot:spring-boot-autoconfigure:{boot}",
            f"org.springframework:spring-jdbc:{spring}",
        }
        if not required <= coordinates:
            return False
        for group, artifact, version in (coordinate.split(":") for coordinate in coordinates):
            if group in ("dev.udak", "com.h2database"):
                return False
            if group == "org.springframework.boot" and version != boot:
                return False
            if group == "org.springframework" and version != spring:
                return False
    return True


def verify_dependency_structure(report):
    dependencies = report.get("dependencies")
    pins = report.get("manifest_sha512")
    if not isinstance(dependencies, dict) or not isinstance(pins, dict):
        raise InvalidEvidence("INVALID_DEPENDENCY_PROOF")
    digest, lanes = dependencies.get("sha512"), dependencies.get("lanes")
    if (
        dependencies.get("status") != "PASS" or not valid_digest(digest)
        or digest != pins.get(DEPENDENCY_PINS)
        or not valid_dependency_graph(lanes, PIN_LANES)
        or not valid_dependency_graph(dependencies.get("consumer_lanes"), CONSUMER_PIN_LANES)
        or lanes["h2"] != ["com.h2database:h2:2.3.232"]
        or type(dependencies.get("artifacts")) is not int
        or dependencies["artifacts"] != PINNED_DEPENDENCIES
        or len(dependency_coordinates(dependencies)) != PINNED_DEPENDENCIES
    ):
        raise InvalidEvidence("INVALID_DEPENDENCY_PROOF")


def verify_dependency_pins(root_fd, report):
    dependencies = report["dependencies"]
    pins = read_report(root_fd, DEPENDENCY_PINS, expected_digest=dependencies["sha512"])
    records = pins.get("artifacts")
    if (
        pins.get("gradle") != GRADLE_PIN or pins.get("lanes") != dependencies["lanes"]
        or pins.get("consumer_lanes") != dependencies["consumer_lanes"]
        or pins.get("approval") != "DECLARED LICENSES VERIFIED; redistribution NOT GRANTED"
        or not isinstance(records, list) or len(records) != dependencies["artifacts"]
    ):
        raise InvalidEvidence("INVALID_DEPENDENCY_PINS")
    coordinates = [verify_dependency_record(record) for record in records]
    if (
        not valid_coordinates(coordinates)
        or set(coordinates) != dependency_coordinates(dependencies)
    ):
        raise InvalidEvidence("INVALID_DEPENDENCY_PINS")
    hashes = {coordinate: record["sha512"] for coordinate, record in zip(coordinates, records)}
    hashes.update({
        f"dev.udak:{module}:{VERSION}": report["reproducibility"]["artifact_sha512"][prefix + ".jar"]
        for module, prefix in zip(RELEASE_MODULES, ARTIFACT_PREFIXES)
    })
    for proof in (*report["boot_lines"].values(), report["bom_consumer"], *report["negative_consumers"]):
        resolution = proof["resolution"]
        if resolution["artifact_sha512"] != {coordinate: hashes[coordinate] for coordinate in resolution["artifacts"]}:
            raise InvalidEvidence("INVALID_CONSUMED_ARTIFACTS")


def verify_dependency_record(record):
    if (
        not isinstance(record, dict) or not valid_digest(record.get("sha512"))
        or not valid_digest(record.get("pom_sha512"))
        or record.get("published_checksum") not in ("sha512", "sha256", "sha1")
        or not positive_int(record.get("size"), 24 * 1024 * 1024)
    ):
        raise InvalidEvidence("INVALID_DEPENDENCY_PINS")
    parts = [record.get(key) for key in ("group", "name", "version")]
    if any(not isinstance(part, str) or ":" in part for part in parts):
        raise InvalidEvidence("INVALID_DEPENDENCY_PINS")
    coordinate = ":".join(parts)
    if not valid_coordinates([coordinate]):
        raise InvalidEvidence("INVALID_DEPENDENCY_PINS")
    group, name, version = parts
    base = f"{MAVEN_CENTRAL}{group.replace('.', '/')}/{name}/{version}/{name}-{version}"
    if record.get("jar_url") != base + ".jar" or record.get("pom_url") != base + ".pom":
        raise InvalidEvidence("INVALID_DEPENDENCY_PINS")
    chain = record.get("pom_chain")
    if not isinstance(chain, list) or not 1 <= len(chain) <= 5:
        raise InvalidEvidence("INVALID_DEPENDENCY_PINS")
    urls = set()
    for entry in chain:
        if (
            not isinstance(entry, dict) or not valid_digest(entry.get("sha512"))
            or not isinstance(entry.get("url"), str) or len(entry["url"]) > 600
            or not MAVEN_POM.fullmatch(entry["url"]) or entry["url"] in urls
        ):
            raise InvalidEvidence("INVALID_DEPENDENCY_PINS")
        urls.add(entry["url"])
    if chain[0] != {"url": record["pom_url"], "sha512": record["pom_sha512"]}:
        raise InvalidEvidence("INVALID_DEPENDENCY_PINS")
    licenses, resources = record.get("licenses"), record.get("license_resources_sha512")
    if (
        not isinstance(licenses, list) or not 1 <= len(licenses) <= 16
        or any(
            not isinstance(license, dict)
            or any(not isinstance(license.get(key), str) or not 0 < len(license[key]) <= 300
                   or "${" in license[key] for key in ("name", "url"))
            for license in licenses
        )
        or not isinstance(resources, dict) or len(resources) > 8
        or any(
            not isinstance(name, str) or len(name) > MAX_PATH_LENGTH
            or not LICENSE_RESOURCE.fullmatch(name) or not valid_digest(digest)
            for name, digest in resources.items()
        )
    ):
        raise InvalidEvidence("INVALID_DEPENDENCY_PINS")
    return coordinate


def source_inventory(paths):
    if len(paths) > MAX_SOURCE_FILES:
        return False
    modules = set()
    for path in paths:
        if not public_path(path) or not SOURCE_PATH.fullmatch(path):
            return False
        module = path.split("/", 1)[0]
        if module not in SOURCE_MODULES:
            return False
        modules.add(module)
    return REQUIRED_SOURCE_MODULES <= modules


def verify_inputs(root_fd, report):
    groups = (
        ("source_sha512", source_inventory),
        ("harness_sha512", lambda paths: REQUIRED_HARNESS <= paths <= HARNESS),
        ("configuration_sha512", lambda paths: REQUIRED_CONFIGURATION <= paths <= CONFIGURATION),
        ("manifest_sha512", lambda paths: paths == MANIFESTS),
    )
    inputs = {}
    for key, validate_inventory in groups:
        hashes = report.get(key)
        if not isinstance(hashes, dict) or not validate_inventory(hashes.keys()):
            raise InvalidEvidence("INVALID_INPUT_INVENTORY")
        if any(not valid_digest(digest) for digest in hashes.values()):
            raise InvalidEvidence("INVALID_DIGEST")
        inputs.update(hashes)
    budget = MAX_INPUT_BYTES
    for path, digest in sorted(inputs.items()):
        budget -= verify_digest(root_fd, path, digest, min(MAX_SOURCE_BYTES, budget))


def artifact_inventory(report):
    rows = report.get("artifacts")
    if not isinstance(rows, list) or len(rows) != len(ARTIFACTS):
        raise InvalidEvidence("INVALID_ARTIFACT_INVENTORY")
    items = {}
    total_size = 0
    for row in rows:
        if not isinstance(row, dict):
            raise InvalidEvidence("INVALID_ARTIFACT_INVENTORY")
        path, size, digest = row.get("path"), row.get("size"), row.get("sha512")
        if not isinstance(path, str) or path not in ARTIFACTS or path in items:
            raise InvalidEvidence("INVALID_ARTIFACT_INVENTORY")
        if not positive_int(size, MAX_ARTIFACT_BYTES) or not valid_digest(digest):
            raise InvalidEvidence("INVALID_ARTIFACT_RECORD")
        items[path] = (size, digest)
        total_size += size
    if items.keys() != ARTIFACTS or total_size > MAX_ARTIFACT_TOTAL_BYTES:
        raise InvalidEvidence("INVALID_ARTIFACT_INVENTORY")
    return items


def verify_structure(report):
    if (
        not isinstance(report, dict) or type(report.get("schema_version")) is not int
        or report["schema_version"] != 1 or type(report.get("phase")) is not int
        or report["phase"] != 6 or report.get("status") != "PASS"
        or "failure_type" in report or "failed_step" in report or report.get("authorize_publish") is not False
        or any(type(report.get(field)) is not int or report[field] != 0
               for field in ("containers_started", "external_publications"))
    ):
        raise InvalidEvidence("PHASE6_INCOMPLETE")
    steps = report.get("steps")
    if (
        not isinstance(steps, list) or len(steps) != len(VALIDATION_STEPS)
        or any(
            not successful_step(step) or step.get("name") != name
            for step, name in zip(steps, VALIDATION_STEPS)
        )
    ):
        raise InvalidEvidence("INVALID_VALIDATION_STEPS")
    verify_dependency_structure(report)
    verify_boot_contracts(report)
    cleanup, candidate_cleanup = report.get("cleanup"), report.get("candidate_cleanup")
    if (
        not successful_cleanup(cleanup, 20000, 2 * 1024**3)
        or cleanup.get("gradle_daemons_quiesced") is not True
        or not successful_step(cleanup.get("gradle_stop"))
        or cleanup["gradle_stop"].get("name") != "cleanup-gradle-stop"
        or not successful_cleanup(candidate_cleanup, 500, MAX_ARTIFACT_TOTAL_BYTES)
    ):
        raise InvalidEvidence("INVALID_CLEANUP_PROOF")
    compatibility = report.get("api_compatibility")
    if (
        not isinstance(compatibility, dict) or compatibility.get("status") != "PASS"
        or compatibility.get("baseline") != "evidence/PHASE5-VALIDATION.json"
        or not positive_int(compatibility.get("preserved_sources"), MAX_SOURCE_FILES)
        or compatibility.get("prior_published_release") != "NONE"
        or compatibility.get("binary_backward_compatibility") != "NOT RUN; no prior published release"
    ):
        raise InvalidEvidence("INVALID_API_COMPATIBILITY")
    artifacts = artifact_inventory(report)
    expected_hashes = {path: artifacts[path][1] for path in REPOSITORY_ARTIFACTS}
    reproduction = report.get("reproducibility")
    if (
        not isinstance(reproduction, dict) or reproduction.get("status") != "PASS"
        or type(reproduction.get("repackaged_artifacts")) is not int
        or reproduction["repackaged_artifacts"] != len(expected_hashes)
        or reproduction.get("artifact_sha512") != expected_hashes
    ):
        raise InvalidEvidence("INVALID_REPRODUCIBILITY")
    return artifacts


def verify_candidate(root_fd, items):
    missing = 0
    for path, (size, digest) in sorted(items.items()):
        try:
            verify_digest(root_fd, path, digest, size, expected_size=size)
        except FileNotFoundError:
            missing += 1
    if missing == len(items):
        return "NOT AVAILABLE"
    if missing:
        raise InvalidEvidence("PARTIAL_ARTIFACTS")
    return "VERIFIED"


def validate_phase6(root_fd, report):
    artifacts = verify_structure(report)
    verify_inputs(root_fd, report)
    verify_dependency_pins(root_fd, report)
    return verify_candidate(root_fd, artifacts)


def historical_evidence(root_fd):
    history = {}
    for gate, path in HISTORICAL.items():
        try:
            report = read_report(root_fd, path)
        except FileNotFoundError:
            history[gate] = "NOT AVAILABLE"
            continue
        if report.get("gate") != gate or report.get("status") != "PASS":
            raise InvalidEvidence("INVALID_HISTORICAL_EVIDENCE")
        history[gate] = "HISTORICAL PASS"
    return history


def inspect(root_fd):
    candidate = validate_phase6(root_fd, read_report(root_fd, VALIDATION))
    return {
        "status": "VERIFIED_EVIDENCE",
        "default_mode": "OBSERVE",
        "default_rewrite": "DENY",
        "boot_lines": {"boot3": "VERIFIED_EVIDENCE", "boot4": "VERIFIED_EVIDENCE"},
        "candidate_artifacts": candidate,
        "historical_gates": historical_evidence(root_fd),
    }


def release_gate(root_fd):
    policy = read_report(root_fd, POLICY)
    if any(policy.get(key) != value for key, value in (BLOCKING_POLICY | RELEASE_POLICY).items()):
        raise InvalidEvidence("INVALID_RELEASE_POLICY")
    try:
        read_report(root_fd, APPROVALS)
        approvals = "UNVERIFIED"
    except FileNotFoundError:
        approvals = "MISSING"
    try:
        report = read_report(root_fd, VALIDATION)
    except FileNotFoundError:
        candidate = "NOT AVAILABLE"
        verification = "NOT AVAILABLE"
    else:
        candidate = validate_phase6(root_fd, report)
        verification = "VERIFIED_EVIDENCE"
    return {
        "status": "BLOCKED",
        "authorize_publish": False,
        "phase6_evidence": verification,
        "candidate_artifacts": candidate,
        "operator_approvals": approvals,
        "blockers": dict(BLOCKING_POLICY),
    }


class PublicArgumentParser(argparse.ArgumentParser):
    def error(self, _message):
        self.exit(2, "INVALID_ARGUMENTS\n")


def print_text(data, prefix=""):
    for key, value in data.items():
        label = f"{prefix}{key}"
        if isinstance(value, dict):
            print_text(value, prefix=f"{label}.")
        else:
            print(f"{label}={json.dumps(value) if isinstance(value, bool) else value}")


def main(command, argv=None, root=ROOT):
    is_gate = command == "release-gate"
    if is_gate:
        parser = PublicArgumentParser(
            prog="release-gate.py", description="Check local release prerequisites.", allow_abbrev=False,
        )
    else:
        parser = PublicArgumentParser(
            prog="udak-cli.py", description="Inspect local verification evidence.", allow_abbrev=False,
        )
        parser.add_argument("command", choices=("inspect",))
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    exit_code = 2 if is_gate else 0
    try:
        with directory(root.parts[1:]) as root_fd:
            result = release_gate(root_fd) if is_gate else inspect(root_fd)
    except (OSError, InvalidEvidence) as error:
        if isinstance(error, InvalidEvidence):
            reason = str(error)
        elif isinstance(error, FileNotFoundError):
            reason = "MISSING_INPUT"
        else:
            reason = "UNSAFE_OR_UNREADABLE_INPUT"
        result = {"status": "BLOCKED", "authorize_publish": False} if is_gate else {"status": "INVALID"}
        result["error"] = reason
        exit_code = 1
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_text(result)
    return exit_code
