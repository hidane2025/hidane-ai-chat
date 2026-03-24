"""Web検索ツール。
外部APIを使ってリアルタイムのWeb情報を検索。
Brave Search API対応（APIキー未設定時はフォールバックメッセージ）。
"""

import json
import os
import urllib.request
import urllib.parse

TOOL_DEF = {
    "name": "web_search",
    "description": "Webを検索して最新の情報を取得します。企業情報、業界動向、競合調査、技術情報などの調査に使えます。",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "検索キーワード（例: 人材開発支援助成金 2026年 改正）",
            },
            "num_results": {
                "type": "integer",
                "description": "取得する結果数（デフォルト: 5、最大: 10）",
            },
        },
        "required": ["query"],
    },
}

BRAVE_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")


def execute(params: dict) -> str:
    query = params.get("query", "").strip()
    num_results = min(params.get("num_results", 5), 10)

    if not query:
        return "検索キーワードを指定してください。"

    if not BRAVE_API_KEY:
        return (
            f"【Web検索: {query}】\n"
            "Web検索APIキーが未設定のため、リアルタイム検索は利用できません。\n"
            "社内ナレッジ（knowledge_search）で代替検索するか、"
            "管理者にBRAVE_SEARCH_API_KEYの設定を依頼してください。"
        )

    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://api.search.brave.com/res/v1/web/search?q={encoded_query}&count={num_results}&search_lang=ja"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": BRAVE_API_KEY,
            },
        )

        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode("utf-8"))

        results = data.get("web", {}).get("results", [])
        if not results:
            return f"「{query}」の検索結果は見つかりませんでした。"

        lines = [f"【Web検索結果: {query}】\n"]
        for i, r in enumerate(results[:num_results], 1):
            title = r.get("title", "")
            url_str = r.get("url", "")
            description = r.get("description", "")
            lines.append(f"{i}. {title}\n   URL: {url_str}\n   {description}\n")

        return "\n".join(lines)

    except Exception as e:
        return f"Web検索エラー: {str(e)}"
