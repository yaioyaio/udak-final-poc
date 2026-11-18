"""Docker Engine transport for dedicated G2 containers and disposable probes."""

from contextlib import contextmanager
import http.client
import json
import re
import socket
import threading
import time
from urllib.parse import urlencode


_API = "/v1.47"
_MAX_RESPONSE = 1024 * 1024
_MAX_DOWNLOAD = 2 * 1024**3
_MANAGED = "dev.udak.g2.managed"
_RUN = "dev.udak.g2.run"
_PROFILE = "dev.udak.g2.profile"
_PROFILES = {"POSTGRESQL", "MYSQL", "SQLSERVER", "ORACLE", "PROBE"}
_STATES = {"created", "running", "paused", "restarting", "removing", "exited", "dead"}
_ID = re.compile(r"[0-9a-f]{64}")
_RUN_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}")
# Name-only pulls would request every registry tag.
_IMAGE = re.compile(r"[a-z0-9][a-z0-9._/-]*(?::[a-zA-Z0-9_][a-zA-Z0-9_.-]*(?:@sha256:[a-f0-9]{64})?"
                    r"|@sha256:[a-f0-9]{64})")
_PLATFORM = re.compile(r"linux/(?:amd64|arm64)(?:/v[0-9]+)?")
_ENV_KEY = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


class DockerError(RuntimeError):
    """An operation failed; messages contain only fixed error codes."""


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path, timeout):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path
        self.transport = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    def connect(self):
        self.sock = self.transport
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)

    def interrupt(self):
        # HTTPConnection can release its socket while HTTPResponse still holds a reader.
        try:
            self.transport.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def _matches(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def _decode(data):
    try:
        return json.loads(data)
    except (ValueError, RecursionError):
        pass
    raise DockerError("DOCKER_RESPONSE_INVALID")


class Engine:
    def __init__(self, socket_path="/var/run/docker.sock"):
        self.socket_path = socket_path
        self._created = {}

    @contextmanager
    def _request(self, method, route, accepted, body=None, wall_seconds=15):
        connection = response = timer = None
        deadline = time.monotonic() + wall_seconds
        failure = "DOCKER_TRANSPORT_FAILED"
        try:
            connection = _UnixHTTPConnection(self.socket_path, min(45, wall_seconds))
            timer = threading.Timer(wall_seconds, connection.interrupt)
            timer.daemon = True
            timer.start()
            headers = {"Content-Type": "application/json"} if body is not None else {}
            connection.request(method, _API + route, body=body, headers=headers)
            response = connection.getresponse()
            if response.status not in accepted:
                raise DockerError("DOCKER_HTTP_REJECTED")
            yield response
            if time.monotonic() >= deadline:
                raise DockerError("DOCKER_TIMEOUT")
            return
        except InterruptedError:
            raise
        except TimeoutError:
            failure = "DOCKER_TIMEOUT"
        except (OSError, http.client.HTTPException):
            if time.monotonic() >= deadline:
                failure = "DOCKER_TIMEOUT"
        except DockerError:
            if time.monotonic() < deadline:
                raise
            failure = "DOCKER_TIMEOUT"
        finally:
            if timer is not None:
                timer.cancel()
            if response is not None:
                response.close()
            if connection is not None:
                connection.close()
                connection.transport.close()
        raise DockerError(failure)

    def _json(self, method, route, accepted, body=None):
        with self._request(method, route, accepted, body=body) as response:
            data = response.read(_MAX_RESPONSE + 1)
            if len(data) > _MAX_RESPONSE:
                raise DockerError("DOCKER_RESPONSE_LIMIT")
            if response.length not in (None, 0):
                raise DockerError("DOCKER_RESPONSE_INVALID")
            return _decode(data)

    def pull(self, image, platform, wall_seconds=180, max_download_bytes=_MAX_DOWNLOAD):
        if (not _matches(_IMAGE, image) or not _matches(_PLATFORM, platform)
                or not _integer(wall_seconds, 1, 180)
                or not _integer(max_download_bytes, 1, _MAX_DOWNLOAD)):
            raise DockerError("DOCKER_PULL_INPUT_INVALID")
        route = "/images/create?" + urlencode({"fromImage": image, "platform": platform})
        layer_sizes = {}
        total = response_bytes = 0
        complete = False
        with self._request("POST", route, (200,), wall_seconds=wall_seconds) as response:
            while True:
                line = response.readline(_MAX_RESPONSE - response_bytes + 1)
                if not line:
                    break
                response_bytes += len(line)
                if response_bytes > _MAX_RESPONSE:
                    raise DockerError("DOCKER_RESPONSE_LIMIT")
                event = _decode(line)
                if not isinstance(event, dict) or "error" in event or "errorDetail" in event:
                    raise DockerError("DOCKER_PULL_FAILED")
                status = event.get("status")
                if status == "Downloading":
                    layer = event.get("id")
                    detail = event.get("progressDetail")
                    if not isinstance(layer, str) or not layer or not isinstance(detail, dict):
                        raise DockerError("DOCKER_PULL_PROGRESS_INVALID")
                    current, size = detail.get("current", 0), detail.get("total", 0)
                    if not all(type(value) is int and value >= 0 for value in (current, size)):
                        raise DockerError("DOCKER_PULL_PROGRESS_INVALID")
                    previous = layer_sizes.get(layer, 0)
                    layer_sizes[layer] = max(previous, current, size)
                    total += layer_sizes[layer] - previous
                    if total > max_download_bytes:
                        raise DockerError("DOCKER_PULL_DOWNLOAD_LIMIT")
                if isinstance(status, str) and status.startswith(("Status: Downloaded newer image for ",
                                                                  "Status: Image is up to date for ")):
                    complete = True
            if not complete or response.length not in (None, 0):
                raise DockerError("DOCKER_PULL_UNCONFIRMED")
        return {"status": "pulled", "download_bytes_reported": total, "layers_reported": len(layer_sizes)}

    def create(self, image, platform, env, internal_port, memory_bytes, nano_cpus, run_id, profile,
               *, command=None):
        if (not _matches(_IMAGE, image) or not _matches(_PLATFORM, platform)
                or not _matches(_RUN_ID, run_id) or not isinstance(profile, str) or profile not in _PROFILES
                or not _integer(internal_port, 1, 65535)
                or not _integer(memory_bytes, 1, 2**63 - 1) or not _integer(nano_cpus, 1, 2**63 - 1)
                or not isinstance(env, dict)
                or not all(_matches(_ENV_KEY, key) and isinstance(value, str) and "\0" not in value
                           for key, value in env.items())
                or (command is not None and (profile != "PROBE" or command != ["sleep", "60"]))):
            raise DockerError("DOCKER_CREATE_INPUT_INVALID")
        shm_mib, pids_limit = {"ORACLE": (1024, 512), "SQLSERVER": (256, 512)}.get(profile, (64, 256))
        shm_bytes = shm_mib * 1024**2
        if shm_bytes > memory_bytes:
            raise DockerError("DOCKER_CREATE_INPUT_INVALID")
        port = f"{internal_port}/tcp"
        route = "/containers/create?" + urlencode({"name": f"udak-g2-{run_id}-{profile.lower()}",
                                                   "platform": platform})
        config = {
            "Image": image,
            # Docker stores Env in daemon metadata. It is never read back by this client.
            "Env": [f"{key}={value}" for key, value in env.items()],
            "Labels": {_MANAGED: "true", _RUN: run_id, _PROFILE: profile},
            "ExposedPorts": {port: {}},
            "HostConfig": {
                "NetworkMode": "bridge", "PortBindings": {port: [{"HostIp": "127.0.0.1", "HostPort": "0"}]},
                "RestartPolicy": {"Name": "no"}, "Memory": memory_bytes, "MemorySwap": memory_bytes,
                "NanoCpus": nano_cpus, "PidsLimit": pids_limit, "ShmSize": shm_bytes,
                "LogConfig": {"Type": "none"},
                "AutoRemove": False, "Privileged": False,
            },
        }
        if command is not None:
            config["Cmd"] = ["sleep", "60"]
        body = json.dumps(config).encode("ascii")
        if len(body) > _MAX_RESPONSE:
            raise DockerError("DOCKER_CREATE_INPUT_INVALID")
        result = self._json("POST", route, (201,), body=body)
        if not isinstance(result, dict) or not _matches(_ID, result.get("Id")):
            raise DockerError("DOCKER_CREATE_UNCONFIRMED")
        container_id = result["Id"]
        # The daemon can accept a create while warning that it ignored a resource limit.
        warnings = result.get("Warnings")
        self._created[container_id] = (run_id, internal_port, warnings is None or warnings == [])
        return container_id

    def _owned(self, container_id, run_id):
        if not _matches(_ID, container_id) or not _matches(_RUN_ID, run_id):
            raise DockerError("DOCKER_IDENTITY_INVALID")
        filters = {"id": [container_id], "label": [f"{_RUN}={run_id}", f"{_MANAGED}=true"]}
        route = "/containers/json?" + urlencode({"all": 1, "filters": json.dumps(filters)})
        matches = self._json("GET", route, (200,))
        if matches == []:
            return None
        if not isinstance(matches, list) or len(matches) != 1 or not isinstance(matches[0], dict):
            raise DockerError("DOCKER_OWNERSHIP_UNCONFIRMED")
        container = matches[0]
        labels = container.get("Labels")
        if (container.get("Id") != container_id or not isinstance(labels, dict)
                or labels.get(_RUN) != run_id or labels.get(_MANAGED) != "true"):
            raise DockerError("DOCKER_OWNERSHIP_UNCONFIRMED")
        state = container.get("State")
        if not isinstance(state, str) or state not in _STATES:
            raise DockerError("DOCKER_STATE_UNCONFIRMED")
        return {"State": state, "Status": container.get("Status"), "Ports": container.get("Ports"),
                "Profile": labels.get(_PROFILE)}

    def start(self, container_id):
        if not _matches(_ID, container_id) or container_id not in self._created:
            raise DockerError("DOCKER_OWNERSHIP_UNCONFIRMED")
        run_id, _, limits_confirmed = self._created[container_id]
        if not limits_confirmed:
            raise DockerError("DOCKER_CREATE_WARNING")
        container = self._owned(container_id, run_id)
        if container is None or container["State"] != "created":
            raise DockerError("DOCKER_START_STATE_INVALID")
        with self._request("POST", f"/containers/{container_id}/start", (204,)):
            pass

    def endpoint(self, container_id, run_id):
        container = self._owned(container_id, run_id)
        if container is None or container["State"] != "running":
            return None
        ports = container.get("Ports")
        if not isinstance(ports, list) or not all(isinstance(port, dict) for port in ports):
            raise DockerError("DOCKER_ENDPOINT_UNCONFIRMED")
        published = [port for port in ports if port.get("PublicPort", 0) != 0]
        if not published:
            return None
        port = published[0]
        created = self._created.get(container_id)
        expected = created[1] if created is not None else port.get("PrivatePort")
        if (len(published) != 1 or port.get("IP") != "127.0.0.1" or port.get("Type") != "tcp"
                or not _integer(port.get("PrivatePort"), 1, 65535) or port["PrivatePort"] != expected
                or not _integer(port.get("PublicPort"), 1, 65535)):
            raise DockerError("DOCKER_ENDPOINT_UNCONFIRMED")
        return port["PublicPort"]

    def state(self, container_id, run_id):
        container = self._owned(container_id, run_id)
        if container is None:
            return {"state": "missing", "status": "missing"}
        state = status = container["State"]
        summary = container.get("Status")
        if state == "running" and isinstance(summary, str):
            for health in ("healthy", "unhealthy", "health: starting"):
                if summary.endswith(f"({health})"):
                    status = "starting" if health == "health: starting" else health
                    break
        return {"state": state, "status": status}

    def stop(self, container_id, run_id, timeout=10):
        if not _integer(timeout, 1, 60):
            raise DockerError("DOCKER_STOP_INPUT_INVALID")
        before = self._owned(container_id, run_id)
        if before is None:
            raise DockerError("DOCKER_OWNERSHIP_UNCONFIRMED")
        stopped_states = ("created", "exited")
        if before["State"] not in stopped_states:
            route = f"/containers/{container_id}/stop?" + urlencode({"t": timeout})
            with self._request("POST", route, (204, 304), wall_seconds=timeout + 5):
                pass
        state = self.state(container_id, run_id)["state"]
        if state not in stopped_states:
            raise DockerError("DOCKER_STOP_UNCONFIRMED")
        return {"status": "stopped", "state": state}

    def remove_probe_only(self, container_id, run_id):
        container = self._owned(container_id, run_id)
        if (container is None or container["Profile"] != "PROBE"
                or container["State"] not in ("created", "exited")):
            raise DockerError("DOCKER_PROBE_REMOVAL_REJECTED")
        route = f"/containers/{container_id}?force=false&v=false"
        with self._request("DELETE", route, (204,)):
            pass
        if self._owned(container_id, run_id) is not None:
            raise DockerError("DOCKER_PROBE_REMOVAL_UNCONFIRMED")
        self._created.pop(container_id, None)
        return {"status": "removed"}
