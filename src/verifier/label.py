"""Agent-free gold-set labeling helper (`python -m verifier.label`).

Interactive: one command per claim. For a given claim_id it runs a deterministic
keyword sweep over the claim's post-call SEC filings, shows candidate passages,
and walks the labeler through picking evidence and assigning a verdict in the
terminal -- then appends one validated GoldLabel row to the gold JSONL. No
hand-editing of files.

    python -m verifier.label --claims data/claims/pilot_claims.csv \\
        --claim-id TSLA_20200129_xxxx --labeler brendan

INDEPENDENCE CONSTRAINT (load-bearing -- do not break).
The gold set grades the verification agent's retrieval (recall@k). If a labeler
seeds evidence from what the agent surfaced, that score is circular. So this
module must NOT import or call any of: `verifier.agent` / `verify`, `faiss`,
`OpenAIEmbeddings`, `verifier.tools`, and must NOT read the `index/` artifacts.
The sweep is deterministic keyword search -- it never ranks by embeddings or an
LLM, and the labeler (not the tool) decides what counts as evidence.

This supersedes the print-only design in `docs/labeling-helper-design.md`
(interactive grading + auto sweep were added for labeling-throughput).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from schemas import Claim
from verifier.gold import GoldEvidence, GoldLabel

# Root for data_pull's per-ticker output; gold-set directory. Both patchable.
PULLED_DATA_ROOT = Path("pulled_data")
GOLD_DIR = Path("data/gold")

_FORMS: tuple[str, ...] = ("10-K", "10-Q", "8-K")
_DEFAULT_WINDOW_DAYS = 730       # ~2 years, when the claim horizon is unresolved
_REPORTING_LAG_DAYS = 150        # filing that reports a period lands months later
_DISPLAY_LIMIT = 5

_VERDICTS = ("verified", "partially_verified", "contradicted", "not_yet_resolvable")
_DECISIVE = {"verified", "partially_verified", "contradicted"}
_CONFIDENCE = {"h": "high", "m": "medium", "l": "low"}

# Deterministic per-claim-type sweep terms -- the keyword loop a labeler would
# otherwise run by hand. No LLM, no embeddings: this stays an independent,
# transparent search. Specific financial-statement line items lead each group;
# the bare keywords stay as recall fallback but rank below the phrases (see
# `_relevance`).
_SWEEP_TERMS: dict[str, list[str]] = {
    "capital_allocation": [
        # share repurchases -- cash-flow / equity line items first
        "repurchases of common stock", "repurchase of common stock",
        "purchases of treasury stock", "treasury stock",
        "repurchase", "buyback",
        # dividends
        "dividends paid", "dividends declared", "cash dividends",
        "dividend", "distribution",
        # capital expenditures
        "purchases of property and equipment", "capital expenditures",
        "additions to property", "property and equipment",
        # debt
        "proceeds from issuance of debt", "repayments of long-term debt",
        "senior notes", "credit facility", "borrowings", "repaid", "redeemed",
    ],
}


@dataclass
class Match:
    """One keyword hit inside a filing's text."""

    char_start: int
    char_end: int
    snippet: str


@dataclass
class Candidate:
    """One sweep hit, ready to be shown and (if chosen) turned into evidence."""

    accession_no: str
    form: str
    filing_date: date
    local_path: str
    term: str
    snippet: str
    report_date: date | None = None

    def to_evidence(self) -> GoldEvidence:
        return GoldEvidence(
            accession_no=self.accession_no,
            form=self.form,
            filing_date=self.filing_date,
            quote=self.snippet[:500],          # schema cap
            section=None,
        )


# ── HTML -> text ───────────────────────────────────────────────────────────

def _html_to_text(html_bytes: bytes) -> str:
    """Flatten filing HTML to paragraph-separated text. Pure, no ranking."""
    soup = BeautifulSoup(html_bytes, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


# ── Claim loading ──────────────────────────────────────────────────────────

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
    if "reportDate" in df.columns:
        df["reportDate"] = pd.to_datetime(df["reportDate"], errors="coerce").dt.date
    return df


def grading_window(claim: Claim) -> date:
    """Upper date bound for filings worth scanning.

    The claim's resolved horizon end (plus a reporting lag, since the filing
    that *reports* a period is filed months after it), or -- when the horizon
    is unresolved -- ~2 years after the call, so an open-ended claim does not
    pull every filing through to the present.
    """
    base = claim.horizon_end_date
    if base is None:
        base = claim.call_date + timedelta(days=_DEFAULT_WINDOW_DAYS)
    return base + timedelta(days=_REPORTING_LAG_DAYS)


def candidate_filings(
    claim: Claim,
    index_df: pd.DataFrame,
    *,
    forms: tuple[str, ...] = _FORMS,
    from_date: date | None = None,
    until_date: date | None = None,
    horizon_end: date | None = None,
) -> pd.DataFrame:
    """Filings that could hold evidence: filed strictly after the call,
    restricted to ``forms``, optionally bounded, sorted by date.

    The no-time-leak guard (`filingDate > call_date`) is always applied. When
    ``horizon_end`` is given, filings are additionally bounded by the period
    they *report* (`reportDate <= horizon_end`), not by when they were filed --
    so a late-filed annual 10-K that reports the horizon year is kept, while a
    next-year quarterly filed inside the old reporting-lag tail is dropped.
    ``until_date`` still bounds by filing date for manual overrides / the
    unresolved-horizon fallback.
    """
    df = index_df[index_df["form"].isin(forms)].copy()
    df = df[df["filingDate"] > claim.call_date]      # no-time-leak guard
    if horizon_end is not None and "reportDate" in df.columns:
        period = df["reportDate"].where(df["reportDate"].notna(), df["filingDate"])
        df = df[period <= horizon_end]               # don't report beyond the horizon
    if from_date is not None:
        df = df[df["filingDate"] >= from_date]
    if until_date is not None:
        df = df[df["filingDate"] <= until_date]
    return df.sort_values("filingDate").reset_index(drop=True)


def _resolve_filing_path(sec_dir: Path, local_path: str) -> Path:
    """Join a localPath from the index (Windows separators) to disk."""
    return sec_dir / Path(str(local_path).replace("\\", "/"))


# ── Keyword search + sweep ─────────────────────────────────────────────────

def search_filing(
    text: str, query: str, *, regex: bool = False, context: int = 240
) -> list[Match]:
    """Every case-insensitive hit of ``query`` in ``text`` (+/- context window)."""
    pattern = re.compile(query if regex else re.escape(query), re.IGNORECASE)
    matches: list[Match] = []
    for m in pattern.finditer(text):
        start = max(0, m.start() - context)
        end = min(len(text), m.end() + context)
        matches.append(Match(m.start(), m.end(), text[start:end].strip()))
    return matches


# Inline-XBRL / taxonomy fragments sometimes survive HTML->text flattening
# (e.g. "0000059478 us-gaap:RestrictedStockUnitsRSUMember 2019-12-31"). They
# carry no human-readable evidence, so a hit whose context is XBRL is dropped
# rather than shown to the labeler.
_NOISE_MARKERS = ("us-gaap:", "xbrli", "iso4217:", "dei:", "srt:", "xmlns")


def _is_noise(snippet: str) -> bool:
    low = snippet.lower()
    return any(marker in low for marker in _NOISE_MARKERS)


# Which sweep terms belong to each capital-allocation subcategory, and the cues
# in a claim's own text that say which subcategory it is about. Used to focus
# the ranking on the claim's topic (a dividend claim should surface the dividend
# line, not the longer capex phrase). Pure keyword matching on the claim text --
# this is the missing `subcategory` field, inferred deterministically for the
# duration of one labeling session; it never reads the agent or an embedding.
_SUBCATEGORY_TERMS: dict[str, set[str]] = {
    "buyback": {"repurchases of common stock", "repurchase of common stock",
                "purchases of treasury stock", "treasury stock",
                "repurchase", "buyback"},
    "dividend": {"dividends paid", "dividends declared", "cash dividends",
                 "dividend", "distribution"},
    "capex": {"purchases of property and equipment", "capital expenditures",
              "additions to property", "property and equipment"},
    "debt": {"proceeds from issuance of debt", "repayments of long-term debt",
             "senior notes", "credit facility", "borrowings", "repaid", "redeemed"},
}
_CLAIM_FOCUS_CUES: dict[str, tuple[str, ...]] = {
    "buyback": ("repurchas", "buyback", "buy back", "treasury", "share repurchase"),
    "dividend": ("dividend", "distribution", "return cash", "return capital", "payout"),
    "capex": ("capital expenditure", "capex", "capital invest", "capital spending",
              "factory", "facility", "plant", "construct", "fulfillment",
              "capacity", "property and equipment", "build"),
    "debt": ("debt", "notes", "borrow", "credit facility", "leverage",
             "refinanc", "repay", "redeem", "issuance"),
}


def _claim_focus(claim: Claim) -> set[str]:
    """Terms to prioritize, inferred from the claim's own quote + summary.

    Empty when no cue matches -- ranking then falls back to pure specificity.
    """
    text = f"{claim.verbatim_quote} {claim.summary}".lower()
    focus: set[str] = set()
    for subcat, cues in _CLAIM_FOCUS_CUES.items():
        if any(cue in text for cue in cues):
            focus |= _SUBCATEGORY_TERMS[subcat]
    return focus


# Bigger than any specificity+dollar score below, so a term matching the claim's
# own subcategory always outranks an off-topic hit regardless of phrase length.
_FOCUS_BONUS = 10


def _relevance(term: str, snippet: str, focus: set[str] | tuple = ()) -> int:
    """Deterministic, transparent relevance score for ranking sweep hits.

    Not semantic and not learned -- it just encodes what a human skims for: a
    term matching the claim's own subcategory (`focus`) wins outright, then a
    multi-word line item ("repurchases of common stock") beats a bare keyword,
    and a hit sitting next to a dollar figure beats the same term in prose. No
    embeddings, no LLM -- the independence guarantee is untouched.
    """
    score = len(term.split())
    low = snippet.lower()
    if "$" in snippet or "million" in low or "billion" in low:
        score += 2
    if term in focus:
        score += _FOCUS_BONUS
    return score


def sweep(
    filings_df: pd.DataFrame,
    sec_dir: Path,
    *,
    terms: list[str],
    context: int = 240,
    focus: set[str] | tuple = (),
) -> list[Candidate]:
    """Deterministic keyword sweep over the candidate filings.

    Per filing, takes the first hit of each term, drops inline-XBRL noise, then
    ranks all hits by a transparent score (`_relevance`): terms matching the
    claim's subcategory (`focus`) first, then specific line-item phrases and
    dollar-adjacent hits, ties broken by filing date then term. Still pure
    keyword search -- no embeddings, no LLM ranker -- so the labeler sees the
    most plausible evidence first without the tool ever deciding what counts.
    """
    scored: list[tuple[int, date, str, Candidate]] = []
    for row in filings_df.itertuples(index=False):
        fpath = _resolve_filing_path(sec_dir, row.localPath)
        if not fpath.exists():
            continue
        text = _html_to_text(fpath.read_bytes())
        for term in terms:
            hits = search_filing(text, term, context=context)
            if not hits:
                continue
            snippet = hits[0].snippet
            if _is_noise(snippet):
                continue
            cand = Candidate(
                accession_no=str(row.accessionNumber),
                form=str(row.form),
                filing_date=row.filingDate,
                local_path=str(row.localPath),
                term=term,
                snippet=snippet,
                report_date=getattr(row, "reportDate", None),
            )
            scored.append((_relevance(term, snippet, focus), row.filingDate, term, cand))
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    return [cand for _, _, _, cand in scored]


# ── Gold-file I/O ──────────────────────────────────────────────────────────

def load_gold_claim_ids(gold_path: Path) -> set[str]:
    """claim_ids already present in the gold JSONL (lenient: skips bad lines)."""
    if not gold_path.exists():
        return set()
    ids: set[str] = set()
    for line in gold_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ids.add(json.loads(line).get("claim_id", ""))
        except json.JSONDecodeError:
            continue
    return ids - {""}


def append_gold_label(gold_path: Path, label: GoldLabel) -> None:
    """Append one validated GoldLabel as a JSON line (never rewrites the file)."""
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    with gold_path.open("a", encoding="utf-8") as fh:
        fh.write(label.model_dump_json() + "\n")


# ── Rendering ──────────────────────────────────────────────────────────────

def _render_claim(claim: Claim, until_date: date | None) -> str:
    if claim.horizon_end_date is not None:
        window = f"reporting periods through {claim.horizon_end_date} (the claim horizon)"
    elif until_date is not None:
        window = f"filed on/before {until_date}"
    else:
        window = "all subsequent filings"
    return (
        f"=== CLAIM {claim.claim_id} ===\n"
        f"  {claim.ticker} ({claim.company}) -- call {claim.call_date}\n"
        f"  type:    {claim.claim_type}\n"
        f"  quote:   {claim.verbatim_quote}\n"
        f"  summary: {claim.summary}\n"
        f"  horizon: {claim.horizon_raw or '(none stated)'}  ->  "
        f"{claim.horizon_period or '(unresolved)'} (ends {claim.horizon_end_date or 'open'})\n"
        f"  Grading filings filed after {claim.call_date}, {window}."
    )


def _render_candidate(index: int, c: Candidate) -> str:
    reports = f", reports {c.report_date}" if c.report_date else ""
    return (f"  [{index}] {c.form} filed {c.filing_date}{reports}  acc {c.accession_no}"
            f"  (matched: {c.term})\n      ...{c.snippet}...")


# ── Interactive session ────────────────────────────────────────────────────

def _prompt_verdict(say, ask, *, has_evidence: bool) -> str | None:
    say("\nVerdict (see docs/labeling_rubric.md):")
    for i, v in enumerate(_VERDICTS, 1):
        say(f"  {i}  {v}")
    while True:
        raw = ask("verdict> ").strip()
        if raw == "quit":
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(_VERDICTS):
            verdict = _VERDICTS[int(raw) - 1]
            if verdict in _DECISIVE and not has_evidence:
                say(f"  {verdict!r} needs at least one evidence passage; you "
                    f"selected none. Choose 4 (not_yet_resolvable) or 'quit' "
                    f"and re-run to pick evidence.")
                continue
            return verdict
        say(f"  (enter 1..{len(_VERDICTS)}, or 'quit')")


def _prompt_confidence(say, ask) -> str | None:
    while True:
        raw = ask("confidence [h/m/l]> ").strip().lower()
        if raw == "quit":
            return None
        if raw in _CONFIDENCE:
            return _CONFIDENCE[raw]
        say("  (enter h, m, or l)")


def run_session(
    claim: Claim,
    filings_df: pd.DataFrame,
    sec_dir: Path,
    gold_path: Path,
    labeler: str,
    until_date: date | None,
    *,
    context: int = 240,
    limit: int = _DISPLAY_LIMIT,
    ask=input,
    say=print,
) -> GoldLabel | None:
    """Interactively grade one claim and append a GoldLabel. Returns the label,
    or None if the labeler aborted. ``ask``/``say`` are injectable for testing.
    """
    say(_render_claim(claim, until_date))

    focus = _claim_focus(claim)
    candidates = sweep(
        filings_df, sec_dir,
        terms=list(_SWEEP_TERMS.get(claim.claim_type, [])), context=context,
        focus=focus,
    )
    shown = 0

    def _show(upto: int) -> None:
        nonlocal shown
        for i in range(shown, min(upto, len(candidates))):
            say(_render_candidate(i + 1, candidates[i]))
        shown = max(shown, min(upto, len(candidates)))

    say(f"\n{len(candidates)} candidate passage(s) from the keyword sweep:")
    if not candidates:
        say("  (none -- use 'more <term>' to search, or 'none' for no evidence)")
    _show(limit)
    if len(candidates) > shown:
        say(f"  ... +{len(candidates) - shown} more (type 'all' to show)")
    say("\nCommands:  <numbers> e.g. 1,3 = pick evidence | more <term> = search "
        "another keyword | all = show all | none = no evidence | quit = abort")

    selected: list[int] = []
    while True:
        raw = ask("evidence> ").strip()
        if raw == "quit":
            say("Aborted; nothing written.")
            return None
        if raw == "all":
            _show(len(candidates))
            continue
        if raw == "none":
            selected = []
            break
        if raw.startswith("more "):
            term = raw[5:].strip()
            if not term:
                say("  (usage: more <keyword>)")
                continue
            existing = {(c.accession_no, c.snippet) for c in candidates}
            found = sweep(filings_df, sec_dir, terms=[term], context=context, focus=focus)
            added = [c for c in found if (c.accession_no, c.snippet) not in existing]
            candidates.extend(added)
            say(f"  +{len(added)} new hit(s) for {term!r}.")
            _show(len(candidates))
            continue
        try:
            nums = [int(x) for x in raw.replace(",", " ").split()]
        except ValueError:
            say("  (enter candidate numbers like '1,3', or a command)")
            continue
        if nums and all(1 <= n <= len(candidates) for n in nums):
            selected = sorted(set(nums))
            break
        say(f"  (numbers must be 1..{len(candidates)})")

    evidence = [candidates[n - 1].to_evidence() for n in selected]
    if evidence:
        say(f"Selected {len(evidence)} evidence passage(s).")

    verdict = _prompt_verdict(say, ask, has_evidence=bool(evidence))
    if verdict is None:
        say("Aborted; nothing written.")
        return None
    confidence = _prompt_confidence(say, ask)
    if confidence is None:
        say("Aborted; nothing written.")
        return None
    notes = ask("notes (optional)> ").strip()

    try:
        label = GoldLabel(
            claim_id=claim.claim_id,
            ticker=claim.ticker,
            labeler=labeler,
            labeled_at=datetime.now(),
            expected_evidence=evidence,
            verdict=verdict,
            confidence=confidence,
            labeler_notes=notes,
        )
    except Exception as exc:                              # schema rejected it
        say(f"Could not build a valid label: {exc}\nNothing written.")
        return None

    append_gold_label(gold_path, label)
    say(f"\nWrote 1 label for {claim.claim_id} -> {gold_path}")
    say(label.model_dump_json())
    return label


# ── CLI ────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="verifier.label",
        description="Interactive agent-free gold-set labeling helper.",
    )
    p.add_argument("--claims", required=True, type=Path,
                   help="Path to the claims CSV (e.g. data/claims/pilot_claims.csv).")
    p.add_argument("--claim-id", required=True, help="The claim_id to label.")
    p.add_argument("--labeler", required=True, help="Your name (recorded on the label).")
    p.add_argument("--gold", type=Path, default=None,
                   help="Gold JSONL to append to (default: data/gold/pilot_<ticker>.jsonl).")
    p.add_argument("--forms", default=None,
                   help="Comma-separated forms to consider (default: 10-K,10-Q,8-K).")
    p.add_argument("--from", dest="from_date", default=None,
                   help="Only filings on/after this date (YYYY-MM-DD).")
    p.add_argument("--until", dest="until_date", default=None,
                   help="Only filings on/before this date (overrides the auto window).")
    p.add_argument("--context", type=int, default=240,
                   help="Characters of context around each match (default 240).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    claim = load_claim(args.claims, args.claim_id)
    gold_path = (args.gold if args.gold
                 else GOLD_DIR / f"pilot_{claim.ticker.lower()}.jsonl")

    if claim.claim_id in load_gold_claim_ids(gold_path):
        answer = input(
            f"{claim.claim_id} is already labeled in {gold_path}. "
            f"Add another label? [y/N] "
        ).strip().lower()
        if answer != "y":
            print("Skipped.")
            return 0

    forms = (tuple(f.strip() for f in args.forms.split(",")) if args.forms
             else _FORMS)
    from_date = date.fromisoformat(args.from_date) if args.from_date else None
    if args.until_date:
        until_date = date.fromisoformat(args.until_date)      # explicit override (filing date)
    elif claim.horizon_end_date is None:
        until_date = grading_window(claim)                    # unresolved horizon: filing-date fallback
    else:
        until_date = None                                     # resolved: reportDate bound does the work

    index_df = _load_filing_index(claim.ticker)
    filings = candidate_filings(
        claim, index_df, forms=forms, from_date=from_date, until_date=until_date,
        horizon_end=claim.horizon_end_date,
    )
    if filings.empty:
        print("No candidate filings in the grading window. "
              "Widen it with --until YYYY-MM-DD.", file=sys.stderr)
        return 1

    sec_dir = PULLED_DATA_ROOT / claim.ticker / "SEC"
    run_session(claim, filings, sec_dir, gold_path, args.labeler, until_date,
                context=args.context)
    return 0


if __name__ == "__main__":
    sys.exit(main())
