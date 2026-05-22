from __future__ import annotations

from pathlib import Path

import pandas as pd


class TranscriptLoader:
    """Load transcript components from a WRDS-format parquet file.

    The parquet has one row per transcript component. Multiple rows share a
    transcriptid; they are joined in componentorder.
    """

    def __init__(self, parquet_path: str | Path) -> None:
        path = Path(parquet_path)
        if not path.exists():
            raise FileNotFoundError(f"Parquet not found: {path}")
        self._df = pd.read_parquet(path)

    def list_calls(self) -> pd.DataFrame:
        """One row per earnings call, sorted oldest-first."""
        return (
            self._df[["transcriptid", "headline", "mostimportantdateutc"]]
            .drop_duplicates(subset=["transcriptid"])
            .sort_values("mostimportantdateutc")
            .reset_index(drop=True)
        )

    def get_transcript(self, transcript_id: int) -> str:
        """Assemble full transcript text for one call, sorted by componentorder."""
        rows = self._df[self._df["transcriptid"] == transcript_id]
        if rows.empty:
            raise KeyError(f"transcript_id {transcript_id} not found")
        ordered = rows.sort_values("componentorder")
        parts = []
        for _, row in ordered.iterrows():
            name = row.get("transcriptpersonname") or ""
            text = row.get("componenttext") or ""
            if name:
                parts.append(f"{name}: {text}")
            else:
                parts.append(text)
        return "\n\n".join(p for p in parts if p.strip())
