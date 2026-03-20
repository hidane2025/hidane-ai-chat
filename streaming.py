"""
SSE streaming module for Claude API responses.
Streams tokens in real-time via Server-Sent Events.
"""

import json
import os
import re
import urllib.request

from flask import Response


ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def _parse_sse_line(line: str):
    """Parse a single SSE line into (field, value). Returns ('', '') for non-SSE lines."""
    if line.startswith("event: "):
        return ("event", line[7:])
    if line.startswith("data: "):
        return ("data", line[6:])
    return ("", "")


def _extract_text_delta(data_str: str) -> str:
    """Extract text from a content_block_delta JSON payload. Returns '' if not a text delta."""
    try:
        obj = json.loads(data_str)
        if obj.get("type") == "content_block_delta":
            delta = obj.get("delta", {})
            if delta.get("type") == "text_delta":
                return delta.get("text", "")
    except (json.JSONDecodeError, TypeError):
        pass
    return ""


def _sse_event(payload: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _detect_pdfs(text: str):
    """Find all [PDF:filename:title] tags in text."""
    return [
        {"filename": m.group(1), "title": m.group(2)}
        for m in re.finditer(r'\[PDF:([^\]:]+\.pdf):([^\]]+)\]', text)
    ]


def stream_claude_response(
    message: str,
    employee: dict,
    session_id: str,
    employee_name: str,
    history: list,
    system_prompt: str,
    on_complete=None,
) -> "Generator[str, None, None]":
    """Generator that yields SSE strings for a streamed Claude API response."""

    # Emit start event with employee metadata
    yield _sse_event({
        "type": "start",
        "employee": employee["full_name"],
        "employee_id": employee.get("id", ""),
        "role": employee.get("role", ""),
        "color": employee.get("color", "#6C5CE7"),
        "avatar": employee.get("avatar", ""),
    })

    # Build conversation messages from DB history
    messages = [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": message})

    # Prepare streaming API request
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 2048,
        "system": system_prompt,
        "messages": messages,
        "stream": True,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers=headers)

    try:
        full_text = ""
        with urllib.request.urlopen(req) as res:
            for raw_line in res:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                field, value = _parse_sse_line(line)
                if field == "data":
                    token = _extract_text_delta(value)
                    if token:
                        full_text += token
                        yield _sse_event({"type": "token", "text": token})

        # Notify caller to persist to DB
        if on_complete:
            on_complete(full_text)

        # Emit done event
        yield _sse_event({"type": "done", "full_text": full_text})

        # Emit PDF events if detected
        for pdf in _detect_pdfs(full_text):
            yield _sse_event({"type": "pdf", "filename": pdf["filename"], "title": pdf["title"]})

    except Exception as exc:
        yield _sse_event({"type": "error", "message": str(exc)})


def make_sse_response(generator: "Generator[str, None, None]") -> Response:
    """Wrap an SSE generator in a Flask Response with proper streaming headers."""
    return Response(
        generator,
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
