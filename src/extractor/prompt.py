"""System prompt, few-shot example, and user-prompt builder for claim extraction.

Bump ``PROMPT_VERSION`` whenever the prompt text changes. The version is stamped
onto every extracted claim so extraction runs stay reproducible and comparable.

v2 changes (after the 5-call pilot): the model no longer reports a turn id
(provenance is now recovered by quote back-matching); sharper "debt" definition;
stronger compound-claim splitting; harder verbatim-quote emphasis.
"""

from __future__ import annotations

from datetime import date

PROMPT_VERSION = "b-extract-v2"

SYSTEM_PROMPT = """You extract forward-looking management claims from earnings call transcripts.

You are given the management portion of one earnings call: executives' prepared \
remarks and their answers to analyst questions, split into turns labelled by \
speaker. Find every in-scope forward-looking claim.

A claim is IN SCOPE only if it is BOTH:

1. Forward-looking -- it states an expectation, target, plan, guidance, or \
commitment about a FUTURE period or outcome. Statements about past or \
current-period results are OUT of scope.

2. Exactly one of these five types:
   - numerical_guidance: a quantitative expectation for a financial or operating \
metric -- revenue, earnings, EPS, profit or profitability, margin, growth rate, \
cash flow, unit volume, deliveries, production capacity, etc.
   - buyback: a plan or commitment to repurchase the company's own shares.
   - dividend: a plan or commitment about dividends (initiation, increase, level).
   - capex: a plan or expectation for capital expenditure or capital investment \
-- building factories, equipment, or capacity.
   - debt: a plan or expectation about DEBT INSTRUMENTS specifically -- \
borrowing, issuing notes or bonds, drawing down or repaying loans or credit \
lines, refinancing, or changing leverage. A statement is NOT a debt claim just \
because it mentions money or cash. Statements about profitability, earnings, or \
being "profitable" are numerical_guidance, never debt.

OUT OF SCOPE -- do not extract: analyst statements; historical or \
current-period results; vague aspirations with no metric or concrete action \
("we feel great about the future"); product or strategy commentary with no \
quantitative or capital-allocation content.

VERBATIM QUOTES -- this is critical:
  - verbatim_quote MUST be copied from the transcript EXACTLY: every character, \
word, and number identical to the source text.
  - Do not fix grammar, do not shorten with "...", do not paraphrase, and do \
not stitch together text from different places.
  - If you cannot reproduce the exact wording, do NOT extract that claim.

SPLIT COMPOUND STATEMENTS -- one claim per atomic, separately-checkable assertion:
  - A sentence with two metrics, two targets, or two time frames becomes two \
or more claims, each with its own verbatim_quote and its own horizon.
  - Example: "2,500 vehicles per week by the end of March and 5,000 by the end \
of Q2" is TWO claims -- one for the 2,500/March target, one for the 5,000/Q2 \
target.

For each in-scope claim return:
  - claim_type: one of the five types above.
  - verbatim_quote: the exact transcript text (see VERBATIM QUOTES above).
  - summary: one plain sentence paraphrasing the claim.
  - horizon_raw: the exact words giving THIS claim's single time frame ("next \
quarter", "by the end of March", "full year 2024"), or "" if none is stated. \
Do not combine two time frames in this field.

Do NOT assess, predict, or comment on whether a claim later came true. Do not \
include any outcome or judgment language anywhere in your output. You surface \
claims only; verification and verdicts happen downstream.

If the call contains no in-scope claims, return an empty list.

EXAMPLE
Input:
Jane Doe (Answer):
We expect full year 2024 revenue growth in the high single digits, and we plan \
to repurchase about $2 billion of stock over the next twelve months.

Correct output -- two atomic claims:
  {"claim_type": "numerical_guidance",
   "verbatim_quote": "We expect full year 2024 revenue growth in the high single digits",
   "summary": "Management expects full year 2024 revenue to grow in the high single digits.",
   "horizon_raw": "full year 2024"}
  {"claim_type": "buyback",
   "verbatim_quote": "we plan to repurchase about $2 billion of stock over the next twelve months",
   "summary": "Management plans to repurchase about $2 billion of stock within twelve months.",
   "horizon_raw": "over the next twelve months"}"""


def build_user_prompt(
    company: str, fiscal_period: str, call_date: date, call_input: str
) -> str:
    """Assemble the user message for one call's extraction request."""
    return (
        f"Company: {company}\n"
        f"Earnings call: {fiscal_period} (held {call_date.isoformat()})\n\n"
        f"Management transcript follows. Extract all in-scope forward-looking "
        f"claims.\n\n"
        f"{call_input}"
    )
