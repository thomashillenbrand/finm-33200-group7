"""Agent-free gold-set labeling helper (`python -m verifier.label`).

For one extracted claim, this CLI surfaces the SEC filings to read and helps a
human locate + copy the relevant passages into a valid gold-set row. It removes
the *mechanical* friction of labeling — finding accession numbers, locating
passages in HTML, hand-formatting JSON. The human still reads the filings and
assigns the verdict (see `docs/labeling_rubric.md`).

INDEPENDENCE CONSTRAINT (load-bearing — do not break).
The gold set grades the verification agent's retrieval (recall@k). If a labeler
seeds evidence from what the agent surfaced, that score is circular. So this
module must NOT import or call any of: `verifier.agent` / `verify`, `faiss`,
`OpenAIEmbeddings`, `verifier.tools`, and must NOT read the `index/` artifacts
(`chunks.parquet` / `faiss.index`). It finds evidence by an independent
mechanism: deterministic keyword/regex search over the raw filing text.

It deliberately does NOT reuse `verifier.index.extract_text_from_html`: importing
`verifier.index` would transitively pull `faiss` and `OpenAIEmbeddings` into this
module's import graph, breaking the constraint above. The small `_html_to_text`
helper here is pure HTML->text with no ranking, so duplicating it is safe.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from schemas import Claim
from verifier.gold import GoldEvidence

# Root for data_pull's per-ticker output. Patchable so tests can point it at a
# fixture directory.
PULLED_DATA_ROOT = Path("Pulled_data")

# Gold evidence may only come from these forms (matches GoldEvidence.form).
_FORMS: tuple[str, ...] = ("10-K", "10-Q", "8-K")

# Suggested --query terms by claim type, printed when no --query is given. A
# deterministic aid that closes most of the keyword-misses-paraphrase gap
# without an LLM (a labeler searching "buyback" would otherwise miss a filing
# that says "repurchases of common stock").
_QUERY_HINTS: dict[str, list[str]] = {
    "capital_allocation": [
        "repurchase", "buyback", "treasury stock",
        "dividend", "distribution",
        "capital expenditures", "capex", "property and equipment",
        "senior notes", "credit facility", "borrowings", "repaid", "redeemed",
    ],
}


@dataclass
class Match:
    """One keyword/regex hit inside a filing's text."""

    char_start: int
    char_end: int
    snippet: str


# ── HTML -> text ───────────────────────────────────────────────────────────

def _html_to_text(html_bytes: bytes) -> str:
    """Flatten filing HTML to paragraph-separated text. Pure, no ranking."""
    soup = BeautifulSoup(html_bytes, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


# ── Claim loading (CSV row -> schemas.Claim) ───────────────────────────────

# Optional date/datetime fields are written as "" by the extractor's CSV
# writer; restore them to None before constructing the pydantic model.
_OPTIONAL_DATE_FIELDS = ("horizon_end_date", "extracted_at")


def _row_to_claim(row: dict) -> Claim:
    data = dict(row)
    for field in _OPTIONAL_DATE_FIELDS:
        if data.get(field, "") == "":
            data[field] = None
    return Claim(**data)


def load_claim(claims_csv: str | Path, claim_id: str) -> Claim:
    """Return the one claim with ``claim_id`` from the claims CSV."""
    path = Path(claims_csv)
    if not path.exists():
        raise SystemExit(f"claims CSV not found: {path}")
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("claim_id") == claim_id:
                return _row_to_claim(row)
    raise SystemExit(f"claim_id {claim_id!r} not found in {path}")


# ── Filing index + candidate filings ───────────────────────────────────────

def _load_filing_index(ticker: str) -> pd.DataFrame:
    """Load the per-ticker SEC filings index parquet (camelCase columns)."""
    path = PULLED_DATA_ROOT / ticker / "SEC" / f"{ticker}_sec_filings_index.parquet"
    if not path.exists():
        raise SystemExit(f"SEC filing index not found: {path}")
    df = pd.read_parquet(path)
    df["filingDate"] = pd.to_datetime(df["filingDate"]).dt.date
    return df


def candidate_filings(
    claim: Claim,
    index_df: pd.DataFrame,
    *,
    forms: tuple[str, ...] = _FORMS,
    from_date: date | None = None,
    until_date: date | None = None,
) -> pd.DataFrame:
    """Filings that could hold evidence for ``claim``: filed strictly after the
    call, restricted to ``forms``, optionally bounded, sorted by date."""
    df = index_df[index_df["form"].isin(forms)].copy()
    df = df[df["filingDate"] > claim.call_date]
    if from_date is not None:
        df = df[df["filingDate"] >= from_date]
    if until_date is not None:
        df = df[df["filingDate"] <= until_date]
    return df.sort_values("filingDate").reset_index(drop=True)


def _resolve_filing_path(sec_dir: Path, local_path: str) -> Path:
    """Join a localPath from the index (stored with Windows separators) to disk."""
    return sec_dir / Path(str(local_path).replace("\\", "/"))


# ── Keyword search ─────────────────────────────────────────────────────────

def search_filing(
    text: str, query: str, *, regex: bool = False, context: int = 240
) -> list[Match]:
    """Find every case-insensitive hit of ``query`` in ``text``.

    Literal substring by default; ``regex=True`` compiles ``query`` as a regex.
    Each Match carries a +/- ``context`` character window around the hit.
    """
    pattern = re.compile(query if regex else re.escape(query), re.IGNORECASE)
    matches: list[Match] = []
    for m in pattern.finditer(text):
        start = max(0, m.start() - context)
        end = min(len(text), m.end() + context)
        matches.append(Match(m.start(), m.end(), text[start:end].strip()))
    return matches


# ── Rendering ──────────────────────────────────────────────────────────────

def _render_claim(claim: Claim) -> str:
    return (
        f"=== CLAIM {claim.claim_id} ===\n"
        f"  {claim.ticker} ({claim.company}) -- call {claim.call_date}\n"
        f"  type:    {claim.claim_type}\n"
        f"  quote:   {claim.verbatim_quote}\n"
        f"  summary: {claim.summary}\n"
        f"  horizon: {claim.horizon_raw or '(none stated)'}  ->  "
        f"{claim.horizon_period or '(unresolved)'} "
        f"(end {claim.horizon_end_date or 'n/a'})\n"
        f"  Evidence must come from filings filed AFTER {claim.call_date}."
    )


def _render_filing_list(df: pd.DataFrame) -> str:
    if df.empty:
        return ("\nNo candidate filings: none in the requested forms were filed "
                "after the call date.")
    lines = ["", f"=== {len(df)} candidate filing(s) filed after the call ==="]
    for r in df.itertuples(index=False):
        lines.append(
            f"  {r.form:<5} {r.filingDate}  {r.accessionNumber}  {r.localPath}"
        )
    return "\n".join(lines)


def _render_query_hint(claim: Claim) -> str:
    terms = _QUERY_HINTS.get(claim.claim_type)
    if terms:
        joined = ", ".join(f'"{t}"' for t in terms)
        return ("\nNo --query given. Re-run with --query to search the filings "
                f"above.\nSuggested terms for a {claim.claim_type} claim: {joined}")
    return '\nNo --query given. Re-run with --query "<term>" to search the filings above.'


def _render_evidence(filing_row, match: Match) -> str:
    """Header + context window + a paste-ready GoldEvidence JSON fragment."""
    quote = match.snippet
    truncated = len(quote) > 500
    if truncated:
        quote = quote[:500]
    fragment = GoldEvidence(
        accession_no=str(filing_row.accessionNumber),
        form=filing_row.form,
        filing_date=filing_row.filingDate,
        quote=quote,
        section=None,
    )
    header = (f"[{filing_row.form} filed {filing_row.filingDate} | "
              f"accession {filing_row.accessionNumber} | open: {filing_row.localPath}]")
    note = "\n  (quote truncated to 500 chars)" if truncated else ""
    return (f"\n{header}\n"
            f"  ...{match.snippet}...\n"
            f"  fragment: {fragment.model_dump_json()}{note}")


def _render_skeleton(claim: Claim, labeler: str) -> str:
    """A GoldLabel line with placeholder verdict/confidence.

    The placeholders are intentionally invalid, so `verifier.gold.load_gold_labels`
    rejects the row until a human fills them -- a forgotten verdict fails loud.
    """
    skeleton = {
        "claim_id": claim.claim_id,
        "ticker": claim.ticker,
        "labeler": labeler,
        "labeled_at": datetime.now().isoformat(timespec="seconds"),
        "expected_evidence": [],
        "verdict": "<FILL: verified|partially_verified|contradicted|not_yet_resolvable>",
        "confidence": "<FILL: high|medium|low>",
        "labeler_notes": "",
    }
    return json.dumps(skeleton)


# ── CLI ────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="verifier.label", description=__doc__)
    p.add_argument("--claims", required=True, type=Path,
                   help="Path to the claims CSV (e.g. data/claims/pilot_claims.csv).")
    p.add_argument("--claim-id", required=True, help="The claim_id to label.")
    p.add_argument("--labeler", required=True, help="Your name, for the skeleton.")
    p.add_argument("--query", default=None,
                   help="Keyword (or regex, with --regex) to search the filings.")
    p.add_argument("--regex", action="store_true",
                   help="Treat --query as a regular expression.")
    p.add_argument("--forms", default=None,
                   help="Comma-separated forms to consider (default: 10-K,10-Q,8-K).")
    p.add_argument("--context", type=int, default=240,
                   help="Characters of context around each match (default 240).")
    p.add_argument("--from", dest="from_date", default=None,
                   help="Only filings on/after this date (YYYY-MM-DD).")
    p.add_argument("--until", dest="until_date", default=None,
                   help="Only filings on/before this date (YYYY-MM-DD).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    claim = load_claim(args.claims, args.claim_id)
    forms = (tuple(f.strip() for f in args.forms.split(",")) if args.forms
             else _FORMS)
    from_date = date.fromisoformat(args.from_date) if args.from_date else None
    until_date = date.fromisoformat(args.until_date) if args.until_date else None

    print(_render_claim(claim))

    index_df = _load_filing_index(claim.ticker)
    candidates = candidate_filings(
        claim, index_df, forms=forms, from_date=from_date, until_date=until_date
    )
    print(_render_filing_list(candidates))

    if not args.query:
        print(_render_query_hint(claim))
    else:
        sec_dir = PULLED_DATA_ROOT / claim.ticker / "SEC"
        hits = 0
        for filing_row in candidates.itertuples(index=False):
            fpath = _resolve_filing_path(sec_dir, filing_row.localPath)
            if not fpath.exists():
                print(f"\n  [skip] filing HTML not on disk: {fpath}", file=sys.stderr)
                continue
            text = _html_to_text(fpath.read_bytes())
            for match in search_filing(
                text, args.query, regex=args.regex, context=args.context
            ):
                hits += 1
                print(_render_evidence(filing_row, match))
        if hits == 0:
            print(f'\nNo matches for {args.query!r}. Try another term '
                  f'(see suggestions with no --query).')

    print("\n--- GoldLabel skeleton: fill verdict/confidence, paste evidence "
          "fragments into expected_evidence, append to data/gold/pilot_"
          f"{claim.ticker.lower()}.jsonl ---")
    print(_render_skeleton(claim, args.labeler))
    return 0


if __name__ == "__main__":
    sys.exit(main())
