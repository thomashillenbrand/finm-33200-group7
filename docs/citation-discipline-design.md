# Citation-Discipline Pass — design

> **Status: PARTIALLY SHIPPED (2026-05-25).** Of the two proposed prompt
> additions, only **#2 (iterate-on-weak-search)** shipped. **#1 (the cite-surfaced
> "must grade" push) was implemented, eval'd, and reverted** — it regressed the
> ship gate (forward controls 5/6 → 4/6) and overall metrics. See "Outcome" below.
> Prompt-only; touches `src/verifier/agent.py` (`VERDICT_SYSTEM_PROMPT`). Workstream C.

## Outcome (2026-05-25)

Both additions were built and the combined version was evaluated
(`data/eval/runs/*citation-discipline*`) against the discipline-pass baseline:

| | discipline-pass | citation-discipline (both) |
|---|---|---|
| recall@8 | 0.821 | 0.667 |
| precision | 0.432 | 0.359 |
| verdict accuracy | 0.714 | 0.607 |
| forward controls | 5/6 | **4/6 (gate failed)** |

The combined change regressed every metric and tripped the pre-registered
forward-control gate (≥5/6). The regression is attributed to **#1**: it drove
over-reach on a forward control (`AMZN_20260429_9465d0a6` stopped abstaining) and
flipped two previously-correct resolvable claims. **#1 was reverted.** **#2 was
kept** — it only adds a search when the first is thin (monotonic; cannot reduce
what is retrieved), so it is accepted as a low-risk addition on top of the
validated discipline-pass without a separate eval (single-run eval is too noisy
to isolate its effect). Caveat for honesty: shipping #2 unmeasured rests on that
a-priori argument, not a measured gain.

## Goal

The trace review (`docs/autolabel-eval-summary.md` → "Trace review") showed
`search_filings` surfaces the correct gold filing **12/13 (92%)** of decisive
claims, but the agent only **cites** it 9/13 — and it runs a single search 24/28.
The leverage is therefore the *agent's use of what it already retrieved*, not the
tool. This pass makes two **conservative** prompt adjustments to close the clear
part of that gap without re-introducing the forward-claim over-reach the prior
discipline pass fixed (forward controls 3/6 → 5/6).

## Scope

Prompt-only edits to `VERDICT_SYSTEM_PROMPT`. **No new tool, no structural
change.** Everything from the discipline pass stays exactly as-is: the coverage
context, the `_enforce_evidence_grounding` evidence net, grade-only-on-existing-
filings, the no-date-cap rule, and agent⟂gold-rubric independence.

## Design principle

Conservative nudge. The abstention default is preserved. We add a *counterweight*
for the one clearly-wrong behavior — abstaining when on-point evidence is already
in the results — and a retry-before-abstaining for thin first searches. We do
**not** broadly push the agent to grade; "directly and explicitly evidences the
outcome" is the bar.

## The two additions to `VERDICT_SYSTEM_PROMPT`

The current prompt has a "Critical: grade only on filings that exist … never a
guess" paragraph (the no-over-reach guardrail). We add its counterpart plus a
search-iteration instruction.

**1. Cite directly-relevant surfaced evidence (counterweight to the no-guess rule).**
Add immediately after the "Critical: grade only on filings that exist…" paragraph:

> *Equally important — do not abstain when the evidence is already in front of
> you. If a retrieved filing **directly and explicitly** evidences the claim's
> outcome, you MUST cite it and assign the matching decisive verdict.
> `not_yet_resolvable` is the wrong answer when clear, on-point supporting
> evidence appears in your search results; reserve it for when the retrieved
> filings do not address the outcome, or the horizon has not elapsed with no
> progress shown.*

**2. Iterate on a weak first search.** Add to the search instruction (after
"Use the `search_filings` tool to retrieve evidence…"):

> *If your first search returns no filing that addresses the claim's outcome,
> issue at least one more search with reformulated terms — the specific facility
> or program name, or the relevant financial-statement line item — before
> concluding `not_yet_resolvable`.*

These are generic reasoning instructions, not the gold rubric, so the
agent⟂`labeling_rubric` independence is unaffected.

## Explicitly unchanged

- `_enforce_evidence_grounding` (decisive-without-citation → `not_yet_resolvable`)
  remains the floor — addition #1 pushes the agent to cite *real* evidence, which
  is exactly what the net requires, so the two reinforce rather than fight.
- Coverage context, `_horizon_within_coverage`, parser retry/repair: untouched.
- No date-based verdict cap; early-with-proof `verified` still allowed.

## Validation (same frozen gold + run records)

Re-eval, saved individually:
`verifier.eval --gold data/gold/auto --claims data/claims/55_full_run.csv
--mode verdict --k 8 --no-cache --run-label citation-discipline`

- **Ship/no-ship gate:** forward controls must stay **≥ 5/6** (no over-reach
  regression). If they regress, revert (the run record's `git_head` makes this
  unambiguous).
- **Goal:** cited-recall and verdict-accuracy rise vs the discipline-pass run
  (recall@8 0.82 / precision 0.43 / verdict 0.71); `not_yet_resolvable` rate on
  *resolvable* claims falls.
- **Trace re-check** the 3 retrieved-but-not-cited claims (`TSLA_20210127_982bc4b3`,
  `LLY_20221101_00d43fa5`, `LLY_20221101_95a826e5`) + 1–2 forward controls —
  confirm the agent now cites the surfaced evidence and the forward controls
  still abstain. Judge behavior from traces, not the headline number alone.

## Testing (offline)

- Prompt-phrase assertions in `tests/test_agent_discipline.py` locking the new
  guidance: the verdict prompt contains "directly and explicitly" (cite-surfaced
  rule) and an iterate-before-abstaining instruction ("issue at least one more
  search").
- Existing `test_verdict_prompt_does_not_reference_the_gold_rubric` and
  `test_agent_module_does_not_load_the_rubric` still pass (independence held).
- Behavioral validation is the eval re-run, not a unit test (it's a prompt change).

## Risks / caveats

- **Regressing forward over-reach** — the main risk; mitigated by the
  conservative "directly and explicitly" bar + the ≥5/6 ship gate + the trace
  re-check. The evidence net still blocks citation-free decisive verdicts.
- **LLM nondeterminism** — verdicts vary run-to-run on borderline claims (seen on
  `TSLA_20250723_bedcd74c`); read the gate from the forward-control set, and don't
  over-index on a single claim flipping.

## Non-goals

- New tools / changing `search_filings` (retrieval is already 92% effective).
- Chunker/embedding autoresearch.
- Numerical-guidance grading (autochecker's job).
- The eval-metric refinement (separate "tool-surfaced vs cited" recall) — noted in
  the trace review as a later idea, not part of this pass.
