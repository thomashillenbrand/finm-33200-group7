"""CLI entry point: `python -m verifier.run --claim path/to/claim.json --mode {evidence,verdict}`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from verifier.agent import verify_from_dict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verifier.run", description=__doc__)
    parser.add_argument("--claim", required=True, type=Path,
                        help="Path to a JSON file describing one claim.")
    parser.add_argument("--mode", default="evidence",
                        choices=["evidence", "verdict"],
                        help="evidence (safe for labeling, default) or verdict")
    parser.add_argument("--no-cache", action="store_true",
                        help="Bypass the SQLite chat-completion cache for this run. "
                             "WARNING: cached responses are returned for identical "
                             "prompts by default; pass --no-cache for fresh LLM calls.")
    args = parser.parse_args(argv)

    load_dotenv()
    claim_dict = json.loads(args.claim.read_text(encoding="utf-8"))
    result = verify_from_dict(claim_dict, mode=args.mode, cache=not args.no_cache)

    print()
    print("=" * 60)
    print(f"Mode: {args.mode}")
    print("=" * 60)
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
