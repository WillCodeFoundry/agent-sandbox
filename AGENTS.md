# agent_sandbox

`agent_sandbox` is a small Python CLI that launches a Docker Sandbox (`sbx`) pre-wired with a
dedicated `ssh-agent`, a GitHub token, a git identity, and SSH commit signing, reconciled to match
its arguments on every launch.

- For the architectural rules that any implementation of this project must satisfy — module
  boundaries, dependency direction, naming conventions — see `docs/architecture.md`.
- For the rationale behind specific, non-obvious design choices — written as Nygard-style ADRs —
  see `docs/decisions/`.
- For the CLI's user-facing contract (flags, path-safety rules, `sbx` caveats) see `README.md`.
- For the exact, authoritative behavior of every rule mentioned here, see `tests/`.
- To run the verification suite (tests, mypy, ruff) before committing, see `README.md`'s
  "Development" section.
