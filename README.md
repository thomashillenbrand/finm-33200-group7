# finm-33200-group7

Group 7 final project for FINM 33200 — *Generative and Agentic AI for Finance* (Spring 2026).

We are building an agentic system that produces auditable historical *truthfulness profiles* for public companies. The system extracts forward-looking management claims from earnings call transcripts and grades whether each claim was realized by checking the same company's subsequent SEC filings.

See [`CLAUDE.md`](CLAUDE.md) for full project context, [`workplan.md`](workplan.md) for the day-by-day execution plan, and [`proposal_for_submission.md`](proposal_for_submission.md) for the formal scope.

For an end-to-end dataflow walkthrough with diagrams (workstreams A–D,
schemas, module-by-module tour), see [`docs/architecture.md`](docs/architecture.md).

**To reproduce the full pipeline from scratch**, see [`docs/pipeline.md`](docs/pipeline.md) — nine steps with exact CLI commands, from data pull to final evaluation.

**To view results**, open [`data/profiles/dashboard.html`](data/profiles/dashboard.html) in a browser, or run `streamlit run src/profiles/app.py`, or open [`notebooks/results.ipynb`](notebooks/results.ipynb).

New to git, or want a quick reference for our branch-and-PR workflow? See [`GIT_CHEATSHEET.md`](GIT_CHEATSHEET.md).

## Project structure

```
finm-33200-group7/
├── pyproject.toml             # PEP 621 metadata + project dependencies
├── requirements.txt           # pip-compile output, locked
├── environment.yml            # mamba env spec (python=3.12, pip-tools)
├── .env.example               # template for API keys and other settings
├── src/
│   ├── data_pull.py           # workstream A — single-file CLI: WRDS transcripts + Compustat quarterly + SEC EDGAR filings, per ticker
│   ├── extractor/             # workstream B — claim extraction pipeline
│   │   ├── __init__.py        # re-exports the public API
│   │   ├── schema.py          # Pydantic models: Claim, ExtractedClaim, ExtractionResponse
│   │   ├── reader.py          # loads transcript parquet, groups turns into earnings calls
│   │   ├── horizon.py         # resolves claim time horizons to absolute dates
│   │   ├── prompt.py          # extraction system prompt + few-shot examples
│   │   ├── provenance.py      # matches an extracted quote back to its source turn
│   │   ├── extract.py         # build_extractor, extract_call, filter_unquantified_guidance, filter_unresolved_horizon, dedupe_claims
│   │   ├── output.py          # writes the claims CSV
│   │   └── run.py             # CLI: python -m extractor.run --input ... --output ...
│   ├── verifier/              # workstream C — verification agent (real EDGAR retrieval + FAISS)
│   |   ├── __init__.py        # re-exports the public API
│   |   ├── schema.py          # Pydantic models: Claim, EvidenceItem, EvidenceBundle, Verdict
│   |   ├── index.py           # offline indexer: chunk + embed SEC HTML → chunks.parquet (+ report_date) + faiss.index
│   |   ├── corpus.py          # SearchIndex: FAISS query, call-date floor + reportDate horizon ceiling
│   |   ├── tools.py           # per-claim search_filings tool (ticker/after_date/horizon_end closed over)
│   |   ├── trace.py           # JSON+Markdown trace writer (adapted from agentic-rag-edgar-demo)
│   |   ├── agent.py           # build_agent, verify (allow_unsupported), coverage context, evidence net, parser repair
│   |   ├── label.py           # human gold-set helper: deterministic keyword sweep (agent-independent)
│   |   ├── autolabel.py       # GPT-5.5 gold-set auto-labeler: select/label CLIs, reuses label.py's sweep
│   |   ├── gold.py            # GoldLabel / GoldEvidence schema + JSONL loader
│   |   ├── eval.py            # scorer: recall@k / precision / verdict accuracy; per-run records (git_head)
│   |   └── run.py             # CLI: python -m verifier.run --claim ... --mode {evidence,verdict}
│   ├── autochecker/           # workstream C iter-3 — Compustat-backed numerical grader
│   │   ├── __init__.py        # package docstring
│   │   ├── schema.py          # Pydantic: ScreenResult, EvidenceResult, VerdictResult, AutocheckRecord
│   │   ├── compustat.py       # parquet loader, YTD→quarterly delta, pre/post-call slicing, field codebook
│   │   ├── prompts.py         # versioned stage-1 + stage-2 prompts (evidence/verdict variants)
│   │   ├── llm.py             # raw OpenAI SDK structured-output wrapper + rate-limit retry
│   │   ├── screen.py          # stage 1: Compustat-relevance screen
│   │   ├── verify.py          # stage 2: verification, citation scrubbing
│   │   └── run.py             # CLI: python -m autochecker.run --claims ... --mode {evidence,verdict}
│   └── profiles/              # workstream D — results visualisation + dashboard
│       ├── __init__.py
│       ├── build_profiles.py  # CLI: python -m profiles.build_profiles → per-firm CSVs
│       ├── dashboard.py       # generates the interactive Plotly HTML dashboard
│       └── app.py             # Streamlit app: streamlit run src/profiles/app.py
├── notebooks/
│   └── results.ipynb          # end-to-end results walkthrough with all charts inline
├── tests/
│   ├── test_extractor_*.py    # extractor tests: schema, reader, horizon, provenance, filter, dedupe, context, output, smoke
│   ├── test_schema.py         # verifier Pydantic schema tests
│   ├── test_corpus.py         # verifier stub corpus loader test
│   ├── test_tools.py          # verifier search_filings stub test
│   └── test_smoke.py          # verifier end-to-end live tests (marked `live`; run with `pytest -m live`)
├── data/
│   ├── Transcript/            # interim transcript CSVs (4 firms; superseded by Pulled_data/ parquet)
│   ├── claims/                # extractor output — claims CSVs (e.g. 55_full_run.csv)
│   ├── gold/                  # gold labels; gold/auto/ = LLM-labeled subset + pinned subset_ids.txt
│   ├── eval/                  # eval output: per_claim_results.csv + runs/<ts>_<label>/ run records
│   ├── verdicts/              # combined verdicts (combined_55_final.csv) + agent residual JSONL
│   ├── stub/                  # canned fixtures (example_claim.json + canned_excerpts.json)
│   ├── autochecker/           # autochecker run outputs — per-claim JSONL + flat summary CSV
│   ├── profiles/              # per-firm profile CSVs, summary.csv, dashboard HTML
│   └── traces/                # per-run agent traces (gitignored)
├── pulled_data/               # data_pull output: per-ticker transcripts, Compustat, SEC filings (gitignored)
└── docs/                      # design docs and other supporting material
```

## Setup

Prerequisites: [mamba](https://mamba.readthedocs.io/) (or conda), an OpenAI API key, and a WRDS account.

```bash
# 1. Create the environment (default name: truth — pass -n <other> to override)
mamba env create -f environment.yml
mamba activate truth

# 2. Install locked Python dependencies
pip install -r requirements.txt              # locked runtime install

# 3. Editable install of the project's source packages
pip install -e ".[dev]"                      # editable install + dev tools (pytest, pip-tools)

# 4. Configure secrets
cp .env.example .env
#    then edit .env and set:
#      OPENAI_API_KEY — required for the extractor and verifier
#      WRDS_USERNAME  — required for `python -m data_pull` (workstream A)
```

### Quick smoke test

Once setup is complete, confirm everything is wired up:

````bash
# Fast unit tests (no API calls)
pytest -v

# End-to-end smoke tests (require OPENAI_API_KEY in .env; live OpenAI calls)
pytest -m live -v

# Run the verification agent on the stub claim
python -m verifier.run --claim data/stub/example_claim.json --mode evidence
python -m verifier.run --claim data/stub/example_claim.json --mode verdict
````

If `pytest -v` is all green and `python -m verifier.run` produces an
`EvidenceBundle` JSON dump, the scaffold is healthy. Traces from each run
land in `data/traces/` (gitignored).

## Data pulls (workstream A)

`src/data_pull.py` is a single-file CLI that, for one ticker, downloads
everything we need from external sources into a per-ticker tree under
`pulled_data/`:

- earnings-call transcript metadata + full text from WRDS Capital IQ
  (`ciq_transcripts.*`) → parquet
- Compustat quarterly fundamentals (`comp.fundq`, 80-ish fields covering
  balance sheet / income statement / cash flow / market) → parquet
- SEC EDGAR primary documents for 10-K, 10-Q, 8-K, plus a parquet index
  of all filings → HTML files + parquet

Run it once per ticker:

```bash
python -m data_pull AMZN --start 2018-01-01
python -m data_pull TSLA --start 2018-01-01
python -m data_pull KO   --start 2018-01-01
python -m data_pull LLY  --start 2018-01-01
```

Each invocation is idempotent — files that already exist are skipped, so
re-running only fetches new filings. The CLI loads `WRDS_USERNAME` from
the project-root `.env`; SEC requests use a `User-Agent` from
`SEC_USER_AGENT` (override in `.env` if you want your email on it).

Output layout for ticker `XXX`:

```
pulled_data/XXX/
├── transcript/   # XXX_metadata.parquet + XXX_transcripts.parquet
├── Compustat/    # XXX_compustat_quarterly.parquet
└── SEC/
    ├── 10-K/...  # primary documents (HTML)
    ├── 10-Q/...
    ├── 8-K/...
    └── XXX_sec_filings_index.parquet
```

`pulled_data/` is gitignored — every collaborator pulls their own copy.

Caveat: cash-flow columns in `comp.fundq` (`capxy`, `dvy`, `dltisy`,
`dltry`, `prstkcy`, etc.) are reported year-to-date. Take first
differences within each fiscal year to recover per-quarter values.

## Claim extraction (workstream B)

The `extractor` package turns the WRDS transcript parquet written by
`data_pull.py` into a CSV of typed, forward-looking management claims for
workstreams C and D to consume. Capital IQ stores each call as several
transcript versions, so the reader first keeps only the final, proofed copy of
each call. For every earnings call it then makes one OpenAI structured-output
request, recovers each claim's source turn by matching the quote back to the
transcript, resolves claim time horizons to absolute dates (absolute and
relative phrasings, plus bare quarters like `Q2` and bare months like `by the
end of March`), drops numerical-guidance claims that state no specific figure,
prunes any claim whose horizon could not be resolved to an end date, and
removes exact-duplicate claims.

Every claim is classified as either `numerical_guidance` (graded against
Compustat) or `capital_allocation` (share buybacks, dividends, capex, and debt
actions — graded against SEC filings), and carries its verbatim quote, a
paraphrase, provenance (source turn + speaker), a resolved horizon, and a
`source_context` field (the source turn plus the turn immediately before it,
so a sparse quote can be read in context). By design the schema
holds no verdict or outcome field: the extractor surfaces claims, the verifier
surfaces evidence, and human labelers assign verdicts.

Run it with the CLI:

```bash
# 5-call pilot on one firm
python -m extractor.run \
    --input Pulled_data/TSLA/transcript/TSLA_transcripts.parquet \
    --output data/claims/pilot_claims.csv --limit 5

# full run over every transcript parquet under a directory
python -m extractor.run --input Pulled_data --output data/claims/all_claims.csv

# override the model (default: openai:gpt-4o-mini)
python -m extractor.run --input ... --output ... --model openai:gpt-5.5
```

The CLI loads `OPENAI_API_KEY` from `.env` automatically. Each run prints a
per-call claim count and a summary (type breakdown, provenance split, horizon
resolution) and writes one row per claim to the output CSV in `data/claims/`.

## Verification — iter-2 real EDGAR retrieval (workstream C)

Iter-1 ran the agent against canned excerpts. Iter-2 runs it against the four
firms' actual SEC filings via a local FAISS index, with the load-bearing
labeling guarantee preserved: in `--mode evidence` the agent returns cited
excerpts without proposing a verdict.

> **iter-3 update (2026-05-24) — claim-horizon time window.** The agent's
> filing search is now bounded at *both* ends, enforced at the tool layer (the
> LLM has no date argument to set): floored at the call date (never a filing
> from before the claim) and ceilinged at the claim's resolved horizon. The
> ceiling is keyed on each filing's **reporting period** (`reportDate`), not its
> filing date — so a late-filed annual 10-K (filed in February but covering the
> prior Dec 31) is still graded against an annual claim. This replaces the old
> LLM-visible `before_date` argument and adds a `report_date` column to
> `chunks.parquet`; **indexes built before this change must be rebuilt** (see
> below). A claim with no resolved horizon (`horizon_end_date` null) would have
> no ceiling — but as of 2026-05-24 the extractor prunes such claims upstream
> (`filter_unresolved_horizon`), so the verifier no longer receives one.

### Prerequisites

Pull SEC filings + Compustat for the four firms (one-time, ~10–30 min total):

```bash
mamba run -n truth python -m data_pull TSLA --start 2018-01-01
mamba run -n truth python -m data_pull AMZN --start 2018-01-01
mamba run -n truth python -m data_pull KO   --start 2018-01-01
mamba run -n truth python -m data_pull LLY  --start 2018-01-01
```

Output lives under `pulled_data/<TICKER>/` (gitignored).

### Build the search indexes

```bash
mamba run -n truth python -m verifier.index --all          # all four tickers
mamba run -n truth python -m verifier.index TSLA           # one ticker
mamba run -n truth python -m verifier.index TSLA --refresh # full rebuild
```

Output: `pulled_data/<TICKER>/index/chunks.parquet` and `faiss.index`.
Idempotent — re-running on an unchanged corpus is a no-op (only new accession
numbers get re-embedded).

`chunks.parquet` carries a `report_date` column (the filing's reporting period,
used for the horizon ceiling). Re-running the indexer **backfills it onto an
existing index for free** — no re-embedding, since chunk IDs are
date-independent. If `SearchIndex.load` raises `IndexCorruptError` about a
missing `report_date` column, your index predates the horizon change; just
re-run `python -m verifier.index --all`.

### Run the verifier

```bash
mamba run -n truth python -m verifier.run --claim path/to/claim.json --mode evidence
mamba run -n truth python -m verifier.run --claim path/to/claim.json --mode verdict
mamba run -n truth python -m verifier.run --claim path/to/claim.json --mode evidence --no-cache
```

Each run also writes a structured trace (`.json` + human-readable `.md`) under
`data/traces/`.

### Caching

Two layers:

- **Document embeddings** — persisted in `pulled_data/<TICKER>/index/faiss.index`
  and `chunks.parquet`. Incremental: re-running the indexer only embeds
  accession numbers absent from the existing index.
- **Chat completions** — SQLite-cached at `pulled_data/.cache/llm_cache.sqlite`
  via `langchain_community.cache.SQLiteCache`. **On by default.** Pass
  `--no-cache` on the CLI to bypass for a single run.

> **Troubleshooting — stale-cache crash.** Cache entries are keyed on the
> prompt + model, not on the structured-output schema. If you edit the
> `EvidenceBundle`/`Verdict` schema (or the parser prompt) and then re-run a
> claim you've run before, a cache *hit* can fail to deserialize with
> `ValueError: ... does not have a 'parsed' field`. Fix: re-run with
> `--no-cache`, or delete `pulled_data/.cache/llm_cache.sqlite` to start fresh.

Query embeddings (one per `search_filings` call) are not separately cached;
they're recomputed each time. This is a known iter-3 backlog item — see
`docs/future_optimizations.md`.

### Scope

The verifier's *validated* scope is **`capital_allocation` claims only** — a
`numerical_guidance` claim raises `UnsupportedClaimTypeError` by default
(Compustat-backed numeric verification is the `autochecker`'s job, below). For
the cascade's fall-through run we override that gate with
`verify(..., allow_unsupported=True)` so the agent grades any claim type the
autochecker screened out; **verdicts on non-cap-alloc claims are UNVALIDATED**
(the gold set is cap-alloc only) and are tagged `validated=False` in the output.

### Model selection

Every model identifier is supplied by a per-task env var — there is **no
hardcoded fallback in the source**, so the var must be set (the resolver raises
a `RuntimeError` naming the missing var otherwise). `cp .env.example .env` ships
working values; change any one to A/B a different model for that stage. They are
read at use time, so a change takes effect on the next run.

| Env var | Stage |
|---|---|
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
