# Verifier Iteration 3 — Evaluation Prep (outstanding items)

Most of iter-3 eval-prep has landed on `feature/verifier-iteration3` (PR in review). The full step-by-step for the completed work lives in git history — this doc now tracks only what's left.

**Done & committed:**

| Item | Commit |
|---|---|
| A — `before_date <= after_date` retrieval fix in the search tool | `be557ec` |
| B — gold-label schema + JSONL loader + template (`verifier/gold.py`, `data/gold/`) | `b794a72` |
| D — eval scorer: recall@k, precision, verdict accuracy (`verifier/eval.py`) | `91de3ca` |
| E — per-task model env vars, enforced with no source fallback | `b75963d` |
| F — README + CLAUDE.md docs; open items #2/#3 updated | `060dbbc` |

**Conventions for the work below:** `truth` mamba env (`mamba run -n truth …`); bare commit messages (no attribution footer); the user owns all git writes (pause and ask before committing).

---

## Outstanding

### 1. Labeling rubric — team deliverable (was Task C, deferred)

`docs/labeling_rubric.md` exists but is an **empty stub**. It is the real prerequisite for *consistent* labels and is owned by the team (domain judgment), not the engineering stream. It must define:

- **Verdict buckets** — `verified` / `partially_verified` / `contradicted` / `not_yet_resolvable`, with the line between them.
- **Partial-credit policy for `capital_allocation`** — concrete rules per sub-kind: buyback, dividend, capex, debt. The motivating question (CLAUDE.md open item #3): "announced \$1B buyback over 12mo → executed \$700M in 12mo → partial or full?"
- **A few worked TSLA/AMZN examples** so labelers calibrate against real cases.
- **Independence reminder** — the rubric is for humans reading evidence; it must not be loaded into the agent's context (would defeat the labeling-circularity guarantee).

Tracks CLAUDE.md open items #3 and #4.

### 2. Labeling helper — design ready, unbuilt

`docs/labeling-helper-design.md` specs an agent-free CLI (`verifier.label`) that surfaces candidate filings + keyword matches so a human can assemble gold rows quickly, without contaminating the eval. Tasks 1–5 are checkbox-tracked there. It **accelerates** the sprint below but is not a hard blocker — a labeler can work from `data/gold/README.md` by hand.

### 3. Pilot labeling sprint — the actual milestone

This produces the first "is the verifier any good?" numbers. Everything above is scaffolding for it.

1. **Pick the pilot subset** — ~15–20 `capital_allocation` claims from `data/claims/pilot_claims.csv`, TSLA-only (the only smoke-validated index). Human picks; not a code task.
2. **Label them independently of the agent** → `data/gold/pilot_tsla.jsonl`. Schema + how-to in `data/gold/README.md`; verdict criteria in `docs/labeling_rubric.md` (once written).
3. **Score** — the scorer runs the agent live per gold claim and reports recall@k / precision / verdict accuracy:
   ```bash
   mamba run -n truth python -m verifier.eval \
       --gold data/gold/pilot_tsla.jsonl \
       --claims data/claims/pilot_claims.csv \
       --mode evidence --k 8
   ```
   (Add `--mode verdict` to also score verdict accuracy.)
4. **Iterate** — fix what the scorer reveals. Likely candidates: chunker tweaks, prompt adjustments, or the iter-3 robustness backlog in `docs/future_optimizations.md` (rate-limit/retry, SQLite cache fragility, `datetime.utcnow()` deprecation). That iteration loop is iter-3's *next* plan, written after the first scorer output — not this doc.
