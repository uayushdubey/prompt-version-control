from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from promptvc.core.repo import PromptRepo
from promptvc.core.scorer import RuleScorer
from promptvc.utils.template import extract_variables


@dataclass
class ValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def validate_dataset(path: str) -> ValidationResult:
    """Validate a test dataset/eval dataset JSON file."""
    errors: List[str] = []
    warnings: List[str] = []

    if not os.path.exists(path):
        return ValidationResult(valid=False, errors=[f"Dataset file does not exist: {path}"])

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        return ValidationResult(valid=False, errors=[f"Invalid JSON: {exc}"])

    if not isinstance(data, list):
        return ValidationResult(valid=False, errors=["Dataset must be a JSON array (list) of objects."])

    golden_dir = os.path.dirname(os.path.abspath(path))

    supported_assertions = {
        "contains", "not_contains", "regex", "starts_with",
        "ends_with", "max_tokens", "min_tokens", "json_valid", "golden"
    }

    for idx, case in enumerate(data):
        case_label = f"Case {idx + 1}"
        if not isinstance(case, dict):
            errors.append(f"{case_label}: Expected a JSON object (dict).")
            continue

        case_id = case.get("id")
        if not case_id:
            errors.append(f"{case_label}: Missing required field 'id'.")
            case_id = f"case-{idx + 1}"
        else:
            case_label = f"Case '{case_id}'"

        input_vars = case.get("input")
        if input_vars is None:
            errors.append(f"{case_label}: Missing required field 'input'.")
        elif not isinstance(input_vars, dict):
            errors.append(f"{case_label}: 'input' must be a JSON object (dict).")

        # Validate assertions
        assertions = case.get("assertions")
        if assertions is not None:
            if not isinstance(assertions, list):
                errors.append(f"{case_label}: 'assertions' must be a JSON array (list).")
            else:
                for a_idx, ass in enumerate(assertions):
                    a_label = f"{case_label} assertion {a_idx + 1}"
                    if not isinstance(ass, dict):
                        errors.append(f"{a_label}: Must be a JSON object.")
                        continue
                    atype = ass.get("type")
                    if not atype:
                        errors.append(f"{a_label}: Missing 'type'.")
                        continue
                    atype_lower = str(atype).lower()
                    if atype_lower not in supported_assertions:
                        errors.append(f"{a_label}: Unsupported assertion type '{atype}'.")
                        continue

                    # Assertion-specific checks
                    if atype_lower == "golden":
                        gfile = ass.get("file")
                        if not gfile:
                            errors.append(f"{a_label}: Missing 'file' for golden assertion.")
                        else:
                            full_path = os.path.join(golden_dir, gfile)
                            if not os.path.exists(full_path):
                                warnings.append(f"{a_label}: Referenced golden file does not exist: {gfile}")
                    elif atype_lower != "json_valid":
                        if "value" not in ass:
                            errors.append(f"{a_label}: Missing required field 'value' for type '{atype}'.")

        # Validate checks
        checks = case.get("checks")
        if checks is not None:
            if not isinstance(checks, list):
                errors.append(f"{case_label}: 'checks' must be a JSON array (list).")
            else:
                for c_idx, check in enumerate(checks):
                    c_label = f"{case_label} check {c_idx + 1}"
                    if not isinstance(check, dict):
                        errors.append(f"{c_label}: Must be a JSON object.")
                        continue
                    ctype = check.get("type")
                    if not ctype:
                        errors.append(f"{c_label}: Missing 'type'.")
                        continue
                    ctype_lower = str(ctype).lower()
                    if ctype_lower not in RuleScorer.SUPPORTED_CHECKS:
                        errors.append(f"{c_label}: Unsupported check type '{ctype}'.")
                        continue

                    # Check value/expected/reference
                    expected_keys = {"expected", "value", "reference"}
                    if ctype_lower != "json_valid" and not any(k in check for k in expected_keys):
                        errors.append(f"{c_label}: Missing expected/value/reference field for check type '{ctype}'.")

        # Validate llm_judge
        llm_judge = case.get("llm_judge")
        if llm_judge is not None:
            if not isinstance(llm_judge, dict):
                errors.append(f"{case_label}: 'llm_judge' must be a JSON object (dict).")
            else:
                criteria = llm_judge.get("criteria")
                if not criteria:
                    errors.append(f"{case_label}: 'llm_judge' missing required field 'criteria'.")
                elif not isinstance(criteria, str):
                    errors.append(f"{case_label}: 'llm_judge.criteria' must be a string.")

                weight = llm_judge.get("weight")
                if weight is not None:
                    try:
                        w_val = float(weight)
                        if w_val < 0.0 or w_val > 1.0:
                            errors.append(f"{case_label}: 'llm_judge.weight' must be between 0.0 and 1.0.")
                    except (ValueError, TypeError):
                        errors.append(f"{case_label}: 'llm_judge.weight' must be a number.")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def validate_prompt(repo: PromptRepo, name: str, version: str) -> ValidationResult:
    """Validate a committed prompt version against its schema."""
    errors: List[str] = []
    warnings: List[str] = []

    try:
        prompt_data = repo.get_version_meta(name, version)
    except Exception as exc:
        return ValidationResult(valid=False, errors=[f"Prompt '{name}@{version}' not found: {exc}"])

    prompt_text = prompt_data.get("prompt", "")
    try:
        template_vars = extract_variables(prompt_text)
    except Exception as exc:
        return ValidationResult(valid=False, errors=[f"Failed to parse variables from prompt template: {exc}"])

    try:
        schema = repo.get_schema(name, version)
        schema_vars = schema.get("variables", {}) if schema else {}
    except Exception as exc:
        schema_vars = {}
        warnings.append(f"Could not load schema: {exc}")

    # Check for variables in template not defined in schema
    for t_var in template_vars:
        if t_var not in schema_vars:
            errors.append(f"Variable '{t_var}' is used in prompt template but not defined in schema.")

    # Check for schema variables not used in template
    for s_var, spec in schema_vars.items():
        if s_var not in template_vars:
            required = spec.get("required", False)
            if required:
                errors.append(f"Variable '{s_var}' is marked as required in schema but not used in prompt template.")
            else:
                warnings.append(f"Variable '{s_var}' is defined in schema but not used in prompt template.")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )
