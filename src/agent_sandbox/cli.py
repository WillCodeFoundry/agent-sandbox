"""agent_sandbox --name NAME --context DIR [--ssh-key FILE] [--github-token-file FILE]
[--git-name NAME --git-email EMAIL] WORKSPACE [-- AGENT_ARGS...]
"""

import argparse
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from agent_sandbox.config import AGENT, Config
from agent_sandbox.errors import SandboxError
from agent_sandbox.host import Host, HostPort
from agent_sandbox.sbx import Sbx
from agent_sandbox.ssh_agent import SshAgent

# What sbx accepts in a sandbox name, starting with a letter or digit. The name
# also names the ssh-agent's socket file, so this keeps out "/" and "..".
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*")
# Unix socket paths are limited to about 104 bytes on macOS (108 on Linux).
MAX_NAME_LENGTH = 64


@dataclass(frozen=True)
class Arguments:
    """workspace, context, ssh_key and github_token_file are always resolved paths."""

    name: str
    workspace: Path
    context: Path
    ssh_key: Path | None = None
    agent_args: tuple[str, ...] = ()
    github_token_file: Path | None = None
    git_name: str | None = None
    git_email: str | None = None


class _StoreOnce(argparse.Action):
    """Like the default store action, but refuses to be given more than once."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        if getattr(namespace, self.dest) is not None:
            parser.error(f"{option_string} may only be given once")
        setattr(namespace, self.dest, values)


def sandbox_name(value: str) -> str:
    """argparse type for --name."""
    if len(value) > MAX_NAME_LENGTH:
        raise argparse.ArgumentTypeError(
            f"sandbox name is {len(value)} characters; at most {MAX_NAME_LENGTH} "
            "(it also names the ssh-agent socket, whose path length is limited)"
        )
    if not NAME_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            f"invalid sandbox name {value!r} (letters, digits, '.', '+' and '-'; must start with a letter or digit)"
        )
    return value


def parse_args(argv: Sequence[str]) -> Arguments:
    # Everything after the first "--" goes to the agent untouched.
    argv = list(argv)
    split = argv.index("--") if "--" in argv else len(argv)
    own, agent_args = argv[:split], argv[split + 1 :]

    parser = argparse.ArgumentParser(
        prog="agent_sandbox",
        description=f"Launch a {AGENT} sandbox with its own ssh-agent and a read-only context directory.",
        usage=(
            "%(prog)s --name NAME --context DIR [--ssh-key FILE] [--github-token-file FILE]\n"
            "                     [--git-name NAME --git-email EMAIL] WORKSPACE [-- AGENT_ARGS...]"
        ),
        epilog=(
            "example:\n"
            "  agent_sandbox --name myproj-dev --context ./agents/dev \\\n"
            "                --ssh-key ~/.ssh/dev_ed25519 ~/src/myproj -- --continue"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("workspace", type=Path, help="project directory to work in")
    parser.add_argument(
        "--name",
        required=True,
        type=sandbox_name,
        help="sandbox name; the same name re-attaches to the same sandbox",
    )
    parser.add_argument(
        "--context",
        required=True,
        type=Path,
        metavar="DIR",
        help="directory mounted read-only into the sandbox",
    )
    parser.add_argument(
        "--ssh-key",
        dest="ssh_key",
        action=_StoreOnce,
        type=Path,
        default=None,
        metavar="FILE",
        help="private key for the sandbox's ssh-agent and commit signing",
    )
    parser.add_argument(
        "--github-token-file",
        type=Path,
        default=None,
        metavar="FILE",
        help="file holding a GitHub token to give the sandbox (enables gh, e.g. to open PRs)",
    )
    parser.add_argument(
        "--git-name",
        default=None,
        metavar="NAME",
        help="git user.name to set inside the sandbox; requires --git-email",
    )
    parser.add_argument(
        "--git-email",
        default=None,
        metavar="EMAIL",
        help="git user.email to set inside the sandbox; requires --git-name",
    )
    parsed = parser.parse_args(own)
    if (parsed.git_name is None) != (parsed.git_email is None):
        parser.error("--git-name and --git-email must be given together")
    return Arguments(
        name=parsed.name,
        workspace=parsed.workspace.resolve(),
        context=parsed.context.resolve(),
        ssh_key=parsed.ssh_key.resolve() if parsed.ssh_key is not None else None,
        agent_args=tuple(agent_args),
        github_token_file=parsed.github_token_file.resolve() if parsed.github_token_file is not None else None,
        git_name=parsed.git_name,
        git_email=parsed.git_email,
    )


def ensure_paths_safe(workspace: Path, context: Path, ssh_key: Path | None) -> None:
    """Refuse layouts that would undo the sandbox's protections.

    workspace, context and ssh_key must already be resolved, so aliasing through a
    relative form can't slip past these checks.
    """
    # sbx reads a trailing ":ro" off its path arguments; a ":" in the path is ambiguous.
    if ":" in str(workspace):
        raise SandboxError(f"workspace path {str(workspace)!r} contains ':'")
    if ":" in str(context):
        raise SandboxError(f"context path {str(context)!r} contains ':'")
    # Keep the context's read-only mount independent of the workspace's.
    if workspace.is_relative_to(context) or context.is_relative_to(workspace):
        raise SandboxError(f"context {str(context)!r} overlaps workspace {str(workspace)!r}")
    # The ssh key the sandbox can read could be copied out, bypassing the agent.
    if ssh_key is not None and ssh_key.is_relative_to(workspace):
        raise SandboxError(f"ssh key {str(ssh_key)!r} is inside the workspace, readable by the sandbox")
    if ssh_key is not None and ssh_key.is_relative_to(context):
        raise SandboxError(f"ssh key {str(ssh_key)!r} is inside the context, readable by the sandbox")


def ensure_valid_args(args: Arguments, host: HostPort) -> None:
    """Raise if anything about args would undo the sandbox's protections or doesn't exist."""
    host.ensure_dir_exists(args.workspace, "workspace")
    host.ensure_dir_exists(args.context, "context")
    if args.ssh_key is not None:
        host.ensure_file_exists(args.ssh_key, "ssh key")
    ensure_paths_safe(args.workspace, args.context, args.ssh_key)
    if args.github_token_file is not None:
        host.ensure_file_exists(args.github_token_file, "github token file")
    if args.ssh_key is not None:
        host.ensure_file_exists(host.public_key_path(args.ssh_key), "public key")


def prepare_sbx_execution(args: Arguments, config: Config, sbx: Sbx, ssh_agent: SshAgent, host: HostPort) -> None:
    """Synchronize the sandbox and its ssh-agent with args, and verify what the sandbox can see.

    Call ensure_valid_args(args, host) first.
    """
    ensure_ssh_agent_running(args, ssh_agent)
    ensure_sandbox_present(args, config, sbx, host)
    ensure_forwarded_keys(ssh_agent, sbx, args.name)


def ensure_ssh_agent_running(args: Arguments, ssh_agent: SshAgent) -> None:
    """Make the sandbox's ssh-agent match args: running, and holding only args.ssh_key (if given)."""
    ssh_agent.ensure_running()
    ssh_agent.replace_keys([args.ssh_key] if args.ssh_key is not None else [])


def ensure_sandbox_present(args: Arguments, config: Config, sbx: Sbx, host: HostPort) -> None:
    """Make the sandbox exist and match args: SSH policy, known hosts, github token, git identity, commit signing."""
    if not sbx.exists(args.name):
        sbx.create(args.name, config.agent, args.workspace, args.context)
    sbx.ensure_github_ssh_allowed(args.name)
    sbx.ensure_known_hosts(args.name)
    if args.github_token_file is not None:
        sbx.set_github_token(args.name, args.github_token_file.read_text().strip())
    else:
        sbx.clear_github_token(args.name)

    ssh_key = args.ssh_key
    public_key = host.public_key_path(ssh_key).read_text().strip() if ssh_key is not None else None
    # Empty values are unset (see Sbx.set_git_config) so git refuses to commit/sign,
    # meaning a launch without an identity or key never leaves a previous launch's
    # configuration behind.
    git_config = [
        ("user.name", args.git_name or ""),
        ("user.email", args.git_email or ""),
        ("gpg.format", "ssh"),
        ("commit.gpgsign", "true"),
        ("user.signingkey", f"key::{public_key}" if public_key else ""),
    ]
    for key, value in git_config:
        sbx.set_git_config(args.name, key, value)


def ensure_forwarded_keys(ssh_agent: SshAgent, sbx: Sbx, name: str) -> None:
    """The sandbox must see exactly the keys we loaded, whatever sbx's settings claim."""
    expected = ssh_agent.list_key_fingerprints()
    seen = sbx.agent_fingerprints(name)
    if seen is None and not expected:
        return  # no agent at all: nothing of ours, or anyone else's, reaches the sandbox
    if seen != expected:
        found = "no ssh-agent" if seen is None else f"keys {sorted(seen)}"
        raise SandboxError(
            f"the sandbox sees {found}, expected {sorted(expected) or 'no keys'}.\n"
            "  check: sbx settings get ssh.agentForwardingEnabled  (must be true)\n"
            "         sbx settings get ssh.agentSocketPath         (must be empty)\n"
            "  then:  sbx daemon restart"
        )


def execution_description(args: Arguments, ssh_agent: SshAgent) -> str:
    """Build the message describing what running args will do, ready to log as-is."""
    loaded = ssh_agent.list_keys()
    # fmt: off
    notes = (
        f"ssh-agent: {ssh_agent.socket}",
        *(f"key:       {key}" for key in loaded),
        *([] if loaded else ["warning: the sandbox's agent holds no key (pass --ssh-key)"]),
        f"sandbox:   {args.name}",
        f"workspace: {args.workspace} (cloned, not directly writable)",
        f"context:   {args.context} (read-only)",
        "github:    token configured" if args.github_token_file is not None else
        "github:    no token (pass --github-token-file to enable gh)",
        f"git:       {args.git_name} <{args.git_email}>" if args.git_name is not None else
        "git:       not configured (pass --git-name/--git-email; commits will fail until set)",
        "signing:   commits are ssh-signed" if args.ssh_key is not None else
        "signing:   no ssh key (pass --ssh-key; commits will fail until set)",
    )
    # fmt: on
    return "\n".join(f"==> {note}" for note in notes)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    config = Config.default()
    host = Host(os.getuid())
    socket = host.socket_path(config.sockets_dir, args.name)
    ssh_agent = SshAgent(host, socket)
    env = Sbx.env(host.environ(), socket)
    sbx = Sbx(host, env)
    try:
        # A socket in a directory someone else controls could be their agent, not ours.
        host.ensure_private_dir(socket.parent)
        ensure_valid_args(args, host)
        prepare_sbx_execution(args, config, sbx, ssh_agent, host)
    except SandboxError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(execution_description(args, ssh_agent), file=sys.stderr)
    # Replace this process with sbx: it gets the terminal, signals and exit code.
    host.exec(sbx.run_args(args.name, args.agent_args), env)
