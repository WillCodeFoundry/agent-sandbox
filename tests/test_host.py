import os

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
