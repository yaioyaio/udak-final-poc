#!/usr/bin/env python3
"""Assemble, inspect and fixture-sign the pinned six-module local release bundle."""
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
import subprocess
import sys
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
REVISION = "940acaefc104660797d531baab9dee660484c909"
REPORT = "evidence/RELEASE-READINESS-LOCAL.json"
SMOKE_REPORT = "evidence/RELEASE-READINESS-SIGNING-SMOKE.json"
HISTORICAL_GATE = "evidence/PHASE6-GATE.json"
spec = importlib.util.spec_from_file_location("local_g0", ROOT / "tools/run-g0-candidate.py")
g0 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g0)
h = g0.h
signing = h.module("local_signing", "tools/run-release-signing.py")
cli = g0.scope_check.cli
require = g0.require
digest = h.guard.digest


def snapshot(work, result):
    fixed = (set(h.CONFIG) - {"build.gradle.kts", "settings.gradle.kts"}) | {"LICENSE", "NOTICE", g0.OVERLAY}
    checks = {g0.DECISION, g0.REVIEW, g0.REPORT, g0.SCOPE, g0.ORIGINAL, h.MANIFEST, HISTORICAL_GATE}
    roots = [f"{module}/src/main" for module in h.MODULES]
    listing = subprocess.run(["git", "ls-tree", "-rlz", REVISION, "--", *sorted(fixed | checks), *roots],
                             cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True, timeout=10)
    inputs = {}
    records = listing.stdout.rstrip(b"\0").split(b"\0")
    require(len(records) <= 150, "SNAPSHOT_BOUND")
    for row in records:
        meta, raw = row.split(b"\t")
        mode, kind, oid, size = meta.split()
        name = raw.decode("ascii")
        source = (name.split("/")[0] in h.MODULES and
                  re.fullmatch(r"[\w-]+/src/main/java/dev/udak/(?:\w+/)+\w+\.java", name))
        require(cli.public_path(name) and (name in fixed | checks or source)
                and mode == b"100644" and kind == b"blob" and 0 < int(size) <= 2**20, "SNAPSHOT_PATH")
        data = subprocess.run(["git", "cat-file", "blob", oid], cwd=ROOT, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, check=True, timeout=10).stdout
        require(len(data) == int(size), "BLOB_SIZE")
        inputs[name] = digest(data)
        if name in checks:
            # Historical validators read these public files from the checkout.
            with cli.directory(ROOT.parts[1:]) as fd, cli.regular_file(fd, name, 2**20) as (stream, length):
                require(stream.read(length + 1) == data, "HISTORICAL_INPUT_CHANGED")
        else:
            target = work / "project" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    require(fixed | checks <= inputs.keys(), "MISSING_INPUT")
    scope = g0.read_json(ROOT / g0.SCOPE)["g0"]
    approval = g0.read_json(ROOT / g0.DECISION)
    scope_report = g0.scope_check.verify_g0(scope, g0.VERSION, g0.read_json(ROOT / g0.ORIGINAL))
    require(approval["approval_basis"] == "EXPLICIT_USER_CONFIRMATION" and approval["authorize_publish"] is False
            and approval["candidate_version"] == g0.VERSION and approval["scope_sha512"] == inputs[g0.SCOPE]
            and approval["scope_verification_sha512"] == inputs[g0.REVIEW]
            and approval["g0"] == {"decision": "APPROVED", "license": "Apache-2.0", "scope": scope}
            and sorted(h.MODULES) == scope["modules"]
            and hashlib.sha256((work / "project/LICENSE").read_bytes()).hexdigest() == g0.LICENSE_SHA256,
            "LICENSE_SCOPE")
    result.update(source_revision=REVISION, input_sha512=inputs, coordinates=scope_report["coordinates"],
                  runner_sha512=digest(Path(__file__).read_bytes()))


def audit_jar(path, module, inputs):
    entries = g0.jar_entries(path)
    for name, origin in g0.LEGAL.items():
        require(entries.pop(name, None) == inputs[origin], "JAR_LEGAL")
    require(entries.pop("META-INF/MANIFEST.MF", None), "JAR_MANIFEST")
    sources = {name.split("/java/")[1]: sha for name, sha in inputs.items()
               if name.startswith(module + "/src/main/java/")}
    resources = {name.split("/resources/")[1]: sha for name, sha in inputs.items()
                 if name.startswith(module + "/src/main/resources/")}
    if path.name.endswith("-javadoc.jar"):
        require("index.html" in entries and any(n.startswith("dev/udak/") and n.endswith(".html") for n in entries)
                and not any(n.endswith((".class", ".java")) for n in entries), "JAVADOC_CONTENT")
    elif path.name.endswith("-sources.jar"):
        require(entries == sources | resources, "SOURCE_CONTENT")
    else:
        for name, sha in resources.items():
            require(entries.pop(name, None) == sha, "BINARY_RESOURCE")
        top_classes = {name.removesuffix(".java") for name in sources}
        require(all(n.endswith(".class") and n[:-6].split("$")[0] in top_classes for n in entries)
                and {c + ".class" for c in top_classes} <= entries.keys(), "THIN_BINARY")


def audit_metadata(path, module, dependencies):
    data = g0.metadata_graph(path)
    component = data["component"]
    require((component["group"], component["module"], component["version"]) ==
            ("dev.udak", module, g0.VERSION), "METADATA_COORDINATE")
    variants = {v["name"]: v for v in data["variants"]}
    expected = {"apiElements": "", "runtimeElements": "", "sourcesElements": "-sources", "javadocElements": "-javadoc"}
    require(variants.keys() == expected.keys() and len(data["variants"]) == 4, "METADATA_VARIANTS")
    for name, suffix in expected.items():
        variant = variants[name]
        require([f["name"] for f in variant["files"]] == [f"{module}-{g0.VERSION}{suffix}.jar"], "METADATA_FILE")
        scopes = {"compile", "import"} if name == "apiElements" else {"compile", "import", "runtime"}
        deps = [(d["groupId"], d["artifactId"], d.get("version", "")) for d in dependencies
                if not suffix and d["scope"] in scopes]
        actual = [(d["group"], d["module"], d.get("version", {}).get("requires", ""))
                  for d in variant.get("dependencies", [])]
        require(sorted(actual) == sorted(deps), "METADATA_DEPENDENCIES")


def bundle(work, result):
    files = g0.package_files()
    expected = {f"repository/dev/udak/{m}/{g0.VERSION}/{m}-{g0.VERSION}{ext}" for m in h.MODULES
                for ext in g0.scope_check.EXTENSIONS}
    require(files.keys() == expected and len(files) == 30, "BUNDLE_INVENTORY")
    previous = g0.read_json(ROOT / g0.REPORT)
    require(previous["status"] == "PASS" and previous["coordinates"] == result["coordinates"], "PRIOR_SCOPE")
    archive, manifest = work / "candidate.zip", work / "manifest.json"
    rows = []
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_STORED) as z:
        for name, path in sorted(files.items()):
            module = path.parent.parent.name
            deps = previous["pom_dependencies"][module]
            if path.suffix == ".jar":
                audit_jar(path, module, result["input_sha512"])
            elif path.suffix == ".pom":
                pom = g0.structure(path)
                require([pom.findtext(k) for k in ("groupId", "artifactId", "version")] ==
                        ["dev.udak", module, g0.VERSION] and
                        [{c.tag: c.text for c in lic} for lic in pom.findall("licenses/license")] ==
                        [{"name": "Apache License, Version 2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0",
                          "distribution": "repo"}] and
                        [{c.tag: c.text for c in dep} for dep in pom.iter("dependency")] == deps, "POM_CONTENT")
            else:
                audit_metadata(path, module, deps)
            payload = path.read_bytes()
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            z.writestr(info, payload)
            rows.append({"coordinate": f"dev.udak:{module}:{g0.VERSION}", "path": name,
                         "size": len(payload), "sha512": digest(payload)})
    g0.record(manifest, {"schema_version": 1, "source_revision": REVISION, "artifacts": rows})
    with zipfile.ZipFile(archive) as z:
        require(z.namelist() == [r["path"] for r in rows], "ZIP_MEMBERSHIP")
        for row in g0.read_json(manifest)["artifacts"]:
            data = z.read(row["path"])
            require(len(data) == row["size"] and digest(data) == row["sha512"], "ZIP_CHECKSUM")
    result.update(artifacts=rows, archive_entries_verified=len(rows), licensed_jars=18, licensed_poms=6,
                  gradle_metadata_files_checked=6)
    return archive, manifest


def check_gate(work, result):
    historical = g0.read_json(ROOT / HISTORICAL_GATE)
    require(historical["formal_release"] == "BLOCKED" and historical["authorize_publish"] is False
            and historical["execution_reports_sha512"][g0.ORIGINAL] == result["input_sha512"][g0.ORIGINAL],
            "HISTORICAL_GATE")
    # This pinned revision contains source updates subsequent to the G6 report.
    receipt = h.step("publication-gate", [sys.executable, "-B", "tools/release-gate.py", "--format", "json"],
                     work, timeout=25, expected=1)
    current = json.loads(signing.read_output(work, "publication-gate"))
    require(current == {"status": "BLOCKED", "authorize_publish": False, "error": "HASH_MISMATCH"},
            "CURRENT_GATE")
    result["steps"].append(receipt)
    result["current_publication_gate"] = current
    result["historical_publication_gate"] = {"formal_release": historical["formal_release"],
                                             "authorize_publish": historical["authorize_publish"]}


def smoke_bundle(work):
    archive, manifest = work / "fixture.zip", work / "fixture-manifest.json"
    data = b"UDAK release rehearsal signing fixture\n"
    with zipfile.ZipFile(archive, "x") as z:
        z.writestr(zipfile.ZipInfo("fixture.txt"), data)
    with zipfile.ZipFile(archive) as z:
        require(z.namelist() == ["fixture.txt"] and z.read("fixture.txt") == data, "SMOKE_ZIP")
    g0.record(manifest, {"scope": "synthetic signing fixture", "path": "fixture.txt",
                         "sha512": digest(data), "size": len(data), "archive_sha512": digest(archive.read_bytes())})
    return archive, manifest


def build_bundle(work, result):
    h.CANDIDATE_BASE = work / "candidate"
    h.CANDIDATE_BASE.mkdir()
    (h.CANDIDATE_BASE / ".owner").write_text(work.name)
    project = work / "project"
    tasks = [f":{module}:publishMavenJavaPublicationToCandidateRepository" for module in h.MODULES]
    command = h.gradle_command(h.gradle_distribution(work), work, project / "starter-testkit", "--init-script",
                               str(project / g0.OVERLAY), "phase6Resolution", *tasks)
    result["steps"].append(h.step("build-six-licensed-modules", command, work, timeout=420))
    g0.graph(work, result)
    return bundle(work, result)


def rehearse(work, result, smoke):
    snapshot(work, result)
    check_gate(work, result)
    inputs = smoke_bundle(work) if smoke else build_bundle(work, result)
    signing.gpg_verify(work, result, inputs)
    # The shared signing helper calls its first input "jar" independent of the container format.
    result["signature_proofs"]["zip"] = result["signature_proofs"].pop("jar")
    require(result["fixture_agent_stopped"] and all(s["child_reaped"] and s["process_group_quiesced"]
            for s in result["steps"]), "PROCESS_CLEANUP")


def main():
    smoke = sys.argv[1:] == ["--signing-smoke"]
    if sys.argv[1:] and not smoke:
        return 2
    result = {"schema_version": 1, "requirement": "RELEASE-021", "status": "FAIL", "steps": [],
              "started_at_utc": datetime.now(timezone.utc).isoformat(), "external_publications": 0,
              "authorize_publish": False, "production_keys_used": 0, "containers_started": 0}
    result["scope"] = "synthetic signing smoke" if smoke else "local six-module package and signing rehearsal"
    result["package_build"] = "NOT RUN"
    for event in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
        signal.signal(event, h.guard.interrupted)
    signal.alarm(120 if smoke else 600)
    try:
        g0.AUDIT.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(g0.AUDIT / "G0.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            require(shutil.disk_usage("/tmp").free >= (32 * 1024**2 if smoke else 4 * 1024**3), "DISK_HEADROOM")
            with h.workspace() as (work, cleanup):
                result["cleanup"] = cleanup
                rehearse(work, result, smoke)
            require(cleanup.get("status") == "PASS" and (smoke or cleanup.get("gradle_daemons_quiesced"))
                    and cleanup.get("temporary_directory_remaining") is False, "CLEANUP_INCOMPLETE")
            result["status"] = "PASS"
            if not smoke:
                result["package_build"] = "PASS"
            h.save(SMOKE_REPORT if smoke else REPORT, result)
    except Exception as error:
        result["status"] = "FAIL"
        result["failure_type"] = type(error).__name__
        if isinstance(error, g0.CheckError):
            result["check"] = str(error)
        if isinstance(error, RuntimeError):
            try:
                receipt = json.loads(str(error))
                if isinstance(receipt, dict) and "exit_code" in receipt:
                    result["failed_step"] = receipt
            except ValueError:
                pass
        name = "local-rehearsal-failed-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + ".json"
        h.save(g0.AUDIT / name, result)
    finally:
        signal.alarm(0)
    print(json.dumps({key: result[key] for key in ("status", "check", "failure_type", "failed_step", "cleanup")
                      if key in result}))
    return int(result["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
