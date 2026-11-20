#!/usr/bin/env python3
"""Read-only RELEASE-021 preflight for one explicitly selected Parallels guest."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BIN_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin"
ERRORS = (OSError, UnicodeError, ValueError, subprocess.SubprocessError)

# Only these tokens can reach the application. Other configuration (including
# identifiers, owner, adapters, paths and addresses) flows straight to the filter.
VM_FILTER = """
$1 == "State:" && $2 ~ /^(running|paused|suspended|stopped)$/ { print "state", $2 }
$1 == "OS:" && $2 ~ /^(ubuntu|debian|fedora|centos|redhat|linux|win-11)$/ { print "os", $2 }
$1 == "cpu" {
    for (i = 2; i <= NF; i++) {
        if ($i ~ /^cpus=[1-9][0-9]*$/) print "cpus", substr($i, 6)
        if ($i ~ /^type=(arm|arm64|x86|x86_64|intel|amd)$/) print "type", substr($i, 6)
    }
}
$1 == "memory" {
    for (i = 2; i <= NF; i++)
        if ($i ~ /^size=[1-9][0-9]*Mb$/) print "memory_mib", substr($i, 6, length($i)-7)
}
"""
ENGINE_FORMAT = (
    "{{.OSType}}|{{.Architecture}}|{{.CgroupVersion}}|{{.ServerVersion}}|{{.Driver}}|"
    '{{range .DriverStatus}}{{if eq (index . 0) "Backing Filesystem"}}{{index . 1}}{{end}}{{end}}'
)


def read_command(args, **kwargs):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True,
                          text=True, timeout=6, **kwargs).stdout.strip()


def parse_vm(filtered):
    fields = {}
    for line in filtered.splitlines():
        key, value = line.split()
        if key in fields:
            raise ValueError("ambiguous VM field")
        fields[key] = int(value) if key in ("cpus", "memory_mib") else value
    if set(fields) != {"state", "os", "cpus", "type", "memory_mib"}:
        raise ValueError("incomplete VM configuration")
    return fields


def vm_facts(name):
    binary = shutil.which("prlctl", path=BIN_PATH)
    if not binary:
        raise ValueError("unavailable")
    with subprocess.Popen([binary, "list", "-i", name], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL) as proc:
        try:
            filtered = read_command(["/usr/bin/awk", VM_FILTER], stdin=proc.stdout)
            if proc.wait(timeout=2):
                raise ValueError("VM inventory failed")
        finally:
            proc.stdout.close()
            if proc.poll() is None:
                proc.kill()
    return parse_vm(filtered)


def swap_free(value):
    match = re.search(r"\bfree\s*=\s*(\d+(?:\.\d+)?)\s*([KMGT])\b", value)
    if not match:
        raise ValueError("swap unavailable")
    return int(Decimal(match[1]) * 1024 ** ("KMGT".index(match[2]) + 1))


def host_facts():
    if platform.system() != "Darwin":
        raise ValueError("requires Darwin")

    def sysctl(key):
        return read_command(["/usr/sbin/sysctl", "-n", key], stdin=subprocess.DEVNULL)

    arm, pressure = sysctl("hw.optional.arm64"), int(sysctl("kern.memorystatus_vm_pressure_level"))
    arch = "arm64" if arm == "1" else platform.machine()
    cores, memory = int(sysctl("hw.physicalcpu")), int(sysctl("hw.memsize"))
    if arch not in {"arm64", "x86_64"} or arm not in {"0", "1"} or pressure not in (1, 2, 4) or min(cores, memory) < 1:
        raise ValueError("unexpected host facts")
    return {"architecture": arch, "physical_cores": cores, "memory_bytes": memory,
            "memory_pressure_level": pressure, "swap_free_bytes": swap_free(sysctl("vm.swapusage")),
            "workspace_free_bytes": shutil.disk_usage(ROOT).free}


def engine_facts():
    empty = Path("/var/empty")
    binary = shutil.which("docker", path=BIN_PATH)
    if not binary or not Path("/var/run/docker.sock").is_socket() or not empty.is_dir() or any(empty.iterdir()):
        raise ValueError("local engine unavailable")
    output = read_command([binary, "--config", str(empty), "--host", "unix:///var/run/docker.sock",
                           "info", "--format", ENGINE_FORMAT], stdin=subprocess.DEVNULL,
                          env={"HOME": str(empty), "PATH": BIN_PATH, "LC_ALL": "C"})
    system, arch, cgroup, version, driver, fs = output.split("|")
    if (system != "linux" or arch not in {"aarch64", "arm64", "amd64", "x86_64"} or cgroup not in {"1", "2"}
            or not re.fullmatch(r"\d+\.\d+\.\d+([.\-+][0-9A-Za-z.\-]+)?", version)
            or not re.fullmatch(r"[a-z0-9_\-]{1,32}", driver)
            or not re.fullmatch(r"[a-z0-9_\-]{0,32}", fs)):
        raise ValueError("unknown engine format")
    return {"os": system, "architecture": arch, "cgroup_version": cgroup, "server_version": version,
            "storage_driver": driver, "backing_filesystem": fs or None}


def qualification(host, engine):
    sql = "UNVERIFIED"
    if host and host["architecture"] == "arm64":
        sql = "BLOCKED_ARM_HOST"
    storage = "UNVERIFIED"
    if engine:
        ready = (engine["architecture"] in ("arm64", "aarch64") and engine["cgroup_version"] == "2"
                 and engine["storage_driver"] == "overlay2" and engine["backing_filesystem"] == "xfs")
        storage = "PREREQUISITES_PRESENT" if ready else "PREREQUISITES_UNMET"
    return {"native_sqlserver_on_selected_host": sql, "oracle_mac_engine_architecture_and_storage": storage,
            "oracle_container_quota_acceptance": "NOT RUN", "guest_engine_and_storage": "UNVERIFIED",
            "sqlserver_g5": "NOT RUN", "oracle_instance_g5": "NOT RUN"}


def self_test():
    sample = "State: suspended\nOS: ubuntu\n cpu cpus=2 auto=off mode=64 type=arm\n memory size=4096Mb auto=off\n"
    facts = parse_vm(read_command(["/usr/bin/awk", VM_FILTER], input=sample + "Owner: ignored\n"))
    if facts != {"state": "suspended", "os": "ubuntu", "cpus": 2, "type": "arm", "memory_mib": 4096}:
        return False
    base = {"architecture": "aarch64", "cgroup_version": "2", "storage_driver": "overlay2", "backing_filesystem": "xfs"}
    return (swap_free("free = 1162.81M (encrypted)") == 1219294658 and
            qualification(None, base)["oracle_mac_engine_architecture_and_storage"] == "PREREQUISITES_PRESENT" and
            qualification({"architecture": "arm64"}, None)["native_sqlserver_on_selected_host"] == "BLOCKED_ARM_HOST" and
            qualification(None, dict(base, storage_driver="overlayfs"))["oracle_mac_engine_architecture_and_storage"]
            == "PREREQUISITES_UNMET")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--vm", metavar="NAME")
    choice.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        passed = self_test()
        print(json.dumps({"self_test": "PASS" if passed else "FAIL"}))
        return 0 if passed else 1
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._()-]{0,127}", args.vm):
        parser.error("unsupported VM name")
    facts, failures = {}, []
    for key, probe in (("mac_host", host_facts), ("parallels_configuration", lambda: vm_facts(args.vm)),
                       ("mac_local_engine", engine_facts)):
        try:
            facts[key] = probe()
        except ERRORS:
            facts[key] = None
            failures.append(key)
    print(json.dumps({"schema_version": 1, "requirement": "RELEASE-021",
                      "probe_status": "PARTIAL" if failures else "COMPLETE", "unavailable": failures,
                      **facts, "qualification": qualification(facts["mac_host"], facts["mac_local_engine"])}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
