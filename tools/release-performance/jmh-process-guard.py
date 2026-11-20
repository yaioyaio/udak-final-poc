"""Own and meter one child JVM in a dedicated session."""

import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

POLL_SECONDS = 0.5
TERM_GRACE = 2
KILL_GRACE = 2
LIMITED_EXEC = """
import os, resource, sys
cpu = int(sys.argv[1])
resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
resource.setrlimit(resource.RLIMIT_FSIZE, (16777216, 16777216))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
os.umask(0o077)
os.execv(sys.argv[2], sys.argv[2:])
"""


class CleanupUnconfirmed(RuntimeError):
    """The workspace and evidence must be preserved."""


def environment(work):
    return {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C", "LC_ALL": "C",
            "TMPDIR": str(work), "HOME": str(work)}


def memory_pressure(work):
    try:
        probe = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level"], env=environment(work),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=2, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return int(probe) if probe in (b"1", b"2", b"4") else None


def seconds(value):
    if not re.fullmatch(r"(?:[0-9]+-)?(?:[0-9]+:)+[0-9]+(?:\.[0-9]+)?", value):
        raise ValueError("Unrecognized process CPU time")
    days, separator, clock = value.partition("-")
    total = 0.0
    for field in (clock if separator else days).split(":"):
        total = total * 60 + float(field)
    return total + (int(days) * 86400 if separator else 0)


def inventory(work):
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,ppid=,pgid=,rss=,state=,time="], env=environment(work),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True, timeout=2,
    ).stdout
    if not 0 < len(result) <= 2 * 1024**2:
        raise ValueError("Process inventory bounds")
    rows = {}
    for line in result.decode("ascii").splitlines():
        pid, ppid, pgid, rss, state, cpu = line.split()
        rows[int(pid)] = (int(ppid), int(pgid), int(rss) * 1024, state, seconds(cpu))
    return rows


def live_group(pid, work):
    rows = inventory(work)
    group = {number for number, item in rows.items() if item[1] == pid}
    if pid in rows and rows[pid][1] != pid:
        raise CleanupUnconfirmed("OWNED_LEADER_GROUP_CHANGED")
    # JMH is run in-process. A child that left the owned group makes cleanup uncertain.
    if any(item[0] in group and item[1] != pid for item in rows.values()):
        raise CleanupUnconfirmed("OWNED_DESCENDANT_LEFT_GROUP")
    return {number: rows[number] for number in group if not rows[number][3].startswith("Z")}


def stop_group(pid, signum):
    # The leader is still our unreaped child, so its group ID cannot be reused.
    try:
        os.killpg(pid, signum)
    except ProcessLookupError:
        pass


def inspect_group(pid, work, rss_cap, cpu_cap):
    live = live_group(pid, work)
    rss = sum(item[2] for item in live.values())
    cpu = sum(item[4] for item in live.values())
    if live.keys() - {pid}:
        return live, rss, "UNEXPECTED_CHILD"
    if rss > rss_cap:
        return live, rss, "RSS_LIMIT"
    if cpu >= cpu_cap:
        return live, rss, "CPU_LIMIT"
    return live, rss, None


def run_owned(command, work, output, *, wall_seconds, rss_bytes, cpu_seconds,
              watch_pressure=False, cancelled=lambda: False, on_start=lambda: None, poll_seconds=POLL_SECONDS):
    if not Path(command[0]).is_absolute() or min(wall_seconds, rss_bytes, cpu_seconds) <= 0:
        raise ValueError("Invalid owned command or limits")
    started = time.monotonic()
    hard_cpu = max(1, math.floor(cpu_seconds))
    peak_rss = 0
    reason = None
    with output.open("xb") as stream:
        proc = subprocess.Popen([sys.executable, "-I", "-S", "-c", LIMITED_EXEC, str(hard_cpu), *command],
                                cwd=work, env=environment(work), stdin=subprocess.DEVNULL,
                                stdout=stream, stderr=subprocess.DEVNULL, start_new_session=True)
        pid = proc.pid
        try:
            on_start()
            while True:
                live, rss, reason = inspect_group(pid, work, rss_bytes, hard_cpu)
                peak_rss = max(peak_rss, rss)
                if reason or not live:
                    break
                if cancelled():
                    reason = "CANCELLED"
                elif time.monotonic() - started >= wall_seconds:
                    reason = "WALL_LIMIT"
                elif watch_pressure and (pressure := memory_pressure(work)) != 1:
                    reason = "HOST_MEMORY_PRESSURE" if pressure else "HOST_PRESSURE_UNAVAILABLE"
                if reason:
                    break
                time.sleep(poll_seconds)
        except CleanupUnconfirmed:
            stop_group(pid, signal.SIGTERM)
            stop_group(pid, signal.SIGKILL)
            raise
        except (OSError, ValueError, subprocess.SubprocessError):
            reason = "PROCESS_INVENTORY_UNAVAILABLE"
        except BaseException:
            stop_group(pid, signal.SIGTERM)
            stop_group(pid, signal.SIGKILL)
            raise CleanupUnconfirmed("SUPERVISOR_INTERRUPTED") from None

        if reason:
            stop_group(pid, signal.SIGTERM)
        deadline = time.monotonic() + (TERM_GRACE if reason else 1)
        killed = False
        while True:
            try:
                live = live_group(pid, work)
            except (OSError, ValueError, subprocess.SubprocessError, CleanupUnconfirmed):
                stop_group(pid, signal.SIGKILL)
                raise CleanupUnconfirmed("GROUP_CLEANUP_UNCONFIRMED") from None
            if not live:
                try:
                    reaped, status, usage = os.wait4(pid, os.WNOHANG)
                except ChildProcessError:
                    raise CleanupUnconfirmed("CHILD_REAP_UNCONFIRMED") from None
                if reaped == pid:
                    proc.returncode = os.waitstatus_to_exitcode(status)
                    break
            if time.monotonic() >= deadline:
                if killed:
                    raise CleanupUnconfirmed("GROUP_CLEANUP_TIMED_OUT")
                stop_group(pid, signal.SIGKILL)
                killed = True
                deadline = time.monotonic() + KILL_GRACE
            time.sleep(min(poll_seconds, 0.1))

    cpu = usage.ru_utime + usage.ru_stime
    peak_rss = max(peak_rss, usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024))
    elapsed = time.monotonic() - started
    if reason is None:
        if peak_rss > rss_bytes:
            reason = "RSS_LIMIT"
        elif cpu > cpu_seconds or (proc.returncode in (-signal.SIGXCPU, -signal.SIGKILL) and cpu >= hard_cpu * 0.98):
            reason = "CPU_LIMIT"
        elif proc.returncode:
            reason = "CHILD_EXIT"
        elif elapsed > wall_seconds:
            reason = "WALL_LIMIT"
    return {"status": "PASS" if reason is None else "STOPPED", "reason": reason,
            "exit_code": proc.returncode, "wall_seconds": round(elapsed, 6),
            "cpu_seconds": round(cpu, 6), "peak_tree_rss_bytes": peak_rss,
            "child_reaped": True, "process_group_quiesced": True}
