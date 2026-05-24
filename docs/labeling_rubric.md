# Gold-Set Labeling Rubric

> **STATUS: DRAFT — provisional, for review.** This is a *minimum-viable temporary*
> rubric written so the team can start trial-labeling before the assigned owner
> finalizes it. Every threshold below marked _(provisional)_ is a placeholder
> the team should ratify or replace. It is not the final rubric. Tracks
> `CLAUDE.md` open items #3 (partial-credit policy) and #4 (rubric finalization).

## Purpose

This rubric tells every labeler how to turn the evidence they find into one
consistent verdict. Without it, two labelers reading the same filings assign
different verdicts, and `verifier.eval`'s verdict-accuracy score measures
labeler noise instead of agent quality. The labeling helper (`verifier.label`)
finds *where the evidence is*; this rubric decides *what verdict it supports*.

## Scope (pilot)

The pilot gold set covers **`capital_allocation` claims only** — forward-looking
management statements about share buybacks, dividends, capital expenditure, or
debt. These are graded against the company's subsequent SEC filings (10-K,
10-Q, 8-K). `numerical_guidance` claims are graded against Compustat, not
filings, and are out of scope for this pilot (the verifier also currently
supports only `capital_allocation`).

## The four verdict buckets

A verdict compares what management *said they would do* against what the
company's later filings *show it did*, within the claim's stated horizon.

- **`verified`** — the filings show the company did substantially what the
  claim stated, within the horizon. For a claim with a stated figure, the
  realized amount lands within the claimed range, or at **≥ 80%** _(provisional)_
  of a single claimed figure. For a figure-less claim ("we will pay down
  debt"), the filings clearly show the action happened in the claimed
  direction.

- **`partially_verified`** — the company moved in the claimed direction but
  fell materially short on magnitude or timing. Use this when the realized
  amount is between **40% and 80%** _(provisional)_ of the claimed figure, or
  the action happened but outside the stated horizon, or a multi-part claim had
  some parts hold and others not.

- **`contradicted`** — the filings show the opposite of the claim, or no
  meaningful movement toward it: realized **< 40%** _(provisional)_ of the
  claim, the wrong direction (claimed a buyback, filings show net share
  issuance; claimed debt paydown, debt rose), or the relevant filing covers the
  horizon and shows the action simply did not occur.

- **`not_yet_resolvable`** — the claim *cannot be graded* from the available
  filings. Use this **only** when the horizon has not elapsed, the filing that
  would cover the horizon is not in the pulled data, or the claim is too vague
  to define any checkable outcome. This is the only verdict that may have empty
  `expected_evidence`.

### `contradicted` vs `not_yet_resolvable` — the key distinction

Do not use `not_yet_resolvable` as a synonym for "I couldn't find evidence."
If the filing that *should* cover the horizon exists, you searched it, and it
shows the action did not happen — that is **`contradicted`**, not unresolvable.
`not_yet_resolvable` means the evidence *cannot exist yet*; `contradicted`
means the evidence *should exist and shows a miss*.

## Partial-credit policy _(provisional — the load-bearing open question)_

The 80% / 40% bands above are deliberate placeholders. The real policy — how
much shortfall turns `verified` into `partially_verified` into `contradicted`,
and how to weigh a magnitude miss against a timing miss — is a team decision
(`CLAUDE.md` #3). Until it is set, apply the 80/40 bands, and **whenever a
claim is near a boundary, record your reasoning in `labeler_notes`** so the
boundary cases can be reviewed when the policy is finalized.

## Selecting `expected_evidence`

`expected_evidence` is the list of filing excerpts that *substantiate your
verdict* — what a second labeler would need to reach the same conclusion.

- Cite the **SEC filing** (by `accession_no`): the cash-flow-statement line for
  a buyback ("repurchases of common stock"), dividends paid, capital
  expenditures, or debt issued/repaid; an 8-K for an announced program.
- Every decisive verdict (`verified` / `partially_verified` / `contradicted`)
  **requires at least one** `GoldEvidence` entry — the loader rejects a
  decisive verdict with empty evidence.
- Keep each `quote` to the relevant passage, **≤ 500 characters**.
- Cite only filings filed **after the call date** — evidence cannot predate
  the claim.

## Confidence

Set `confidence` on each label:

- **`high`** — the evidence is explicit and unambiguous (a filing line item
  states the figure directly).
- **`medium`** — the evidence is indirect or needs some interpretation.
- **`low`** — the evidence is sparse, the claim is borderline-vague, or you
  are genuinely unsure. Pair a `low` confidence with a note explaining why.

## Independence rule (load-bearing — do not break)

Build each label **independently of what the verification agent surfaced.**
Do not run `verifier.run` and copy its evidence into the gold set — the eval
scores the agent's retrieval against this gold set, so seeding the gold set
from the agent's own output makes the score circular and meaningless. Use the
agent-free helper (`verifier.label`) or read the filings directly.

## Workflow

1. Run `python -m verifier.label --claims <claims.csv> --claim-id <id>
   --labeler <you>` to see the claim and the filings filed after the call.
2. Add `--query <term>` to search those filings; the helper prints paste-ready
   `GoldEvidence` fragments.
3. Read the filings yourself, decide the verdict against this rubric, and fill
   the printed `GoldLabel` skeleton (`verdict`, `confidence`, `labeler_notes`,
   and the evidence fragments you judged relevant).
4. Append the line to `data/gold/pilot_<ticker>.jsonl` and validate it with the
   one-liner in `data/gold/README.md` (`verifier.gold.load_gold_labels`).

## Open decisions for the rubric owner

1. Ratify or replace the 80% / 40% partial-credit bands.
2. Define how a **timing** miss (right amount, wrong period) trades off against
   a **magnitude** miss.
3. Decide whether a multi-part claim is labeled once (whole-claim verdict) or
   split — the current extractor already splits compound statements, so one
   `claim_id` should be one atomic assertion, but confirm.
4. Decide whether `low`-confidence labels are kept, down-weighted, or excluded
   by `verifier.eval`.
