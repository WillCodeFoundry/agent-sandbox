import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from agent_sandbox.config import Config
from agent_sandbox.host import CommandToExecute, Host

Response = str | int


class FakeHost:
    """Answers commands from ``responses`` and records them in ``calls``.

    A response is stdout (str, exit 0), an exit code (int), or a list of
    those, used in turn. An unexpected command raises KeyError.
    """

    def __init__(self) -> None:
        self.responses: dict[tuple[str, ...], Response | list[Response]] = {}
        self.calls: list[tuple[tuple[str, ...], Mapping[str, str] | None]] = []

    def run(self, cmd: CommandToExecute) -> subprocess.CompletedProcess[str]:
        self.calls.append((cmd.command, cmd.env))
        response = self.responses[cmd.command]
        if isinstance(response, list):
            response = response.pop(0)
        if isinstance(response, int):
            return subprocess.CompletedProcess(cmd.command, response, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd.command, 0, stdout=response, stderr="")

    @property
    def commands(self) -> list[tuple[str, ...]]:
        return [command for command, _ in self.calls]


@pytest.fixture
def host() -> FakeHost:
    host = FakeHost()
    _: Host = host  # type check: FakeHost must satisfy the Host protocol
    return host


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(agent="claude", sockets_dir=tmp_path / "sockets", uid=os.getuid())
