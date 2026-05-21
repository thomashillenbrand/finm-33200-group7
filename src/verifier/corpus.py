"""Stub corpus: loads canned excerpts from disk.

Iteration 2+ replaces this with a real EDGAR-backed corpus (filings, chunks,
FAISS index, etc., modeled on agentic-rag-edgar-demo's corpus.py). The
interface that `tools.py` consumes from this module is the seam we'll keep
stable across that transition.
"""

from __future__ import annotations

import json
from pathlib import Path

from verifier.schema import EvidenceItem

STUB_PATH = Path(__file__).resolve().parents[2] / "data" / "stub" / "canned_excerpts.json"


def load_stub_excerpts() -> list[EvidenceItem]:
    """Return the canned excerpts as validated `EvidenceItem` objects.

    Validation through `EvidenceItem` keeps the (source, excerpt) contract
    defined in one place (`schema.py`) and catches malformed stub data at
    load time instead of at agent-runtime.
    """
    records = json.loads(STUB_PATH.read_text())
    return [EvidenceItem(**r) for r in records]
