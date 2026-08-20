// Grand Meridian console — access-token acquisition.
//
// Exposes window.GM_AUTH with:
//   init()            -> resolves the runtime config (mode, agent URL, guest)
//   authHeaders()     -> {} in no-auth mode, {Authorization: "Bearer …"} otherwise
//   state()           -> {mode, ready, reason} for the UI to render
//   signIn()          -> pkce mode only: starts the redirect
//
// Three modes, decided by the server, not by this file:
//
//   none    No token. The browser calls the agent directly. Only valid against
//           an unprotected agent.
//   broker  Fetch a token from this site's own /auth/token. The OAuth2 client
//           secret lives on the dev server, never here. Cached until shortly
//           before expiry.
//
// The mode is decided by the server from whether a full credential is
// configured, so there is nothing to keep in sync here.
//
// The agent performs no authentication of its own. The platform gateway in
// front of it validates the token. This file's only job is to obtain one and
// attach it; if it is missing or wrong, the gateway rejects the call and the
// widget surfaces that.
(() => {
  "use strict";

  const CHAT_PATH = "/chat";

  // Mirrors chat_endpoint() in web/serve.py. Only needed for the ?agent=
  // override, which never passes through the server; the configured AGENT_URL
  // arrives already resolved. Keep the two in step.
  function chatEndpoint(base) {
    const b = String(base || "").trim().replace(/\/+$/, "");
    if (!b) return `http://127.0.0.1:8000${CHAT_PATH}`;
    return b.endsWith(CHAT_PATH) ? b : b + CHAT_PATH;
  }

  let config = null;
  let cached = null; // {token, expiresAt}

  // ---- config ----------------------------------------------------------
  // Served by web/serve.py. Falls back to a window global so the page still
  // works behind a plain static file server, in no-auth mode only.
  async function init() {
    try {
      const res = await fetch("/auth/config", { cache: "no-store" });
      if (res.ok) {
        config = await res.json();
        return config;
      }
    } catch (_) {}
    config = {
      mode: "none",
      agentUrl: chatEndpoint(window.GRAND_MERIDIAN_AGENT_URL),
      _fallback: true,
    };
    return config;
  }

  const cfg = () => config || { mode: "none", guest: {} };

  // Which guest the console acts as. Defaulted here rather than configured,
  // and overridable for a single load: ?guest=guest-marcus asks as someone
  // else. Client-asserted, so it proves nothing about identity - that is
  // exactly what the cross-user security cases probe.
  const DEFAULT_GUEST = { id: "guest-priya", name: "Priya Raman" };

  function guest() {
    const g = { ...DEFAULT_GUEST };
    try {
      const q = new URLSearchParams(location.search);
      if (q.get("guest")) { g.id = q.get("guest"); g.name = q.get("guest_name") || g.id; }
    } catch (_) {}
    return g;
  }

  // ---- broker ----------------------------------------------------------
  async function brokerToken() {
    if (cached && Date.now() < cached.expiresAt - 30000) return cached.token;
    const res = await fetch("/auth/token", { method: "POST" });
    const body = await res.json().catch(() => ({}));
    if (!res.ok || !body.access_token) {
      const why = body.detail || body.error || `HTTP ${res.status}`;
      throw new Error(`could not obtain an access token: ${why}`);
    }
    cached = {
      token: body.access_token,
      expiresAt: Date.now() + (Number(body.expires_in) || 300) * 1000,
    };
    return cached.token;
  }

  // ---- public ----------------------------------------------------------
  async function authHeaders() {
    const mode = cfg().mode;
    if (mode === "none") return {};
    if (mode === "broker") return { Authorization: `Bearer ${await brokerToken()}` };
    throw new Error(`unknown auth mode ${mode}`);
  }

  function state() {
    const c = cfg();
    if (c.mode === "none") {
      return { mode: "none", ready: true, reason: c._fallback ? "no dev server; running unsecured" : "" };
    }
    if (c.mode === "broker") {
      return {
        mode: "broker",
        ready: !!c.brokerReady,
        reason: c.brokerReady ? "" : "credential incomplete — see dev/web.env",
      };
    }
    return { mode: c.mode, ready: false, reason: "unknown mode" };
  }

  window.GM_AUTH = {
    init: async () => {
      await init();
      return cfg();
    },
    authHeaders,
    state,
    guest,
    agentUrl: () => cfg().agentUrl,
    chatEndpoint,
  };
})();
