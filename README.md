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
│   └── verifier/              # workstream C — verification agent (iteration 1: stubbed tools)
│       ├── __init__.py        # re-exports the public API
│       ├── schema.py          # Pydantic models: Claim, EvidenceItem, EvidenceBundle, Verdict
│       ├── corpus.py          # iteration-1 stub: loads canned excerpts from data/stub/
│       ├── tools.py           # search_filings tool (stubbed; real EDGAR in iteration 2)
│       ├── trace.py           # JSON+Markdown trace writer (adapted from agentic-rag-edgar-demo)
│       ├── agent.py           # build_agent, verify, verify_from_dict
│       └── run.py             # CLI: python -m verifier.run --claim ... --mode {evidence,verdict}
├── tests/
│   ├── test_schema.py         # Pydantic schema tests (incl. the no-verdict-on-EvidenceBundle guarantee)
│   ├── test_corpus.py         # stub corpus loader test
│   ├── test_tools.py          # search_filings stub test
│   └── test_smoke.py          # end-to-end live tests (marked `live`; run with `pytest -m live`)
├── data/
│   ├── stub/                  # canned fixtures (example_claim.json + canned_excerpts.json)
│   └── traces/                # per-run agent traces (gitignored)
└── docs/                      # design docs and other supporting material
```

Workstreams A (data infrastructure), B (claim extraction), and D (evaluation & writeup) will add their own modules under `src/` as they come online.

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

# End-to-end smoke tests (require OPENAI_API_KEY in .env; ~2 OpenAI calls per test)
pytest -m live -v

# Run the agent on the stub claim — see the full trace and the structured output
python -m verifier.run --claim data/stub/example_claim.json --mode evidence
python -m verifier.run --claim data/stub/example_claim.json --mode verdict
````

If `pytest -v` shows 9 passed and `python -m verifier.run` produces an
`EvidenceBundle` JSON dump, the scaffold is healthy. Traces from each run
land in `data/traces/` (gitignored).

### Adding or updating dependencies

`pyproject.toml` is the source of truth. After editing `[project.dependencies]`:

```bash
pip-compile pyproject.toml -o requirements.txt   # regenerate the lock file
pip install -r requirements.txt                  # apply
```

Commit both `pyproject.toml` and `requirements.txt` together.
