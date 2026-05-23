"""EvidenceBundle — the evidence-mode output. By construction, no verdict
field. The labeling workflow depends on this structural absence (see CLAUDE.md
and `test_evidence_bundle_has_no_verdict_field`).
"""

from __future__ import annotations

from pydantic import BaseModel

from schemas.evidence_item import EvidenceItem


class EvidenceBundle(BaseModel):
    items: list[EvidenceItem]
