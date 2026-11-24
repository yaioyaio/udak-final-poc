#!/usr/bin/env python3
"""Verify the published ThingsBoard COUNT change through JDBC and the inventory PR report."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "dao/src/main/java/org/thingsboard/server/dao/sql/device/DefaultNativeDeviceRepository.java"
BASE = ("fd9dc186e4134d4de9a129a91a7c4b1461781cde", "b039f30d32876e670abbb901df200fe30c4e9b6a")
HEAD = ("924c9cf5d038084fda404185c8e7a60b3cd508f6", "c4ba36ce2ebe71a91a79adbf78b19881e1ff039b")
DOCKER = [shutil.which("docker") or "/usr/local/bin/docker", "-H", "unix:///var/run/docker.sock"]
IMAGE = "postgres:18"
INDEX = "sha256:eb63372c1e05c755f55fa30cbd07aecc443676fc6c0fa90b9002d01537841e1a"

spec = importlib.util.spec_from_file_location("guard", ROOT / "tools/run-phase1.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def upstream(pair):
    revision, expected_blob = pair
    url = f"https://raw.githubusercontent.com/thingsboard/thingsboard/{revision}/{SOURCE}"
    with urllib.request.urlopen(url, timeout=7) as response:
        if response.geturl() != url:
            raise ValueError("Unexpected upstream source origin")
        data = response.read(65537)
    header = f"blob {len(data)}\0".encode()
    if len(data) > 65536 or hashlib.sha1(header + data).hexdigest() != expected_blob:
        raise ValueError("Pinned upstream source mismatch")
    return data.decode()


def count_sql():
    before, after = upstream(BASE), upstream(HEAD)
    base = re.findall(r'"(SELECT count\(id\) FROM device;)"', before)
    head = re.findall(r'String\.format\("(SELECT count\(id\) FROM device WHERE tenant_id = \'%s\';)", tenantId\)', after)
    if len(base) != 1 or len(head) != 1:
        raise ValueError("Unexpected upstream COUNT declaration")
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    return first, second, base[0], head[0] % first, head[0] % second


def inspect(*args, timeout=8, env=None):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
    if result.returncode:
        raise RuntimeError("Bounded fixture command failed")
    return result.stdout.strip()


def host_ready():
    level = inspect("/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level")
    swap = inspect("/usr/sbin/sysctl", "-n", "vm.swapusage")
    free = re.search(r"\bfree = ([0-9.]+)M", swap)
    return level == "1" and free is not None and float(free[1]) >= 768


def docker_count(owner):
    return inspect(*DOCKER, "ps", "-aq", "--no-trunc",
                   "--filter", f"label=dev.udak.thingsboard-pilot={owner}").splitlines()


def compile_replay(work, jdbc, java, replay_class="UpstreamDeviceCount"):
    classes = work / "classes"
    classes.mkdir()
    files = sorted((ROOT / "observe-core/src/main/java").rglob("*.java"))
    files += sorted((ROOT / "legacy-observe/src/main/java/dev/udak/observe/jdbc").glob("*.java"))
    files += [
        ROOT / "sql-inventory/src/main/java/dev/udak/inventory/InventoryCapture.java",
        ROOT / "tools/thingsboard-pilot/dev/udak/pilot" / f"{replay_class}.java",
    ]
    guard.run_step("compile", [str(java / "bin/javac"), "-J-Xmx160m", "-J-XX:ActiveProcessorCount=1",
                   "--release", "17", "-cp", str(jdbc), "-d", str(classes), *map(str, files)], work, timeout=20)
    return classes


def replay(work, classes, jdbc, java, sql_values, replay_class="UpstreamDeviceCount"):
    if not host_ready():
        raise RuntimeError("Host resource preflight did not pass")
    digest = inspect(*DOCKER, "image", "ls", "--filter", f"reference={IMAGE}", "--digests", "--format", "{{.Digest}}")
    if digest != INDEX:
        raise RuntimeError("Pinned PostgreSQL image is missing")
    owner = uuid.uuid4().hex
    password = secrets.token_hex(24)
    try:
        container = inspect(*DOCKER, "run", "-d", "--rm", "--pull", "never", "--restart", "no",
                            "--memory", "512m", "--memory-swap", "512m", "--cpus", "1", "--pids-limit", "128",
                            "--log-driver", "none", "--tmpfs", "/var/lib/postgresql:rw,size=256m",
                            "-p", "127.0.0.1::5432", "--label", f"dev.udak.thingsboard-pilot={owner}",
                            "-e", "POSTGRES_PASSWORD", IMAGE, timeout=15,
                            env={"PATH": "/opt/homebrew/bin:/usr/bin:/bin", "POSTGRES_PASSWORD": password})
        if docker_count(owner) != [container]:
            raise RuntimeError("Unexpected fixture ownership")
        mounts = inspect(*DOCKER, "inspect", "--format",
                         '{{range .Mounts}}{{if eq .Type "volume"}}{{.Destination}}{{end}}{{end}}', container)
        if mounts:
            raise RuntimeError("Fixture must not allocate persistent volumes")
        for _ in range(20):
            if not host_ready():
                raise RuntimeError("Host resource guard stopped fixture")
            ready = subprocess.run([*DOCKER, "exec", container, "pg_isready", "-h", "127.0.0.1",
                                    "-t", "1"], capture_output=True, timeout=3).returncode
            if ready == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("PostgreSQL fixture did not become ready")
        port = re.fullmatch(r"127\.0\.0\.1:(\d+)", inspect(*DOCKER, "port", container, "5432/tcp"))
        if port is None:
            raise RuntimeError("Unverified fixture port binding")
        guard.run_step("jdbc-replay", [str(java / "bin/java"), "-Xmx160m", "-XX:ActiveProcessorCount=1",
            "-cp", f"{classes}:{jdbc}", f"dev.udak.pilot.{replay_class}", str(work), port[1]],
            work, timeout=15, private_input=("\n".join((password, *sql_values)) + "\n").encode())
    finally:
        for container in docker_count(owner):
            inspect(*DOCKER, "stop", "-t", "3", container, timeout=10)
        for _ in range(12):
            if not docker_count(owner):
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("Fixture cleanup unconfirmed")


def check_reports(work):
    for name in ("BASE", "HEAD", "CONTROL"):
        target = work / name.lower() / "SQL-INVENTORY.json"
        target.parent.mkdir()
        (work / f"{name}.json").rename(target)
    launcher = ("import os,runpy,sys; os.chdir(sys.argv.pop(2)); "
                "sys.argv.pop(0); runpy.run_path(sys.argv[0],run_name='__main__')")
    command = [sys.executable, "-B", "-c", launcher, str(ROOT / "tools/sql-inventory.py"), str(work),
               "--fail-on-change"]
    for name, base, head, expected in (("change", "BASE", "HEAD", 3), ("control", "HEAD", "CONTROL", 0)):
        invocation = [*command, "--base", f"{base.lower()}/SQL-INVENTORY.json",
                      "--head", f"{head.lower()}/SQL-INVENTORY.json"]
        guard.run_step(name, invocation, work, timeout=10, expected=expected)
        result = json.loads((work / f"{name}.output").read_bytes())
        if result["status"] != "COMPLETE" or result["changes_detected"] != (expected == 3) or len(result["queries"]) != 1:
            raise ValueError("Unexpected PR report verdict")
        query, = result["queries"]
        if query["framework"] != "JDBC" or query["shape_status"] != ("DIFFERENT" if expected else "UNCHANGED"):
            raise ValueError("Unexpected PR report shape status")
        if expected and (len(query["added_observed_shapes"]) != 1 or len(query["absent_observed_shapes"]) != 1
                         or len(query["impacted_test_ids"]) != 1):
            raise ValueError("Expected one changed SQL shape and impacted test")
        if expected:
            guard.run_step("pr-markdown", [*invocation, "--format", "markdown"], work, timeout=10, expected=3)
            markdown = (work / "pr-markdown.output").read_text()
            if "OBSERVED_SHAPES_ADDED" not in markdown or "OBSERVED_SHAPES_ABSENT" not in markdown:
                raise ValueError("Markdown PR report did not show both fingerprint changes")


def main():
    if len(sys.argv) != 2:
        raise ValueError("Pass the verified PostgreSQL JDBC JAR path")
    jdbc = Path(sys.argv[1]).resolve(strict=True)
    java = Path(inspect("/usr/libexec/java_home", "-v", "21"))
    sql_values = count_sql()
    with guard.workspace("udak-thingsboard-count-replay-") as (work, cleanup):
        classes = compile_replay(work, jdbc, java)
        replay(work, classes, jdbc, java, sql_values)
        check_reports(work)
    print(json.dumps({"status": "PASS", "base_commit": BASE[0], "head_commit": HEAD[0],
                      "postgresql_count_assertions": 3, "pr_shape_changes": 1,
                      "literal_only_control_changes": 0, "container_cleanup": "PASS", "cleanup": cleanup}))


if __name__ == "__main__":
    main()
