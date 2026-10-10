# agent-sandbox

Launch a [Docker Sandboxes](https://docs.docker.com/ai/sandboxes/) (`sbx`) agent with its
own SSH agent and a read-only context directory. Each launch:

1. refuses path layouts that would undo the sandbox's protections (see below);
2. starts (or reuses) an `ssh-agent` dedicated to the sandbox, and makes the keys you
   pass the only keys it holds;
3. creates the sandbox if needed, then checks from inside it that it sees exactly those
   keys, so your personal agent can't have been forwarded;
4. runs `sbx run` with only that agent's socket visible, mounting the context directory
   read-only.

## Install

```console
$ python -m venv .venv
$ .venv/bin/pip install -e .
```

## Use

```console
$ agent_sandbox --name myproj-dev --context ./agents/dev --key ~/.ssh/dev_ed25519 ~/src/myproj
$ agent_sandbox --name myproj-dev --context ./agents/dev --key ~/.ssh/dev_ed25519 ~/src/myproj -- --continue
```

| Argument | Meaning |
| --- | --- |
| `WORKSPACE` | Project directory the agent works in |
| `--name` | Sandbox name. The same name re-attaches to the same sandbox. |
| `--context DIR` | Directory mounted read-only into the sandbox |
| `--key FILE` | Private key for the sandbox's SSH agent; repeat for several, or omit for none |
| `-- ARGS` | Passed to the agent |

A sandbox's mounts are fixed when it is created: re-using a `--name` with a different
workspace or `--context` re-attaches to the existing sandbox with its original mounts.
Remove it first (`sbx rm NAME`) to change them.

The sandbox's SSH agent listens on `/tmp/sbx-agents-<uid>/<name>.sock`. On every launch it
is emptied and given exactly the `--key` files, so keys from earlier launches never linger.
The agent (`claude`) and the sockets directory are set in `src/agent_sandbox/config.py`.

## Path rules

The launch is refused when:

- the workspace and `--context` overlap (one inside the other, or the same directory): this
  keeps the context's read-only mount independent of the workspace's;
- a `--key` file is inside the workspace or the context: the sandbox could read it and copy
  the private key out, bypassing the agent;
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
$ .venv/bin/pip install -e '.[dev]'
$ .venv/bin/pytest
$ .venv/bin/mypy
```
