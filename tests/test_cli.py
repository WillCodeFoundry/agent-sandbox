from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_sandbox.cli import (
    MAX_NAME_LENGTH,
    Arguments,
    ensure_valid_args,
    execution_description,
    parse_args,
    prepare_sbx_execution,
)
from agent_sandbox.config import Config
from agent_sandbox.errors import SandboxError
from agent_sandbox.host import HostPort
from agent_sandbox.sbx import GITHUB_HOST_KEYS, Sbx
from agent_sandbox.ssh_agent import SshAgent

NAME = "myproj-dev"
LIST_KEYS = ("ssh-add", "-l")  # on the host
DELETE_ALL = ("ssh-add", "-D")
EXISTS = ("sbx", "exec", NAME, "true")
SANDBOX_LIST_KEYS = ("sbx", "exec", NAME, "ssh-add", "-l")
CLEAR_TOKEN = ("sbx", "secret", "rm", "github", "--sandbox", NAME, "-f")
SET_TOKEN = ("sbx", "secret", "set", "github", "--sandbox", NAME, "-t", "ghp_abc123")
BLANK_GIT_NAME = ("sbx", "exec", NAME, "git", "config", "--global", "user.name", "")
BLANK_GIT_EMAIL = ("sbx", "exec", NAME, "git", "config", "--global", "user.email", "")
SET_GPG_FORMAT = ("sbx", "exec", NAME, "git", "config", "--global", "gpg.format", "ssh")
SET_GPGSIGN = ("sbx", "exec", NAME, "git", "config", "--global", "commit.gpgsign", "true")
BLANK_SIGNING_KEY = ("sbx", "exec", NAME, "git", "config", "--global", "user.signingkey", "")
ALLOW_GITHUB_SSH = ("sbx", "policy", "allow", "network", "--sandbox", NAME, "github.com:22")
NO_KEYS, NO_AGENT = 1, 2  # ssh-add -l exit codes
KEY_LINE = "256 SHA256:abc test-key (ED25519)\n"
PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest test-key"
PERSONAL_ENV = {"PATH": "/bin", "SSH_AUTH_SOCK": "/personal.sock", "SSH_AGENT_PID": "42"}


def signing_key_command(public_key: str) -> tuple[str, ...]:
    return ("sbx", "exec", NAME, "git", "config", "--global", "user.signingkey", f"key::{public_key}")


def known_hosts_command() -> tuple[str, ...]:
    setup = "mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/known_hosts && chmod 600 ~/.ssh/known_hosts"
    seed_one = "(grep -qxF '{key}' ~/.ssh/known_hosts || echo '{key}' >> ~/.ssh/known_hosts)"
    script = " && ".join((setup, *(seed_one.format(key=key) for key in GITHUB_HOST_KEYS)))
    return ("sbx", "exec", NAME, "sh", "-c", script)


KNOWN_HOSTS = known_hosts_command()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "myproj"
    path.mkdir()
    return path


@pytest.fixture
def context(tmp_path: Path) -> Path:
    path = tmp_path / "context"
    path.mkdir()
    return path


@pytest.fixture
def ssh_key(tmp_path: Path) -> Path:
    path = tmp_path / "id_ed25519"
    path.write_text("key")
    path.with_name(path.name + ".pub").write_text(PUBLIC_KEY + "\n")
    return path


@pytest.fixture
def github_token_file(tmp_path: Path) -> Path:
    path = tmp_path / "gh-token"
    path.write_text("ghp_abc123\n")
    return path


@pytest.fixture
def socket(config: Config, host: HostPort) -> Path:
    return host.socket_path(config.sockets_dir, NAME)


@pytest.fixture
def ready_host(host):
    """A running, empty agent and an existing sandbox with nothing configured."""
    host.responses = {
        LIST_KEYS: NO_KEYS,
        DELETE_ALL: 0,
        EXISTS: 0,
        SANDBOX_LIST_KEYS: NO_KEYS,
        ALLOW_GITHUB_SSH: 0,
        KNOWN_HOSTS: 0,
        CLEAR_TOKEN: 0,
        BLANK_GIT_NAME: 0,
        BLANK_GIT_EMAIL: 0,
        SET_GPG_FORMAT: 0,
        SET_GPGSIGN: 0,
        BLANK_SIGNING_KEY: 0,
    }
    return host


def run_prepare(
    host,
    config,
    socket,
    workspace,
    context,
    ssh_key=None,
    agent_args=(),
    github_token_file=None,
    git_name=None,
    git_email=None,
):
    """Run prepare_sbx_execution and report what the subsequent launch would do."""
    host.environ_value = PERSONAL_ENV
    ssh_agent = SshAgent(host, socket)
    env = Sbx.env(host.environ(), socket)
    sbx = Sbx(host, env)
    args = Arguments(
        name=NAME,
        workspace=workspace,
        context=context,
        ssh_key=ssh_key,
        agent_args=tuple(agent_args),
        github_token_file=github_token_file,
        git_name=git_name,
        git_email=git_email,
    )
    ensure_valid_args(args, host)
    prepare_sbx_execution(args, config, sbx, ssh_agent, host)
    return SimpleNamespace(
        command=sbx.run_args(args.name, args.agent_args),
        env=env,
        message=execution_description(args, ssh_agent),
    )


def with_ssh_key(host, ssh_key):
    """The agent holds ``ssh_key``, the sandbox sees it, and can sign commits with it."""
    host.responses[("ssh-add", "-q", str(ssh_key))] = 0
    host.responses[LIST_KEYS] = [NO_KEYS, KEY_LINE, KEY_LINE]
    host.responses[SANDBOX_LIST_KEYS] = KEY_LINE
    host.responses[signing_key_command(PUBLIC_KEY)] = 0


@pytest.fixture
def prepare(ready_host, config, socket, workspace, context):
    """prepare_sbx_execution against the standard sandbox, varying only what's passed."""

    def _prepare(ssh_key=None, agent_args=(), github_token_file=None, git_name=None, git_email=None):
        return run_prepare(
            ready_host,
            config,
            socket,
            workspace,
            context,
            ssh_key=ssh_key,
            agent_args=agent_args,
            github_token_file=github_token_file,
            git_name=git_name,
            git_email=git_email,
        )

    return _prepare


# --- parse_args -------------------------------------------------------------


def test_parses_all_arguments():
    args = parse_args(
        [
            "--name",
            NAME,
            "--context",
            "ctx",
            "--ssh-key",
            "sk",
            "--github-token-file",
            "tok",
            "--git-name",
            "Dev",
            "--git-email",
            "dev@example.com",
            "/src/proj",
            "--",
            "--continue",
            "--",
            "x",
        ]
    )

    assert args == Arguments(
        name=NAME,
        workspace=Path("/src/proj").resolve(),
        context=Path("ctx").resolve(),
        ssh_key=Path("sk").resolve(),
        agent_args=("--continue", "--", "x"),
        github_token_file=Path("tok").resolve(),
        git_name="Dev",
        git_email="dev@example.com",
    )


def test_ssh_key_is_optional():
    assert parse_args(["--name", "n", "--context", "ctx", "/src/proj"]).ssh_key is None


def test_ssh_key_may_only_be_given_once(capsys):
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--name",
                "n",
                "--context",
                "ctx",
                "--ssh-key",
                "a",
                "--ssh-key",
                "b",
                "/src/proj",
            ]
        )

    assert "--ssh-key may only be given once" in capsys.readouterr().err


def test_github_token_file_is_optional():
    args = parse_args(["--name", "n", "--context", "ctx", "/src/proj"])
    assert args.github_token_file is None


def test_git_identity_is_optional():
    args = parse_args(["--name", "n", "--context", "ctx", "/src/proj"])
    assert args.git_name is None
    assert args.git_email is None


@pytest.mark.parametrize(
    "argv",
    [
        ["--git-name", "Dev"],  # no --git-email
        ["--git-email", "dev@example.com"],  # no --git-name
    ],
)
def test_git_name_and_email_must_be_given_together(argv):
    with pytest.raises(SystemExit):
        parse_args(["--name", "n", "--context", "ctx", "/src/proj", *argv])


@pytest.mark.parametrize(
    "argv",
    [
        ["--context", "ctx", "/src/proj"],  # no --name
        ["--name", "n", "/src/proj"],  # no --context
        ["--name", "n", "--context", "ctx"],  # no workspace
    ],
)
def test_required_arguments(argv):
    with pytest.raises(SystemExit):
        parse_args(argv)


@pytest.mark.parametrize("name", ["..", "a/b", ".hidden", "-x", "a b", "a:b", "", "x" * (MAX_NAME_LENGTH + 1)])
def test_unsafe_sandbox_names_are_rejected(name):
    with pytest.raises(SystemExit):
        parse_args([f"--name={name}", "--context", "ctx", "/src/proj"])


@pytest.mark.parametrize("name", [NAME, "a.b+c", "Dev2", "x" * MAX_NAME_LENGTH])
def test_valid_sandbox_names(name):
    assert parse_args(["--name", name, "--context", "ctx", "/src/proj"]).name == name


# --- prepare: launch --------------------------------------------------------


def test_launches_sbx_with_only_the_sandboxs_agent(prepare, socket):
    cmd = prepare(agent_args=["--continue"])

    assert cmd.command == ("sbx", "run", "--name", NAME, "--", "--continue")
    assert cmd.env == {"PATH": "/bin", "SSH_AUTH_SOCK": str(socket)}


def test_every_sbx_call_carries_the_sandboxs_socket(prepare, ready_host, socket):
    prepare()

    sbx_envs = [env for command, env in ready_host.calls if command[0] == "sbx"]
    assert sbx_envs and all(env is not None and env["SSH_AUTH_SOCK"] == str(socket) for env in sbx_envs)


def test_creates_a_missing_cloned_sandbox_before_checking_it(prepare, ready_host, workspace, context):
    create = ("sbx", "create", "--clone", "--name", NAME, "claude", f"{workspace}", f"{context}:ro")
    ready_host.responses[EXISTS] = 1
    ready_host.responses[create] = 0

    cmd = prepare()

    commands = ready_host.commands
    assert commands.index(create) < commands.index(SANDBOX_LIST_KEYS)
    assert "cloned, not directly writable" in cmd.message


def test_reuses_an_existing_sandbox(prepare, ready_host):
    prepare()

    assert not any(command[:2] == ("sbx", "create") for command in ready_host.commands)


def test_allows_this_sandboxs_ssh_traffic_to_github_on_every_launch(prepare, ready_host):
    prepare()

    assert ALLOW_GITHUB_SSH in ready_host.commands


def test_github_ssh_policy_failure_is_reported(prepare, ready_host):
    ready_host.responses[ALLOW_GITHUB_SSH] = 1

    with pytest.raises(SandboxError, match="sbx policy allow failed"):
        prepare()


def test_seeds_githubs_known_host_keys_on_every_launch(prepare, ready_host):
    prepare()

    assert KNOWN_HOSTS in ready_host.commands


def test_known_hosts_seed_failure_is_reported(prepare, ready_host):
    ready_host.responses[KNOWN_HOSTS] = 1

    with pytest.raises(SandboxError, match="sbx exec known_hosts seed failed"):
        prepare()


def test_the_agent_holds_exactly_the_given_key(prepare, ready_host, ssh_key):
    with_ssh_key(ready_host, ssh_key)

    cmd = prepare(ssh_key=ssh_key)

    commands = ready_host.commands
    assert commands.index(DELETE_ALL) < commands.index(("ssh-add", "-q", str(ssh_key)))
    assert "test-key" in cmd.message
    assert "holds no key" not in cmd.message


def test_warns_when_no_ssh_key_is_given(prepare, ready_host):
    cmd = prepare()

    assert DELETE_ALL in ready_host.commands  # still emptied: no key from an earlier launch
    assert "holds no key" in cmd.message


# --- prepare: github token ---------------------------------------------------


def test_sets_the_sandboxs_github_token(prepare, ready_host, github_token_file):
    ready_host.responses[SET_TOKEN] = 0

    cmd = prepare(github_token_file=github_token_file)

    assert SET_TOKEN in ready_host.commands
    assert CLEAR_TOKEN not in ready_host.commands
    assert "token configured" in cmd.message
    assert "no token" not in cmd.message


def test_clears_the_sandboxs_github_token_when_not_given(prepare, ready_host):
    cmd = prepare()

    assert CLEAR_TOKEN in ready_host.commands  # still cleared: no token from an earlier launch
    assert not any(command[:3] == ("sbx", "secret", "set") for command in ready_host.commands)
    assert "no token" in cmd.message


def test_github_token_set_failure_is_reported(prepare, ready_host, github_token_file):
    ready_host.responses[SET_TOKEN] = 1

    with pytest.raises(SandboxError, match="sbx secret set failed"):
        prepare(github_token_file=github_token_file)


def test_github_token_clear_failure_is_reported(prepare, ready_host):
    ready_host.responses[CLEAR_TOKEN] = 1

    with pytest.raises(SandboxError, match="sbx secret rm failed"):
        prepare()


# --- prepare: git identity ---------------------------------------------------


def test_sets_the_sandboxs_git_identity(prepare, ready_host):
    set_name = ("sbx", "exec", NAME, "git", "config", "--global", "user.name", "Dev")
    set_email = ("sbx", "exec", NAME, "git", "config", "--global", "user.email", "dev@example.com")
    ready_host.responses[set_name] = 0
    ready_host.responses[set_email] = 0

    cmd = prepare(git_name="Dev", git_email="dev@example.com")

    assert set_name in ready_host.commands
    assert set_email in ready_host.commands
    assert BLANK_GIT_NAME not in ready_host.commands
    assert "Dev <dev@example.com>" in cmd.message
    assert "not configured" not in cmd.message


def test_blanks_the_sandboxs_git_identity_when_not_given(prepare, ready_host):
    cmd = prepare()

    # still blanked: no identity from an earlier launch, and git refuses to commit with none
    assert BLANK_GIT_NAME in ready_host.commands
    assert BLANK_GIT_EMAIL in ready_host.commands
    assert "not configured" in cmd.message


def test_git_identity_failure_is_reported(prepare, ready_host):
    ready_host.responses[BLANK_GIT_NAME] = 1

    with pytest.raises(SandboxError, match="sbx exec git config failed"):
        prepare()


# --- prepare: commit signing -------------------------------------------------


def test_signs_commits_with_the_given_ssh_key(prepare, ready_host, ssh_key):
    with_ssh_key(ready_host, ssh_key)

    cmd = prepare(ssh_key=ssh_key)

    assert SET_GPG_FORMAT in ready_host.commands
    assert SET_GPGSIGN in ready_host.commands
    assert signing_key_command(PUBLIC_KEY) in ready_host.commands
    assert BLANK_SIGNING_KEY not in ready_host.commands
    assert "ssh-signed" in cmd.message
    assert "no ssh key" not in cmd.message


def test_blanks_the_signing_key_when_no_ssh_key_is_given(prepare, ready_host):
    cmd = prepare()

    # still configured to fail: no key means no way to sign, but commit.gpgsign stays on
    assert SET_GPG_FORMAT in ready_host.commands
    assert SET_GPGSIGN in ready_host.commands
    assert BLANK_SIGNING_KEY in ready_host.commands
    assert "no ssh key" in cmd.message


def test_commit_signing_failure_is_reported(prepare, ready_host):
    ready_host.responses[SET_GPG_FORMAT] = 1

    with pytest.raises(SandboxError, match="sbx exec git config failed"):
        prepare()


# --- prepare: verifying what the sandbox sees -------------------------------


def test_an_extra_key_in_the_sandbox_stops_the_launch(prepare, ready_host, ssh_key):
    with_ssh_key(ready_host, ssh_key)
    ready_host.responses[SANDBOX_LIST_KEYS] = KEY_LINE + "256 SHA256:personal me@laptop (ED25519)\n"

    with pytest.raises(SandboxError, match="(?s)sandbox sees keys .*daemon restart"):
        prepare(ssh_key=ssh_key)


def test_key_not_reaching_the_sandbox_stops_the_launch(prepare, ready_host, ssh_key):
    with_ssh_key(ready_host, ssh_key)
    ready_host.responses[SANDBOX_LIST_KEYS] = NO_AGENT

    with pytest.raises(SandboxError, match="sandbox sees no ssh-agent"):
        prepare(ssh_key=ssh_key)


def test_no_agent_in_the_sandbox_is_fine_without_a_key(prepare, ready_host):
    ready_host.responses[SANDBOX_LIST_KEYS] = NO_AGENT

    prepare()


# --- prepare: path checks ---------------------------------------------------


@pytest.mark.parametrize(
    "missing, message",
    [
        ("workspace", "workspace .* is not a directory"),
        ("context", "context .* is not a directory"),
        ("ssh_key", "ssh key .* is not a file"),
        ("github_token_file", "github token file .* is not a file"),
    ],
)
def test_missing_paths_stop_before_anything_runs(
    host, config, socket, workspace, context, ssh_key, github_token_file, tmp_path, missing, message
):
    paths = {
        "workspace": workspace,
        "context": context,
        "ssh_key": ssh_key,
        "github_token_file": github_token_file,
    }
    paths[missing] = tmp_path / "missing"

    with pytest.raises(SandboxError, match=message):
        run_prepare(
            host,
            config,
            socket,
            paths["workspace"],
            paths["context"],
            ssh_key=paths["ssh_key"],
            github_token_file=paths["github_token_file"],
        )
    assert host.calls == []


def test_missing_public_key_stops_before_anything_runs(host, config, socket, workspace, context, tmp_path):
    key_without_pub = tmp_path / "id_ed25519"
    key_without_pub.write_text("key")

    with pytest.raises(SandboxError, match="public key .* is not a file"):
        run_prepare(host, config, socket, workspace, context, ssh_key=key_without_pub)
    assert host.calls == []


@pytest.mark.parametrize("layout", ["context inside workspace", "workspace inside context", "same"])
def test_overlapping_workspace_and_context_are_refused(host, config, socket, tmp_path, layout):
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    workspace, context = {
        "context inside workspace": (outer, inner),
        "workspace inside context": (inner, outer),
        "same": (outer, outer),
    }[layout]

    with pytest.raises(SandboxError, match="overlaps"):
        run_prepare(host, config, socket, workspace, context)
    assert host.calls == []


@pytest.mark.parametrize("folder", ["workspace", "context"])
def test_ssh_key_the_sandbox_could_read_is_refused(host, config, socket, workspace, context, folder):
    inside = {"workspace": workspace, "context": context}[folder] / "id_ed25519"
    inside.write_text("key")

    with pytest.raises(SandboxError, match=f"inside the {folder}"):
        run_prepare(host, config, socket, workspace, context, ssh_key=inside)
    assert host.calls == []


@pytest.mark.parametrize("folder", ["workspace", "context"])
def test_paths_containing_a_colon_are_refused(host, config, socket, workspace, context, tmp_path, folder):
    colon = tmp_path / "x:rw"
    colon.mkdir()
    paths = {"workspace": workspace, "context": context, folder: colon}

    with pytest.raises(SandboxError, match="contains ':'"):
        run_prepare(host, config, socket, paths["workspace"], paths["context"])
    assert host.calls == []
