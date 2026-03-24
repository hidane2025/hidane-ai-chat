"""社内ナレッジ検索ツール。
COMPANY_CORE, EMPLOYEE_KNOWLEDGE, カスタムナレッジから関連情報を検索。
"""

from knowledge import COMPANY_CORE, EMPLOYEE_KNOWLEDGE

TOOL_DEF = {
    "name": "knowledge_search",
    "description": "社内ナレッジベースを検索します。会社情報、事業内容、営業パイプライン、助成金制度、社員の専門知識などを検索できます。",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "検索キーワード（例: 助成金 計算、研修コース、営業パイプライン）",
            },
        },
        "required": ["query"],
    },
}


def execute(params: dict) -> str:
    """ナレッジ検索を実行し、関連するセクションを返す。"""
    query = params.get("query", "").lower()
    if not query:
        return "検索キーワードを指定してください。"

    results = []

    # COMPANY_CORE から検索
    for section in COMPANY_CORE.split("\n\n"):
        if any(term in section.lower() for term in query.split()):
            results.append(section.strip())

    # EMPLOYEE_KNOWLEDGE から検索
    for emp_name, knowledge in EMPLOYEE_KNOWLEDGE.items():
        if any(term in knowledge.lower() for term in query.split()):
            results.append(f"[{emp_name}の知識]\n{knowledge.strip()}")

    if not results:
        return f"「{query}」に関連する情報は見つかりませんでした。"

    return "\n\n---\n\n".join(results[:5])  # 最大5セクション
