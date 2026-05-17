from __future__ import annotations

import argparse
import json
from typing import Any
from promptvc.utils.config import get_config_value, set_config_value, list_config
from promptvc.utils.console import safe_print

def _parse_value(val: str) -> Any:
    lower_val = val.lower()
    if lower_val == "true":
        return True
    if lower_val == "false":
        return False
    if lower_val == "null":
        return None
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val

def config_command(args: argparse.Namespace) -> None:
    action = getattr(args, "action", None)
    
    if action == "set":
        key = getattr(args, "key", None)
        value_raw = getattr(args, "value", None)
        if not key or value_raw is None:
            safe_print("Error: 'set' requires <key> and <value>")
            return
        
        parsed_value = _parse_value(value_raw)
        set_config_value(key, parsed_value)
        safe_print(f"Set {key} = {parsed_value}")
        
    elif action == "get":
        key = getattr(args, "key", None)
        if not key:
            safe_print("Error: 'get' requires <key>")
            return
        val = get_config_value(key)
        if val is None:
            safe_print(f"Key not found: {key}")
        else:
            if isinstance(val, dict):
                safe_print(json.dumps(val, indent=2))
            else:
                safe_print(str(val))
                
    elif action == "list":
        config = list_config()
        safe_print(json.dumps(config, indent=2))
    else:
        safe_print("Unknown config action. Use set, get, or list.")