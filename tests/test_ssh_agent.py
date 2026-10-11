import pytest

from agent_sandbox.errors import SandboxError
from agent_sandbox.ssh_agent import SshAgent

LIST = ("ssh-add", "-l")
DELETE_ALL = ("ssh-add", "-D")
NOT_RUNNING, NO_KEYS = 2, 1  # ssh-add -l exit codes
PERSONAL_ENV = {"PATH": "/bin", "HOME": "/home/dev", "SSH_AUTH_SOCK": "/personal.sock", "SSH_AGENT_PID": "42"}


@pytest.fixture
def socket(tmp_path):
    return tmp_path / "sockets" / "dev.sock"


@pytest.fixture
def make_agent(host, socket):
    host.environ_value = PERSONAL_ENV
    return lambda: SshAgent(host, socket)


def start(socket):
    return ("ssh-agent", "-a", str(socket), "-s")


# --- environment ------------------------------------------------------------


def test_ssh_add_calls_only_carry_path_and_the_sandboxs_socket(host, make_agent, socket):
    host.responses = {LIST: NO_KEYS}

    make_agent().ensure_running()

    assert host.calls == [(LIST, {"PATH": "/bin", "SSH_AUTH_SOCK": str(socket)})]


# --- ensure_running ---------------------------------------------------------


def test_starts_an_agent_when_none_is_running(host, make_agent, socket):
    host.responses = {LIST: [NOT_RUNNING, NO_KEYS], start(socket): 0}

    make_agent().ensure_running()

    assert host.commands == [LIST, start(socket), LIST]


def test_reuses_a_running_agent(host, make_agent):
    host.responses = {LIST: NO_KEYS}

    make_agent().ensure_running()

    assert host.commands == [LIST]


def test_removes_a_stale_socket_before_starting(host, make_agent, socket):
    host.responses = {LIST: [NOT_RUNNING, NO_KEYS], start(socket): 0}
    socket.parent.mkdir(mode=0o700)
    socket.touch()  # left behind by a dead agent

    make_agent().ensure_running()

    assert not socket.exists()


@pytest.mark.parametrize("start_exit, list_after", [(0, NOT_RUNNING), (1, NO_KEYS)])
def test_reports_an_agent_that_fails_to_start(host, make_agent, socket, start_exit, list_after):
    host.responses = {LIST: [NOT_RUNNING, list_after], start(socket): start_exit}

    with pytest.raises(SandboxError, match="ssh-agent failed to start"):
        make_agent().ensure_running()


# --- keys -------------------------------------------------------------------


def test_replace_keys_empties_the_agent_then_adds_each_key(host, make_agent, socket, tmp_path):
    keys = [tmp_path / "id_ed25519", tmp_path / "deploy"]
    host.responses = {DELETE_ALL: 0, **{("ssh-add", "-q", str(key)): 0 for key in keys}}

    make_agent().replace_keys(keys)

    assert host.commands == [DELETE_ALL, *(("ssh-add", "-q", str(key)) for key in keys)]
    assert all(env is not None and env["SSH_AUTH_SOCK"] == str(socket) for _, env in host.calls)


def test_replace_keys_with_no_keys_leaves_the_agent_empty(host, make_agent):
    host.responses = {DELETE_ALL: 0}

    make_agent().replace_keys([])

    assert host.commands == [DELETE_ALL]


def test_reports_an_agent_that_cannot_be_emptied(host, make_agent, tmp_path):
    host.responses = {DELETE_ALL: 1}

    with pytest.raises(SandboxError, match="could not empty the agent"):
        make_agent().replace_keys([tmp_path / "key"])
    assert host.commands == [DELETE_ALL]


def test_reports_a_key_that_cannot_be_added(host, make_agent, tmp_path):
    host.responses = {DELETE_ALL: 0, ("ssh-add", "-q", str(tmp_path / "bad")): 1}

    with pytest.raises(SandboxError, match="ssh-add failed"):
        make_agent().replace_keys([tmp_path / "bad"])


def test_lists_keys(host, make_agent):
    host.responses = {LIST: "256 SHA256:a key1 (ED25519)\n256 SHA256:b key2 (ED25519)\n"}

    assert make_agent().list_keys() == ["256 SHA256:a key1 (ED25519)", "256 SHA256:b key2 (ED25519)"]


def test_lists_no_keys_for_an_empty_agent(host, make_agent):
    host.responses = {LIST: NO_KEYS}

    assert make_agent().list_keys() == []
