#!/usr/bin/env python3
"""Dev server for the Grand Meridian console.

Two modes, chosen by a flag:

    python web/serve.py --no-auth      # no security: the browser calls the agent directly
    python web/serve.py                # secured: the agent is behind an OAuth2 gateway

In secured mode the console will not talk to the agent without an access token.
It gets one from this server, which is also a **dev-only token broker**: the
OAuth2 client id and secret live here, server-side, and the browser only ever
receives a short-lived access token.

That split is deliberate. Exercise 1's completion evidence requires that no
credential appears "in source code, build output, or the browser client", and a
client secret shipped to a browser would fail that on its own. If your supplied
client is a public client instead, set AUTH_MODE=pkce and no secret is involved
at all.

Nothing here authenticates anything. The platform gateway in front of the agent
validates the token; the agent itself has no auth logic and should not gain any.
This server only obtains a token and serves static files.

NOT FOR PRODUCTION. No TLS, no state encryption, permissive CORS, secrets in a
plain env file. It exists so a facilitator can drive the fixture from a browser.

Config lives in dev/web.env, generated on first run. Stdlib only, so it runs
without the project venv.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import socketserver
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
ROOT = WEB_DIR.parent
ENV_PATH = ROOT / "dev" / "web.env"

ENV_TEMPLATE = """# Console configuration. Generated {stamp}. Local use only, gitignored.
#
# AUTH_MODE:
#   none     the browser calls the agent directly, no token. Same as --no-auth.
#   broker   this server performs a client_credentials grant and hands the
#            browser only the access token. The secret stays server-side.
#   pkce     the browser runs authorization-code + PKCE against the IdP. No
#            secret anywhere. Needs OAUTH_AUTHORIZE_URL and a registered
#            redirect URI. This is the correct shape for a public client.
AUTH_MODE=broker

# The agent's /chat endpoint. In a deployed setup this is the gateway URL, not
# the agent's own address.
AGENT_URL=http://127.0.0.1:8000/chat

# --- OAuth2 client, as supplied with the participant package -----------------
OAUTH_TOKEN_URL=
OAUTH_AUTHORIZE_URL=
OAUTH_CLIENT_ID=
# Used by AUTH_MODE=broker only. Never sent to the browser.
OAUTH_CLIENT_SECRET=
OAUTH_SCOPES=
# Used by AUTH_MODE=pkce only. Must match what is registered at the IdP.
OAUTH_REDIRECT_URI=http://localhost:5500/

# --- Which guest the console acts as ----------------------------------------
# Sent in the request `context`. Client-asserted and therefore spoofable: this
# is a dev affordance, not an identity claim. See web/README.md.
GUEST_ID=guest-priya
GUEST_NAME=Priya Raman
"""


class Server(ThreadingHTTPServer):
    """ThreadingHTTPServer minus the reverse-DNS lookup at bind time.

    ``http.server.HTTPServer.server_bind`` calls ``socket.getfqdn()`` purely to
    populate ``server_name``, which this server never uses. On a machine with
    slow or absent reverse DNS — a VPN, an ssh tunnel, a captive network — that
    lookup blocks for many seconds or hangs outright, and startup silently
    stalls after the socket is already bound. Skip it and take the host as given.
    """

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host or socket.gethostname()
        self.server_port = port


def _port_holders(port: int) -> list[str]:
    """Name whatever is listening, so the error says what to stop rather than
    just that the port is taken. Best effort: lsof may be absent."""
    try:
        out = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip().splitlines()
    except Exception:
        return []
    lines = []
    for row in out[1:]:
        parts = row.split()
        if len(parts) >= 2:
            lines.append(f"{parts[0]} (pid {parts[1]})")
    return lines


def load_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        ENV_PATH.write_text(ENV_TEMPLATE.format(stamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
        print(f"Generated {ENV_PATH.relative_to(ROOT)} — fill in the OAuth2 client before secured mode works.")
    env: dict[str, str] = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    # A real environment variable wins, so CI or a wrapper script can override.
    for key in list(env) + ["AUTH_MODE", "AGENT_URL"]:
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


class Handler(SimpleHTTPRequestHandler):
    env: dict[str, str] = {}
    force_mode: str | None = None

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB_DIR), **kw)

    def log_message(self, fmt, *args):  # quieter, and never log query strings
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---- helpers ----
    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _mode(self) -> str:
        return self.force_mode or self.env.get("AUTH_MODE", "broker").strip().lower()

    # ---- routes ----
    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] == "/auth/config":
            mode = self._mode()
            # Deliberately omits OAUTH_CLIENT_SECRET. Everything here is safe to
            # hand a browser; if you add a field, check that it still is.
            self._json({
                "mode": mode,
                "agentUrl": self.env.get("AGENT_URL", "http://127.0.0.1:8000/chat"),
                "clientId": self.env.get("OAUTH_CLIENT_ID", ""),
                "authorizeUrl": self.env.get("OAUTH_AUTHORIZE_URL", ""),
                "tokenUrl": self.env.get("OAUTH_TOKEN_URL", ""),
                "scopes": self.env.get("OAUTH_SCOPES", ""),
                "redirectUri": self.env.get("OAUTH_REDIRECT_URI", ""),
                "guest": {
                    "id": self.env.get("GUEST_ID", ""),
                    "name": self.env.get("GUEST_NAME", ""),
                },
                "brokerReady": bool(self.env.get("OAUTH_TOKEN_URL") and self.env.get("OAUTH_CLIENT_ID")
                                    and self.env.get("OAUTH_CLIENT_SECRET")),
            })
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?")[0] != "/auth/token":
            self._json({"error": "not_found"}, 404)
            return
        if self._mode() != "broker":
            self._json({"error": "broker_disabled",
                        "detail": f"AUTH_MODE is {self._mode()!r}; the token broker only runs in broker mode."}, 400)
            return

        token_url = self.env.get("OAUTH_TOKEN_URL", "")
        client_id = self.env.get("OAUTH_CLIENT_ID", "")
        client_secret = self.env.get("OAUTH_CLIENT_SECRET", "")
        if not (token_url and client_id and client_secret):
            self._json({"error": "not_configured",
                        "detail": "Set OAUTH_TOKEN_URL, OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET in dev/web.env."}, 503)
            return

        form = {"grant_type": "client_credentials"}
        if self.env.get("OAUTH_SCOPES"):
            form["scope"] = self.env["OAUTH_SCOPES"]
        data = urllib.parse.urlencode(form).encode()
        cred = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        req = urllib.request.Request(token_url, data=data, method="POST", headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {cred}",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                payload = json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:400]
            print(f"token request failed: HTTP {e.code} {detail}", file=sys.stderr)
            self._json({"error": "token_request_failed", "status": e.code, "detail": detail}, 502)
            return
        except Exception as e:
            print(f"token request error: {e}", file=sys.stderr)
            self._json({"error": "token_request_error", "detail": str(e)}, 502)
            return

        # Return only what the browser needs. Refresh tokens and id tokens stay
        # here if the IdP sent any.
        self._json({
            "access_token": payload.get("access_token", ""),
            "token_type": payload.get("token_type", "Bearer"),
            "expires_in": payload.get("expires_in", 300),
            "scope": payload.get("scope", ""),
        })


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--no-auth", action="store_true",
                   help="Run with no security: the browser calls the agent directly, no token.")
    p.add_argument("--port", type=int, default=5500)
    args = p.parse_args()

    # Line-buffer stdout: Python block-buffers when redirected, which hid the
    # startup banner under nohup/tee — exactly where the stated auth mode
    # matters most.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    env = load_env()
    Handler.env = env
    Handler.force_mode = "none" if args.no_auth else None
    mode = Handler.force_mode or env.get("AUTH_MODE", "broker").strip().lower()

    if mode not in ("none", "broker", "pkce"):
        sys.exit(f"Unknown AUTH_MODE {mode!r}. Use none, broker or pkce.")

    # Bind BEFORE printing anything. Announcing a URL and then failing to bind
    # reads as "the server started and something else broke", which sends you
    # looking in the wrong place entirely.
    try:
        httpd = Server(("0.0.0.0", args.port), Handler)
    except OSError as e:
        if e.errno not in (48, 98):  # EADDRINUSE on macOS / Linux
            raise
        print(f"\nPort {args.port} is already in use, so the console did not start.",
              file=sys.stderr)
        holders = _port_holders(args.port)
        if holders:
            print("  held by:", file=sys.stderr)
            for line in holders:
                print(f"    {line}", file=sys.stderr)
            print("  If that is an older console of your own, stop it with:", file=sys.stderr)
            print("    pkill -f web/serve.py", file=sys.stderr)
        print(f"  Or pick another port:  python web/serve.py --port {args.port + 1}",
              file=sys.stderr)
        sys.exit(1)

    print(f"\nGrand Meridian console  http://localhost:{args.port}/", flush=True)
    print(f"  auth mode   {mode}{'  (forced by --no-auth)' if args.no_auth else ''}", flush=True)
    print(f"  agent       {env.get('AGENT_URL','(unset)')}", flush=True)
    print(f"  acting as   {env.get('GUEST_NAME','(none)')} / {env.get('GUEST_ID','(none)')}", flush=True)

    if mode == "none":
        print("\n  NO SECURITY. No token is sent. Only valid against an unprotected agent.", flush=True)
    elif mode == "broker":
        ready = bool(env.get("OAUTH_TOKEN_URL") and env.get("OAUTH_CLIENT_ID") and env.get("OAUTH_CLIENT_SECRET"))
        print(f"  token broker {'ready' if ready else 'NOT CONFIGURED - fill in dev/web.env'}", flush=True)
        print("  client secret is held here, server-side. The browser only receives a token.", flush=True)
    elif mode == "pkce":
        ok = bool(env.get("OAUTH_AUTHORIZE_URL") and env.get("OAUTH_CLIENT_ID"))
        print(f"  pkce        {'ready' if ok else 'NOT CONFIGURED - need OAUTH_AUTHORIZE_URL and OAUTH_CLIENT_ID'}", flush=True)
        print(f"  redirect    {env.get('OAUTH_REDIRECT_URI','(unset)')} — must be registered at the IdP", flush=True)

    # Flush explicitly: the banner is the only place the active auth mode is
    # stated, and Python buffers stdout when it is not a TTY (nohup, tee, a
    # supervisor), which would hide it exactly when it matters most.
    print("\n  Ctrl-C to stop.\n", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped")
