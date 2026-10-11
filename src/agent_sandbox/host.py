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

    def ensure_private_dir(self, path: Path, uid: int) -> None:
        """Create path as a directory only uid can use; raise if it isn't one."""
        ...

    def remove_file(self, path: Path) -> None:
        """Delete path if it exists."""
        ...

    def socket_path(self, sockets_dir: Path, name: str, uid: int) -> Path:
        """The ssh-agent socket for sandbox ``name``, under a directory private to ``uid``."""
        ...

    def public_key_path(self, ssh_key: Path) -> Path:
        """Where ssh-keygen puts the public half of a private key, by naming convention."""
        ...

    def ensure_dir_exists(self, path: Path, what: str) -> None:
        """Raise if path is not a directory."""
        ...

    def ensure_file_exists(self, path: Path, what: str) -> None:
        """Raise if path is not a file."""
        ...

    def contains(self, folder: Path, path: Path) -> bool:
        """Whether path is folder itself or somewhere inside it."""
        ...

    def is_nested_dir(self, a: Path, b: Path) -> bool:
        """Whether a and b are the same path, or one is nested inside the other."""
        ...


class Host:
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

    def ensure_private_dir(self, path: Path, uid: int) -> None:
        """Create path as a directory only uid can use, refusing one we don't own.

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

    def remove_file(self, path: Path) -> None:
        path.unlink(missing_ok=True)

    def socket_path(self, sockets_dir: Path, name: str, uid: int) -> Path:
        return sockets_dir.with_name(f"{sockets_dir.name}-{uid}") / f"{name}.sock"

    def public_key_path(self, ssh_key: Path) -> Path:
        return ssh_key.with_name(ssh_key.name + ".pub")

    def ensure_dir_exists(self, path: Path, what: str) -> None:
        if not path.is_dir():
            raise SandboxError(f"{what} {str(path)!r} is not a directory")

    def ensure_file_exists(self, path: Path, what: str) -> None:
        if not path.is_file():
            raise SandboxError(f"{what} {str(path)!r} is not a file")

    def contains(self, folder: Path, path: Path) -> bool:
        return path.is_relative_to(folder)

    def is_nested_dir(self, a: Path, b: Path) -> bool:
        return self.contains(a, b) or self.contains(b, a)
