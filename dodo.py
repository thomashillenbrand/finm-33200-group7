"""
dodo.py — PyDoIt task file for the FINM 33200 Group 7 pipeline.

Install doit (once):
    pip install doit

Common commands:
    doit              # run default tasks (through dashboard)
    doit list         # list all tasks
    doit <task>       # run one task (and its dependencies)
    doit clean        # remove generated targets
    doit -n 4         # run up to 4 tasks in parallel (independent ones only)

WARNING: several tasks make live OpenAI API calls and can be expensive.
         Read the per-task docstrings before running the full pipeline.

Task dependency graph:
    pull:AMZN ─┐
    pull:TSLA  ├─► extract ─┬─► autocheck ─┬─► combine ─► dashboard
    pull:KO    │             │               │
    pull:LLY  ─┘             └─► index ──► verify_agent ─┘

    extract ─► autocheck ─► autolabel_select ─► autolabel_label ─► eval
"""

import json
import tempfile
import subprocess
import sys
from pathlib import Path

import pandas as pd

# ── paths ──────────────────────────────────────────────────────────────────────

ROOT         = Path(__file__).resolve().parent
PULLED_DATA  = ROOT / "Pulled_data"

CLAIMS_CSV   = ROOT / "data/claims/55_full_run.csv"
AUTOCHECK_CSV = ROOT / "data/autochecker/55_full_run_verdict_autochecker-v1.csv"
AGENT_JSONL  = ROOT / "data/verdicts/agent_screenfalse_55.jsonl"
COMBINED_CSV = ROOT / "data/verdicts/combined_55_final.csv"
DASHBOARD_HTML   = ROOT / "data/profiles/dashboard.html"
PROFILE_SUMMARY  = ROOT / "data/profiles/summary.csv"
AGENT_JSONL_FULL = ROOT / "data/autochecker/55_full_run_verdict_autochecker-v1.jsonl"
GOLD_DIR     = ROOT / "data/gold/auto"
SUBSET_IDS   = ROOT / "data/gold/auto/subset_ids.txt"
EVAL_RUNS_DIR = ROOT / "data/eval/runs"

TICKERS    = ["AMZN", "TSLA", "KO", "LLY"]
START_DATE = "2018-01-01"

# ── doit global config ────────────────────────────────────────────────────────

DOIT_CONFIG = {
    "default_tasks": ["profiles", "dashboard"],
    "verbosity": 2,
}

# ── helper: file paths ────────────────────────────────────────────────────────

def _transcript_parquet(ticker: str) -> Path:
    return PULLED_DATA / ticker / "transcript" / f"{ticker}_transcripts.parquet"

def _faiss_index(ticker: str) -> Path:
    return PULLED_DATA / ticker / "index" / "faiss.index"

# ── helper: combine verdicts (Python action) ──────────────────────────────────

def _combine_verdicts():
    """
    Merge autochecker + agent verdicts into combined_55_final.csv.
    Autochecker takes priority; agent fills in what it resolved.
    """
    RESOLVED = {"verified", "partially_verified", "contradicted", "not_yet_resolvable"}

    ac = pd.read_csv(AUTOCHECK_CSV)
    ac_resolved = ac[ac["verdict"].isin(RESOLVED)].copy()
    ac_resolved["source"] = "autochecker"

    with open(AGENT_JSONL) as f:
        agent_rows = [json.loads(line) for line in f if line.strip()]
    agent = pd.DataFrame(agent_rows)
    # keep only the columns that exist in both
    agent_cols = [c for c in ["claim_id", "ticker", "verdict"] if c in agent.columns]
    agent = agent[agent_cols].copy()
    agent["source"] = "agent"

    # columns to carry forward from autochecker rows
    ac_cols = [c for c in ["claim_id", "ticker", "call_date", "claim_type", "verdict", "source"]
               if c in ac_resolved.columns]

    combined = pd.concat(
        [ac_resolved[ac_cols], agent],
        ignore_index=True,
    ).drop_duplicates(subset="claim_id", keep="first")

    COMBINED_CSV.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(COMBINED_CSV, index=False)
    print(f"Wrote {COMBINED_CSV} ({len(combined)} rows)")


# ── helper: batch verifier (Python action) ────────────────────────────────────

def _run_verifier_batch():
    """
    Run verifier.run once per residual claim (those not resolved by autochecker).
    Each claim is written to a temp JSON file and passed via --claim.

    WARNING: makes one live OpenAI call per residual claim — can be expensive.
             The verifier has an LLM cache (pulled_data/.cache/llm_cache.sqlite)
             so re-running the same claim is free unless --no-cache was used.
    """
    RESOLVED = {"verified", "partially_verified", "contradicted", "not_yet_resolvable"}

    claims = pd.read_csv(CLAIMS_CSV)
    ac = pd.read_csv(AUTOCHECK_CSV)
    resolved_ids = set(ac.loc[ac["verdict"].isin(RESOLVED), "claim_id"])
    residual = claims[~claims["claim_id"].isin(resolved_ids)]

    print(f"Running verifier agent on {len(residual)} residual claims...")
    AGENT_JSONL.parent.mkdir(parents=True, exist_ok=True)

    with AGENT_JSONL.open("w", encoding="utf-8") as out_f:
        for i, (_, row) in enumerate(residual.iterrows(), 1):
            claim_dict = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            ) as tmp:
                json.dump(claim_dict, tmp)
                tmp_path = Path(tmp.name)

            try:
                result = subprocess.run(
                    [sys.executable, "-m", "verifier.run",
                     "--claim", str(tmp_path), "--mode", "verdict"],
                    capture_output=True, text=True, cwd=ROOT,
                )
                if result.returncode == 0:
                    # verifier prints the verdict JSON as the last non-empty line
                    for line in reversed(result.stdout.splitlines()):
                        line = line.strip()
                        if line.startswith("{"):
                            out_f.write(line + "\n")
                            break
                    print(f"  [{i}/{len(residual)}] {row['claim_id']} OK")
                else:
                    print(
                        f"  [{i}/{len(residual)}] WARN: {row['claim_id']} "
                        f"failed — {result.stderr[:120]}"
                    )
            finally:
                tmp_path.unlink(missing_ok=True)

    print(f"Wrote {AGENT_JSONL}")


# ── tasks ─────────────────────────────────────────────────────────────────────

def task_pull():
    """Pull WRDS transcripts, Compustat, and SEC filings — one subtask per ticker.

    Each subtask is idempotent: data_pull skips files that already exist on disk.
    Requires WRDS_USERNAME and SEC_USER_AGENT in .env.
    Output: Pulled_data/<TICKER>/transcript/, SEC/, Compustat/
    """
    for ticker in TICKERS:
        target = _transcript_parquet(ticker)
        yield {
            "name": ticker,
            "doc": f"Pull data for {ticker} (WRDS + SEC + Compustat)",
            "actions": [
                f"python -m data_pull {ticker} --start {START_DATE}",
            ],
            "targets": [str(target)],
            # no file_dep — external sources; skip if target already on disk
        }


def task_extract():
    """Extract forward-looking management claims from all transcript parquets.

    Reads every *_transcripts.parquet under Pulled_data/ and writes one CSV row
    per claim. Requires EXTRACTOR_MODEL (or OPENAI_API_KEY) in .env.

    WARNING: makes one structured-output LLM call per earnings call (~55 calls
             across 4 tickers). Approx cost: $0.50–$2 depending on model.
    Output: data/claims/55_full_run.csv
    """
    return {
        "actions": [
            f"python -m extractor.run "
            f"--input {PULLED_DATA} "
            f"--output {CLAIMS_CSV}",
        ],
        "file_dep": [str(_transcript_parquet(t)) for t in TICKERS],
        "targets":  [str(CLAIMS_CSV)],
        "task_dep": [f"pull:{t}" for t in TICKERS],
    }


def task_index():
    """Build FAISS search indexes for all four tickers.

    Chunks, embeds, and indexes every SEC filing for fast retrieval by the
    verifier agent. Only new accession numbers are embedded on re-runs.
    Requires EMBEDDING_MODEL in .env.

    WARNING: embeds several thousand text chunks — approx cost: $1–$3.
    Output: Pulled_data/<TICKER>/index/chunks.parquet + faiss.index
    """
    return {
        "actions":  ["python -m verifier.index --all"],
        "file_dep": [str(_transcript_parquet(t)) for t in TICKERS],
        "targets":  [str(_faiss_index(t)) for t in TICKERS],
        "task_dep": [f"pull:{t}" for t in TICKERS],
    }


def task_autocheck():
    """Grade numerical guidance claims against Compustat quarterly data.

    Two-stage: (1) screen whether the claim maps to a Compustat field,
    (2) compare against realized figures. Claims not resolved here are
    passed to the verifier agent in task_verify_agent.

    WARNING: makes two LLM calls per Compustat-relevant claim.
    Output: data/autochecker/55_full_run_verdict_autochecker-v1.csv
    """
    return {
        "actions": [
            f"python -m autochecker.run "
            f"--claims {CLAIMS_CSV} "
            f"--mode verdict",
        ],
        "file_dep": [str(CLAIMS_CSV)],
        "targets":  [str(AUTOCHECK_CSV)],
        "task_dep": ["extract"],
    }


def task_verify_agent():
    """Run the verifier agent on residual claims not resolved by autochecker.

    Iterates over every claim in CLAIMS_CSV that has no resolved autochecker
    verdict, serialises it to a temp JSON, and calls verifier.run --mode verdict.
    Results are appended to data/verdicts/agent_screenfalse_55.jsonl.

    The agent has an LLM cache (pulled_data/.cache/llm_cache.sqlite) so
    re-running already-processed claims is free.

    WARNING: makes several tool-call + completion round-trips per claim.
             Full run over ~200 residual claims: approx $5–$20.
    Output: data/verdicts/agent_screenfalse_55.jsonl
    """
    return {
        "actions":  [_run_verifier_batch],
        "file_dep": [str(CLAIMS_CSV), str(AUTOCHECK_CSV)],
        "targets":  [str(AGENT_JSONL)],
        "task_dep": ["extract", "autocheck", "index"],
    }


def task_combine():
    """Merge autochecker + agent verdicts → data/verdicts/combined_55_final.csv.

    Autochecker verdicts take priority; agent fills in the rest.
    No LLM calls — pure pandas merge.
    Output: data/verdicts/combined_55_final.csv
    """
    return {
        "actions":  [_combine_verdicts],
        "file_dep": [str(AUTOCHECK_CSV), str(AGENT_JSONL)],
        "targets":  [str(COMBINED_CSV)],
        "task_dep": ["autocheck", "verify_agent"],
    }


def task_profiles():
    """Build per-firm profile CSVs and aggregate summary → data/profiles/.

    Merges combined verdicts + claim details + grader reasoning into one CSV
    per ticker (AMZN_profile.csv, TSLA_profile.csv, KO_profile.csv,
    LLY_profile.csv) and a cross-firm summary.csv. No LLM calls.
    Output: data/profiles/<TICKER>_profile.csv + data/profiles/summary.csv
    """
    return {
        "actions": [
            f"python -m profiles.build_profiles "
            f"--verdicts        {COMBINED_CSV} "
            f"--claims          {CLAIMS_CSV} "
            f"--agent-jsonl     {AGENT_JSONL} "
            f"--autocheck-jsonl {AGENT_JSONL_FULL} "
            f"--out-dir         {ROOT / 'data/profiles'}",
        ],
        "file_dep": [str(COMBINED_CSV), str(CLAIMS_CSV)],
        "targets":  [str(PROFILE_SUMMARY)],
        "task_dep": ["combine"],
    }


def task_dashboard():
    """Generate the interactive HTML dashboard → data/profiles/dashboard.html.

    Builds a self-contained Plotly.js dashboard from the combined verdict CSV.
    No LLM calls. Also used as the data source for `streamlit run src/profiles/app.py`.
    Output: data/profiles/dashboard.html
    """
    return {
        "actions": [
            f"python -m profiles.dashboard "
            f"--verdicts {COMBINED_CSV} "
            f"--claims   {CLAIMS_CSV} "
            f"--runs-dir {EVAL_RUNS_DIR} "
            f"--out      {DASHBOARD_HTML}",
        ],
        "file_dep": [str(COMBINED_CSV), str(CLAIMS_CSV)],
        "targets":  [str(DASHBOARD_HTML)],
        "task_dep": ["combine"],
    }


def task_autolabel_select():
    """Select and freeze the gold-set claim subset (no LLM calls).

    Picks capital-allocation claims the autochecker screened out, biased
    toward elapsed horizons plus a few forward "not-yet-resolvable" controls.
    Output: data/gold/auto/subset_ids.txt
    """
    return {
        "actions": [
            f"python -m verifier.autolabel select "
            f"--claims {CLAIMS_CSV} "
            f"--out {SUBSET_IDS} "
            f"--exclude-checked {AUTOCHECK_CSV} "
            f"--elapsed-by 2024-12-31 "
            f"--forward-per-ticker 2",
        ],
        "file_dep": [str(CLAIMS_CSV), str(AUTOCHECK_CSV)],
        "targets":  [str(SUBSET_IDS)],
        "task_dep": ["extract", "autocheck"],
    }


def task_autolabel_label():
    """Label the frozen gold subset with GPT-5.5 using the labeling rubric.

    Requires GOLD_LABELER_MODEL in .env. Uses the same deterministic keyword
    sweep as the human helper — not the agent's FAISS index — so recall@k
    independence is preserved.

    WARNING: makes one LLM call per gold claim (~28 calls). Approx cost: $1–$3.
    Output: data/gold/auto/<claim_id>.jsonl files
    """
    return {
        "actions": [
            f"python -m verifier.autolabel label "
            f"--claims {CLAIMS_CSV} "
            f"--claim-ids {SUBSET_IDS} "
            f"--gold-dir {GOLD_DIR}",
        ],
        "file_dep": [str(CLAIMS_CSV), str(SUBSET_IDS)],
        "targets":  [],   # files are per-claim; doit will re-run if subset_ids.txt changes
        "task_dep": ["autolabel_select"],
        # always re-run if subset changes; otherwise treat as done once labels exist
        "uptodate": [GOLD_DIR.exists and any(GOLD_DIR.glob("*.jsonl"))
                     if GOLD_DIR.exists() else False],
    }


def task_eval():
    """Score the verifier agent against the auto-labeled gold set.

    Runs the agent live on every gold claim and computes recall@8, precision,
    and verdict accuracy. Each run is saved under data/eval/runs/<timestamp>/.

    WARNING: makes live agent calls — one per gold claim (~28 calls).
             Pass --no-cache if prompts have changed since the last run.
    Output: data/eval/runs/<timestamp>_discipline-pass/ (new dir each run)
    """
    return {
        "actions": [
            f"python -m verifier.eval "
            f"--gold {GOLD_DIR} "
            f"--claims {CLAIMS_CSV} "
            f"--mode verdict "
            f"--k 8 "
            f"--run-label discipline-pass "
            f"--runs-dir {EVAL_RUNS_DIR}",
        ],
        "file_dep": [str(CLAIMS_CSV)],
        "task_dep": ["autolabel_label"],
        # eval writes a new timestamped dir each run — always re-run when invoked
        "uptodate": [False],
    }
