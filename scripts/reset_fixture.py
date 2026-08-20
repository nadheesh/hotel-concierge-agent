#!/usr/bin/env python3
"""Restore hotel-mcp to its seeded baseline and confirm the fixture is intact.

Run between participants. A previous session's cancellations and date changes
will otherwise make Script A's ground truth wrong and Exercise 1's scenario
booking unusable.

    HOTEL_MCP_ADMIN_TOKEN=... python scripts/reset_fixture.py --mcp-url https://<mcp>/

Also prints the audit log before resetting, which is worth capturing: it is the
record of what the participant's agents actually wrote.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

EXPECTED = {
    "GM-4471": ("2026-05-12", "confirmed", "deluxe"),
    "GM-5510": ("2026-09-18", "confirmed", "honeymoon"),
    "GM-9902": ("2026-05-20", "confirmed", "junior"),
    "GM-7731": ("2026-06-02", "confirmed", "standard"),
    "GM-3320": ("2026-07-04", "confirmed", "presidential"),
    "GM-8845": ("2026-04-28", "cancelled", "deluxe"),
}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--mcp-url", default=os.environ.get("HOTEL_MCP_BASE", "http://localhost:9000"),
                   help="Base URL of hotel-mcp, without /mcp.")
    p.add_argument("--token", default=os.environ.get("HOTEL_MCP_ADMIN_TOKEN", ""))
    p.add_argument("--audit-only", action="store_true", help="Print the audit log, do not reset.")
    args = p.parse_args()

    if not args.token:
        sys.exit("Set HOTEL_MCP_ADMIN_TOKEN or pass --token.")

    base = args.mcp_url.rstrip("/").removesuffix("/mcp")
    headers = {"x-admin-token": args.token}

    with httpx.Client(timeout=30.0) as client:
        audit = client.get(f"{base}/admin/audit", headers=headers)
        if audit.status_code != 200:
            sys.exit(f"Audit request failed: {audit.status_code} {audit.text[:200]}")
        entries = audit.json().get("entries", [])
        print(f"{len(entries)} write(s) since the last reset:")
        for e in entries:
            print(f"  {e.get('action'):16} {e.get('booking_ref'):10} by {e.get('subject')}")
        if not entries:
            print("  (none)")

        if args.audit_only:
            return

        reset = client.post(f"{base}/admin/reset", headers=headers)
        if reset.status_code != 200:
            sys.exit(f"Reset failed: {reset.status_code} {reset.text[:200]}")
        print(f"\nReset. {reset.json().get('bookings')} bookings restored.")

        health = client.get(f"{base}/health").json()
        print(json.dumps(health, indent=2))
        if health.get("bookings") != len(EXPECTED):
            sys.exit(f"Expected {len(EXPECTED)} bookings, found {health.get('bookings')}.")
        print("\nBaseline restored.")


if __name__ == "__main__":
    main()
