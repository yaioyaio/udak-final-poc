#!/usr/bin/env python3
"""Offline checks for the Oracle guest readiness gate."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("oracle_guest", Path(__file__).with_name("check-oracle-guest.py"))
guest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guest)


class GuestProbeTest(unittest.TestCase):
    def setUp(self):
        self.info = f"linux|aarch64|2|2|{6 * guest.GIB}|overlay2|xfs|true|/var/lib/docker"
        self.inventory = ""
        self.quota = "xfs rw,prjquota"
        self.image = f"sha256:{'a' * 64} linux/arm64 0"
        root = guest.ROOT
        self.files = {
            Path("/sys/fs/cgroup/cgroup.controllers"): "cpu memory pids io",
            root / "tools/g2-server-images.json": json.dumps({"images": [{
                "profile": "ORACLE", "image": f"registry.example/oracle@sha256:{'b' * 64}", "platform": "linux/arm64",
            }]}),
            root / "evidence/PHASE5-CONTAINER-RETENTION.json": json.dumps({"profiles": {"ORACLE": {
                "image_id": f"sha256:{'a' * 64}", "mount_count": 0,
            }}}),
        }
        self.enterContext(patch.object(guest.sys, "platform", "linux"))
        self.enterContext(patch.object(guest.os, "uname", return_value=SimpleNamespace(machine="aarch64")))
        self.enterContext(patch.object(guest.os, "sched_getaffinity", create=True, return_value={0, 1}))
        self.read_text = self.enterContext(patch.object(
            guest.Path, "read_text", autospec=True, side_effect=lambda path, **_: self.files[path]))
        self.enterContext(patch.object(guest.Path, "is_dir", return_value=True))
        self.disk_usage = self.enterContext(patch.object(
            guest.shutil, "disk_usage", return_value=SimpleNamespace(free=60 * guest.GIB)))
        self.enterContext(patch.object(guest.host, "available_memory", return_value=5 * guest.GIB))
        self.daemon = self.enterContext(patch.object(guest.host, "local_daemon_running", return_value=True))
        self.docker = self.enterContext(patch.object(guest.host, "docker_fields", side_effect=self.docker_fields))
        self.findmnt = self.enterContext(patch.object(
            guest.subprocess, "run", side_effect=lambda *a, **kw: SimpleNamespace(stdout=self.quota)))

    def docker_fields(self, *args):
        if args[0] == "info":
            return self.info
        if args[0] == "ps":
            return self.inventory
        self.assertEqual(args[:3], ("image", "inspect", "--format"))
        return self.image

    def test_ready_with_only_read_only_docker_calls(self):
        self.assertEqual(guest.probe(), [])
        self.assertEqual([call.args[0] for call in self.docker.call_args_list], ["info", "ps", "image"])
        self.assertEqual(self.findmnt.call_args.args[0], [
            "findmnt", "-n", "-T", "/var/lib/docker", "-o", "FSTYPE,OPTIONS",
        ])

    def test_mac_never_touches_local_docker(self):
        with patch.object(guest.sys, "platform", "darwin"):
            self.assertEqual(guest.probe(), ["GUEST_LINUX_ARM64"])
        self.daemon.assert_not_called()
        self.docker.assert_not_called()

    def test_stopped_daemon_is_not_activated(self):
        self.daemon.return_value = False
        self.assertEqual(guest.probe(), ["LOCAL_DOCKER_DAEMON"])
        self.docker.assert_not_called()

    def test_low_memory_and_separate_disk_capacities(self):
        self.info = self.info.replace(str(6 * guest.GIB), str(4 * guest.GIB - 1))
        self.disk_usage.side_effect = [SimpleNamespace(free=39 * guest.GIB), SimpleNamespace(free=2 * guest.GIB)]
        with patch.object(guest.host, "available_memory", return_value=3 * guest.GIB):
            self.assertEqual(guest.probe(), [
                "GUEST_CAPACITY", "WORKSPACE_DISK_40_GIB", "DOCKER_CAPACITY", "DOCKER_DATA_FREE_3_GIB",
            ])

    def test_wrong_engine_platform_and_overlayfs(self):
        self.info = self.info.replace("aarch64|2", "x86_64|1").replace("overlay2|xfs|true", "overlayfs||")
        self.assertEqual(guest.probe(), ["DOCKER_LINUX_ARM64_CGROUP_V2", "DOCKER_OVERLAY2_XFS_DTYPE"])

    def test_requires_empty_inventory_and_exact_local_image(self):
        self.inventory = "exited"
        for image in ("", self.image[:-1] + "1", self.image.replace("arm64", "amd64"),
                      self.image.replace("a" * 64, "c" * 64)):
            with self.subTest(image=image):
                self.image = image
                self.assertEqual(guest.probe(), ["DEDICATED_DOCKER_EMPTY", "PINNED_LOCAL_ORACLE_IMAGE"])

    def test_redirected_receipt_is_rejected_before_reading(self):
        pin = guest.ROOT / "tools/g2-server-images.json"
        resolve = guest.Path.resolve
        with patch.object(guest.Path, "resolve", autospec=True,
                          side_effect=lambda path, **kwargs: pin.with_name("unapproved") if path == pin
                          else resolve(path, **kwargs)):
            self.assertEqual(guest.probe(), ["PINNED_LOCAL_ORACLE_IMAGE"])
        self.assertEqual([call.args[0] for call in self.read_text.call_args_list],
                         [Path("/sys/fs/cgroup/cgroup.controllers")])

    def test_requires_writable_enforced_xfs_project_quota(self):
        for options in ("xfs ro,prjquota", "xfs rw,pqnoenforce", "xfs rw,pquota,pqnoenforce",
                        "xfs rw,usrquota", "ext4 rw,prjquota"):
            with self.subTest(options=options):
                self.quota = options
                self.assertEqual(guest.probe(), ["XFS_PROJECT_QUOTA_MOUNT"])
        self.quota = "xfs rw,pquota"
        self.assertEqual(guest.probe(), [])

    def test_missing_daemon_info_fails_closed(self):
        for response in ("invalid", subprocess.TimeoutExpired("docker", 6)):
            with self.subTest(response=response):
                if isinstance(response, Exception):
                    self.docker.side_effect = response
                else:
                    self.info = response
                self.assertEqual(guest.probe(), ["LOCAL_DOCKER_INFO"])


if __name__ == "__main__":
    unittest.main()
