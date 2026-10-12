# 3. Gate CI on mutation-testing regressions against a baseline, not a raw survivor count

## Status

Accepted.

## Context

Raw mutmut survivor count is not a meaningful merge gate for this project. `cli.parse_args` in
particular is `argparse`-heavy and has many permanently unkillable mutants in things like help
text and error-message wording that no reasonable test should assert character-for-character;
some mutants are also simply equivalent to the original code. An initial CI integration ran
mutmut with `continue-on-error: true` at the whole-job level — informational only, triaged by a
human, never failing the build.

That same initial mutation-testing pass was still used to find and close three real test gaps
before any baseline was captured:

- `execution_description`'s notes were only ever asserted present, never asserted *absent* for
  the other branch, so a mutation collapsing a ternary to always the same branch (e.g. always
  showing the "holds no key" warning, even with a key loaded) went uncaught.
- `SshAgent.list_keys`'s `NO_KEYS`-path test happened to also have empty `stdout`, so a mutation
  making the method return `stdout.splitlines()` unconditionally — ignoring the exit code
  entirely — still passed.
- The "`--ssh-key` given twice" test asserted `SystemExit` but never the error message, so
  `parser.error(None)` would have survived undetected.

Only after those three gaps were closed was the remaining survivor backlog (mostly permanently
unkillable `argparse` text) captured as a committed baseline file, `mutmut-baseline.txt` — the
sorted output of `mutmut results`.

## Decision

CI's mutmut job runs `mutmut run` with `continue-on-error: true` scoped to *that one step* (so a
flaky mutant worker can't mask a real failure in the step that follows it), then diffs the fresh,
sorted `mutmut results` output against the committed `mutmut-baseline.txt` with `comm -13`, and
fails the build only when that diff is non-empty — i.e., only when a mutant survives now that
wasn't already an accepted, triaged survivor. An expected new survivor (e.g. more unkillable help
text) is accepted by regenerating and committing a new baseline locally:

```
uv run mutmut run && uv run mutmut results | sed -E 's/^[[:space:]]+//' | sort > mutmut-baseline.txt
```

## Consequences

- A pull request that weakens an existing test — for example, removing a negative assertion like
  the ones added to close the gaps above — fails CI even though `pytest`/`mypy`/`ruff` all stay
  green, because the mutant that assertion used to kill resurfaces as a new, un-triaged survivor
  in the `comm -13` diff.
- The baseline absorbs permanently-unkillable mutants once; they never need re-triaging on every
  subsequent PR.
- Cost accepted: the baseline is a committed artifact that must be regenerated and reviewed
  whenever a legitimately-untestable mutant is introduced. A reviewer must distinguish "this new
  baseline entry is genuinely unkillable" from "this PR quietly weakened a test" by reading the
  PR's diff of `mutmut-baseline.txt` — the mechanism itself cannot tell the two apart; only a
  human reviewing *which* mutant newly appears can.
- Cost accepted: mutmut must still run to completion in CI even though it no longer blocks on raw
  count — it is the slowest job, and its wall-clock cost scales with the full test suite's runtime
  multiplied by the mutant count.
