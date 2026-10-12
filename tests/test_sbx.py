from pathlib import Path

import pytest

from agent_sandbox.errors import SandboxError
from agent_sandbox.sbx import Sbx

SANDBOX_ENV = {"PATH": "/bin", "SSH_AUTH_SOCK": "/sockets/n.sock"}
EXISTS = ("sbx", "exec", "n", "true")
LIST = ("sbx", "exec", "n", "ssh-add", "-l")
CREATE = ("sbx", "create", "--clone", "--name", "n", "claude", "/w", "/ctx:ro")
SET_NAME = ("sbx", "exec", "n", "git", "config", "--global", "user.name", "Dev")


@pytest.fixture
def sbx(host):
    return Sbx(host, SANDBOX_ENV)


def test_every_call_carries_the_sandboxs_environment(host, sbx):
    host.responses = {EXISTS: 0, CREATE: 0, LIST: 1}

    sbx.exists("n")
    sbx.create("n", "claude", Path("/w"), Path("/ctx"))
    sbx.agent_fingerprints("n")

    assert [env for _, env in host.calls] == [SANDBOX_ENV] * 3


@pytest.mark.parametrize("exit_code, exists", [(0, True), (1, False)])
def test_exists(host, sbx, exit_code, exists):
    host.responses = {EXISTS: exit_code}

    assert sbx.exists("n") is exists


def test_create_clones_the_workspace_and_mounts_context_read_only(host, sbx):
    host.responses = {CREATE: 0}

    sbx.create("n", "claude", Path("/w"), Path("/ctx"))

    assert host.commands == [CREATE]


def test_create_failure_is_reported(host, sbx):
    host.responses = {CREATE: 1}

    with pytest.raises(SandboxError, match="sbx create failed"):
        sbx.create("n", "claude", Path("/w"), Path("/ctx"))


def test_set_github_token(host, sbx):
    set_token = ("sbx", "secret", "set", "github", "--sandbox", "n", "-t", "ghp_abc123")
    host.responses = {set_token: 0}

    sbx.set_github_token("n", "ghp_abc123")

    assert host.commands == [set_token]


def test_set_github_token_failure_is_reported(host, sbx):
    set_token = ("sbx", "secret", "set", "github", "--sandbox", "n", "-t", "ghp_abc123")
    host.responses = {set_token: 1}

    with pytest.raises(SandboxError, match="sbx secret set failed"):
        sbx.set_github_token("n", "ghp_abc123")


def test_clear_github_token(host, sbx):
    clear_token = ("sbx", "secret", "rm", "github", "--sandbox", "n", "-f")
    host.responses = {clear_token: 0}

    sbx.clear_github_token("n")

    assert host.commands == [clear_token]


def test_clear_github_token_failure_is_reported(host, sbx):
    clear_token = ("sbx", "secret", "rm", "github", "--sandbox", "n", "-f")
    host.responses = {clear_token: 1}

    with pytest.raises(SandboxError, match="sbx secret rm failed"):
        sbx.clear_github_token("n")


def test_set_git_config(host, sbx):
    host.responses = {SET_NAME: 0}

    sbx.set_git_config("n", "user.name", "Dev")

    assert host.commands == [SET_NAME]


def test_set_git_config_failure_is_reported(host, sbx):
    host.responses = {SET_NAME: 1}

    with pytest.raises(SandboxError, match="sbx exec git config failed"):
        sbx.set_git_config("n", "user.name", "Dev")


def test_agent_fingerprints_of_the_sandboxs_keys(host, sbx):
    host.responses = {LIST: "256 SHA256:aaa key-a (ED25519)\n3072 SHA256:bbb key-b (RSA)\n"}

    assert sbx.agent_fingerprints("n") == {"SHA256:aaa", "SHA256:bbb"}


def test_agent_fingerprints_of_an_empty_agent(host, sbx):
    host.responses = {LIST: 1}

    assert sbx.agent_fingerprints("n") == set()


def test_agent_fingerprints_when_no_agent_reaches_the_sandbox(host, sbx):
    host.responses = {LIST: 2}

    assert sbx.agent_fingerprints("n") is None


def test_agent_fingerprints_failure_is_reported(host, sbx):
    host.responses = {LIST: 125}

    with pytest.raises(SandboxError, match="could not list the sandbox's keys"):
        sbx.agent_fingerprints("n")


def test_run_args_attach_by_name_and_pass_agent_args(sbx):
    assert sbx.run_args("n", ["--continue"]) == ("sbx", "run", "--name", "n", "--", "--continue")


def test_run_args_without_agent_args(sbx):
    assert sbx.run_args("n", []) == ("sbx", "run", "--name", "n")


def test_env_carries_the_sandboxs_socket_and_drops_the_personal_agent_pid():
    assert Sbx.env({"PATH": "/bin", "SSH_AGENT_PID": "42"}, Path("/sockets/n.sock")) == {
        "PATH": "/bin",
        "SSH_AUTH_SOCK": "/sockets/n.sock",
    }
