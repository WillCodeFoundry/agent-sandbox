# Architecture

This document states the rules any implementation of `agent_sandbox` must follow. It describes
required structure and boundaries, not the current file layout for its own sake — if a rule here
and the current code ever disagree, the rule wins and the code is a bug.

For *why* a rule exists, follow the link into `docs/decisions/`. For the *exact* observable
behavior each module must produce, see the corresponding `tests/test_*.py` file — this document
does not restate test assertions.

## Dependency rule

There is exactly one boundary to the outside world (the OS: processes, the filesystem, process
environment, signals, exit codes). It is named `HostPort` (a `Protocol`) with one production
implementation, `Host`. Every other piece of domain/orchestration logic depends on `HostPort`,
never directly on `Host`, **except** the composition root.

The composition root is `cli.main()`. It is the only function in the project allowed to:

- construct a real `Host` (which requires real OS identity, `os.getuid()`);
- read the real process environment to seed a `Config`;
- decide, from real argv, what the rest of the system should do.

The dependency arrow points inward, toward `host.py` and `errors.py`, and only `cli.py` (plus the
one-line `__main__.py` entry point) is allowed to depend on everything:

```
__main__.py
    -> cli.py
        -> config.py            (leaf: no further dependencies)
        -> sbx.py       -> host.py, ssh_agent.py (enum + fingerprint parsing), errors.py
        -> ssh_agent.py -> host.py, errors.py
        -> host.py      -> errors.py
```

`errors.py` is the shared kernel: every module may depend on it, and it depends on nothing.

This is what makes every module except `cli.py`'s composition root testable against a fake world
(see `tests/conftest.py::FakeHost`) instead of a real filesystem and real subprocesses.

## Module responsibilities

| Module | Responsibility | Must NOT |
| --- | --- | --- |
| `errors.py` | Defines `SandboxError`: the single exception type for problems the user can fix, reported without a traceback. | Import anything else in this package. Be raised for a programmer error (bugs raise normally, not through this type). |
| `host.py` | The sole boundary to the OS. Defines `HostPort` (the port — see `docs/decisions/0001-host-hostport-os-boundary.md` for its full method set) and `Host` (the one real adapter). Owns every external-process call, environment read, filesystem-privilege check, and OS/filesystem naming convention this project needs. `run()` must translate a missing executable into a `SandboxError` naming the missing command — every other exception `run()` can raise must stay an ordinary, unconverted exception. | Know about `sbx`, `ssh-agent`, git, or CLI arguments. Be the *second* module in the project that imports `subprocess`, calls `os.execvpe`, or reads `os.environ` directly — no other module may. |
| `config.py` | Holds the project's two tunable defaults (`agent`, `sockets_dir`) as a frozen `Config`, built by `Config.default()`. | Read environment variables, touch the filesystem, or depend on `host.py`. |
| `ssh_agent.py` | Manages one `ssh-agent` process bound to one socket: start-if-not-already-running, replace all held keys, list keys/fingerprints. Defines `SshAddExitCode`. | Know about `sbx`, about git, or about `cli.Arguments`. Decide what socket path to use (it is always handed one). Call `subprocess`/`os` directly — only through the `HostPort` it is given. Re-check that its socket's directory is private — that is the caller's precondition (see `docs/decisions/0002-ensure-private-dir-runs-before-any-socket-probe.md`). |
| `sbx.py` | A thin wrapper around `sbx` subcommands scoped to one sandbox name — existence/creation, syncing its GitHub-token secret and git config, and reading back its forwarded key fingerprints — plus building the environment every such call must carry. | Encode what any git config key *means* (identity vs. signing vs. anything else) — it only ever exposes the generic `set_git_config(name, key, value)`. Decide product policy (what to do when a key or token is absent — that is `cli.py`'s job). |
| `cli.py` | The composition root and the only module holding product policy: argument parsing and validation, path-safety rules, and the orchestration that reconciles one sandbox to match the given arguments, calling its `ensure_*` helpers in order. Builds the human-readable launch description. `main()` constructs the one real `Host` and execs into `sbx run`. | Call `subprocess`/`os` directly anywhere — always through `host`/`sbx`/`ssh_agent` objects it built or was given. Duplicate a filesystem/permission check that belongs on `HostPort`. |
| `__main__.py` | Entry point: delegate to `cli.main()` and exit with its return code. | Contain any logic beyond that delegation. |

## Forbidden

The following would violate this architecture if introduced, regardless of whether tests happen
to pass:

- Importing `subprocess`, `os.execvpe`, or reading `os.environ` in any module other than
  `host.py`.
- A test double for `HostPort` (`FakeHost` or any replacement) that reimplements any of `Host`'s
  filesystem-privilege-check or naming-convention methods instead of inheriting them from the real
  `Host`. The only methods a fake may override are the process-facing trio: `run`, `exec`,
  `environ`. See `docs/decisions/0001-host-hostport-os-boundary.md` for the full method list.
- `ssh_agent.py` or `sbx.py` importing `argparse`, `sys`, or anything from `cli.py`.
- Referring to the SSH agent as bare "agent" in an identifier or docstring (see Naming below).
- Constructing a real `Host`, or calling `os.getuid()`, anywhere outside `cli.main()`.
- Any code path that can reach a sandbox's `ssh-agent` socket (probing it, starting an agent on
  it, running `ssh-add` against it) before `host.ensure_private_dir(socket.parent)` has run for
  that process, for that socket's parent directory. See
  `docs/decisions/0002-ensure-private-dir-runs-before-any-socket-probe.md`.
- Giving `Sbx` or `SshAgent` a method that embeds CLI-level policy (e.g. "if no key, do X") rather
  than a plain mechanism that `cli.py` decides how to use.

## Naming conventions

- **"ssh_agent" / "ssh-agent" vs. "agent".** `ssh_agent.py`'s `SshAgent` class, and the phrase
  "ssh-agent", always refer to the real OpenSSH `ssh-agent` process this project starts and
  manages. The bare word "agent" alone must never be used as an identifier or docstring noun for
  it. Reserve bare "agent" for the *coding* agent being launched inside the sandbox (`config.AGENT`,
  the thing `sbx create`/`sbx run` actually runs). This is not stylistic: an earlier revision of
  this project had a local literally named `agent` that meant the ssh-agent wrapper, which reads as
  "the coding agent" to anyone skimming the file — a real naming collision, not a hypothetical one.
  It was renamed to `ssh_agent` throughout, and a later cleanup caught and fixed a docstring that
  still said "the agent's socket" for the same reason. Grepping for a bare `agent` identifier that
  means the ssh-agent is a sign something was reverted by accident.
- **`<Noun>Port` vs. the bare noun.** A `Protocol` naming an architectural boundary is suffixed
  `Port` (`HostPort`); the one concrete, real-world adapter implementing it is the bare noun
  (`Host`) — never an implementation-flavored name like `SubprocessHost`. If a second boundary is
  ever introduced, name it the same way (`FooPort` / `Foo`). See
  `docs/decisions/0001-host-hostport-os-boundary.md`.
- **`ensure_*` functions never return a bool.** Every function named `ensure_*`
  (`ensure_dir_exists`, `ensure_file_exists`, `ensure_private_dir`, `ensure_valid_args`,
  `ensure_ssh_agent_running`, `ensure_sandbox_present`, `ensure_forwarded_keys`,
  `ensure_paths_safe`) either returns `None` or raises `SandboxError`. A caller never needs to
  check a return value to know whether the condition holds — if the call returned, it holds.
- **`sbx` vs. `Sbx` vs. `ssh_key`.** `sbx` (lowercase) is always the external Docker Sandboxes
  product/CLI this project shells out to. `Sbx` (capitalized) is this project's own wrapper class
  around it. `ssh_key`/`--ssh-key` is always the user's private key path, never the agent itself.
  These are visually close by necessity (the wrapper is named after the thing it wraps); keep
  case and underscores as the only disambiguator and do not introduce a fourth near-homonym.
