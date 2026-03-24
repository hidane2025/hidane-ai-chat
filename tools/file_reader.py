"""ファイル読み込みツール。
商談先フォルダやstatic/files/のPDF一覧・メタデータを取得。
"""

from pathlib import Path

TOOL_DEF = {
    "name": "file_reader",
    "description": "社内のファイルやフォルダを読み取ります。商談先フォルダの資料一覧、送信可能なPDF一覧、テキストファイルの内容読み取りに対応。",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_clients", "list_pdfs", "read_file", "client_files"],
                "description": "list_clients: 商談先一覧、list_pdfs: 送信可能PDF一覧、read_file: ファイル読み取り、client_files: 特定商談先の資料一覧",
            },
            "path": {
                "type": "string",
                "description": "read_fileの場合: ファイルパス。client_filesの場合: 会社名",
            },
        },
        "required": ["action"],
    },
}

_BASE_DIR = Path(__file__).parent.parent
_CLIENTS_DIR = _BASE_DIR.parent / "商談先"
_FILES_DIR = _BASE_DIR / "static" / "files"

# 読み取り許可する拡張子
_ALLOWED_EXTENSIONS = {".txt", ".md", ".csv", ".json"}


def execute(params: dict) -> str:
    action = params.get("action", "")
    path_param = params.get("path", "")

    if action == "list_clients":
        return _list_clients()
    if action == "list_pdfs":
        return _list_pdfs()
    if action == "client_files":
        return _client_files(path_param)
    if action == "read_file":
        return _read_file(path_param)
    return f"不明なアクション: {action}"


def _list_clients() -> str:
    if not _CLIENTS_DIR.exists():
        return "商談先フォルダが見つかりません。"
    companies = []
    for item in sorted(_CLIENTS_DIR.iterdir()):
        if item.is_dir() and not item.name.startswith("."):
            file_count = sum(1 for f in item.iterdir() if f.is_file())
            companies.append(f"- {item.name}（{file_count}ファイル）")
    if not companies:
        return "商談先フォルダは空です。"
    return "【商談先一覧】\n" + "\n".join(companies)


def _list_pdfs() -> str:
    if not _FILES_DIR.exists():
        return "PDFフォルダが見つかりません。"
    pdfs = sorted(_FILES_DIR.glob("*.pdf"))
    if not pdfs:
        return "送信可能なPDFはありません。"
    lines = [f"- {f.name}（{round(f.stat().st_size / 1024, 1)}KB）" for f in pdfs]
    return "【送信可能なPDF一覧】\n" + "\n".join(lines)


def _client_files(company_name: str) -> str:
    if not company_name:
        return "会社名を指定してください。"
    target = _CLIENTS_DIR / company_name
    if not target.exists():
        # 部分一致で検索
        matches = [d for d in _CLIENTS_DIR.iterdir() if d.is_dir() and company_name in d.name]
        if not matches:
            return f"「{company_name}」に該当する商談先が見つかりません。"
        target = matches[0]

    files = sorted(f for f in target.iterdir() if f.is_file())
    if not files:
        return f"「{target.name}」フォルダにファイルはありません。"
    lines = [f"- {f.name}（{round(f.stat().st_size / 1024, 1)}KB）" for f in files]
    return f"【{target.name}の資料一覧】\n" + "\n".join(lines)


def _read_file(path_param: str) -> str:
    if not path_param:
        return "ファイルパスを指定してください。"

    # セキュリティ: パストラバーサル防止
    if ".." in path_param:
        return "不正なパスです。"

    # 商談先フォルダ内 or static/files/ 内のみ許可
    candidates = [
        _CLIENTS_DIR / path_param,
        _FILES_DIR / path_param,
    ]
    target = None
    for c in candidates:
        if c.exists() and c.is_file():
            target = c
            break

    if target is None:
        return f"ファイルが見つかりません: {path_param}"

    if target.suffix.lower() not in _ALLOWED_EXTENSIONS:
        return f"読み取り対応外の形式です（{target.suffix}）。対応: {', '.join(_ALLOWED_EXTENSIONS)}"

    try:
        content = target.read_text(encoding="utf-8")
        # 長すぎる場合は切り詰め
        if len(content) > 5000:
            content = content[:5000] + "\n\n...（以降省略、全{len(content)}文字）"
        return f"【{target.name}の内容】\n{content}"
    except Exception as e:
        return f"読み取りエラー: {str(e)}"
