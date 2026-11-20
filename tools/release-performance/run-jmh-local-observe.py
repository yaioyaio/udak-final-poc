#!/usr/bin/env python3
"""Build and protect one DB-free Observe cache-hit JMH pilot."""

import argparse
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
import time
import urllib.request
import zipfile

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parents[1]
MAVEN = "https://repo.maven.apache.org/maven2/"
JOPT_LICENSE = "https://raw.githubusercontent.com/jopt-simple/jopt-simple/jopt-simple-5.0.4/LICENSE.txt"
FIXTURE_CLASS = "dev.udak.bench.JdbcCacheHitBenchmark"
BENCHMARK = FIXTURE_CLASS + ".cacheHit"
FIXTURE = TOOLS / "JdbcCacheHitBenchmark.java"
DEPENDENCIES = TOOLS / "jmh-dependencies.json"
VARIANTS = {"WRAPPER": "34b5f273d6191262e1a08024b80a889402bcf782",
            "HMAC": "046b3bd08ed8c1a4ea1ca8087c34d6bb96f3fd77"}
ARTIFACTS = ("jmh-core", "jmh-generator-annprocess", "jopt-simple", "commons-math3")
SOURCE_DIR = "observe-core/src/main/java/dev/udak/observe"
PREPARE_WALL_SECONDS = 90


def load(file):
    spec = importlib.util.spec_from_file_location(file, TOOLS / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load("jmh-process-guard.py")
diagnosis = load("assess-local-observe.py")
plan = diagnosis.L1_FORK_PLAN
limits = diagnosis.L1_RESOURCE_PLAN


class Stopped(RuntimeError):
    """The authorized work stopped or a prerequisite was unavailable."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def file_bytes(path, maximum):
    if path.resolve(strict=True) != path or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("Public input rejected")
    return path.read_bytes()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def proposal(run_id):
    inputs = (Path(__file__).resolve(), TOOLS / "jmh-process-guard.py", TOOLS / "assess-local-observe.py",
              FIXTURE, DEPENDENCIES, ROOT / "tools/run-schema-regression.py")
    return {"schema_version": 1, "run_id": run_id, "authorized_runs": 1,
            "benchmark": BENCHMARK, "phase": "A/A", "source": VARIANTS["HMAC"],
            "jmh": plan, "resource_limits": limits,
            "inputs_sha256": {path.relative_to(ROOT).as_posix(): digest(file_bytes(path, 128 * 1024))
                              for path in inputs}}


def fetch(url, maximum, budget):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url, timeout=6) as response:
        if response.geturl() != url:
            raise ValueError("Dependency redirect")
        data = bytearray()
        while chunk := response.read1(64 * 1024):
            data.extend(chunk)
            budget.available()
            if len(data) > maximum:
                raise ValueError("Dependency size bound")
    return bytes(data)


def dependencies(work, budget):
    manifest = json.loads(file_bytes(DEPENDENCIES, 64 * 1024))
    if (manifest["schema_version"] != 1 or manifest["version"] != "1.37"
            or set(manifest["artifacts"]) != set(ARTIFACTS)):
        raise ValueError("JMH dependency inventory")
    parent = manifest["parent_pom"]
    if digest(fetch(MAVEN + parent["maven_path"] + ".pom", 200000, budget)) != parent["sha256"]:
        raise ValueError("JMH parent POM checksum")
    jars = {}
    for name in ARTIFACTS:
        pin = manifest["artifacts"][name]
        url = MAVEN + pin["maven_path"]
        jar = fetch(url + ".jar", 3 * 1024**2, budget)
        if digest(jar) != pin["jar_sha256"] or digest(fetch(url + ".pom", 200000, budget)) != pin["pom_sha256"]:
            raise ValueError("JMH dependency checksum")
        jars[name] = work / (name + ".jar")
        jars[name].write_bytes(jar)
        with zipfile.ZipFile(jars[name]) as archive:
            for entry, sha in pin["jar_notice_sha256"].items():
                if archive.getinfo(entry).file_size > 128 * 1024 or digest(archive.read(entry)) != sha:
                    raise ValueError("JMH legal notice checksum")
    if digest(fetch(JOPT_LICENSE, 128 * 1024, budget)) != manifest["jopt_simple_license_sha256"]:
        raise ValueError("jopt-simple license checksum")
    return jars


def git(*args):
    return subprocess.run(["/usr/bin/git", "--no-lazy-fetch", "--no-replace-objects", *args], cwd=ROOT,
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          timeout=5, check=True).stdout


def sources(revision, target):
    items = git("ls-tree", "-rlz", revision, "--", SOURCE_DIR).rstrip(b"\0").split(b"\0")
    if not 1 <= len(items) <= 16:
        raise ValueError("Observe source inventory")
    files = []
    for item in items:
        metadata, encoded = item.split(b"\t")
        mode, kind, sha, size = metadata.split()
        name = encoded.decode("ascii")
        if (mode != b"100644" or kind != b"blob" or not 0 < int(size) <= 128 * 1024
                or not re.fullmatch(re.escape(SOURCE_DIR) + r"/[A-Za-z][A-Za-z0-9]*\.java", name)):
            raise ValueError("Observe source path")
        data = git("cat-file", "blob", sha.decode("ascii"))
        if len(data) != int(size):
            raise ValueError("Observe source size")
        file = target / Path(name).name
        file.write_bytes(data)
        files.append(str(file))
    return files


def executable(name):
    binary = shutil.which(name)
    if binary is None:
        raise ValueError("JDK tool unavailable")
    return str(Path(binary).resolve(strict=True))


class Batch:
    def __init__(self, work, report, measured, cancelled):
        self.work, self.report = work, report
        self.measured, self.cancelled = measured, cancelled
        seconds = limits["wall_seconds"] if measured else PREPARE_WALL_SECONDS
        self.started = time.monotonic()
        self.deadline = self.started + seconds
        self.cpu_used = 0.0

    def available(self):
        remaining = self.deadline - time.monotonic()
        if self.cancelled() or remaining < 7 or limits["tree_cpu_seconds"] - self.cpu_used < 1:
            raise Stopped("BATCH_LIMIT_OR_CANCEL")
        return remaining

    def step(self, name, command, timeout):
        # Reserve time for termination and reaping.
        wall = min(timeout, self.available() - 6)
        cpu = min(limits["peak_process_cpu_seconds"], limits["tree_cpu_seconds"] - self.cpu_used)
        output = self.work / (name + ".output")

        def launched():
            if name.startswith("sample-"):
                self.report["workload_started"] = True

        record = guard.run_owned(command, self.work, output, wall_seconds=wall,
                                 rss_bytes=limits["peak_tree_rss_bytes"], cpu_seconds=cpu,
                                 watch_pressure=self.measured, cancelled=self.cancelled, on_start=launched)
        self.cpu_used += record["cpu_seconds"]
        self.report["steps"][name] = record
        if record["status"] != "PASS":
            raise Stopped(record["reason"])
        self.available()
        return output

    def resources(self, cleanup):
        steps = self.report["steps"].values()
        elapsed = round(time.monotonic() - self.started, 6)
        return {"wall_seconds": elapsed, "peak_tree_rss_bytes": max(
                    (step["peak_tree_rss_bytes"] for step in steps), default=0),
                "tree_cpu_seconds": self.cpu_used, "peak_process_cpu_seconds": max(
                    (step["cpu_seconds"] for step in steps), default=0),
                "peak_active_forks": int(any(name.startswith("sample-") for name in self.report["steps"])),
                "memory_warning_observed": any(step["reason"] in
                    ("HOST_MEMORY_PRESSURE", "HOST_PRESSURE_UNAVAILABLE") for step in steps),
                "cleanup_confirmed": cleanup.get("status") == "PASS" and cleanup.get("remaining") is False}


def java_command(classpath, heap, main_class="org.openjdk.jmh.Main"):
    return [executable("java"), f"-Xmx{heap}m", "-XX:MaxMetaspaceSize=128m",
            f"-XX:ActiveProcessorCount={plan['active_processor_count']}", "-cp", classpath, main_class]


def link(batch, variant, jars):
    work = batch.work / variant.lower()
    work.mkdir()
    classes = work / "classes"
    classes.mkdir()
    core = str(jars["jmh-core"])
    processor = os.pathsep.join((str(jars["jmh-generator-annprocess"]), core))
    fixture = work / FIXTURE.name
    fixture.write_bytes(file_bytes(FIXTURE, 32 * 1024))
    command = [executable("javac"), "-J-Xmx256m", "-J-XX:MaxMetaspaceSize=128m",
               "-J-XX:ActiveProcessorCount=2", "--release", "17", "-cp", core,
               "-processorpath", processor, "-processor", "org.openjdk.jmh.generators.BenchmarkProcessor",
               "-d", str(classes), str(fixture), *sources(VARIANTS[variant], work)]
    batch.step("compile-" + variant.lower(), command, 30)
    classpath = os.pathsep.join((str(classes), core, str(jars["jopt-simple"]), str(jars["commons-math3"])))
    command = java_command(classpath, 128) + ["-l"]
    output = batch.step("discover-" + variant.lower(), command, 10)
    if file_bytes(output, 8192).decode("ascii").split() != ["Benchmarks:", BENCHMARK]:
        raise ValueError("Expected exactly one JMH benchmark")
    output = batch.step("cache-hit-" + variant.lower(), java_command(classpath, 128, FIXTURE_CLASS), 10)
    if file_bytes(output, 8192).strip() != b"CACHE_HIT_PASS":
        raise ValueError("Unverified cache-hit fixture")
    return classpath


def sample(batch, classpath, number):
    name = f"sample-{number}"
    result = batch.work / (name + ".json")
    command = java_command(classpath, plan["heap_mib"]) + [
        "^" + re.escape(BENCHMARK) + "$", "-f", "0", "-t", str(plan["benchmark_threads"]),
        "-wi", str(plan["warmup_iterations"]), "-i", str(plan["measurement_iterations"]),
        "-w", f"{plan['iteration_seconds']}s", "-r", f"{plan['iteration_seconds']}s",
        "-tu", "ns", "-bm", "avgt", "-foe", "true", "-prof", "gc", "-rf", "json", "-rff", str(result),
    ]
    batch.step(name, command, 30)
    metric, = json.loads(file_bytes(result, 128 * 1024))
    latency = metric["primaryMetric"]
    allocation = metric["secondaryMetrics"]["gc.alloc.rate.norm"]
    if (metric["benchmark"] != BENCHMARK or metric["mode"] != "avgt"
            or metric["forks"] != 0 or metric["threads"] != plan["benchmark_threads"]
            or latency["scoreUnit"] != "ns/op" or allocation["scoreUnit"] != "B/op"
            or not diagnosis.finite_number(latency["score"], minimum=0.000001)
            or not diagnosis.finite_number(allocation["score"])):
        raise ValueError("JMH result protocol")
    return [latency["score"], allocation["score"]]


def approval(run_id):
    path = ROOT / "evidence" / f"OBSERVE-L1-{run_id}-APPROVAL.json"
    expected = {**proposal(run_id), "status": "APPROVED", "approval_basis": "EXPLICIT_USER_CONFIRMATION"}
    try:
        data = file_bytes(path, 32 * 1024)
        if json.dumps(json.loads(data), sort_keys=True) != json.dumps(expected, sort_keys=True):
            raise ValueError("Approval differs")
    except (OSError, ValueError):
        raise Stopped("APPROVAL_REQUIRED") from None
    return digest(data)


def git_private(name):
    root = ROOT / ".git"
    if root.resolve(strict=True) != root or not root.is_dir():
        raise ValueError("Use the primary Git checkout")
    path = root / name
    if path.resolve() != path:
        raise ValueError("Private directory redirected")
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def execute(report, run_id, cancelled):
    schema = diagnosis.g5_verifier().schema
    if run_id is not None and guard.memory_pressure(Path("/tmp").resolve()) != 1:
        raise Stopped("HOST_MEMORY_NOT_READY")
    common = git_private("udak-g2-managed")
    with os.fdopen(os.open(common / "RUN.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        marker = (git_private("udak-observe-l1") / f"{run_id}.claimed") if run_id else None
        if marker is not None and marker.exists():
            raise Stopped("APPROVAL_ALREADY_CLAIMED")
        batch = None
        try:
            with schema.workspace() as (work, cleanup):
                report["cleanup"] = cleanup
                batch = Batch(work, report, run_id is not None, cancelled)
                try:
                    jars = dependencies(work, batch)
                    if run_id is None:
                        for variant in VARIANTS:
                            link(batch, variant, jars)
                    else:
                        classpath = link(batch, "HMAC", jars)
                        if guard.memory_pressure(work) != 1:
                            raise Stopped("HOST_MEMORY_NOT_READY")
                        digest_before_claim = approval(run_id)
                        if digest_before_claim != report["approval_sha256"]:
                            raise Stopped("APPROVAL_CHANGED")
                        batch.available()
                        with marker.open("x") as claim:
                            claim.write(digest_before_claim + "\n")
                            claim.flush()
                            os.fsync(claim.fileno())
                        report["workload_run_claimed"] = True
                        for block in range(plan["paired_blocks_proposed"]):
                            left = sample(batch, classpath, 2 * block)
                            right = sample(batch, classpath, 2 * block + 1)
                            report["aa_ns_per_op"].append([left[0], right[0]])
                            report["aa_alloc_bytes_per_op"].append([left[1], right[1]])
                except guard.CleanupUnconfirmed:
                    raise schema.native.PreservationRequired("JMH cleanup unconfirmed") from None
        finally:
            if batch is not None:
                report["resources"] = batch.resources(cleanup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--proposal", metavar="RUN_ID")
    mode.add_argument("--run", metavar="RUN_ID")
    args = parser.parse_args()
    run_id = args.proposal or args.run
    if run_id is not None and not re.fullmatch(r"[A-Z][A-Z0-9-]{0,31}", run_id):
        parser.error("invalid run ID")
    if args.proposal:
        print(json.dumps({**proposal(args.proposal), "approval": "PENDING"}))
        return 0

    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    for event in (signal.SIGINT, signal.SIGTERM):
        signal.signal(event, stop)
    report = {"schema_version": 1, "status": "NOT RUN", "benchmark": BENCHMARK, "jmh_version": "1.37",
              "workload_started": False, "workload_run_claimed": False, "steps": {}, "real_database_starts": 0,
              "source_revisions": {"HMAC": VARIANTS["HMAC"]} if args.run else VARIANTS}
    try:
        if args.run:
            report["run_id"] = run_id
            report["approval_sha256"] = approval(run_id)
            report.update(regression_limit_percent=None, aa_ns_per_op=[], aa_alloc_bytes_per_op=[],
                          ab_ns_per_op=[], ab_alloc_bytes_per_op=[])
        else:
            report["inputs_sha256"] = proposal("PREPARATION")["inputs_sha256"]
        execute(report, args.run, lambda: stopping)
        if args.run and not diagnosis.resource_receipt_passes(report["resources"]):
            raise Stopped("RESOURCE_EVIDENCE")
        report["status"] = "RECORDED" if args.run else "PASS"
    except Stopped as error:
        report["reason"] = str(error)
        if args.prepare:
            report["status"] = "FAIL"
        elif report["workload_started"]:
            report["status"] = "INCONCLUSIVE"
    except (RuntimeError, ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        report["status"] = "INCONCLUSIVE" if report["workload_started"] else "FAIL"
        report["reason"] = type(error).__name__
    print(json.dumps(report, allow_nan=False))
    return 0 if report["status"] in ("PASS", "RECORDED") else (2 if report["status"] == "NOT RUN" else 1)


if __name__ == "__main__":
    sys.exit(main())
