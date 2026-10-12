# agent-sandbox

Launch a [Docker Sandboxes](https://docs.docker.com/ai/sandboxes/) (`sbx`) agent with its
own SSH agent and a read-only context directory. Each launch:

1. refuses path layouts that would undo the sandbox's protections (see below);
2. starts (or reuses) an `ssh-agent` dedicated to the sandbox, and makes the key you pass
   the only key it holds;
3. creates the sandbox if needed, then checks from inside it that it sees exactly that
   key, so your personal agent can't have been forwarded;
4. runs `sbx run` with only that agent's socket visible, mounting the context directory
   read-only.

## Install

```console
$ uv sync
```

## Use

```console
$ uv run agent_sandbox --name myproj-dev --context ./agents/dev --ssh-key ~/.ssh/dev_ed25519 ~/src/myproj
$ uv run agent_sandbox --name myproj-dev --context ./agents/dev --ssh-key ~/.ssh/dev_ed25519 ~/src/myproj -- --continue
```

| Argument | Meaning |
| --- | --- |
| `WORKSPACE` | Project directory the agent works in |
| `--name` | Sandbox name. The same name re-attaches to the same sandbox. |
| `--context DIR` | Directory mounted read-only into the sandbox |
| `--ssh-key FILE` | Private key for the sandbox's SSH agent and for signing commits; omit for none |
| `--github-token-file FILE` | File holding a GitHub token to give the sandbox (enables `gh`, e.g. to open PRs) |
| `--git-name NAME` | git `user.name` to set inside the sandbox; requires `--git-email` |
| `--git-email EMAIL` | git `user.email` to set inside the sandbox; requires `--git-name` |
| `-- ARGS` | Passed to the agent |

A sandbox's mounts are fixed when it is created: re-using a `--name` with a different
workspace or `--context` re-attaches to the existing sandbox with its original mounts.
Remove it first (`sbx rm NAME`) to change them.

The sandbox's SSH agent listens on `/tmp/sbx-agents-<uid>/<name>.sock`. On every launch it
is emptied and given exactly `--ssh-key` (or nothing, if omitted), so a key from an earlier
launch never lingers. The agent (`claude`) and the sockets directory are set in
`src/agent_sandbox/config.py`.

The sandbox's `github` secret is kept in sync with `--github-token-file` on every launch,
the same way the ssh-agent's key is kept in sync with `--ssh-key`: given, it's set to the
file's contents (`sbx secret set github --sandbox NAME -t TOKEN`), so this is also how an
existing sandbox's token gets rotated; omitted, it's cleared (`sbx secret rm github
--sandbox NAME -f`), so a token from an earlier launch never lingers. The token is scoped
to this one sandbox only, so different sandboxes can use different tokens.

The sandbox's global git identity (`git config --global user.name`/`user.email`) is set
from `--git-name`/`--git-email` on every launch, the same way. Omit both and they're set
to empty strings on purpose: git treats an empty identity as unset and refuses to commit
(`*** Please tell me who you are.`), so a forgotten `--git-name`/`--git-email` fails loudly
at commit time inside the sandbox rather than silently committing as the wrong person.

Commits are always configured to be SSH-signed (`gpg.format ssh`, `commit.gpgsign true`),
using `--ssh-key`'s matching `.pub` file (read by naming convention: `KEY` pairs with
`KEY.pub`) as `user.signingkey`. The private key itself never needs to be readable inside
the sandbox — signing happens through the forwarded agent, the same way authentication
does. Without `--ssh-key`, `user.signingkey` is blanked on purpose: with no signing key,
git refuses to commit (`error: user.signingkey needs to be set for ssh signing`), so a
sandbox without a key fails loudly at commit time instead of committing unsigned.

## Path rules

The launch is refused when:

- the workspace and `--context` overlap (one inside the other, or the same directory): this
  keeps the context's read-only mount independent of the workspace's;
- the `--ssh-key` file is inside the workspace or the context: the sandbox could read it
  and copy the private key out, bypassing the agent;
- the workspace or context path contains `:`, which sbx would confuse with its `:ro` suffix.

## sbx settings and caveats

SSH agent forwarding must be on, and not pinned to a fixed socket:

```console
$ sbx settings set ssh.agentForwardingEnabled true
$ sbx settings unset ssh.agentSocketPath
$ sbx daemon restart
```

- **Restart the daemon after changing any `ssh.*` setting.** Until then, the daemon keeps
  its old behaviour; the in-sandbox key check will refuse to launch if that lets other
  keys through.
- **sbx points a sandbox at the agent of the latest `sbx` command aimed at it**, live, even
  for sessions already running. Running, say, `sbx exec myproj-dev ...` from a terminal
  where your personal `SSH_AUTH_SOCK` is set hands the sandbox your personal agent. Interact
  with these sandboxes through `agent_sandbox`, or unset `SSH_AUTH_SOCK` first.
- Forwarding is a global setting: a sandbox started with plain `sbx run` from a terminal
  holding your personal agent gets that agent.

## Development

```console
$ uv sync --extra dev
$ uv run ruff format .
$ uv run ruff check .
$ uv run mypy
$ uv run pytest
```

Run them in this order: cheapest and fastest first, so a trivial style or type issue fails
fast instead of making you wait on the full test run. `.claude/hooks/pre-commit-checks.sh`
enforces the same order (with `ruff format --check`, since it only checks, never rewrites)
before any commit.
