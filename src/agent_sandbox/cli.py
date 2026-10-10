"""agent_sandbox --name NAME --context DIR [--ssh-key FILE] WORKSPACE [-- AGENT_ARGS...]"""

import argparse
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from agent_sandbox.config import AGENT, Config
from agent_sandbox.errors import SandboxError
from agent_sandbox.host import SubprocessHost
from agent_sandbox.sbx import Sbx, fingerprints, sbx_run_args
from agent_sandbox.ssh_agent import SshAgent

# What sbx accepts in a sandbox name, starting with a letter or digit. The name
# also names the agent's socket file, so this keeps out "/" and "..".
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*")
# Unix socket paths are limited to about 104 bytes on macOS (108 on Linux).
MAX_NAME_LENGTH = 64


@dataclass(frozen=True)
class Arguments:
    name: str
    workspace: Path
    context: Path
    ssh_key: Path | None = None
    agent_args: tuple[str, ...] = ()
    github_token_file: Path | None = None
    git_name: str | None = None
    git_email: str | None = None


@dataclass(frozen=True)
class Launch:
    """What to run, and what to tell the user before running it."""

    command: tuple[str, ...]
    env: Mapping[str, str]
    notes: tuple[str, ...] = ()


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
        description=(f"Launch a {AGENT} sandbox with its own ssh-agent and a read-only context directory."),
        usage="%(prog)s --name NAME --context DIR [--ssh-key FILE] WORKSPACE [-- AGENT_ARGS...]",
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
        parsed.name,
        parsed.workspace,
        parsed.context,
        parsed.ssh_key,
        tuple(agent_args),
        parsed.github_token_file,
        parsed.git_name,
        parsed.git_email,
    )


def prepare(args: Arguments, config: Config, sbx: Sbx, agent: SshAgent) -> Launch:
    """Check everything, set up the sandbox and its agent; return what to run."""
    workspace = existing_dir(args.workspace, "workspace")
    context = existing_dir(args.context, "context")
    ssh_key = existing_file(args.ssh_key, "ssh key") if args.ssh_key is not None else None
    check_paths(workspace, context, ssh_key)
    github_token_file = (
        existing_file(args.github_token_file, "github token file") if args.github_token_file is not None else None
    )
    public_key = (
        existing_file(ssh_key.with_name(ssh_key.name + ".pub"), "public key").read_text().strip()
        if ssh_key is not None
        else None
    )

    agent.ensure_running()
    agent.replace_keys([ssh_key] if ssh_key is not None else [])
    loaded = agent.list_keys()

    if not sbx.exists(args.name):
        sbx.create(args.name, config.agent, workspace, context)
    if github_token_file is not None:
        sbx.set_github_token(args.name, github_token_file.read_text().strip())
    else:
        sbx.clear_github_token(args.name)
    sbx.set_git_identity(args.name, args.git_name or "", args.git_email or "")
    sbx.set_commit_signing(args.name, public_key or "")
    check_forwarded_keys(fingerprints(loaded), sbx.agent_fingerprints(args.name))

    notes = (
        f"ssh-agent: {agent.socket}",
        *(f"key:       {key}" for key in loaded),
        *([] if loaded else ["warning: the sandbox's agent holds no key (pass --ssh-key)"]),
        f"sandbox:   {args.name}",
        f"workspace: {workspace}",
        f"context:   {context} (read-only)",
        note(
            github_token_file is not None,
            "github:    token configured",
            "github:    no token (pass --github-token-file to enable gh)",
        ),
        note(
            args.git_name is not None,
            f"git:       {args.git_name} <{args.git_email}>",
            "git:       not configured (pass --git-name/--git-email; commits will fail until set)",
        ),
        note(
            public_key is not None,
            "signing:   commits are ssh-signed",
            "signing:   no ssh key (pass --ssh-key; commits will fail until set)",
        ),
    )
    command = sbx_run_args(args.name, args.agent_args)
    return Launch(command, agent.env, notes)


def check_paths(workspace: Path, context: Path, ssh_key: Path | None) -> None:
    """Refuse layouts that would undo the sandbox's protections."""
    for path, what in [(workspace, "workspace"), (context, "context")]:
        # sbx reads a trailing ":ro" off its path arguments; a ":" in the path is ambiguous.
        if ":" in str(path):
            raise SandboxError(f"{what} path {str(path)!r} contains ':'")
    # Keep the context's read-only mount independent of the workspace's.
    if overlaps(workspace, context):
        raise SandboxError(f"context {str(context)!r} overlaps workspace {str(workspace)!r}")
    # The ssh key the sandbox can read could be copied out, bypassing the agent.
    if ssh_key is not None:
        for folder, what in [(workspace, "workspace"), (context, "context")]:
            if ssh_key.is_relative_to(folder):
                raise SandboxError(f"ssh key {str(ssh_key)!r} is inside the {what}, readable by the sandbox")


def existing_dir(path: Path, what: str) -> Path:
    if not path.is_dir():
        raise SandboxError(f"{what} {str(path)!r} is not a directory")
    return path.resolve()


def existing_file(path: Path, what: str) -> Path:
    if not path.is_file():
        raise SandboxError(f"{what} {str(path)!r} is not a file")
    return path.resolve()


def overlaps(a: Path, b: Path) -> bool:
    return a.is_relative_to(b) or b.is_relative_to(a)


def note(enabled: bool, if_true: str, if_false: str) -> str:
    return if_true if enabled else if_false


def check_forwarded_keys(expected: set[str], seen: set[str] | None) -> None:
    """The sandbox must see exactly the keys we loaded, whatever sbx's settings claim."""
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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    config = Config.default()
    host = SubprocessHost()
    agent = SshAgent(host, config.sockets_dir / f"{args.name}.sock", os.environ, config.uid)
    try:
        launch = prepare(args, config, Sbx(host, agent.env), agent)
    except SandboxError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    for note in launch.notes:
        print(f"==> {note}", file=sys.stderr)
    # Replace this process with sbx: it gets the terminal, signals and exit code.
    os.execvpe(launch.command[0], launch.command, launch.env)
