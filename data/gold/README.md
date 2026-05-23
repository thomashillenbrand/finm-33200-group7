# Gold-set labels

Human-assigned ground truth for evaluating the verification agent. One JSONL
row per labeled claim. The scorer (`python -m verifier.eval`) reads these files
and compares the agent's output against them.

## What lives here

- `template.jsonl` — one example row showing the format. **Do not label into
  this file** — copy its shape into a per-ticker file.
- `pilot_<ticker>.jsonl` — the actual labels (e.g. `pilot_tsla.jsonl`). One file
  per ticker; the scorer merges them.
- `README.md` — this file (schema + how-to-label).

The verdict criteria live separately in [`docs/labeling_rubric.md`](../../docs/labeling_rubric.md).
Read that before labeling — it defines what "verified" vs "partially_verified"
actually means for each claim type.

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
