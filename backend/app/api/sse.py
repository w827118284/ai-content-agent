import json
from typing import Any


def encode_sse(event: str, data: dict[str, Any]) -> str:
    if "\n" in event or "\r" in event:
        raise ValueError("SSE event name cannot contain line breaks")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"
