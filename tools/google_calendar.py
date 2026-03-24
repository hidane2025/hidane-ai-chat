"""
Google Calendar ツール
予定の検索・閲覧・作成・更新・削除を行う。
"""

from datetime import datetime, timedelta
from typing import Optional

from tools.google_auth import get_user_credentials, is_configured

TOOL_DEF = {
    "name": "google_calendar",
    "description": (
        "Googleカレンダーで予定の検索・閲覧・作成・更新・削除を行うツール。"
        "研修スケジュール・商談予定・社内ミーティングなどを管理できます。"
        "action: list（予定一覧）、create（作成）、update（更新）、delete（削除）、free_slots（空き時間）"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create", "update", "delete", "free_slots"],
                "description": (
                    "list=予定一覧、create=予定作成、"
                    "update=予定更新、delete=予定削除、free_slots=空き時間検索"
                ),
            },
            "date": {
                "type": "string",
                "description": "日付（YYYY-MM-DD形式）。list=対象日、free_slots=開始日。省略時は今日",
            },
            "days": {
                "type": "integer",
                "description": "取得日数（list, free_slotsで使用。デフォルト: 7）",
            },
            "event_id": {
                "type": "string",
                "description": "予定ID（update, deleteで使用）",
            },
            "title": {
                "type": "string",
                "description": "予定タイトル（create, updateで使用）",
            },
            "start_time": {
                "type": "string",
                "description": "開始日時（YYYY-MM-DDTHH:MM形式。例: 2026-03-25T10:00）",
            },
            "end_time": {
                "type": "string",
                "description": "終了日時（YYYY-MM-DDTHH:MM形式。省略時は開始から1時間後）",
            },
            "description": {
                "type": "string",
                "description": "予定の詳細説明",
            },
            "location": {
                "type": "string",
                "description": "場所（URL or 住所）",
            },
            "attendees": {
                "type": "string",
                "description": "参加者メールアドレス（カンマ区切り）",
            },
            "query": {
                "type": "string",
                "description": "検索キーワード（listで使用）",
            },
        },
        "required": ["action"],
    },
}

_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_TIMEZONE = "Asia/Tokyo"

_calendar_service = None


def _get_calendar_service():
    """Google Calendar APIサービスを返す。"""
    global _calendar_service
    if _calendar_service is not None:
        return _calendar_service

    creds = get_user_credentials(_SCOPES)
    if creds is None:
        return None

    try:
        from googleapiclient.discovery import build
        _calendar_service = build("calendar", "v3", credentials=creds)
        return _calendar_service
    except Exception as e:
        print(f"[google_calendar] サービス初期化エラー: {e}")
        return None


def _list_events(date: Optional[str] = None, days: int = 7, query: str = "") -> str:
    """予定一覧を取得する。"""
    service = _get_calendar_service()
    if service is None:
        return _fallback()

    try:
        if date:
            start_dt = datetime.fromisoformat(date)
        else:
            start_dt = datetime.now()

        time_min = start_dt.replace(hour=0, minute=0, second=0).isoformat() + "+09:00"
        time_max = (start_dt + timedelta(days=days)).replace(hour=23, minute=59, second=59).isoformat() + "+09:00"

        kwargs = {
            "calendarId": "primary",
            "timeMin": time_min,
            "timeMax": time_max,
            "maxResults": 30,
            "singleEvents": True,
            "orderBy": "startTime",
            "timeZone": _TIMEZONE,
        }
        if query:
            kwargs["q"] = query

        results = service.events().list(**kwargs).execute()
        events = results.get("items", [])

        if not events:
            period = f"{start_dt.strftime('%m/%d')}〜{(start_dt + timedelta(days=days)).strftime('%m/%d')}"
            return f"{period} の予定はありません。"

        lines = [f"📅 予定一覧（{len(events)}件）", ""]
        current_date = ""

        for event in events:
            start = event.get("start", {})
            end = event.get("end", {})

            # 終日 or 時間指定
            if "date" in start:
                event_date = start["date"]
                time_str = "終日"
            else:
                dt = start.get("dateTime", "")
                event_date = dt[:10]
                start_t = dt[11:16] if len(dt) > 16 else ""
                end_t = end.get("dateTime", "")[11:16] if end.get("dateTime") else ""
                time_str = f"{start_t}〜{end_t}"

            # 日付ヘッダー
            if event_date != current_date:
                current_date = event_date
                lines.append(f"── {event_date} ──")

            title = event.get("summary", "(タイトルなし)")
            location = event.get("location", "")
            loc_str = f" 📍{location}" if location else ""

            lines.append(f"  {time_str} {title}{loc_str}  (ID: {event['id']})")

        return "\n".join(lines)

    except Exception as e:
        return f"予定一覧エラー: {str(e)}"


def _create_event(
    title: str,
    start_time: str,
    end_time: Optional[str] = None,
    description: str = "",
    location: str = "",
    attendees: str = "",
) -> str:
    """予定を作成する。"""
    service = _get_calendar_service()
    if service is None:
        return _fallback()

    if not title or not start_time:
        return "タイトル(title)と開始日時(start_time)を指定してください。"

    try:
        # 終了時刻が未指定なら開始から1時間後
        if not end_time:
            start_dt = datetime.fromisoformat(start_time)
            end_dt = start_dt + timedelta(hours=1)
            end_time = end_dt.isoformat()

        event_body = {
            "summary": title,
            "start": {"dateTime": start_time + ":00+09:00", "timeZone": _TIMEZONE},
            "end": {"dateTime": end_time + ":00+09:00", "timeZone": _TIMEZONE},
        }

        if description:
            event_body["description"] = description
        if location:
            event_body["location"] = location
        if attendees:
            event_body["attendees"] = [
                {"email": email.strip()} for email in attendees.split(",")
            ]

        created = service.events().insert(
            calendarId="primary",
            body=event_body,
            sendUpdates="all" if attendees else "none",
        ).execute()

        return (
            f"✅ 予定を作成しました\n"
            f"タイトル: {created.get('summary')}\n"
            f"日時: {start_time} 〜 {end_time}\n"
            f"ID: {created['id']}"
        )

    except Exception as e:
        return f"予定作成エラー: {str(e)}"


def _update_event(
    event_id: str,
    title: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
) -> str:
    """予定を更新する。"""
    service = _get_calendar_service()
    if service is None:
        return _fallback()

    if not event_id:
        return "予定ID(event_id)を指定してください。"

    try:
        # 現在のイベントを取得
        event = service.events().get(
            calendarId="primary",
            eventId=event_id,
        ).execute()

        # 指定されたフィールドのみ更新
        if title:
            event["summary"] = title
        if start_time:
            event["start"] = {"dateTime": start_time + ":00+09:00", "timeZone": _TIMEZONE}
        if end_time:
            event["end"] = {"dateTime": end_time + ":00+09:00", "timeZone": _TIMEZONE}
        if description is not None:
            event["description"] = description
        if location is not None:
            event["location"] = location

        updated = service.events().update(
            calendarId="primary",
            eventId=event_id,
            body=event,
        ).execute()

        return f"✅ 予定を更新しました\nタイトル: {updated.get('summary')}\nID: {updated['id']}"

    except Exception as e:
        return f"予定更新エラー: {str(e)}"


def _delete_event(event_id: str) -> str:
    """予定を削除する。"""
    service = _get_calendar_service()
    if service is None:
        return _fallback()

    if not event_id:
        return "予定ID(event_id)を指定してください。"

    try:
        # 削除前に名前を取得
        event = service.events().get(
            calendarId="primary",
            eventId=event_id,
        ).execute()
        title = event.get("summary", "(タイトルなし)")

        service.events().delete(
            calendarId="primary",
            eventId=event_id,
        ).execute()

        return f"🗑️ 予定「{title}」を削除しました"

    except Exception as e:
        return f"予定削除エラー: {str(e)}"


def _find_free_slots(date: Optional[str] = None, days: int = 5) -> str:
    """空き時間を検索する。"""
    service = _get_calendar_service()
    if service is None:
        return _fallback()

    try:
        if date:
            start_dt = datetime.fromisoformat(date)
        else:
            start_dt = datetime.now()

        time_min = start_dt.replace(hour=0, minute=0, second=0).isoformat() + "+09:00"
        time_max = (start_dt + timedelta(days=days)).replace(hour=23, minute=59, second=59).isoformat() + "+09:00"

        # 予定一覧を取得
        results = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            timeZone=_TIMEZONE,
        ).execute()

        events = results.get("items", [])
        work_start = 9   # 営業時間 9:00
        work_end = 18     # 営業時間 18:00

        lines = [f"🕐 空き時間（{start_dt.strftime('%m/%d')}〜{days}日間、{work_start}:00-{work_end}:00）", ""]

        for day_offset in range(days):
            check_date = start_dt + timedelta(days=day_offset)
            # 土日スキップ
            if check_date.weekday() >= 5:
                continue

            day_str = check_date.strftime("%m/%d(%a)")
            day_events = []

            for event in events:
                e_start = event.get("start", {}).get("dateTime", "")
                if e_start and e_start[:10] == check_date.strftime("%Y-%m-%d"):
                    s_hour = int(e_start[11:13])
                    s_min = int(e_start[14:16])
                    e_end = event.get("end", {}).get("dateTime", "")
                    e_hour = int(e_end[11:13]) if e_end else s_hour + 1
                    e_min = int(e_end[14:16]) if e_end else 0
                    day_events.append((s_hour * 60 + s_min, e_hour * 60 + e_min))

            # 空き時間を計算
            day_events.sort()
            free_slots = []
            cursor = work_start * 60

            for busy_start, busy_end in day_events:
                if busy_start > cursor and busy_start >= work_start * 60:
                    free_slots.append((cursor, min(busy_start, work_end * 60)))
                cursor = max(cursor, busy_end)

            if cursor < work_end * 60:
                free_slots.append((cursor, work_end * 60))

            # 30分以上の空きのみ表示
            slot_strs = []
            for fs, fe in free_slots:
                duration = fe - fs
                if duration >= 30:
                    slot_strs.append(f"{fs // 60:02d}:{fs % 60:02d}〜{fe // 60:02d}:{fe % 60:02d}（{duration}分）")

            if slot_strs:
                lines.append(f"📅 {day_str}")
                for s in slot_strs:
                    lines.append(f"  ✅ {s}")
            else:
                lines.append(f"📅 {day_str} — 空きなし")

        return "\n".join(lines)

    except Exception as e:
        return f"空き時間検索エラー: {str(e)}"


def _fallback() -> str:
    return (
        "Googleカレンダー連携が設定されていません。\n"
        "管理者にOAuth2環境変数の設定を依頼してください。"
    )


def execute(params: dict) -> str:
    """ツール実行のエントリーポイント。"""
    action = params.get("action", "list")

    if action == "list":
        return _list_events(
            params.get("date"),
            params.get("days", 7),
            params.get("query", ""),
        )

    if action == "create":
        return _create_event(
            params.get("title", ""),
            params.get("start_time", ""),
            params.get("end_time"),
            params.get("description", ""),
            params.get("location", ""),
            params.get("attendees", ""),
        )

    if action == "update":
        return _update_event(
            params.get("event_id", ""),
            params.get("title"),
            params.get("start_time"),
            params.get("end_time"),
            params.get("description"),
            params.get("location"),
        )

    if action == "delete":
        return _delete_event(params.get("event_id", ""))

    if action == "free_slots":
        return _find_free_slots(params.get("date"), params.get("days", 5))

    return f"不明なアクション: {action}"
