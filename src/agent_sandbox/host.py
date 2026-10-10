"""The boundary to the host machine: every external command goes through here."""

import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from agent_sandbox.errors import SandboxError


@dataclass(frozen=True)
class CommandToExecute:
    """A command to run on the host, plus a message describing it worth logging first."""

    command: tuple[str, ...]
    env: Mapping[str, str] | None = None
    message: str = ""


class Host(Protocol):
    def run(self, cmd: CommandToExecute) -> subprocess.CompletedProcess[str]:
        """Run a command to completion, capturing its output (like subprocess.run)."""
        ...


class SubprocessHost:
    def run(self, cmd: CommandToExecute) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                list(cmd.command),
                env=None if cmd.env is None else dict(cmd.env),
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            raise SandboxError(f"{cmd.command[0]} not found in PATH") from None
