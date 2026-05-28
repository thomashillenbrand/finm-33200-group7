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
<<<<<<< Updated upstream
| `EXTRACTOR_MODEL` | Claim extraction (`extractor`) |
| `VERIFIER_AGENT_MODEL` | Tool-using verifier agent |
| `VERIFIER_PARSER_MODEL` | Verdict-mode structured-output parser |
| `EMBEDDING_MODEL` | FAISS document + query embeddings |

The extractor additionally honors `--model` / `model_name=`, which wins over
`EXTRACTOR_MODEL`. `.env.example` is the canonical list.

## Compustat verification (workstream C, iter-3)

The `autochecker` package grades the extracted claims against Compustat
quarterly fundamentals. Two-stage flow per claim:

- **Stage 1 — screen.** One LLM call asks: does this claim assert a direction
  or magnitude about a figure that appears in Compustat? A codebook of 39
  fields (revenue, income, balance-sheet items, plus per-quarter deltas
  derived from the YTD cash-flow columns) is included in the prompt. Returns
  `is_compustat_relevant`, `candidate_fields`, `assertion_kind`, and a one-
  sentence reasoning. Operational / qualitative claims are filtered here.
- **Stage 2 — verify.** For claims the screen accepted *and* that carry a
  resolved `horizon_end_date`, the loader builds a panel slice
  (`call_date < datadate ≤ horizon_end_date`) plus four pre-call quarters as
  a YoY baseline, projects down to the stage-1 candidate fields, and asks
  the LLM to either surface citations + a neutral comparison paragraph
  (`--mode evidence`, default) or to also emit a verdict label
  (`--mode verdict`). Citations are scrubbed against the actual sliced panel
  so hallucinated `(datadate, field)` pointers are dropped before write.

The package uses the **raw OpenAI SDK** (`client.beta.chat.completions.parse`
with Pydantic schemas), not LangChain — autochecker has no agent loop or
chat-completion cache to integrate with, and skipping the LangChain layer
keeps it runnable inside the `sec_filings` conda env without extra installs.
Model id is read from `VERIFIER_AGENT_MODEL` in `.env` (the `openai:` prefix
is stripped automatically, so the same value works across stages).

### Run it

```bash
# default: evidence mode on the full 590-claim pilot
python -m autochecker.run --claims data/claims/51_full_run.csv

# verdict mode (opt-in — see caveat below)
python -m autochecker.run --claims data/claims/51_full_run.csv --mode verdict

# smoke run: first N claims, single ticker
python -m autochecker.run --claims data/claims/51_full_run.csv \
    --mode evidence --tickers TSLA --limit 5
```

Each run writes two files under `data/autochecker/`:

- `<stem>_<mode>_autochecker-v1.jsonl` — one JSON object per claim with the
  full stage-1 result, the stage-2 evidence/verdict payload, and the model
  + mode used. This is the audit artifact.
- `<stem>_<mode>_autochecker-v1.csv` — a flat per-claim summary (no
  citations, no reasoning text) for spreadsheet inspection.

The CLI prints per-claim progress (`[i/N] <claim_id> (TICKER) -> screen=...
stage2=...`) and is idempotent at the level of the output files (re-running
overwrites).

### Time-leak guarantee

Stage 2's slicer applies a strict `>` cutoff on `datadate` against the call
date, so the LLM never sees a Compustat row that ended on or before the
call. Four pre-call quarters are included separately and clearly labelled
as "base period" in the prompt — they were already public when the claim
was made, so surfacing them as a YoY baseline is not a time leak.

### Caveats

- **`--mode verdict` is opt-in for a reason.** Structured-output runs
  occasionally have the model's free-text `reasoning` field disagree with
  the structured `verdict` field (e.g. reasoning concludes "partially_verified"
  while `verdict` emits "verified"). Spot-check `reasoning` before trusting
  the labels, and do **not** feed `data/autochecker/*verdict*` into gold-set
  labeling without a hand-audit.
- The load-bearing labeling pattern (agent surfaces evidence, humans assign
  verdicts) means `--mode evidence` is the default for a reason — keep it
  unless you explicitly need labels.
- Claims with `horizon_end_date` missing are skipped at stage 2 with
  `skipped_reason="no_horizon"` rather than guessed; this avoids judging a
  claim against an arbitrary window.

## Gold-set evaluation (workstream D)

To measure how good the verifier is, we score its output against 'gold set'. Instead of hand-labeling as origianlly planned, we use the same output from gpt-5.5 as the gold set.

Gold labels live in `data/gold/` as one JSONL row per claim. The schema is in
[`data/gold/README.md`](data/gold/README.md); the verdict criteria + partial-credit
policy are in [`docs/labeling_rubric.md`](docs/labeling_rubric.md). The agent
surfaces evidence **without proposing a verdict**, and the labeler assigns the
verdict independently.

**Gold-set labeling — auto-labeled (2026-05-25).** Hand-labeling was replaced,
under time pressure, by an LLM labeler: `python -m verifier.autolabel` runs
**GPT-5.5 + the rubric** over the *same deterministic keyword sweep* the human
helper uses (never the agent's FAISS index, and the graded agent never sees the
rubric — so the recall@k and rubric-independence guarantees hold). This is
LLM-led, **not** hand-labeled — a flagged shortcoming (see `CLAUDE.md`
deliverable #3). Two subcommands:

```bash
# select + freeze the residual subset (no LLM): cap-alloc claims the autochecker
# screened out, biased to elapsed horizons + a few forward "not-yet-resolvable" controls
mamba run -n truth python -m verifier.autolabel select \
    --claims data/claims/55_full_run.csv --out data/gold/auto/subset_ids.txt \
    --exclude-checked data/autochecker/55_full_run_verdict_autochecker-v1.jsonl \
    --elapsed-by 2024-12-31 --forward-per-ticker 2
# label the frozen subset with GPT-5.5 (needs GOLD_LABELER_MODEL in .env)
mamba run -n truth python -m verifier.autolabel label \
    --claims data/claims/55_full_run.csv --claim-ids data/gold/auto/subset_ids.txt \
    --gold-dir data/gold/auto
```

Score a gold file/dir with:

```bash
mamba run -n truth python -m verifier.eval \
    --gold data/gold/auto --claims data/claims/55_full_run.csv \
    --mode verdict --k 8 --no-cache --run-label discipline-pass
```

The scorer looks up each gold claim in the claims CSV, runs the agent live,
prints summary stats, and writes a per-claim CSV (`--output`, default
`data/eval/per_claim_results.csv`). `--gold` accepts a directory of `*.jsonl`
(merged). **Each run is also saved individually** under
`data/eval/runs/<timestamp>_<label>/` (`per_claim.csv` + `summary.json` +
`meta.json` with the `git_head`) — set `--run-label` / `--runs-dir`. This makes
iterations comparable and a regression revertable to a known commit. Use
`--no-cache` when a prompt changed so the agent re-runs instead of replaying
cached completions. See [`docs/autolabel-eval-summary.md`](docs/autolabel-eval-summary.md)
for the eval narrative (baseline → discipline pass → trace review → citation attempt).

**Cascade / residual verdicts.** In production the autochecker grades what
Compustat can; the agent grades the rest (`is_compustat_relevant: false`). Agent
verdicts over that residual (all claim types) are captured in
`data/verdicts/agent_screenfalse_55.jsonl`. These two halves are merged into
`data/verdicts/combined_55_final.csv`, which drives the dashboard and notebook.

## Results & Visualization (workstream D)

The `profiles` package assembles the combined verdict CSV into an interactive
dashboard. Two ways to view results:

| Method | Command | Output |
|---|---|---|
| Per-firm profiles | `python -m profiles.build_profiles` | `data/profiles/<TICKER>_profile.csv` + `summary.csv` |
| Streamlit app | `streamlit run src/profiles/app.py` | Live app on `localhost:8501` |
| Jupyter notebook | `jupyter notebook notebooks/results.ipynb` | All charts inline with narrative |

All three read from `data/verdicts/combined_55_final.csv` (the merged autochecker +
agent output) and `data/claims/55_full_run.csv`.

### Per-firm profile CSVs (`python -m profiles.build_profiles`)

The primary structured deliverable — one CSV per firm with every claim, its
verdict, and the grader's reasoning:

```bash
python -m profiles.build_profiles   # uses default paths, writes to data/profiles/
```

Output files:

| File | Contents |
|---|---|
| `data/profiles/AMZN_profile.csv` | 116 claims — Amazon |
| `data/profiles/KO_profile.csv` | 123 claims — Coca-Cola |
| `data/profiles/LLY_profile.csv` | 151 claims — Eli Lilly |
| `data/profiles/TSLA_profile.csv` | 61 claims — Tesla |
| `data/profiles/summary.csv` | Aggregate truth scores across all four firms |

Each profile CSV has columns: `claim_id`, `company`, `ticker`, `call_date`,
`fiscal_period`, `claim_type`, `speaker_name`, `verbatim_quote`, `summary`,
`horizon_raw`, `horizon_end_date`, `verdict`, `grader` (autochecker or agent),
`reasoning` (grader's explanation).

### Streamlit app (`src/profiles/app.py`)

Renders the same HTML dashboard inside a full-screen Streamlit iframe. Useful
for sharing a live view with teammates:

```bash
streamlit run src/profiles/app.py
```

The app caches the dashboard build with `@st.cache_data`, so reloads are fast
after the first build.

### Jupyter notebook (`notebooks/results.ipynb`)

A narrative walkthrough: pipeline overview, per-company stats table, all charts
inline, and the agent eval metrics (recall@8, precision, verdict accuracy). Run
top-to-bottom with the `truth` conda env active.

## Adding or updating dependencies

`pyproject.toml` is the source of truth. After editing `[project.dependencies]`:

```bash
pip-compile pyproject.toml -o requirements.txt   # regenerate the lock file
pip install -r requirements.txt                  # apply
```

Commit both `pyproject.toml` and `requirements.txt` together.
=======
| `data/claims/55_full_run.csv` | 539 extracted claims (GPT-5.5, prompt v5) |
| `data/autochecker/55_full_run_verdict_autochecker-v1.csv` | Compustat verdicts |
| `data/verdicts/agent_screenfalse_55.jsonl` | Agent verdicts for remaining claims |
| `data/verdicts/combined_55_final.csv` | Final merged verdicts (451 claims) |
| `data/profiles/` | 7 visualization charts |
| `data/gold/auto/` | Auto-labeled gold set (28 claims, GPT-5.5 + rubric) |
| `data/eval/runs/` | Evaluation run records (recall, precision, verdict accuracy) |
| `notebooks/results.ipynb` | Full results notebook |
>>>>>>> Stashed changes
