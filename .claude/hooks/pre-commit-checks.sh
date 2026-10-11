#!/usr/bin/env bash
# PreToolUse hook (see ../settings.json): runs before any Bash call containing
# "git commit", checks it, and blocks it (exit 2) with a specific reason if
# something is wrong - never fixes anything silently, so the failure message
# is always the thing that tells Claude what to do next.
set -u

if ! command -v jq >/dev/null 2>&1; then
  echo "pre-commit-checks.sh: jq not found, skipping checks" >&2
  exit 0
fi

cmd=$(jq -r '.tool_input.command // empty')
case "$cmd" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

block() {
  echo "BLOCKED: $1" >&2
  echo >&2
  echo "$2" >&2
  exit 2
}

case "$cmd" in
  *"Co-Authored-By"*)
    block "the commit command contains a Co-Authored-By trailer." \
      "Remove the Co-Authored-By line from the commit message, then retry the commit."
    ;;
esac

run_check() {
  local label="$1"
  shift
  echo "pre-commit-checks.sh: running $label" >&2
  if ! out=$("$@" 2>&1); then
    block "$label failed." "$out"
  fi
}

run_check "pytest" uv run pytest -q
run_check "mypy" uv run mypy
run_check "ruff check" uv run ruff check .
run_check "ruff format --check" uv run ruff format --check .

exit 0
