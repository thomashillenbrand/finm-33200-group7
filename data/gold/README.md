# Gold-set labels

Ground truth for evaluating the verification agent. One JSONL row per labeled
claim (a `GoldLabel`). The scorer (`python -m verifier.eval`) reads these files
and compares the agent's output against them.

> **As-built (2026-05-25): the active gold set is LLM-labeled, not hand-labeled.**
> Under time pressure, hand-labeling was replaced by `python -m verifier.autolabel`
> (GPT-5.5 + the rubric, grading over the *same deterministic keyword sweep* a
> human would use — never the agent's FAISS index). It lives in `auto/`. This is
> a flagged shortcoming (see `CLAUDE.md` deliverable #3). The human how-to below
> still documents the schema and the manual path (`verifier.label`), which the
> auto-labeler mirrors.

## What lives here

- `auto/` — the **LLM-labeled** gold set: `auto_<ticker>.jsonl` (labeler tag
  `gpt-5.5`) + `subset_ids.txt`, the pinned/frozen claim subset. **This is what
  the eval scores.** Drawn from the autochecker's cap-alloc residual.
- `template.jsonl` — one example row showing the format.
- `pilot_<ticker>.jsonl` — earlier hand/pilot labels, if any. One file per ticker.
- `README.md` — this file (schema + how-to-label).

Two labeling tools, both agent-independent (keyword sweep, no FAISS): the human
helper `python -m verifier.label` and the LLM `python -m verifier.autolabel`.

The verdict criteria live in [`docs/labeling_rubric.md`](../../docs/labeling_rubric.md)
(now fleshed out) — it defines `verified` vs `partially_verified` vs the
evidenced-non-occurrence `contradicted` rule per claim type.

## How to label one claim

1. Open `data/claims/pilot_claims.csv` and pick a `capital_allocation` claim.
   Note its `claim_id`, `call_date`, and `verbatim_quote`.
2. Open that ticker's filings under `pulled_data/<TICKER>/SEC/` (10-Q, 10-K,
   8-K) filed **after** the call date. The accession-number index is
   `pulled_data/<TICKER>/SEC/<TICKER>_sec_filings_index.parquet`.
3. Find the passage(s) that show whether the claim came true. Copy each into an
   `expected_evidence` entry: its `accession_no`, `form`, `filing_date`, a
   verbatim `quote` (≤500 chars), and an optional `section` pointer.
4. Assign a `verdict` and a `confidence` per `docs/labeling_rubric.md`. Write a
   short `labeler_notes` explaining *why* — this is what calibrates the rubric.
5. Append the row as one line to `pilot_<ticker>.jsonl`.

Label the **evidence and verdict independently of what the agent surfaced** —
do not read the agent's output first. That independence is what makes the
evaluation non-circular (see `CLAUDE.md`, "labeling workflow is load-bearing").

If you genuinely cannot find evidence and the horizon has elapsed, that is a
real signal — label `not_yet_resolvable` with `confidence: low` and say so in
the notes. `not_yet_resolvable` is the only verdict that may carry an empty
`expected_evidence` list.

## Schema (one row = one `GoldLabel`)

| Field | Type | Required | Notes |
|---|---|---|---|
| `claim_id` | str | yes | FK into `data/claims/pilot_claims.csv` |
| `ticker` | str | yes | Denormalized for quick filtering |
| `labeler` | str | yes | Short tag, e.g. `"tom"` |
| `labeled_at` | ISO datetime | yes | When the label was assigned |
| `expected_evidence` | list | yes (may be empty) | Filing excerpts; empty only for `not_yet_resolvable` |
| `expected_evidence[].accession_no` | str | yes | e.g. `"0001564590-20-019931"` |
| `expected_evidence[].form` | str | yes | `10-K`, `10-Q`, or `8-K` |
| `expected_evidence[].filing_date` | ISO date | yes | |
| `expected_evidence[].quote` | str | yes | Verbatim snippet, ≤500 chars |
| `expected_evidence[].section` | str | no | e.g. `"Item 7 — MD&A"` |
| `verdict` | str | yes | `verified` / `partially_verified` / `contradicted` / `not_yet_resolvable` |
| `confidence` | str | yes | `high` / `medium` / `low` (independent of verdict) |
| `labeler_notes` | str | no | Why this verdict — load-bearing for rubric calibration |

The schema is enforced by `src/verifier/gold.py`. Validate a file with:

```bash
mamba run -n truth python -c "from verifier.gold import load_gold_labels; print(len(load_gold_labels('data/gold/pilot_tsla.jsonl')), 'labels OK')"
```

A malformed row fails loudly with its line number — fix it, don't ignore it.
