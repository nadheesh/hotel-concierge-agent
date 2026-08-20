# Grand Meridian console

The guest-facing website and chat widget. This is the client the participant
connects to the agent in Exercise 1, and it is the only place in the fixture
where OAuth2 shows up on the inbound side.

```bash
python web/serve.py --no-auth     # no security, browser calls the agent directly
python web/serve.py               # secured, an access token is attached to every call
python web/serve.py --port 5501   # if 5500 is taken
```

Then open http://localhost:5500/. The widget header shows which mode is live:
**● unsecured**, **● secured (broker)** or **● not authorised**.

## The division of responsibility

The agent has **no authentication logic and must not gain any.** The platform
gateway in front of it validates the token and rejects what fails. The console's
only job is to obtain a token and attach it as `Authorization: Bearer`. If the
token is missing, expired or short a scope, the gateway returns 401 or 403 and
the widget says so — that path is worth exercising deliberately, because
telling a gateway rejection apart from an agent error is part of what the study
observes.

Do not add token checking to `agent/`. An agent that validates its
own tokens is not testing the platform.

## Modes

Set `AUTH_MODE` in `dev/web.env`, generated on first run.

### `none`

No token. The browser posts straight to the agent. Same as `--no-auth`, which
forces this mode whatever the file says.

Use it to drive an unprotected local agent, and to establish the baseline before
security is configured. The header shows amber **● unsecured** so nobody mistakes
this for a working secured setup.

### `broker` (default)

`serve.py` performs a `client_credentials` grant and returns **only** the access
token to the browser. The client id and secret stay server-side in
`dev/web.env`.

That split is not incidental. Exercise 1's completion evidence requires that no
credential appears "in source code, build output, or the browser client", and a
client secret shipped to a browser fails that on its own — anyone can read it in
devtools. If you are tempted to skip the broker and put the secret in a JS file,
that is the failure the exercise is looking for.

Configure:

```
AUTH_MODE=broker
OAUTH_TOKEN_URL=https://<idp>/oauth2/token
OAUTH_CLIENT_ID=<client id>
OAUTH_CLIENT_SECRET=<client secret>
OAUTH_SCOPES=<space separated, if the gateway requires any>
```

Tokens are cached until 30s before expiry and refreshed on demand, so a short
TTL is fine and is worth testing.

### `pkce`

Authorization code with PKCE, run in the browser. No secret anywhere, which is
the correct shape for a public client and the one that matches a supplied client
package listing a redirect URI.

```
AUTH_MODE=pkce
OAUTH_AUTHORIZE_URL=https://<idp>/oauth2/authorize
OAUTH_TOKEN_URL=https://<idp>/oauth2/token
OAUTH_CLIENT_ID=<client id>
OAUTH_REDIRECT_URI=http://localhost:5500/
OAUTH_SCOPES=<space separated>
```

The redirect URI must be registered at the IdP exactly as written. The widget
shows a **Sign in** button until a token is held; the code is exchanged on
return and `code`/`state` are stripped from the address bar so a reload does not
re-exchange. The token lives in `sessionStorage` and dies with the tab.

## Which guest the console acts as

`GUEST_ID` and `GUEST_NAME` in `dev/web.env` are sent in the request `context`.
Override for one load with `?guest=guest-marcus&guest_name=Marcus%20Chen`.

That override is a deliberate dev affordance and it is also a live demonstration
of a real weakness: **`context` is client-asserted, and the agent trusts it.**
Anyone can claim to be any guest by editing a query string. In a real deployment
the guest identity should be derived from the validated token, not from the
request body.

This is not a bug to fix here. It is what security category 4 (cross-user data
extraction) probes, and being able to reproduce it from the address bar makes the
finding concrete. See `evaluators/security/04-cross-user.md`.

Seeded guests: `guest-priya`, `guest-marcus`, `guest-sofia`, `guest-daniel`,
`guest-mei`.

## Pointing at a deployed agent

`AGENT_URL` in `dev/web.env`, or `?agent=<url>` for one load — that persists to
`localStorage` and sticks until `?agent=reset`.

In a deployed setup this must be the **gateway** URL, not the agent's own
address. Pointing it at the agent directly bypasses the thing being tested, and
if that works it is itself a finding: the agent should not be reachable except
through the gateway.

## Not for production

No TLS, no CSRF protection, permissive CORS, secrets in a plain env file, and
tokens held in browser storage. `serve.py` exists so a facilitator can drive the
fixture from a browser. `dev/` is gitignored; nothing in it should ever be
committed or reused in a shared environment.
