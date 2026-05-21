"""End-to-end smoke tests for the verification agent.

These tests make live OpenAI API calls. They skip cleanly if OPENAI_API_KEY
isn't set in the environment. .env is loaded at import time so running
`pytest` from a shell that hasn't sourced .env still picks up the key.

Each test costs a few cents on gpt-4o-mini and takes ~10–30 seconds.
"""

import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()

from verifier.agent import verify_from_dict
from verifier.schema import EvidenceBundle, Verdict

CLAIM_PATH = Path(__file__).resolve().parents[1] / "data" / "stub" / "example_claim.json"


pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set; smoke tests require live LLM access.",
)


@pytest.mark.live
def test_evidence_mode_runs_end_to_end():
    claim = json.loads(CLAIM_PATH.read_text())
    result = verify_from_dict(claim, mode="evidence", trace=False)
    assert isinstance(result, EvidenceBundle)


@pytest.mark.live
def test_verdict_mode_runs_end_to_end():
    claim = json.loads(CLAIM_PATH.read_text())
    result = verify_from_dict(claim, mode="verdict", trace=False)
    assert isinstance(result, Verdict)
    assert result.verdict in {"verified", "partially_verified", "contradicted", "not_yet_resolvable"}
