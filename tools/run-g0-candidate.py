#!/usr/bin/env python3
"""Build the approved six thin modules in an owned, disposable Maven repository."""
from collections import Counter
from datetime import datetime, timezone
import fcntl
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
import xml.etree.ElementTree as ET
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("g0_packaging", ROOT / "tools/run-phase6.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
scope_check = h.module("g0_scope_check", "tools/verify-release-approval-scope.py")

REPORT = "evidence/RELEASE-G0-CANDIDATE.json"
DECISION = "evidence/RELEASE-G0-G5-DECISION.json"
ORIGINAL = "evidence/PHASE6-VALIDATION.json"
SCOPE = "tools/phase6-approval-scope.json"
REVIEW = "evidence/RELEASE-APPROVAL-SCOPE.json"
OVERLAY = "tools/release-g0/license.init.gradle"
AUDIT = ROOT / ".git/udak-release-support"
VERSION = "0.1.0-poc"
LICENSE_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
LEGAL = {"META-INF/LICENSE": "LICENSE", "META-INF/NOTICE": "NOTICE"}
STATIC = (DECISION, ORIGINAL, SCOPE, REVIEW, OVERLAY, h.MANIFEST, "LICENSE", "NOTICE",
          "tools/verify-release-approval-scope.py", "tools/run-g0-candidate.py",
          "tools/run-phase6.py", "udak-cli/udak_cli.py")


class CheckError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise CheckError(reason)


def read_json(path):
    return json.loads(path.read_bytes())


def record(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def approved_inputs(result):
    static_hash = h.hashes(STATIC)
    original = read_json(ROOT / ORIGINAL)
    decision = read_json(ROOT / DECISION)
    approved = read_json(ROOT / SCOPE)["g0"]
    scope_check.verify_g0(approved, VERSION, original)
    require(decision.get("approval_basis") == "EXPLICIT_USER_CONFIRMATION"
            and decision.get("candidate_version") == VERSION and decision.get("authorize_publish") is False
            and decision.get("g0") == {"decision": "APPROVED", "license": "Apache-2.0", "scope": approved}
            and decision.get("scope_sha512") == static_hash[SCOPE]
            and decision.get("scope_verification_sha512") == static_hash[REVIEW], "OWNER_SCOPE")
    require(hashlib.sha256((ROOT / "LICENSE").read_bytes()).hexdigest() == LICENSE_SHA256
            and (ROOT / "NOTICE").stat().st_size > 0, "LEGAL_INPUT")
    configs = set(h.CONFIG) - {"build.gradle.kts", "settings.gradle.kts"}
    sources = {path for path in original["source_sha512"]
               if path.split("/")[0] in h.MODULES
               and re.fullmatch(r"[\w-]+/src/main/java/dev/udak/(?:\w+/)+\w+\.java", path)}
    copied = sorted(configs | sources)
    pins = original["source_sha512"] | original["configuration_sha512"] | original["manifest_sha512"]
    actual = h.hashes(copied + [h.MANIFEST])
    require(all(sha == pins.get(path) for path, sha in actual.items()), "ORIGINAL_BUILD_INPUT")
    require(original["status"] == "PASS" and len(sources) == 26, "ORIGINAL_SOURCE_INVENTORY")
    result["input_sha512"] = static_hash | actual
    return original, copied, approved


def graph(work, result):
    pin = read_json(ROOT / h.MANIFEST)
    require(pin["gradle"] == {"version": h.GRADLE_VERSION, "distribution_sha256": h.GRADLE_SHA256}, "GRADLE_PIN")
    artifacts = {":".join(row[k] for k in ("group", "name", "version")): row for row in pin["artifacts"]}
    lanes = {}
    for lane, rows in read_json(work / "resolution.json").items():
        coords = []
        for row in rows:
            coord = ":".join(row[k] for k in ("group", "name", "version"))
            jar = Path(row["file"])
            require(jar.resolve() == jar and jar.is_relative_to(work / "home") and jar.is_file()
                    and coord in artifacts and jar.stat().st_size == artifacts[coord]["size"]
                    and h.guard.digest(jar.read_bytes()) == artifacts[coord]["sha512"], "DEPENDENCY_HASH")
            coords.append(coord)
        lanes[lane] = sorted(coords)
    require(lanes == pin["lanes"], "DEPENDENCY_LANES")
    result["dependency_graph"] = {"status": "PASS", "resolved_lanes": lanes,
                                  "pinned_manifest_artifacts": len(artifacts),
                                  "resolved_distinct_artifacts": len(set().union(*lanes.values())),
                                  "manifest_sha512": result["input_sha512"][h.MANIFEST]}


def jar_entries(path):
    with zipfile.ZipFile(path) as jar:
        items = jar.infolist()
        require(len(items) <= 2000 and sum(item.file_size for item in items) <= 32 * 1024**2, "JAR_BOUND")
        names = [item.filename for item in items]
        require(all(count == 1 for count in Counter(names).values()), "DUPLICATE_JAR_ENTRY")
        for name in names:
            require(not Path(name).is_absolute() and ".." not in Path(name).parts
                    and not name.lower().endswith((".jar", ".war", ".zip", ".tar", ".gz", ".dll", ".so", ".dylib")),
                    "UNAPPROVED_JAR_ENTRY")
        return {i.filename: h.guard.digest(jar.read(i)) for i in items if not i.is_dir()}


def package_files():
    return {p.relative_to(h.CANDIDATE_BASE).as_posix(): p for p in h.candidate_inventory()
            if p.suffix in {".jar", ".module", ".pom"}}


def structure(pom):
    root = ET.parse(pom).getroot()
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    return root


def metadata_graph(path):
    data = read_json(path)
    for variant in data["variants"]:
        for file in variant.get("files", []):
            filename = file["name"]
            require(file["url"] == filename and filename == Path(filename).name
                    and filename.endswith(".jar"), "MODULE_FILE_REFERENCE")
            jar = path.with_name(filename)
            payload = jar.read_bytes()
            require(file["size"] == len(payload) and all(
                file[algo] == hashlib.new(algo, payload).hexdigest() for algo in ("md5", "sha1", "sha256", "sha512")
            ), "MODULE_FILE_DIGEST")
            for key in ("size", "md5", "sha1", "sha256", "sha512"):
                del file[key]
    return data


def audit_packages(before, result):
    packages = package_files()
    require(len(packages) == 30 and packages.keys() == before.keys(), "CANDIDATE_INVENTORY")
    rows = []
    pom_dependencies = {}
    legal_hashes = {entry: result["input_sha512"][source] for entry, source in LEGAL.items()}
    for name, path in sorted(packages.items()):
        base = before[name]
        module = path.parent.parent.name
        digest = h.guard.digest(path.read_bytes())
        require(digest != base["sha512"], "LICENSE_OVERLAY_NOT_APPLIED")
        if path.suffix == ".jar":
            entries = jar_entries(path)
            require(all(entries.pop(entry, None) == sha for entry, sha in legal_hashes.items())
                    and entries == base["entries"], "JAR_CONTENT_CHANGED")
        elif path.suffix == ".pom":
            root = structure(path)
            licenses = root.findall("licenses/license")
            require(len(licenses) == 1 and {child.tag: child.text for child in licenses[0]} == {
                "name": "Apache License, Version 2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0",
                "distribution": "repo"}, "POM_LICENSE")
            root.remove(root.find("licenses"))
            # Compare elements/attributes/text independent of Maven XML indentation.
            root.find("description").text = base["description"]
            require(ET.canonicalize(ET.tostring(root, encoding="unicode"), strip_text=True) == base["xml"],
                    "POM_DEPENDENCY_CHANGE")
            pom_dependencies[module] = [{elem.tag: elem.text for elem in dep} for dep in root.iter("dependency")]
        else:
            require(metadata_graph(path) == base["metadata"], "MODULE_GRAPH_CHANGE")
        rows.append({"path": name, "sha512": digest, "size": path.stat().st_size, "baseline_sha512": base["sha512"]})
    result.update(artifacts=rows, package_artifacts=len(rows), pom_dependencies=pom_dependencies,
                  licensed_poms=6, licensed_jars=18, retained_original_archive_contents=True,
                  gradle_metadata_files_checked=6, bundled_third_party_jars=0)
    return rows


def baseline(original):
    packages = package_files()
    previous = {p.removeprefix("build/phase6/"): sha
                for p, sha in original["reproducibility"]["artifact_sha512"].items()}
    require(packages.keys() == previous.keys() and len(packages) == 30, "BASELINE_INVENTORY")
    evidence = {}
    for name, path in packages.items():
        item = {"sha512": h.guard.digest(path.read_bytes())}
        # Same historical artifacts, including every Javadoc resource and notice.
        require(item["sha512"] == previous[name], "BASELINE_ARTIFACT_MISMATCH_" + path.name)
        if path.suffix == ".jar":
            item["entries"] = jar_entries(path)
            require(LEGAL.keys().isdisjoint(item["entries"]), "EXISTING_LEGAL_ENTRY")
            if not name.endswith(("-sources.jar", "-javadoc.jar")):
                require(any(n.endswith(".class") for n in item["entries"])
                        and all(n.startswith("dev/udak/") and n.endswith(".class")
                                or n in ("META-INF/MANIFEST.MF", *[p.split("/resources/")[1] for p in h.CONFIG if "/resources/" in p])
                                for n in item["entries"]), "THIN_JAR_CONTENT")
        elif path.suffix == ".pom":
            root = structure(path)
            item.update(description=root.findtext("description"),
                        xml=ET.canonicalize(ET.tostring(root, encoding="unicode"), strip_text=True))
        else:
            item["metadata"] = metadata_graph(path)
        evidence[name] = item
    return evidence


def supporting_files(packages, result, original):
    base = h.CANDIDATE_BASE
    artifacts = read_json(ROOT / h.MANIFEST)["artifacts"]
    sbom = {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1, "components": [
        {"type": "library", "group": a["group"], "name": a["name"], "version": a["version"],
         "purl": "pkg:maven/" + a["group"] + "/" + a["name"] + "@" + a["version"],
         "hashes": [{"alg": "SHA-512", "content": a["sha512"]}],
         "licenses": [{"license": {"name": license["name"], "url": license["url"]}} for license in a["licenses"]]}
        for a in artifacts]}
    # The existing SBOM and API compatibility proof describe the unchanged external
    # dependency inventory and sources. Preserve the historical serialization too.
    for name, data in [("SBOM.json", sbom), ("API-COMPATIBILITY.json", original["api_compatibility"])]:
        path = base / name
        path.write_text(json.dumps(data, indent=2) + "\n")
        pinned = next(item for item in original["artifacts"] if item["path"] == "build/phase6/" + name)
        require(h.guard.digest(path.read_bytes()) == pinned["sha512"], "HISTORICAL_SUPPORT_METADATA")
    license_rows = [":".join(a[key] for key in ("group", "name", "version")) + " | "
                    + "; ".join(entry["name"] + " " + entry["url"] for entry in a["licenses"]) for a in artifacts]
    (base / "NOTICE.txt").write_text((ROOT / "NOTICE").read_text() + "\nSeparately resolved dependencies\n"
                                     + "\n".join(license_rows) + "\n")
    record(base / "CANDIDATE.json", {"version": VERSION, "license": "Apache-2.0", "authorize_publish": False,
            "decision_sha512": result["input_sha512"][DECISION], "artifacts": packages})
    paths = sorted([r["path"] for r in packages] + ["API-COMPATIBILITY.json", "CANDIDATE.json", "NOTICE.txt", "SBOM.json"])
    (base / "CHECKSUMS.sha512").write_text("".join(h.guard.digest((base / p).read_bytes()) + "  " + p + "\n" for p in paths))
    result["supporting_artifacts"] = {name: h.guard.digest((base / name).read_bytes()) for name in scope_check.METADATA}
    result["checksum_manifest_entries"] = len(paths)
    result["metadata_artifacts"] = len(result["supporting_artifacts"])


def build(work, result, original, copied):
    h.CANDIDATE_BASE = work / "candidate"
    h.CANDIDATE_BASE.mkdir()
    (h.CANDIDATE_BASE / ".owner").write_text(work.name)
    isolated = work / "project"
    for name in copied + ["LICENSE", "NOTICE", OVERLAY]:
        target = isolated / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
        require(h.guard.digest(target.read_bytes()) == result["input_sha512"][name], "SOURCE_COPY")
    binary = h.gradle_distribution(work)
    project = isolated / "starter-testkit"
    tasks = [f":{module}:publishMavenJavaPublicationToCandidateRepository" for module in h.MODULES]
    command = h.gradle_command(binary, work, project, "phase6Resolution", *tasks)
    result["steps"].append(h.step("reference-local-package", command, work, timeout=420))
    graph(work, result)
    before = baseline(original)
    result["original_candidate_artifacts_reproduced"] = len(before)
    command = h.gradle_command(binary, work, project, "--offline", "--init-script", str(isolated / OVERLAY), *tasks)
    try:
        result["steps"].append(h.step("licensed-local-package", command, work, timeout=270))
    except RuntimeError:
        output = (work / "licensed-local-package.output").read_bytes()
        result["license_build_categories"] = [category for category, pattern in (
            ("INITIALIZER_LOCATION", rb"license\.init\.gradle' line: [0-9]+"),
            ("UNKNOWN_PROPERTY", rb"Could not get unknown property"),
            ("UNKNOWN_METHOD", rb"Could not find method"),
            ("OFFLINE_RESOLUTION", rb"available for offline mode"),
            ("COMPILATION", rb"Could not compile"),
            ("ARCHIVE_COPY", rb"Could not copy|Cannot convert the provided notation|No signature of method.*into"),
        ) if re.search(pattern, output)]
        raise
    packages = audit_packages(before, result)
    supporting_files(packages, result, original)


def main():
    if sys.argv[1:]:
        print("G0 INVALID_ARGUMENTS")
        return 2
    AUDIT.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    result = {"schema_version": 1, "requirement": "RELEASE-006", "gate": "G0",
              "scope": "local validation of six approved thin packages", "status": "FAIL",
              "started_at_utc": datetime.now(timezone.utc).isoformat(), "steps": [],
              "authorize_publish": False, "external_publications": 0, "containers_started": 0,
              "limits": {"wall_seconds": 900, "workers": 1, "gradle_heap_mib": 512,
                         "gradle_metaspace_mib": 256, "active_cpus": 2, "child_cpu_seconds": 120,
                         "workspace_files": 20000, "workspace_bytes": 2 * 1024**3}}
    for event in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT):
        signal.signal(event, h.guard.interrupted)
    signal.alarm(result["limits"]["wall_seconds"])
    try:
        lock_fd = os.open(AUDIT / "G0.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(lock_fd, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            original, copied, approved = approved_inputs(result)
            result["approved_scope"] = approved
            result["coordinates"] = [f"dev.udak:{m}:{VERSION}" for m in sorted(h.MODULES)]
            require(shutil.disk_usage("/tmp").free >= 4 * 1024**3, "DISK_HEADROOM")
            with h.workspace() as (work, cleanup):
                result["cleanup"] = cleanup
                jvm = "_JAVA_OPTIONS=-Xmx256m -XX:MaxMetaspaceSize=128m -XX:ActiveProcessorCount=2"
                result["steps"].append(h.step("core-smoke", ["/usr/bin/env", jvm, "./tools/run-core-smoke.sh"], work))
                build(work, result, original, copied)
                require(h.hashes(result["input_sha512"]) == result["input_sha512"], "INPUTS_CHANGED")
            require(cleanup.get("status") == "PASS" and cleanup.get("temporary_directory_remaining") is False
                    and cleanup.get("gradle_daemons_quiesced") is True and cleanup.get("candidate_files_removed", 0) >= 35,
                    "CLEANUP_INCOMPLETE")
            result["elapsed_seconds"] = round(time.monotonic() - started, 3)
            result["status"] = "PASS"
            h.save(REPORT, result)
    except Exception as error:
        result["status"] = "FAIL"
        result["failure_type"] = type(error).__name__
        if isinstance(error, CheckError):
            result["check"] = str(error)
        if isinstance(error, RuntimeError):
            try:
                receipt = json.loads(str(error))
                if isinstance(receipt, dict) and "exit_code" in receipt:
                    result["failed_step"] = receipt
            except ValueError:
                pass
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        name = "g0-failed-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + ".json"
        h.save(AUDIT / name, result)
    finally:
        signal.alarm(0)
    print(json.dumps({k: result[k] for k in ("status", "check", "failed_step", "license_build_categories", "package_artifacts",
                     "metadata_artifacts", "elapsed_seconds", "cleanup") if k in result}))
    return int(result["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
