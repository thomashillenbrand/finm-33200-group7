"""Prompt strings for the two LLM stages, versioned for reproducibility."""

from __future__ import annotations

from datetime import date

from autochecker.compustat import FIELD_CODEBOOK

PROMPT_VERSION = "autochecker-v1"

# ---------------------------------------------------------------------------
# Stage 1 — Compustat-relevance screen
# ---------------------------------------------------------------------------

SCREEN_SYSTEM = f"""\
You screen forward-looking management claims for whether they can be checked
against the speaker's company in Compustat quarterly fundamentals.

Compustat has these fields (code: meaning):
{FIELD_CODEBOOK}

A claim is Compustat-relevant ONLY if it asserts something — a direction or a
magnitude — about a figure represented above. Examples:
  - "we expect organic revenue growth of approximately 5%" -> RELEVANT (saleq/revtq)
  - "we expect ~$1B in early convert paydowns in Q4" -> RELEVANT (dltr_q)
  - "we expect a 1- to 1.5-week delay in the Shanghai ramp" -> NOT RELEVANT (operational timing)
  - "we will provide more detail in the 10-K" -> NOT RELEVANT (meta-statement)
  - "we expect to complete supply chain localization in 2020" -> NOT RELEVANT (qualitative project status)

Output strictly the structured object. If is_compustat_relevant is false,
candidate_fields must be empty and assertion_kind must be "none". If true,
pick the smallest set of fields the claim directly speaks to (usually 1–3).
"""

def build_screen_user_prompt(
    *,
    ticker: str,
    company: str,
    call_date: date,
    claim_type: str,
    verbatim_quote: str,
    summary: str,
) -> str:
    return f"""\
Company: {company} ({ticker})
Call date: {call_date.isoformat()}
Claim type (from upstream extractor): {claim_type}

Verbatim quote:
\"\"\"{verbatim_quote}\"\"\"

Paraphrase:
{summary}

Decide whether this claim is Compustat-relevant per the rules above.
"""

# ---------------------------------------------------------------------------
# Stage 2 — verification (two prompts: evidence-mode vs verdict-mode)
# ---------------------------------------------------------------------------

_FIELD_REMINDER = f"""\
Compustat field codebook (you will be shown a table whose columns use these codes):
{FIELD_CODEBOOK}

All currency values are in millions of US dollars unless the label says otherwise.
YTD fields ending in 'y' in the raw parquet have already been converted to
per-quarter deltas (columns ending in '_q'); each row's value is THAT
quarter's activity, not a year-to-date running total.
"""

EVIDENCE_SYSTEM = f"""\
You are a research-assistant that surfaces Compustat evidence for a claim.
DO NOT assign a verdict, judgment, or label. The forbidden words/phrases
include: 'verified', 'confirmed', 'failed', 'missed', 'beat', 'exceeded',
'fell short', 'above guidance', 'below guidance', 'on track', 'consistent
with the claim', 'contradicted'. Any wording that compares the realised
number to the claim's number with a judgmental verb is a verdict — do not
write it. A human labeler will assign the verdict from your numbers alone;
biasing them defeats the evaluation.

Your job:
  1. Pick the cells from the panel most relevant to the claim and return
     them as citations (datadate + field code + value).
  2. Write a short, neutral 'comparison_notes' paragraph stating the cited
     values, in the SAME UNITS the claim uses. If the claim gives a
     percentage and the table gives dollars, compute the percentage change
     against the appropriate base period (e.g. prior year same quarter, or
     full prior year) and report the resulting realised number — WITHOUT
     saying whether it matches, exceeds, or falls short of the claim.

{_FIELD_REMINDER}
"""

VERDICT_SYSTEM = f"""\
You verify a forward-looking management claim against Compustat fundamentals.

Procedure:
  1. From the post-call Compustat table, pick the cells most relevant to the
     claim and return them as citations (datadate + field code + value).
  2. Compare the cited values to the claim. If the claim states a magnitude,
     compute the realised value in the claim's units (often a percentage
     change vs the same quarter of the prior year, or a full-year sum vs the
     stated horizon). If the claim states only a direction, compare signs.
  3. Choose ONE verdict label:
       - "verified": the realised values match the claim within a reasonable
         tolerance (~10% relative for magnitudes; correct sign for directions).
       - "partially_verified": claim is qualitatively in the right direction
         but the magnitude is off by more than the tolerance; or the claim
         had multiple parts and only some hold.
       - "contradicted": realised values go the other way, or the magnitude
         is wrong by a clear margin (more than ~25% relative).
       - "not_yet_resolvable": the horizon has not closed yet, or the rows
         needed are missing from the panel.
       - "insufficient_data": the rows are present but the field needed to
         judge the claim is missing or null.

Be concrete in 'reasoning': state the realised number, the claimed number,
and the comparison.

{_FIELD_REMINDER}
"""

def build_stage2_user_prompt(
    *,
    ticker: str,
    company: str,
    call_date: date,
    horizon_end_date: date | None,
    claim_type: str,
    verbatim_quote: str,
    summary: str,
    assertion_kind: str,
    candidate_fields: list[str],
    table_csv: str,
) -> str:
    horizon_line = (
        f"Claim horizon ends: {horizon_end_date.isoformat()}"
        if horizon_end_date is not None
        else "Claim horizon: (none provided)"
    )
    fields_line = (
        ", ".join(candidate_fields) if candidate_fields else "(none — pick your own from the codebook)"
    )
    return f"""\
Company: {company} ({ticker})
Call date: {call_date.isoformat()}
{horizon_line}
Claim type (from upstream extractor): {claim_type}
Stage-1 assertion kind: {assertion_kind}
Stage-1 candidate Compustat fields: {fields_line}

Verbatim quote:
\"\"\"{verbatim_quote}\"\"\"

Paraphrase:
{summary}

Compustat quarterly panel (two sections: a pre-call BASE for YoY/level
comparisons, and the POST-CALL window the claim is graded against):

{table_csv}
"""
