"""Container runtime seam. SessionManager talks to this interface; tests use a fake."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

LABEL = "dbrowser.session"
VIEWER_PORT = 6080
CDP_PORT = 9223


@dataclass
class ContainerSpec:
    name: str
    image: str
    labels: dict[str, str]
    env: dict[str, str]
    network: str
    publish_bind: str
    memory_limit: str
    shm_size: str
    cpus: float
    pids_limit: int
    cap_add: list[str] = field(default_factory=list)
    sysctls: dict[str, str] = field(default_factory=dict)


@dataclass
class ContainerInfo:
    id: str
    name: str
    labels: dict[str, str]
    status: str
    ip: str | None
    host_ports: dict[int, int]


class RuntimeError_(Exception):
    """The container runtime failed (daemon down, image missing, ...)."""


class Runtime(Protocol):
    def run(self, spec: ContainerSpec) -> ContainerInfo: ...
    def list(self) -> list[ContainerInfo]: ...
    def get(self, name: str) -> ContainerInfo | None: ...
    def remove(self, name: str) -> None: ...
    def logs(self, name: str) -> str: ...


# Capabilities the entrypoint needs to set up tmpfs and drop to uid 10001.
BASE_CAPS = ["CHOWN", "SETUID", "SETGID", "KILL", "DAC_OVERRIDE", "FOWNER"]


class DockerRuntime:
    def __init__(self, client=None) -> None:
        import docker

        self._docker = docker
        self._client = client or docker.from_env()

    def _info(self, c) -> ContainerInfo:
        ports: dict[int, int] = {}
        for key, bindings in (c.attrs.get("NetworkSettings", {}).get("Ports") or {}).items():
            if bindings:
                ports[int(key.split("/")[0])] = int(bindings[0]["HostPort"])
        ip = None
        for net in (c.attrs.get("NetworkSettings", {}).get("Networks") or {}).values():
            if net.get("IPAddress"):
                ip = net["IPAddress"]
                break
        return ContainerInfo(c.id, c.name, dict(c.labels), c.status, ip, ports)

    def run(self, spec: ContainerSpec) -> ContainerInfo:
        try:
            c = self._client.containers.run(
                spec.image,
                name=spec.name,
                detach=True,
                auto_remove=True,
                labels=spec.labels,
                environment=spec.env,
                network=spec.network,
                ports={
                    f"{VIEWER_PORT}/tcp": (spec.publish_bind, None),
                    f"{CDP_PORT}/tcp": (spec.publish_bind, None),
                },
                read_only=True,
                tmpfs={"/tmp": "rw,nosuid,nodev,size=2g,mode=1777"},  # noqa: S108 - per-session tmpfs
                shm_size=spec.shm_size,
                mem_limit=spec.memory_limit,
                nano_cpus=int(spec.cpus * 1e9),
                pids_limit=spec.pids_limit,
                cap_drop=["ALL"],
                cap_add=BASE_CAPS + spec.cap_add,
                security_opt=["no-new-privileges"],
                sysctls=spec.sysctls or None,
                init=False,
            )
            c.reload()
            return self._info(c)
        except self._docker.errors.DockerException as e:
            raise RuntimeError_(str(e)) from e

    def list(self) -> list[ContainerInfo]:
        try:
            return [self._info(c) for c in self._client.containers.list(filters={"label": LABEL})]
        except self._docker.errors.DockerException as e:
            raise RuntimeError_(str(e)) from e

    def get(self, name: str) -> ContainerInfo | None:
        try:
            c = self._client.containers.get(name)
        except self._docker.errors.NotFound:
            return None
        if LABEL not in c.labels:
            return None
        return self._info(c)

    def remove(self, name: str) -> None:
        try:
            self._client.containers.get(name).remove(force=True)
        except self._docker.errors.NotFound:
            pass
        except self._docker.errors.APIError as e:
            # auto_remove may already be deleting it.
            if "removal of container" not in str(e) and "is already in progress" not in str(e):
                raise RuntimeError_(str(e)) from e

    def logs(self, name: str) -> str:
        try:
            return self._client.containers.get(name).logs(tail=500).decode("utf-8", "replace")
        except self._docker.errors.NotFound:
            return ""
