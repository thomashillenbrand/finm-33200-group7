# AI Usage Statement

**Course:** FINM 33200 — Generative and Agentic AI for Finance
**Team (Group 7):** Brendan Kehoe, Seback Oh, Tejaswini Shashidhar, Thomas Hillenbrand
**Project:** Auditable historical truthfulness profiles for public companies

AI is used in this project in two distinct ways: as a **development assistant** that
helped us build the code, and as a set of **components inside the system itself**.
We separate them below, then describe how we checked the outputs in each case.

---

## 1. AI as a development assistant

We used **Claude Code** (Anthropic's CLI, Claude Opus) as a pair-programming
assistant throughout development. It helped with:

- **Scaffolding the packages** — the `extractor`, `verifier` (FAISS index + agentic
  filing search), `autochecker` (Compustat-backed numerical grader), and `profiles`
  builders were drafted with Claude and then revised by us.
- **Tests and refactors** — generating the bulk of the 200+ automated tests, and
  carrying out mechanical refactors (e.g. unifying two independently-built extraction
  prototypes into one `extractor` package).
- **Documentation** — drafting `README.md`, the `docs/` design notes, and the running
  `CLAUDE.md` project log.
- **Debugging** — diagnosing issues such as time-leak risks in the retrieval layer and
  structured-output parsing failures.

**Human ownership of decisions.** Architecture and scope decisions were made by the
team, not the assistant. For example, the merge decisions for the extractor (parquet-only
input, lightweight schema, single-CSV contract) and the locked project scope (4 firms,
SEC-EDGAR-only verification) were team choices; Claude implemented against them. We
reviewed every change before committing.

## 2. AI as components of the system

The pipeline is itself an LLM system. Each stage uses a model, selected per-stage via
environment variables (`.env.example`) so the choice is auditable and A/B-able without
code edits:

| Stage | Tool / model | Role |
|-------|--------------|------|
| Claim extraction | OpenAI structured output via LangChain `init_chat_model` (`gpt-4o-mini` default; the full run used **GPT-5.5**, prompt `b-extract-v5`) | Pull typed forward-looking claims from earnings-call transcripts |
| Embeddings / retrieval | `text-embedding-3-small` + FAISS, per ticker | Semantic search over SEC filings for the verifier agent |
| Verification agent | **GPT-5.1** (no rubric) | Agentic search over SEC filings; returns cited evidence (and, in verdict mode, a label) |
| Numerical grader (autochecker) | OpenAI SDK structured output | Two-stage screen + compare against a Compustat quarterly panel |
| Gold-set labeler | **GPT-5.5** + grading rubric | Assign reference verdicts for evaluation |

A load-bearing design choice: the **labeler (GPT-5.5 + rubric) is a different model from
the graded agent (GPT-5.1, which never sees the rubric)**, so the agent cannot grade to
the test. This is enforced by tests.

## 3. How we checked the outputs

**For the development assistant (Claude Code):**
- We read and reviewed every generated diff before committing it; nothing was merged
  unread.
- **200+ automated tests** (offline) plus **live tests** (`pytest -m live`) back the
  packages; we ran these as the acceptance gate for assistant-written code.
- We hand-inspected representative runs — e.g. a 5-claim verifier smoke run confirming
  **0 time-leaks and 0 verdict-language leakage across 61 retrieved chunks**.

**For the in-pipeline models:**
- **Structural guards, not trust.** The no-time-leak guarantee (the agent never sees
  filings dated after the claim) is enforced at the *tool layer*, not by prompting; the
  search window also has a horizon ceiling keyed on each filing's reporting date; and
  autochecker citations are scrubbed against the actual data panel to drop hallucinated
  pointers.
- **An evaluation harness.** `verifier.eval` scores agent output against the gold set on
  recall@k, citation precision, and verdict accuracy, writing per-run records (with the
  git HEAD) so iterations are comparable. Best validated config: **recall@8 0.82 /
  verdict accuracy 0.71 / forward-control abstention 5/6** on capital-allocation claims.
- **The agent surfaces evidence without proposing a verdict** to the labeler, so the
  agent's opinion cannot bias the reference labels.

## 4. Honest limitations

We flag these as shortcomings and future work rather than hiding them:

- **The gold set is LLM-labeled, not hand-labeled** — a deliberate, time-constrained
  substitution for the proposal's hand-labeling sprint. Using a different model for
  labeling vs. grading *reduces* but does not *eliminate* model-vs-model circularity.
- **Verdict-mode structured-output inconsistency** in the autochecker (the free-text
  reasoning can disagree with the emitted label); evidence mode is the safe default.
- **Single-run evals are noisy** on a 28-claim set; small prompt changes need multi-run
  averaging to adjudicate.

---

*This is a proof of concept. Every AI-assisted artifact was reviewed by the team, and
the evaluation numbers above are reproducible from the run records in `data/eval/runs/`.*
