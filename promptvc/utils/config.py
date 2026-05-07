from __future__ import annotations

import json
from pathlib import Path

_CONFIG_DIR = Path(".promptvc")
_CONFIG_FILE = _CONFIG_DIR / "config.json"


def load_config() -> dict:
    if _CONFIG_FILE.exists():
        with _CONFIG_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with _CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def set_config_value(key: str, value) -> None:
    config = load_config()
    config[key] = value
    save_config(config)


def get_config_value(key: str, default=None):
    return load_config().get(key, default)