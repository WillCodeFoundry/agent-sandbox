#!/usr/bin/env bash
# PreToolUse hook (see ../settings.json): runs before any Bash call containing
# "git commit", checks it, and blocks it (exit 2) with a specific reason if
# something is wrong - never fixes anything silently, so the failure message
# is always the thing that tells Claude what to do next.
#
# Kept identical across repos; change it everywhere at once.
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

shopt -s nocasematch
case "$cmd" in
  *"Co-Authored-By"*)
    block "the commit command contains a Co-Authored-By trailer." \
      "Remove the Co-Authored-By line from the commit message, then retry the commit."
    ;;
esac
shopt -u nocasematch

# Flags are checked on the command without its message: drop any heredoc body and
# quoted strings, so a message that merely mentions a flag is not mistaken for it.
flags=${cmd%%<<*}
flags=$(printf '%s' "$flags" | sed -E "s/'[^']*'//g; s/\"[^\"]*\"//g")

case "$flags" in
  *"--no-verify"*)
    block "the commit command uses --no-verify." \
      "Never skip hooks. Fix whatever the hooks report, then retry without --no-verify."
    ;;
  *"--no-gpg-sign"*)
    block "the commit command disables signing (--no-gpg-sign)." \
      "Commits must be signed. Remove --no-gpg-sign and retry."
    ;;
esac

case "$flags" in
  *" -S"* | *"--gpg-sign"*) ;;
  *)
    if [ "$(git config --get commit.gpgsign)" != "true" ]; then
      block "the commit would not be signed." \
        "Add -S to the git commit command (commit.gpgsign is not enabled), then retry."
    fi
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

# Cheapest/fastest checks first, so a trivial style or type issue fails fast
# instead of waiting on the full test run.
run_check "ruff format --check" uv run ruff format --check .
run_check "ruff check" uv run ruff check .
run_check "mypy" uv run mypy
run_check "pytest" uv run pytest

exit 0
