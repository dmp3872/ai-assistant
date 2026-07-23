"""Configuration loading: non-secret YAML/env config + secret access via Keychain.

Secrets are NEVER read from the repo or .env. They come from the macOS Keychain
through app.security.secrets. This module only handles non-secret settings.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def _load_yaml(name: str) -> dict[str, Any]:
    """Load config/<name>.yaml, falling back to the committed .example.yaml."""
    real = CONFIG_DIR / f"{name}.yaml"
    example = CONFIG_DIR / f"{name}.example.yaml"
    path = real if real.exists() else example
    if not path.exists():
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


class Settings:
    """Resolved runtime settings. Instantiate once via get_settings()."""

    def __init__(self) -> None:
        self.config = _load_yaml("config")
        self.style = _load_yaml("style_profile")

        self.host = os.getenv("RADAR_HOST", "127.0.0.1")
        self.port = int(os.getenv("RADAR_PORT", "4317"))

        self.data_dir = Path(os.getenv("RADAR_DATA_DIR", str(ROOT / "data"))).resolve()
        self.log_dir = Path(os.getenv("RADAR_LOG_DIR", str(ROOT / "logs"))).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.data_dir / "radar.db"
        self.lock_path = self.data_dir / ".run.lock"
        self.emergency_stop_path = self.data_dir / "EMERGENCY_STOP"

        self.ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        self.ollama_classify_model = os.getenv("OLLAMA_CLASSIFY_MODEL", "llama3.1:8b")
        self.ollama_embed_model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
        self.claude_model = os.getenv("CLAUDE_MODEL", "claude-opus-4-8")

    # convenience accessors ------------------------------------------------
    def connector(self, name: str) -> dict[str, Any]:
        return (self.config.get("connectors") or {}).get(name, {}) or {}

    def connector_enabled(self, name: str) -> bool:
        return bool(self.connector(name).get("enabled", False))

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def emergency_stopped(self) -> bool:
        return self.emergency_stop_path.exists()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
