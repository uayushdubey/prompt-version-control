import uuid
from datetime import datetime, timezone
from promptvc.core.trace import TraceRecord, TraceStore


def test_trace_store(tmp_path):
    store = TraceStore(tmp_path)
    trace_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    rec = TraceRecord(
        trace_id=trace_id,
        timestamp=timestamp,
        prompt_name="summarize",
        version="v1",
        rendered_prompt="Summarize this",
        variables={"text": "this"},
        provider="mock",
        model="mock",
        output="siht ezirammus",
        tokens=2,
        latency_ms=12.5,
    )

    store.append(rec)

    # Query matching name and version
    results = store.query("summarize", "v1")
    assert len(results) == 1
    assert results[0].trace_id == trace_id
    assert results[0].output == "siht ezirammus"

    # Query matching name, any version
    results_any = store.query("summarize")
    assert len(results_any) == 1

    # Query non-matching name
    results_none = store.query("other_prompt")
    assert len(results_none) == 0
