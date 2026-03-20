/**
 * ヒダネ AI社員チャット - SSEストリーミングクライアント
 * POST fetch + ReadableStream で SSE を処理
 */

class ChatStream {
    constructor() {
        this._controller = null;
        this._retryCount = 0;
        this._maxRetries = 3;
        this._listeners = {};
    }

    /**
     * イベントリスナー登録
     * @param {string} event - 'stream-start' | 'stream-token' | 'stream-pdf' | 'stream-done' | 'stream-error'
     * @param {Function} callback
     */
    on(event, callback) {
        if (!this._listeners[event]) {
            this._listeners[event] = [];
        }
        this._listeners[event] = [...this._listeners[event], callback];
        return this;
    }

    /**
     * イベントリスナー解除
     * @param {string} event
     * @param {Function} callback
     */
    off(event, callback) {
        if (!this._listeners[event]) return this;
        this._listeners[event] = this._listeners[event].filter(
            (cb) => cb !== callback
        );
        return this;
    }

    /**
     * イベント発火
     * @param {string} event
     * @param {*} data
     */
    _emit(event, data) {
        const handlers = this._listeners[event];
        if (!handlers) return;
        for (const handler of handlers) {
            try {
                handler(data);
            } catch (err) {
                console.error(`[ChatStream] handler error for '${event}':`, err);
            }
        }
    }

    /**
     * ストリーミング接続を開始
     * @param {string} message - ユーザーメッセージ
     * @param {string|null} employee - 社員名（null で自動振り分け）
     * @param {string} sessionId - セッションID
     * @param {object} [options] - 追加オプション { department }
     */
    async connect(message, employee, sessionId, options = {}) {
        this._retryCount = 0;
        await this._attemptConnect(message, employee, sessionId, options);
    }

    /**
     * 接続試行（リトライ対応）
     */
    async _attemptConnect(message, employee, sessionId, options) {
        const abortController = new AbortController();
        this._controller = abortController;

        const body = {
            message,
            session_id: sessionId,
        };
        if (employee) {
            body.employee = employee;
        }
        if (options.department) {
            body.department = options.department;
        }

        try {
            this._emit("stream-start", { message, employee, sessionId });

            const response = await fetch("/api/chat/stream", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
                signal: abortController.signal,
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                // 最後の不完全行はバッファに残す
                buffer = lines.pop() || "";

                for (const line of lines) {
                    this._processSSELine(line);
                }
            }

            // バッファに残った最終行を処理
            if (buffer.trim()) {
                this._processSSELine(buffer);
            }

            this._emit("stream-done", { sessionId });
            this._retryCount = 0;
        } catch (err) {
            if (abortController.signal.aborted) {
                // ユーザーによる明示的キャンセル
                return;
            }

            console.error("[ChatStream] connection error:", err);

            if (this._retryCount < this._maxRetries) {
                this._retryCount += 1;
                const delay = Math.min(1000 * Math.pow(2, this._retryCount - 1), 5000);
                console.log(
                    `[ChatStream] retry ${this._retryCount}/${this._maxRetries} in ${delay}ms`
                );
                await this._wait(delay);
                await this._attemptConnect(message, employee, sessionId, options);
            } else {
                this._emit("stream-error", {
                    error: err.message || "接続エラーが発生しました",
                    retries: this._retryCount,
                });
            }
        }
    }

    /**
     * SSE行をパースしてイベント発火
     * @param {string} line
     */
    _processSSELine(line) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith(":")) {
            // 空行またはコメント行はスキップ
            return;
        }

        if (!trimmed.startsWith("data: ")) {
            return;
        }

        const jsonStr = trimmed.slice(6);

        // "[DONE]" 終端マーカー
        if (jsonStr === "[DONE]") {
            return;
        }

        try {
            const payload = JSON.parse(jsonStr);

            switch (payload.type) {
                case "token":
                    this._emit("stream-token", {
                        token: payload.token || "",
                        employee: payload.employee || null,
                        employee_color: payload.employee_color || null,
                        avatar: payload.avatar || null,
                    });
                    break;

                case "pdf":
                    this._emit("stream-pdf", {
                        filename: payload.filename,
                        title: payload.title,
                        url: payload.url,
                    });
                    break;

                case "error":
                    this._emit("stream-error", {
                        error: payload.message || "サーバーエラー",
                    });
                    break;

                case "done":
                    // サーバーが明示的に done を送る場合
                    this._emit("stream-done", {
                        sessionId: payload.session_id || null,
                        full_text: payload.full_text || null,
                    });
                    break;

                default:
                    // 不明な type はトークンとして扱う
                    if (payload.token) {
                        this._emit("stream-token", {
                            token: payload.token,
                            employee: payload.employee || null,
                            employee_color: payload.employee_color || null,
                            avatar: payload.avatar || null,
                        });
                    }
                    break;
            }
        } catch (e) {
            // JSON パース失敗 → プレーンテキストとして扱う
            this._emit("stream-token", { token: jsonStr });
        }
    }

    /**
     * ストリーミングを中断
     */
    abort() {
        if (this._controller) {
            this._controller.abort();
            this._controller = null;
        }
    }

    /**
     * 待機ユーティリティ
     * @param {number} ms
     * @returns {Promise<void>}
     */
    _wait(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }
}

/**
 * ストリーミングトークンを DOM 要素に逐次追記するヘルパー
 * appendMessageDom で作成した .msg-bubble 要素を targetElement として渡す
 *
 * @param {ChatStream} stream - ChatStream インスタンス
 * @param {HTMLElement} targetElement - テキストを追記する要素
 * @param {object} [options] - { charDelay: number } 1文字あたりの遅延（ms）
 * @returns {Function} cleanup - リスナー解除用関数
 */
function attachStreamToElement(stream, targetElement, options = {}) {
    const charDelay = options.charDelay || 0;
    let queue = [];
    let isProcessing = false;

    async function processQueue() {
        if (isProcessing) return;
        isProcessing = true;

        while (queue.length > 0) {
            const token = queue.shift();
            if (charDelay > 0) {
                for (const char of token) {
                    targetElement.textContent += char;
                    if (charDelay > 0) {
                        await new Promise((r) => setTimeout(r, charDelay));
                    }
                }
            } else {
                targetElement.textContent += token;
            }
        }

        isProcessing = false;
    }

    function onToken(data) {
        queue = [...queue, data.token];
        processQueue();
    }

    stream.on("stream-token", onToken);

    return function cleanup() {
        stream.off("stream-token", onToken);
    };
}
