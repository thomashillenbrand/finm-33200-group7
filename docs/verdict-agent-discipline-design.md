# Verdict-Agent Discipline Pass — design

> **Status: proposed (2026-05-25).** First improvement pass on the gpt-5.1
> capital-allocation verification agent, motivated by the auto-labeled-gold eval.
> Touches `src/verifier/` (agent.py, corpus.py) only. Workstream C.

## Goal

The eval (`docs/autolabel-eval-summary.md`) showed the agent retrieves well
(recall@8 0.75) but **over-claims on forward-looking claims** — it returned a
decisive verdict on 3 of 6 controls whose horizons (2026–27) make any verdict
impossible. Root issue: the agent grades as if a future-dated outcome were
already knowable, instead of grounding strictly on filings that exist.

This pass makes the verdict agent **evidence-grounded and date-aware** without a
crude date-based verdict ceiling.

## Scope

In: (1) a deterministic **coverage pre-check** feeding the agent date context;
(2) **grounding discipline + a real rubric** in the verdict prompt; (3) a
structural **evidence net** (no decisive verdict without citations); (4) **parser
retry/repair**; (5) **trace review** as the validation method.

Deferred (separate efforts): adding *new* agent tools (gated on what the trace
review finds), and chunker/embedding **autoresearch**.

## Design principle (load-bearing)

Date is **context, not a ceiling.** A claim fulfilled *early*, with clear filing
proof, is still `verified` — the horizon is a deadline, not a window that must
close. The only thing deterministically *forced* is **"no decisive verdict
without cited evidence."** Everything date-related informs the agent's own
reasoning; it never caps the verdict.

## Components

### 1. Coverage pre-check (structural, deterministic)

`SearchIndex` already loads `chunks.parquet` (with `report_date`). Add a cached
accessor `SearchIndex.max_report_date -> date | None` = the latest filing period
available for the ticker.

In `verify()` (before building the agent; the index is already loaded+cached by
`bind_search_filings`), compute:
- `coverage = SearchIndex.load(claim.ticker).max_report_date`
- `fully_covered = claim.horizon_end_date is not None and coverage is not None and coverage >= claim.horizon_end_date`

This is passed to `_format_claim_for_agent` (new params). No "today" needed — a
filing whose reporting period reaches the horizon *is* proof the horizon elapsed.

### 2. Claim-message coverage context

`_format_claim_for_agent` gains a line stating the evidence boundary, e.g.:

> *Filings are available through their 2024-12-31 reporting period. This claim's
> horizon runs to 2026-12-31 — beyond available coverage. Grade only on filings
> that exist; do not assume or infer outcomes from filings not yet published.*

(When `fully_covered`, the line says the horizon is within coverage.)

### 3. Verdict prompt rewrite (`VERDICT_SYSTEM_PROMPT`)

Replace the thin one-line verdict definitions + the "rubric forthcoming" note
with grounding discipline and concrete criteria (the *spirit* of the gold
rubric — ±10% / evidenced-non-occurrence — **not** the gold file verbatim, so
the agent⟂gold-rubric independence holds):

- **`verified`** — realization is clearly evidenced in retrieved filings,
  *including if it occurred earlier than the stated horizon*. A numeric target
  met within ~10% counts.
- **`partially_verified`** — intervening filings show genuine partial progress,
  or a numeric outcome is directionally right but materially off.
- **`contradicted`** — a filing shows the opposite, OR (horizon elapsed) the
  line item where the action must appear shows it did not happen.
- **`not_yet_resolvable`** — no supporting evidence found in the available
  filings. This is the **default** when neither full nor partial credit can be
  grounded; do **not** infer realization from tangential mentions or from
  filings that do not yet exist.

### 4. Evidence net (structural safety)

In `verify()`, after `_extract_structured`, when `mode == "verdict"`: if
`output.verdict in {"verified","partially_verified"}` and `output.items` is empty,
coerce to `not_yet_resolvable` (`output.model_copy(update=…)`) and log the
override. This catches pure confabulation. It never touches an evidence-backed
`verified`, so legitimate early verification is preserved. (No date-based cap.)

### 5. Parser retry/repair (`_extract_structured`)

The parser LLM call (`extractor.invoke`) intermittently returns an unparseable
structured response ("no 'parsed' field nor 'refusal'"); `max_retries` does not
cover this (the API call succeeded). Wrap it: on `ValueError`/`ValidationError`,
retry once **force-fresh** (bypass the chat cache so a cached bad completion
isn't replayed); on persistent failure, return a safe empty instance
(`EvidenceBundle(items=[])` / `Verdict(items=[], verdict="not_yet_resolvable",
reasoning="parser failed to produce structured output")`) rather than raising —
so one bad parse degrades to `not_yet_resolvable`, not a lost claim.

### 6. Trace review (method)

Re-run a handful of claims with `trace=True`; read the traces to (a) confirm the
coverage context + evidence net behave, and (b) assess `search_filings`
effectiveness (does the agent search enough / redundantly? are there obvious
gaps a new tool would close?). Findings queue a possible new-tool follow-up.

## Data flow

```
Claim ──▶ verify()
  ├─ SearchIndex.max_report_date(ticker) ─▶ fully_covered? ──┐
  ├─ _format_claim_for_agent(claim, coverage, fully_covered) │ (coverage line in user msg)
  ├─ agent.invoke (searches intervening filings, bounded by tool's horizon ceiling)
  ├─ _extract_structured(...)  ── retry/repair ──▶ Verdict
  └─ evidence net: decisive & no items ─▶ not_yet_resolvable
```

## Validation + an eval-comparison caveat

Re-run `verifier.eval` against the frozen gold and compare to the baseline
(recall@8 0.75 / verdict 0.56). **Watch this:** allowing `partially_verified` on
open-horizon claims with real intervening evidence may *disagree* with the
keyword-sweep gold's conservative `not_yet_resolvable` — which can *lower*
measured verdict-accuracy even though the agent is more nuanced. Judge the
forward-control behavior from the **traces**, not the headline number alone.

## Testing (offline, mocked)

- `max_report_date` returns the latest `report_date`; `None` on empty.
- `fully_covered` classification: horizon ≤ coverage → True; horizon > coverage
  or either None → False.
- Coverage line appears in `_format_claim_for_agent` for both covered/open cases.
- Evidence net: `verified`/`partial` + empty items → `not_yet_resolvable`;
  `verified` + non-empty items → unchanged; `not_yet_resolvable` + empty →
  unchanged.
- Parser repair: a fake extractor that raises once then succeeds → succeeds;
  one that always raises → safe empty instance, no exception.
- Independence: the verdict prompt does not load `docs/labeling_rubric.md`
  (the existing agent⟂rubric test still passes).

## Risks / caveats

- **Prompt rubric drift from the gold rubric** — keep it criteria-in-spirit, not
  the gold file, or the agent⟂gold independence breaks. Enforced by the existing
  no-`labeling_rubric` test on the agent path.
- **Coverage from the index, not EDGAR** — `max_report_date` reflects *pulled*
  filings; if data is stale, a resolvable claim could read as open. Acceptable
  (and honest — the agent can only grade on what's indexed).
- **Evidence net is verdict-mode only** — evidence mode is unaffected.

## Non-goals

- New tools (gated on the trace review).
- Chunker/embedding autoresearch.
- Numerical-guidance grading (autochecker's job).
- Re-labeling the gold set.
