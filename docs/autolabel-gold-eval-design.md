# LLM-Led Gold Set + gpt-5.1 Agent Eval — design

> **Status: proposed (2026-05-25).** Time-boxed end-to-end evaluation of the
> capital-allocation verification agent, then a short agent-improvement loop.
> On branch `feature/gold-set-autolabel` (based on the autochecker branch).
> Touches `src/verifier/` (new module only) and `data/gold/`.

## Goal

1. **Auto-label a gold set** with **GPT-5.5 + the rubric** over a frozen subset
   of the capital-allocation claims in `55_full_run.csv`.
2. **Run the verification agent with gpt-5.1** (no rubric) over the same claims
   and **score** retrieval (recall@k, precision) and verdict accuracy with
   `verifier.eval`.
3. With that gold set frozen, run a short improvement loop: a couple of
   iterations on the verifier's toolset, then a couple of chunker
   autoresearch runs.

### Known shortcoming (must be named in the writeup)

The gold set is **LLM-labeled, not hand-labeled** — a deliberate
time-constrained substitution for the proposal's hand-labeled set. The
labeler/agent asymmetry (GPT-5.5 **with** the rubric labels; gpt-5.1
**without** the rubric is graded) reduces but does not eliminate
model-vs-model circularity, and the later improvement loop tunes the agent
toward this gold set — so treat it as a proxy, do not overfit, and flag it as
an explicit future-work item (replace with human labels).

## Scope

- **Claim source:** `data/claims/55_full_run.csv` (gpt-5.5 / `b-extract-v5`,
  539 claims).
- **Agent capability:** the verifier grades `capital_allocation` only
  (`numerical_guidance` raises `UnsupportedClaimTypeError`). The eval is
  capital-allocation only — **137** such claims in the 55 run
  (AMZN 76 / TSLA 28 / KO 22 / LLY 11).
- **Gold set = a frozen stratified subset** of the *residual* (cap-alloc claims
  with no figure in the quote — see the cascade section), not the whole 137; a
  validation set is a sample. Target ~32, capped per ticker so AMZN does not
  dominate; final size fixed at selection time. **Once selected, the claim set
  is frozen** for the entire eval + improvement loop, or recall@k / verdict
  numbers are not comparable across iterations.
- **No re-labeling after seeing agent output** — that reintroduces circularity.

## Production workflow (cascade) and what it means for the gold set

The intended production architecture is a **cascade**: the Compustat autograder
runs first (cheap, deterministic, high-precision on anything Compustat can
measure); whatever it screens out as *not* Compustat-verifiable falls through to
this agentic SEC-filings verifier (expensive, handles the qualitative residual).
The two are **independent pipelines** — our gold labeling uses the keyword sweep
+ GPT-5.5 + rubric and never touches Compustat or the autochecker output.

This does **not** gate the labeling *mechanics*, but it does dictate *which*
claims represent the verifier's job: in production the verifier only ever sees
the autograder's **residual**, so the gold subset is sampled from that residual
to make the numbers representative.

**Identifying the residual — figure heuristic, no LLM (chosen).** Approximate the
non-Compustat-verifiable cap-alloc claims as those whose `verbatim_quote` carries
no figure (no `$` / `%` / "billion" / "million" / digit). The quantified
buyback/dividend/debt claims (which Compustat settles upstream) are thereby
excluded; what remains is the qualitative capex/investment residual — the same
capex-skew flagged below, now with a principled reason: that skew *is* the
verifier's production distribution. A precise residual (the autochecker's
screen stage) is a deliberate later refinement if the wiring warrants it.

Two carve-outs of awareness, both out of scope here: (a) the residual also
includes non-Compustat **numerical_guidance** claims the verifier cannot yet
grade (`UnsupportedClaimTypeError`) — a future item; (b) **downstream profile
assembly** must decide authority when a claim carries both a Compustat and an
SEC-filings verdict — a profile-merge concern.

## Architecture

One new module; everything downstream already exists.

### New: `src/verifier/autolabel.py`

A **non-interactive sibling of `verifier.label`**. Kept a separate file — not an
`--auto` flag on `label.py` — so the teammate-owned interactive helper and its
independence import-test stay untouched.

Reuses from `verifier.label` (no duplication of the sweep): `load_claim`,
`candidate_filings`, `grading_window`, `sweep`, `_claim_focus`, `_SWEEP_TERMS`,
plus `GoldEvidence` / `GoldLabel` and `append_gold_label`.

Replaces the human `run_session` with one GPT-5.5 structured-output call:

1. Build the candidate list with the **same deterministic keyword sweep** the
   human helper uses (no FAISS, no agent).
2. Prompt GPT-5.5 with: the claim, the full text of `docs/labeling_rubric.md`,
   and the numbered candidate passages.
3. Structured output (`AutoLabelDecision`): `selected_indices: list[int]`,
   `verdict: VerdictLabel`, `confidence: Confidence`, `notes: str`.
4. Map `selected_indices` → the chosen `Candidate`s → `GoldEvidence`; build a
   `GoldLabel(labeler="gpt-5.5", ...)`; append to `data/gold/auto_<ticker>.jsonl`.
5. Enforce the same invariant the human flow does: a decisive verdict with no
   selected evidence is rejected — re-prompt once, then record
   `not_yet_resolvable` if it still returns none (logged).

Model from a new env var **`GOLD_LABELER_MODEL`** (e.g. `openai:gpt-5.5`).

CLI: `python -m verifier.autolabel --claims <csv> --gold-dir data/gold
[--ticker T] [--claim-ids <file>] [--limit N]`. Idempotent: skips a claim
already present in its `auto_<ticker>.jsonl` (reuses `load_gold_claim_ids`).
A claim-id list file pins the frozen subset.

### Reused unchanged: `verifier.eval` + `verifier.agent`

`python -m verifier.eval --gold data/gold/ --claims data/claims/55_full_run.csv
--mode verdict --k 8` runs `verify()` live per gold claim and scores it. The
agent prompt does **not** load the rubric today (only a "rubric forthcoming"
note) — the design must keep it that way.

## Data flow

```
55_full_run.csv ──cap_alloc & no-figure (residual), stratified-sample, freeze──▶ gold claim subset (~32)
        │
        ▼  verifier.autolabel  (GPT-5.5 + rubric, deterministic sweep evidence)
data/gold/auto_{amzn,tsla,ko,lly}.jsonl
        │
        ▼  verifier.eval --mode verdict --k 8   (VERIFIER_AGENT_MODEL=openai:gpt-5.1, NO rubric)
summary (mean recall@k, precision, verdict_accuracy) + data/eval/per_claim_results.csv
```

## Independence guarantees (load-bearing)

- **Labeler ⟂ agent retrieval:** the auto-labeler reuses only the deterministic
  keyword sweep — never the agent's FAISS index, `verifier.agent`,
  `verifier.tools`, or `index/` artifacts. Same import constraints as
  `label.py`; an import-graph test enforces it. recall@k stays a real comparison
  of two independent retrievals.
- **Agent ⟂ rubric:** the rubric is loaded only into the GPT-5.5 labeler prompt.
  The gpt-5.1 agent never sees it. A test asserts the rubric path is not
  referenced from the agent prompt path.

## Staging

1. **Prereqs (no new code):** rebuild FAISS indexes if stale
   (`python -m verifier.index --all`; required after the horizon-ceiling change);
   set `.env`: `GOLD_LABELER_MODEL=openai:gpt-5.5`,
   `VERIFIER_AGENT_MODEL=openai:gpt-5.1` (+ existing parser/embedding vars).
2. **Select + freeze** the gold subset: apply the no-figure residual filter to
   the 137 cap-alloc claims, stratified-sample ~32, and write the claim-id list
   to a pinned file under `data/gold/`.
3. **Build** `verifier.autolabel` + offline tests (LLM mocked).
4. **Smoke** end-to-end on one ticker: auto-label → eval → eyeball
   `per_claim_results.csv`.
5. **Scale** to the full frozen subset; record the baseline gpt-5.1 numbers.

## Downstream phases (gated on the frozen gold set)

- **Toolset iteration:** a couple of passes improving the agent's tools/prompt,
  re-scoring against the frozen gold each pass. Drives verdict accuracy
  (reasoning over retrieved evidence).
- **Chunker autoresearch:** a couple of sweeps over chunk/retrieval configs,
  scored by recall@k against the (sweep-derived, embedding-independent) gold
  evidence. Drives retrieval quality. Because it improves the evidence the agent
  reasons over, consider running it early / interleaved rather than strictly
  after toolset work. (This is the deferred chunker autoresearcher, now
  unblocked by having a gold set.)

## Testing (offline, LLM mocked)

- Independence: `autolabel` import graph excludes `agent`/`faiss`/`tools`/index.
- A mocked decision maps `selected_indices` → correct `GoldEvidence` and builds
  a schema-valid `GoldLabel`.
- Decisive-verdict-without-evidence is rejected/handled per the rule above.
- Idempotent skip of an already-labeled claim; the pinned claim-id list is
  honored.

## Risks / caveats

- **LLM-labeled gold + tuned-against-it loop** — the headline caveat for the
  paper; treat the gold as a proxy, do not overfit.
- **Capex-skewed, AMZN-heavy population** — little subcategory diversity;
  verdicts are judgment-heavy. Report it; do not over-claim generality.
- **`55_full_run.csv` may change** if re-extracted / on autochecker merge —
  freeze the subset by pinned claim-id list so a CSV refresh doesn't silently
  shift the eval; re-pull deliberately if intended.
- **gpt-5.1 agent runtime/cost over the subset** — mitigated by the SQLite chat
  cache; staged by ticker.

## Non-goals

- Grading `numerical_guidance` (autochecker's job).
- Modifying `verifier.label`, the rubric, or the autochecker; consuming
  autochecker output.
- Human labeling (explicit future work).
- Any change to the agent's retrieval/prompt beyond confirming it stays
  rubric-free (until the downstream toolset/chunker phases, which are scoped
  separately).
