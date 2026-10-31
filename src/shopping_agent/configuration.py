"""Read only explicit project configuration; never evaluate shell syntax or log values."""

import os
from pathlib import Path


def read_env_file(path: str | Path) -> dict[str, str]:
    """Parse the two supported settings without changing the process environment."""
    path = Path(path)
    if not path.exists():
        return {}
    if path.stat().st_size > 16000:
        raise ValueError("Environment file too large")
    settings: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or key not in {"DEEPSEEK_API_KEY", "DEEPSEEK_MODEL"}:
            raise ValueError("Unsupported environment file syntax or setting")
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError("Unclosed environment value")
            value = value[1:-1]
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("Invalid environment value")
        settings[key] = value
    return settings


def load_env(path: str | Path) -> None:
    """CLI compatibility: process values take precedence over the selected env file."""
    for key, value in read_env_file(path).items():
        os.environ.setdefault(key, value)
