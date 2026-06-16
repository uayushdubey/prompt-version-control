"""
utils/template.py

Minimal, strict, dependency-free template rendering system for promptrepo.
Supports only {{variable_name}} syntax with strict variable validation.
"""

import re
from typing import Dict, Set


# Compiled regex pattern for matching template variables.
# Matches {{ variable_name }} with optional surrounding whitespace inside braces.
# Variable names must follow: [a-zA-Z_][a-zA-Z0-9_]*
_VARIABLE_PATTERN: re.Pattern = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class TemplateError(Exception):
    """Raised when template rendering encounters missing or invalid variables."""
    pass


def extract_variables(template: str) -> Set[str]:
    """
    Extract all unique variable names from a template string.

    Scans the template for all occurrences of {{variable_name}} syntax,
    including variants with surrounding whitespace (e.g., {{ name }}).

    Args:
        template: The template string to scan.

    Returns:
        A set of unique variable name strings found in the template.

    Example:
        >>> extract_variables("Hello {{name}}, you are {{age}} years old.")
        {'name', 'age'}
    """
    return set(_VARIABLE_PATTERN.findall(template))


def validate_variables(template: str, variables: Dict[str, str]) -> None:
    """
    Validate that all variables required by the template are provided.

    Raises:
        TemplateError if required variables are missing.
    """
    required: Set[str] = extract_variables(template)
    provided: Set[str] = set(variables.keys())

    missing: Set[str] = required - provided

    if missing:
        missing_list = ", ".join(sorted(missing))
        raise TemplateError(f"Missing variable(s): {missing_list}")


def render_template(template: str, variables: Dict[str, str]) -> str:
    """
    Render a template string by substituting all variable placeholders.

    Validates that all required variables are provided before rendering.
    Each occurrence of {{variable_name}} (with optional inner whitespace)
    is replaced with the corresponding value from the variables dictionary.
    Extra variables not referenced in the template are ignored.

    Args:
        template: The template string containing variable placeholders.
        variables: A dictionary mapping variable names to their string values.

    Returns:
        The fully rendered string with all placeholders substituted.

    Raises:
        TemplateError: If one or more required variables are missing
                       from the variables dictionary.

    Example:
        >>> render_template("Fix this code:\\n{{code}}\\nStyle: {{style}}", {
        ...     "code": "print('hello')",
        ...     "style": "PEP8"
        ... })
        "Fix this code:\\nprint('hello')\\nStyle: PEP8"
    """
    validate_variables(template, variables)

    def replace_match(match: re.Match) -> str:
        return str(variables[match.group(1)])

    return _VARIABLE_PATTERN.sub(replace_match, template)

def find_unused_variables(template: str, variables: Dict[str, str]) -> Set[str]:
    """
    Identify variables that were provided but not used in the template.

    Args:
        template: The template string containing variable placeholders.
        variables: A dictionary of provided variables.

    Returns:
        A set of variable names that were provided but not used in the template.
    """
    required: Set[str] = extract_variables(template)
    provided: Set[str] = set(variables.keys())

    return provided - required