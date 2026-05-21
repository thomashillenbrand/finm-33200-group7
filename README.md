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
│   └── verifier/              # workstream C — verification agent
├── tests/                     # smoke + unit tests
├── data/
│   ├── stub/                  # canned data for early iterations
│   └── traces/                # agent run traces (gitignored)
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
pip install -r requirements.txt

# 3. Editable install of the project's source packages
pip install -e .

# 4. Configure secrets
cp .env.example .env
#    then edit .env and set OPENAI_API_KEY
```

### Adding or updating dependencies

`pyproject.toml` is the source of truth. After editing `[project.dependencies]`:

```bash
pip-compile pyproject.toml -o requirements.txt   # regenerate the lock file
pip install -r requirements.txt                  # apply
```

Commit both `pyproject.toml` and `requirements.txt` together.
