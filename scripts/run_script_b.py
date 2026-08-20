#!/usr/bin/env python3
"""Script B — adversarial traffic across all seven security categories.

Sends the 43 security cases, each labelled with exactly one primary category
and an expected safe outcome, and writes one result row per case.

    AGENT_URL=https://<gateway>/<agent-endpoint> \
    AGENT_TOKEN_URL=https://<idp>/oauth2/token \
    AGENT_CLIENT_ID=<id> AGENT_CLIENT_SECRET=<secret> \
    python scripts/run_script_b.py

    python scripts/run_script_b.py --deployment ops --category unauthorized-tool
    python scripts/run_script_b.py --agent-url https://<customer-agent>/chat --token <jwt>

Connection settings come from the environment, the same names web/run.sh uses.
Set all three of AGENT_TOKEN_URL, AGENT_CLIENT_ID and AGENT_CLIENT_SECRET and a
fresh token is fetched per run. AGENT_INSECURE_TLS=1 skips certificate
verification for a dev cluster. A flag beats the environment.

Cases marked deployment "both" run against whichever endpoint you pass; run
them twice, once per deployment, and compare. Identical agent, identical
attack, different blast radius, decided entirely by scope configuration — that
comparison is the clearest result this suite produces. Run once with AGENT_URL
pointed at one deployment, again with it pointed at the other.

This script only generates traffic. Scoring happens in the console, one
evaluator per category; the rubrics under evaluators/security/ are the
reference for configuring them. Note when reading those results that the suite
is framed as RESILIENCE — higher is better, 100% means every attack was
withstood — which is the inverse of an attack-success rate.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import FIXTURES, base_parser, iter_results, write_results


def main() -> None:
    parser = base_parser(__doc__.split("\n")[0])
    parser.add_argument("--deployment", choices=["customer", "ops"], default="customer",
                        help="Which deployment the endpoint belongs to. Recorded on every row.")
    args = parser.parse_args()

    rows = []
    for row in iter_results(args, "script_b_cases.jsonl"):
        row["run_against"] = args.deployment
        rows.append(row)

    out = Path(args.out) if args.out else FIXTURES / f"script_b_results_{args.deployment}.jsonl"
    write_results(rows, out)

    print(f"\nCoverage ({args.deployment} deployment):", file=sys.stderr)
    for cat, n in sorted(Counter(r["category"] for r in rows).items()):
        legit = sum(1 for r in rows if r["category"] == cat and r["legitimate"])
        print(f"  {cat:22} {n:3} cases ({legit} legitimate control)", file=sys.stderr)

    print("\nTraffic only. Score it with the console's evaluators, one per category\n"
          "(see evaluators/security/README.md).", file=sys.stderr)


if __name__ == "__main__":
    main()
