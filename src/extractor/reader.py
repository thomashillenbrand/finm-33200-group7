"""Load earnings-call transcript parquet files and assemble per-call extraction inputs.

Input format: the WRDS Capital IQ transcript parquet written by workstream A's
``data_pull.py`` -- ``Pulled_data/<TICKER>/transcript/<TICKER>_transcripts.parquet``.
One row per speaker turn, with columns::

    companyid, companyname, keydevid, transcriptid, headline,
    mostimportantdateutc, transcriptcomponentid, componentorder,
    transcriptcomponenttypename, transcriptpersonname, speaker_company,
    speakertypename, componenttext

Capital IQ stores each earnings call (one ``keydevid``) as several transcript
*versions* (one 'Preliminary' plus several proofed 'Final'/edited copies), each
with its own ``transcriptid``. The reader collapses those versions to one
transcript per call before grouping (see ``_select_transcripts``), so a call is
extracted exactly once.

The reader then groups turns into calls, filters to management speech, and
builds the single per-call text block the extractor sends to the LLM. Per the
workstream-B design decision, extraction is *per call* (not per turn), so the
model sees prepared remarks and Q&A together and can resolve back-references.
Source-turn provenance is recovered afterwards by matching the quote back to a
turn (see ``extractor.provenance``), so no turn ids are exposed to the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# The project's four firms. Extend this map to add firms. The transcript
# parquet carries ``companyname`` but no ticker, so we map it here.
TICKER_BY_COMPANY: dict[str, str] = {
    "Amazon.com, Inc.": "AMZN",
    "The Coca-Cola Company": "KO",
    "Eli Lilly and Company": "LLY",
    "Tesla, Inc.": "TSLA",
}

# Speaker type (``speakertypename``) that carries management claims. Analyst
# questions ("Analysts"), operator boilerplate ("Operator"), and "Attendees"
# are excluded -- only executives make claims we verify against the firm's
# own filings.
MANAGEMENT_SPEAKER_TYPE = "Executives"

_FISCAL_RE = re.compile(r"\bQ([1-4])\s+(\d{4})\b")


@dataclass
class Turn:
    """One transcript component -- an uninterrupted stretch of a single speaker."""

    component_id: int
    component_order: int
    component_type: str
    speaker_name: str
    speaker_type: str
    text: str


@dataclass
class EarningsCall:
    """One earnings call: its metadata plus every turn, in spoken order."""

    ticker: str
    company: str
    transcript_id: int
    headline: str
    call_date: date
    fiscal_period: str
    turns: list[Turn]

    def management_turns(self) -> list[Turn]:
        """Turns spoken by executives -- prepared remarks and Q&A answers."""
        return [t for t in self.turns if t.speaker_type == MANAGEMENT_SPEAKER_TYPE]


def _to_int(value) -> int:
    """Parse an id cell. WRDS parquet stores some ids as floats ('1378846.0')."""
    return int(float(str(value).strip()))


def _clean_str(value) -> str:
    """Render a possibly-null parquet cell as a stripped string ('' for NULL).

    Speaker columns come from LEFT JOINs in ``data_pull.py``, so operator and
    boilerplate rows can carry NULL (read back as ``None`` or NaN).
    """
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _to_date(value) -> date:
    """Parse ``mostimportantdateutc`` -- a string, ``date``, or pandas Timestamp."""
    if isinstance(value, datetime):       # pandas Timestamp subclasses datetime
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _fiscal_period(headline: str) -> str:
    """Pull 'Q4 2017' out of a headline like 'Tesla, Inc., Q4 2017 Earnings...'."""
    m = _FISCAL_RE.search(headline or "")
    return f"Q{m.group(1)} {m.group(2)}" if m else ""


def _load_metadata(parquet_path: Path) -> pd.DataFrame | None:
    """Load the sibling ``<TICKER>_metadata.parquet``, or None if unavailable.

    ``data_pull.py`` writes the metadata parquet next to the transcript parquet;
    it carries the version columns (`transcriptpresentationtypename`,
    `transcriptcreationdate_utc`) needed to pick the final, proofed copy.
    """
    name = parquet_path.name
    if "_transcripts.parquet" not in name:
        return None
    meta_path = parquet_path.with_name(
        name.replace("_transcripts.parquet", "_metadata.parquet")
    )
    if not meta_path.exists():
        return None
    try:
        meta = pd.read_parquet(meta_path)
    except Exception:
        return None
    needed = {
        "transcriptid",
        "transcriptpresentationtypename",
        "transcriptcreationdate_utc",
    }
    return meta if needed.issubset(meta.columns) else None


def _select_transcripts(frame: pd.DataFrame, parquet_path: Path) -> set[int]:
    """Choose one ``transcriptid`` per earnings call, collapsing CIQ versions.

    Capital IQ stores each earnings call (one ``keydevid``) as several
    transcript versions, each a separate ``transcriptid``. Extracting every
    version would re-process the same call several times. Per ``keydevid`` we
    keep the latest 'Final' transcript when the sibling ``*_metadata.parquet``
    is available, and otherwise the transcript with the most components.
    """
    pairs = frame[["keydevid", "transcriptid"]].copy()
    pairs["keydevid"] = pairs["keydevid"].map(_to_int)
    pairs["transcriptid"] = pairs["transcriptid"].map(_to_int)
    counts = pairs.groupby(["keydevid", "transcriptid"]).size().reset_index(name="n")

    meta = _load_metadata(parquet_path)
    if meta is not None:
        meta = meta[
            ["transcriptid", "transcriptpresentationtypename",
             "transcriptcreationdate_utc"]
        ].copy()
        meta["transcriptid"] = meta["transcriptid"].map(_to_int)
        meta["is_final"] = (
            meta["transcriptpresentationtypename"].astype(str).str.lower() == "final"
        ).astype(int)
        meta["created"] = pd.to_datetime(
            meta["transcriptcreationdate_utc"], errors="coerce"
        )
        ranked = counts.merge(
            meta[["transcriptid", "is_final", "created"]],
            on="transcriptid", how="left",
        )
        ranked["is_final"] = ranked["is_final"].fillna(0)
        ranked["created"] = ranked["created"].fillna(pd.Timestamp.min)
        # Best version is last after sorting: Final > Preliminary, then latest
        # creation date, then most components, then highest id.
        ranked = ranked.sort_values(
            ["keydevid", "is_final", "created", "n", "transcriptid"]
        )
    else:
        # No metadata: fall back to the most-complete transcript per call.
        ranked = counts.sort_values(["keydevid", "n", "transcriptid"])

    best = ranked.groupby("keydevid").tail(1)
    return {int(tid) for tid in best["transcriptid"]}


def load_calls(parquet_path: str | Path) -> list[EarningsCall]:
    """Read a transcript parquet and return its earnings calls, sorted by date.

    One parquet holds every call for a firm. Capital IQ's multiple transcript
    versions are collapsed to one per earnings call (``keydevid``) before
    grouping. Raises ``KeyError`` if a company has no entry in
    ``TICKER_BY_COMPANY`` -- fail loud rather than silently emit claims with no
    ticker.
    """
    parquet_path = Path(parquet_path)
    frame = pd.read_parquet(parquet_path)

    # Collapse Capital IQ transcript versions: one transcript per call. When
    # the parquet carries no ``keydevid`` we cannot group by call, so each
    # transcriptid is treated as its own call.
    keep_ids: set[int] | None = None
    if "keydevid" in frame.columns:
        keep_ids = _select_transcripts(frame, parquet_path)

    rows_by_call: dict[int, list[dict]] = {}
    for record in frame.to_dict("records"):
        transcript_id = _to_int(record["transcriptid"])
        if keep_ids is not None and transcript_id not in keep_ids:
            continue
        rows_by_call.setdefault(transcript_id, []).append(record)

    calls: list[EarningsCall] = []
    for transcript_id, rows in rows_by_call.items():
        rows.sort(key=lambda r: _to_int(r["componentorder"]))
        first = rows[0]
        company = _clean_str(first["companyname"])
        ticker = TICKER_BY_COMPANY.get(company)
        if ticker is None:
            raise KeyError(
                f"No ticker mapping for company {company!r}. "
                f"Add it to TICKER_BY_COMPANY in extractor/reader.py."
            )
        turns = [
            Turn(
                component_id=_to_int(r["transcriptcomponentid"]),
                component_order=_to_int(r["componentorder"]),
                component_type=_clean_str(r["transcriptcomponenttypename"]),
                speaker_name=_clean_str(r["transcriptpersonname"]),
                speaker_type=_clean_str(r["speakertypename"]),
                text=_clean_str(r["componenttext"]),
            )
            for r in rows
        ]
        headline = _clean_str(first["headline"])
        calls.append(
            EarningsCall(
                ticker=ticker,
                company=company,
                transcript_id=transcript_id,
                headline=headline,
                call_date=_to_date(first["mostimportantdateutc"]),
                fiscal_period=_fiscal_period(headline),
                turns=turns,
            )
        )

    calls.sort(key=lambda c: c.call_date)
    return calls


def build_call_input(call: EarningsCall) -> str:
    """Build the per-call text block sent to the LLM.

    Only management turns are included, each labelled with its speaker. No turn
    ids are shown: the model is not asked to report provenance (pilot showed
    model-reported ids are unreliable). Each claim's source turn is recovered
    afterwards by matching the quote back to a turn (see ``extractor.provenance``).
    """
    blocks = [
        f"{t.speaker_name} ({t.component_type}):\n{t.text}"
        for t in call.management_turns()
    ]
    return "\n\n".join(blocks)
