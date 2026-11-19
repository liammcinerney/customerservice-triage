"""Settings from the environment, with a tiny .env reader (no python-dotenv)."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MODEL = "claude-opus-5-5"


def parse_env_file(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines.

    Blank lines and lines starting with # are ignored, a leading `export ` is
    allowed, and one pair of matching surrounding quotes is stripped.
    Inline comments after a value are not supported.
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_env(path: str | Path = ".env") -> None:
    """Load a .env file into os.environ.

    Variables already set in the environment win. Empty values are skipped, so
    `ANTHROPIC_API_KEY=` copied from .env.example doesn't mask another credential.
    A missing file is not an error.
    """
    env_path = Path(path)
    if not env_path.is_file():
        return
    for key, value in parse_env_file(env_path.read_text(encoding="utf-8")).items():
        if value:
            os.environ.setdefault(key, value)


def model_name() -> str:
    """The model used for triage: TRIAGE_MODEL, or the default."""
    return os.environ.get("TRIAGE_MODEL") or DEFAULT_MODEL
