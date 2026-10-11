# 2. ensure_private_dir runs unconditionally, first, before anything touches the agent socket

## Status

Accepted.

## Context

A sandbox's `ssh-agent` listens on a Unix socket under a directory in `/tmp`
(`config.SOCKETS_DIR`), a location every user on the host shares. Before this process trusts or
creates a socket there, it must own that directory exclusively: it has to exist, be a real
directory (not a file, and not a symlink pointing at one), and be owned by this process's uid,
with mode `0o700` (`Host.ensure_private_dir`). If that check is skipped, or runs too late, another
local user could have pre-created the directory (or a symlink inside it) before this process
does. Anything this process then does against a socket inside it — probing whether an agent is
listening, or trusting the key fingerprints it reports — could be talking to an attacker's agent
instead of ours.

Earlier in this project's history, this check lived inside `SshAgent.ensure_running()` itself,
immediately before its first probe of the socket — a comment at that call site read "Check the
directory before talking to anything in it." A later refactor moved the actual
`host.ensure_private_dir(socket.parent)` call out of `SshAgent` entirely and into `cli.main()`,
as the first statement inside `main()`'s `try` block — ahead of `ensure_valid_args(args, host)`
and ahead of `prepare_sbx_execution(...)`, which is what eventually calls into
`SshAgent.ensure_running()`. `SshAgent.ensure_running()`'s docstring now states the precondition
("The caller must have already made `socket`'s directory private to this user") instead of
re-checking it itself.

## Decision

`host.ensure_private_dir(socket.parent)` must be the first thing `cli.main()` does inside its
`try` block, unconditionally — before argument validation (`ensure_valid_args`) and before
anything that could reach the socket (`prepare_sbx_execution` → `ensure_ssh_agent_running` →
`SshAgent.ensure_running`). `SshAgent` does not perform this check itself; it documents it as a
precondition the caller must already have satisfied. There is exactly one enforcement point for
this invariant in the whole codebase.

## Consequences

- The invariant is visible at a single call site, with an inline comment explaining it ("A socket
  in a directory someone else controls could be their agent, not ours"), rather than re-checked
  (or, worse, inconsistently re-checked) in every module that might eventually touch the socket.
- Because the check is cheap, pure (no subprocess), and independent of the CLI arguments given,
  running it unconditionally and first costs nothing and needs no special-casing for "what if the
  arguments turn out to be invalid" — it must hold regardless of what the rest of the launch does,
  so it runs before anything that depends on the arguments being valid.
- Cost accepted: `cli.main()` itself has no unit tests — every `agent_sandbox.cli.x_main__mutmut_*`
  entry in `mutmut-baseline.txt` is marked "no tests," an accepted, already-triaged gap, not a
  regression. A future edit to `main()` that reorders or drops this call would not be caught by
  the automated test suite; it can only be caught by re-reading `main()` against this document and
  `docs/architecture.md`'s forbidden list. `SshAgent` trusting the precondition, rather than
  re-checking it, means `tests/test_ssh_agent.py` — which constructs `SshAgent` directly against a
  `FakeHost` — cannot detect a caller that forgot to call `ensure_private_dir` first; it only
  exercises `SshAgent` in isolation, never `main()`'s sequencing.
- Cost accepted: any future second entry point that reaches a sandbox's socket must itself
  remember to call `host.ensure_private_dir(socket.parent)` first; nothing enforces this
  automatically for a caller that isn't `cli.main()`.
