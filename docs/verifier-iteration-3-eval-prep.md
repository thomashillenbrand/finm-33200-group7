# Verifier Iteration 3 — Evaluation Prep

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the prerequisites that gate the pilot gold-set labeling sprint — without which we can't iteratively improve the verifier. Specifically: (1) fix the `before_date <= after_date` retrieval bug surfaced in iter-2's smoke run; (2) spec a labeling format that captures expected evidence + verdict per claim; (3) draft a labeling rubric with verdict buckets and partial-credit policy; (4) build a scorer harness that compares agent output against gold labels; (5) externalize model identifiers to per-task env vars so we can A/B different models per stage without code edits during iteration.

**Non-goal:** the labeling sprint itself, the full chunker autoresearcher, and the rest of the iter-3 robustness backlog (rate-limit/retry, SQLite cache fragility, `datetime.utcnow` deprecation) — those land separately. The cut here is "the smallest possible kit that unblocks iterative improvement against a real gold set."

**Branch:** `feature/verifier-iteration3` (branched from `feature/verifier-iteration2`).

**Conventions used in every task below:**

- All Python runs inside the `truth` mamba env: prefix with `mamba run -n truth …`.
- `pytest` runs from repo root with the default `addopts = "-m 'not live'"` from pyproject.
- Commits use the project's bare-message style (no Claude-Code attribution footer — per `feedback_commits_no_claude_attribution`).
- The user owns all git writes (per `feedback_user_handles_git`). **Where this plan says "commit", pause and ask the user to commit** — do not stage/commit on your own.

---

## Section A — Fix the `before_date` retrieval bug

### Task 1: Silent-widen `before_date` in the tool layer when it's <= `after_date`

**Context.** Iter-2's smoke run (5 capital_allocation claims against the real TSLA index) showed the agent passing `before_date == call_date` in 3/5 traces, which collapses the search window to `[call_date, call_date]` and returns zero hits. smoke_2 produced 0 evidence purely because of this. The agent has already demonstrated it can ignore docstring guidance, so a docstring-only fix is fragile. We harden it at the tool layer instead.

**Files:**
- Modify: `src/verifier/tools.py` (the closure inside `bind_search_filings`)
- Modify: `tests/test_tools.py` (or wherever the closure tests live — confirm first)

- [ ] **Step 1: Find the existing tool-layer tests**

```bash
grep -rln "bind_search_filings\|search_filings" tests/
```

Expected: identifies the test file(s) covering the closure. We'll add new cases alongside.

- [ ] **Step 2: Write failing tests for the silent-widen behavior**

Add to the tool-layer test file. The closure normally takes a `SearchIndex`; in tests we either use a real index (live) or a stub. Use the same stubbing pattern the existing tests use — don't introduce a new one.

```python
def test_search_tool_widens_window_when_before_le_after(...):
    """If the agent passes a before_date <= the closed-over after_date, the
    tool layer should silently treat before_date as None (open-ended upper
    bound) rather than producing an empty window."""
    # Construct the closure with a known after_date, call it with a
    # before_date <= after_date, and assert the underlying SearchIndex.query
    # was called with before_date=None (not the agent-supplied value).

def test_search_tool_passes_through_valid_before_date(...):
    """If before_date > after_date, the tool layer should pass it through
    unchanged."""
```

How to assert against `SearchIndex.query`: either use a mock that records calls, or assert via the returned evidence's `filing_date` range. The existing test file will indicate which style is in use.

- [ ] **Step 3: Run the tests to verify they fail**

```bash
mamba run -n truth pytest tests/test_tools.py -v -k widens
```

Expected: FAIL — the silent-widen is not implemented yet.

- [ ] **Step 4: Implement silent-widen in `src/verifier/tools.py`**

In the closure body, before calling `index.query`, normalize the `before_date` argument:

```python
@tool
def search_filings(
    query: str,
    before_date: date | None = None,
    forms: list[str] | None = None,
) -> str:
    """Search this firm's SEC filings for evidence about a claim.

    Args:
        query: Free-form text describing what to look for. Examples:
            "share repurchase amount Q1 2024", "capex 2024 actual spend".
        before_date: Optional upper bound on filing date (inclusive). Must
            be strictly later than the call date that the verifier is using
            as its time floor; values at or before the floor are ignored
            (treated as open-ended).
        forms: Optional restriction to filing forms (e.g. ["10-Q", "8-K"]).

    Returns:
        Up to 8 matching excerpts, each preceded by a bracketed
        `[form filed YYYY-MM-DD, accession ...]` header.
    """
    if before_date is not None and before_date <= after_date:
        # Agent passed a non-useful upper bound; ignore it.
        before_date = None
    items = index.query(query, after_date=after_date,
                        before_date=before_date, forms=forms, k=8)
    return _stringify_evidence(items)
```

Docstring is updated to document the new behavior, but the **load-bearing** fix is the conditional reset above.

- [ ] **Step 5: Run the offline test suite**

```bash
mamba run -n truth pytest -v
```

Expected: all tests PASS, including the two new widen-cases.

- [ ] **Step 6: Commit (ask user)**

Suggested message: `fix(verifier): silent-widen before_date when <= after_date in search tool`

---

## Section B — Labeling format

### Task 2: Spec the gold-set labeling format

**Context.** The pilot gold set is what unblocks both retrieval eval (recall@k) and verdict eval (accuracy). We need a single artifact per claim that carries (a) the human-identified relevant evidence excerpts and (b) the human-assigned verdict. JSONL — not CSV — because `expected_evidence` is naturally a list of objects.

**Files:**
- Create: `data/gold/README.md` (one-page schema doc + how-to-label)
- Create: `data/gold/template.jsonl` (one fully-filled example row + commented field list)
- Create: `src/verifier/gold.py` (Pydantic schema + JSONL loader + validator)
- Create: `tests/test_gold.py`

- [ ] **Step 1: Decide the schema (no code yet — write it down)**

The artifact is one JSONL row per labeled claim. Fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| `claim_id` | str | yes | FK into `data/claims/pilot_claims.csv` |
| `ticker` | str | yes | Denormalized for quick filtering |
| `labeler` | str | yes | Short tag, e.g. `"tom"`, `"brendan"` |
| `labeled_at` | ISO datetime | yes | When the label was assigned |
| `expected_evidence` | list[object] | yes (may be empty) | One entry per filing excerpt the labeler considers necessary. Empty list = "no evidence available in the corpus" (a legitimate label). |
| `expected_evidence[].accession_no` | str | yes | E.g. `"0001318605-24-000050"` |
| `expected_evidence[].form` | str | yes | One of `10-K`, `10-Q`, `8-K` |
| `expected_evidence[].filing_date` | ISO date | yes | |
| `expected_evidence[].quote` | str | yes | Verbatim snippet (≤500 chars) that the labeler used to decide |
| `expected_evidence[].section` | str | no | Free-text section pointer, e.g. `"Item 7 — MD&A"` |
| `verdict` | str | yes | One of `verified`, `partially_verified`, `contradicted`, `not_yet_resolvable` |
| `confidence` | str | yes | One of `high`, `medium`, `low` — tracks how sure the labeler is, separate from the verdict |
| `labeler_notes` | str | no | Free-text explanation (the *why* of the verdict — load-bearing for rubric calibration) |

Special-case: `not_yet_resolvable` may carry an empty `expected_evidence` list — that's the intended encoding for "horizon hasn't elapsed at the corpus date."

- [ ] **Step 2: Write `src/verifier/gold.py` (Pydantic schema + loader)**

```python
"""Gold-set labeling schema and JSONL loader.

The artifact is one JSONL row per labeled claim, written by hand during the
gold-set labeling sprint and consumed by `verifier.eval` for scoring.

Schema invariants (enforced):
- claim_id is non-empty
- verdict is one of the four canonical buckets
- if verdict in {verified, partially_verified, contradicted}, expected_evidence
  must be non-empty (a claim cannot be "verified" with no evidence pointing to
  it)
- if verdict == not_yet_resolvable, expected_evidence may be empty
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


Verdict = Literal["verified", "partially_verified", "contradicted", "not_yet_resolvable"]
Confidence = Literal["high", "medium", "low"]


class GoldEvidence(BaseModel):
    accession_no: str = Field(min_length=1)
    form: Literal["10-K", "10-Q", "8-K"]
    filing_date: date
    quote: str = Field(min_length=1, max_length=500)
    section: Optional[str] = None


class GoldLabel(BaseModel):
    claim_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    labeler: str = Field(min_length=1)
    labeled_at: datetime
    expected_evidence: list[GoldEvidence] = Field(default_factory=list)
    verdict: Verdict
    confidence: Confidence
    labeler_notes: str = ""

    @model_validator(mode="after")
    def evidence_required_for_decisive_verdicts(self) -> "GoldLabel":
        decisive = {"verified", "partially_verified", "contradicted"}
        if self.verdict in decisive and not self.expected_evidence:
            raise ValueError(
                f"verdict={self.verdict!r} requires non-empty expected_evidence; "
                f"use 'not_yet_resolvable' if no evidence applies."
            )
        return self


def load_gold_labels(path: Path) -> list[GoldLabel]:
    """Read a JSONL file, returning one GoldLabel per non-blank line.

    Raises ValidationError on the first malformed row, with the row number in
    the error message — labelers fix the file, not silently drop bad rows.
    """
    labels: list[GoldLabel] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                labels.append(GoldLabel.model_validate_json(line))
            except Exception as e:
                raise ValueError(f"gold label row {i} failed validation: {e}") from e
    return labels
```

- [ ] **Step 3: Write `tests/test_gold.py`**

Tests must cover:
- Round-trip: dump a `GoldLabel` to JSON, load it back, fields match
- `verdict=verified` with empty `expected_evidence` raises ValidationError
- `verdict=not_yet_resolvable` with empty `expected_evidence` is valid
- `load_gold_labels` parses a multi-row JSONL file
- `load_gold_labels` raises with the row number on a malformed row
- Unknown verdict label rejected
- Unknown form (e.g., `DEF 14A`) rejected

- [ ] **Step 4: Write `data/gold/README.md`**

One-page doc. Sections:
1. **What this directory is** — purpose, what files live here
2. **How to label one claim** — step-by-step: open the pilot CSV, find the claim, open the relevant ticker's 10-Q/10-K, find the evidence, write one JSONL row
3. **Verdict buckets** — short version (point at `docs/labeling_rubric.md` for the full version, which Task 3 produces)
4. **Schema reference** — table copied from Step 1 above
5. **File naming** — `data/gold/pilot_<ticker>.jsonl` (per-ticker file; labels merged at eval time)

- [ ] **Step 5: Write `data/gold/template.jsonl`**

One example row (TSLA, a real `capital_allocation` claim from the pilot CSV, with hand-written placeholder evidence) plus a commented-out header documenting the field order. Since JSONL is one-row-per-line, the "comment" is actually the README cross-reference — just include one filled example.

```jsonl
{"claim_id":"TSLA_20200129_<hash>","ticker":"TSLA","labeler":"template","labeled_at":"2026-05-23T00:00:00","expected_evidence":[{"accession_no":"0001318605-20-000010","form":"10-Q","filing_date":"2020-04-30","quote":"Capital expenditures for the three months ended March 31, 2020 were $455 million.","section":"Cash flow statement"}],"verdict":"partially_verified","confidence":"high","labeler_notes":"Claim said 'over $3B in 2020', Q1 actuals tracking ~$455M annualizes to ~$1.8B — short of guidance through one quarter."}
```

(Pick the actual claim_id from `data/claims/pilot_claims.csv` when filling this in — don't fabricate.)

- [ ] **Step 6: Run the gold-schema tests**

```bash
mamba run -n truth pytest tests/test_gold.py -v
```

Expected: all tests PASS, including the template row passing validation:

```bash
mamba run -n truth python -c "from verifier.gold import load_gold_labels; print(load_gold_labels('data/gold/template.jsonl'))"
```

- [ ] **Step 7: Commit (ask user)**

Suggested message: `feat(verifier): add gold-label schema + JSONL loader + template`

---

## Section C — Labeling rubric

### Task 3: Draft the labeling rubric

**Context.** Open item #3 from CLAUDE.md ("Capital allocation grading rubric — partial-credit policy") cannot be written purely in the abstract — labelers need worked examples to calibrate. This task produces a v0 rubric that the team revises during/after the pilot labeling.

**Files:**
- Create: `docs/labeling_rubric.md`

- [ ] **Step 1: Read existing context**

```bash
# Re-read CLAUDE.md open items + the verdict bucket definitions
grep -A 20 "Labeling workflow" CLAUDE.md
grep -A 5 "Capital allocation grading" CLAUDE.md
```

- [ ] **Step 2: Write `docs/labeling_rubric.md`**

Structure (sections in order):

1. **Purpose & non-purposes** — one paragraph. The rubric is for human labelers reading agent-surfaced evidence and deciding verdicts independently. It is *not* an agent system prompt and must not be loaded into the agent's context (would defeat the labeling-circularity guarantee).

2. **Verdict buckets** — definition for each:
   - `verified`: subsequent filings show the management claim was substantially realized (≥80% of stated figure or directional intent fully matched)
   - `partially_verified`: outcome matched some but not all of the claim (e.g., direction right but magnitude short, or one of several stated actions completed)
   - `contradicted`: subsequent filings show the outcome was opposite to or materially short of the stated claim
   - `not_yet_resolvable`: horizon has not elapsed at the corpus date, OR the corpus genuinely lacks the evidence (e.g., a private-company subsidiary action not broken out)

3. **Partial-credit policy for capital_allocation** — concrete decision rules:
   - **Buyback**: announced $X over N months. Cumulative actual / X ≥ 0.80 → verified; 0.40–0.80 → partial; <0.40 or net issuance → contradicted; horizon incomplete → not_yet_resolvable.
   - **Dividend**: announced increase / initiation / suspension. Match exactly → verified; raised by less than announced → partial; not raised / cut against announcement → contradicted.
   - **Capex**: forward-looking spend figure. Use ±15% as the verified band; ±15–40% partial; beyond that contradicted. Honor the firm's own framing — "approximately" vs. "at least" vs. "no more than" set asymmetric bands.
   - **Debt actions**: issuance, paydown, refinancing. Action of the stated type completed within the horizon → verified; smaller scale or longer timeline than stated → partial.

4. **Worked examples** — at least four, one per sub-kind above. Use real (or realistic) TSLA/AMZN cases. Each example shows: the claim verbatim, the would-be evidence excerpts, the assigned verdict, and a 1-2 sentence justification.

5. **Ambiguity-resolution guidance**
   - When evidence is split (one 10-Q supports, the next contradicts) → take the latest available datapoint within the horizon
   - When the agent surfaces zero evidence → check yourself; if you also can't find it, label as `not_yet_resolvable` with `confidence: low` and a note explaining
   - Confidence is independent of verdict — a labeler can be `high` confidence that something is `not_yet_resolvable` (horizon hasn't elapsed) just as easily as `high` confidence it is `verified`

6. **Inter-labeler calibration** — explicit advice: when starting the sprint, have two labelers independently label the same 3 claims, compare verdicts and notes, refine the rubric before scaling. The pilot is a chance to calibrate before the full sprint.

7. **Open questions for the team** — explicit list of decisions deferred. The user, Brendan, Seback, and Tejaswini should weigh in on these before the full sprint.

- [ ] **Step 3: Cross-link from CLAUDE.md**

Add one line under "Key documents in this directory":

```markdown
- `docs/labeling_rubric.md` — gold-set labeling rubric: verdict buckets, partial-credit policy for capital_allocation, worked examples. Draft; revised during/after the pilot sprint.
```

And resolve open item #3 from "Capital allocation grading rubric (partial-credit policy — …)" to "Capital allocation grading rubric — see `docs/labeling_rubric.md` (v0 draft, refine after pilot)".

- [ ] **Step 4: Commit (ask user)**

Suggested message: `docs: add v0 labeling rubric with verdict buckets and partial-credit policy`

---

## Section D — Scorer harness

### Task 4: Build the scorer that compares agent output to gold labels

**Files:**
- Create: `src/verifier/eval.py` (scorer module + CLI)
- Create: `tests/test_eval.py`
- Modify: `data/.gitignore` (if needed — ensure `data/gold/*.jsonl` is *not* gitignored; the labels are checked in)

**Context.** Two metrics need scoring:

1. **Retrieval quality** — does the agent's `EvidenceBundle` contain the chunks the labeler said matter? Per-claim **recall@k** (of the labeler's expected accessions, how many appear in the agent's top-k?) and **precision** (of the agent's k retrieved chunks, how many are in the labeler's set?).
2. **Verdict accuracy** — when run in `--mode verdict`, does the agent's `Verdict.verdict` match the labeler's? Per-claim exact match, plus a confusion matrix across all claims.

Matching is at **accession_no granularity**, not chunk granularity — labelers point at filings, not at our chunker's window cuts.

- [ ] **Step 1: Write the failing scorer tests**

```python
"""Tests for verifier.eval."""

from datetime import date, datetime
from pathlib import Path

import pytest

from verifier.eval import (
    score_retrieval,
    score_verdict,
    aggregate,
    PerClaimResult,
)
from verifier.gold import GoldLabel, GoldEvidence
from schemas import EvidenceItem, EvidenceBundle, Verdict


def _gold(claim_id="c1", verdict="verified", evidence_accessions=("acc-1", "acc-2")):
    return GoldLabel(
        claim_id=claim_id,
        ticker="TSLA",
        labeler="test",
        labeled_at=datetime(2026, 5, 23),
        expected_evidence=[
            GoldEvidence(accession_no=a, form="10-Q", filing_date=date(2024, 1, 1),
                         quote=f"q-{a}")
            for a in evidence_accessions
        ],
        verdict=verdict,
        confidence="high",
    )


def _evidence(accessions):
    return EvidenceBundle(items=[
        EvidenceItem(source=f"src-{a}", excerpt=f"e-{a}", accession_no=a,
                     form="10-Q", filing_date=date(2024, 1, 1),
                     chunk_id=f"chunk-{a}", score=0.5)
        for a in accessions
    ])


def test_recall_at_k_exact_hit():
    gold = _gold(evidence_accessions=("acc-1", "acc-2"))
    bundle = _evidence(["acc-1", "acc-2", "acc-3"])
    result = score_retrieval(gold, bundle, k=3)
    assert result.recall_at_k == 1.0
    assert result.precision == 2 / 3


def test_recall_at_k_partial_hit():
    gold = _gold(evidence_accessions=("acc-1", "acc-2", "acc-3"))
    bundle = _evidence(["acc-1", "acc-4"])
    result = score_retrieval(gold, bundle, k=2)
    assert result.recall_at_k == 1 / 3
    assert result.precision == 0.5


def test_recall_when_gold_has_no_evidence():
    """not_yet_resolvable claims have empty expected_evidence; recall is
    undefined. Scorer should return None for recall (not 0)."""
    gold = _gold(verdict="not_yet_resolvable", evidence_accessions=())
    bundle = _evidence([])
    result = score_retrieval(gold, bundle, k=3)
    assert result.recall_at_k is None


def test_verdict_exact_match():
    gold = _gold(verdict="verified")
    verdict = Verdict(items=[], verdict="verified", reasoning="r")
    assert score_verdict(gold, verdict) is True


def test_verdict_mismatch():
    gold = _gold(verdict="verified")
    verdict = Verdict(items=[], verdict="partially_verified", reasoning="r")
    assert score_verdict(gold, verdict) is False


def test_aggregate_summary_stats():
    """Aggregate over a list of per-claim results: mean recall@k, mean
    precision, verdict accuracy."""
    results = [
        PerClaimResult(claim_id="c1", recall_at_k=1.0, precision=0.5, verdict_match=True),
        PerClaimResult(claim_id="c2", recall_at_k=0.5, precision=0.25, verdict_match=False),
        PerClaimResult(claim_id="c3", recall_at_k=None, precision=None, verdict_match=True),
    ]
    summary = aggregate(results)
    # Recall/precision averaged over non-None entries only.
    assert summary["mean_recall_at_k"] == pytest.approx(0.75)
    assert summary["mean_precision"] == pytest.approx(0.375)
    assert summary["verdict_accuracy"] == pytest.approx(2 / 3)
    assert summary["n_claims"] == 3
    assert summary["n_recall_scored"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
mamba run -n truth pytest tests/test_eval.py -v
```

Expected: FAIL with ImportError on `verifier.eval`.

- [ ] **Step 3: Implement `src/verifier/eval.py`**

```python
"""Scorer for gold-set evaluation.

Compares agent output (EvidenceBundle from evidence-mode, or Verdict from
verdict-mode) against hand-labeled GoldLabels. Matching is at accession_no
granularity; labelers point at filings, not at our chunker's windows.

Recall@k: fraction of gold-labeled accessions present in the agent's top-k.
Precision: fraction of the agent's k accessions that the labeler marked.
Both are None for claims where the labeler provided no evidence (verdict =
not_yet_resolvable with empty expected_evidence) — division by zero would
otherwise silently report 0.

Verdict accuracy: exact match between gold.verdict and agent.Verdict.verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from schemas import EvidenceBundle, Verdict
from verifier.gold import GoldLabel


@dataclass(frozen=True)
class PerClaimResult:
    claim_id: str
    recall_at_k: Optional[float]
    precision: Optional[float]
    verdict_match: Optional[bool]  # None if verdict not scored (evidence-mode only)


def score_retrieval(gold: GoldLabel, bundle: EvidenceBundle, *, k: int) -> PerClaimResult:
    """Score one claim's retrieval against gold."""
    expected = {e.accession_no for e in gold.expected_evidence}
    retrieved = [it.accession_no for it in bundle.items][:k]
    if not expected:
        # No labeled evidence → recall undefined.
        return PerClaimResult(
            claim_id=gold.claim_id,
            recall_at_k=None,
            precision=None,
            verdict_match=None,
        )
    retrieved_set = set(retrieved)
    recall = len(expected & retrieved_set) / len(expected)
    precision = (len(expected & retrieved_set) / len(retrieved)) if retrieved else 0.0
    return PerClaimResult(
        claim_id=gold.claim_id,
        recall_at_k=recall,
        precision=precision,
        verdict_match=None,
    )


def score_verdict(gold: GoldLabel, verdict: Verdict) -> bool:
    return gold.verdict == verdict.verdict


def aggregate(results: list[PerClaimResult]) -> dict:
    """Mean retrieval metrics over scorable claims; verdict accuracy over all
    scored claims."""
    recall_scored = [r for r in results if r.recall_at_k is not None]
    precision_scored = [r for r in results if r.precision is not None]
    verdict_scored = [r for r in results if r.verdict_match is not None]

    mean = lambda xs: (sum(xs) / len(xs)) if xs else None

    return {
        "n_claims": len(results),
        "n_recall_scored": len(recall_scored),
        "mean_recall_at_k": mean([r.recall_at_k for r in recall_scored]),
        "mean_precision": mean([r.precision for r in precision_scored]),
        "verdict_accuracy": mean([1.0 if r.verdict_match else 0.0 for r in verdict_scored]),
    }
```

- [ ] **Step 4: Add the CLI (in the same file)** — *implemented; design changed from the original plan*

**Design change discovered during implementation.** The original plan assumed the CLI would read persisted trace files keyed by claim_id (`--traces <dir>`, glob `<claim_id>__*.json`, parse an `output` field). Reading `src/verifier/trace.py` showed that's not viable: traces are named `verify_{mode}_{timestamp}.json` (not keyed by claim_id), and they store only raw message records — **no structured `EvidenceBundle`/`Verdict`, no `output` field**. `verify()` returns the structured output in memory and never persists it.

So the CLI **runs the agent live per gold claim** instead of parsing traces:

```
python -m verifier.eval --gold <jsonl|dir> --claims <pilot_csv> \
    [--mode evidence|verdict] [--k 8] [--no-cache] [--output <csv>]
```

For each gold label: look up the claim row in `--claims` (the pilot CSV) by `claim_id`, build a `Claim` (NaN cells dropped so Pydantic fills defaults), call `verify(claim, mode, trace=False, cache=...)`, then `score_retrieval` (+ `score_verdict` in verdict mode). Skips with a warning on unknown claim_id or `UnsupportedClaimTypeError` (numerical_guidance). The SQLite chat cache (on by default) makes re-scoring cheap after the first pass; `--no-cache` forces fresh calls.

The pure functions (`score_retrieval`/`score_verdict`/`aggregate`) are unchanged from Steps 1–3 and stay offline-unit-tested. The agent imports are deferred inside `_cli()` so importing `verifier.eval` for the unit tests doesn't pull in the agent stack or require the model env vars.

- [ ] **Step 5: Run the offline tests**

```bash
mamba run -n truth pytest tests/test_eval.py -v
```

Expected: all PASS (8 tests).

- [ ] **Step 6: Smoke-test the CLI**

Confirm the CLI parses (a full live run needs a real gold JSONL + a built index):

```bash
mamba run -n truth python -m verifier.eval --help
```

A real run is part of the pilot flow in "Done criteria" below:
`--gold data/gold/pilot_tsla.jsonl --claims data/claims/pilot_claims.csv --mode evidence`.

- [ ] **Step 7: Commit (ask user)**

Suggested message: `feat(verifier): add eval scorer (recall@k, precision, verdict accuracy)`

---

## Section E — Externalize model identifiers to env vars

### Task 5: Replace hardcoded models with `<TASK>_MODEL` env vars + fallback

**Context.** Today the model identifiers are baked into source files. We want each task type configured via a dedicated env var, **enforced at the env level with no hardcoded fallback in the source** — the resolver raises `RuntimeError` if the var is unset. `.env.example` ships populated working values, so `cp .env.example .env` yields a runnable config; changing any var A/Bs a different model for that stage. Naming convention: `<TASK>_MODEL` suffix. No shared `MODEL` value — different stages may want different models.

| Env var | `.env.example` value | Replaces | Used in |
|---|---|---|---|
| `EXTRACTOR_MODEL` | `openai:gpt-4o-mini` | `MODEL_NAME` in `src/extractor/extract.py` | Claim extraction |
| `VERIFIER_AGENT_MODEL` | `openai:gpt-4o-mini` | `MODEL_NAME` at the agent-loop call site in `src/verifier/agent.py` | Tool-using verifier agent |
| `VERIFIER_PARSER_MODEL` | `openai:gpt-4o-mini` | same constant, but at the structured-output parser call site | Verdict-mode JSON parser |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | `EMBED_MODEL` in `src/verifier/index.py` | FAISS doc + query embeddings |

**Enforcement, not fallback.** The values above live in `.env.example` only, not in the source. If a var is unset at use time the resolver raises a `RuntimeError` naming the missing var and pointing at `.env.example`. The extractor keeps its explicit-arg override (`--model` / `model_name=`) which wins over the env var; the verifier and embeddings have no explicit override, so it's env-or-raise.

**Implementation gotcha (load-bearing).** Env vars must be read **at use time inside functions**, not at module import. The entrypoint CLIs call `load_dotenv()` inside `main()` — by then the extractor/verifier modules have already been imported, so any module-level constants would have been captured before `.env` loaded. Pattern: a small `_resolve_*_model(...)` helper called inside `build_extractor` / the embedding factory / each `init_chat_model` site, doing `explicit or os.environ.get(env_var)` then raising if still empty.

**Consequence for live tests.** `pytest -m live` and any live CLI run now require these vars in the developer's actual `.env` (not just `.env.example`). A `.env` predating this change must add the four vars or live runs raise.

**Out of scope.** Tokenizer (`cl100k_base`) stays tied to the embedding-model family in code — no env var. If someone swaps in a non-OpenAI embed model later they need to think about tokenizer compatibility separately. API key envs (`OPENAI_API_KEY`, `WRDS_USERNAME`, `SEC_USER_AGENT`) are already env-driven; no changes.

**Files:**
- Modify: `src/extractor/extract.py` (replace `MODEL_NAME`; thread resolver through `build_extractor`)
- Modify: `src/extractor/run.py` (drop `MODEL_NAME` import; `--model` default `None`)
- Modify: `src/verifier/agent.py` (two getters; update both `init_chat_model` calls)
- Modify: `src/verifier/index.py` (replace `EMBED_MODEL`; update `_make_embeddings_client`)
- Modify: `.env.example` (append commented "Model selection (optional)" block)
- Create / Modify: `tests/test_model_resolver.py` (new) — covers env-var override + explicit-arg precedence

- [ ] **Step 1: Locate the existing constants**

```bash
grep -n "MODEL_NAME\|EMBED_MODEL" src/extractor/*.py src/verifier/*.py
```

Expected: confirms the exact line numbers for each constant. There should be one in `extract.py`, one in `agent.py` (used at two call sites), and one in `index.py`. If grep surfaces additional occurrences (e.g., extractor `run.py` imports `MODEL_NAME` for its `--model` default), note them — they all need updating.

- [ ] **Step 2: Write failing tests for the resolver behavior**

Create `tests/test_model_resolver.py`:

```python
"""Env-var resolution for model identifiers.

Each task module exposes a private `_resolve_*_model` callable that does
explicit-arg > env-var > default. These tests pin that precedence.
"""

import importlib

import pytest


def test_extractor_resolver_explicit_wins(monkeypatch):
    monkeypatch.setenv("EXTRACTOR_MODEL", "openai:gpt-via-env")
    from extractor.extract import _resolve_extractor_model
    assert _resolve_extractor_model("openai:gpt-explicit") == "openai:gpt-explicit"


def test_extractor_resolver_env_wins_over_default(monkeypatch):
    monkeypatch.setenv("EXTRACTOR_MODEL", "openai:gpt-via-env")
    from extractor.extract import _resolve_extractor_model
    assert _resolve_extractor_model(None) == "openai:gpt-via-env"


def test_extractor_resolver_default_when_unset(monkeypatch):
    monkeypatch.delenv("EXTRACTOR_MODEL", raising=False)
    from extractor.extract import _resolve_extractor_model
    assert _resolve_extractor_model(None) == "openai:gpt-4o-mini"


def test_verifier_agent_resolver(monkeypatch):
    monkeypatch.setenv("VERIFIER_AGENT_MODEL", "openai:via-env")
    from verifier.agent import _resolve_agent_model
    assert _resolve_agent_model() == "openai:via-env"
    monkeypatch.delenv("VERIFIER_AGENT_MODEL")
    assert _resolve_agent_model() == "openai:gpt-4o-mini"


def test_verifier_parser_resolver_independent_from_agent(monkeypatch):
    """Parser model is its own env var; setting agent's must not change parser's."""
    monkeypatch.setenv("VERIFIER_AGENT_MODEL", "openai:agent-only")
    monkeypatch.delenv("VERIFIER_PARSER_MODEL", raising=False)
    from verifier.agent import _resolve_parser_model
    assert _resolve_parser_model() == "openai:gpt-4o-mini"


def test_embedding_resolver(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-large")
    from verifier.index import _resolve_embedding_model
    assert _resolve_embedding_model() == "text-embedding-3-large"
    monkeypatch.delenv("EMBEDDING_MODEL")
    assert _resolve_embedding_model() == "text-embedding-3-small"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
mamba run -n truth pytest tests/test_model_resolver.py -v
```

Expected: FAIL on `ImportError` for the four `_resolve_*` helpers.

- [ ] **Step 4: Update `src/extractor/extract.py`**

Replace the `MODEL_NAME` constant with a default + resolver:

```python
import os

DEFAULT_EXTRACTOR_MODEL = "openai:gpt-4o-mini"


def _resolve_extractor_model(explicit: str | None) -> str:
    """Resolve the extractor model name: explicit arg > EXTRACTOR_MODEL env > default."""
    if explicit:
        return explicit
    return os.environ.get("EXTRACTOR_MODEL") or DEFAULT_EXTRACTOR_MODEL
```

In `build_extractor(model: str | None = None, ...)`, change the body so the model is resolved at call time:

```python
def build_extractor(model: str | None = None, ...):
    model_name = _resolve_extractor_model(model)
    return init_chat_model(model_name, ...)
```

Search for any other internal references to `MODEL_NAME` in `extract.py` and replace them with `_resolve_extractor_model(...)` calls. Confirm with `grep -n MODEL_NAME src/extractor/extract.py` — expect zero hits after the change.

- [ ] **Step 5: Update `src/extractor/run.py`**

Remove the `MODEL_NAME` import. Change the CLI's `--model` argument to default to `None`:

```python
p.add_argument("--model", default=None,
               help="Override the extractor model (default: EXTRACTOR_MODEL env or openai:gpt-4o-mini)")
```

Thread the `None` through into `build_extractor` (which now handles `None` via the resolver). Confirm with `grep -n MODEL_NAME src/extractor/run.py` — zero hits.

- [ ] **Step 6: Update `src/verifier/agent.py`**

Same pattern, two resolvers:

```python
import os

DEFAULT_VERIFIER_AGENT_MODEL = "openai:gpt-4o-mini"
DEFAULT_VERIFIER_PARSER_MODEL = "openai:gpt-4o-mini"


def _resolve_agent_model() -> str:
    return os.environ.get("VERIFIER_AGENT_MODEL") or DEFAULT_VERIFIER_AGENT_MODEL


def _resolve_parser_model() -> str:
    return os.environ.get("VERIFIER_PARSER_MODEL") or DEFAULT_VERIFIER_PARSER_MODEL
```

Update the two `init_chat_model(...)` call sites (currently both reading the old `MODEL_NAME` constant): the agent-loop site uses `_resolve_agent_model()`, the structured-output parser site uses `_resolve_parser_model()`. Delete the `MODEL_NAME` constant. Confirm with `grep -n MODEL_NAME src/verifier/agent.py` — zero hits.

- [ ] **Step 7: Update `src/verifier/index.py`**

```python
import os

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


def _resolve_embedding_model() -> str:
    return os.environ.get("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL


def _make_embeddings_client():
    return OpenAIEmbeddings(model=_resolve_embedding_model())
```

Delete the old `EMBED_MODEL` constant. Confirm with `grep -n EMBED_MODEL src/verifier/index.py` — zero hits.

- [ ] **Step 8: Run the resolver tests**

```bash
mamba run -n truth pytest tests/test_model_resolver.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 9: Run the full offline suite**

```bash
mamba run -n truth pytest -v
```

Expected: green. Existing extractor/verifier tests that pass explicit `model=` strings keep working unchanged; tests that don't pass a model now pick up the resolver default (still `openai:gpt-4o-mini`), so behavior is invariant.

- [ ] **Step 10: Append a "Model selection (required)" block to `.env.example`**

```
# --- Model selection (required) ---------------------------------------------
# Required: one model identifier per task type. The code has no hardcoded
# fallback — these must be set (this template populates working defaults).
# Change any of them to A/B a different model for that stage; read at use time,
# so a change takes effect on the next run.
EXTRACTOR_MODEL=openai:gpt-4o-mini
VERIFIER_AGENT_MODEL=openai:gpt-4o-mini
VERIFIER_PARSER_MODEL=openai:gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small
```

Lines are **uncommented** — they're required, so `cp .env.example .env` must produce a runnable config.

- [ ] **Step 11: Commit (ask user)**

Suggested message: `feat: externalize model identifiers to per-task env vars`

---

## Section F — Documentation + final wrap

### Task 6: Update README and CLAUDE.md

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add a "Gold-set evaluation" section to README**

Insert after the "Verification — iter-2 real EDGAR retrieval" section. Document:
- Where gold labels live (`data/gold/`)
- The labeling format (one-line reference; full doc at `data/gold/README.md`)
- How to score (`python -m verifier.eval --gold ... --traces ... --k 8`)
- That `docs/labeling_rubric.md` is the labeler's authoritative reference

- [ ] **Step 2: Add model-selection env vars to the README**

Add a short subsection (in the iter-2 verification section, or under setup — wherever flows best) listing the four `<TASK>_MODEL` env vars with their defaults, and the one-liner that they're read at use time from `.env`. Point at `.env.example` for the canonical list.

- [ ] **Step 3: Update CLAUDE.md workstream D bullet**

The current `workstream D` bullet says "evaluation & writeup". Add a sentence noting that the pilot-eval scaffolding (gold schema, rubric, scorer) landed on `feature/verifier-iteration3` on 2026-05-XX (fill in actual date at commit time). One sentence, not a paragraph — keep CLAUDE.md tight.

- [ ] **Step 4: Resolve open items in CLAUDE.md**

Item #2 (LLM provider choice per stage): replace the "verifier hardcoded at `verifier/agent.py:46`" line with a pointer to the four env vars (`EXTRACTOR_MODEL`, `VERIFIER_AGENT_MODEL`, `VERIFIER_PARSER_MODEL`, `EMBEDDING_MODEL`).

Item #3 (Capital allocation grading rubric):

> 3. ~~Capital allocation grading rubric~~ — v0 lives in `docs/labeling_rubric.md` (2026-05-23); refine after pilot labeling

- [ ] **Step 5: Strike the env-var item from `docs/future_optimizations.md`**

The "Externalize model/third-party specs to env vars" section there is now done — replace its body with a one-line "Landed in iter-3, see commit `<hash>`" pointer (or delete entirely if the user prefers).

- [ ] **Step 6: Commit (ask user)**

Suggested message: `docs: README + CLAUDE.md updates for iter-3 eval scaffolding + env-var models`

---

## Done criteria

iter-3-eval-prep is complete when:

1. `mamba run -n truth pytest -v` is green (all offline tests pass), including the 6 new resolver tests in `tests/test_model_resolver.py`.
2. `data/gold/template.jsonl` validates: `mamba run -n truth python -c "from verifier.gold import load_gold_labels; load_gold_labels('data/gold/template.jsonl')"` prints a `GoldLabel` instance.
3. `docs/labeling_rubric.md` exists and the user has read it (rubric content needs human review; tests can't validate this).
4. `python -m verifier.eval --help` runs without error.
5. `grep -n "MODEL_NAME\|EMBED_MODEL" src/extractor/ src/verifier/` returns zero hits — all four model identifiers come from env-var resolvers.
6. CLAUDE.md and README updated; open items #2 and #3 resolved.

Once those land, the path to the pilot labeling sprint is:

1. **Pick the pilot subset** — ~15-20 capital_allocation claims from `data/claims/pilot_claims.csv`, TSLA-only (the only index that's been smoke-validated). The user picks; not a code task.
2. **Label them** — write `data/gold/pilot_tsla.jsonl` using the schema. ~2-3 hours.
3. **Run the verifier on each in evidence mode** — produces trace files.
4. **Score** — `mamba run -n truth python -m verifier.eval --gold data/gold/pilot_tsla.jsonl --traces data/traces/ --k 8`.
5. **Iterate** — fix what the scorer reveals (likely candidates: chunker tweaks, prompt adjustments, the iter-3 robustness backlog items).

That iteration loop is iter-3's *next* plan, written after we see the first scorer output. Not this PR.
