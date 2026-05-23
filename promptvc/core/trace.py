from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class TraceRecord:
    trace_id: str  # UUID
    timestamp: str  # ISO format
    prompt_name: str
    version: str
    rendered_prompt: str
    variables: Dict[str, str]
    provider: str
    model: str
    output: str
    tokens: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: float = 0.0
    cost_usd: Optional[float] = None
    score: Optional[float] = None
    error: Optional[str] = None


class TraceStore:
    """Append-only trace log stored as JSONL for efficient querying."""

    def __init__(self, root: Path):
        self._path = root / "traces.jsonl"

    def append(self, record: TraceRecord) -> None:
        """Append a trace record to the JSONL log file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record)) + "\n")

    def query(
        self,
        name: str,
        version: str = None,
        limit: int = 20,
    ) -> List[TraceRecord]:
        """Query recent trace records matching name and optional version."""
        if not self._path.exists():
            return []

        records = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    if data.get("prompt_name") == name:
                        if version is None or data.get("version") == version:
                            records.append(TraceRecord(**data))
                except Exception:
                    continue

        return records[-limit:]
