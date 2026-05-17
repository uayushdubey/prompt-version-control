from __future__ import annotations

import argparse
import json
from promptvc.utils.config import get_config_value, set_config_value, load_config

def config_command(args: argparse.Namespace) -> None:
    action = getattr(args, "action", None)
    
    if action == "set":
        key = getattr(args, "key", None)
        value = getattr(args, "value", None)
        if not key or value is None:
            print("Error: 'set' requires <key> and <value>")
            return
        set_config_value(key, value)
        print(f"Set {key} = {value}")
        
    elif action == "get":
        key = getattr(args, "key", None)
        if not key:
            print("Error: 'get' requires <key>")
            return
        val = get_config_value(key)
        if val is None:
            print(f"Key not found: {key}")
        else:
            if isinstance(val, dict):
                print(json.dumps(val, indent=2))
            else:
                print(val)
                
    elif action == "list":
        config = load_config()
        print(json.dumps(config, indent=2))
    else:
        print("Unknown config action. Use set, get, or list.")