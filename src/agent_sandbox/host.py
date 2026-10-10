"""The boundary to the host machine: every external command goes through here."""

import subprocess
from collections.abc import Mapping, Sequence
from typing import Protocol

from agent_sandbox.errors import SandboxError


class Host(Protocol):
    def run(self, cmd: Sequence[str], *, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        """Run a command to completion, capturing its output (like subprocess.run)."""
        ...


class SubprocessHost:
    def run(self, cmd: Sequence[str], *, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                list(cmd),
                env=None if env is None else dict(env),
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            raise SandboxError(f"{cmd[0]} not found in PATH") from None
