"""A dedicated ssh-agent per sandbox, reachable at a fixed socket path."""

import os
import stat
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from agent_sandbox.errors import SandboxError
from agent_sandbox.host import Host

# ssh-add -l exit codes
_HAS_KEYS = 0
_NO_KEYS = 1


class SshAgent:
    """An ssh-agent bound to ``socket``, reused across launches of one sandbox.

    ``environ`` is the caller's environment; the agent's own environment is
    derived from it with the personal agent replaced by this one.
    """

    def __init__(self, host: Host, socket: Path, environ: Mapping[str, str], uid: int) -> None:
        self._host = host
        self._uid = uid
        self.socket = socket
        self.env = {key: value for key, value in environ.items() if key != "SSH_AGENT_PID"}
        self.env["SSH_AUTH_SOCK"] = str(socket)

    def ensure_running(self) -> None:
        """Start the agent unless one already answers on the socket."""
        # Check the directory before talking to anything in it: a socket in a
        # directory someone else controls could be their agent, not ours.
        ensure_private_dir(self.socket.parent, self._uid)
        if self._is_running():
            return

        self.socket.unlink(missing_ok=True)  # stale socket from a dead agent
        # The env script ssh-agent prints is ignored on purpose: nothing in
        # this process should start using the sandbox's agent by accident.
        result = self._host.run(["ssh-agent", "-a", str(self.socket), "-s"])
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
        return self._host.run(["ssh-add", *args], env=self.env)


def ensure_private_dir(path: Path, uid: int) -> None:
    """Create ``path`` as a directory only ``uid`` can use, refusing one we don't own.

    The sockets directory lives in /tmp, which is shared: another user could
    create it first, or put a symlink there pointing somewhere they control.
    """
    try:
        path.mkdir(mode=0o700, exist_ok=True)
        info = os.lstat(path)
        ours = stat.S_ISDIR(info.st_mode) and info.st_uid == uid
    except FileExistsError:  # a file, or a dangling symlink
        ours = False
    if not ours:
        raise SandboxError(f"{path} is not a directory owned by you")
    path.chmod(0o700)
