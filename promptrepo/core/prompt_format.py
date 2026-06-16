"""
promptrepo/core/prompt_format.py

Structured prompt format support for PromptVC.

Developers can now store prompts in three formats:
  - "raw"         : Plain string (current default, backward-compatible)
  - "chat"        : List of {role, content} messages (OpenAI chat format)
  - "instruction" : Single system + user message pair

Chat prompts support template variables inside any message content field.

Usage:
    from promptrepo.core.prompt_format import (
        PromptFormat, ChatMessage, render_prompt, messages_to_plain
    )

    # Commit a chat-format prompt
    messages = [
        {"role": "system", "content": "You are a {{persona}} assistant."},
        {"role": "user", "content": "Summarize: {{text}}"},
    ]
    repo.commit("summarizer", messages, "chat prompt v1", format="chat")

    # Render at runtime
    rendered_messages = render_prompt(raw_prompt, {"persona": "helpful", "text": "..."}, format="chat")
    result = provider.run("", messages=rendered_messages)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from promptrepo.utils.template import render_template, extract_variables


class PromptFormat:
    """Supported prompt format type constants."""
    RAW = "raw"
    CHAT = "chat"
    INSTRUCTION = "instruction"

    VALID_FORMATS = {RAW, CHAT, INSTRUCTION}
    VALID_ROLES = {"system", "user", "assistant", "tool", "function"}

    @classmethod
    def validate(cls, fmt: str) -> None:
        if fmt not in cls.VALID_FORMATS:
            raise ValueError(
                f"Invalid prompt format '{fmt}'. "
                f"Valid formats: {', '.join(sorted(cls.VALID_FORMATS))}"
            )


@dataclass
class ChatMessage:
    """A single message in a chat-format prompt."""
    role: str          # "system", "user", "assistant"
    content: str       # Template string with optional {{variables}}
    name: Optional[str] = None   # Optional speaker name

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMessage":
        return cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
            name=data.get("name"),
        )


def validate_chat_messages(messages: List[Dict[str, Any]]) -> None:
    """
    Validate a list of chat message dicts.

    Raises:
        ValueError: If any message is malformed.
    """
    if not isinstance(messages, list) or not messages:
        raise ValueError("Chat prompt must be a non-empty list of messages.")

    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            raise ValueError(f"Message at index {i} must be a dict, got {type(msg).__name__}.")

        role = msg.get("role")
        if not role:
            raise ValueError(f"Message at index {i} is missing required 'role' field.")

        if role not in PromptFormat.VALID_ROLES:
            raise ValueError(
                f"Message at index {i} has invalid role '{role}'. "
                f"Valid roles: {', '.join(sorted(PromptFormat.VALID_ROLES))}"
            )

        content = msg.get("content")
        if content is None:
            raise ValueError(f"Message at index {i} (role='{role}') is missing 'content' field.")


def render_prompt(
    raw: Union[str, List[Dict[str, Any]]],
    variables: Dict[str, str],
    fmt: str = PromptFormat.RAW,
) -> Union[str, List[Dict[str, Any]]]:
    """
    Render a prompt (raw string or chat messages list) with template variables.

    For RAW format: returns rendered string.
    For CHAT/INSTRUCTION format: returns rendered messages list with variables
    substituted in each message's content field.

    Args:
        raw: The stored prompt string or messages list.
        variables: Dict of variable name → value.
        fmt: One of PromptFormat.RAW, .CHAT, or .INSTRUCTION.

    Returns:
        str for RAW, List[Dict] for CHAT/INSTRUCTION.
    """
    PromptFormat.validate(fmt)

    if fmt == PromptFormat.RAW:
        if not isinstance(raw, str):
            raw = json.dumps(raw)
        return render_template(raw, variables)

    # CHAT or INSTRUCTION — render each message content
    if isinstance(raw, str):
        try:
            messages = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            # Treat as single user message
            messages = [{"role": "user", "content": raw}]
    else:
        messages = raw

    validate_chat_messages(messages)

    rendered: List[Dict[str, Any]] = []
    for msg in messages:
        msg_copy = dict(msg)
        content = msg_copy.get("content", "")
        if variables:
            # Only render if there are template vars in this message
            if "{{" in content:
                msg_copy["content"] = render_template(content, variables)
        rendered.append(msg_copy)

    return rendered


def messages_to_plain(messages: List[Dict[str, Any]]) -> str:
    """
    Convert a chat messages list to a plain string representation.

    Useful for tokenization, display, and diff operations.

    Format:
        [system]: ...
        [user]: ...
        [assistant]: ...
    """
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        parts.append(f"[{role}]: {content}")
    return "\n".join(parts)


def extract_variables_from_prompt(
    raw: Union[str, List[Dict[str, Any]]],
    fmt: str = PromptFormat.RAW,
) -> set:
    """
    Extract all template variable names from a prompt (any format).

    For CHAT format: combines variables from all message content fields.
    """
    PromptFormat.validate(fmt)

    if fmt == PromptFormat.RAW:
        if not isinstance(raw, str):
            raw = json.dumps(raw)
        return extract_variables(raw)

    if isinstance(raw, str):
        try:
            messages = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return extract_variables(raw)
    else:
        messages = raw

    all_vars: set = set()
    for msg in messages:
        content = msg.get("content", "")
        all_vars |= extract_variables(content)

    return all_vars


def prompt_to_storage(
    prompt: Union[str, List[Dict[str, Any]]],
    fmt: str = PromptFormat.RAW,
) -> str:
    """
    Convert a prompt (any format) to its storage representation (JSON string for chat).
    Raw prompts are stored as-is.
    """
    PromptFormat.validate(fmt)
    if fmt == PromptFormat.RAW:
        if not isinstance(prompt, str):
            raise ValueError("RAW format prompt must be a string.")
        return prompt

    if isinstance(prompt, list):
        validate_chat_messages(prompt)
        return json.dumps(prompt, ensure_ascii=False)

    return str(prompt)


def prompt_from_storage(
    stored: str,
    fmt: str = PromptFormat.RAW,
) -> Union[str, List[Dict[str, Any]]]:
    """
    Deserialize a stored prompt from its storage representation.
    """
    PromptFormat.validate(fmt)
    if fmt == PromptFormat.RAW:
        return stored

    try:
        parsed = json.loads(stored)
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    return [{"role": "user", "content": stored}]
