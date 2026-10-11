"""A dedicated ssh-agent per sandbox, reachable at a fixed socket path."""

import subprocess
from collections.abc import Sequence
from pathlib import Path

from agent_sandbox.errors import SandboxError
from agent_sandbox.host import HostPort

# ssh-add -l exit codes
_HAS_KEYS = 0
_NO_KEYS = 1


class SshAgent:
    """An ssh-agent bound to ``socket``, reused across launches of one sandbox."""

    def __init__(self, host: HostPort, socket: Path) -> None:
        self._host = host
        self.socket = socket

    def ensure_running(self) -> None:
        """Start the agent unless one already answers on the socket.

        The caller must have already made ``socket``'s directory private to
        this user - a socket in a directory someone else controls could be
        their agent, not ours.
        """
        if self._is_running():
            return

        self._host.reset_socket(self.socket)  # stale socket from a dead agent
        # The env script ssh-agent prints is ignored on purpose: nothing in
        # this process should start using the sandbox's agent by accident.
        result = self._host.run(("ssh-agent", "-a", str(self.socket), "-s"))
        if result.returncode != 0 or not self._is_running():
            raise SandboxError(f"ssh-agent failed to start on {self.socket}")

    def replace_keys(self, keys: Sequence[Path]) -> None:
        """Make ``keys`` the only keys the agent holds.

        The agent belongs to one sandbox, so emptying it first is safe, and it
        stops keys from earlier launches (such as a rotated-out key) lingering.
        """
        result = self._ssh_add("-D")
        if result.returncode != 0:
            raise SandboxError(f"ssh-add could not empty the agent: {result.stderr.strip()}")
        for key in keys:
            result = self._ssh_add("-q", str(key))
            if result.returncode != 0:
                raise SandboxError(f"ssh-add failed for {key}: {result.stderr.strip()}")

    def list_keys(self) -> list[str]:
        result = self._ssh_add("-l")
        return result.stdout.splitlines() if result.returncode == _HAS_KEYS else []

    def _is_running(self) -> bool:
        return self._ssh_add("-l").returncode in (_HAS_KEYS, _NO_KEYS)

    def _ssh_add(self, *args: str) -> subprocess.CompletedProcess[str]:
        # ssh-add only needs to find itself and reach the right agent - nothing else.
        environ = self._host.environ()
        env = {"SSH_AUTH_SOCK": str(self.socket)}
        if "PATH" in environ:
            env["PATH"] = environ["PATH"]
        return self._host.run(("ssh-add", *args), env=env)
