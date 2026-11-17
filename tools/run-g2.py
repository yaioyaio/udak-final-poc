#!/usr/bin/env python3
"""Bounded pinned-driver checks and explicit, dedicated four-database execution."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import sys
import time
import traceback
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "evidence/G2-VALIDATION.json"
spec = importlib.util.spec_from_file_location("phase2_harness", ROOT / "tools/run-phase2.py")
phase2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phase2)
guard = phase2.guard
PROFILES = ("POSTGRESQL", "MYSQL", "SQLSERVER", "ORACLE")
SCENARIOS = ("INSERT_NULL", "READ_NULL", "UPDATE", "INSERT_SECOND", "INSERT_THIRD",
             "PAGE", "BIND", "COMMIT", "ROLLBACK", "DELETE")


def fetch(url, maximum):
    approved = ("https://repo.maven.apache.org/maven2/",
                "https://raw.githubusercontent.com/protocolbuffers/protobuf/v36.1/LICENSE",
                "https://raw.githubusercontent.com/microsoft/mssql-jdbc/v13.6.2/LICENSE")
    if not url.startswith(approved):
        raise ValueError("Dependency origin rejected")
    with urllib.request.urlopen(url, timeout=12) as response:
        if not response.geturl().startswith(approved):
            raise ValueError("Dependency redirect rejected")
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Dependency size exceeded")
    return data


def direct_dependencies(xml):
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    dependencies = []
    for node in xml.findall("m:dependencies/m:dependency", ns):
        if node.findtext("m:scope", "compile", ns) not in ("compile", "runtime"):
            continue
        if node.findtext("m:optional", "false", ns) == "true":
            continue
        dependencies.append(":".join(node.findtext("m:" + key, namespaces=ns)
                                     for key in ("groupId", "artifactId", "version")))
    return dependencies


def dependencies(work, manifest):
    paths, evidence, total = [], [], 0
    coordinates = {item["coordinate"] for item in manifest["artifacts"]}
    for item in manifest["artifacts"]:
        jar = fetch(item["jar_url"], 10 * 1024 * 1024)
        pom = fetch(item["pom_url"], 200_000)
        total += len(jar) + len(pom)
        if total > 30 * 1024 * 1024:
            raise ValueError("Dependency total exceeded")
        if guard.digest(jar) != item["jar_sha512"] or guard.digest(pom) != item["pom_sha512"]:
            raise ValueError("Dependency integrity mismatch")
        algorithm = item["published_checksum_algorithm"]
        if algorithm not in ("sha512", "sha1"):
            raise ValueError("Published checksum algorithm rejected")
        published = fetch(item["jar_url"] + item["published_checksum_extension"], 1024).decode().split()[0]
        if hashlib.new(algorithm, jar).hexdigest() != published:
            raise ValueError("Published checksum mismatch")
        pom_checksum = item["official_pom_checksum"]
        if (pom_checksum["algorithm"] not in ("sha1", "sha512")
                or pom_checksum["url"] != item["pom_url"] + "." + pom_checksum["algorithm"]):
            raise ValueError("POM checksum origin rejected")
        published_pom = fetch(pom_checksum["url"], 1024).decode().split()[0]
        if hashlib.new(pom_checksum["algorithm"], pom).hexdigest() != published_pom:
            raise ValueError("Published POM checksum mismatch")
        xml = ET.fromstring(pom)
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        licenses = [n.findtext("m:name", namespaces=ns) for n in xml.findall("m:licenses/m:license", ns)]
        graph = direct_dependencies(xml)
        if licenses != item["licenses"] or graph != item["runtime_dependencies"] or not set(graph) <= coordinates:
            raise ValueError("License or dependency graph changed")
        path = work / (item["artifact"] + ".jar")
        path.write_bytes(jar)
        with zipfile.ZipFile(path) as archive:
            entries = {name: guard.digest(archive.read(name)) for name in archive.namelist()
                       if not name.endswith("/") and not name.endswith(".class")
                       and Path(name).name.upper().startswith(("LICENSE", "NOTICE", "COPYING"))}
            majors = set()
            for entry in archive.infolist():
                if entry.filename.endswith(".class") and not entry.filename.startswith("META-INF/versions/"):
                    with archive.open(entry) as stream:
                        majors.add(int.from_bytes(stream.read(8)[6:8], "big"))
        if entries != item["license_entries"] or sorted(majors) != item["base_class_major_versions"] or max(majors) > 61:
            raise ValueError("License bundle or Java baseline changed")
        paths.append(path)
        evidence.append({"coordinate": item["coordinate"], "jar_sha512": guard.digest(jar),
                         "pom_sha512": guard.digest(pom), "runtime_dependencies": graph,
                         "license_entries_verified": len(entries), "base_class_major_versions": sorted(majors),
                         "published_checksum_verified": True})
    upstream = []
    for item in manifest["upstream_license_checks"]:
        data = fetch(item["url"], item["maximum_bytes"])
        if guard.digest(data) != item["sha512"]:
            raise ValueError("Upstream license changed")
        upstream.append({"url": item["url"], "sha512": guard.digest(data), "status": "PASS"})
    return paths, {"status": "PASS", "artifacts": evidence, "download_bytes": total,
                   "upstream_license_checks": upstream,
                   "redistribution_approval": "NOT GRANTED"}


def load_drivers(work, jars):
    # Load each actual pinned driver on the current JVM without constructing a DataSource or connecting.
    probe = work / "G2DriverProbe.java"
    probe.write_text('''public final class G2DriverProbe {
        public static void main(String[] args) throws Exception {
            String[] names = {"org.postgresql.Driver", "com.mysql.cj.jdbc.Driver",
                "com.microsoft.sqlserver.jdbc.SQLServerDriver", "oracle.jdbc.OracleDriver"};
            for (String name : names) {
                Object driver = Class.forName(name).getDeclaredConstructor().newInstance();
                if (!(driver instanceof java.sql.Driver)) throw new IllegalStateException();
            }
            System.out.println("DRIVER_LOAD=4;CONNECTIONS=0");
        }
    }''')
    classes = work / "probe-classes"
    classes.mkdir()
    classpath = os.pathsep.join(str(p) for p in jars)
    steps = [guard.run_step("javac-drivers", ["javac", "-J-Xmx256m", "-J-XX:MaxMetaspaceSize=128m",
                           "--release", "17", "-cp", classpath, "-d", str(classes), str(probe)], work)]
    steps.append(guard.run_step("driver-load", ["java", "-Xmx256m", "-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2",
                                "-cp", str(classes) + os.pathsep + classpath, "G2DriverProbe"], work))
    if (work / "driver-load.output").read_text().strip() != "DRIVER_LOAD=4;CONNECTIONS=0":
        raise ValueError("Driver load protocol invalid")
    return steps


def parse_profile(profile, output, exit_code):
    lines = output.splitlines()
    # Arbitrary third-party output is never copied into evidence.
    if lines and lines[0] == profile + " PASS" and exit_code == 0:
        expected = {"SERVER_VERSION", "DRIVER_VERSION", "CHECKS", "CLEANUP"}
        values = dict(line.split("=", 1) for line in lines[1:] if "=" in line and not line.startswith("SCENARIO="))
        scenarios = [line.removeprefix("SCENARIO=") for line in lines if line.startswith("SCENARIO=")]
        if (set(values) != expected or not re.fullmatch(r"[0-9]+\.[0-9]+", values["SERVER_VERSION"])
                or not re.fullmatch(r"[0-9]+\.[0-9]+", values["DRIVER_VERSION"])
                or values["CHECKS"] != "10" or values["CLEANUP"] != "CONFIRMED"
                or scenarios != [name + ":PASS" for name in SCENARIOS] or len(lines) != 15):
            return {"status": "FAIL", "reason": "EVIDENCE_PROTOCOL_INVALID", "cleanup": "UNCONFIRMED"}
        return {"status": "PASS", "server_version": values["SERVER_VERSION"],
                "driver_version": values["DRIVER_VERSION"], "checks": 10, "cleanup": "CONFIRMED",
                "scenarios": {name: "PASS" for name in SCENARIOS}}
    match = re.fullmatch(re.escape(profile) + r" (NOT RUN|FAIL): ([A-Z_]+)(?: FIXTURE=(udak_p2_[0-9a-f]{12}))?", lines[0]) if lines else None
    if match and exit_code == 1 and len(lines) == 1:
        result = {"status": match[1], "reason": match[2]}
        if match[3]:
            result.update(fixture=match[3], cleanup="UNCONFIRMED")
        return result
    return {"status": "FAIL", "reason": "EXECUTION_OR_PROTOCOL_ERROR", "cleanup": "UNCONFIRMED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Explicitly run all four approved dedicated providers")
    parser.add_argument("--provider-jar", action="append", default=[], help="Owner-reviewed provider JAR; never a secret file")
    args = parser.parse_args()
    if args.run != bool(args.provider_jar) or len(args.provider_jar) > 4:
        parser.error("--run requires one to four approved --provider-jar arguments")
    provider_paths = [Path(value) for value in args.provider_jar]
    for path in provider_paths:
        if (path.suffix != ".jar" or re.search(r"(?:^\.env|\.env(?:\.|$))", path.name)
                or path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024):
            parser.error("Provider artifact rejected")
    started = time.monotonic()
    result = {"schema_version": 1, "gate": "G2", "status": "INCOMPLETE", "steps": [],
              "scope": "pinned JDBC drivers and minimal dedicated CRUD/Query/Spring transaction contract",
              "limits": {"wall_seconds": 360, "per_profile_seconds": 45, "child_cpu_seconds": 30,
                         "heap_mib": 256, "metaspace_mib": 128, "active_cpus": 2, "parallel_profiles": 1,
                         "workspace_files": 2000, "workspace_bytes": 134217728},
              "containers_started": 0, "existing_containers_modified": 0,
              "worktrees_created": 0, "worktrees_removed": 0,
              "real_database_profiles": {name: {"status": "NOT RUN", "reason": "DEDICATED_PROVIDER_REQUIRED"} for name in PROFILES},
              "not_run": ["Gradle", "Spring Boot/JPA/MyBatis demo", "performance/load tests", "product distribution approval"]}
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, guard.interrupted)
    signal.alarm(360)
    try:
        manifest_path = ROOT / "tools/g2-dependencies.json"
        manifest = json.loads(manifest_path.read_text())
        result["manifest_sha512"] = guard.digest(manifest_path.read_bytes())
        with guard.workspace("udak-g2-") as (work, cleanup):
            result["cleanup"] = cleanup
            os.putenv("TMPDIR", str(work))
            # Remove inherited JVM launch injection without reading its values; use bounded flags below.
            for key in ("_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS"):
                os.unsetenv(key)
            jars, result["driver_dependencies"] = dependencies(work, manifest)
            result["steps"].append(guard.run_step("evidence-protocol-tests",
                                  [sys.executable, "tools/test-g2-harness.py"], work))
            result["steps"].extend(load_drivers(work, jars))
            if args.run:
                spring, result["spring_dependencies"] = phase2.dependencies(work, json.loads((ROOT / "tools/phase2-dependencies.json").read_text()))
                spring = [p for p in spring if p.name != "h2.jar"]
                # Main classes/resources only: the H2 test provider registration cannot enter live mode.
                sources = [p for module in ("core", "udak-api", "jdbc-spring", "db-testkit")
                           for p in sorted((ROOT / module / "src/main/java").rglob("*.java"))]
                classes = work / "classes"
                classes.mkdir()
                classpath = os.pathsep.join(str(p) for p in jars + spring)
                result["steps"].append(guard.run_step("javac-live", ["javac", "-J-Xmx256m", "-J-XX:MaxMetaspaceSize=128m", "--release", "17", "-cp", classpath,
                                         "-d", str(classes)] + [str(p) for p in sources], work))
                classpath = os.pathsep.join([str(classes), classpath] + [str(p.resolve()) for p in provider_paths])
                versions = manifest["metadata_versions"]
                for name in PROFILES:
                    fixture = "udak_p2_" + uuid.uuid4().hex[:12]
                    # Durable intent precedes CREATE and survives JVM/Python timeout or interruption.
                    intent = {"profile": name, "fixture": fixture, "execution_started": True,
                              "status": "FAIL", "reason": "EXECUTION_INTERRUPTED_OR_UNCONFIRMED", "cleanup": "UNCONFIRMED",
                              "started_at_utc": datetime.now(timezone.utc).isoformat()}
                    journal = ROOT / ".git/udak-g2/live-intents" / (uuid.uuid4().hex + ".json")
                    journal.parent.mkdir(parents=True, exist_ok=True)
                    with journal.open("x") as stream:
                        stream.write(json.dumps(intent, indent=2) + "\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                    result["real_database_profiles"][name] = dict(intent)
                    command = ["java", "-Xmx256m", "-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2", "-cp", classpath,
                               "dev.udak.testkit.RealDatabaseContractRunner", "--run", name, "--driver-version", versions[name],
                               "--fixture", fixture]
                    try:
                        step = guard.run_step("live-" + name, command, work, timeout=45)
                    except RuntimeError as error:
                        try:
                            step = json.loads(str(error))
                        except (ValueError, TypeError):
                            raise RuntimeError("Bounded live execution failed") from None
                    result["steps"].append(step)
                    profile = parse_profile(name, (work / ("live-" + name + ".output")).read_text(), step["exit_code"])
                    profile.update(fixture=fixture, execution_started=True)
                    if profile["status"] == "NOT RUN":
                        profile["cleanup"] = "NOT_CREATED"
                    elif profile.get("reason") == "SCENARIO_FAILED":
                        profile["cleanup"] = "CONFIRMED"
                    intent.update(profile)
                    journal.write_text(json.dumps(intent, indent=2) + "\n")
                    result["real_database_profiles"][name] = profile
                    if profile["status"] != "PASS":
                        # Do not begin another DB operation after a failure or uncertain cleanup.
                        break
                result["source_sha512"] = {str(p.relative_to(ROOT)): guard.digest(p.read_bytes()) for p in sources}
            statuses = [p["status"] for p in result["real_database_profiles"].values()]
            result["status"] = "PASS" if statuses == ["PASS"] * 4 else ("FAIL" if "FAIL" in statuses else "INCOMPLETE")
    except Exception as error:
        result.update(status="FAIL", failure_type=type(error).__name__,
                      failure_locations=[{"file": Path(frame.filename).name, "line": frame.lineno,
                                          "function": frame.name} for frame in traceback.extract_tb(error.__traceback__)])
    finally:
        signal.alarm(0)
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["harness_sha512"] = guard.digest(Path(__file__).read_bytes())
        if REPORT.exists():
            old = REPORT.read_bytes()
            archive = ROOT / ".git/udak-g2/previous-reports"
            archive.mkdir(parents=True, exist_ok=True)
            (archive / (hashlib.sha256(old).hexdigest() + ".json")).write_bytes(old)
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "real_database_profiles", "cleanup", "failure_type") if k in result}))
    return {"PASS": 0, "INCOMPLETE": 2, "FAIL": 1}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
