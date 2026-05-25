# Capital-Allocation Verifier — Auto-Labeled Gold Set + gpt-5.1 Eval

*Workstream C/D · 2026-05-25 · Thomas*

## TL;DR

Built an **automated gold-set labeler** (`verifier.autolabel`) and ran the **gpt-5.1 verification agent** against it on capital-allocation claims.

| Metric | Value | Scored over |
|---|---|---|
| **recall@8** | **0.75** | 12 decisive claims (gold has cited evidence) |
| **precision@8** | 0.33 | same 12 |
| **verdict accuracy** | **0.56** | 27 claims (1 skipped on a parser error) |

**Main takeaways:**
- **Retrieval is solid** — the agent finds 75% of the gold-cited filings.
- **The agent over-claims on forward-looking claims** — on the 6 deliberately-too-early "control" claims (horizons in 2026–27, so no evidence *can* exist yet), it invented a verdict **3 of 6 times** instead of saying *not yet resolvable*. This is the clearest weakness.
- Verdict accuracy on the **resolvable** claims is better: **8/12 (67%)**.

---

## What the auto-labeler is, and why

The production design is a **cascade**: the Compustat **autochecker** grades the quantitative claims it can verify; whatever it can't falls through to the **agentic SEC-filings verifier**. The gold set validates *that agent*, so it samples the autochecker's **residual** (the non-Compustat-verifiable capital-allocation claims).

`verifier.autolabel` replaces a human labeler with **GPT-5.5 + the grading rubric**, deciding verdicts over a **deterministic keyword sweep** of the filings. Two properties are load-bearing and enforced by tests:

- **Labeler ⟂ agent retrieval** — the labeler uses only the keyword sweep, never the agent's FAISS index, so `recall@k` is a real comparison of two independent retrievals.
- **Agent ⟂ rubric** — the rubric goes only into the labeler's prompt; the gpt-5.1 agent never sees it, so it can't grade to the test.

**Honest caveat:** this is **LLM-labeled, not hand-labeled** — a deliberate time-constrained substitution for the proposal's hand-labeled set, and a flagged future-work item. The labeler (GPT-5.5 + rubric) and the agent-under-test (gpt-5.1, no rubric) are *different* models, which reduces — but does not eliminate — model-vs-model circularity.

---

## The gold set (28 claims)

- **Source:** `55_full_run.csv` (gpt-5.5 / prompt v5), `capital_allocation` only.
- **Partition:** excluded every claim the autochecker verdicted (its real Compustat screen) → the agent's true residual, which is **qualitative capex / capacity** commitments.
- **Strengthened** in two passes: (1) drew the bulk from **elapsed-horizon** claims (≤ 2024-12-31) so they can resolve decisively; (2) added the claim's own **facility/proper-noun terms** ("Berlin", "Corpus Christi", "RTP") to the sweep so narrative evidence surfaces. Plus **6 forward claims** (2026–27 horizons) kept on purpose as *not-yet-resolvable controls*.

| Bucket | Count |
|---|---|
| Resolvable, decisive gold (verified / partial) | 13 |
| Forward "too-early" controls (gold = not_yet_resolvable) | 6 |
| Elapsed but genuinely unverifiable from filings | 9 |
| **Total** | **28** (AMZN 10 / TSLA 10 / LLY 6 / KO 2) |

Gold verdict mix: **12 verified, 1 partial, 15 not_yet_resolvable, 0 contradicted.**

---

## Eval results in detail

**Retrieval (recall@8 = 0.75 over 12 decisive claims):** the agent's FAISS retrieval returns the gold-cited filing for most claims; 2 of 12 were complete misses (recall 0). Precision is low (0.33) by construction — the agent returns 8 chunks while gold cites only 1–3 filings.

**Verdict accuracy = 0.56 (15/27), split by claim type:**

| Gold type | Agent verdict accuracy |
|---|---|
| Resolvable (decisive) | 8 / 12 = **0.67** |
| Not-yet-resolvable (forward + hard) | 7 / 15 = 0.47 |
| └ of which: **forward controls** | **3 / 6** correctly abstained |

**The forward-control result is the headline finding.** Those 6 claims have horizons in 2026–27 — no filing could yet confirm them — so any non-`not_yet_resolvable` verdict is the agent **confabulating**. It did so half the time. The agent needs a stronger "is this horizon even resolvable yet?" guard before grading.

**Interpretation caveat (don't over-read the 0.47):** the gold labeler's keyword sweep is *weaker* than the agent's semantic retrieval on narrative claims, so on some elapsed "hard" claims the gold said *not_yet_resolvable* simply because the sweep missed evidence the agent legitimately found. Those count as "disagreements" but may be the **agent being more right than the gold**. The clean, unconfounded signal is the forward controls (no evidence can exist → agent should always abstain).

---

## Limitations (state these in the paper)

1. **LLM-labeled gold**, not human — the central methodological caveat.
2. **Small n** — 12 recall-scored, 27 verdict-scored.
3. **Verdict skew** — these firms executed their capacity plans, so the gold is `verified`-heavy with **0 contradicted**; this eval cannot test the agent's contradiction detection.
4. **Labeler/agent retrieval asymmetry** — keyword sweep vs semantic FAISS; inflates apparent disagreement on narrative claims.

---

## Engineering notes

- New: `src/verifier/autolabel.py` (+ 18 offline tests). CLI: `select` (pick/freeze the residual subset, no LLM) and `label` (GPT-5.5 grading).
- Two verifier robustness fixes the eval surfaced: `EvidenceItem.filing_date` tolerates an unparseable/placeholder date (→ `None`) instead of crashing; `verifier.eval` isolates per-claim agent failures so one bad result doesn't abort the batch.
- **Open follow-up:** the gpt-5.1 structured-output parser intermittently returns an empty/unparseable response (1 claim skipped this run) — worth a retry/repair path.

Artifacts: gold set in `data/gold/auto/`, per-claim scores in `data/eval/per_claim_results.csv`.
