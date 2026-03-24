"""
ヒダネ AI社員ツールモジュール
Claude tool_use で使用するツールの定義とディスパッチ。
"""

from tools.knowledge_search import TOOL_DEF as KNOWLEDGE_SEARCH_DEF, execute as knowledge_search_execute
from tools.calculator import TOOL_DEF as CALCULATOR_DEF, execute as calculator_execute
from tools.file_reader import TOOL_DEF as FILE_READER_DEF, execute as file_reader_execute
from tools.web_search import TOOL_DEF as WEB_SEARCH_DEF, execute as web_search_execute
from tools.document_writer import TOOL_DEF as DOCUMENT_WRITER_DEF, execute as document_writer_execute
from tools.google_drive import TOOL_DEF as GOOGLE_DRIVE_DEF, execute as google_drive_execute

# ツール名 → (定義, 実行関数) のマッピング
_TOOL_REGISTRY = {
    "knowledge_search": (KNOWLEDGE_SEARCH_DEF, knowledge_search_execute),
    "calculator": (CALCULATOR_DEF, calculator_execute),
    "file_reader": (FILE_READER_DEF, file_reader_execute),
    "web_search": (WEB_SEARCH_DEF, web_search_execute),
    "document_writer": (DOCUMENT_WRITER_DEF, document_writer_execute),
    "google_drive": (GOOGLE_DRIVE_DEF, google_drive_execute),
}

# 全ツール定義リスト（Claude API に渡す用）
ALL_TOOL_DEFINITIONS = [defn for defn, _ in _TOOL_REGISTRY.values()]


def get_tool_definitions(tool_names: list[str]) -> list[dict]:
    """指定されたツール名のみの定義リストを返す。"""
    return [
        _TOOL_REGISTRY[name][0]
        for name in tool_names
        if name in _TOOL_REGISTRY
    ]


def execute_tool(name: str, params: dict) -> str:
    """ツールを名前で実行し、結果文字列を返す。"""
    if name not in _TOOL_REGISTRY:
        return f"エラー: 不明なツール '{name}'"
    _, exec_fn = _TOOL_REGISTRY[name]
    try:
        return exec_fn(params)
    except Exception as e:
        return f"ツール実行エラー ({name}): {str(e)}"
