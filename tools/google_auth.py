"""
Google OAuth2 共通認証モジュール
Gmail・カレンダー等、ユーザーアカウントへのアクセスに使用。
リフレッシュトークンを環境変数から取得し、アクセストークンを自動更新する。
"""

import os
import json

# OAuth2 クライアント情報（環境変数から取得）
_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
_REFRESH_TOKEN = os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN", "")

# キャッシュ
_credentials_cache = None


def get_user_credentials(scopes: list[str]):
    """OAuth2ユーザー認証情報を返す。リフレッシュトークンからアクセストークンを取得。"""
    global _credentials_cache

    if _credentials_cache is not None and _credentials_cache.valid:
        return _credentials_cache

    if not _CLIENT_ID or not _CLIENT_SECRET or not _REFRESH_TOKEN:
        return None

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = Credentials(
            token=None,
            refresh_token=_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=_CLIENT_ID,
            client_secret=_CLIENT_SECRET,
            scopes=scopes,
        )
        creds.refresh(Request())
        _credentials_cache = creds
        return creds

    except Exception as e:
        print(f"[google_auth] OAuth2認証エラー: {e}")
        return None


def is_configured() -> bool:
    """OAuth2が設定済みかどうかを返す。"""
    return bool(_CLIENT_ID and _CLIENT_SECRET and _REFRESH_TOKEN)
