from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from promptrepo.utils.console import safe_print

_CONFIG_DIR = Path.home() / ".promptrepo"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

_DEFAULT_CONFIG = {
    "provider": "mock",
    "models": {
        "openai": "gpt-4o-mini",
        "gemini": "gemini-1.5-pro",
        "anthropic": "claude-3-haiku-20240307",
        "ollama": "llama3"
    },
    "defaults": {
        "timeout": 60,
        "max_tokens": None
    }
}

def load_config() -> dict:
    if _CONFIG_FILE.exists():
        try:
            with _CONFIG_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    safe_print("Warning: config file corrupted, using defaults")
                    return _DEFAULT_CONFIG.copy()
                return data
        except (json.JSONDecodeError, OSError):
            safe_print("Warning: config file corrupted, using defaults")
            return _DEFAULT_CONFIG.copy()
    
    # Auto-create if missing
    save_config(_DEFAULT_CONFIG.copy())
    return _DEFAULT_CONFIG.copy()

def save_config(config: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with _CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

def get_config_value(key: str, default: Any = None) -> Any:
    config = load_config()
    keys = key.split('.')
    val = config
    for k in keys:
        if isinstance(val, dict) and k in val:
            val = val[k]
        else:
            return default
    return val

def set_config_value(key: str, value: Any) -> None:
    config = load_config()
    keys = key.split('.')
    current = config
    for k in keys[:-1]:
        if k not in current or not isinstance(current[k], dict):
            current[k] = {}
        current = current[k]
    current[keys[-1]] = value
    save_config(config)

def list_config() -> dict:
    return load_config()
