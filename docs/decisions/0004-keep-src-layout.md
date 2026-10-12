# 4. Keep the src/ package layout after prototyping a flat layout

## Status

Accepted. An alternative was prototyped and not adopted.

## Context

A flat layout — moving `agent_sandbox/` to the repository root instead of nesting it under
`src/` — was prototyped on a side branch that was never merged into `main`. That branch's stated
rationale for dropping `src/`: the usual benefit of a `src/` layout is forcing imports (including
`pytest`'s own test collection) through the installed package rather than an accidentally
importable local copy sitting next to the interpreter's working directory; for a single-package
CLI tool already run through `uv`, which performs an editable install via `uv sync` before
anything runs, that protection is largely already provided by the workflow itself, so the extra
`src/` nesting isn't buying much. Making that change also required telling setuptools' package
discovery to include only `agent_sandbox*`, so it would not also try to package the top-level
`tests/` directory (which has its own `__init__.py`).

That branch was abandoned without a recorded reason; the project's history simply moved on from
it back to `main`, which kept `src/`. No commit message in this repository's history states a
rationale for *keeping* `src/` — only the counter-argument for dropping it exists, on a branch
that was itself not acted on. The rationale below for keeping it is this document's own
reasoning about the tradeoff, not a recovered historical justification.

## Decision

Keep the `src/` layout. `pyproject.toml`'s `[tool.setuptools.packages.find]` with `where =
["src"]` is the enforced mechanism: the installable package lives at `src/agent_sandbox/`, and
`tests/` lives outside it, at the repository root, as its own top-level directory with its own
`tests/__init__.py` — never nested inside the installable package.

## Consequences

- `pytest`, `mypy`, or anything else that imports `agent_sandbox` can only ever resolve it through
  the editable install setuptools creates (`uv sync`), never by accident through a stray
  current-working-directory import — the exact protection a `src/` layout is known for, kept
  rather than traded away for one fewer directory level.
- `tests/` staying outside the installable package means `[tool.setuptools.packages.find] where =
  ["src"]` needs no exclusion rule for it — contrast the abandoned flat-layout branch, which had to
  add one (`include = ["agent_sandbox*"]`) specifically because a flat `tests/__init__.py` next to
  a flat `agent_sandbox/` would otherwise have been picked up as a second package.
- Cost accepted: one extra directory level (`src/agent_sandbox/` instead of `agent_sandbox/`) for
  what is a single-package project, which the abandoned branch judged not worth it. A future
  contributor re-proposing a flat layout should know this was already tried once and not merged;
  if it is tried again, the reason should be recorded here (as a new, superseding decision file),
  not left implicit a second time.
