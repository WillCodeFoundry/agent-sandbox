import os
from pathlib import Path

import pytest

from agent_sandbox.errors import SandboxError
from agent_sandbox.host import Host


@pytest.fixture
def host() -> Host:
    return Host(os.getuid())


# --- environ ------------------------------------------------------------------


def test_environ_is_the_processs_own_environment(host):
    assert host.environ() is os.environ


# --- ensure_private_dir ------------------------------------------------------


def test_private_dir_is_created_for_the_owner_only(host, tmp_path):
    host.ensure_private_dir(tmp_path / "sockets")

    assert (tmp_path / "sockets").stat().st_mode & 0o777 == 0o700


def test_private_dir_tightens_existing_permissions(host, tmp_path):
    (tmp_path / "sockets").mkdir(mode=0o755)

    host.ensure_private_dir(tmp_path / "sockets")

    assert (tmp_path / "sockets").stat().st_mode & 0o777 == 0o700


def test_private_dir_refuses_a_directory_owned_by_someone_else(tmp_path):
    host = Host(os.getuid() + 1)

    with pytest.raises(SandboxError, match="not a directory owned by you"):
        host.ensure_private_dir(tmp_path / "sockets")


def test_private_dir_symlink_is_refused_and_target_untouched(host, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir(mode=0o755)
    (tmp_path / "sockets").symlink_to(target)

    with pytest.raises(SandboxError, match="not a directory owned by you"):
        host.ensure_private_dir(tmp_path / "sockets")
    assert target.stat().st_mode & 0o777 == 0o755


def test_private_dir_that_is_a_file_is_refused(host, tmp_path):
    (tmp_path / "sockets").touch()

    with pytest.raises(SandboxError, match="not a directory owned by you"):
        host.ensure_private_dir(tmp_path / "sockets")


def test_private_dir_that_is_a_dangling_symlink_is_refused(host, tmp_path):
    (tmp_path / "sockets").symlink_to(tmp_path / "missing")

    with pytest.raises(SandboxError, match="not a directory owned by you"):
        host.ensure_private_dir(tmp_path / "sockets")


# --- reset_socket --------------------------------------------------------------


def test_reset_socket_deletes_an_existing_file(host, tmp_path):
    socket = tmp_path / "sockets" / "dev.sock"
    socket.parent.mkdir(mode=0o700)
    socket.touch()

    host.reset_socket(socket)

    assert not socket.exists()


def test_reset_socket_is_a_noop_when_nothing_is_there(host, tmp_path):
    host.reset_socket(tmp_path / "sockets" / "dev.sock")


def test_reset_socket_also_makes_the_parent_dir_private(host, tmp_path):
    socket = tmp_path / "sockets" / "dev.sock"

    host.reset_socket(socket)

    assert socket.parent.stat().st_mode & 0o777 == 0o700


def test_reset_socket_refuses_a_parent_dir_owned_by_someone_else(tmp_path):
    host = Host(os.getuid() + 1)
    socket = tmp_path / "sockets" / "dev.sock"

    with pytest.raises(SandboxError, match="not a directory owned by you"):
        host.reset_socket(socket)


# --- socket_path --------------------------------------------------------------


def test_socket_path_is_private_to_the_uid_and_named_for_the_sandbox():
    host = Host(501)

    assert host.socket_path(Path("/tmp/sbx-agents"), "myproj-dev") == Path("/tmp/sbx-agents-501/myproj-dev.sock")


# --- ensure_dir_exists / ensure_file_exists -------------------------------------


def test_ensure_dir_exists_accepts_a_directory(host, tmp_path):
    host.ensure_dir_exists(tmp_path, "workspace")


def test_ensure_dir_exists_refuses_a_missing_path(host, tmp_path):
    with pytest.raises(SandboxError, match="is not a directory"):
        host.ensure_dir_exists(tmp_path / "missing", "workspace")


def test_ensure_file_exists_accepts_a_file(host, tmp_path):
    target = tmp_path / "key"
    target.touch()

    host.ensure_file_exists(target, "ssh key")


def test_ensure_file_exists_refuses_a_directory(host, tmp_path):
    with pytest.raises(SandboxError, match="is not a file"):
        host.ensure_file_exists(tmp_path, "ssh key")


# --- public_key_path -----------------------------------------------------------


def test_public_key_path_appends_pub(host):
    assert host.public_key_path(Path("/home/dev/.ssh/id_ed25519")) == Path("/home/dev/.ssh/id_ed25519.pub")
