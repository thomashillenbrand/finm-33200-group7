# End-to-End Pipeline — How to Run Everything

This document describes how to reproduce the full results from scratch.
Each step is independent and idempotent — re-running a step that already
has output on disk is safe (it will skip or overwrite in place).

All commands assume you are in the repo root and using the `truth` conda env:

```
cd finm-33200-group7
```

---

## Prerequisites

1. Copy `.env.example` to `.env` and fill in your keys:

```
OPENAI_API_KEY=sk-...
WRDS_USERNAME=your_wrds_username
SEC_USER_AGENT="Your Name your@email.com"
EXTRACTOR_MODEL=openai:gpt-4o-mini
VERIFIER_AGENT_MODEL=openai:gpt-4o-mini
VERIFIER_PARSER_MODEL=openai:gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small
```

2. Install dependencies:

```
pip install -r requirements.txt
```

---

## Step 1 — Pull data (Workstream A)

Downloads WRDS transcripts, SEC filings (10-K/10-Q/8-K), and Compustat
fundamentals for each ticker into `Pulled_data/<TICKER>/`.

```
python -m data_pull AMZN --start 2018-01-01
python -m data_pull TSLA --start 2018-01-01
python -m data_pull KO   --start 2018-01-01
python -m data_pull LLY  --start 2018-01-01
```

Output layout:
```
Pulled_data/<TICKER>/
  transcript/   WRDS transcript parquet
  SEC/          10-K, 10-Q, 8-K HTML files + filings index parquet
  Compustat/    quarterly fundamentals parquet
```

---

## Step 2 — Extract claims (Workstream B)

Reads the transcript parquets and produces a CSV of typed forward-looking
claims. Uses GPT-5.5 by default (set `EXTRACTOR_MODEL` in `.env`).

```
python -m extractor.run \
    --input Pulled_data/ \
    --output data/claims/55_full_run.csv
```

To run on a single ticker or limit the number of calls (for testing):

```
python -m extractor.run \
    --input Pulled_data/TSLA/transcript/TSLA_transcripts.parquet \
    --output data/claims/tsla_test.csv \
    --limit 5
```

The output CSV contains one row per claim with: `claim_id`, `ticker`,
`company`, `call_date`, `claim_type`, `verbatim_quote`, `summary`,
`horizon_raw`, `horizon_period`, `horizon_end_date`, `speaker_name`.

---

## Step 3 — Build the FAISS search index (Workstream C)

Chunks and embeds all SEC filings for fast retrieval by the verifier agent.
Only needs to run once per ticker (or after new filings are pulled).

```
python -m verifier.index --all
```

To rebuild a single ticker from scratch:

```
python -m verifier.index TSLA --refresh
```

Output: `Pulled_data/<TICKER>/index/chunks.parquet` and `faiss.index`.

---

## Step 4 — Run the Compustat autochecker (Workstream C)

Grades numerical guidance claims against Compustat quarterly data.
Runs in two stages: (1) screens whether the claim maps to a Compustat
field, (2) compares against the actual realized figures.

```
python -m autochecker.run \
    --claims data/claims/55_full_run.csv \
    --mode verdict \
    --output data/autochecker/55_full_run_verdict_autochecker-v1.csv
```

Claims the autochecker cannot resolve (non-Compustat, or no data available)
are left with an empty verdict and passed to the agent in Step 5.

---

## Step 5 — Run the verifier agent (Workstream C)

Grades capital-allocation claims (and any numerical claims not resolved by
the autochecker) using agentic SEC-filings retrieval.

Run against all claims not resolved by the autochecker:

```
python -m verifier.run \
    --claims data/claims/55_full_run.csv \
    --autochecker-results data/autochecker/55_full_run_verdict_autochecker-v1.csv \
    --mode verdict \
    --output data/verdicts/agent_screenfalse_55.jsonl
```

To run a single claim for inspection:

```
python -m verifier.run \
    --claim data/stub/smoke_0.json \
    --mode evidence
```

---

## Step 6 — Combine verdicts

Merge the autochecker and agent outputs into one final verdicts file.
The autochecker takes priority; the agent fills in what is left.

```python
import pandas as pd, json

ac = pd.read_csv('data/autochecker/55_full_run_verdict_autochecker-v1.csv')
ac_resolved = ac[ac['verdict'].isin(
    ['verified','partially_verified','contradicted','not_yet_resolvable']
)]
ac_resolved['source'] = 'autochecker'

with open('data/verdicts/agent_screenfalse_55.jsonl') as f:
    agent_rows = [json.loads(l) for l in f if l.strip()]
agent = pd.DataFrame(agent_rows)[['claim_id','ticker','verdict']]
agent['source'] = 'agent'

combined = pd.concat([
    ac_resolved[['claim_id','ticker','call_date','claim_type','verdict','source']],
    agent,
], ignore_index=True).drop_duplicates(subset='claim_id', keep='first')

combined.to_csv('data/verdicts/combined_55_final.csv', index=False)
```

Or run `python src/profiles/combine_verdicts.py` once that script exists.

---

## Step 7 — Generate visualizations

Produces 7 charts in `data/profiles/`:

```
python -m profiles.visualize \
    --verdicts data/verdicts/combined_55_final.csv \
    --claims   data/claims/55_full_run.csv \
    --out      data/profiles/
```

Charts produced:
- `01_overview_donuts.png` — truth score per company
- `02_company_verdict_bars.png` — stacked verdict breakdown
- `03_claim_type_breakdown.png` — numerical vs capital allocation
- `04_truth_score_over_time.png` — year-by-year trend
- `05_heatmap_company_year.png` — company x year grid
- `06_overall_verdict_counts.png` — total verdict distribution
- `07_score_comparison.png` — ranked comparison with confidence intervals

---

## Step 8 — View results notebook

Open the results notebook for an interactive walkthrough of all findings:

```
jupyter notebook notebooks/results.ipynb
```

---

## Step 9 — Run the evaluation (optional)

Score the agent against the auto-labeled gold set:

```
python -m verifier.eval \
    --gold data/gold/auto/ \
    --claims data/claims/55_full_run.csv \
    --mode verdict \
    --k 8
```

Results are written to `data/eval/runs/<timestamp>/`.

---

## Summary of outputs

| Path | What it is |
|---|---|
| `data/claims/55_full_run.csv` | 539 extracted claims (GPT-5.5, prompt v5) |
| `data/autochecker/55_full_run_verdict_autochecker-v1.csv` | Compustat verdicts |
| `data/verdicts/agent_screenfalse_55.jsonl` | Agent verdicts for remaining claims |
| `data/verdicts/combined_55_final.csv` | Final merged verdicts (451 claims) |
| `data/profiles/` | 7 visualization charts |
| `data/gold/auto/` | Auto-labeled gold set (28 claims, GPT-5.5 + rubric) |
| `data/eval/runs/` | Evaluation run records (recall, precision, verdict accuracy) |
| `notebooks/results.ipynb` | Full results notebook |
