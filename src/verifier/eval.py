"""Scorer for gold-set evaluation.

Compares the verification agent's output against hand-labeled GoldLabels.
Matching is at accession_no granularity; labelers point at filings, not at the
chunker's window cuts (so this survives a chunker swap).

  recall@k  - fraction of gold-labeled accessions present in the agent's top-k
  precision - fraction of the agent's k accessions that the labeler marked
  verdict   - exact match between gold.verdict and the agent's verdict

recall@k and precision are None (not 0) for claims with no labeled evidence
(`not_yet_resolvable` with empty expected_evidence) — dividing by zero would
otherwise report a meaningless 0 and drag the mean down.

The pure scoring functions (`score_retrieval`, `score_verdict`, `aggregate`)
take already-computed objects and are unit-tested offline. The CLI runs the
agent live per gold claim — the agent's structured output is not persisted to
the trace, so scoring re-runs `verify()`. The SQLite chat cache (on by default)
keeps re-scoring cheap after the first pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from schemas import EvidenceBundle, Verdict
from verifier.gold import GoldLabel


@dataclass(frozen=True)
class PerClaimResult:
    claim_id: str
    recall_at_k: Optional[float]
    precision: Optional[float]
    verdict_match: Optional[bool]  # None when verdict not scored (evidence mode)


def score_retrieval(gold: GoldLabel, bundle: EvidenceBundle, *, k: int) -> PerClaimResult:
    """Score one claim's retrieval against gold, at accession-number granularity."""
    expected = {e.accession_no for e in gold.expected_evidence}
    retrieved = [it.accession_no for it in bundle.items][:k]
    if not expected:
        # No labeled evidence → recall/precision undefined.
        return PerClaimResult(gold.claim_id, None, None, None)
    retrieved_set = set(retrieved)
    hits = len(expected & retrieved_set)
    recall = hits / len(expected)
    precision = (hits / len(retrieved)) if retrieved else 0.0
    return PerClaimResult(gold.claim_id, recall, precision, None)


def score_verdict(gold: GoldLabel, verdict: Verdict) -> bool:
    """Exact-match the agent's verdict against the labeler's."""
    return gold.verdict == verdict.verdict


def aggregate(results: list[PerClaimResult]) -> dict:
    """Mean retrieval metrics over scorable claims; verdict accuracy over scored."""
    recall_scored = [r.recall_at_k for r in results if r.recall_at_k is not None]
    precision_scored = [r.precision for r in results if r.precision is not None]
    verdict_scored = [r.verdict_match for r in results if r.verdict_match is not None]

    def _mean(xs: list) -> Optional[float]:
        return (sum(xs) / len(xs)) if xs else None

    return {
        "n_claims": len(results),
        "n_recall_scored": len(recall_scored),
        "mean_recall_at_k": _mean(recall_scored),
        "mean_precision": _mean(precision_scored),
        "verdict_accuracy": _mean([1.0 if v else 0.0 for v in verdict_scored]),
    }


# --- Run records -----------------------------------------------------------

def _git_head_sha() -> str:
    """Short git HEAD sha, so a run's numbers are tied to a code state (for
    revert decisions). 'unknown' if git is unavailable."""
    import subprocess

    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def write_run_record(runs_dir, label, *, results, summary, meta):
    """Write a self-contained, never-overwritten eval run record:

        <runs_dir>/<meta['timestamp']>_<label>/{per_claim.csv, summary.json, meta.json}

    Each run lands in its own timestamped directory, so successive evals
    accumulate side by side and a regression can be traced to (and reverted via)
    the `git_head` recorded in meta. Returns the run directory.
    """
    import csv
    import json
    from pathlib import Path

    run_dir = Path(runs_dir) / f"{meta['timestamp']}_{label}"
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "per_claim.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["claim_id", "recall_at_k", "precision", "verdict_match"])
        for r in results:
            w.writerow([r.claim_id, r.recall_at_k, r.precision, r.verdict_match])
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return run_dir


# --- CLI -------------------------------------------------------------------

def _load_claims_by_id(claims_csv) -> dict:
    """Read the pilot claims CSV into {claim_id: row-dict}, NaN → dropped.

    Dropping null cells lets Pydantic fill schema defaults; required columns are
    always populated in the CSV, so they survive.
    """
    import pandas as pd

    df = pd.read_csv(claims_csv)
    by_id: dict[str, dict] = {}
    for _, row in df.iterrows():
        d = {k: v for k, v in row.items() if pd.notna(v)}
        by_id[str(d["claim_id"])] = d
    return by_id


def _cli() -> int:
    """`python -m verifier.eval --gold <jsonl|dir> --claims <pilot_csv> [...]`

    Runs the agent on each gold-labeled claim (looked up in the claims CSV),
    scores the result, prints a summary, and writes a per-claim CSV.
    """
    import argparse
    import csv
    import json
    import os
    import sys
    from datetime import datetime
    from pathlib import Path

    from dotenv import load_dotenv

    p = argparse.ArgumentParser(prog="verifier.eval", description=__doc__)
    p.add_argument("--gold", required=True, type=Path,
                   help="Gold-label JSONL, or a directory of *.jsonl files.")
    p.add_argument("--claims", required=True, type=Path,
                   help="Claims CSV (provides claim fields to run the agent).")
    p.add_argument("--mode", choices=["evidence", "verdict"], default="evidence",
                   help="evidence (retrieval only) or verdict (also score verdict).")
    p.add_argument("--k", type=int, default=8,
                   help="Top-k cutoff for recall/precision (default 8 = tool's k).")
    p.add_argument("--no-cache", action="store_true",
                   help="Bypass the SQLite chat cache for fresh LLM calls.")
    p.add_argument("--output", type=Path, default=Path("data/eval/per_claim_results.csv"),
                   help="Where to write the per-claim CSV.")
    args = p.parse_args()

    load_dotenv()

    # Deferred imports: these pull in the agent stack + require env model vars.
    from schemas import Claim
    from verifier.agent import UnsupportedClaimTypeError, verify
    from verifier.gold import load_gold_labels

    gold_paths = sorted(args.gold.glob("*.jsonl")) if args.gold.is_dir() else [args.gold]
    gold_labels: dict[str, GoldLabel] = {}
    for gp in gold_paths:
        for gl in load_gold_labels(gp):
            gold_labels[gl.claim_id] = gl
    if not gold_labels:
        print(f"No gold labels found at {args.gold}", file=sys.stderr)
        return 1

    claims_by_id = _load_claims_by_id(args.claims)

    results: list[PerClaimResult] = []
    for claim_id, gold in gold_labels.items():
        row = claims_by_id.get(claim_id)
        if row is None:
            print(f"WARN: claim_id {claim_id} not in {args.claims}, skipping",
                  file=sys.stderr)
            continue
        try:
            claim = Claim(**row)
            output = verify(claim, mode=args.mode, trace=False, cache=not args.no_cache)
        except UnsupportedClaimTypeError as e:
            print(f"WARN: skipping {claim_id}: {e}", file=sys.stderr)
            continue
        except Exception as e:  # one bad agent/parse result must not nuke the batch
            print(f"WARN: skipping {claim_id}: agent error: {type(e).__name__}: {e}",
                  file=sys.stderr)
            continue

        if args.mode == "verdict":
            bundle = EvidenceBundle(items=output.items)
            r = score_retrieval(gold, bundle, k=args.k)
            r = PerClaimResult(r.claim_id, r.recall_at_k, r.precision,
                               score_verdict(gold, output))
        else:
            r = score_retrieval(gold, output, k=args.k)
        results.append(r)
        print(f"  scored {claim_id}: recall@{args.k}={r.recall_at_k} "
              f"precision={r.precision} verdict_match={r.verdict_match}")

    summary = aggregate(results)
    print("\n" + json.dumps(summary, indent=2))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["claim_id", "recall_at_k", "precision", "verdict_match"])
        for r in results:
            w.writerow([r.claim_id, r.recall_at_k, r.precision, r.verdict_match])
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
