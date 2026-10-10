"""Configuration. Edit the constants to change the defaults."""

import os
from dataclasses import dataclass
from pathlib import Path

AGENT = "claude"
"""sbx agent to run."""

SOCKETS_DIR = "/tmp/sbx-agents-{uid}"
"""ssh-agent sockets, one per sandbox: SOCKETS_DIR/<name>.sock."""


@dataclass(frozen=True)
class Config:
    agent: str
    sockets_dir: Path
    uid: int

    @classmethod
    def default(cls) -> "Config":
        uid = os.getuid()
        return cls(agent=AGENT, sockets_dir=Path(SOCKETS_DIR.format(uid=uid)), uid=uid)
