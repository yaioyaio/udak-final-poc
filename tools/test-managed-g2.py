#!/usr/bin/env python3
"""Regressions for managed Docker ownership, private input and durable intent."""
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("managed_g2", Path(__file__).with_name("run-managed-g2.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ID = "a" * 64
RUN = "b" * 32
IMAGE = "test/image@sha256:" + "c" * 64


class FakeEngine(m.docker.Engine):
    def __init__(self):
        super().__init__()
        self.requests = []
        self.rows = [{"Id": ID, "Labels": {"dev.udak.g2.managed": "true", "dev.udak.g2.run": RUN,
                                              "dev.udak.g2.profile": "POSTGRESQL"},
                      "State": "exited", "Ports": []}]

    def _json(self, method, route, accepted, body=None):
        self.requests.append((method, route, body))
        if method == "POST" and route.startswith("/containers/create?"):
            return {"Id": ID, "Warnings": []}
        if method == "GET" and route.startswith("/containers/json?"):
            return self.rows
        raise AssertionError("Unexpected Docker route")

    @contextmanager
    def _request(self, method, route, accepted, body=None, wall_seconds=15):
        self.requests.append((method, route, body))
        if method == "DELETE":
            self.rows = []
        yield None


class ManagedSafetyTest(unittest.TestCase):
    def test_creation_bounds_and_no_public_secret_result(self):
        for profile, pids, shm in [("POSTGRESQL", 256, 64), ("MYSQL", 256, 64),
                                   ("SQLSERVER", 512, 256), ("ORACLE", 512, 1024)]:
            engine = FakeEngine()
            result = engine.create(IMAGE, "linux/arm64", {"TEST_INPUT": "SYNTHETIC_PRIVATE_SENTINEL"},
                                   1521, 4 * 1024**3, 2 * 10**9, RUN, profile)
            self.assertEqual(result, ID)
            config = json.loads(engine.requests[0][2])
            host = config["HostConfig"]
            self.assertEqual(host["PortBindings"]["1521/tcp"][0]["HostIp"], "127.0.0.1")
            self.assertEqual(host["PidsLimit"], pids)
            self.assertEqual(host["ShmSize"], shm * 1024**2)
            self.assertEqual(host["RestartPolicy"]["Name"], "no")
            self.assertEqual(host["LogConfig"]["Type"], "none")
            self.assertEqual(host["Memory"], host["MemorySwap"])
            self.assertNotIn("Cmd", config)
            self.assertNotIn("SYNTHETIC_PRIVATE_SENTINEL", result)

    def test_foreign_owner_cannot_stop(self):
        engine = FakeEngine()
        engine.rows[0]["Labels"]["dev.udak.g2.run"] = "d" * 32
        with self.assertRaises(m.docker.DockerError):
            engine.stop(ID, RUN)
        self.assertEqual([request[0] for request in engine.requests], ["GET"])

    def test_database_container_cannot_be_deleted(self):
        engine = FakeEngine()
        with self.assertRaises(m.docker.DockerError):
            engine.remove_probe_only(ID, RUN)
        self.assertTrue(all(request[0] != "DELETE" for request in engine.requests))

    def test_only_exited_owned_probe_can_be_removed_without_volumes(self):
        engine = FakeEngine()
        engine.rows[0]["Labels"]["dev.udak.g2.profile"] = "PROBE"
        self.assertEqual(engine.remove_probe_only(ID, RUN)["status"], "removed")
        route = next(route for method, route, body in engine.requests if method == "DELETE")
        self.assertIn("force=false&v=false", route)

    def test_endpoint_rejects_non_loopback_publication(self):
        engine = FakeEngine()
        engine.rows[0].update(State="running", Ports=[{"IP": "0.0.0.0", "Type": "tcp", "PrivatePort": 5432, "PublicPort": 15432}])
        with self.assertRaises(m.docker.DockerError):
            engine.endpoint(ID, RUN)

    def test_failed_atomic_replace_preserves_original_intent(self):
        with m.guard.workspace("udak-intent-test-") as (work, cleanup):
            path = work / "intent.json"
            m.save(path, {"state": "CREATE_INTENT"})
            with patch.object(m.os, "replace", side_effect=OSError()):
                with self.assertRaises(OSError):
                    m.save(path, {"state": "STOPPED"})
            self.assertEqual(json.loads(path.read_text()), {"state": "CREATE_INTENT"})

    def test_private_pipe_is_not_copied_to_output_or_result(self):
        value = b"SYNTHETIC_PRIVATE_SENTINEL"
        with m.guard.workspace("udak-private-input-test-") as (work, cleanup):
            result = m.guard.run_step("private-input", [sys.executable, "-c",
                        "import sys; print('PRIVATE_BYTES='+str(len(sys.stdin.buffer.read())))"],
                        work, private_input=value)
            self.assertEqual((work / "private-input.output").read_text().strip(), "PRIVATE_BYTES=26")
            self.assertNotIn(value.decode(), json.dumps(result))


if __name__ == "__main__":
    unittest.main()
