"""
Claude API クライアント（Anthropic SDK使用）
ツール実行ループ対応。非ストリーミング版。
"""

import os

import anthropic

from tools import execute_tool

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 4096
MAX_TOOL_ROUNDS = 5


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def call_claude_with_tools(
    message: str,
    history: list,
    system_prompt: str,
    tools=None,
) -> str:
    """Claude APIをツール実行ループ付きで呼び出す。最終テキストを返す。

    ツールが指定されている場合:
    1. Claudeにリクエスト
    2. tool_useレスポンス → サーバー側でツール実行
    3. tool_resultをClaudeに返す
    4. 最大MAX_TOOL_ROUNDSまで繰り返し
    """
    if not ANTHROPIC_API_KEY:
        return "APIキーが未設定のためデモモードで動作中です。"

    client = _get_client()

    # 会話メッセージを構築
    messages = [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": message})

    api_kwargs = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system_prompt,
        "messages": messages,
    }
    if tools:
        api_kwargs["tools"] = tools

    for _round in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(**api_kwargs)

        # レスポンスからテキストとツールコールを分離
        text_parts = []
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(block)

        # ツールコールがなければ完了
        if not tool_calls:
            return "\n".join(text_parts)

        # ツール実行 → tool_resultメッセージを構築
        # まずassistantのレスポンスをメッセージに追加
        assistant_content = []
        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        messages.append({"role": "assistant", "content": assistant_content})

        # ツール実行結果をまとめる
        tool_results = []
        for tc in tool_calls:
            result = execute_tool(tc.name, tc.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

        # 次のラウンドへ（messagesを更新してapi_kwargsを再構築）
        api_kwargs["messages"] = messages

    # ラウンド上限に達した場合、最後のテキストを返す
    return "\n".join(text_parts) if text_parts else "ツール実行が上限に達しました。"
