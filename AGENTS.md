# agent_sandbox

`agent_sandbox` is a small Python CLI that launches a Docker Sandbox (`sbx`) pre-wired for a
coding agent: a dedicated per-sandbox `ssh-agent` carrying exactly one key, a GitHub token secret,
a git identity, and SSH-based commit signing, all kept in sync with the arguments given on every
launch. It exists so that re-running it against an already-existing sandbox *reconciles* that
sandbox's credentials and config to match the current arguments, rather than letting an earlier
launch's key, token, or identity linger silently.

- For the architectural rules that any implementation of this project must satisfy — module
  boundaries, dependency direction, naming conventions — see `docs/architecture.md`.
- For the rationale behind specific, non-obvious design choices — written as Nygard-style ADRs —
  see `docs/decisions/`.
- For the CLI's user-facing contract (flags, path-safety rules, `sbx` caveats) see `README.md`.
- For the exact, authoritative behavior of every rule mentioned here, see `tests/`.
