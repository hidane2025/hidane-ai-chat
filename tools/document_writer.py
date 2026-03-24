"""文書生成ツール。
Markdown/テキスト文書を生成し、ダウンロード可能なファイルとして保存。
"""

import os
import uuid
from datetime import datetime
from pathlib import Path

TOOL_DEF = {
    "name": "document_writer",
    "description": "文書を作成してファイルとして保存します。提案書、報告書、台本、メモなどのテキスト文書を生成できます。",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "ファイル名（例: 提案書_株式会社Uxlst.md、研修報告書.txt）",
            },
            "content": {
                "type": "string",
                "description": "文書の本文（Markdown形式推奨）",
            },
            "title": {
                "type": "string",
                "description": "文書のタイトル（表示用）",
            },
        },
        "required": ["filename", "content"],
    },
}

_OUTPUT_DIR = Path(__file__).parent.parent / "static" / "generated"


def execute(params: dict) -> str:
    filename = params.get("filename", "").strip()
    content = params.get("content", "")
    title = params.get("title", filename)

    if not filename or not content:
        return "ファイル名と本文を指定してください。"

    # セキュリティ: ファイル名サニタイズ
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._-（）() ")
    if not safe_name:
        safe_name = f"document_{uuid.uuid4().hex[:8]}.md"

    # 拡張子チェック
    allowed = {".md", ".txt", ".csv"}
    ext = Path(safe_name).suffix.lower()
    if ext not in allowed:
        safe_name = safe_name + ".md"

    # ユニーク名（衝突防止）
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_name = f"{timestamp}_{safe_name}"

    # 出力ディレクトリ作成
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 書き込み
    output_path = _OUTPUT_DIR / unique_name
    output_path.write_text(content, encoding="utf-8")

    size_kb = round(output_path.stat().st_size / 1024, 1)

    return (
        f"文書を作成しました。\n"
        f"タイトル: {title}\n"
        f"ファイル名: {unique_name}\n"
        f"サイズ: {size_kb}KB\n"
        f"ダウンロード: /api/generated/{unique_name}"
    )
