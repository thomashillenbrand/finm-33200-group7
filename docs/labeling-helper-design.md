# Gold-Set Labeling Helper (`verifier.label`) — design / as-built

> **Status: implemented (2026-05-23).** This describes the tool as built. It
> supersedes the original *print-only* plan: the helper was built as an
> interactive, single-command grader, not a print-only two-pass tool — see
> "Divergences from the original plan" below. Pending review by Thomas
> (workstream C), since it touches `src/verifier/`.
>
> **2026-05-25:** this human helper now has an LLM sibling,
> `src/verifier/autolabel.py` (`python -m verifier.autolabel`), which reuses this
> module's deterministic keyword sweep but has GPT-5.5 + the rubric pick evidence
> and assign the verdict instead of a human. The active gold set
> (`data/gold/auto/`) is produced by it — LLM-labeled, not hand-labeled. See
> `docs/autolabel-gold-eval-design.md`.

## Goal

Give a labeler a single command that, for one extracted claim, surfaces the
candidate SEC filings, lets them pick the relevant passages and assign a verdict
interactively, and appends one validated `GoldLabel` row to the gold JSONL — no
hand-editing of files. It removes the *mechanical* friction of labeling (finding
accession numbers, locating passages in HTML, formatting JSON); the human still
reads the filings and decides the verdict (see `docs/labeling_rubric.md`).

## Independence constraint (load-bearing — do not break)

The gold set grades the verification agent's retrieval (recall@k). If a labeler
seeds evidence from what the agent surfaced, that score is circular. So
`src/verifier/label.py` must NOT import or call `verifier.agent` / `verify`,
`faiss`, `OpenAIEmbeddings`, or `verifier.tools`, and must NOT read the `index/`
artifacts (`chunks.parquet` / `faiss.index`). It finds evidence by a
deterministic keyword sweep over raw filing text — never embeddings or an LLM
ranker. The test `test_label_module_imports_nothing_from_agent_or_index`
enforces the import constraint so a future edit cannot quietly reintroduce it.

The helper has its own small `_html_to_text` rather than reusing
`verifier.index.extract_text_from_html`: importing `verifier.index` would pull
`faiss` / `OpenAIEmbeddings` into the helper's import graph transitively, which
would itself break the constraint above.

## How it works (as built)

One command per claim:

```
python -m verifier.label --claims <claims.csv> --claim-id <id> --labeler <you>
```

1. Loads the claim from the claims CSV.
2. If the claim already has a label in the gold file, asks before adding another.
3. Builds the candidate filings: 10-K / 10-Q / 8-K filed after the call,
   bounded by the claim's resolved horizon (plus a reporting lag), or ~2 years
   past the call when the horizon is unresolved — so an open-ended claim does
   not pull every filing through to the present.
4. Runs a deterministic keyword sweep (the per-claim-type term list), drops
   inline-XBRL noise, ranks hits by a transparent keyword-specificity score
   (specific line-item phrases / dollar-adjacent hits first), and prints the
   claim plus the candidate passages.
5. Interactive `evidence>` prompt: `<numbers>` (e.g. `1,3`) to pick evidence,
   `more <term>` to search an extra keyword, `all` to show every hit, `none`,
   or `quit`.
6. Prompts for verdict (the four-bucket menu), confidence, and notes. A
   decisive verdict with no evidence selected is rejected and re-prompted.
7. Validates the `GoldLabel` and **appends** it to
   `data/gold/pilot_<ticker>.jsonl` — append-only, never rewrites.

Optional flags: `--gold`, `--forms`, `--from`, `--until`, `--context`.

## Divergences from the original print-only plan

- **Interactive, not print-only.** The original plan printed a skeleton for the
  human to hand-edit. For an ~80-claim labeling effort that is too much
  friction, so grading happens in the terminal and the tool writes the
  validated row itself. It still only appends — it never rewrites the file.
- **Auto keyword sweep, not manual `--query`.** The tool runs the standard
  per-type term list itself; `more <term>` covers custom searches. It is still
  deterministic keyword search, so the independence property is unchanged.
- **Own `_html_to_text`, not `verifier.index.extract_text_from_html`** — see the
  independence section: reusing it would pull `faiss` into the helper.
- **`verifier/__init__.py` made lazy.** That file eagerly imported the agent
  (`from verifier.agent import verify, verify_from_dict`), so importing *any*
  `verifier` submodule — including this lightweight, agent-free helper — loaded
  the whole agent stack and `faiss`. It was changed to a PEP 562 `__getattr__`
  lazy export so light submodules import without `faiss` / `deepagents`.
  (Separately: `faiss` is imported by `verifier/corpus.py` but is missing from
  `pyproject.toml` dependencies — a verifier packaging bug worth fixing.)

## Inputs / outputs on disk

| What | Path |
|---|---|
| Claim rows | `data/claims/*.csv` (`schemas.Claim`) |
| SEC filing index | `Pulled_data/<TICKER>/SEC/<TICKER>_sec_filings_index.parquet` — camelCase columns: `accessionNumber`, `filingDate`, `form`, `localPath` |
| Filing HTML | `Pulled_data/<TICKER>/SEC/<localPath>` — `localPath` uses Windows separators; the helper normalizes them |
| Output | `data/gold/pilot_<ticker>.jsonl` — appended `GoldLabel` rows |

## Non-goals (unchanged)

Auto-labeling, verdict *suggestion*, and semantic / embedding retrieval. The
tool surfaces candidates and records the human's decision; it never proposes a
verdict, and any ordering it applies is a transparent deterministic
keyword-specificity rank (`_relevance`: multi-word line-item phrases and
dollar-adjacent hits first) — never an embedding or LLM relevance ranking. The
labeler still reads the filing and decides what counts as evidence.

## Files & tests

- `src/verifier/label.py` — the helper.
- `tests/test_label.py` — 17 offline tests; the interactive session is driven
  by an injected input function. Includes the independence-import test.
- `src/verifier/__init__.py` — the lazy-import change.
- `docs/labeling_rubric.md` — the verdict rubric the labeler consults (draft,
  pending the rubric owner).
