#!/usr/bin/env python3
"""Dev server for the Grand Meridian console.

Four settings, and the mode follows from them:

    AGENT_URL             the agent's BASE url (the gateway, not the agent's own
                          address). /chat is appended for you.
    AGENT_TOKEN_URL       OAuth2 token endpoint
    AGENT_CLIENT_ID       OAuth2 client id
    AGENT_CLIENT_SECRET   OAuth2 client secret

Supply all three credential values and the console runs secured: it obtains an
access token and attaches it to every call. Leave them empty, or pass --no-auth,
and it calls the agent directly with no token. There is no mode setting to keep
in sync with the credentials.

When secured, this server acts as a **dev-only token broker**: the client id and
secret live here, server-side, and the browser only ever receives a short-lived
access token. That split is deliberate. Exercise 1's completion evidence requires
that no credential appears "in source code, build output, or the browser client",
and a client secret shipped to a browser fails that on its own.

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

# Every setting the console understands. Declared explicitly so a real
# environment variable can override any of them, whether or not the key happens
# to be present and uncommented in dev/web.env.
KNOWN_KEYS = (
    "AGENT_URL",
    "AGENT_TOKEN_URL",
    "AGENT_CLIENT_ID",
    "AGENT_CLIENT_SECRET",
    "AGENT_SCOPES",
)

ENV_TEMPLATE = """# Console configuration. Generated {stamp}. Local use only, gitignored.

# The agent's BASE url. /chat is appended for you.
# Use the GATEWAY url, not the agent's own address: pointing straight at the
# agent bypasses the thing being tested.
AGENT_URL=http://127.0.0.1:8000

# OAuth2 client for calling the agent. Fill in all three and the console runs
# secured. Leave them empty and it calls the agent with no token.
# The secret stays here, server-side, and is never sent to the browser.
AGENT_TOKEN_URL=
AGENT_CLIENT_ID=
AGENT_CLIENT_SECRET=

# Optional. Only set this if the gateway rejects tokens without a scope.
AGENT_SCOPES=
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


CHAT_PATH = "/chat"


def chat_endpoint(base: str) -> str:
    """Resolve the configured base URL to the agent's chat endpoint.

    /chat is part of the platform's chat-agent contract, so the console knows it
    and nobody should have to type it. Tolerant of a base that already ends in
    /chat, and of trailing slashes, because both are natural things to paste.

    Mirrored in web/auth.js for the ?agent= override; keep the two in step.
    """
    base = (base or "").strip().rstrip("/")
    if not base:
        return f"http://127.0.0.1:8000{CHAT_PATH}"
    return base if base.endswith(CHAT_PATH) else base + CHAT_PATH


def _credential_complete(env: dict[str, str]) -> bool:
    """All three parts, or none. A partial credential is a misconfiguration
    rather than a reason to fall back to calling the agent unauthenticated —
    silently dropping the token is how you end up thinking a gateway is open
    when it is not."""
    return all(env.get(k) for k in ("AGENT_TOKEN_URL", "AGENT_CLIENT_ID", "AGENT_CLIENT_SECRET"))


def _credential_partial(env: dict[str, str]) -> bool:
    parts = [env.get(k) for k in ("AGENT_TOKEN_URL", "AGENT_CLIENT_ID", "AGENT_CLIENT_SECRET")]
    return any(parts) and not all(parts)


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
    # A real environment variable wins, so a one-off command or CI can override
    # the file without editing it.
    for key in KNOWN_KEYS:
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
        """"none" or "broker". Derived from whether a full credential is present,
        so there is no mode setting that can drift out of step with it."""
        if self.force_mode:
            return self.force_mode
        return "broker" if _credential_complete(self.env) else "none"

    # ---- routes ----
    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] == "/auth/config":
            mode = self._mode()
            # Deliberately omits AGENT_CLIENT_SECRET. Everything here is safe to
            # hand a browser; if you add a field, check that it still is.
            self._json({
                "mode": mode,
                "agentUrl": chat_endpoint(self.env.get("AGENT_URL", "")),
                "clientId": self.env.get("AGENT_CLIENT_ID", ""),
                "scopes": self.env.get("AGENT_SCOPES", ""),
                "brokerReady": _credential_complete(self.env),
            })
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?")[0] != "/auth/token":
            self._json({"error": "not_found"}, 404)
            return
        if self._mode() != "broker":
            self._json({"error": "broker_disabled",
                        "detail": "Running unsecured, so there is no token to issue."}, 400)
            return

        token_url = self.env.get("AGENT_TOKEN_URL", "")
        client_id = self.env.get("AGENT_CLIENT_ID", "")
        client_secret = self.env.get("AGENT_CLIENT_SECRET", "")
        if not (token_url and client_id and client_secret):
            self._json({"error": "not_configured",
                        "detail": "Set AGENT_TOKEN_URL, AGENT_CLIENT_ID and AGENT_CLIENT_SECRET."}, 503)
            return

        form = {"grant_type": "client_credentials"}
        if self.env.get("AGENT_SCOPES"):
            form["scope"] = self.env["AGENT_SCOPES"]
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
    mode = Handler.force_mode or ("broker" if _credential_complete(env) else "none")

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
        print(f"  Or pick another port:  ./web/run.sh --port {args.port + 1}", file=sys.stderr)
        sys.exit(1)

    print(f"\nGrand Meridian console  http://localhost:{args.port}/", flush=True)
    print(f"  agent       {chat_endpoint(env.get('AGENT_URL', ''))}", flush=True)

    if mode == "none":
        if args.no_auth:
            print("  security    OFF (forced by --no-auth)", flush=True)
        else:
            print("  security    OFF (no credential configured)", flush=True)
        print("\n  No token is sent. Only valid against an unprotected agent.", flush=True)
        if _credential_partial(env):
            print("\n  WARNING: a partial credential is set. All three of AGENT_TOKEN_URL,",
                  flush=True)
            print("           AGENT_CLIENT_ID and AGENT_CLIENT_SECRET are needed, so the",
                  flush=True)
            print("           console is running UNSECURED. Missing:", flush=True)
            for key in ("AGENT_TOKEN_URL", "AGENT_CLIENT_ID", "AGENT_CLIENT_SECRET"):
                if not env.get(key):
                    print(f"             {key}", flush=True)
    else:
        print(f"  security    ON  (client {env.get('AGENT_CLIENT_ID')})", flush=True)
        print(f"  token from  {env.get('AGENT_TOKEN_URL')}", flush=True)
        if env.get("AGENT_SCOPES"):
            print(f"  scopes      {env['AGENT_SCOPES']}", flush=True)
        print("\n  The client secret stays here. The browser only receives a token.", flush=True)

    print("\n  Ctrl-C to stop.\n", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped")
