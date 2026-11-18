#!/usr/bin/env python3
"""Bounded Observe contracts and real Hibernate/MyBatis/Spring JDBC compatibility."""
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
import xml.etree.ElementTree as ET
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "evidence/PHASE3-VALIDATION.json"
spec = importlib.util.spec_from_file_location("phase3_guard", ROOT / "tools/run-phase1.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
CHECKS = ("SHARED_RESOURCE", "EXISTING_SERVICE", "FLUSH_VISIBILITY", "JPA_CACHE", "MYBATIS_CACHE",
          "MIXED_COMMIT", "MIXED_ROLLBACK", "RESULT_MAPPING", "OBSERVATION_METADATA", "LISTENER_FAILURE")


def fetch(url, maximum):
    origin = "https://repo.maven.apache.org/maven2/"
    if not url.startswith(origin):
        raise ValueError("Dependency origin rejected")
    with urllib.request.urlopen(url, timeout=12) as response:
        if not response.geturl().startswith(origin):
            raise ValueError("Dependency redirect rejected")
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Dependency bounds exceeded")
    return data


def dependencies(work):
    manifest_path = ROOT / "tools/phase3-dependencies.json"
    manifest = json.loads(manifest_path.read_text())
    jars, evidence, total = [], [], 0
    for model in manifest["metadata_models"]:
        pom = fetch(model["pom_url"], 600000)
        if guard.digest(pom) != model["pom_sha512"]:
            raise ValueError("Dependency POM changed")
    for item in manifest["artifacts"]:
        jar = fetch(item["jar_url"], 20 * 1024**2)
        total += len(jar)
        if total > 60 * 1024**2 or guard.digest(jar) != item["jar_sha512"]:
            raise ValueError("Dependency integrity or bounds failed")
        checksum = item["published_checksum"]
        if checksum["algorithm"] not in ("sha1", "sha512"):
            raise ValueError("Published checksum algorithm rejected")
        published = fetch(item["jar_url"] + checksum["extension"], 1024).decode().split()[0]
        if hashlib.new(checksum["algorithm"], jar).hexdigest() != published:
            raise ValueError("Published checksum failed")
        path = work / (item["artifact"] + "-" + item["version"] + ".jar")
        path.write_bytes(jar)
        with zipfile.ZipFile(path) as archive:
            notices = {n: guard.digest(archive.read(n)) for n in archive.namelist()
                       if not n.endswith(("/", ".class")) and Path(n).name.upper().startswith(("LICENSE", "NOTICE", "COPYING"))}
            majors = set()
            for entry in archive.infolist():
                if entry.filename.endswith(".class") and not entry.filename.startswith("META-INF/versions/"):
                    with archive.open(entry) as stream:
                        majors.add(int.from_bytes(stream.read(8)[6:8], "big"))
        if notices != item["license_entries"] or sorted(majors) != item["base_class_major_versions"] or max(majors) > 61:
            raise ValueError("Dependency license or Java baseline changed")
        jars.append(path)
        evidence.append({"coordinate": item["coordinate"], "jar_sha512": guard.digest(jar),
                         "pom_sha512": item["pom_sha512"], "effective_licenses": item["effective_licenses"],
                         "notice_entries_verified": len(notices), "published_checksum_verified": True})
    return jars, {"status": "PASS", "artifacts": evidence, "jar_bytes": total,
                  "manifest_sha512": guard.digest(manifest_path.read_bytes()), "redistribution_approval": "NOT GRANTED"}


def build(work):
    jars, dependency_evidence = dependencies(work)
    sources = []
    for name in ("core", "observe-core", "legacy-observe", "legacy-compat-testkit"):
        sources += sorted((ROOT / name / "src").rglob("*.java"))
    sources += [ROOT / "spring-boot-demo/src/main/java/dev/udak/demo" / (name + ".java")
                for name in ("UserEntity", "UserJpaRepository", "UserMapper", "MixedUserService")]
    for name in ("core", "observe-core"):
        for path in (ROOT / name / "src/main/java").rglob("*.java"):
            if re.search(r"^import (?:org\.springframework|org\.hibernate|org\.apache\.ibatis|net\.sf\.jsqlparser)", path.read_text(), re.M):
                raise ValueError("Core dependency boundary violated")
    classes = work / "classes"
    classes.mkdir()
    dependencies_path = os.pathsep.join(str(p) for p in jars)
    step = guard.run_step("compile-phase3", ["javac", "-J-Xmx256m", "-J-XX:MaxMetaspaceSize=128m", "-J-XX:ActiveProcessorCount=2", "--release", "17",
                          "-cp", dependencies_path, "-d", str(classes)] + [str(p) for p in sources], work)
    isolated = work / "observe-jdk-only"
    isolated.mkdir()
    step["observe_jdk_only_compile"] = guard.run_step("compile-observe-jdk-only", ["javac", "-J-Xmx256m",
                          "-J-XX:MaxMetaspaceSize=128m", "-J-XX:ActiveProcessorCount=2", "--release", "17", "-d", str(isolated)]
                          + [str(p) for p in sorted((ROOT / "observe-core/src").rglob("*.java"))], work)
    return os.pathsep.join([str(classes), dependencies_path]), sources, dependency_evidence, step


def protocol(profile, text, exit_code):
    lines = text.splitlines()
    expected = [profile + " PASS", "CHECKS=10", "CLEANUP=CONFIRMED"] + ["SCENARIO=" + name + ":PASS" for name in CHECKS]
    if exit_code == 0 and lines == expected:
        return {"status": "PASS", "checks": 10, "cleanup": "CONFIRMED", "scenarios": {name: "PASS" for name in CHECKS}}
    match = re.fullmatch(re.escape(profile) + r" FAIL: ([A-Z_]+)", lines[0]) if lines else None
    return {"status": "FAIL", "reason": match[1] if match else "INVALID_PROTOCOL_OR_EXIT", "cleanup": "UNCONFIRMED"}


def main():
    started = time.monotonic()
    result = {"schema_version": 1, "phase": 3, "status": "FAIL", "steps": [],
              "scope": "Observe adapters and actual same-DataSource Hibernate/MyBatis/JdbcTemplate semantics",
              "limits": {"wall_seconds": 240, "child_cpu_seconds": 30, "heap_mib": 256,
                         "metaspace_mib": 128, "active_cpus": 2, "workspace_files": 2000, "workspace_bytes": 134217728},
              "java_compile_release": 17, "containers_started": 0, "existing_resources_modified": 0,
              "not_run": ["four real databases (separate managed runner)", "Gradle task execution", "Spring Boot autoconfiguration",
                          "performance/load tests", "product redistribution approval"]}
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, guard.interrupted)
    signal.alarm(240)
    try:
        result["documentation"] = guard.verify_documents()
        with guard.workspace("udak-phase3-") as (work, cleanup):
            result["cleanup"] = cleanup
            os.putenv("TMPDIR", str(work))
            for key in ("_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS"):
                os.unsetenv(key)
            os.putenv("_JAVA_OPTIONS", "-Xmx256m -XX:MaxMetaspaceSize=128m -XX:ActiveProcessorCount=2")
            result["steps"].append(guard.run_step("core-smoke", ["./tools/run-core-smoke.sh"], work))
            os.unsetenv("_JAVA_OPTIONS")
            classpath, sources, result["dependencies"], compile_step = build(work)
            result["steps"].append(compile_step)
            java = ["java", "-Xmx256m", "-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2", "-cp", classpath]
            for name, cls in [("core-contract", "dev.udak.core.CompilerContractTest"),
                              ("observe-contract", "dev.udak.observe.ObserveContractTest"),
                              ("adapter-contract", "dev.udak.observe.LegacyObserveAdapterContractTest"),
                              ("compatibility-h2", "dev.udak.compat.LegacyCompatibilityTest")]:
                try:
                    command = java + [cls]
                    if name == "observe-contract":
                        command = java[:4] + ["-cp", str(work / "observe-jdk-only"), cls]
                    step = guard.run_step(name, command, work, timeout=90 if name == "compatibility-h2" else 30)
                except RuntimeError as error:
                    step = json.loads(str(error))
                    result["steps"].append(step)
                    if name == "compatibility-h2":
                        safe = re.compile(r"DIAGNOSTIC=[A-Za-z0-9_.$]+(?: at dev\.udak\.[A-Za-z0-9_.$]+:[0-9]+)?$")
                        result["compatibility_diagnostics"] = [line for line in (work / (name + ".output")).read_text().splitlines() if safe.fullmatch(line)][:5]
                    raise
                count = re.search(r"(?:assertions|checks): ([0-9]+)", (work / (name + ".output")).read_text())
                if count:
                    step["assertions"] = int(count[1])
                result["steps"].append(step)
            result["h2"] = protocol("H2", (work / "compatibility-h2.output").read_text(), 0)
            if result["h2"]["status"] != "PASS":
                raise ValueError("Compatibility evidence protocol failed")
            result["source_sha512"] = {str(p.relative_to(ROOT)): guard.digest(p.read_bytes()) for p in sources}
            result["status"] = "PASS"
    except Exception as error:
        result.update(failure_type=type(error).__name__, failure_locations=[{"file": Path(f.filename).name, "line": f.lineno} for f in traceback.extract_tb(error.__traceback__)])
    finally:
        signal.alarm(0)
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["harness_sha512"] = guard.digest(Path(__file__).read_bytes())
        if REPORT.exists():
            old = REPORT.read_bytes()
            target = ROOT / ".git/udak-phase3/previous-reports" / (hashlib.sha256(old).hexdigest() + ".json")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(old)
        REPORT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "steps", "h2", "compatibility_diagnostics", "cleanup", "failure_type") if k in result}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
