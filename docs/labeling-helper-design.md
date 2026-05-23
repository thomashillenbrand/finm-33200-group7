# Design — Gold-Set Labeling Helper (`verifier.label`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal.** Give a human team member a CLI that, for one extracted claim, surfaces the candidate SEC filings to read and helps them locate + copy the relevant passages into a valid gold-set row — *without* the verification agent in the loop. The friction this removes is mechanical: finding accession numbers, locating passages in HTML, and hand-formatting JSON. The human still reads the filings and assigns the verdict.

**Non-goals.** Auto-labeling, verdict suggestion, semantic/embedding retrieval, and writing verdicts. Those either belong to the agent (`verifier.run` / `verifier.eval`) or to the human labeler — not here.

---

## Why a separate tool (and not `verifier.run`)

The gold set's job is to *grade* the agent — both its retrieval (recall@k) and, in verdict mode, its verdict. If a labeler seeds `expected_evidence` from what the agent surfaced (`verifier.run --mode evidence`, which ranks with the same FAISS index + embeddings the eval grades), then recall@k is circular: the agent is scored against its own output. `data/gold/README.md` already states the rule — "label the evidence and verdict independently of what the agent surfaced."

So this helper finds evidence by an **independent mechanism: deterministic keyword/regex search over the raw filing text.** Different failure modes from dense retrieval (keyword misses paraphrase; dense misses exact figures), transparent (the human sees *why* a line matched), and no shared ranking with the system under test. The gold set stays a fair yardstick.

### The independence guarantee (load-bearing — enforce in review)

`verifier/label.py` must **not** import or call any of: `verifier.agent` / `verify`, `faiss`, `OpenAIEmbeddings`, `verifier.tools`, or read `index/chunks.parquet` / `index/faiss.index`. It reads only the SEC index parquet and the raw filing HTML. It reuses exactly one thing from `verifier/index.py`: `extract_text_from_html` — that is pure HTML→text extraction, not a ranking step, so sharing it does not reintroduce circularity. Add a one-line module docstring note stating this constraint so a future edit doesn't quietly wire in `verify()`.

---

## Branch & conventions

- **Branch:** off the current `feature/verifier-iteration3` (or a fresh `feature/labeling-helper` — user's call; user branches).
- Python runs inside the `truth` mamba env: prefix with `mamba run -n truth …`.
- `pytest` runs from repo root with the default `addopts = "-m 'not live'"`. This helper needs **no live tests** — it makes no network calls.
- Commits use the project's bare-message style (no Claude-Code attribution footer).
- The user owns all git writes. Where this plan says "commit", pause and ask.

---

## Inputs on disk (confirmed against the code)

| What | Path | Notes |
|---|---|---|
| Claim rows | `data/claims/pilot_claims.csv` | `schemas.Claim`; fields used below |
| SEC filing index | `pulled_data/<TICKER>/SEC/<TICKER>_sec_filings_index.parquet` | **camelCase** cols: `localPath`, `accessionNumber`, `form`, `filingDate` |
| Filing HTML | `pulled_data/<TICKER>/SEC/<localPath>` | primary doc, `.htm`/`.html` |
| (optional) Compustat | `pulled_data/<TICKER>/Compustat/<TICKER>_compustat_quarterly.parquet` | YTD cash-flow cols; see stretch tool |

`Claim` fields the helper displays: `claim_id`, `ticker`, `company`, `call_date`, `claim_type`, `verbatim_quote`, `summary`, `horizon_raw`, `horizon_period`, `horizon_end_date`. (`verifier.eval._load_claims_by_id` already loads this CSV by id — reuse that pattern or lift it to a shared helper.)

Output schema the helper emits toward: `verifier.gold.GoldLabel` / `GoldEvidence` (`accession_no`, `form ∈ {10-K,10-Q,8-K}`, `filing_date`, `quote ≤500 chars`, optional `section`).

---

## CLI surface

Single command, progressive disclosure via flags (kept simple — team programming skill varies widely). All output to stdout; **v1 writes nothing** (no clobber risk) — the human pastes into their `data/gold/pilot_<ticker>.jsonl`.

```
mamba run -n truth python -m verifier.label \
    --claims data/claims/pilot_claims.csv \
    --claim-id TSLA_20200129_87696b9b \
    --labeler tom \
    [--query "share repurchase"] [--regex] \
    [--forms 10-Q,8-K] [--context 240] \
    [--from 2020-01-29] [--until 2021-06-30]
```

Behavior by what's passed:

1. **claim-id only** → prints (a) the claim block (quote, summary, horizon, call_date), (b) the candidate filing list (form, filing_date, accession, localPath) for filings filed after `call_date`, sorted by date, (c) a usage hint to add `--query`, and (d) a blank `GoldLabel` skeleton to copy.
2. **`--query TERM`** → additionally extracts text per candidate filing (`extract_text_from_html`), finds keyword (or `--regex`) matches, and for each prints a header `[<form> filed <date> | accession <no> | open: <path>]`, a context window (`--context` chars, default ~240) around the match, and a **ready-to-paste `GoldEvidence` JSON fragment** with `accession_no`/`form`/`filing_date`/`quote` filled and `section` null. Quote is trimmed to ≤500 chars (schema cap) with a notice if truncated.

The human reads the matches (opening `localPath` in a browser when the evidence is a financial-statement table that flattens poorly as text), drops the fragments they judge relevant into the skeleton's `expected_evidence`, fills `verdict`/`confidence`/`labeler_notes`, and appends the line. They then validate with the existing one-liner in `data/gold/README.md`.

### Example skeleton printed (verdict left as a placeholder the human replaces)

```jsonc
{"claim_id":"TSLA_20200129_87696b9b","ticker":"TSLA","labeler":"tom","labeled_at":"2026-05-23T14:02:00","expected_evidence":[],"verdict":"<FILL: verified|partially_verified|contradicted|not_yet_resolvable>","confidence":"<FILL: high|medium|low>","labeler_notes":""}
```

(The placeholder verdict means the skeleton is intentionally *not* loadable until filled — `load_gold_labels` rejects it, which is the right failure if someone forgets to fill it.)

---

## Optional / stretch tools (recommend deferring from v1 — "lean narrower")

- **Compustat cross-reference (`--compustat`). DECIDED: deferred (2026-05-23).** Idea, for the record: print the post-call quarters' cash-flow line items (`prstkcy` buybacks, `dvy` dividends, `capxy` capex, `dltisy`/`dltry` debt — YTD, so first-difference within fiscal year per README) as a *magnitude orientation* aid: "claim said ~$1B buyback; Compustat shows ~$700M repurchases over the next 3 quarters — go confirm the line in the 10-Q." **Hard caveat if ever added:** the cited `expected_evidence` must be the SEC filing (its `accession_no`), never Compustat — capital-allocation grading is SEC-sourced by scope, and Compustat is the *numerical_guidance* source. Risk that drove the defer: a labeler anchors on the Compustat number instead of reading the filing. Add only if labelers report they can't find magnitudes.
- **Section detection.** Auto-fill `GoldEvidence.section` from the nearest preceding heading (`<h*>`/bold table caption). Nice-to-have; `extract_text_from_html` currently discards structure, so this needs its own light parse. Defer.

---

## Open questions (decide before/at implementation)

1. **Amended forms. DECIDED: filter out in v1 (2026-05-23).** `GoldEvidence.form` is strictly `{10-K, 10-Q, 8-K}`. The helper restricts candidates to those three exact forms; `10-K/A` etc. are dropped. Revisit (and extend the gold schema) only if a labeler needs an amendment.
2. **Print-only vs. append.** v1 prints; a later `--append <path>` could write the skeleton. Kept out of v1 to avoid clobbering a labeler's in-progress file.
3. **Reuse vs. copy `_load_claims_by_id`.** Lifting it from `eval.py` to a small shared module is cleaner but touches `eval.py`; copying keeps the diff local. Either is fine — implementer's call, note it in the commit.

---

## Tasks

### Task 1 — Scaffold + claim/filing display
- [ ] Create `src/verifier/label.py` with the independence-constraint docstring note. Add `_load_filing_index(ticker) -> pd.DataFrame` (reads the SEC index parquet, normalizes the camelCase columns), and `candidate_filings(claim, *, forms, from_date, until_date) -> DataFrame` (filter `filingDate > call_date`, restrict to `forms`, sort by date).
- [ ] Add the claim loader (reuse `eval._load_claims_by_id` pattern) and a `_render_claim(claim)` printer.
- [ ] Wire a flat argparse CLI (`--claims`, `--claim-id`, `--labeler`, `--forms`, `--from`, `--until`, `--query`, `--regex`, `--context`).
- [ ] Verify: `mamba run -n truth python -m verifier.label --help` parses; with `--claim-id` it lists filings.

### Task 2 — Keyword search + evidence fragments
- [ ] `search_filing(text, query, *, regex, context) -> list[Match]` returning `(char_start, char_end, snippet)` for each hit (case-insensitive substring by default; `--regex` compiles the query).
- [ ] For each candidate filing with ≥1 hit: extract text via `extract_text_from_html`, run `search_filing`, print the header + context + a `GoldEvidence`-shaped JSON fragment (quote trimmed to ≤500). Build the fragment by constructing a `GoldEvidence` and dumping it, so the printed shape is schema-true.
- [ ] Verify against a tiny fixture corpus (see Task 4) that matches print with correct accession/form/date.

### Task 3 — Skeleton emission
- [ ] `_render_skeleton(claim, labeler) -> str` printing the placeholder `GoldLabel` line (empty `expected_evidence`, placeholder verdict/confidence). Print it whenever the CLI runs.
- [ ] Confirm the *filled* shape round-trips: a hand-completed example validates via `verifier.gold.load_gold_labels`.

### Task 4 — Tests (`tests/test_label.py`, offline)
- [ ] Build a fixture: temp dir as `PULLED_DATA_ROOT` (monkeypatch — `index.PULLED_DATA_ROOT` is already patchable; `label.py` should resolve paths through the same root or its own patchable constant) with `pulled_data/FAKE/SEC/FAKE_sec_filings_index.parquet` + two small `.htm` files (one 10-Q with a "repurchase" line, one 8-K).
- [ ] Cover: filing list filters out pre-call dates and non-requested forms; keyword search finds the line and reports the right `accessionNumber`/`form`/`filingDate`; regex mode; quote truncation at 500; emitted fragment parses as `GoldEvidence`; skeleton string has the placeholder verdict and is *rejected* by `load_gold_labels` until filled.
- [ ] **Independence test:** assert `label.py`'s import graph pulls in no agent/faiss/embeddings module (e.g. import `verifier.label` and assert `"faiss"`/`"verifier.agent"` not in `sys.modules` attributable to it, or simply grep-assert the source has no such import). Keeps the guarantee from regressing.

### Task 5 — Docs
- [ ] Add a "Using the labeling helper" subsection to `data/gold/README.md` (the command, the read-filings-yourself reminder, the paste-and-validate loop). One short block.
- [ ] One line in `README.md` "Gold-set evaluation" section pointing at the helper.

### Task 6 — Commit (ask user)
Suggested message: `feat(verifier): add agent-free gold-labeling helper CLI`

---

## Done criteria

1. `mamba run -n truth pytest -v` green, including the new `tests/test_label.py` and the independence test.
2. `mamba run -n truth python -m verifier.label --claims data/claims/pilot_claims.csv --claim-id <real id>` prints the claim, its post-call filings, and a skeleton.
3. Adding `--query "repurchase"` prints matches with paste-ready `GoldEvidence` fragments.
4. `verifier/label.py` imports none of: `verifier.agent`, `faiss`, `OpenAIEmbeddings`, `verifier.tools`; reads no `index/` artifacts.
5. A hand-filled row produced from the helper validates via `verifier.gold.load_gold_labels`.
