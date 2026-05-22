"""Link an extracted claim back to the speaker turn it came from.

Given the raw transcript DataFrame (from TranscriptLoader) and a source_span,
find the component row whose text contains that span and return speaker metadata.
"""

from __future__ import annotations

import pandas as pd


def find_speaker(source_span: str, transcript_df: pd.DataFrame) -> dict:
    """Return speaker info for the turn containing source_span.

    Searches componenttext for the verbatim span. Returns a dict with:
      speaker       — name of the person who said it (or None)
      speaker_type  — 'Corporate Participant', 'Analyst', etc. (or None)
      component_order — position in the transcript (or None)

    If no match is found (hallucinated span), all values are None.
    """
    span = source_span.strip()
    for _, row in transcript_df.iterrows():
        text = str(row.get("componenttext") or "")
        if span in text or span[:60] in text:
            return {
                "speaker": row.get("transcriptpersonname") or None,
                "speaker_type": row.get("speakertypename") or None,
                "component_order": int(row["componentorder"]) if pd.notna(row.get("componentorder")) else None,
            }
    return {"speaker": None, "speaker_type": None, "component_order": None}


def is_management_speaker(speaker_type: str | None) -> bool:
    """Return True if the speaker type indicates a company executive (not an analyst)."""
    if not speaker_type:
        return False
    return "corporate" in speaker_type.lower() or "company" in speaker_type.lower()
