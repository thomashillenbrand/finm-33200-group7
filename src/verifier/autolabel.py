"""Non-interactive GPT-5.5 gold-set auto-labeler (`python -m verifier.autolabel`).

A sibling of ``verifier.label``: same deterministic keyword sweep and same
``GoldLabel`` output, but an LLM (GPT-5.5 + the rubric) selects evidence and
assigns the verdict instead of a human.

INDEPENDENCE (load-bearing — do not break). Like ``verifier.label`` this module
must NOT import ``verifier.agent`` / ``verify``, ``faiss``,
``langchain...OpenAIEmbeddings``, or ``verifier.tools``, and must NOT read the
``index/`` artifacts. Evidence comes only from the deterministic keyword sweep,
so recall@k stays an independent comparison against the agent's FAISS retrieval.
The rubric is loaded ONLY here, never into the agent.

See docs/autolabel-gold-eval-design.md.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from extractor.extract import _has_number, _supports_temperature  # canonical figure/temperature logic
from schemas import Claim
from verifier.gold import Confidence, GoldLabel, VerdictLabel
from verifier.label import (
    PULLED_DATA_ROOT,
    _SWEEP_TERMS,
    _claim_focus,
    _load_filing_index,
    append_gold_label,
    candidate_filings,
    grading_window,
    load_claim,
    load_gold_claim_ids,
    sweep,
)

GOLD_DIR = Path("data/gold/auto")
RUBRIC_PATH = Path("docs/labeling_rubric.md")
_DECISIVE = {"verified", "partially_verified", "contradicted"}
_MAX_CANDIDATES = 25


class AutoLabelDecision(BaseModel):
    """One LLM grading decision over the numbered sweep candidates."""

    selected_indices: list[int] = Field(
        default_factory=list,
        description="1-based indices of the candidate passages that are evidence "
        "for the verdict. Empty only when the verdict is not_yet_resolvable.",
    )
    verdict: VerdictLabel
    confidence: Confidence
    notes: str = ""


def claim_has_figure(quote: str) -> bool:
    """True if the quote states a real financial figure (reuses the extractor's
    canonical test, which ignores years / form names / product designations)."""
    return _has_number(quote)


def select_residual_subset(
    df: pd.DataFrame, *, per_ticker_cap: int = 8, seed: int = 0
) -> list[str]:
    """Frozen stratified subset of the verifier's production residual.

    The residual = ``capital_allocation`` claims whose quote carries no figure
    (the quantified ones are settled upstream by the Compustat autochecker).
    Stratified by ticker, capped per ticker, deterministic for a given seed.
    """
    ca = df[df["claim_type"] == "capital_allocation"]
    residual = ca[~ca["verbatim_quote"].map(claim_has_figure)]
    rng = random.Random(seed)
    picked: list[str] = []
    for _, grp in residual.groupby("ticker"):
        ids = sorted(grp["claim_id"].tolist())
        rng.shuffle(ids)
        picked.extend(ids[:per_ticker_cap])
    return sorted(picked)


def _decision_to_evidence(candidates, indices):
    """Map 1-based candidate indices to GoldEvidence, silently dropping any
    index outside ``1..len(candidates)``."""
    ev = []
    for n in indices:
        if 1 <= n <= len(candidates):
            ev.append(candidates[n - 1].to_evidence())
    return ev


def _build_label(claim, candidates, decider, rubric_text, *, labeler):
    """One grading decision → a validated GoldLabel.

    Asks the LLM once. If it returns a decisive verdict with no usable evidence,
    re-prompts once with an explicit nudge; if it still returns none, the verdict
    is forced to ``not_yet_resolvable`` (the only verdict valid with no
    evidence — see GoldLabel's invariant), so the row stays schema-valid.
    """
    messages = build_label_messages(claim, candidates, rubric_text)
    decision = decider.invoke(messages)
    evidence = _decision_to_evidence(candidates, decision.selected_indices)
    if decision.verdict in _DECISIVE and not evidence:
        nudge = messages + [{
            "role": "user",
            "content": "You returned a decisive verdict but selected no evidence "
            "passages. Either select the supporting passage index/indices, or "
            "change the verdict to not_yet_resolvable.",
        }]
        decision = decider.invoke(nudge)
        evidence = _decision_to_evidence(candidates, decision.selected_indices)
        if decision.verdict in _DECISIVE and not evidence:
            decision = decision.model_copy(update={"verdict": "not_yet_resolvable"})
    return GoldLabel(
        claim_id=claim.claim_id,
        ticker=claim.ticker,
        labeler=labeler,
        labeled_at=datetime.now(),
        expected_evidence=evidence,
        verdict=decision.verdict,
        confidence=decision.confidence,
        labeler_notes=decision.notes,
    )


_SYSTEM_PROMPT = (
    "You assign a gold-standard verdict to a forward-looking management claim by "
    "reading ONLY the candidate SEC-filing passages provided. Follow the rubric "
    "exactly. Choose the passage indices that are evidence for your verdict. A "
    "decisive verdict (verified / partially_verified / contradicted) MUST cite at "
    "least one passage; use not_yet_resolvable when the passages do not settle it. "
    "Do not use any knowledge beyond the passages shown. "
    "Evidenced non-occurrence is a contradiction, not not_yet_resolvable: if the "
    "claim's horizon has elapsed and a passage shows the financial-statement line "
    "where the promised action would necessarily appear (e.g. the cash-flow "
    "repurchase / dividend / capex line) is zero, absent, or moves the opposite "
    "way, cite that passage and mark contradicted. Reserve not_yet_resolvable for "
    "claims whose horizon has not elapsed, or that have no such obligatory "
    "disclosure point where silence would be meaningful."
)


def load_rubric(path=RUBRIC_PATH) -> str:
    """Read the verdict rubric text (labeler-only — never given to the agent)."""
    return Path(path).read_text(encoding="utf-8")


def _format_candidates(candidates) -> str:
    return "\n".join(
        f"[{i}] {c.form} filed {c.filing_date} (reports {c.report_date}) "
        f"acc {c.accession_no} (matched: {c.term})\n    {c.snippet}"
        for i, c in enumerate(candidates, 1)
    )


def build_label_messages(claim, candidates, rubric_text):
    """Build the (system, user) messages for one grading decision."""
    user = (
        f"RUBRIC:\n{rubric_text}\n\n"
        f"CLAIM\n"
        f"  ticker:  {claim.ticker} ({claim.company})\n"
        f"  call:    {claim.call_date}\n"
        f"  quote:   {claim.verbatim_quote}\n"
        f"  summary: {claim.summary}\n"
        f"  horizon: {claim.horizon_raw or '(none)'} -> "
        f"{claim.horizon_period or '(unresolved)'} (ends "
        f"{claim.horizon_end_date or 'open'})\n\n"
        f"CANDIDATE PASSAGES (1-based; cite by index):\n"
        f"{_format_candidates(candidates) or '  (none found)'}\n\n"
        f"Return selected_indices, verdict, confidence, notes."
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _resolve_labeler_model(model_name=None) -> str:
    model = model_name or os.environ.get("GOLD_LABELER_MODEL")
    if not model:
        raise RuntimeError(
            "GOLD_LABELER_MODEL is not set. Copy .env.example to .env or export "
            "GOLD_LABELER_MODEL (e.g. openai:gpt-5.5) before running."
        )
    return model


def build_decider(model_name=None):
    """LLM bound to AutoLabelDecision. gpt-5 / o-series reject a custom
    temperature, so it is only set where supported (reuses the extractor's rule)."""
    from langchain.chat_models import init_chat_model

    model_name = _resolve_labeler_model(model_name)
    kwargs: dict = {"max_retries": 3}
    if _supports_temperature(model_name):
        kwargs["temperature"] = 0
    return init_chat_model(model_name, **kwargs).with_structured_output(AutoLabelDecision)


def _label_one(claim, decider, rubric_text, *, labeler, max_candidates):
    """Run the sweep for one claim and produce its GoldLabel."""
    focus = _claim_focus(claim)
    until = None if claim.horizon_end_date else grading_window(claim)
    index_df = _load_filing_index(claim.ticker)
    filings = candidate_filings(
        claim, index_df, until_date=until, horizon_end=claim.horizon_end_date
    )
    sec_dir = PULLED_DATA_ROOT / claim.ticker / "SEC"
    candidates = sweep(
        filings, sec_dir,
        terms=list(_SWEEP_TERMS.get(claim.claim_type, [])), focus=focus,
    )[:max_candidates]
    return _build_label(claim, candidates, decider, rubric_text, labeler=labeler)


def _cli_select(args) -> int:
    df = pd.read_csv(args.claims).fillna("")
    ids = select_residual_subset(df, per_ticker_cap=args.per_ticker, seed=args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(ids) + "\n", encoding="utf-8")
    print(f"Wrote {len(ids)} claim_ids -> {args.out}")
    return 0


def _cli_label(args) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    labeler = _resolve_labeler_model().split(":", 1)[-1]   # e.g. "gpt-5.5"
    decider = build_decider()
    rubric_text = load_rubric()
    claim_ids = [c for c in args.claim_ids.read_text().split() if c]
    if args.limit:
        claim_ids = claim_ids[: args.limit]
    args.gold_dir.mkdir(parents=True, exist_ok=True)
    for cid in claim_ids:
        claim = load_claim(args.claims, cid)
        gold_path = args.gold_dir / f"auto_{claim.ticker.lower()}.jsonl"
        if cid in load_gold_claim_ids(gold_path) and not args.relabel:
            print(f"skip (already labeled): {cid}")
            continue
        label = _label_one(
            claim, decider, rubric_text,
            labeler=labeler, max_candidates=args.max_candidates,
        )
        append_gold_label(gold_path, label)
        print(f"{cid}  ->  {label.verdict} ({len(label.expected_evidence)} ev)  {gold_path}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="verifier.autolabel",
                                description="GPT-5.5 gold-set auto-labeler.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("select", help="Pick + freeze the residual subset (no LLM).")
    s.add_argument("--claims", required=True, type=Path)
    s.add_argument("--out", required=True, type=Path)
    s.add_argument("--per-ticker", type=int, default=8)
    s.add_argument("--seed", type=int, default=0)
    s.set_defaults(func=_cli_select)

    label_p = sub.add_parser("label", help="Auto-label the pinned subset with GPT-5.5.")
    label_p.add_argument("--claims", required=True, type=Path)
    label_p.add_argument("--claim-ids", required=True, type=Path)
    label_p.add_argument("--gold-dir", type=Path, default=GOLD_DIR)
    label_p.add_argument("--limit", type=int, default=None)
    label_p.add_argument("--max-candidates", type=int, default=_MAX_CANDIDATES)
    label_p.add_argument("--relabel", action="store_true",
                         help="Add another label even if the claim_id is already present.")
    label_p.set_defaults(func=_cli_label)
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
