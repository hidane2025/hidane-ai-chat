/**
 * ヒダネ AI社員チャット - フロントエンド
 * チャンネル別会話履歴 + 部署グループチャット対応
 * SSEストリーミング + サジェスチョン + エクスポート統合
 */

// ========== State ==========
const state = {
    employees: [],
    departments: [],
    // チャンネル管理: { channelId: { type, name, messages: [], ... } }
    channels: {},
    currentChannel: null,   // "emp_ソウ" | "dept_営業部" | "auto"
    autoRoute: false,
    sending: false,
    activeStream: null,     // 現在アクティブなChatStreamインスタンス
};

// ========== DOM ==========
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const dom = {};
function cacheDom() {
    dom.sidebar = $("#sidebar");
    dom.sidebarOpen = $("#sidebarOpen");
    dom.sidebarClose = $("#sidebarClose");
    dom.channelList = $("#channelList");
    dom.headerAvatar = $("#headerAvatar");
    dom.headerName = $("#headerName");
    dom.headerRole = $("#headerRole");
    dom.chatArea = $("#chatArea");
    dom.messages = $("#messages");
    dom.welcomeMessage = $("#welcomeMessage");
    dom.messageInput = $("#messageInput");
    dom.sendBtn = $("#sendBtn");
    dom.btnAutoRoute = $("#btnAutoRoute");
    dom.routingPreview = $("#routingPreview");
    dom.routeBadge = $("#routeBadge");
    dom.routeText = $("#routeText");
    dom.modeIndicator = $("#modeIndicator");
}

// ========== Init ==========
async function init() {
    cacheDom();
    await Promise.all([loadEmployees(), loadDepartments()]);
    initChannels();
    renderSidebar();
    setupEventListeners();
    checkApiStatus();
    initExportMenu();
    injectStreamingStyles();
    // デフォルトで自動振り分けチャンネルを選択
    switchChannel("auto");
}

async function loadEmployees() {
    try {
        const res = await fetch("/api/employees");
        state.employees = await res.json();
    } catch (e) {
        console.error("社員データ読み込みエラー:", e);
    }
}

async function loadDepartments() {
    try {
        const res = await fetch("/api/departments");
        state.departments = await res.json();
    } catch (e) {
        console.error("部署データ読み込みエラー:", e);
    }
}

function initChannels() {
    // 自動振り分けチャンネル
    state.channels["auto"] = {
        type: "auto",
        name: "自動振り分け",
        icon: "🤖",
        color: "#6C5CE7",
        messages: [],
    };

    // 部署グループチャンネル
    for (const dept of state.departments) {
        const id = `dept_${dept.name}`;
        state.channels[id] = {
            type: "department",
            name: dept.name,
            icon: dept.icon,
            color: dept.color,
            description: dept.description,
            members: dept.members,
            messages: [],
        };
    }

    // 個別社員チャンネル
    for (const emp of state.employees) {
        const id = `emp_${emp.name}`;
        state.channels[id] = {
            type: "employee",
            name: emp.name,
            avatar: emp.avatar,
            color: emp.color,
            role: emp.role,
            empId: emp.id,
            messages: [],
        };
    }
}

async function checkApiStatus() {
    try {
        const res = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "ping", session_id: "check" }),
            credentials: "same-origin",
        });
        const data = await res.json();
        const isDemo = data.message.includes("デモモード");
        const indicator = dom.modeIndicator;
        const dot = indicator.querySelector(".mode-dot");
        if (isDemo) {
            dot.classList.add("offline");
            indicator.querySelector("span:last-child").textContent = "デモモード（API未設定）";
        } else {
            dot.classList.remove("offline");
            indicator.querySelector("span:last-child").textContent = "Claude API 接続中";
        }
    } catch (e) {
        const indicator = dom.modeIndicator;
        indicator.querySelector(".mode-dot").classList.add("offline");
        indicator.querySelector("span:last-child").textContent = "接続エラー";
    }
}

// ========== Export Menu Integration ==========
function initExportMenu() {
    const headerActions = document.querySelector(".header-actions");
    if (headerActions && typeof createExportMenu === "function") {
        createExportMenu(headerActions);
    }
}

// ========== Streaming Styles ==========
function injectStreamingStyles() {
    const style = document.createElement("style");
    style.textContent = `
        .error-bubble {
            background: rgba(255, 59, 48, 0.1) !important;
            border-left-color: #FF3B30 !important;
            color: var(--text-primary);
        }
        .retry-btn {
            background: var(--accent);
            color: white;
            border: none;
            border-radius: var(--radius-sm, 6px);
            padding: 6px 14px;
            margin-top: 8px;
            font-size: 13px;
            font-family: inherit;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        .retry-btn:hover {
            opacity: 0.85;
        }
        .msg-bubble.streaming {
            border-left-style: solid;
        }
        .msg-bubble.streaming::after {
            content: "▍";
            animation: blink-cursor 0.8s step-end infinite;
            color: var(--text-secondary);
        }
        @keyframes blink-cursor {
            50% { opacity: 0; }
        }
        .suggestions-area {
            padding: 4px 16px 8px;
        }
        .tool-indicator {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 6px 10px;
            margin: 6px 0;
            background: rgba(108, 92, 231, 0.1);
            border-radius: 6px;
            font-size: 12px;
            color: #a29bfe;
            border-left: 2px solid #6C5CE7;
        }
        .tool-indicator.tool-done {
            background: rgba(0, 184, 148, 0.1);
            color: #00b894;
            border-left-color: #00b894;
        }
        .tool-spinner {
            display: inline-block;
            width: 12px;
            height: 12px;
            border: 2px solid rgba(108, 92, 231, 0.3);
            border-top-color: #6C5CE7;
            border-radius: 50%;
            animation: tool-spin 0.6s linear infinite;
        }
        .tool-done-icon::before {
            content: "\\2713";
            font-weight: bold;
        }
        @keyframes tool-spin {
            to { transform: rotate(360deg); }
        }
    `;
    document.head.appendChild(style);
}

// ========== Sidebar Render ==========
function renderSidebar() {
    let html = "";

    // 自動振り分け
    html += `
        <div class="channel-section-title">チャット</div>
        <div class="channel-card ${state.currentChannel === 'auto' ? 'active' : ''}"
             data-channel="auto" style="border-left-color: #6C5CE7">
            <div class="channel-icon">🤖</div>
            <div class="info">
                <div class="name">自動振り分け</div>
                <div class="role">内容に応じて最適な社員が対応</div>
            </div>
        </div>
    `;

    // 部署グループ
    html += `<div class="channel-section-title">部署グループ</div>`;
    for (const dept of state.departments) {
        const id = `dept_${dept.name}`;
        const ch = state.channels[id];
        const memberAvatars = dept.members.slice(0, 3).map((m) =>
            `<img class="mini-avatar" src="/static/avatars/${m.avatar}" alt="${m.name}"
                  onerror="this.style.display='none'" title="${m.name}">`
        ).join("");
        const msgCount = ch.messages.length;
        html += `
            <div class="channel-card ${state.currentChannel === id ? 'active' : ''}"
                 data-channel="${id}" style="border-left-color: ${dept.color}">
                <div class="channel-icon">${dept.icon}</div>
                <div class="info">
                    <div class="name">${dept.name}</div>
                    <div class="role">${dept.description}</div>
                    <div class="member-avatars">${memberAvatars}</div>
                </div>
                ${msgCount > 0 ? `<span class="msg-count">${msgCount}</span>` : ''}
            </div>
        `;
    }

    // 個別社員
    html += `<div class="channel-section-title">個別チャット</div>`;
    for (const emp of state.employees) {
        const id = `emp_${emp.name}`;
        const ch = state.channels[id];
        const msgCount = ch.messages.length;
        html += `
            <div class="channel-card ${state.currentChannel === id ? 'active' : ''}"
                 data-channel="${id}" style="border-left-color: ${emp.color}">
                <img class="avatar" src="/static/avatars/${emp.avatar}" alt="${emp.name}" loading="lazy"
                     onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 40 40%22><rect fill=%22${encodeURIComponent(emp.color)}%22 width=%2240%22 height=%2240%22 rx=%2220%22/><text x=%2220%22 y=%2226%22 text-anchor=%22middle%22 fill=%22white%22 font-size=%2216%22>${emp.name[0]}</text></svg>'">
                <div class="info">
                    <div class="name">
                        ${emp.name}
                        <span class="id-badge">${emp.id}</span>
                    </div>
                    <div class="role">${emp.role}</div>
                </div>
                ${msgCount > 0 ? `<span class="msg-count">${msgCount}</span>` : ''}
            </div>
        `;
    }

    dom.channelList.innerHTML = html;

    // クリックイベント
    $$(".channel-card").forEach((card) => {
        card.addEventListener("click", () => {
            switchChannel(card.dataset.channel);
            closeSidebar();
        });
    });
}

// ========== Channel Switching ==========
function switchChannel(channelId) {
    // アクティブなストリーミングがあれば中断
    if (state.activeStream) {
        state.activeStream.abort();
        state.activeStream = null;
    }

    state.currentChannel = channelId;
    const ch = state.channels[channelId];
    if (!ch) return;

    // ヘッダー更新
    if (ch.type === "auto") {
        dom.headerAvatar.style.display = "none";
        dom.headerName.textContent = "🤖 自動振り分け";
        dom.headerName.style.color = "#6C5CE7";
        dom.headerRole.textContent = "メッセージ内容に応じて最適な社員が対応";
        state.autoRoute = true;
    } else if (ch.type === "department") {
        dom.headerAvatar.style.display = "none";
        dom.headerName.textContent = `${ch.icon} ${ch.name}`;
        dom.headerName.style.color = ch.color;
        dom.headerRole.textContent = ch.description;
        state.autoRoute = false;
    } else {
        dom.headerAvatar.style.display = "";
        dom.headerAvatar.src = `/static/avatars/${ch.avatar}`;
        dom.headerAvatar.onerror = function () {
            this.style.display = "none";
        };
        dom.headerName.textContent = ch.name;
        dom.headerName.style.color = ch.color;
        dom.headerRole.textContent = ch.role;
        state.autoRoute = false;
    }

    // 自動振り分けボタン表示
    dom.btnAutoRoute.style.display = ch.type === "auto" ? "" : "none";

    // メッセージ表示切替
    renderMessages(channelId);

    // サイドバーのアクティブ更新
    $$(".channel-card").forEach((card) => {
        card.classList.toggle("active", card.dataset.channel === channelId);
    });

    // サジェスチョンをクリア
    clearSuggestionsContainer();

    dom.messageInput.focus();
}

function renderMessages(channelId) {
    const ch = state.channels[channelId];
    dom.messages.innerHTML = "";

    if (ch.messages.length === 0) {
        dom.welcomeMessage.style.display = "";
        // ウェルカムメッセージをチャンネルに合わせる
        const welcomeTitle = $("#welcomeTitle");
        const welcomeDesc = $("#welcomeDesc");
        if (ch.type === "auto") {
            welcomeTitle.textContent = "ヒダネ AI社員チャット";
            welcomeDesc.innerHTML = "メッセージを送信すると<br>内容に応じて最適なAI社員が自動で対応します。";
        } else if (ch.type === "department") {
            welcomeTitle.textContent = `${ch.icon} ${ch.name}`;
            const memberNames = ch.members.map((m) => m.name).join("・");
            welcomeDesc.innerHTML = `${ch.description}<br>メンバー: ${memberNames}`;
        } else {
            welcomeTitle.textContent = ch.name;
            welcomeDesc.textContent = `${ch.role} との個別チャット`;
        }
    } else {
        dom.welcomeMessage.style.display = "none";
        for (const msg of ch.messages) {
            appendMessageDom(msg.type, msg.text, msg.data);
        }
    }
    scrollToBottom();
}

// ========== Suggestions Integration ==========

/**
 * サジェスチョンコンテナを取得（なければ作成）
 */
function getSuggestionsContainer() {
    let container = document.getElementById("suggestionsContainer");
    if (!container) {
        container = document.createElement("div");
        container.id = "suggestionsContainer";
        container.className = "suggestions-area";
        // messages の直後に挿入
        dom.messages.parentNode.insertBefore(container, dom.messages.nextSibling);
    }
    return container;
}

/**
 * サジェスチョンをクリア
 */
function clearSuggestionsContainer() {
    const container = document.getElementById("suggestionsContainer");
    if (container && typeof clearSuggestions === "function") {
        clearSuggestions(container);
    }
}

/**
 * AI応答後にサジェスチョンを表示
 */
function showSuggestionsAfterResponse() {
    if (typeof renderSuggestions !== "function") return;

    setTimeout(() => {
        const container = getSuggestionsContainer();
        const ch = state.channels[state.currentChannel];
        if (!ch) return;

        const channelType = ch.type === "employee" ? "employee" : "auto";
        const empName = ch.type === "employee" ? ch.name : null;
        renderSuggestions(channelType, empName, container);
    }, 500);
}

// ========== Streaming Support ==========

/**
 * ストリーミング用のメッセージバブルを作成して返す
 * @param {object} streamData - { employee, employee_color, avatar, employee_role }
 * @returns {HTMLElement}
 */
function createStreamBubble(streamData) {
    const div = document.createElement("div");
    div.className = "message ai";
    const time = new Date().toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });

    const employee = streamData.employee || "ソウ";
    const employeeColor = streamData.employee_color || "#6C5CE7";
    const avatar = streamData.avatar || "桐生ソウ_アバター.png";
    const employeeRole = streamData.employee_role || "";

    div.innerHTML = `
        <img class="msg-avatar" src="/static/avatars/${avatar}" alt="${employee}"
             onerror="this.style.display='none'">
        <div class="msg-content">
            <div class="msg-header">
                <span class="msg-name" style="color:${employeeColor}">${employee}</span>
                ${employeeRole ? `<span class="msg-role-tag">${employeeRole}</span>` : ''}
                <span class="msg-time">${time}</span>
            </div>
            <div class="msg-bubble streaming" style="border-left-color:${employeeColor}"></div>
        </div>
    `;

    return div;
}

/**
 * エラー表示（リトライボタン付き）
 * @param {string} text - エラーメッセージ
 * @param {Function|null} retryFn - 再試行関数
 */
function showError(text, retryFn) {
    const div = document.createElement("div");
    div.className = "message error";
    div.innerHTML = `
        <div class="msg-content">
            <div class="msg-bubble error-bubble">
                <span>${escapeHtml(text)}</span>
                ${retryFn ? '<button class="retry-btn">再試行</button>' : ''}
            </div>
        </div>
    `;

    if (retryFn) {
        const btn = div.querySelector(".retry-btn");
        btn.addEventListener("click", () => {
            div.remove();
            retryFn();
        });
    }

    dom.messages.appendChild(div);
    scrollToBottom();
}

/**
 * SSEストリーミングでメッセージを送信
 * @param {string} text - ユーザーメッセージ
 * @param {string} channelId - チャンネルID
 * @param {object} ch - チャンネルオブジェクト
 * @param {HTMLElement} typingEl - タイピングインジケーター要素
 */
function sendViaStreaming(text, channelId, ch, typingEl) {
    const stream = new ChatStream();
    state.activeStream = stream;

    let streamBubble = null;
    let fullText = "";
    let streamMeta = {
        employee: null,
        employee_color: null,
        avatar: null,
        employee_role: null,
    };

    stream.on("stream-start", () => {
        // stream-start はconnect直後に発火するのでバブルは最初のトークンで作成
    });

    stream.on("stream-token", (data) => {
        // 最初のトークンでバブルを作成
        if (!streamBubble) {
            typingEl.remove();

            // トークンから社員情報を取得
            streamMeta = {
                employee: data.employee || streamMeta.employee || "ソウ",
                employee_color: data.employee_color || streamMeta.employee_color || "#6C5CE7",
                avatar: data.avatar || streamMeta.avatar || "桐生ソウ_アバター.png",
                employee_role: data.employee_role || streamMeta.employee_role || "",
            };

            streamBubble = createStreamBubble(streamMeta);
            dom.messages.appendChild(streamBubble);
        }

        // 社員情報が途中で届く場合を更新
        if (data.employee && data.employee !== streamMeta.employee) {
            streamMeta = {
                ...streamMeta,
                employee: data.employee,
                employee_color: data.employee_color || streamMeta.employee_color,
                avatar: data.avatar || streamMeta.avatar,
                employee_role: data.employee_role || streamMeta.employee_role,
            };
            const nameEl = streamBubble.querySelector(".msg-name");
            if (nameEl) {
                nameEl.textContent = streamMeta.employee;
                nameEl.style.color = streamMeta.employee_color;
            }
        }

        // テキスト蓄積＋表示更新
        fullText += (data.token || "");
        const bubbleContent = streamBubble.querySelector(".msg-bubble");
        if (bubbleContent) {
            bubbleContent.innerHTML = renderMessageContent(fullText);
            // streaming クラスを維持（カーソル表示）
            bubbleContent.classList.add("streaming");
        }
        scrollToBottom();
    });

    stream.on("stream-pdf", (data) => {
        // PDF添付がストリーム中に届いた場合、テキストに追加
        const pdfTag = `[PDF:${data.filename}:${data.title}]`;
        fullText += pdfTag;
        if (streamBubble) {
            const bubbleContent = streamBubble.querySelector(".msg-bubble");
            if (bubbleContent) {
                bubbleContent.innerHTML = renderMessageContent(fullText);
                bubbleContent.classList.add("streaming");
            }
            scrollToBottom();
        }
    });

    stream.on("stream-tool-start", (data) => {
        // ツール実行開始の表示
        const toolNames = {
            knowledge_search: "ナレッジを検索中",
            calculator: "計算中",
            file_reader: "ファイルを確認中",
            web_search: "Webを検索中",
            document_writer: "文書を作成中",
            google_drive: "Google Driveを検索中",
        };
        const label = toolNames[data.tool] || `${data.tool}を実行中`;

        if (!streamBubble) {
            typingEl.remove();
            streamMeta = {
                employee: streamMeta.employee || "ソウ",
                employee_color: streamMeta.employee_color || "#6C5CE7",
                avatar: streamMeta.avatar || "桐生ソウ_アバター.png",
                employee_role: streamMeta.employee_role || "",
            };
            streamBubble = createStreamBubble(streamMeta);
            dom.messages.appendChild(streamBubble);
        }

        const bubbleContent = streamBubble.querySelector(".msg-bubble");
        if (bubbleContent) {
            const indicator = document.createElement("div");
            indicator.className = "tool-indicator";
            indicator.id = `tool-${data.tool_use_id}`;
            indicator.innerHTML = `<span class="tool-spinner"></span> ${label}...`;
            bubbleContent.appendChild(indicator);
            scrollToBottom();
        }
    });

    stream.on("stream-tool-result", (data) => {
        // ツール完了表示の更新
        if (streamBubble) {
            const indicator = streamBubble.querySelector(`#tool-${data.tool_use_id}`);
            if (indicator) {
                indicator.innerHTML = `<span class="tool-done-icon"></span> ${data.tool} 完了`;
                indicator.classList.add("tool-done");
            }
        }
    });

    stream.on("stream-done", (data) => {
        state.activeStream = null;

        // 最終テキストで更新
        const finalText = data.full_text || fullText;

        if (streamBubble) {
            const bubbleContent = streamBubble.querySelector(".msg-bubble");
            if (bubbleContent) {
                bubbleContent.innerHTML = renderMessageContent(finalText);
                bubbleContent.classList.remove("streaming");
            }
        } else {
            // トークンが1つも届かずに完了した場合
            typingEl.remove();
        }

        // チャンネル履歴に保存
        const aiMsg = {
            type: "ai",
            text: finalText,
            data: {
                message: finalText,
                employee: streamMeta.employee || "ソウ",
                employee_color: streamMeta.employee_color || "#6C5CE7",
                avatar: streamMeta.avatar || "桐生ソウ_アバター.png",
                employee_role: streamMeta.employee_role || "",
            },
        };
        ch.messages.push(aiMsg);
        updateSidebarCount(channelId);

        // 送信状態をリセット
        state.sending = false;
        dom.sendBtn.disabled = !dom.messageInput.value.trim();

        // サジェスチョン表示
        showSuggestionsAfterResponse();
    });

    stream.on("stream-error", (data) => {
        state.activeStream = null;
        typingEl.remove();

        // ストリーミング途中でエラーが出た場合、バブルがあれば削除
        if (streamBubble) {
            streamBubble.remove();
            streamBubble = null;
        }

        console.error("[chat] stream error, falling back to regular API:", data.error);

        // 通常APIにフォールバック
        fallbackToRegularApi(text, channelId);
    });

    // 接続パラメータ構築
    const employee = ch.type === "employee" ? ch.name : null;
    const options = {};
    if (ch.type === "department") {
        options.department = ch.name;
    }

    stream.connect(text, employee, channelId, options);
}

/**
 * 通常API（非ストリーミング）でメッセージを送信（フォールバック用）
 * @param {string} text - ユーザーメッセージ
 * @param {string} channelId - チャンネルID
 */
async function fallbackToRegularApi(text, channelId) {
    const ch = state.channels[channelId];
    const typingEl = showTyping(channelId);

    try {
        let res;
        if (ch.type === "department") {
            res = await fetch("/api/chat/department", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    message: text,
                    department: ch.name,
                    session_id: channelId,
                }),
                credentials: "same-origin",
            });
        } else if (ch.type === "employee") {
            res = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    message: text,
                    employee: ch.name,
                    session_id: channelId,
                }),
                credentials: "same-origin",
            });
        } else {
            res = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    message: text,
                    session_id: channelId,
                }),
                credentials: "same-origin",
            });
        }

        const data = await res.json();
        typingEl.remove();

        // AI応答保存＋表示
        const aiMsg = { type: "ai", text: data.message, data };
        ch.messages.push(aiMsg);
        appendMessageDom("ai", data.message, data);

        // サイドバーのメッセージカウント更新
        updateSidebarCount(channelId);

        // サジェスチョン表示
        showSuggestionsAfterResponse();

    } catch (e) {
        typingEl.remove();

        // エラー表示（リトライボタン付き）
        showError("接続エラーが発生しました。", () => {
            fallbackToRegularApi(text, channelId);
        });
    }

    state.sending = false;
    dom.sendBtn.disabled = !dom.messageInput.value.trim();
}

// ========== Chat ==========
async function sendMessage() {
    const text = dom.messageInput.value.trim();
    if (!text || state.sending) return;

    const channelId = state.currentChannel;
    const ch = state.channels[channelId];

    state.sending = true;
    dom.sendBtn.disabled = true;
    dom.welcomeMessage.style.display = "none";
    dom.routingPreview.style.display = "none";

    // サジェスチョンをクリア
    clearSuggestionsContainer();

    // ユーザーメッセージ保存＋表示
    const userMsg = { type: "user", text, data: null };
    ch.messages.push(userMsg);
    appendMessageDom("user", text, null);
    dom.messageInput.value = "";
    autoResizeTextarea();

    // タイピングインジケーター
    const typingEl = showTyping(channelId);

    // ストリーミング可能か判定（部署チャットは通常APIのまま）
    const canStream = typeof ChatStream !== "undefined" && ch.type !== "department";

    if (canStream) {
        // SSEストリーミングで送信
        sendViaStreaming(text, channelId, ch, typingEl);
    } else {
        // 通常API（部署チャットまたはChatStream未ロード時）
        typingEl.remove();
        await fallbackToRegularApi(text, channelId);
    }
}

function appendMessageDom(type, text, data) {
    const div = document.createElement("div");
    div.className = `message ${type}`;
    const time = new Date().toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });

    if (type === "ai" && data) {
        div.innerHTML = `
            <img class="msg-avatar" src="/static/avatars/${data.avatar}" alt="${data.employee}"
                 onerror="this.style.display='none'">
            <div class="msg-content">
                <div class="msg-header">
                    <span class="msg-name" style="color:${data.employee_color}">${data.employee}</span>
                    ${data.employee_role ? `<span class="msg-role-tag">${data.employee_role}</span>` : ''}
                    <span class="msg-time">${time}</span>
                </div>
                <div class="msg-bubble" style="border-left-color:${data.employee_color}">
                    ${renderMessageContent(text)}
                </div>
            </div>
        `;
    } else {
        div.innerHTML = `
            <div class="msg-content">
                <div class="msg-header">
                    <span class="msg-name" style="color:var(--accent)">あなた</span>
                    <span class="msg-time">${time}</span>
                </div>
                <div class="msg-bubble">${escapeHtml(text)}</div>
            </div>
        `;
    }

    dom.messages.appendChild(div);
    scrollToBottom();
}

function showTyping(channelId) {
    const ch = state.channels[channelId];
    const div = document.createElement("div");
    div.className = "typing-indicator";

    let avatarSrc = "";
    if (ch.type === "employee") {
        avatarSrc = ch.avatar || "";
    }

    div.innerHTML = `
        ${avatarSrc ? `<img class="msg-avatar" src="/static/avatars/${avatarSrc}" alt="" onerror="this.style.display='none'">` : ''}
        <div class="typing-dots">
            <span></span><span></span><span></span>
        </div>
    `;
    dom.messages.appendChild(div);
    scrollToBottom();
    return div;
}

function updateSidebarCount(channelId) {
    const card = $(`.channel-card[data-channel="${channelId}"]`);
    if (!card) return;
    const ch = state.channels[channelId];
    let countEl = card.querySelector(".msg-count");
    const aiCount = ch.messages.filter((m) => m.type === "ai").length;
    if (aiCount > 0) {
        if (!countEl) {
            countEl = document.createElement("span");
            countEl.className = "msg-count";
            card.appendChild(countEl);
        }
        countEl.textContent = aiCount;
    }
}

function scrollToBottom() {
    dom.chatArea.scrollTop = dom.chatArea.scrollHeight;
}

// ========== Routing Preview ==========
let routeTimer = null;

async function updateRoutingPreview(text) {
    if (!text.trim() || state.currentChannel !== "auto") {
        dom.routingPreview.style.display = "none";
        return;
    }

    clearTimeout(routeTimer);
    routeTimer = setTimeout(async () => {
        try {
            const payload = { message: text };
            const ch = state.channels[state.currentChannel];
            if (ch && ch.type === "department") {
                payload.department = ch.name;
            }
            const res = await fetch("/api/route", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const data = await res.json();

            dom.routeBadge.textContent = data.employee;
            dom.routeBadge.style.background = data.color;
            dom.routeText.textContent = `${data.role} が対応します`;
            dom.routingPreview.style.display = "flex";
        } catch (e) {
            dom.routingPreview.style.display = "none";
        }
    }, 300);
}

// ========== Event Listeners ==========
function setupEventListeners() {
    dom.sendBtn.addEventListener("click", sendMessage);
    dom.messageInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            sendMessage();
        }
    });

    dom.messageInput.addEventListener("input", () => {
        const hasText = dom.messageInput.value.trim().length > 0;
        dom.sendBtn.disabled = !hasText;
        autoResizeTextarea();
        updateRoutingPreview(dom.messageInput.value);
    });

    // 自動振り分けボタン（表示のみ、autoチャンネルのインジケーター）
    dom.btnAutoRoute.addEventListener("click", () => {
        switchChannel("auto");
    });

    dom.sidebarOpen.addEventListener("click", openSidebar);
    dom.sidebarClose.addEventListener("click", closeSidebar);

    // クイックアクション
    $$(".quick-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            dom.messageInput.value = btn.dataset.msg;
            dom.sendBtn.disabled = false;
            dom.welcomeMessage.style.display = "none";
            dom.messageInput.focus();
        });
    });
}

function autoResizeTextarea() {
    const ta = dom.messageInput;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
}

function openSidebar() { dom.sidebar.classList.add("open"); }
function closeSidebar() { dom.sidebar.classList.remove("open"); }

// ========== Utilities ==========
function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function renderMessageContent(text) {
    // まずHTMLエスケープ
    let html = escapeHtml(text);
    // [PDF:filename.pdf:表示名] をPDFカードに変換
    html = html.replace(
        /\[PDF:([^\]:]+\.pdf):([^\]]+)\]/g,
        (_, filename, title) => {
            const url = `/api/files/${encodeURIComponent(filename)}`;
            return `<div class="pdf-card">
                <div class="pdf-card-icon">📄</div>
                <div class="pdf-card-info">
                    <div class="pdf-card-title">${escapeHtml(title)}</div>
                    <div class="pdf-card-filename">${escapeHtml(filename)}</div>
                </div>
                <a href="${url}" target="_blank" class="pdf-card-btn" title="PDFを開く">開く</a>
                <a href="${url}" download class="pdf-card-btn pdf-dl" title="ダウンロード">⬇</a>
            </div>`;
        }
    );
    return html;
}

// ========== Start ==========
document.addEventListener("DOMContentLoaded", init);
