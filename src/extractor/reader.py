"""Load earnings-call transcript CSVs and assemble per-call extraction inputs.

Input format: the Capital IQ-style transcript CSV (one row per speaker turn).
Columns used here::

    transcriptid, componentorder, transcriptcomponentid,
    transcriptcomponenttypename, transcriptpersonname, speakertypename,
    componenttext, companyname, headline, mostimportantdateutc

The reader groups turns into calls, filters to management speech, and builds
the single per-call text block the extractor sends to the LLM. Per the
workstream-B design decision, extraction is *per call* (not per turn), so the
model sees prepared remarks and Q&A together and can resolve back-references.
Each turn in the call block is prefixed with its component id so the model can
cite an exact source turn.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# The project's four firms. Extend this map to add firms. The transcript CSV
# carries ``companyname`` but no ticker, so we map it here.
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


def _to_int(value: str) -> int:
    """Parse an id cell. Some columns store ints as floats ('1378846.0')."""
    return int(float(str(value).strip()))


def _fiscal_period(headline: str) -> str:
    """Pull 'Q4 2017' out of a headline like 'Tesla, Inc., Q4 2017 Earnings...'."""
    m = _FISCAL_RE.search(headline or "")
    return f"Q{m.group(1)} {m.group(2)}" if m else ""


def load_calls(csv_path: str | Path) -> list[EarningsCall]:
    """Read a transcript CSV and return its earnings calls, sorted by call date.

    Raises ``KeyError`` if a company has no entry in ``TICKER_BY_COMPANY`` --
    fail loud rather than silently emit claims with no ticker.
    """
    csv_path = Path(csv_path)
    rows_by_call: dict[int, list[dict]] = {}
    with csv_path.open(encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            transcript_id = _to_int(row["transcriptid"])
            rows_by_call.setdefault(transcript_id, []).append(row)

    calls: list[EarningsCall] = []
    for transcript_id, rows in rows_by_call.items():
        rows.sort(key=lambda r: _to_int(r["componentorder"]))
        first = rows[0]
        company = first["companyname"].strip()
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
                component_type=r["transcriptcomponenttypename"].strip(),
                speaker_name=r["transcriptpersonname"].strip(),
                speaker_type=r["speakertypename"].strip(),
                text=r["componenttext"].strip(),
            )
            for r in rows
        ]
        calls.append(
            EarningsCall(
                ticker=ticker,
                company=company,
                transcript_id=transcript_id,
                headline=first["headline"].strip(),
                call_date=date.fromisoformat(first["mostimportantdateutc"].strip()),
                fiscal_period=_fiscal_period(first["headline"]),
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
