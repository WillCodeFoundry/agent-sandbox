"""Configuration. Edit the constants to change the defaults."""

from dataclasses import dataclass
from pathlib import Path

AGENT = "claude"
"""sbx agent to run."""

SOCKETS_DIR = "/tmp/sbx-agents"
"""Base directory for ssh-agent sockets; Host.socket_path makes it private per-uid."""


@dataclass(frozen=True)
class Config:
    agent: str
    sockets_dir: Path

    @classmethod
    def default(cls) -> "Config":
        return cls(agent=AGENT, sockets_dir=Path(SOCKETS_DIR))
