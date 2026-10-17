#!/usr/bin/env bash
# pre-push hook (see ../.pre-commit-config.yaml): mirrors the "mutmut" job in
# .github/workflows/ci.yml - re-running mutation testing and failing only on a
# *new* survivor against mutmut-baseline.txt. Already-triaged survivors are
# expected and fine; a new one means a change just lost test coverage it used
# to have.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# Exits nonzero whenever any mutant survives at all - expected on a healthy
# baseline, so its own exit status is not the failure signal here.
uv run mutmut run || true

current=$(mktemp)
trap 'rm -f "$current"' EXIT
uv run mutmut results | sed -E 's/^[[:space:]]+//' | sort > "$current"

new_survivors=$(comm -13 mutmut-baseline.txt "$current")
if [ -n "$new_survivors" ]; then
  echo "New mutants survived that aren't in mutmut-baseline.txt:" >&2
  echo "$new_survivors" >&2
  echo >&2
  echo "If this is expected, regenerate the baseline locally and commit it:" >&2
  echo "  uv run mutmut run && uv run mutmut results | sed -E 's/^[[:space:]]+//' | sort > mutmut-baseline.txt" >&2
  exit 1
fi
echo "No new mutation survivors."
