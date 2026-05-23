from typing import Dict, List, Optional, Set
from promptvc.utils.console import safe_print, bold, dim

def _parse_vars(var_args: Optional[List[str]]) -> Dict[str, str]:
    """Parse var arguments formatted as key=value."""
    if not var_args:
        return {}
    variables: Dict[str, str] = {}
    for entry in var_args:
        if "=" not in entry:
            raise ValueError(f"Invalid --var format: '{entry}'. Expected 'key=value'.")
        key, value = entry.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid --var format: '{entry}'. Key must not be empty.")
        variables[key] = value.strip()
    return variables


def _collect_schema_variables(
    schema_vars: Dict[str, Dict],
    provided_vars: Dict[str, str],
    is_non_interactive: bool = False,
) -> Dict[str, str]:
    """Collect required variables specified in schema."""
    collected: Dict[str, str] = {}
    for var_name, spec in schema_vars.items():
        if var_name in provided_vars:
            continue
        required = spec.get("required", False)
        default  = spec.get("default")
        if default is not None:
            collected[var_name] = str(default)
            continue
        if required:
            if is_non_interactive:
                raise RuntimeError(f"Missing required variable '{var_name}' in non-interactive mode.")
            value = input(dim(f"  {var_name}: ")).strip()
            collected[var_name] = value
    return collected


def _collect_template_variables(
    required_vars: Set[str],
    provided_vars: Dict[str, str],
    is_non_interactive: bool = False,
) -> Dict[str, str]:
    """Interactively collect variables required by the prompt template."""
    missing = required_vars - set(provided_vars.keys())
    if not missing:
        return {}
    if is_non_interactive:
        first_missing = sorted(missing)[0]
        raise RuntimeError(f"Missing required variable '{first_missing}' in non-interactive mode.")
    safe_print(bold("\n  Variables needed:"))
    collected: Dict[str, str] = {}
    for var in sorted(missing):
        value = input(dim(f"  {var}: ")).strip()
        collected[var] = value
    return collected
