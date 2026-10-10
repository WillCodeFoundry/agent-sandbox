"""Docker Sandboxes (sbx)."""

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from agent_sandbox.errors import SandboxError
from agent_sandbox.host import Host

# ssh-add -l exit codes, as seen inside the sandbox
_HAS_KEYS = 0
_NO_KEYS = 1
_NO_AGENT = 2


class Sbx:
    """sbx commands for one sandbox.

    Every call carries ``env``, the sandbox's own environment: sbx points a
    sandbox's forwarded agent at the SSH_AUTH_SOCK of each call aimed at it,
    so no call may carry another socket.
    """

    def __init__(self, host: Host, env: Mapping[str, str]) -> None:
        self._host = host
        self._env = env

    def exists(self, name: str) -> bool:
        return self._sbx("exec", name, "true").returncode == 0

    def create(self, name: str, agent: str, workspace: Path, context: Path) -> None:
        result = self._sbx("create", "--name", name, agent, f"{workspace}", f"{context}:ro")
        if result.returncode != 0:
            raise SandboxError(f"sbx create failed: {result.stderr.strip()}")

    def set_github_token(self, name: str, token: str) -> None:
        result = self._sbx("secret", "set", "github", "--sandbox", name, "-t", token)
        if result.returncode != 0:
            raise SandboxError(f"sbx secret set failed: {result.stderr.strip()}")

    def clear_github_token(self, name: str) -> None:
        result = self._sbx("secret", "rm", "github", "--sandbox", name, "-f")
        if result.returncode != 0:
            raise SandboxError(f"sbx secret rm failed: {result.stderr.strip()}")

    def agent_fingerprints(self, name: str) -> set[str] | None:
        """Fingerprints of the keys the sandbox's agent offers, or None if no agent reaches it."""
        result = self._sbx("exec", name, "ssh-add", "-l")
        if result.returncode == _HAS_KEYS:
            return fingerprints(result.stdout.splitlines())
        if result.returncode == _NO_KEYS:
            return set()
        if result.returncode == _NO_AGENT:
            return None
        raise SandboxError(f"could not list the sandbox's keys: {result.stderr.strip()}")

    def _sbx(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self._host.run(["sbx", *args], env=self._env)


def fingerprints(ssh_add_lines: Sequence[str]) -> set[str]:
    """Fingerprints from ``ssh-add -l`` lines: ``<bits> <fingerprint> <comment> (<type>)``."""
    return {line.split()[1] for line in ssh_add_lines if line.strip()}


def sbx_run_args(name: str, agent_args: Sequence[str]) -> tuple[str, ...]:
    """``sbx run`` for an existing sandbox.

    The sandbox is always created first, and sbx refuses workspace paths when
    attaching to an existing sandbox: its mounts are fixed at creation.
    """
    args = ("sbx", "run", "--name", name)
    return (*args, "--", *agent_args) if agent_args else args
