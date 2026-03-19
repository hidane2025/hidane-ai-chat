# ヒダネ AI社員チャットシステム

## 概要
AI社員11名と対話できるチャットシステム。Web Chat UI + LINE Bot の2チャネル対応。

## 起動方法

```bash
# 基本起動（デモモード）
python3 ai-chat-system/app.py

# Claude API接続（本番モード）
export ANTHROPIC_API_KEY=sk-ant-xxxxx
python3 ai-chat-system/app.py
```

**Web Chat UI**: http://localhost:5555

## 機能

| 機能 | 説明 |
|------|------|
| 自動振り分け | メッセージ内容から最適なAI社員を自動選択 |
| 社員指定 | サイドバーから社員を選んで直接会話 |
| リアルタイムルーティング | 入力中に振り分け先をプレビュー表示 |
| 会話履歴 | セッション内で直近10往復を保持 |
| LINE Bot | LINE Messaging API 経由で同じAI社員と会話 |

## ファイル構成

```
ai-chat-system/
├── app.py              # メインサーバー（Flask）
├── employees.py        # AI社員データ・ルーティングロジック
├── requirements.txt    # Python依存パッケージ
├── LINE_SETUP.md       # LINE Bot セットアップガイド
├── templates/
│   └── chat.html       # Web Chat UIテンプレート
└── static/
    ├── css/chat.css    # スタイルシート
    ├── js/chat.js      # フロントエンドJS
    └── avatars/        # AI社員アバター画像
```

## LINE Bot セットアップ
→ [LINE_SETUP.md](LINE_SETUP.md) を参照
