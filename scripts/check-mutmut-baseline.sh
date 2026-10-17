#!/usr/bin/env bash
# The single definition of the mutation-testing gate - run directly by the
# "mutmut" job in .github/workflows/ci.yml, and by the pre-push hook in
# .pre-commit-config.yaml. Re-runs mutation testing and fails only on a *new*
# survivor against mutmut-baseline.txt. Already-triaged survivors are expected
# and fine; a new one means a change just lost test coverage it used to have.
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
  # Under GitHub Actions, ::error:: turns this into a workflow annotation on
  # the step, same as CI's own inline version used to produce.
  prefix=""
  [ "${GITHUB_ACTIONS:-}" = "true" ] && prefix="::error::"
  echo "${prefix}New mutants survived that aren't in mutmut-baseline.txt:" >&2
  echo "$new_survivors" >&2
  echo >&2
  echo "If this is expected, regenerate the baseline locally and commit it:" >&2
  echo "  uv run mutmut run && uv run mutmut results | sed -E 's/^[[:space:]]+//' | sort > mutmut-baseline.txt" >&2
  exit 1
fi
echo "No new mutation survivors."
