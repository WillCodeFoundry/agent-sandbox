"""Docker Sandboxes (sbx)."""

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from agent_sandbox.errors import SandboxError
from agent_sandbox.host import HostPort
from agent_sandbox.ssh_agent import SshAddExitCode, SshAgent

# GitHub's own published host keys (one entry per key type), not fetched from the
# sandbox itself: ssh-keyscan trusts whatever key the host offers on first contact
# (TOFU), which is no better than skipping verification. Pinning the keys GitHub
# publishes at https://docs.github.com/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints
# means verification is real from the sandbox's very first SSH connection.
GITHUB_HOST_KEYS = (
    "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl",
    "github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=",  # noqa: E501
    "github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk=",  # noqa: E501
)


class Sbx:
    """sbx commands for one sandbox.

    Every call carries ``env``, the sandbox's own environment: sbx points a
    sandbox's forwarded agent at the SSH_AUTH_SOCK of each call aimed at it,
    so no call may carry another socket.
    """

    def __init__(self, host: HostPort, env: Mapping[str, str]) -> None:
        self._host = host
        self._env = env

    @staticmethod
    def env(environ: Mapping[str, str], socket: Path) -> dict[str, str]:
        """The environment every call aimed at the sandbox must carry: its own agent socket.

        sbx points a sandbox's forwarded agent at SSH_AUTH_SOCK, so no call may
        carry another socket - including the final exec into ``sbx run``.
        """
        env = {key: value for key, value in environ.items() if key != "SSH_AGENT_PID"}
        env["SSH_AUTH_SOCK"] = str(socket)
        return env

    def exists(self, name: str) -> bool:
        return self._sbx("exec", name, "true").returncode == 0

    def create(self, name: str, agent: str, workspace: Path, context: Path) -> None:
        # --clone: the sandbox works in its own git clone, never a direct writable
        # mount of the workspace. The workspace must be a git repo (its main
        # checkout, not a worktree); sbx enforces and reports that itself.
        result = self._sbx("create", "--clone", "--name", name, agent, f"{workspace}", f"{context}:ro")
        if result.returncode != 0:
            raise SandboxError(f"sbx create failed: {result.stderr.strip()}")

    def ensure_known_hosts(self, name: str) -> None:
        """Trust GitHub's published host keys, so the sandbox's first SSH git operation
        doesn't block on host-key verification - there's no TTY inside it to confirm one.
        """
        setup = "mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/known_hosts && chmod 600 ~/.ssh/known_hosts"
        seed_one = "(grep -qxF '{key}' ~/.ssh/known_hosts || echo '{key}' >> ~/.ssh/known_hosts)"
        script = " && ".join((setup, *(seed_one.format(key=key) for key in GITHUB_HOST_KEYS)))
        result = self._sbx("exec", name, "sh", "-c", script)
        if result.returncode != 0:
            raise SandboxError(f"sbx exec known_hosts seed failed: {result.stderr.strip()}")

    def set_github_token(self, name: str, token: str) -> None:
        result = self._sbx("secret", "set", "github", "--sandbox", name, "-t", token)
        if result.returncode != 0:
            raise SandboxError(f"sbx secret set failed: {result.stderr.strip()}")

    def clear_github_token(self, name: str) -> None:
        result = self._sbx("secret", "rm", "github", "--sandbox", name, "-f")
        if result.returncode != 0:
            raise SandboxError(f"sbx secret rm failed: {result.stderr.strip()}")

    def set_git_config(self, name: str, key: str, value: str) -> None:
        result = self._sbx("exec", name, "git", "config", "--global", key, value)
        if result.returncode != 0:
            raise SandboxError(f"sbx exec git config failed: {result.stderr.strip()}")

    def agent_fingerprints(self, name: str) -> set[str] | None:
        """Fingerprints of the keys the sandbox's agent offers, or None if no agent reaches it."""
        result = self._sbx("exec", name, "ssh-add", "-l")
        if result.returncode == SshAddExitCode.HAS_KEYS:
            return {SshAgent.parse_fingerprint(line) for line in result.stdout.splitlines() if line.strip()}
        if result.returncode == SshAddExitCode.NO_KEYS:
            return set()
        if result.returncode == SshAddExitCode.NO_AGENT:
            return None
        raise SandboxError(f"could not list the sandbox's keys: {result.stderr.strip()}")

    def run_args(self, name: str, agent_args: Sequence[str]) -> tuple[str, ...]:
        """``sbx run`` for an existing sandbox.

        The sandbox is always created first, and sbx refuses workspace paths when
        attaching to an existing sandbox: its mounts are fixed at creation.
        """
        args = ("sbx", "run", "--name", name)
        return (*args, "--", *agent_args) if agent_args else args

    def _sbx(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self._host.run(("sbx", *args), env=self._env)
