# Project Context — Truthfulness Profiles (Group 7)

**Course:** FINM 33200 — Generative and Agentic AI for Finance, Spring 2026
**Team:** Brendan Kehoe, Seback Oh, Tejaswini Shashidhar, Thomas Hillenbrand
**Final submission:** 2026-05-27

## Collaboration with Claude
- When a user starts a new session with the project, they should be reminded to make sure to pull the latest updates from the repository.
- Using branches is encouraged for any significant changes or additions to the codebase, and users should be reminded to create a new branch for their work and to merge it back into the main branch once it's ready.
  - If they decide they are uncomfortable with branching, offer to guide them through the process. Do not force them.
- If changes made by a user affect the overall project context or would be helpful for other collaborators to know, they should be reminded to update the `CLAUDE.md` file.
  - Update should include a summary of the changes and their implications for the project.
- It is fine for users to make changes to the `CLAUDE.md` file themselves or via claude.
- When a user makes updates to the project, they should be reminded to push their changes to the repository with a clean commit message.

## Guiding principle

This is a proof of concept. When in doubt on scope decisions, lean narrower.

## What we're building

An agentic system that produces auditable historical truthfulness profiles for public companies. Given an earnings call transcript, the system extracts forward-looking management claims; it then grades whether each claim was realized by checking the same company's subsequent SEC filings (10-Q, 10-K, 8-K).

Three deliverables:
1. A verification agent
2. Per-firm truthfulness profiles for 4 firms
3. A hand-labeled validation gold set

## Scope (locked-in)

- **Sample:** 4 firms × ~20 earnings calls each over 2020–2025 = ~80 calls
- **Firms:** Tesla (auto/EV), Amazon (tech/consumer), Coca-Cola (consumer staples), Eli Lilly (healthcare/pharma)
- **Claim categories:** Numerical guidance (graded against Compustat) + capital allocation: buybacks, dividends, capex plans, debt (graded against subsequent 10-Q balance sheet, cash flow, and 8-Ks)
- **Verification source:** SEC EDGAR exclusively — no news/web APIs
- **Pipeline:** transcript → typed-claim extraction → SEC-filings-based verification → graded verdict (verified / partially verified / contradicted / not yet resolvable) + cited evidence
- **Labeling workflow (load-bearing — don't change):** the agent surfaces candidate evidence *without proposing a verdict*; human labelers read the evidence and assign verdicts independently. Letting the agent's verdict bias the labeler creates circularity in the evaluation.
- **Fallback:** if capital allocation grading hits roadblocks, drop to numerical-guidance-only.

## Key documents in this directory

- `proposal.md` — submitted proposal (the formal scope)
- `workplan.md` — 10-day execution plan with workstreams and daily milestones
- `pitch.md` — older framing, not authoritative; use proposal/CLAUDE.md when in conflict
- `README.md` — setup, project structure, smoke tests, and CLI usage for the data_pull, extractor, and verifier packages
- `docs/architecture.md` — end-to-end dataflow, mermaid diagrams, module-by-module tour. Read this first for a code-level orientation; it's the baseline iter-3 changes should be planned against.

## Workstreams

- **A. Data infrastructure** — transcripts, SEC filings (EDGAR), Compustat loader, sample selection. *Per-ticker loader landed as `src/data_pull.py` on 2026-05-22: `python -m data_pull <TICKER> --start YYYY-MM-DD` writes WRDS transcripts (parquet), Compustat quarterly fundamentals (parquet), and SEC 10-K/10-Q/8-K primary docs (HTML) into `Pulled_data/<TICKER>/`. Idempotent. See README for output layout. Authored by Brendan — kept as a single file pending his approval before further restructuring.*
- **B. Claim extraction pipeline** — LLM extraction with typed schema, prompt engineering. *Two prototypes were built independently (`feature/build-extraction-pipeline` and `feature/claim-extraction-scaffold`, both landed 2026-05-21) and unified into a single `extractor` package on 2026-05-22. Unified design: reads the WRDS transcript parquet written by workstream A's `data_pull.py`, collapsing Capital IQ's multiple transcript versions to the final proofed copy of each call; one OpenAI structured-output request per call (LangChain `init_chat_model`, default `openai:gpt-4o-mini`, `--model` override); lightweight typed `Claim` schema with two claim types (numerical_guidance, capital_allocation) and a deterministic SHA-1 `claim_id`; source-turn provenance recovered by quote back-matching; horizons resolved to absolute dates with the raw wording kept; numerical-guidance claims with no stated figure dropped (`filter_unquantified_guidance`) while figure-less capital-allocation claims are kept; exact-duplicate dedup; single claims CSV as the contract for workstreams C and D. 51 offline tests pass. Use `python -m extractor.run --input <parquet|dir> --output <csv>`; see README.md. The merge decisions (parquet-only input, lightweight schema, figure-required-for-guidance, single-CSV output) were made by Brendan; the superseded `extractor_2` package was removed. **Horizon-prune + source-context update 2026-05-24:** the horizon resolver now resolves bare quarters ("Q2" → the next valid quarter 2 relative to the call date) and bare months ("by the end of March"); any claim whose horizon still cannot be resolved to an end date is pruned from the output by `filter_unresolved_horizon` — a blanket rule applied to both claim types, since an unresolvable horizon leaves workstream C with no filing window. A new `source_context` CSV column carries the source turn plus the turns immediately before and after it (same call), so a sparse `verbatim_quote` can be read in context by the verifier. 84 offline extractor tests pass.*
- **C. Verification agent** — agentic search over SEC filings. *Iteration 1 (stubbed tools, deepagents + Pydantic, evidence/verdict modes) landed on `feature/build-agent-scaffold` on 2026-05-21. Iteration 2 (real EDGAR retrieval) landed on `feature/verifier-iteration2` on 2026-05-23: a fixed-token chunker + FAISS index per ticker, a `search_filings` LangChain tool bound per claim (hides `ticker`/`after_date` from the LLM and enforces the no-time-leak guarantee at the tool layer), a `langchain_community.cache.SQLiteCache` for chat completions (on by default, `--no-cache` to bypass), and two new CLIs: `python -m verifier.index [--all | <TICKER>] [--refresh]` and the existing `python -m verifier.run` (now backed by real filings). All four firms (TSLA/AMZN/KO/LLY) indexed locally under `pulled_data/<TICKER>/index/`. Scope is locked to `capital_allocation` claims for iter-2 — `numerical_guidance` raises `UnsupportedClaimTypeError` (Compustat-backed numerical grading lands in iter-3). Done-criteria validated by 130 offline tests, 4 live tests (`pytest -m live`), and a 5-claim hand-inspected smoke run confirming 0 time-leaks and 0 verdict-language leakage across 61 retrieved chunks. See README.md "Verification — iter-2 real EDGAR retrieval (workstream C)" for prerequisites, CLIs, and caching layout. **Iter-3 horizon ceiling merged to master 2026-05-24:** the per-claim search window now also has an upper bound — `bind_search_filings` closes over `horizon_end` (= `claim.horizon_end_date`) and the corpus filters `report_date <= horizon_end`, keyed on each filing's reporting period (`reportDate`) so a late-filed annual 10-K still grades an annual claim. This replaces the removed LLM-visible `before_date` (both time bounds are now structural, not model-driven). `chunks.parquet` gained a `report_date` column, backfilled with no re-embedding — **indexes built before this change must be rebuilt** (`python -m verifier.index --all`; `SearchIndex.load` raises `IndexCorruptError` on a pre-horizon index). Validated live on 5 verdict-mode claims (0 post-horizon citations). The unresolved-horizon case (`horizon_end_date=None`) still has no ceiling and over-reaches to recent filings — gated on the extractor's bare-quarter horizon resolution (open item #6, owned by a teammate).*
- **D. Evaluation & writeup** — gold-set labeling, agent scoring, profile assembly, paper, defense prep. *Pilot-eval scaffolding landed on `feature/verifier-iteration3` on 2026-05-23: a gold-label schema + JSONL loader (`src/verifier/gold.py`, `data/gold/`) and a scorer (`src/verifier/eval.py`, `python -m verifier.eval`) reporting recall@k, precision (accession-granularity), and verdict accuracy against hand labels. The verdict rubric (`docs/labeling_rubric.md`) is stubbed and pending the team. See README "Gold-set evaluation".*

Gold-set labeling is a whole-team sprint on days 6–7, not loaded onto stream D alone.

## Open items

1. WRDS / Compustat access confirmation
2. LLM provider choice per stage — now set via per-task env vars (`EXTRACTOR_MODEL`, `VERIFIER_AGENT_MODEL`, `VERIFIER_PARSER_MODEL`, `EMBEDDING_MODEL`; no source fallback, the resolver raises if unset — see `.env.example`). All four currently point at `openai:gpt-4o-mini` / `text-embedding-3-small`; the actual per-stage choice is still open but now A/B-able without code edits.
3. Capital allocation grading rubric (partial-credit policy — e.g., "announced $1B buyback over 12mo → executed $700M in 12mo" → partial? full?). The gold-label schema + scorer are in place (`src/verifier/gold.py`, `src/verifier/eval.py`); the rubric itself is a stubbed, pending team deliverable at `docs/labeling_rubric.md`.
4. Labeling rubric finalization
5. Extraction: occasional claim-type misclassification (e.g. a product-timeline statement filed as `debt`) — watch for it during gold-set labeling
6. ~~Extraction: horizon resolver does not handle bare months ("by the end of March") or bare quarters ("Q2" with no year).~~ **Resolved 2026-05-24.** The resolver now handles bare quarters ("Q2" with no year → the next valid quarter 2 relative to the call date) and bare months ("by the end of March"). Claims whose horizon still cannot be resolved to an end date are pruned from the extractor output by `filter_unresolved_horizon` (a blanket rule covering both claim types). This also closes the verifier's unresolved-horizon over-reach at the source: with null-`horizon_end_date` claims pruned upstream, the verifier never receives a claim with an open-ended `horizon_end` ceiling.

Deferred optimizations (kept out of CLAUDE.md to avoid bloat): see `docs/future_optimizations.md`. Open items as of 2026-05-24: the chunker/embedding/retriever autoresearcher (gated on having a small gold set). Of the four iter-2-smoke robustness items, three are now resolved (rate-limit/retry layer added; the `before_date<=call_date` agent reasoning bug eliminated by the iter-3 horizon ceiling — `before_date` was removed entirely; `datetime.utcnow()` deprecation fixed); the SQLite LLM-cache schema-drift fragility remains an accepted limitation with a documented `--no-cache` workaround.

## Execution notes

- **The labeling workflow is load-bearing.** Don't break the agent-as-research-assistant (evidence-only) pattern — letting the agent's verdict bias the labeler creates circularity in the evaluation.
- **Day-4 pilot is the load-bearing checkpoint.** If extraction or agent scaffolding is broken on the pilot, the whole plan slips.

## Course material reference

The course site (https://finm-33200.github.io/) covers techniques directly relevant to pipeline implementation:

- **Discussion 1** — Lopez-Lira & Tang (LLM prompting) and Chen-Kelly-Xiu (embeddings) for return-prediction setups; useful framing for the optional alpha extension.
- **Discussion 2** — Tokenization, embeddings basics.
- **Discussion 3** — OpenAI API, structured outputs with Pydantic — directly applicable to the claim-extraction pipeline.
- **Discussion 4** — Classical RAG, semantic search over SEC filings, RAG benchmarking. The `02_rag_benchmark_ipynb.html` notebook and the `01_filing_search_ipynb.html` semantic-search notebook are the most directly reusable references for the verification agent's filing search.
- **Discussion 5** — Introduction to Agents.
- **HW3** — student-built RAG pipeline on SEC 10-Ks; the chunking, embedding, retrieval, and prompt scaffolds from this assignment are reusable.
- **HW4** — Agentic RAG trace audit on SEC filings, using Matt Stockton's `agentic-rag-edgar-demo` repo. That repo's EDGAR tool patterns are a useful starting point for workstream C.

The project's distinction from class material lives in: earnings call transcripts as input, forward-claim verification as the task, and SEC filings as delayed ground truth.
