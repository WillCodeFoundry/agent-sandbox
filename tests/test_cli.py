from pathlib import Path

import pytest

from agent_sandbox.cli import MAX_NAME_LENGTH, Arguments, parse_args, prepare
from agent_sandbox.config import Config
from agent_sandbox.errors import SandboxError
from agent_sandbox.sbx import Sbx
from agent_sandbox.ssh_agent import SshAgent

NAME = "myproj-dev"
LIST_KEYS = ("ssh-add", "-l")  # on the host
DELETE_ALL = ("ssh-add", "-D")
EXISTS = ("sbx", "exec", NAME, "true")
SANDBOX_LIST_KEYS = ("sbx", "exec", NAME, "ssh-add", "-l")
NO_KEYS, NO_AGENT = 1, 2  # ssh-add -l exit codes
KEY_LINE = "256 SHA256:abc test-key (ED25519)\n"
PERSONAL_ENV = {"PATH": "/bin", "SSH_AUTH_SOCK": "/personal.sock", "SSH_AGENT_PID": "42"}


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
def key(tmp_path: Path) -> Path:
    path = tmp_path / "id_ed25519"
    path.write_text("key")
    return path


@pytest.fixture
def socket(config: Config) -> Path:
    return config.sockets_dir / f"{NAME}.sock"


@pytest.fixture
def ready_host(host):
    """A running, empty agent and an existing sandbox that sees no keys."""
    host.responses = {LIST_KEYS: NO_KEYS, DELETE_ALL: 0, EXISTS: 0, SANDBOX_LIST_KEYS: NO_KEYS}
    return host


def run_prepare(host, config, socket, workspace, context, keys=(), agent_args=()):
    agent = SshAgent(host, socket, PERSONAL_ENV, config.uid)
    args = Arguments(NAME, workspace, context, tuple(keys), tuple(agent_args))
    return prepare(args, config, Sbx(host, agent.env), agent)


def with_key(host, key):
    """The agent holds ``key``, and the sandbox sees it too."""
    host.responses[("ssh-add", "-q", str(key))] = 0
    host.responses[LIST_KEYS] = [NO_KEYS, KEY_LINE]
    host.responses[SANDBOX_LIST_KEYS] = KEY_LINE


# --- parse_args -------------------------------------------------------------


def test_parses_all_arguments():
    args = parse_args([
        "--name", NAME, "--context", "ctx", "--key", "k1", "--key", "k2",
        "/src/proj", "--", "--continue", "--", "x",
    ])

    assert args == Arguments(
        NAME, Path("/src/proj"), Path("ctx"), (Path("k1"), Path("k2")), ("--continue", "--", "x")
    )


def test_keys_are_optional():
    assert parse_args(["--name", "n", "--context", "ctx", "/src/proj"]).keys == ()


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


@pytest.mark.parametrize(
    "name", ["..", "a/b", ".hidden", "-x", "a b", "a:b", "", "x" * (MAX_NAME_LENGTH + 1)]
)
def test_unsafe_sandbox_names_are_rejected(name):
    with pytest.raises(SystemExit):
        parse_args([f"--name={name}", "--context", "ctx", "/src/proj"])


@pytest.mark.parametrize("name", [NAME, "a.b+c", "Dev2", "x" * MAX_NAME_LENGTH])
def test_valid_sandbox_names(name):
    assert parse_args(["--name", name, "--context", "ctx", "/src/proj"]).name == name


# --- prepare: launch --------------------------------------------------------


def test_launches_sbx_with_only_the_sandboxs_agent(ready_host, config, socket, workspace, context):
    launch = run_prepare(ready_host, config, socket, workspace, context, agent_args=["--continue"])

    assert launch.command == ("sbx", "run", "--name", NAME, "--", "--continue")
    assert launch.env == {"PATH": "/bin", "SSH_AUTH_SOCK": str(socket)}


def test_every_sbx_call_carries_the_sandboxs_socket(ready_host, config, socket, workspace, context):
    run_prepare(ready_host, config, socket, workspace, context)

    sbx_envs = [env for command, env in ready_host.calls if command[0] == "sbx"]
    assert sbx_envs and all(env is not None and env["SSH_AUTH_SOCK"] == str(socket) for env in sbx_envs)


def test_creates_a_missing_sandbox_before_checking_it(ready_host, config, socket, workspace, context):
    create = ("sbx", "create", "--name", NAME, "claude", f"{workspace}", f"{context}:ro")
    ready_host.responses[EXISTS] = 1
    ready_host.responses[create] = 0

    run_prepare(ready_host, config, socket, workspace, context)

    commands = ready_host.commands
    assert commands.index(create) < commands.index(SANDBOX_LIST_KEYS)


def test_reuses_an_existing_sandbox(ready_host, config, socket, workspace, context):
    run_prepare(ready_host, config, socket, workspace, context)

    assert not any(command[:2] == ("sbx", "create") for command in ready_host.commands)


def test_the_agent_holds_exactly_the_given_keys(ready_host, config, socket, workspace, context, key):
    with_key(ready_host, key)

    launch = run_prepare(ready_host, config, socket, workspace, context, keys=[key])

    commands = ready_host.commands
    assert commands.index(DELETE_ALL) < commands.index(("ssh-add", "-q", str(key)))
    assert any("test-key" in note for note in launch.notes)


def test_warns_when_no_keys_are_given(ready_host, config, socket, workspace, context):
    launch = run_prepare(ready_host, config, socket, workspace, context)

    assert DELETE_ALL in ready_host.commands  # still emptied: no keys from an earlier launch
    assert any("holds no keys" in note for note in launch.notes)


# --- prepare: verifying what the sandbox sees -------------------------------


def test_an_extra_key_in_the_sandbox_stops_the_launch(ready_host, config, socket, workspace, context, key):
    with_key(ready_host, key)
    ready_host.responses[SANDBOX_LIST_KEYS] = KEY_LINE + "256 SHA256:personal me@laptop (ED25519)\n"

    with pytest.raises(SandboxError, match="(?s)sandbox sees keys .*daemon restart"):
        run_prepare(ready_host, config, socket, workspace, context, keys=[key])


def test_keys_not_reaching_the_sandbox_stop_the_launch(ready_host, config, socket, workspace, context, key):
    with_key(ready_host, key)
    ready_host.responses[SANDBOX_LIST_KEYS] = NO_AGENT

    with pytest.raises(SandboxError, match="sandbox sees no ssh-agent"):
        run_prepare(ready_host, config, socket, workspace, context, keys=[key])


def test_no_agent_in_the_sandbox_is_fine_without_keys(ready_host, config, socket, workspace, context):
    ready_host.responses[SANDBOX_LIST_KEYS] = NO_AGENT

    run_prepare(ready_host, config, socket, workspace, context)


# --- prepare: path checks ---------------------------------------------------


@pytest.mark.parametrize(
    "missing, message",
    [
        ("workspace", "workspace .* is not a directory"),
        ("context", "context .* is not a directory"),
        ("key", "key .* is not a file"),
    ],
)
def test_missing_paths_stop_before_anything_runs(
    host, config, socket, workspace, context, key, tmp_path, missing, message
):
    paths = {"workspace": workspace, "context": context, "key": key}
    paths[missing] = tmp_path / "missing"

    with pytest.raises(SandboxError, match=message):
        run_prepare(host, config, socket, paths["workspace"], paths["context"], keys=[paths["key"]])
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
def test_keys_the_sandbox_could_read_are_refused(host, config, socket, workspace, context, folder):
    inside = {"workspace": workspace, "context": context}[folder] / "id_ed25519"
    inside.write_text("key")

    with pytest.raises(SandboxError, match=f"inside the {folder}"):
        run_prepare(host, config, socket, workspace, context, keys=[inside])
    assert host.calls == []


@pytest.mark.parametrize("folder", ["workspace", "context"])
def test_paths_containing_a_colon_are_refused(host, config, socket, workspace, context, tmp_path, folder):
    colon = tmp_path / "x:rw"
    colon.mkdir()
    paths = {"workspace": workspace, "context": context, folder: colon}

    with pytest.raises(SandboxError, match="contains ':'"):
        run_prepare(host, config, socket, paths["workspace"], paths["context"])
    assert host.calls == []
