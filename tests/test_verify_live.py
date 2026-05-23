"""End-to-end live test: run verify() against the real TSLA index with a real
capital-allocation claim, assert sane evidence.

The pilot claims CSV is TSLA-only (24 claims, 12 capital_allocation), so iter-2's
first live target is TSLA. AMZN/KO/LLY are also indexed; extending this test to
them is one extraction PR away.

Gated by:
  - the `live` pytest marker (run with `pytest -m live`)
  - OPENAI_API_KEY env var
  - pulled_data/TSLA/index/ existing locally (built by `python -m verifier.index TSLA`)
  - data/claims/pilot_claims.csv existing locally
"""

import os
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from dotenv import load_dotenv

load_dotenv()

from schemas import EvidenceBundle
from verifier.agent import verify_from_dict

TICKER = "TSLA"
INDEX_PARQUET = Path("pulled_data") / TICKER / "index" / "chunks.parquet"
PILOT_CLAIMS = Path("data") / "claims" / "pilot_claims.csv"


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"),
                       reason="OPENAI_API_KEY not set"),
    pytest.mark.skipif(not INDEX_PARQUET.exists(),
                       reason=f"{TICKER} index not built; run `python -m verifier.index {TICKER}`"),
    pytest.mark.skipif(not PILOT_CLAIMS.exists(),
                       reason="data/claims/pilot_claims.csv missing"),
]


def _first_capital_allocation_claim() -> dict:
    """Pick the first capital_allocation claim for TICKER from the pilot CSV."""
    df = pd.read_csv(PILOT_CLAIMS)
    cap = df[(df["ticker"] == TICKER) & (df["claim_type"] == "capital_allocation")]
    if cap.empty:
        pytest.skip(f"No {TICKER} capital-allocation claims in pilot CSV")
    row = cap.iloc[0]
    # The pilot CSV's schema may differ from the iter-2 combined Claim shape.
    # Fill in defaults for fields the CSV doesn't carry; this is a smoke test,
    # not a contract test.
    return {
        "claim_id": str(row.get("claim_id", f"{TICKER}_pilot_{row.name}")),
        "ticker": row["ticker"],
        "call_date": row["call_date"],
        "company": str(row.get("company", "")),
        "fiscal_period": str(row.get("fiscal_period", "")),
        "source_call": str(row.get("source_call", "")),
        "claim_type": row["claim_type"],
        "verbatim_quote": str(row.get("verbatim_quote", "")),
        "summary": str(row.get("summary", row.get("verbatim_quote", ""))),
        "horizon_raw": str(row.get("horizon_raw", "")),
        "horizon_period": str(row.get("horizon_period", "")),
        "horizon_end_date": (row.get("horizon_end_date") or None),
        "transcript_id": int(row["transcript_id"]),
        "component_id": int(row["component_id"]),
    }


def test_verify_evidence_against_real_index():
    claim_dict = _first_capital_allocation_claim()
    claim_call_date = date.fromisoformat(claim_dict["call_date"])
    bundle = verify_from_dict(claim_dict, mode="evidence", trace=False)
    assert isinstance(bundle, EvidenceBundle)
    # We don't require >0 items (the agent may legitimately return empty for
    # not-yet-resolvable claims), but if items exist they must satisfy:
    for item in bundle.items:
        assert item.filing_date >= claim_call_date, (
            f"Time leak: {item.form} filed {item.filing_date} "
            f"predates the call ({claim_call_date})"
        )
