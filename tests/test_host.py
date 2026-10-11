import os
from pathlib import Path

import pytest

from agent_sandbox.errors import SandboxError
from agent_sandbox.host import Host


@pytest.fixture
def host() -> Host:
    return Host()


# --- ensure_private_dir ------------------------------------------------------


def test_private_dir_is_created_for_the_owner_only(host, tmp_path):
    host.ensure_private_dir(tmp_path / "sockets", os.getuid())

    assert (tmp_path / "sockets").stat().st_mode & 0o777 == 0o700


def test_private_dir_tightens_existing_permissions(host, tmp_path):
    (tmp_path / "sockets").mkdir(mode=0o755)

    host.ensure_private_dir(tmp_path / "sockets", os.getuid())

    assert (tmp_path / "sockets").stat().st_mode & 0o777 == 0o700


def test_private_dir_symlink_is_refused_and_target_untouched(host, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir(mode=0o755)
    (tmp_path / "sockets").symlink_to(target)

    with pytest.raises(SandboxError, match="not a directory owned by you"):
        host.ensure_private_dir(tmp_path / "sockets", os.getuid())
    assert target.stat().st_mode & 0o777 == 0o755


def test_private_dir_that_is_a_file_is_refused(host, tmp_path):
    (tmp_path / "sockets").touch()

    with pytest.raises(SandboxError, match="not a directory owned by you"):
        host.ensure_private_dir(tmp_path / "sockets", os.getuid())


def test_private_dir_that_is_a_dangling_symlink_is_refused(host, tmp_path):
    (tmp_path / "sockets").symlink_to(tmp_path / "missing")

    with pytest.raises(SandboxError, match="not a directory owned by you"):
        host.ensure_private_dir(tmp_path / "sockets", os.getuid())


# --- remove_file --------------------------------------------------------------


def test_remove_file_deletes_an_existing_file(host, tmp_path):
    target = tmp_path / "stale.sock"
    target.touch()

    host.remove_file(target)

    assert not target.exists()


def test_remove_file_is_a_noop_when_nothing_is_there(host, tmp_path):
    host.remove_file(tmp_path / "missing")


# --- socket_path --------------------------------------------------------------


def test_socket_path_is_private_to_the_uid_and_named_for_the_sandbox(host):
    assert host.socket_path(Path("/tmp/sbx-agents"), "myproj-dev", 501) == Path("/tmp/sbx-agents-501/myproj-dev.sock")


# --- public_key_path -----------------------------------------------------------


def test_public_key_path_appends_pub(host):
    assert host.public_key_path(Path("/keys/id_ed25519")) == Path("/keys/id_ed25519.pub")


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


# --- contains / is_nested_dir ----------------------------------------------------


def test_contains_a_path_inside_the_folder(host):
    assert host.contains(Path("/a"), Path("/a/b"))


def test_contains_the_folder_itself(host):
    assert host.contains(Path("/a"), Path("/a"))


def test_contains_rejects_an_unrelated_path(host):
    assert not host.contains(Path("/a"), Path("/b"))


def test_is_nested_dir_when_one_is_nested_in_the_other(host):
    assert host.is_nested_dir(Path("/a"), Path("/a/b"))
    assert host.is_nested_dir(Path("/a/b"), Path("/a"))


def test_is_nested_dir_rejects_sibling_paths(host):
    assert not host.is_nested_dir(Path("/a/one"), Path("/a/two"))
