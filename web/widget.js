// The Grand Meridian — concierge chat widget.
//
// Vanilla JS, no build step. Three deps loaded by index.html before this file:
// `marked` (markdown parser), `DOMPurify` (sanitizer), and auth.js which
// supplies window.GM_AUTH. User messages stay escaped (no markdown).
//
// The agent is expected to sit behind the platform's OAuth2 gateway. This widget
// attaches whatever Authorization header GM_AUTH provides and does nothing else
// about auth — the gateway validates, the agent has no auth logic of its own.
// Run `web/serve.py --no-auth` to drive an unprotected agent instead.
(() => {
  "use strict";

  // Endpoint resolution precedence:
  //   1. ?agent=<url>      — overrides and persists to localStorage. ?agent=reset clears.
  //   2. localStorage      — sticky across reloads once set via the query param.
  //   3. /auth/config      — served by web/serve.py, the normal path.
  //   4. window.GRAND_MERIDIAN_AGENT_URL (the committed default in index.html).
  //   5. http://localhost:8000/chat.
  // In a deployed setup this should be the gateway URL, not the agent's own address.
  const endpointOverride = (() => {
    const LS_KEY = "gmAgentUrl";
    const fallback = null;
    let fromQuery = null;
    try {
      fromQuery = new URLSearchParams(window.location.search).get("agent");
    } catch (_) {}
    if (fromQuery === "reset") {
      try { localStorage.removeItem(LS_KEY); } catch (_) {}
      return fallback;
    }
    if (fromQuery) {
      try { new URL(fromQuery); } catch (_) { return fallback; }
      try { localStorage.setItem(LS_KEY, fromQuery); } catch (_) {}
      return fromQuery;
    }
    try {
      const stored = localStorage.getItem(LS_KEY);
      if (stored) { new URL(stored); return stored; }
    } catch (_) {}
    return fallback;
  })();

  function resolveEndpoint() {
    // ?agent= takes a base url too, so it gets the same /chat resolution the
    // configured AGENT_URL already received server-side.
    const resolve = (window.GM_AUTH && window.GM_AUTH.chatEndpoint) || ((u) => u);
    if (endpointOverride) return resolve(endpointOverride);
    return (window.GM_AUTH && window.GM_AUTH.agentUrl()) || resolve(window.GRAND_MERIDIAN_AGENT_URL);
  }

  const PANEL_W = 380;
  const PANEL_H = 560;

  const GREETING =
    "Welcome to The Grand Meridian. How can I help you today? I can check availability, share our menus, or recommend something nearby.";
  const CHIPS = ["Check availability", "Room service", "Things to do nearby"];

  // One session per page load. Server tracks conversation state keyed by this id.
  const SESSION_ID =
    (typeof crypto !== "undefined" && crypto.randomUUID)
      ? crypto.randomUUID()
      : `gm-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

  // ---- DOM construction ----
  const root = document.getElementById("concierge-widget");
  if (!root) {
    console.warn("concierge-widget mount point not found");
    return;
  }

  const wrapper = document.createElement("div");
  wrapper.style.cssText = `position:fixed;right:32px;bottom:32px;z-index:50;font-family:Inter,sans-serif;`;
  root.appendChild(wrapper);

  // Launcher button
  const launcher = document.createElement("button");
  launcher.setAttribute("aria-label", "Open concierge chat");
  launcher.style.cssText = `
    width:64px;height:64px;border-radius:50%;background:#1B2B4B;color:#C9A84C;
    border:none;cursor:pointer;font-size:24px;line-height:1;
    box-shadow:0 12px 30px rgba(27,43,75,0.35);display:flex;align-items:center;justify-content:center;
    transition:transform 0.18s ease;
  `;
  launcher.innerHTML = `<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#C9A84C" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>`;
  launcher.addEventListener("mouseenter", () => (launcher.style.transform = "scale(1.05)"));
  launcher.addEventListener("mouseleave", () => (launcher.style.transform = "scale(1)"));
  wrapper.appendChild(launcher);

  // Panel (hidden by default)
  const panel = document.createElement("aside");
  panel.setAttribute("aria-label", "Concierge chat");
  panel.style.cssText = `
    display:none;flex-direction:column;width:${PANEL_W}px;height:${PANEL_H}px;
    background:#fff;border:1px solid #E6E2D6;
    box-shadow:0 18px 50px rgba(27,43,75,0.18);overflow:hidden;
  `;
  wrapper.appendChild(panel);

  // Header
  const head = document.createElement("div");
  head.style.cssText = `
    padding:18px 20px;background:#1B2B4B;color:#fff;
    display:flex;align-items:center;gap:12px;flex-shrink:0;
  `;
  head.innerHTML = `
    <div style="width:28px;height:28px;border-radius:50%;background:#C9A84C;
                display:flex;align-items:center;justify-content:center;">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#1B2B4B" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>
    </div>
    <div style="display:flex;flex-direction:column;line-height:1.2;">
      <div style="font-family:'Playfair Display',serif;font-size:16px;font-weight:600;letter-spacing:0.02em;">
        Ask our concierge
      </div>
      <div id="cm-status" style="font-size:11px;color:#cfd6e3;letter-spacing:0.06em;">● Available now</div>
    </div>
    <button id="cm-close" aria-label="Close chat"
      style="margin-left:auto;background:none;border:none;color:#cfd6e3;font-size:22px;line-height:1;cursor:pointer;">×</button>
  `;
  panel.appendChild(head);

  // Thread (scrollable)
  const thread = document.createElement("div");
  thread.style.cssText = `
    flex:1;overflow:auto;padding:20px;background:#FBFAF6;
    display:flex;flex-direction:column;gap:12px;
  `;
  panel.appendChild(thread);

  // Error toast (above input, hidden by default)
  const toast = document.createElement("div");
  toast.style.cssText = `
    display:none;background:#FEF3F2;color:#B42318;padding:8px 16px;
    font-size:12px;border-top:1px solid #F4C7C0;
  `;
  panel.appendChild(toast);

  // Input row
  const inputRow = document.createElement("form");
  inputRow.style.cssText = `
    display:flex;align-items:center;gap:10px;padding:14px 16px;
    border-top:1px solid #E6E2D6;background:#fff;flex-shrink:0;
  `;
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Type a question…";
  input.setAttribute("aria-label", "Type a message");
  input.style.cssText = `
    flex:1;border:none;outline:none;font-family:inherit;font-size:14px;padding:8px 0;color:#1a1a1a;
  `;
  const sendBtn = document.createElement("button");
  sendBtn.type = "submit";
  sendBtn.setAttribute("aria-label", "Send");
  sendBtn.style.cssText = `
    background:#1B2B4B;color:#C9A84C;border:none;width:36px;height:36px;cursor:pointer;font-size:18px;
  `;
  sendBtn.innerHTML = "→";
  inputRow.appendChild(input);
  inputRow.appendChild(sendBtn);
  panel.appendChild(inputRow);

  // ---- State helpers ----
  function el(tag, style, html) {
    const e = document.createElement(tag);
    if (style) e.style.cssText = style;
    if (html) e.innerHTML = html;
    return e;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  // Configure marked once. `breaks: true` — single newlines render as <br>,
  // matching how the LLM tends to format chat replies. `gfm: true` for
  // task lists, autolinks, fenced code.
  if (typeof marked !== "undefined" && typeof marked.setOptions === "function") {
    marked.setOptions({ breaks: true, gfm: true });
  }

  // Render LLM markdown safely. If either CDN dep failed to load, fall back
  // to escaped plaintext rather than risking unsanitized innerHTML.
  function renderMarkdown(text) {
    if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
      return escapeHtml(text).replace(/\n/g, "<br>");
    }
    return DOMPurify.sanitize(marked.parse(String(text)), {
      ADD_ATTR: ["target", "rel"],
    });
  }

  function renderBot(text, opts = {}) {
    const isGreeting = !!opts.greeting;
    const bubble = el(
      "div",
      `max-width:85%;padding:12px 14px;font-size:14px;line-height:1.5;
       background:#fff;color:#1a1a1a;border:1px solid #E6E2D6;align-self:flex-start;
       border-radius:2px 14px 14px 14px;`,
      isGreeting
        ? `<div style="font-family:'Playfair Display',serif;font-size:15px;font-weight:600;color:#1B2B4B;margin-bottom:4px;">Welcome to The Grand Meridian.</div>${escapeHtml(text.replace("Welcome to The Grand Meridian. ", ""))}`
        : `<div class="cm-md">${renderMarkdown(text)}</div>`
    );
    // Make rendered links open in a new tab without leaking the opener.
    bubble.querySelectorAll("a[href]").forEach((a) => {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener noreferrer");
    });
    thread.appendChild(bubble);
    scrollToBottom();
    return bubble;
  }

  function renderUser(text) {
    const bubble = el(
      "div",
      `max-width:85%;padding:12px 14px;font-size:14px;line-height:1.5;
       background:#1B2B4B;color:#fff;align-self:flex-end;
       border-radius:14px 2px 14px 14px;`,
      escapeHtml(text)
    );
    thread.appendChild(bubble);
    scrollToBottom();
  }

  function renderChips() {
    const wrap = el(
      "div",
      `display:flex;flex-wrap:wrap;gap:8px;align-self:flex-start;margin-top:-4px;`
    );
    CHIPS.forEach((label) => {
      const chip = el(
        "button",
        `background:#fff;border:1px solid #E6E2D6;color:#1B2B4B;
         font-family:inherit;font-size:13px;padding:6px 12px;border-radius:999px;cursor:pointer;
         transition:background 0.15s ease;`,
        escapeHtml(label)
      );
      chip.addEventListener("mouseenter", () => (chip.style.background = "#F5F2E8"));
      chip.addEventListener("mouseleave", () => (chip.style.background = "#fff"));
      chip.addEventListener("click", () => {
        wrap.remove();
        send(label);
      });
      wrap.appendChild(chip);
    });
    thread.appendChild(wrap);
    scrollToBottom();
  }

  function renderTyping() {
    const dots = el(
      "div",
      `align-self:flex-start;display:flex;gap:4px;padding:14px 16px;
       background:#fff;border:1px solid #E6E2D6;border-radius:2px 14px 14px 14px;`,
      `<span class="cm-dot"></span><span class="cm-dot"></span><span class="cm-dot"></span>`
    );
    thread.appendChild(dots);
    scrollToBottom();
    return dots;
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      thread.scrollTop = thread.scrollHeight;
    });
  }

  function showToast(msg) {
    toast.textContent = msg;
    toast.style.display = "block";
    setTimeout(() => {
      toast.style.display = "none";
    }, 4000);
  }

  function setSendingState(on) {
    sendBtn.disabled = on;
    sendBtn.style.opacity = on ? "0.5" : "1";
    sendBtn.style.cursor = on ? "not-allowed" : "pointer";
    input.disabled = on;
  }

  // ---- Conversation loop ----
  let firstOpen = true;
  function openPanel() {
    panel.style.display = "flex";
    launcher.style.display = "none";
    if (firstOpen) {
      firstOpen = false;
      paintStatus();
      renderBot(GREETING, { greeting: true });
      renderChips();
    }
    input.focus();
  }

  function closePanel() {
    panel.style.display = "none";
    launcher.style.display = "flex";
  }

  launcher.addEventListener("click", openPanel);
  document.getElementById("cm-close").addEventListener("click", closePanel);

  // ---- auth status ----
  const statusEl = document.getElementById("cm-status");

  function paintStatus() {
    if (!statusEl) return;
    const s = window.GM_AUTH ? window.GM_AUTH.state() : { mode: "none", ready: true };
    const g = window.GM_AUTH ? window.GM_AUTH.guest() : {};
    const who = g && g.name ? ` · ${escapeHtml(g.name)}` : "";
    if (s.mode === "none") {
      statusEl.innerHTML = `<span style="color:#F0C674">● unsecured</span>${who}`;
      statusEl.title = "No token is being sent. Only valid against an unprotected agent.";
    } else if (s.ready) {
      statusEl.innerHTML = `<span style="color:#8FD8A0">● secured (${escapeHtml(s.mode)})</span>${who}`;
      statusEl.title = "An OAuth2 access token is attached to every request. The gateway validates it.";
    } else {
      statusEl.innerHTML = `<span style="color:#F4A8A0">● not authorised</span>${who}`;
      statusEl.title = s.reason || "";
    }
  }

  inputRow.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    send(text);
  });

  async function send(text) {
    renderUser(text);
    setSendingState(true);
    const typing = renderTyping();

    let headers = { "Content-Type": "application/json" };
    try {
      // Throws in pkce mode when not signed in, and in broker mode when the
      // token endpoint is unreachable or unconfigured. Both are worth showing
      // plainly rather than as a generic network error.
      Object.assign(headers, await window.GM_AUTH.authHeaders());
    } catch (e) {
      typing.remove();
      setSendingState(false);
      showToast(String((e && e.message) || e));
      paintStatus();
      return;
    }

    // `context` is client-asserted. The agent trusts it, which is exactly what
    // the cross-user security cases probe. In a real deployment the guest
    // identity should come from the validated token, not from here.
    const g = window.GM_AUTH.guest();

    try {
      const res = await fetch(resolveEndpoint(), {
        method: "POST",
        headers,
        body: JSON.stringify({
          message: text,
          session_id: SESSION_ID,
          context: g && g.id ? { guest_id: g.id, guest_name: g.name } : {},
        }),
      });
      typing.remove();
      if (res.status === 401 || res.status === 403) {
        // The gateway rejected the token. Nothing the agent did.
        showToast(`Gateway rejected the request (${res.status}). Token missing, expired or wrong scope.`);
        setSendingState(false);
        paintStatus();
        return;
      }
      if (!res.ok) {
        showToast(`Concierge offline (${res.status}). Retry?`);
        setSendingState(false);
        return;
      }
      const data = await res.json();
      const reply = (data && data.response) || "I'm having trouble — could you try again?";
      renderBot(reply);
    } catch (err) {
      typing.remove();
      console.warn("widget send failed", err);
      showToast("Concierge offline. Retry?");
    } finally {
      setSendingState(false);
      input.focus();
    }
  }

  // Resolve the auth config before first paint so the header shows the real
  // mode rather than flickering from unsecured to secured.
  (async () => {
    try {
      if (window.GM_AUTH) await window.GM_AUTH.init();
    } catch (e) {
      console.warn("auth init failed", e);
    }
    paintStatus();
  })();

  // Typing-dot animation + markdown styles, scoped so they only apply inside the bubble.
  const styleTag = document.createElement("style");
  styleTag.textContent = `
    .cm-dot {
      width:6px;height:6px;border-radius:50%;background:#1B2B4B;
      animation: cm-dot 1.4s infinite ease-in-out;
    }
    .cm-dot:nth-child(2) { animation-delay: 0.2s; }
    .cm-dot:nth-child(3) { animation-delay: 0.4s; }
    @keyframes cm-dot {
      0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
      40% { opacity: 1; transform: translateY(-2px); }
    }

    /* Markdown rendering inside bot bubbles */
    .cm-md > *:first-child { margin-top: 0; }
    .cm-md > *:last-child  { margin-bottom: 0; }
    .cm-md p { margin: 0 0 8px; }
    .cm-md ul, .cm-md ol { margin: 4px 0 8px; padding-left: 20px; }
    .cm-md li { margin: 2px 0; }
    .cm-md li > p { margin: 0; }
    .cm-md h1, .cm-md h2, .cm-md h3, .cm-md h4, .cm-md h5, .cm-md h6 {
      font-family: 'Playfair Display', serif;
      color: #1B2B4B;
      margin: 8px 0 4px;
      line-height: 1.3;
    }
    .cm-md h1 { font-size: 17px; }
    .cm-md h2 { font-size: 16px; }
    .cm-md h3, .cm-md h4, .cm-md h5, .cm-md h6 { font-size: 15px; }
    .cm-md a { color: #1B2B4B; text-decoration: underline; text-decoration-color: #C9A84C; }
    .cm-md a:hover { text-decoration-color: #1B2B4B; }
    .cm-md strong { font-weight: 600; color: #1B2B4B; }
    .cm-md em { font-style: italic; }
    .cm-md code {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12.5px;
      background: #F5F2E8;
      padding: 1px 5px;
      border-radius: 3px;
    }
    .cm-md pre {
      background: #FBFAF6;
      border: 1px solid #E6E2D6;
      padding: 8px 10px;
      margin: 6px 0;
      border-radius: 4px;
      overflow-x: auto;
      font-size: 12.5px;
      line-height: 1.45;
    }
    .cm-md pre code { background: transparent; padding: 0; }
    .cm-md blockquote {
      margin: 6px 0;
      padding: 2px 0 2px 10px;
      border-left: 2px solid #C9A84C;
      color: #4a4a4a;
    }
    .cm-md hr {
      border: none;
      border-top: 1px solid #E6E2D6;
      margin: 10px 0;
    }
    .cm-md table {
      border-collapse: collapse;
      margin: 6px 0;
      font-size: 13px;
    }
    .cm-md th, .cm-md td {
      border: 1px solid #E6E2D6;
      padding: 4px 8px;
      text-align: left;
    }
    .cm-md th { background: #FBFAF6; font-weight: 600; color: #1B2B4B; }
  `;
  document.head.appendChild(styleTag);
})();
