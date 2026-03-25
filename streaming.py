"""
SSE streaming module for Claude API responses.
Anthropic SDK使用。ツール実行ループ対応。
"""

import json
import os
import re
from typing import Generator, List, Dict, Optional

import anthropic
from flask import Response

from tools import execute_tool

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 4096
MAX_TOOL_ROUNDS = 5


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
    tools: Optional[List[Dict]] = None,
) -> Generator[str, None, None]:
    """Generator that yields SSE strings for a streamed Claude API response.
    ツールが指定されている場合、ツール実行→再ストリーミングのループを行う。
    """

    # Emit start event with employee metadata
    yield _sse_event({
        "type": "start",
        "employee": employee["full_name"],
        "employee_id": employee.get("id", ""),
        "role": employee.get("role", ""),
        "color": employee.get("color", "#6C5CE7"),
        "avatar": employee.get("avatar", ""),
    })

    if not ANTHROPIC_API_KEY:
        yield _sse_event({"type": "token", "token": "APIキー未設定のためデモモードで動作中です。"})
        yield _sse_event({"type": "done", "full_text": "デモモード"})
        return

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build conversation messages
    messages = [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": message})

    full_text = ""

    try:
        for _round in range(MAX_TOOL_ROUNDS):
            # ストリーミングでClaudeを呼び出し
            api_kwargs = {
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "system": system_prompt,
                "messages": messages,
            }
            if tools:
                api_kwargs["tools"] = tools
                print(f"[streaming] ツール数: {len(tools)}, ツール名: {[t['name'] for t in tools]}")

            # ストリーミングレスポンスを処理
            round_text = ""
            tool_calls = []  # (id, name, input_json_str)
            current_tool_id = None
            current_tool_name = None
            current_tool_input = ""

            with client.messages.stream(**api_kwargs) as stream:
                for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            current_tool_id = block.id
                            current_tool_name = block.name
                            current_tool_input = ""
                            # フロントにツール開始を通知
                            yield _sse_event({
                                "type": "tool_start",
                                "tool": current_tool_name,
                                "tool_use_id": current_tool_id,
                            })

                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            token = delta.text
                            round_text += token
                            full_text += token
                            yield _sse_event({"type": "token", "token": token})
                        elif delta.type == "input_json_delta":
                            current_tool_input += delta.partial_json

                    elif event.type == "content_block_stop":
                        if current_tool_id:
                            # ツールコール完了
                            try:
                                tool_input = json.loads(current_tool_input) if current_tool_input else {}
                            except json.JSONDecodeError:
                                tool_input = {}
                            tool_calls.append((current_tool_id, current_tool_name, tool_input))
                            current_tool_id = None
                            current_tool_name = None
                            current_tool_input = ""

            # ツールコールがなければ完了
            if not tool_calls:
                break

            # ツール実行 → messagesに追加して次のラウンドへ
            # assistantレスポンスを再構築
            assistant_content = []
            if round_text:
                assistant_content.append({"type": "text", "text": round_text})
            for tc_id, tc_name, tc_input in tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc_id,
                    "name": tc_name,
                    "input": tc_input,
                })
            messages.append({"role": "assistant", "content": assistant_content})

            # ツール実行
            tool_results = []
            for tc_id, tc_name, tc_input in tool_calls:
                print(f"[streaming] ツール実行: {tc_name} input={tc_input}")
                result = execute_tool(tc_name, tc_input)
                print(f"[streaming] ツール結果: {tc_name} -> {result[:200]}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc_id,
                    "content": result,
                })
                # フロントにツール結果を通知
                yield _sse_event({
                    "type": "tool_result",
                    "tool": tc_name,
                    "tool_use_id": tc_id,
                    "summary": result[:200] + ("..." if len(result) > 200 else ""),
                })

            messages.append({"role": "user", "content": tool_results})

        # DB保存コールバック
        if on_complete:
            on_complete(full_text)

        # 完了イベント
        yield _sse_event({"type": "done", "full_text": full_text})

        # PDF検出
        for pdf in _detect_pdfs(full_text):
            yield _sse_event({"type": "pdf", "filename": pdf["filename"], "title": pdf["title"]})

    except Exception as exc:
        import traceback
        traceback.print_exc()
        yield _sse_event({"type": "error", "message": f"ストリーミングエラー: {str(exc)}"})


def make_sse_response(generator: Generator[str, None, None]) -> Response:
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
