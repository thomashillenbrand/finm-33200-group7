# finm-33200-group7

Group 7 final project for FINM 33200 — *Generative and Agentic AI for Finance* (Spring 2026).

We are building an agentic system that produces auditable historical *truthfulness profiles* for public companies. The system extracts forward-looking management claims from earnings call transcripts and grades whether each claim was realized by checking the same company's subsequent SEC filings.

See [`CLAUDE.md`](CLAUDE.md) for full project context, [`workplan.md`](workplan.md) for the day-by-day execution plan, and [`proposal_for_submission.md`](proposal_for_submission.md) for the formal scope.

For an end-to-end dataflow walkthrough with diagrams (workstreams A–D,
schemas, module-by-module tour), see [`docs/architecture.md`](docs/architecture.md).

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
│   │   ├── extract.py         # build_extractor, extract_call, filter_unquantified_guidance, dedupe_claims
│   │   ├── output.py          # writes the claims CSV
│   │   └── run.py             # CLI: python -m extractor.run --input ... --output ...
│   ├── verifier/              # workstream C — verification agent (iteration 1: stubbed tools)
│   │   ├── __init__.py        # re-exports the public API
│   │   ├── schema.py          # Pydantic models: Claim, EvidenceItem, EvidenceBundle, Verdict
│   │   ├── corpus.py          # iteration-1 stub: loads canned excerpts from data/stub/
│   │   ├── tools.py           # search_filings tool (stubbed; real EDGAR in iteration 2)
│   │   ├── trace.py           # JSON+Markdown trace writer (adapted from agentic-rag-edgar-demo)
│   │   ├── agent.py           # build_agent, verify, verify_from_dict
│   │   └── run.py             # CLI: python -m verifier.run --claim ... --mode {evidence,verdict}
│   └── autochecker/           # workstream C iter-3 — Compustat-backed numerical grader
│       ├── __init__.py        # package docstring
│       ├── schema.py          # Pydantic: ScreenResult, EvidenceResult, VerdictResult, AutocheckRecord
│       ├── compustat.py       # parquet loader, YTD→quarterly delta, pre/post-call slicing, field codebook
│       ├── prompts.py         # versioned stage-1 + stage-2 prompts (evidence/verdict variants)
│       ├── llm.py             # raw OpenAI SDK structured-output wrapper + rate-limit retry
│       ├── screen.py          # stage 1: Compustat-relevance screen
│       ├── verify.py          # stage 2: verification, citation scrubbing
│       └── run.py             # CLI: python -m autochecker.run --claims ... --mode {evidence,verdict}
├── tests/
│   ├── test_extractor_*.py    # extractor tests: schema, reader, horizon, provenance, filter, dedupe, output, smoke
│   ├── test_schema.py         # verifier Pydantic schema tests
│   ├── test_corpus.py         # verifier stub corpus loader test
│   ├── test_tools.py          # verifier search_filings stub test
│   └── test_smoke.py          # verifier end-to-end live tests (marked `live`; run with `pytest -m live`)
├── data/
│   ├── Transcript/            # interim transcript CSVs (4 firms; superseded by Pulled_data/ parquet)
│   ├── claims/                # extractor output — claims CSVs
│   ├── stub/                  # canned fixtures (example_claim.json + canned_excerpts.json)
│   ├── autochecker/           # autochecker run outputs — per-claim JSONL + flat summary CSV
│   └── traces/                # per-run agent traces (gitignored)
├── pulled_data/               # data_pull output: per-ticker transcripts, Compustat, SEC filings (gitignored)
└── docs/                      # design docs and other supporting material
```

Workstream D (evaluation & writeup) will add its own modules under `src/` as it comes online.

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
transcript, resolves claim time horizons to absolute dates, drops
numerical-guidance claims that state no specific figure, and removes
exact-duplicate claims.

Every claim is classified as either `numerical_guidance` (graded against
Compustat) or `capital_allocation` (share buybacks, dividends, capex, and debt
actions — graded against SEC filings), and carries its verbatim quote, a
paraphrase, provenance (source turn + speaker), and a resolved horizon. By
design the schema holds no verdict or outcome field: the extractor surfaces
claims, the verifier surfaces evidence, and human labelers assign verdicts.

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

Iter-2 verifies **`capital_allocation` claims only**. A `numerical_guidance`
claim raises `UnsupportedClaimTypeError`; Compustat-backed numeric verification
lands in iter 3.

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

The `autochecker` package grades `numerical_guidance` claims against Compustat
quarterly fundamentals — the half of workstream C that iter-2 deferred (iter-2
locked scope to `capital_allocation` against SEC filings and raised
`UnsupportedClaimTypeError` on numerical claims). Two-stage flow per claim:

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

To measure how good the verifier is, we score its output against a hand-labeled
gold set. Two questions, both scored from one artifact:

- **Retrieval quality** — do the agent's cited filings include the ones a human
  labeler marked relevant? (recall@k and precision, at accession-number
  granularity)
- **Verdict accuracy** — in `--mode verdict`, does the agent's verdict match the
  labeler's?

Gold labels live in `data/gold/` as one JSONL row per claim
(`pilot_<ticker>.jsonl`). The schema and how-to-label steps are in
[`data/gold/README.md`](data/gold/README.md); the verdict criteria and
partial-credit policy belong in [`docs/labeling_rubric.md`](docs/labeling_rubric.md)
(stub — a pending team deliverable; read it before labeling once written).
Labelers assign evidence and verdicts **independently of what the agent
surfaced** — that independence is what keeps the evaluation non-circular.

Score a gold file with:

```bash
mamba run -n truth python -m verifier.eval \
    --gold data/gold/pilot_tsla.jsonl \
    --claims data/claims/pilot_claims.csv \
    --mode evidence --k 8
```

The scorer looks up each gold claim in the claims CSV, runs the agent live (the
SQLite chat cache keeps re-scoring cheap), prints summary stats, and writes a
per-claim CSV (default `data/eval/per_claim_results.csv`). Use `--mode verdict`
to also score verdict accuracy. `--gold` accepts a directory of `*.jsonl` files
(per-ticker labels are merged).

## Adding or updating dependencies

`pyproject.toml` is the source of truth. After editing `[project.dependencies]`:

```bash
pip-compile pyproject.toml -o requirements.txt   # regenerate the lock file
pip install -r requirements.txt                  # apply
```

Commit both `pyproject.toml` and `requirements.txt` together.
