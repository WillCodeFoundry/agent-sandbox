"""The boundary to the host machine: every external command and filesystem privilege check goes through here."""

import os
import stat
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NoReturn, Protocol

from agent_sandbox.errors import SandboxError


class HostPort(Protocol):
    def run(self, cmd: Sequence[str], *, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        """Run a command to completion, capturing its output (like subprocess.run)."""
        ...

    def exec(self, cmd: Sequence[str], env: Mapping[str, str]) -> NoReturn:
        """Replace the current process with cmd (like os.execvpe)."""
        ...

    def environ(self) -> Mapping[str, str]:
        """This process's own environment."""
        ...

    def ensure_private_dir(self, path: Path) -> None:
        """Create path as a directory only this user can use; raise if it isn't one."""
        ...

    def reset_socket(self, path: Path) -> None:
        """Make path ready for a fresh ssh-agent: private parent dir, no leftover socket file."""
        ...

    def socket_path(self, sockets_dir: Path, name: str) -> Path:
        """The ssh-agent socket for sandbox ``name``, under a directory private to this user."""
        ...

    def ensure_dir_exists(self, path: Path, what: str) -> None:
        """Raise if path is not a directory."""
        ...

    def ensure_file_exists(self, path: Path, what: str) -> None:
        """Raise if path is not a file."""
        ...

    def public_key_path(self, ssh_key: Path) -> Path:
        """Where ssh-keygen puts the public half of a private key, by naming convention."""
        ...


class Host:
    def __init__(self, uid: int) -> None:
        self._uid = uid

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

    def exec(self, cmd: Sequence[str], env: Mapping[str, str]) -> NoReturn:
        os.execvpe(cmd[0], list(cmd), dict(env))

    def environ(self) -> Mapping[str, str]:
        return os.environ

    def ensure_private_dir(self, path: Path) -> None:
        """Create path as a directory only this user can use, refusing one we don't own.

        The sockets directory lives in /tmp, which is shared: another user could
        create it first, or put a symlink there pointing somewhere they control.
        """
        try:
            path.mkdir(mode=0o700, exist_ok=True)
            info = os.lstat(path)
            ours = stat.S_ISDIR(info.st_mode) and info.st_uid == self._uid
        except FileExistsError:  # a file, or a dangling symlink
            ours = False
        if not ours:
            raise SandboxError(f"{path} is not a directory owned by you")
        path.chmod(0o700)

    def reset_socket(self, path: Path) -> None:
        self.ensure_private_dir(path.parent)
        path.unlink(missing_ok=True)

    def socket_path(self, sockets_dir: Path, name: str) -> Path:
        return sockets_dir.with_name(f"{sockets_dir.name}-{self._uid}") / f"{name}.sock"

    def ensure_dir_exists(self, path: Path, what: str) -> None:
        if not path.is_dir():
            raise SandboxError(f"{what} {str(path)!r} is not a directory")

    def ensure_file_exists(self, path: Path, what: str) -> None:
        if not path.is_file():
            raise SandboxError(f"{what} {str(path)!r} is not a file")

    def public_key_path(self, ssh_key: Path) -> Path:
        return ssh_key.with_name(ssh_key.name + ".pub")
