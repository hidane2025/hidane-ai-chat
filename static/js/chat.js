/**
 * ヒダネ AI社員チャット - フロントエンド
 * チャンネル別会話履歴 + 部署グループチャット対応
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

    // ユーザーメッセージ保存＋表示
    const userMsg = { type: "user", text, data: null };
    ch.messages.push(userMsg);
    appendMessageDom("user", text, null);
    dom.messageInput.value = "";
    autoResizeTextarea();

    // タイピングインジケーター
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
            });
        } else {
            // auto
            res = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    message: text,
                    session_id: channelId,
                }),
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

    } catch (e) {
        typingEl.remove();
        const errData = {
            employee: "ソウ",
            employee_color: "#6C5CE7",
            avatar: "桐生ソウ_アバター.png",
        };
        const errMsg = { type: "ai", text: "接続エラーが発生しました。", data: errData };
        ch.messages.push(errMsg);
        appendMessageDom("ai", errMsg.text, errData);
    }

    state.sending = false;
    dom.sendBtn.disabled = !dom.messageInput.value.trim();
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
