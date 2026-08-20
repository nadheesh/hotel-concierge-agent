"""Shared plumbing for the traffic scripts.

The scripts generate labelled traffic for Agent Manager's evaluators. They do
not grade it. Every request uses the case id as its session id, so any result
in the console traces back to exactly one fixture line.

Scoring happens outside these scripts, in the console. The rubrics under
evaluators/ are the reference for configuring those evaluators; nothing here
reads them. Adding local grading back would mean two scoring paths that can
disagree, and the one that matters is the platform's.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterator

import httpx

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
EVALUATORS = ROOT / "evaluators"

# Connection settings come from the environment, the same names and the same
# invocation style as web/run.sh. No config file of their own: one command
# carries everything, and nothing persists a client secret to disk.
CHAT_PATH = "/chat"


def chat_endpoint(base: str) -> str:
    """Mirror of web/serve.py's resolver: accept the base url and append /chat,
    tolerating a base that already ends in it. Keep the two in step."""
    base = (base or "").strip().rstrip("/")
    if not base:
        return f"http://localhost:8000{CHAT_PATH}"
    return base if base.endswith(CHAT_PATH) else base + CHAT_PATH


def _insecure_tls(cfg: dict[str, str]) -> bool:
    return (cfg.get("AGENT_INSECURE_TLS") or "").strip().lower() in {"1", "true", "yes", "on"}


def fetch_token(cfg: dict[str, str]) -> str:
    """Client-credentials grant, so a run against a secured deployment does not
    depend on someone pasting a JWT that expires in an hour."""
    form = {"grant_type": "client_credentials"}
    if cfg.get("AGENT_SCOPES"):
        form["scope"] = cfg["AGENT_SCOPES"]
    try:
        r = httpx.post(
            cfg["AGENT_TOKEN_URL"],
            data=form,
            auth=(cfg["AGENT_CLIENT_ID"], cfg["AGENT_CLIENT_SECRET"]),
            verify=not _insecure_tls(cfg),
            timeout=30.0,
        )
    except Exception as e:
        sys.exit(f"Token request to {cfg['AGENT_TOKEN_URL']} failed: {e}\n"
                 "If the endpoint uses a certificate this machine cannot verify, set\n"
                 "AGENT_INSECURE_TLS=1 (dev clusters only) or SSL_CERT_FILE to the cluster CA.")
    if r.status_code != 200:
        sys.exit(f"Token request failed: HTTP {r.status_code} {r.text[:300]}")
    token = r.json().get("access_token", "")
    if not token:
        sys.exit(f"Token endpoint returned no access_token: {r.text[:300]}")
    return token


CLIENT_KEYS = ("AGENT_TOKEN_URL", "AGENT_CLIENT_ID", "AGENT_CLIENT_SECRET")


def resolve(args) -> None:
    """Fill in agent_url, token and verify. A flag wins over the environment.
    Called by iter_results, so the scripts carry no connection code of their
    own."""
    cfg = dict(os.environ)

    args.agent_url = chat_endpoint(args.agent_url or cfg.get("AGENT_URL", ""))
    args.verify = not _insecure_tls(cfg)

    if not args.token:
        present = [k for k in CLIENT_KEYS if cfg.get(k)]
        if len(present) == len(CLIENT_KEYS):
            print(f"Requesting a token from {cfg['AGENT_TOKEN_URL']}", file=sys.stderr)
            args.token = fetch_token(cfg)
        elif present:
            # Refuse rather than quietly sending an unauthenticated run. A wall
            # of 401s reads as the agent rejecting the attacks it was supposed
            # to be tested with, which is the wrong conclusion to hand someone.
            missing = [k for k in CLIENT_KEYS if not cfg.get(k)]
            sys.exit("Incomplete OAuth2 client. Set all three or none. Missing: "
                     + ", ".join(missing))


def load_cases(name: str, categories: list[str] | None = None) -> list[dict[str, Any]]:
    cases = [json.loads(line) for line in (FIXTURES / name).read_text().splitlines() if line.strip()]
    if categories:
        cases = [c for c in cases if c["category"] in categories]
    return cases


def base_parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    # Both default to empty so resolve() can tell "not given" from "given", and
    # apply flag > environment > dev/web.env in that order.
    p.add_argument("--agent-url", default="",
                   help="Agent base or /chat url. Falls back to AGENT_URL, then dev/web.env.")
    p.add_argument("--token", default=os.environ.get("AGENT_TOKEN", ""),
                   help="Bearer token. Omit and the OAuth2 client in dev/web.env is used to fetch one.")
    p.add_argument("--category", action="append", dest="categories",
                   help="Restrict to one category. Repeatable.")
    p.add_argument("--out", default="", help="Results JSONL path. Defaults next to the fixture.")
    p.add_argument("--delay", type=float, default=0.0,
                   help="Seconds between cases. Raise this if a rate limit is in play.")
    return p


def send(client: httpx.Client, url: str, token: str, message: str, session_id: str,
         context: dict[str, Any]) -> tuple[str, int, float]:
    """One turn. Returns (reply, status, elapsed_ms). Never raises."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    started = time.perf_counter()
    try:
        r = client.post(url, headers=headers,
                        json={"message": message, "session_id": session_id, "context": context},
                        timeout=120.0)
        elapsed = (time.perf_counter() - started) * 1000
        if r.status_code != 200:
            return f"<HTTP {r.status_code}: {r.text[:300]}>", r.status_code, elapsed
        return r.json().get("response", ""), 200, elapsed
    except Exception as e:
        return f"<transport error: {e}>", 0, (time.perf_counter() - started) * 1000


def run_case(client: httpx.Client, args, case: dict[str, Any]) -> dict[str, Any]:
    """Run one case, single or multi turn. Session id is the case id."""
    context = {"guest_id": case.get("guest_id"), "guest_name": case.get("guest_name")}
    turns = case.get("turns") or [case["input"]]
    exchanges = []
    for i, message in enumerate(turns):
        reply, status, elapsed = send(client, args.agent_url, args.token, message, case["id"], context)
        exchanges.append({"turn": i + 1, "input": message, "reply": reply,
                          "status": status, "elapsed_ms": round(elapsed)})
        if args.delay:
            time.sleep(args.delay)
    return {**case, "exchanges": exchanges, "reply": exchanges[-1]["reply"]}


def iter_results(args, fixture: str) -> Iterator[dict[str, Any]]:
    resolve(args)
    cases = load_cases(fixture, args.categories)
    if not cases:
        sys.exit("No cases matched. Check --category against the fixture file.")
    auth = "bearer token" if args.token else "NO TOKEN"
    print(f"{len(cases)} case(s) -> {args.agent_url}  ({auth}"
          f"{', TLS verification off' if not args.verify else ''})", file=sys.stderr)
    with httpx.Client(verify=args.verify) as client:
        for n, case in enumerate(cases, 1):
            result = run_case(client, args, case)
            failed = any(e["status"] != 200 for e in result["exchanges"])
            print(f"  [{n}/{len(cases)}] {case['id']} {case['category']}"
                  f"{'  TRANSPORT FAILURE' if failed else ''}", file=sys.stderr)
            yield result


def write_results(rows: list[dict[str, Any]], path: Path) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"\nWrote {len(rows)} result(s) to {path}", file=sys.stderr)


