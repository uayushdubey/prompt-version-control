from __future__ import annotations

import argparse

from promptvc.utils.config import set_config_value


def config_command(args: argparse.Namespace) -> None:
    if args.action == "set-provider":
        set_config_value("provider", args.value)
        print(f"Provider set to '{args.value}'")
    elif args.action == "set-api-key":
        set_config_value("api_key", args.value)
        print("API key saved")
    else:
        raise ValueError("Invalid config action")