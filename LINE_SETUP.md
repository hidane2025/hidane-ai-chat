# LINE Bot セットアップガイド

## 1. LINE Developers で Messaging API チャネルを作成

1. https://developers.line.biz/ にログイン
2. 「新規プロバイダー」を作成（例: ヒダネ）
3. 「Messaging API」チャネルを作成
   - チャネル名: ヒダネ AI社員
   - チャネル説明: 株式会社ヒダネのAI社員チャットシステム
4. 「チャネルアクセストークン（長期）」を発行
5. 「チャネルシークレット」をメモ

## 2. 環境変数を設定

```bash
export ANTHROPIC_API_KEY=sk-ant-xxxxx
export LINE_CHANNEL_SECRET=xxxxx
export LINE_CHANNEL_ACCESS_TOKEN=xxxxx
```

## 3. サーバー起動

```bash
cd /Users/kunoyuuki/Desktop/Hidane-AI
python3 ai-chat-system/app.py
```

## 4. ngrok で外部公開（開発時）

```bash
# ngrok インストール: brew install ngrok
ngrok http 5555
```

表示された URL（例: https://xxxx.ngrok-free.app）をコピー

## 5. LINE Developers で Webhook を設定

1. Messaging API設定 → Webhook URL に入力:
   `https://xxxx.ngrok-free.app/line/webhook`
2. 「Webhook の利用」を ON
3. 「検証」ボタンで接続テスト

## 6. 本番デプロイ（将来）

- Railway / Render / Fly.io 等にデプロイ
- 独自ドメイン + SSL で Webhook URL を固定
- 月額無料〜数百円で運用可能

## 料金

- LINE Messaging API: 無料枠 月200通（それ以上は従量課金）
- Claude API: 入力$3/出力$15 per 1M tokens（Sonnet 4）
- ngrok: 無料枠あり（開発用）
