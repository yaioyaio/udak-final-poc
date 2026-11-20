#!/usr/bin/env python3
"""Read-only Oracle G5 readiness probe on a dedicated Linux ARM64 guest."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
GIB = 1024**3
ARM64 = {"aarch64", "arm64"}
ERRORS = (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError)
INFO_FORMAT = (
    "{{.OSType}}|{{.Architecture}}|{{.CgroupVersion}}|{{.NCPU}}|{{.MemTotal}}|{{.Driver}}|"
    '{{range .DriverStatus}}{{if eq (index . 0) "Backing Filesystem"}}{{index . 1}}{{end}}{{end}}|'
    '{{range .DriverStatus}}{{if eq (index . 0) "Supports d_type"}}{{index . 1}}{{end}}{{end}}|'
    "{{.DockerRootDir}}"
)

# Reuse the provider checks for procfs and safe, local Docker CLI access.
spec = importlib.util.spec_from_file_location("provider_host", Path(__file__).with_name("check-sqlserver-host.py"))
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


def read_public_receipt(relative):
    path = ROOT / relative
    try:
        canonical = path.resolve(strict=True)
    except RuntimeError:
        raise ValueError("Receipt path cannot be resolved") from None
    if canonical != path or not path.is_file():
        raise ValueError("Receipt must be a local regular file")
    return json.loads(path.read_text(encoding="utf-8"))


def pinned_image_present():
    pins = read_public_receipt("tools/g2-server-images.json")["images"]
    pin, = (item for item in pins if item["profile"] == "ORACLE")
    archive = read_public_receipt("evidence/PHASE5-CONTAINER-RETENTION.json")["profiles"]["ORACLE"]
    if (pin["platform"] != "linux/arm64" or archive["mount_count"] != 0
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", archive["image_id"])
            or not re.fullmatch(r"[a-z0-9][a-z0-9._/-]+@sha256:[a-f0-9]{64}", pin["image"])):
        return False
    image = host.docker_fields("image", "inspect", "--format",
                               "{{.Id}} {{.Os}}/{{.Architecture}} {{len .Config.Volumes}}", pin["image"])
    return image == f'{archive["image_id"]} linux/arm64 0'


def project_quota(data_root):
    fields = subprocess.run(
        ["findmnt", "-n", "-T", str(data_root), "-o", "FSTYPE,OPTIONS"],
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=True, text=True,
    ).stdout.split()
    if len(fields) != 2 or fields[0] != "xfs":
        return False
    options = set(fields[1].split(","))
    return "rw" in options and bool({"pquota", "prjquota"} & options) and "pqnoenforce" not in options


def probe():
    if sys.platform != "linux" or os.uname().machine not in ARM64:
        return ["GUEST_LINUX_ARM64"]

    failures = []

    def check(code, read):
        try:
            if read():
                return True
        except ERRORS:
            pass
        failures.append(code)
        return False

    check("GUEST_CGROUP_V2", lambda: {"cpu", "memory", "pids"}.issubset(
        Path("/sys/fs/cgroup/cgroup.controllers").read_text().split()))
    check("GUEST_CAPACITY", lambda: len(os.sched_getaffinity(0)) >= 2 and host.available_memory() >= 4 * GIB)
    check("WORKSPACE_DISK_40_GIB", lambda: shutil.disk_usage(ROOT).free >= 40 * GIB)
    if not check("LOCAL_DOCKER_DAEMON", host.local_daemon_running):
        return failures

    try:
        system, arch, cgroup, cpus, memory, driver, backing, dtype, data_path = host.docker_fields(
            "info", "--format", INFO_FORMAT).split("|")
        cpus, memory = int(cpus), int(memory)
        data_root = Path(data_path)
    except ERRORS:
        return failures + ["LOCAL_DOCKER_INFO"]

    check("DOCKER_LINUX_ARM64_CGROUP_V2", lambda: system == "linux" and arch in ARM64 and cgroup == "2")
    check("DOCKER_CAPACITY", lambda: cpus >= 2 and memory >= 4 * GIB)
    check("DEDICATED_DOCKER_EMPTY", lambda: not host.docker_fields("ps", "-a", "--latest", "--format", "{{.State}}"))
    check("DOCKER_OVERLAY2_XFS_DTYPE", lambda: (driver, backing, dtype) == ("overlay2", "xfs", "true"))
    if check("DOCKER_DATA_ROOT", lambda: data_root.is_absolute() and data_root.is_dir()):
        check("DOCKER_DATA_FREE_3_GIB", lambda: shutil.disk_usage(data_root).free >= 3 * GIB)
        check("XFS_PROJECT_QUOTA_MOUNT", lambda: project_quota(data_root))
    check("PINNED_LOCAL_ORACLE_IMAGE", pinned_image_present)
    return failures


if __name__ == "__main__":
    codes = probe()
    print(json.dumps({"requirement": "RELEASE-026", "readiness": "BLOCKED" if codes else "PASS",
                      "failure_codes": codes, "container_quota_acceptance": "NOT RUN",
                      "oracle_instance_g5": "NOT RUN"}))
    sys.exit(2 if codes else 0)
