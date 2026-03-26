"""
タスクキュー自動処理モジュール
Google Drive の タスクキュー/pending/ を定期巡回し、
Claude APIでタスクを実行して結果を保存する。
"""

import json
import sys
import os
import io
from datetime import datetime

# Google Drive API
from tools.google_drive import _get_drive_service, ROOT_FOLDER_ID

# Claude API（非ストリーミング版）
from claude_client import call_claude_with_tools
from tools import get_tool_definitions
from employees import get_employee
from system_prompt import build_system_prompt

# フォルダIDキャッシュ
_pending_folder_id = None
_done_folder_id = None


def _find_folder_by_name(service, parent_id, name):
    """親フォルダ内で名前指定のフォルダIDを探す。"""
    try:
        results = service.files().list(
            q=f"'{parent_id}' in parents and name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
            fields="files(id, name)",
            pageSize=1,
        ).execute()
        files = results.get("files", [])
        return files[0]["id"] if files else None
    except Exception as e:
        print(f"[task_processor] フォルダ検索エラー ({name}): {e}", flush=True, file=sys.stderr)
        return None


def _get_queue_folder_ids(service):
    """タスクキュー/pending/ と done/ のフォルダIDを取得・キャッシュ。"""
    global _pending_folder_id, _done_folder_id

    if _pending_folder_id and _done_folder_id:
        return _pending_folder_id, _done_folder_id

    # タスクキュー フォルダを探す
    queue_id = _find_folder_by_name(service, ROOT_FOLDER_ID, "タスクキュー")
    if not queue_id:
        return None, None

    _pending_folder_id = _find_folder_by_name(service, queue_id, "pending")
    _done_folder_id = _find_folder_by_name(service, queue_id, "done")

    return _pending_folder_id, _done_folder_id


def _read_task_file(service, file_id):
    """タスクファイル（JSON）を読み込む。"""
    try:
        from googleapiclient.http import MediaIoBaseDownload
        request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        text = buffer.getvalue().decode("utf-8", errors="replace")
        return json.loads(text)
    except Exception as e:
        print(f"[task_processor] タスク読み込みエラー: {e}", flush=True, file=sys.stderr)
        return None


def _move_to_done(service, file_id, pending_id, done_id, result_data=None):
    """タスクファイルをpending→doneに移動し、結果を追記。"""
    try:
        # 結果データがあれば更新
        if result_data:
            from googleapiclient.http import MediaInMemoryUpload
            content = json.dumps(result_data, ensure_ascii=False, indent=2)
            media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/plain")
            service.files().update(fileId=file_id, media_body=media).execute()

        # done/に移動
        service.files().update(
            fileId=file_id,
            addParents=done_id,
            removeParents=pending_id,
            fields="id, name, parents",
        ).execute()
        return True
    except Exception as e:
        print(f"[task_processor] 移動エラー: {e}", flush=True, file=sys.stderr)
        return False


# スキル別プロンプトマッピング
SKILL_PROMPTS = {
    "sales-pipeline": (
        "あなたは営業準備のエキスパートです。以下の企業について営業準備を実行してください。\n"
        "1. Web検索で企業情報をリサーチ\n"
        "2. 課題仮説を3つ立てる\n"
        "3. ヒダネの研修サービス（AI研修40万/人、助成金75%活用）を踏まえた提案を作成\n"
        "4. リサーチ結果をgoogle_driveのcreate_fileアクションで保存（商談先フォルダ内）\n"
        "結果はMarkdownでまとめてください。"
    ),
    "teleapo-list": "テレアポリストの作成・最適化を実行してください。",
    "training-report": "研修実施報告書を作成してください。",
    "weekly-kpi": "週次KPIレポートを作成してください。",
    "curriculum": "研修カリキュラムを設計してください。",
    "followup-email": "商談後のフォローメールを作成してください。",
}


def process_pending_tasks():
    """メイン巡回関数。pending/フォルダのタスクを処理する。"""
    service = _get_drive_service()
    if not service:
        return

    pending_id, done_id = _get_queue_folder_ids(service)
    if not pending_id or not done_id:
        return

    # pending/フォルダ内のJSONファイルを取得
    try:
        results = service.files().list(
            q=f"'{pending_id}' in parents and trashed = false",
            fields="files(id, name, mimeType)",
            pageSize=10,
        ).execute()
        files = results.get("files", [])
    except Exception as e:
        print(f"[task_processor] pending一覧取得エラー: {e}", flush=True, file=sys.stderr)
        return

    if not files:
        return  # タスクなし、何もしない

    print(f"[task_processor] {len(files)}件のタスクを検出", flush=True, file=sys.stderr)

    for f in files:
        file_id = f["id"]
        file_name = f["name"]

        # JSONファイルのみ処理
        if not file_name.endswith(".json"):
            continue

        print(f"[task_processor] 処理開始: {file_name}", flush=True, file=sys.stderr)

        # タスクを読み込む
        task_data = _read_task_file(service, file_id)
        if not task_data:
            print(f"[task_processor] タスク読み込み失敗: {file_name}", flush=True, file=sys.stderr)
            continue

        skill = task_data.get("skill", "")
        target = task_data.get("target", "")
        instructions = task_data.get("instructions", "")

        # スキル別プロンプトを構築
        skill_prompt = SKILL_PROMPTS.get(skill, "指示されたタスクを実行してください。")

        user_message = (
            f"タスク実行依頼:\n"
            f"対象: {target}\n"
            f"スキル: {skill}\n"
            f"指示: {instructions}\n\n"
            f"{skill_prompt}"
        )

        # Claude APIで実行
        try:
            emp = get_employee("ソウ")
            system = build_system_prompt(emp, "ソウ", "hidane", public_mode=False)
            emp_tools = get_tool_definitions(emp.get("tools", []))

            result_text = call_claude_with_tools(
                message=user_message,
                history=[],
                system_prompt=system,
                tools=emp_tools,
            )

            print(f"[task_processor] 処理完了: {file_name} ({len(result_text)}文字)", flush=True, file=sys.stderr)

            # タスクを完了状態に更新してdone/に移動
            task_data["status"] = "done"
            task_data["completed_at"] = datetime.now().isoformat()
            task_data["result_summary"] = result_text[:500]

            _move_to_done(service, file_id, pending_id, done_id, task_data)

        except Exception as e:
            print(f"[task_processor] タスク実行エラー ({file_name}): {e}", flush=True, file=sys.stderr)
            task_data["status"] = "error"
            task_data["error"] = str(e)
            _move_to_done(service, file_id, pending_id, done_id, task_data)
