#!/usr/bin/env python3
"""Bounded Java 17 Phase 1 checks; never starts Spring, Gradle, Docker or a DB."""
import hashlib
from collections import Counter
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "evidence/PHASE1-VALIDATION.json"
CURRENT = None
MAX_BYTES = 16 * 1024 * 1024


def digest(data):
    return hashlib.sha512(data).hexdigest()


def stop_child():
    if CURRENT is not None:
        # The new session/process group belongs to this exact invocation, including descendants.
        group = CURRENT.pid
        if group_alive(group):
            os.killpg(group, signal.SIGTERM)
        try:
            CURRENT.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(group, signal.SIGKILL)
            CURRENT.wait(timeout=3)
        deadline = time.monotonic() + 3
        while group_alive(group) and time.monotonic() < deadline:
            time.sleep(0.03)
        if group_alive(group):
            os.killpg(group, signal.SIGKILL)
            deadline = time.monotonic() + 3
            while group_alive(group) and time.monotonic() < deadline:
                time.sleep(0.03)
        if group_alive(group):
            raise RuntimeError("Owned process group cleanup unconfirmed")


def group_alive(group):
    try:
        os.killpg(group, 0)
        return True
    except ProcessLookupError:
        return False


@contextmanager
def workspace(prefix):
    temporary = tempfile.TemporaryDirectory(prefix=prefix)
    work = Path(temporary.name)
    cleanup = {}
    try:
        yield work, cleanup
    finally:
        try:
            stop_child()
        except Exception:
            temporary._finalizer.detach()
            cleanup.update(status="PRESERVED_PROCESS_UNKNOWN", temporary_directory_remaining=True)
            raise
        entries = list(work.rglob("*"))
        files = [p for p in entries if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        if len(entries) > 2000 or size > 128 * 1024 * 1024 or any(p.is_symlink() for p in entries):
            temporary._finalizer.detach()  # Preserve an uncertain workspace for diagnosis.
            cleanup.update(status="PRESERVED_UNKNOWN", temporary_directory_remaining=True)
            raise RuntimeError("Workspace cleanup bounds exceeded")
        temporary.cleanup()
        cleanup.update(status="PASS", temporary_files_removed=len(files),
                       temporary_bytes_removed=size, temporary_directory_remaining=work.exists())
        if work.exists():
            raise RuntimeError("Workspace cleanup incomplete")


def interrupted(signum, _frame):
    stop_child()
    raise InterruptedError("Bounded run interrupted")


def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES, MAX_BYTES))


def run_step(name, command, work, timeout=30, expected=0, private_input=None):
    global CURRENT
    log = work / (name + ".output")
    with log.open("wb") as stream:
        CURRENT = subprocess.Popen(command, cwd=ROOT, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True,
                                   stdin=subprocess.PIPE if private_input is not None else subprocess.DEVNULL,
                                   preexec_fn=limits)
        try:
            if private_input is None:
                code = CURRENT.wait(timeout=timeout)
            else:
                CURRENT.communicate(input=private_input, timeout=timeout)
                code = CURRENT.returncode
        except subprocess.TimeoutExpired:
            stop_child()
            code = 124
        finally:
            stop_child()
            process = CURRENT
            if CURRENT.stdin is not None and not CURRENT.stdin.closed:
                CURRENT.stdin.close()
            CURRENT = None
    output = log.read_bytes()
    if len(output) > 1024 * 1024:
        raise RuntimeError("Output limit exceeded")
    text = output.decode("utf-8", errors="replace")
    result = {"name": name, "exit_code": code, "status": "PASS" if code == expected else "FAIL",
              "child_reaped": process.poll() is not None, "process_group_quiesced": not group_alive(process.pid),
              "output_sha512": digest(output)}
    count = re.search(r"assertions=(\d+)", text)
    if count:
        result["assertions"] = int(count.group(1))
    if code != expected:
        # Keep locations/categories, never SQL, values, raw logs or connection details.
        result["diagnostics"] = [line.strip() for line in text.splitlines()
                                 if line.strip().startswith(("symbol:", "location:", "at dev.udak."))][:20]
        raise RuntimeError(json.dumps(result))
    return result


def download(url, maximum):
    if not url.startswith("https://repo.maven.apache.org/maven2/com/github/jsqlparser/jsqlparser/5.4/"):
        raise ValueError("Unapproved dependency origin")
    with urllib.request.urlopen(url, timeout=12) as response:
        if not response.geturl().startswith("https://repo.maven.apache.org/"):
            raise ValueError("Unapproved dependency redirect")
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Download limit exceeded")
    return data


def dependency_checks(manifest, work):
    jar = download(manifest["artifact_url"], 5_000_000)
    pom = download(manifest["pom_url"], 200_000)
    published = download(manifest["artifact_url"] + ".sha512", 1024).decode().split()[0]
    if digest(jar) != manifest["jar_sha512"] or digest(jar) != published:
        raise ValueError("Artifact integrity mismatch")
    if digest(pom) != manifest["pom_sha512"]:
        raise ValueError("POM integrity mismatch")
    license_bytes = (ROOT / manifest["license_file"]).read_bytes()
    notice = (ROOT / manifest["notice_file"]).read_text()
    if digest(license_bytes) != manifest["license_sha512"] or "Apache License" not in license_bytes.decode():
        raise ValueError("Bundled license mismatch")
    if manifest["coordinate"] not in notice or "Apache" not in notice:
        raise ValueError("Attribution missing")
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    xml = ET.fromstring(pom)
    licenses = [e.findtext("m:name", namespaces=ns) for e in xml.findall("m:licenses/m:license", ns)]
    if not any("Apache" in name for name in licenses):
        raise ValueError("Apache license option absent")
    runtime = [e.findtext("m:artifactId", namespaces=ns)
               for e in xml.findall("m:dependencies/m:dependency", ns)
               if e.findtext("m:scope", default="compile", namespaces=ns) in ("compile", "runtime")]
    if runtime != manifest["expected_runtime_dependencies"]:
        raise ValueError("Dependency license graph changed")
    jar_path = work / "jsqlparser-5.4.jar"
    jar_path.write_bytes(jar)
    with zipfile.ZipFile(jar_path) as archive:
        majors = set()
        for entry in archive.infolist():
            if entry.filename.endswith(".class"):
                with archive.open(entry) as item:
                    majors.add(int.from_bytes(item.read(8)[6:8], "big"))
        if not majors or max(majors) > manifest["expected_max_class_major"]:
            raise ValueError("Dependency Java baseline changed")
        upstream_notices = [n for n in archive.namelist() if "LICENSE" in n.upper() or "NOTICE" in n.upper()]
    return jar_path, {"status": "PASS", "coordinate": manifest["coordinate"],
                      "jar_sha512": digest(jar), "pom_sha512": digest(pom), "license_sha512": digest(license_bytes),
                      "jar_bytes": len(jar), "pom_bytes": len(pom), "license_bytes": len(license_bytes),
                      "selected_license": "Apache-2.0", "runtime_dependencies": runtime,
                      "class_major_versions": sorted(majors), "bundled_license_verified": True,
                      "upstream_binary_notice_entries": len(upstream_notices),
                      "product_distribution_approval": "NOT GRANTED; separate release gate"}


def cleanup_probe(kind):
    cleanup = {}
    try:
      with workspace("udak-phase1-probe-") as (work, cleanup):
        if kind == "failure":
            command, expected, timeout = [sys.executable, "-c", "raise SystemExit(7)"], 7, 5
        elif kind == "timeout":
            command, expected, timeout = [sys.executable, "-c", "import time; time.sleep(2)"], 124, 0.1
        elif kind == "signal":
            command, expected, timeout = [sys.executable, "-c", "import os,signal; os.kill(os.getpid(),signal.SIGTERM)"], -signal.SIGTERM, 5
        elif kind == "descendant":
            command = [sys.executable, "-c", "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)'])"]
            expected, timeout = 0, 5
        else:
            command, expected, timeout = [sys.executable, "-c", "raise SystemExit(7)"], 0, 5
        result = run_step("probe-" + kind, command, work, timeout, expected)
    except RuntimeError:
        if kind != "exception" or cleanup.get("status") != "PASS":
            raise
        result = {"name": "probe-exception", "status": "PASS", "actual_failure_path": True}
    result["cleanup"] = cleanup
    if work.exists():
        raise RuntimeError("Probe cleanup incomplete")
    return result


def verify_documents():
    korean = {p.name: p for p in (ROOT / "docs/ko").glob("*.md")}
    english = {p.name: p for p in (ROOT / "docs/en").glob("*.md")}
    if korean.keys() != english.keys():
        raise ValueError("Unpaired documentation")
    identifiers = r"(?<![A-Za-z0-9])(?:FR-\d{3}|NFR-\d{2}|ADR-\d{3}|T-\d{3}|GOV-\d{3})(?![A-Za-z0-9])"
    versions = r"(?<![0-9A-Za-z])\d+(?:\.\d+){1,3}(?![0-9A-Za-z])"
    links = 0
    documents = list(korean.values()) + list(english.values())
    documents += [ROOT / name for name in ("README.md", "README-KO.md", "AGENTS.md", "CLAUDE.md")]
    for document in documents:
        if not re.fullmatch(r"[A-Z0-9-]+\.md", document.name):
            raise ValueError("Invalid documentation filename")
        text = document.read_text()
        if re.search(r"docs/\d{2}-[A-Z0-9-]+\.md", text):
            raise ValueError("Stale documentation path")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if target.startswith(("https:", "http:", "#", "mailto:")):
                continue
            links += 1
            if not (document.parent / target.split("#", 1)[0]).exists():
                raise ValueError("Broken documentation link")
    for name in korean:
        left, right = korean[name].read_text(), english[name].read_text()
        for pattern in (identifiers, versions):
            if Counter(re.findall(pattern, left)) != Counter(re.findall(pattern, right)):
                raise ValueError("Bilingual identifier/version mismatch")
        pattern = r"^#{1,6} |^\||^```"
        if len(re.findall(pattern, left, re.M)) != len(re.findall(pattern, right, re.M)):
            raise ValueError("Bilingual structure mismatch")
        if "../en/" + name not in left or "../ko/" + name not in right:
            raise ValueError("Language switch missing")
    return {"status": "PASS", "paired_documents": len(korean), "local_links_checked": links,
            "id_version_structure_parity": "PASS"}


def main():
    result = {"schema_version": 1, "phase": 1, "status": "FAIL", "steps": [],
              "limits": {"wall_seconds": 120, "child_cpu_seconds": 30, "heap_mib": 256,
                         "metaspace_mib": 128, "active_cpus": 2, "download_bytes_per_file": 5_000_000,
                         "file_bytes": MAX_BYTES, "output_bytes": 1024 * 1024},
              "not_run": ["Gradle task execution", "Spring demo", "real databases", "SQL translation",
                          "commercial license purchase", "performance/load tests"],
              "worktrees_created": 0, "worktrees_removed": 0}
    start = time.monotonic()
    work = None
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, interrupted)
    signal.alarm(120)
    try:
        result["cleanup_probes"] = [cleanup_probe(kind) for kind in ("failure", "timeout", "signal", "exception", "descendant")]
        result["documentation"] = verify_documents()
        with workspace("udak-phase1-") as (work, cleanup):
            result["cleanup"] = cleanup
            try:
                os.putenv("TMPDIR", str(work))
                os.putenv("_JAVA_OPTIONS", "-Xmx256m -XX:MaxMetaspaceSize=128m -XX:ActiveProcessorCount=2")
                manifest = json.loads((ROOT / "tools/phase1-dependencies.json").read_text())
                jar, result["dependency"] = dependency_checks(manifest, work)
                core_sources = sorted((ROOT / "core/src/main/java").rglob("*.java"))
                if any(re.search(r"^import (?:org\.springframework|org\.hibernate|org\.apache\.ibatis|net\.sf\.jsqlparser)", p.read_text(), re.M) for p in core_sources):
                    raise ValueError("Core dependency boundary violated")
                result["core_dependency_boundary"] = "PASS"
                result["steps"].append(run_step("core-smoke", ["./tools/run-core-smoke.sh"], work))
                sources = core_sources + sorted((ROOT / "core/src/test/java").rglob("*.java"))
                sources += sorted((ROOT / "sql-jsqlparser/src").rglob("*.java"))
                classes = work / "classes"
                classes.mkdir()
                result["steps"].append(run_step("javac", ["javac", "--release", "17", "-cp", str(jar), "-d", str(classes)] + [str(p) for p in sources], work))
                classpath = str(classes) + os.pathsep + str(jar)
                result["steps"].append(run_step("basic-contract", ["java", "-cp", classpath, "dev.udak.core.CompilerContractTest"], work))
                result["steps"].append(run_step("external-contract", ["java", "-cp", classpath, "dev.udak.jsqlparser.JSqlParserCompilerTest"], work))
                result["source_sha512"] = {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sources}
                result["harness_sha512"] = digest(Path(__file__).read_bytes())
                result["dependency_manifest_sha512"] = digest((ROOT / "tools/phase1-dependencies.json").read_bytes())
                result["status"] = "PASS"
            finally:
                stop_child()
    except Exception as error:
        result["status"] = "FAIL"
        result["failure_type"] = type(error).__name__
        # RuntimeError from run_step contains only the explicitly filtered diagnostic object.
        if isinstance(error, RuntimeError) and str(error).startswith('{'):
            result["failed_step"] = json.loads(str(error))
    finally:
        signal.alarm(0)
        if work is not None and "cleanup" in result:
            result["cleanup"]["temporary_directory_remaining"] = work.exists()
        result["elapsed_seconds"] = round(time.monotonic() - start, 3)
        REPORT.parent.mkdir(exist_ok=True)
        if REPORT.exists():
            archive = ROOT / ".git/udak-phase1/previous-reports"
            archive.mkdir(parents=True, exist_ok=True)
            old = REPORT.read_bytes()
            (archive / (hashlib.sha256(old).hexdigest() + ".json")).write_bytes(old)
        REPORT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("status", "steps", "cleanup", "failure_type", "failed_step") if key in result}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
