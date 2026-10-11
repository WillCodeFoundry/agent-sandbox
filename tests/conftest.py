import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NoReturn

import pytest

from agent_sandbox.config import Config
from agent_sandbox.host import Host, HostPort

Response = str | int


class ExecCalled(Exception):
    """Raised by FakeHost.exec instead of replacing the process, carrying what would have run."""

    def __init__(self, cmd: tuple[str, ...], env: Mapping[str, str]) -> None:
        self.cmd = cmd
        self.env = env


class FakeHost(Host):
    """Answers commands from ``responses`` and records them in ``calls``.

    A response is stdout (str, exit 0), an exit code (int), or a list of
    those, used in turn. An unexpected command raises KeyError.

    Only ``run``/``exec``/``environ`` are faked. Everything else (filesystem
    safety checks, path naming) is inherited from the real ``Host``
    unchanged: there's nothing worth faking about them, and tests assert on
    the real directory/file state they leave behind.
    """

    def __init__(self) -> None:
        super().__init__(os.getuid())
        self.responses: dict[tuple[str, ...], Response | list[Response]] = {}
        self.calls: list[tuple[tuple[str, ...], Mapping[str, str] | None]] = []
        self.environ_value: Mapping[str, str] = {}

    def run(self, cmd: Sequence[str], *, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        command = tuple(cmd)
        self.calls.append((command, env))
        response = self.responses[command]
        if isinstance(response, list):
            response = response.pop(0)
        if isinstance(response, int):
            return subprocess.CompletedProcess(command, response, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout=response, stderr="")

    def exec(self, cmd: Sequence[str], env: Mapping[str, str]) -> NoReturn:
        raise ExecCalled(tuple(cmd), env)

    def environ(self) -> Mapping[str, str]:
        return self.environ_value

    @property
    def commands(self) -> list[tuple[str, ...]]:
        return [command for command, _ in self.calls]


@pytest.fixture
def host() -> FakeHost:
    host = FakeHost()
    _: HostPort = host  # type check: FakeHost must satisfy the HostPort protocol
    return host


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(agent="claude", sockets_dir=tmp_path / "sockets")
