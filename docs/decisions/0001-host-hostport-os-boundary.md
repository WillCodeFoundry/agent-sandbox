# 1. Host/HostPort as the sole OS-boundary abstraction; FakeHost subclasses Host

## Status

Accepted.

## Context

Every other module needs to run external commands (`sbx`, `ssh-agent`, `ssh-add`), replace the
current process (`os.execvpe`, to hand off the terminal/signals/exit code to `sbx run`), read the
process environment, and perform filesystem-privilege checks (does this directory exist, is it
ours, is it a symlink) and path-naming conventions (where does a key's `.pub` file live; where
does a sandbox's socket live).

An earlier revision of this project scattered these directly: a bare module-level
`ensure_private_dir(path, uid)` function in `ssh_agent.py` that called `os.lstat`/`os.chmod`
itself, a bare `os.execvpe(...)` call inline in `cli.main()`, and a `Protocol` named `Host` whose
one real implementation was named `SubprocessHost` — a name that read backwards once that real
implementation grew to own more than subprocess calls (filesystem checks, path conventions). None
of this was independently testable without either hitting the real filesystem/process table, or
duplicating the check's logic in a hand-rolled fake that could silently drift from what the real
one actually enforced.

## Decision

Define a single `Protocol`, `HostPort`, covering every external-world capability this project
needs: `run`, `exec`, `environ`, `ensure_private_dir`, `reset_socket`, `socket_path`,
`ensure_dir_exists`, `ensure_file_exists`, `public_key_path`. Define exactly one production
implementation, `Host` — an ordinary class, not a `Protocol`, constructed with the OS uid it acts
as. Every other module (`ssh_agent.py`, `sbx.py`, `cli.py`'s helpers) takes a `HostPort` and never
imports or names `Host` directly; only `cli.main()`, the composition root, constructs
`Host(os.getuid())`.

The test double, `FakeHost` (`tests/conftest.py`), **subclasses the real `Host`** rather than
implementing `HostPort` from scratch, and overrides only the three process-facing methods that
would otherwise touch the real OS: `run`, `exec`, `environ`. Every other `HostPort` method —
every filesystem-privilege check, every path-naming convention — runs for real in tests, against
`pytest`'s `tmp_path`.

## Consequences

- The filesystem-privilege logic (ownership, symlink, and mode checks in `ensure_private_dir`) is
  implemented and tested exactly once, in `tests/test_host.py`, against the real filesystem. Every
  other test that exercises code built on top of it gets that logic for real, for free — there is
  no second, parallel "fake" implementation of a security check that could drift from what the
  real one enforces.
- `FakeHost.run()` being a simple `command -> canned response` table (see its docstring) is what
  lets `tests/test_cli.py`, `tests/test_sbx.py`, and `tests/test_ssh_agent.py` assert exact
  subprocess argv, ordering, and environments without a real `sbx`/`ssh-agent`/`ssh-add` installed.
- Cost accepted: `FakeHost` is coupled to `Host.__init__`'s signature (a single `uid: int`) and to
  the real behavior of every method it does not override. Adding a new OS-touching method to
  `Host` without adding it to `HostPort` first, or without deciding whether `FakeHost` needs to
  override it, is a trap — `FakeHost` would silently inherit a real, OS-touching implementation in
  tests. Any new `Host` method must go on `HostPort` first, and a contributor must explicitly
  decide whether it belongs with the faked process-facing trio or with the filesystem checks that
  run for real.
- Cost accepted: because `Host` takes `uid` at construction rather than per call, simulating "a
  directory owned by someone else" requires constructing a *second* `Host`/`FakeHost` with a
  different uid, not varying an argument on one instance (see
  `tests/test_host.py::test_private_dir_refuses_a_directory_owned_by_someone_else`).
