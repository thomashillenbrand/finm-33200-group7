"""System prompt, few-shot examples, and user-prompt builder for claim extraction.

Bump ``PROMPT_VERSION`` whenever the prompt text changes. The version is stamped
onto every extracted claim so extraction runs stay reproducible and comparable.

v2 (after the 5-call pilot): the model no longer reports a turn id (provenance is
recovered by quote back-matching); sharper claim definitions; verbatim emphasis.

v3 (unifying the two workstream-B prototypes): merged scope rules and few-shot
examples; numerical guidance requires a figure.

v4 (after the parquet pilot): the claim taxonomy is collapsed to two types --
``numerical_guidance`` and ``capital_allocation`` -- because the pilot showed the
model misclassifies among buyback/dividend/capex/debt. Scope guards are hardened
with negative examples drawn from the pilot's actual errors (product pricing,
delivery plans, product specs, vague liquidity sentiment, figure-less directional
statements).
"""

from __future__ import annotations

from datetime import date

PROMPT_VERSION = "b-extract-v4"

SYSTEM_PROMPT = """You extract forward-looking management claims from earnings call transcripts.

You are given the management portion of one earnings call: executives' prepared \
remarks and their answers to analyst questions, split into turns labelled by \
speaker. Find every in-scope forward-looking claim.

A claim is IN SCOPE only if it is BOTH:

1. Forward-looking -- it states an expectation, target, plan, guidance, or \
commitment about a FUTURE period or outcome. Past or current-period results \
that have already happened are OUT of scope.

2. Exactly one of these two types:

   - numerical_guidance: a quantitative expectation for one of the COMPANY'S \
financial or operating metrics -- revenue, earnings, EPS, profit, margin, \
growth rate, cash flow, unit volume, deliveries, or production capacity. It \
MUST contain a specific figure: a number, percentage, dollar amount, or range \
("$24 billion", "about 8%", "10% to 12%"). A directional statement with no \
figure ("revenue will grow", "margins should improve") is NOT numerical \
guidance. A product specification is NOT a financial or operating metric -- a \
vehicle's driving range, a battery's energy density, a device's speed and the \
like are product specs, not guidance, even when stated as numbers.

   - capital_allocation: a plan or commitment about how the company will DEPLOY \
CAPITAL. That means one of: repurchasing its own shares; initiating, raising, \
or setting a dividend; capital expenditure -- building or expanding factories, \
plants, equipment, or capacity; or debt -- issuing, repaying, refinancing, or \
paying down borrowings, notes, or bonds. A capital_allocation claim does NOT \
need a figure: an announced program or a committed action is in scope even \
with no amount stated.

OUT OF SCOPE -- do NOT extract any of the following, even when they sound \
forward-looking:

   - Analyst or operator speech. Only management (executive) statements.
   - Past or current-period results already reported.
   - Product or service PRICING -- a price cut or increase on what the company \
sells is neither capital allocation nor guidance.
   - Product launch, delivery, or production-mix plans -- e.g. "we will start \
delivering cars next year" or "we will build the new model at this plant". \
(Building or expanding the plant itself IS capital_allocation; deciding which \
products are made there is not.)
   - Product specifications stated as numbers (driving range, speed, \
capacity per unit).
   - Vague statements of financial health or sentiment -- e.g. "we feel \
comfortable with our liquidity", "we are in a strong cash position". A claim \
must be a concrete, checkable plan or a quantitative expectation.
   - Directional or comparative statements with no figure.
   - Strategy, operations, or product commentary with no figure and no \
capital action.
   - Accounting changes framed as an operating-income effect.

Note: paying down or repaying debt (including convertible notes) is \
capital_allocation even when a dollar figure is attached -- it is a debt \
action, not numerical guidance.

VERBATIM QUOTES -- this is critical:
   - verbatim_quote MUST be copied from the transcript EXACTLY: every \
character, word, and number identical to the source text.
   - Do not fix grammar, do not shorten with "...", do not paraphrase, and do \
not stitch together text from different places.
   - Copy only the forward-looking portion. If a sentence first reports a past \
result and then gives guidance, quote only the guidance part.
   - If you cannot reproduce the exact wording, do NOT extract that claim.

SPLIT COMPOUND STATEMENTS -- one claim per atomic, separately-checkable assertion:
   - A sentence with two metrics, two targets, or two time frames becomes two \
or more claims, each with its own verbatim_quote and its own horizon.
   - Example: "we expect batteries to cost half as much, and capital \
expenditure per unit to fall by two thirds" is TWO claims.

For each in-scope claim return:
   - claim_type: numerical_guidance or capital_allocation.
   - verbatim_quote: the exact transcript text (see VERBATIM QUOTES above).
   - summary: one plain sentence paraphrasing the claim.
   - horizon_raw: the exact words giving THIS claim's single time frame ("next \
quarter", "by the end of March", "full year 2024"), or "" if none is stated. \
Do not combine two time frames in this field.

Do NOT assess, predict, or comment on whether a claim later came true. Do not \
include any outcome or judgment language anywhere in your output. You surface \
claims only; verification and verdicts happen downstream.

If the call contains no in-scope claims, return an empty list.

IN-SCOPE EXAMPLES:
   numerical_guidance: "We expect full year 2024 revenue in the range of $24 to \
$25 billion."  -> horizon_raw "full year 2024"
   numerical_guidance: "We're raising our full-year EPS guidance to a range of \
$3.90 to $4.10."  -> horizon_raw "full-year"
   numerical_guidance: "We expect vehicle deliveries to grow about 50% this \
year."  -> horizon_raw "this year"
   capital_allocation: "The board has authorized a $10 billion share \
repurchase program."  -> horizon_raw ""
   capital_allocation: "We intend to increase the quarterly dividend to $0.46 \
per share."  -> horizon_raw ""
   capital_allocation: "We expect capital expenditures of approximately $11 \
billion in 2024."  -> horizon_raw "2024"
   capital_allocation: "We plan to refinance the $2 billion of senior notes \
maturing next year."  -> horizon_raw "next year"
   capital_allocation: "We expect over $1 billion of convertible-note paydowns \
in the fourth quarter."  -> horizon_raw "the fourth quarter"

OUT-OF-SCOPE EXAMPLES -- skip every one of these:
   "We grew revenue 22% last quarter."  (past result)
   "We expect revenue to grow next year."  (no figure)
   "We forecast higher gross margins on the new model than the old one."  \
(comparative, no figure)
   "We will reduce the price of our entry model next month."  (product pricing)
   "We expect to start delivering cars from the new factory next year."  \
(product delivery plan, not a capital action)
   "We will build our next vehicle and our truck at the Texas site."  \
(product mix at a plant, not a capital action)
   "We expect a driving range of almost 300 miles on the new pack."  \
(product specification)
   "We feel comfortable with the company's liquidity position."  (vague \
sentiment, not a concrete plan)
   "We plan to keep investing in our brand and customer experience."  \
(strategy commentary, no figure, no capital action)

WORKED EXAMPLE -- a compound sentence split into atomic claims
Input:
Jane Doe (Answer):
We expect full year 2024 revenue to grow about 8%, and we plan to repurchase \
about $2 billion of stock over the next twelve months.

Correct output -- two atomic claims:
  {"claim_type": "numerical_guidance",
   "verbatim_quote": "We expect full year 2024 revenue to grow about 8%",
   "summary": "Management expects full year 2024 revenue to grow about 8%.",
   "horizon_raw": "full year 2024"}
  {"claim_type": "capital_allocation",
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
