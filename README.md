# finm-33200-group7

Group 7 final project for FINM 33200 — *Generative and Agentic AI for Finance* (Spring 2026).

We are building an agentic system that produces auditable historical *truthfulness profiles* for public companies. The system extracts forward-looking management claims from earnings call transcripts and grades whether each claim was realized by checking the same company's subsequent SEC filings.

See [`CLAUDE.md`](CLAUDE.md) for full project context, [`workplan.md`](workplan.md) for the day-by-day execution plan, and [`proposal_for_submission.md`](proposal_for_submission.md) for the formal scope.

## Project structure

```
finm-33200-group7/
├── pyproject.toml             # PEP 621 metadata + project dependencies
├── requirements.txt           # pip-compile output, locked
├── environment.yml            # mamba env spec (python=3.12, pip-tools)
├── .env.example               # template for API keys and other settings
├── src/
│   ├── extractor/             # workstream B — claim extraction pipeline
│   │   ├── __init__.py        # re-exports the public API
│   │   ├── schema.py          # Pydantic models: Claim, ExtractedClaim, ExtractionResponse
│   │   ├── reader.py          # loads transcript CSVs, groups turns into earnings calls
│   │   ├── horizon.py         # resolves claim time horizons to absolute dates
│   │   ├── prompt.py          # extraction system prompt + few-shot example
│   │   ├── provenance.py      # matches an extracted quote back to its source turn
│   │   ├── extract.py         # build_extractor, extract_call, extract_transcript, dedupe_claims
│   │   ├── output.py          # writes the claims CSV
│   │   └── run.py             # CLI: python -m extractor.run --input ... --output ...
│   └── verifier/              # workstream C — verification agent (iteration 1: stubbed tools)
│       ├── __init__.py        # re-exports the public API
│       ├── schema.py          # Pydantic models: Claim, EvidenceItem, EvidenceBundle, Verdict
│       ├── corpus.py          # iteration-1 stub: loads canned excerpts from data/stub/
│       ├── tools.py           # search_filings tool (stubbed; real EDGAR in iteration 2)
│       ├── trace.py           # JSON+Markdown trace writer (adapted from agentic-rag-edgar-demo)
│       ├── agent.py           # build_agent, verify, verify_from_dict
│       └── run.py             # CLI: python -m verifier.run --claim ... --mode {evidence,verdict}
├── tests/
│   ├── test_extractor_*.py    # extractor tests: schema, reader, horizon, provenance, dedupe, smoke
│   ├── test_schema.py         # verifier Pydantic schema tests
│   ├── test_corpus.py         # verifier stub corpus loader test
│   ├── test_tools.py          # verifier search_filings stub test
│   └── test_smoke.py          # verifier end-to-end live tests (marked `live`; run with `pytest -m live`)
├── data/
│   ├── Transcript/            # input earnings-call transcript CSVs (4 firms)
│   ├── claims/                # extractor output — claims CSVs
│   ├── stub/                  # canned fixtures (example_claim.json + canned_excerpts.json)
│   └── traces/                # per-run agent traces (gitignored)
└── docs/                      # design docs and other supporting material
```

Workstreams A (data infrastructure) and D (evaluation & writeup) will add their own modules under `src/` as they come online.

## Setup

Prerequisites: [mamba](https://mamba.readthedocs.io/) (or conda), an OpenAI API key.

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
#    then edit .env and set OPENAI_API_KEY
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

## Claim extraction (workstream B)

The `extractor` package turns earnings-call transcripts into a CSV of typed,
forward-looking management claims for workstreams C and D to consume. For each
earnings call it makes one OpenAI structured-output request, recovers each
claim's source turn by matching the quote back to the transcript, resolves
claim time horizons to absolute dates, and drops exact-duplicate claims.

Every claim is classified into one of five types — `numerical_guidance`,
`buyback`, `dividend`, `capex`, `debt` — and carries its verbatim quote, a
paraphrase, provenance (source turn + speaker), and a resolved horizon. By
design the schema holds no verdict or outcome field: the extractor surfaces
claims, the verifier surfaces evidence, and human labelers assign verdicts.

Run it with the CLI:

```bash
# 5-call pilot on one firm
python -m extractor.run \
    --input data/Transcript/Tesla_2018_2022.csv \
    --output data/claims/pilot_claims.csv --limit 5

# full run over every transcript CSV in a directory
python -m extractor.run --input data/Transcript --output data/claims/all_claims.csv

# override the model (default: openai:gpt-4o-mini)
python -m extractor.run --input ... --output ... --model openai:gpt-5.5
```

The CLI loads `OPENAI_API_KEY` from `.env` automatically. Each run prints a
per-call claim count and a summary (type breakdown, provenance split, horizon
resolution) and writes one row per claim to the output CSV in `data/claims/`.

## Adding or updating dependencies

`pyproject.toml` is the source of truth. After editing `[project.dependencies]`:

```bash
pip-compile pyproject.toml -o requirements.txt   # regenerate the lock file
pip install -r requirements.txt                  # apply
```

Commit both `pyproject.toml` and `requirements.txt` together.
