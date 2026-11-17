#!/usr/bin/env python3
"""Bounded CRUD/Spring JDBC/H2 checks and four-DB verification foundation."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import time
import traceback
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "evidence/PHASE2-VALIDATION.json"
spec = importlib.util.spec_from_file_location("phase1_harness", ROOT / "tools/run-phase1.py")
guard = importlib.util.module_from_spec(spec)
sys.dont_write_bytecode = True
spec.loader.exec_module(guard)


def fetch(url, maximum):
    allowed = ("https://repo.maven.apache.org/maven2/org/springframework/",
               "https://repo.maven.apache.org/maven2/com/h2database/h2/")
    if not url.startswith(allowed):
        raise ValueError("Unapproved dependency origin")
    with urllib.request.urlopen(url, timeout=12) as response:
        if not response.geturl().startswith("https://repo.maven.apache.org/"):
            raise ValueError("Dependency redirect rejected")
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Dependency size limit exceeded")
    return data


def dependencies(work, manifest):
    paths, evidence = [], []
    for item in manifest["artifacts"]:
        jar, pom = fetch(item["jar_url"], 5_000_000), fetch(item["pom_url"], 200_000)
        published = fetch(item["jar_url"] + item["published_checksum_extension"], 1024).decode().split()[0]
        algorithm = item["published_checksum_algorithm"]
        if algorithm not in ("sha512", "sha1"):
            raise ValueError("Unapproved published checksum algorithm")
        if guard.digest(jar) != item["jar_sha512"] or hashlib.new(algorithm, jar).hexdigest() != published:
            raise ValueError("JAR integrity mismatch")
        if guard.digest(pom) != item["pom_sha512"]:
            raise ValueError("POM integrity mismatch")
        xml = ET.fromstring(pom)
        namespace = xml.tag.split("}")[0].lstrip("{") if "}" in xml.tag else None
        ns, prefix = ({"m": namespace}, "m:") if namespace else ({}, "")
        licenses = [node.findtext(prefix + "name", namespaces=ns)
                    for node in xml.findall(prefix + "licenses/" + prefix + "license", ns)]
        graph = [node.findtext(prefix + "groupId", namespaces=ns) + ":" +
                 node.findtext(prefix + "artifactId", namespaces=ns) + ":" +
                 node.findtext(prefix + "version", namespaces=ns)
                 for node in xml.findall(prefix + "dependencies/" + prefix + "dependency", ns)
                 if node.findtext(prefix + "scope", default="compile", namespaces=ns) in ("compile", "runtime")
                 and node.findtext(prefix + "optional", default="false", namespaces=ns) != "true"]
        if licenses != item["licenses"] or graph != item["runtime_dependencies"]:
            raise ValueError("Dependency license graph changed")
        path = work / (item["artifact"] + ".jar")
        path.write_bytes(jar)
        paths.append(path)
        with zipfile.ZipFile(path) as archive:
            notices = [n for n in archive.namelist() if "LICENSE" in n.upper() or "NOTICE" in n.upper()]
            majors = set()
            for entry in archive.infolist():
                if entry.filename.endswith(".class") and not entry.filename.startswith("META-INF/versions/"):
                    with archive.open(entry) as stream:
                        majors.add(int.from_bytes(stream.read(8)[6:8], "big"))
            if not majors or max(majors) > 61 or notices != item["license_entries"]:
                raise ValueError("Dependency baseline or notice changed")
        evidence.append({"coordinate": item["coordinate"], "jar_sha512": guard.digest(jar),
                         "pom_sha512": guard.digest(pom), "jar_bytes": len(jar), "pom_bytes": len(pom),
                         "licenses": licenses, "scope": item["scope"], "runtime_dependencies": graph,
                         "published_checksum_algorithm": algorithm, "published_checksum_verified": True,
                         "base_class_major_versions": sorted(majors), "upstream_notice_entries": notices})
    license_data = (ROOT / manifest["h2_license_file"]).read_bytes()
    if guard.digest(license_data) != manifest["h2_license_sha512"]:
        raise ValueError("H2 license bundle mismatch")
    return paths, {"status": "PASS", "artifacts": evidence, "h2_selected_license": "MPL-2.0",
                   "h2_license_sha512": guard.digest(license_data),
                   "product_distribution_approval": "NOT GRANTED; separate release gate"}


def copy_resources(work):
    target = work / "test-resources"
    for module in ("jdbc-spring", "db-testkit"):
        source = ROOT / module / "src/test/resources"
        if source.is_dir():
            for item in source.rglob("*"):
                if item.is_file():
                    if item.is_symlink() or re.search(r"(?:^\.env|\.env(?:\.|$))", item.name):
                        raise ValueError("Unsafe test resource")
                    destination = target / item.relative_to(source)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(item, destination)
    return target


def main():
    started = time.monotonic()
    result = {"schema_version": 1, "phase": 2, "status": "FAIL", "steps": [],
              "scope": "minimal API, actual Spring JDBC/H2 executor and four-real-DB verification foundation",
              "full_phase2_g2": "NOT PASSED; real DB profiles require separate execution",
              "limits": {"wall_seconds": 180, "child_cpu_seconds": 30, "heap_mib": 256,
                         "metaspace_mib": 128, "active_cpus": 2, "download_bytes_per_file": 5_000_000,
                         "workspace_files": 2000, "workspace_bytes": 134217728},
              "containers_started": 0, "existing_containers_modified": 0,
              "worktrees_created": 0, "worktrees_removed": 0,
              "not_run": ["four real database servers", "Gradle task execution", "Spring Boot/JPA/MyBatis demo",
                          "performance/load tests", "product distribution approval"]}
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, guard.interrupted)
    signal.alarm(180)
    try:
        result["cleanup_probes"] = []
        for name in ("failure", "timeout", "signal", "exception", "descendant"):
            result["stage"] = "cleanup-probe-" + name
            result["cleanup_probes"].append(guard.cleanup_probe(name))
        result["stage"] = "documentation"
        result["documentation"] = guard.verify_documents()
        with guard.workspace("udak-phase2-") as (work, cleanup):
            result["cleanup"] = cleanup
            os.putenv("TMPDIR", str(work))
            os.putenv("_JAVA_OPTIONS", "-Xmx256m -XX:MaxMetaspaceSize=128m -XX:ActiveProcessorCount=2")
            manifest = json.loads((ROOT / "tools/phase2-dependencies.json").read_text())
            result["stage"] = "dependencies"
            jars, result["dependencies"] = dependencies(work, manifest)
            parser_jar, result["phase1_dependency"] = guard.dependency_checks(
                json.loads((ROOT / "tools/phase1-dependencies.json").read_text()), work)
            jars.append(parser_jar)
            core = list((ROOT / "core/src/main/java").rglob("*.java"))
            if any(re.search(r"^import (?:org\.springframework|org\.hibernate|org\.apache\.ibatis|net\.sf\.jsqlparser)", p.read_text(), re.M) for p in core):
                raise ValueError("Core dependency boundary violated")
            result["stage"] = "java-contracts"
            result["steps"].append(guard.run_step("core-smoke", ["./tools/run-core-smoke.sh"], work))
            sources = []
            for module in ("core", "sql-jsqlparser", "udak-api", "jdbc-spring", "db-testkit"):
                sources.extend(sorted((ROOT / module / "src").rglob("*.java")))
            classes = work / "classes"
            classes.mkdir()
            classpath = os.pathsep.join(str(jar) for jar in jars)
            runtime_probe = work / "Phase2Runtime.java"
            runtime_probe.write_text('public class Phase2Runtime { public static void main(String[] a) { System.out.println(System.getProperty("java.version")); } }')
            result["steps"].append(guard.run_step("javac", ["javac", "--release", "17", "-cp", classpath,
                                                           "-d", str(classes)] + [str(p) for p in sources] + [str(runtime_probe)], work))
            resources = copy_resources(work)
            classpath = str(classes) + os.pathsep + str(resources) + os.pathsep + classpath
            result["steps"].append(guard.run_step("runtime-version", ["java", "-cp", classpath, "Phase2Runtime"], work))
            version = re.search(r"^\d+(?:\.\d+){0,3}(?:[+_-][A-Za-z0-9.-]+)?$", (work / "runtime-version.output").read_text(), re.M)
            result["java_runtime_version"] = version.group() if version else "UNRECOGNIZED"
            result["java_compile_release"] = 17
            for name, main_class in [("basic-contract", "dev.udak.core.CompilerContractTest"),
                                     ("external-contract", "dev.udak.jsqlparser.JSqlParserCompilerTest"),
                                     ("crud-api", "dev.udak.api.CrudApiContractTest"),
                                     ("spring-jdbc-h2", "dev.udak.jdbc.SpringJdbcExecutorTest"),
                                     ("db-foundation-h2", "dev.udak.testkit.DatabaseFoundationTest"),
                                     ("real-db-inventory", "dev.udak.testkit.RealDatabaseContractRunner")]:
                result["steps"].append(guard.run_step(name, ["java", "-cp", classpath, main_class], work))
            inventory = (work / "real-db-inventory.output").read_text().splitlines()
            profiles = ("POSTGRESQL", "MYSQL", "SQLSERVER", "ORACLE")
            result["real_database_profiles"] = {}
            for name in profiles:
                if name + " NOT RUN: DEDICATED_PROVIDER_REQUIRED" not in inventory:
                    raise ValueError("Real-DB inventory gate mismatch")
                result["real_database_profiles"][name] = {"status": "NOT RUN", "reason": "DEDICATED_PROVIDER_REQUIRED"}
            result["source_sha512"] = {str(p.relative_to(ROOT)): guard.digest(p.read_bytes()) for p in sources}
            result["harness_sha512"] = {"tools/run-phase2.py": guard.digest(Path(__file__).read_bytes()),
                                       "tools/run-phase1.py": guard.digest((ROOT / "tools/run-phase1.py").read_bytes())}
            result["manifest_sha512"] = guard.digest((ROOT / "tools/phase2-dependencies.json").read_bytes())
            result["status"] = "PASS"
    except Exception as error:
        result["status"] = "FAIL"
        result["failure_type"] = type(error).__name__
        result["failure_errno"] = getattr(error, "errno", None)
        result["failure_locations"] = [{"file": Path(frame.filename).name, "line": frame.lineno,
                                         "function": frame.name}
                                        for frame in traceback.extract_tb(error.__traceback__)]
        if isinstance(error, RuntimeError) and str(error).startswith("{"):
            result["failed_step"] = json.loads(str(error))
    finally:
        signal.alarm(0)
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        REPORT.parent.mkdir(exist_ok=True)
        if REPORT.exists():
            old = REPORT.read_bytes()
            archive = ROOT / ".git/udak-phase2/previous-reports"
            archive.mkdir(parents=True, exist_ok=True)
            (archive / (hashlib.sha256(old).hexdigest() + ".json")).write_bytes(old)
        REPORT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("status", "steps", "cleanup", "failure_type", "failed_step", "real_database_profiles") if key in result}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
