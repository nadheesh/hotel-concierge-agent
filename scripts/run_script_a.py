#!/usr/bin/env python3
"""Script A — representative traffic for hallucination and reasoning quality.

Sends the 10 quality cases and writes one result row per case. Point Agent
Manager's hallucination and reasoning-quality evaluators at the resulting
traffic; the `expected` and `ground_truth` fields in the fixture are the
reference answers.

    AGENT_URL=https://<gateway>/<agent-endpoint> \
    AGENT_TOKEN_URL=https://<idp>/oauth2/token \
    AGENT_CLIENT_ID=<id> AGENT_CLIENT_SECRET=<secret> \
    python scripts/run_script_a.py

    python scripts/run_script_a.py --category out-of-corpus
    python scripts/run_script_a.py --agent-url https://<agent>/chat --token <jwt>

Connection settings come from the environment, the same names web/run.sh uses.
Set all three of AGENT_TOKEN_URL, AGENT_CLIENT_ID and AGENT_CLIENT_SECRET and a
fresh token is fetched per run. AGENT_INSECURE_TLS=1 skips certificate
verification for a dev cluster. A flag beats the environment.

This script only generates traffic. Scoring happens in the console; the rubric
in evaluators/quality/grounded-refusal.md is the reference for configuring the
evaluator there, not something this script reads.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import FIXTURES, base_parser, iter_results, write_results


def main() -> None:
    args = base_parser(__doc__.split("\n")[0]).parse_args()
    rows = list(iter_results(args, "script_a_cases.jsonl"))

    out = Path(args.out) if args.out else FIXTURES / "script_a_results.jsonl"
    write_results(rows, out)

    print("\nCases by category:", file=sys.stderr)
    for cat, n in sorted(Counter(r["category"] for r in rows).items()):
        print(f"  {cat:22} {n:3}", file=sys.stderr)
    print("\nHallucination and reasoning quality are scored in the console, not here.",
          file=sys.stderr)


if __name__ == "__main__":
    main()
