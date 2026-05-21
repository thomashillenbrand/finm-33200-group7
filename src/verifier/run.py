"""CLI entry point: `python -m verifier.run --claim path/to/claim.json --mode {evidence,verdict}`.

Designed for teammates who want to sanity-check the agent without writing Python.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from verifier.agent import verify_from_dict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verifier.run", description=__doc__)
    parser.add_argument("--claim", required=True, type=Path, help="Path to a JSON file describing one claim.")
    parser.add_argument(
        "--mode",
        default="evidence",
        choices=["evidence", "verdict"],
        help="evidence (safe for labeling, default) or verdict",
    )
    args = parser.parse_args(argv)

    load_dotenv()

    # Malformed input — missing file, invalid JSON, or schema-invalid claim —
    # produces a Python traceback by design. The traceback is diagnostic for
    # iteration 1; we don't wrap these in pretty error messages.
    claim_dict = json.loads(args.claim.read_text(encoding="utf-8"))
    result = verify_from_dict(claim_dict, mode=args.mode)

    print()
    print("=" * 60)
    print(f"Mode: {args.mode}")
    print("=" * 60)
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
