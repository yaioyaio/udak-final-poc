#!/usr/bin/env python3
"""RELEASE-014 technical preflight on an operator-authorized dedicated local host.

PASS covers the checks below. The host owner must independently establish execution
authorization, dedication, and a native Intel/AMD platform without translation.
Linux and Docker can report emulated CPU identities. No SQL workload is run here.

Container prerequisites: https://learn.microsoft.com/sql/linux/quickstart-install-connect-docker?view=sql-server-ver16
Reviewed Docker host releases: https://docs.docker.com/engine/install/{ubuntu,debian,rhel}/
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
GIB = 1024**3
SOCKET = Path("/run/docker.sock")


def supported_distribution():
    fields = {}
    with Path("/etc/os-release").open(encoding="utf-8") as stream:
        for line in stream:
            key, _, value = line.rstrip().partition("=")
            if key in {"ID", "VERSION_ID"}:
                fields[key] = value.strip('"').strip("'")
    distro, version = fields.get("ID"), fields.get("VERSION_ID", "")
    if distro == "rhel":
        return re.fullmatch(r"(8|9|10)(\.\d+)?", version) is not None
    return version in {"ubuntu": ("22.04", "24.04", "26.04", "26.10"),
                       "debian": ("12", "13")}.get(distro, ())


def cpu_vendor_supported():
    with Path("/proc/cpuinfo").open(encoding="ascii") as stream:
        for line in stream:
            key, _, value = line.partition(":")
            if key.strip() == "vendor_id":
                return value.strip() in {"GenuineIntel", "AuthenticAMD"}
    return False


def available_memory():
    with Path("/proc/meminfo").open(encoding="ascii") as stream:
        for line in stream:
            match = re.fullmatch(r"MemAvailable:\s+(\d+) kB\s*", line)
            if match:
                return int(match[1]) * 1024
    return 0


def local_daemon_running():
    # Avoid connecting to a systemd activation socket with a stopped daemon.
    pid = Path("/run/docker.pid").read_text(encoding="ascii").strip()
    return (re.fullmatch("[1-9][0-9]{0,8}", pid) is not None and
            Path("/proc", pid, "comm").read_text(encoding="ascii").strip() == "dockerd" and
            SOCKET.is_socket())


def docker_fields(*args):
    # No user CLI configuration, contexts, proxy settings, or registry credentials.
    return subprocess.run(
        ["docker", "--host", "unix://" + str(SOCKET), "--config", "/proc/self", *args],
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/proc/self"},
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, timeout=6, check=True,
    ).stdout.strip()


def sqlserver_pin():
    pins = json.loads((ROOT / "tools/g2-server-images.json").read_text())["images"]
    pin, = [row for row in pins if row["profile"] == "SQLSERVER"]
    digest = pin["manifest_digest"]
    if (not re.fullmatch("sha256:[0-9a-f]{64}", digest) or
            pin["image"] != "mcr.microsoft.com/mssql/server@" + digest or
            pin["selector"] != "mcr.microsoft.com/mssql/server:2022-latest" or
            pin["platform"] != "linux/amd64" or pin["memory_mib"] != 4096 or pin["cpus"] != 2):
        raise ValueError("SQLSERVER_PIN")
    return pin


def probe():
    failures = []

    def check(code, read):
        try:
            if read():
                return True
        except (OSError, UnicodeError, ValueError, subprocess.SubprocessError):
            pass
        failures.append(code)
        return False

    if not check("HOST_LINUX_X86_64", lambda: sys.platform == "linux" and
                 os.uname().machine == "x86_64"):
        return failures
    check("CPU_VENDOR", cpu_vendor_supported)
    check("HOST_DISTRIBUTION_UNVERIFIED", supported_distribution)
    check("CGROUP_V2", lambda: {"memory", "cpu", "pids"}.issubset(
        Path("/sys/fs/cgroup/cgroup.controllers").read_text().split()))
    check("WORKSPACE_DISK_40_GIB", lambda: shutil.disk_usage(ROOT).free >= 40 * GIB)

    try:
        pin = sqlserver_pin()
    except (OSError, ValueError, KeyError, TypeError):
        return failures + ["SQLSERVER_PIN"]
    required_memory = (pin["memory_mib"] + 1024) * 1024**2
    check("HOST_AVAILABLE_MEMORY", lambda: available_memory() >= required_memory)
    check("HOST_CPU_CAPACITY", lambda: len(os.sched_getaffinity(0)) >= pin["cpus"])
    if not check("LOCAL_DOCKER_DAEMON", local_daemon_running):
        return failures
    try:
        system, arch, cgroup, cpus, memory = docker_fields(
            "info", "--format", "{{.OSType}} {{.Architecture}} {{.CgroupVersion}} {{.NCPU}} {{.MemTotal}}"
        ).split()
        cpus, memory = int(cpus), int(memory)
    except (OSError, ValueError, subprocess.SubprocessError):
        return failures + ["LOCAL_DOCKER_INFO"]
    check("DOCKER_LINUX_AMD64", lambda: system == "linux" and arch in {"amd64", "x86_64"})
    check("DOCKER_CGROUP_V2", lambda: cgroup == "2")
    check("DOCKER_CAPACITY", lambda: cpus >= pin["cpus"] and memory >= required_memory)

    # The exact digest must identify a local image. Format only immutable repo
    # digest membership and platform. Docker image inspect never pulls an image.
    template = ('{{.Os}}/{{.Architecture}} {{range .RepoDigests}}{{if eq . "' +
                pin["image"] + '"}}match{{end}}{{end}}')
    check("PINNED_LOCAL_IMAGE", lambda: docker_fields(
        "image", "inspect", "--format", template, pin["image"]) == "linux/amd64 match")
    return failures


if __name__ == "__main__":
    codes = probe()
    print(json.dumps({"readiness": "BLOCKED" if codes else "PASS", "failure_codes": codes,
                      "sqlserver_g5": "NOT RUN", "operator_evidence": "REQUIRED"}))
    sys.exit(2 if codes else 0)
