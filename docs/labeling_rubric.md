# Gold-Set Labeling Rubric

**Who this is for:** Human labelers assigning verdicts to extracted claims in `data/gold/`.

**Critical rule:** Do NOT read the verification agent's output before labeling. Read the SEC filings
directly and assign your verdict independently. The entire evaluation depends on this independence —
if you use the agent's output to guide your labels, the scoring is circular and meaningless.

---

## The Four Verdicts

### `verified`
The filing evidence **clearly confirms** the claim came true — the figure, action, or outcome is
explicitly stated in a post-call 10-Q, 10-K, or 8-K within the claim's horizon window.

Use when:
- The announced figure matches the actual figure **within ~10%** (accounting for rounding/revisions)
- The announced action was taken (buyback completed, factory opened, dividend increased)
- No material contradiction exists elsewhere in the filing

### `partially_verified`
The filing evidence **partially supports** the claim but something meaningful is missing or off.

Use when:
- A numeric claim is directionally right but the magnitude is materially off (>10% gap)
- A buyback/capex was announced for $X but only $Y was executed (Y < ~90% of X) within the horizon
- An action was taken but later than promised (horizon elapsed with partial completion)
- Multiple parts of a compound claim — only some came true

### `contradicted`
The filing evidence **explicitly contradicts** the claim — including **evidenced
non-occurrence**: a place where the promised outcome *would necessarily* be reported shows it did not happen.

Use when:
- The filing reports a figure that is opposite in direction (claimed growth → actual decline)
- An announced action was reversed (buyback paused/cancelled, dividend cut)
- The company directly walked back the guidance in a subsequent filing
- **The horizon has elapsed and the obligatory disclosure line shows the action did not occur** — e.g. a
  promised buyback but the cash-flow "Repurchases of common stock" line is zero/absent for the full
  horizon, or promised debt issuance/paydown that never appears. Cite that line as your evidence.
  (Absence in an *obligatory* disclosure point is evidence of non-occurrence — distinct from merely
  failing to find a mention, which is `not_yet_resolvable`.)

### `not_yet_resolvable`
You **cannot find evidence** in the available filings, OR the horizon had not elapsed by the time of
the last available filing.

Use when:
- The claim horizon is multi-year and no filing yet covers the endpoint
- The filing exists but contains no relevant data point for this claim
- You searched 10-Qs, 10-Ks, and 8-Ks within the window and genuinely found nothing

Do **not** use it when the horizon has elapsed **and** an obligatory disclosure line (cash-flow /
balance-sheet) shows the promised action did not occur — that is evidenced non-occurrence, i.e.
`contradicted`. `not_yet_resolvable` is for "too early to tell" or "no obligatory disclosure point
where silence would be meaningful," not for excusing a promise that an elapsed-horizon statement shows
never happened.

`not_yet_resolvable` is the only verdict allowed with an empty `expected_evidence` list.

---

## Confidence Levels

Assign independently from the verdict — confidence reflects how sure YOU are of the label, not
whether the company succeeded.

| Level | When to use |
|---|---|
| `high` | Evidence is explicit, unambiguous, and directly addresses the claim |
| `medium` | Evidence is relevant but requires some inference or the figure is indirect |
| `low` | You found something suggestive but it could be explained another way |

---

## Partial-Credit Policy by Claim Sub-type

### `numerical_guidance` (revenue, EPS, margins, etc.)

| Situation | Verdict |
|---|---|
| Actual within ±10% of stated figure | `verified` |
| Actual is in the right direction but more than 10% off | `partially_verified` |
| Actual is in the wrong direction (e.g., claimed growth → actual decline) | `contradicted` |
| No Compustat / filing data covers the claimed period yet | `not_yet_resolvable` |

**Note on ranges:** If the claim gives a range (e.g., "$148B–$153B"), the actual must fall inside the
range for `verified`. If it falls within 10% of the nearest bound, use `partially_verified`.

---

### `capital_allocation` — Buybacks (`subcategory: buyback`)

The key question is: **was the authorized amount actually repurchased within the stated horizon?**

| Situation | Verdict |
|---|---|
| ≥90% of announced amount repurchased within horizon | `verified` |
| 50–89% repurchased within horizon | `partially_verified` |
| <50% repurchased OR program cancelled/suspended | `contradicted` or `partially_verified` (use your judgment + notes) |
| No subsequent 10-Q cash flow statement covers the horizon yet | `not_yet_resolvable` |

**Where to look:** Cash flow statement → "Repurchases of common stock" (or treasury stock line). Also
check 8-Ks for buyback announcements and press releases filed as exhibits.

---

### `capital_allocation` — Dividends (`subcategory: dividend`)

| Situation | Verdict |
|---|---|
| Dividend paid at the stated amount and on schedule | `verified` |
| Dividend paid but at a different amount or timing | `partially_verified` |
| Dividend cut, suspended, or reversed | `contradicted` |
| Horizon not yet elapsed in available filings | `not_yet_resolvable` |

**Where to look:** 8-Ks declaring dividends; 10-Q cash flow statement → "Dividends paid."

---

### `capital_allocation` — CapEx Plans (`subcategory: capex_plan`)

Capital expenditure claims are often directional or range-based. Apply:

| Situation | Verdict |
|---|---|
| Stated factory / facility was built and began operations within horizon | `verified` |
| Project started but not completed within horizon, or costs materially exceeded claim | `partially_verified` |
| Project cancelled, delayed beyond horizon with no restart signal | `contradicted` |
| No filing yet covers the horizon endpoint | `not_yet_resolvable` |

**For dollar-figure capex claims:** Use the same ±10% rule as numerical_guidance.

**Where to look:** 10-Q/10-K cash flow statement → "Capital expenditures"; MD&A section;
8-Ks announcing plant openings or cancellations.

---

### `capital_allocation` — Debt (`subcategory: debt`)

| Situation | Verdict |
|---|---|
| Stated paydown / issuance occurred within the horizon at the stated amount (±10%) | `verified` |
| Debt action taken but amount or timing materially different | `partially_verified` |
| Opposite action taken (claimed paydown → actually issued more; claimed issuance → didn't happen) | `contradicted` |
| Filing period doesn't yet cover the horizon | `not_yet_resolvable` |

**Where to look:** 10-Q/10-K balance sheet → long-term debt; cash flow statement → "Repayments of
debt" / "Proceeds from issuance of debt"; 8-Ks for note offerings or credit facility changes.

---

## Worked Examples (TSLA)

These use real claims from `data/claims/pilot_claims.csv`. Read them before labeling to calibrate.

---

### Example 1 — `verified`

**Claim** (`TSLA_20200722_124bd5bf`, call date 2020-07-22):
> "we're going to be building our next Gigafactory in Texas"

**Horizon:** unspecified  
**What to find:** An 8-K or 10-K confirming Giga Texas broke ground and eventually began production.  
**Verdict:** `verified` — Giga Texas opened in April 2022, confirmed in the Q1 2022 10-Q and an 8-K
press release. The factory was built. Confidence: `high`.

---

### Example 2 — `partially_verified`

**Claim** (`TSLA_20201021_2636f8b9`, call date 2020-10-21):
> "we have revised up our expectations for capital spending by $2 billion to $2.5 billion."

**Horizon:** unspecified (implied near-term given it's a revised guidance for the current spending
cycle)  
**What to find:** Actual CapEx in subsequent 10-Qs/10-K for fiscal 2020 and 2021.  
**Verdict:** `partially_verified` — Check the cash flow statement. If actual CapEx came in within
the revised range → `verified`. If it came in higher or lower by >10% → `partially_verified`.
This particular claim is a revision announcement, not a commitment — weight the
direction of the revision, not just the magnitude. Confidence: `medium`.

---

### Example 3 — `verified` (delivery guidance)

**Claim** (`TSLA_20201021_6ff23990`, call date 2020-10-21):
> "we expect to achieve our original 2020 guidance of 500,000 deliveries despite the operational
> interruptions earlier in the year."

**Horizon:** FY2020  
**What to find:** Tesla's full-year 2020 delivery announcement (filed as an 8-K in January 2021)
or the 10-K delivery table.  
**Verdict:** Tesla delivered 499,550 vehicles in 2020 — within 0.1% of 500,000.
Label as `verified` (within ±10%). Confidence: `high`.

---

### Example 4 — `not_yet_resolvable`

**Claim** (`TSLA_20200129_24163afe`, call date 2020-01-29):
> "we also anticipate significant progress on factory construction of Shanghai- and Berlin-built
> Model Y, which will result in continued increases in capital spending"

**Horizon:** unspecified, no `horizon_end_date`  
**Note:** No specific dollar figure is given, and "continued increases" is directional.
This claim has no `horizon_end_date` and no precise magnitude to verify.  
**Verdict:** `not_yet_resolvable` — Cannot assign a precise verdict without a target figure or
end date. Note this in `labeler_notes`. Confidence: `low`.

---

## Common Mistakes to Avoid

1. **Don't use the agent's retrieved evidence first.** Open the SEC filings yourself.

2. **Don't require exact match for `verified`.** ±10% is real-world rounding; management can't
   predict the future to the dollar.

3. **Don't mark `not_yet_resolvable` just because it's hard to find.** Search the MD&A, the cash
   flow statement, and 8-Ks before giving up. Only use it if you genuinely cannot find relevant
   evidence after looking — and **not** to excuse a promise that an elapsed-horizon obligatory line
   (e.g. a zero buyback in the cash-flow statement) shows never happened: that is `contradicted`.

4. **Don't mark `contradicted` just because the number is off.** If the direction was right but
   the magnitude missed, that's `partially_verified`, not `contradicted`. Reserve `contradicted`
   for directional reversals and explicit cancellations.

5. **Claims with no `horizon_end_date` need judgment.** If no horizon is stated, use the next
   2–4 filings after the call date as your search window. Note your window choice in
   `labeler_notes`.

6. **Write labeler notes.** Even one sentence — "Q2 2021 10-Q cash flow shows $487M repurchases
   vs $500M announced, within 10%." This is what calibrates the rubric across labelers.

---

## Quick Reference Card

```
verified           → claim came true, evidence is clear, figure within ±10%
partially_verified → partially right: direction correct but magnitude off, or partial completion
contradicted       → filing shows the opposite, OR an elapsed-horizon obligatory line shows it didn't happen
not_yet_resolvable → horizon hasn't elapsed, or no obligatory disclosure point (≠ excusing a broken promise)

confidence: high   → evidence is unambiguous and directly addresses the claim
confidence: medium → evidence is relevant but requires inference
confidence: low    → something suggestive but not definitive
```

**Evidence must come from:** 10-Q, 10-K, or 8-K filed **after** the call date and within the
claim horizon. Never cite Compustat directly — it's a convenience cross-check only; the cited
`accession_no` must be an SEC filing.
