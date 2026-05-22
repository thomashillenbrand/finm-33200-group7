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
- `README.md` — setup, project structure, and quick-smoke-test instructions for the verifier package

## Workstreams

- **A. Data infrastructure** — transcripts, SEC filings (EDGAR), Compustat loader, sample selection
- **B. Claim extraction pipeline** — *Iteration 1 landed on `feature/claim-extraction-scaffold` on 2026-05-21.* Package at `src/extractor/`: typed schema (NumericalGuidanceClaim / CapitalAllocationClaim discriminated union), TranscriptLoader for WRDS parquet format, extraction prompts with few-shot examples, horizon resolver, provenance/speaker matching, deduplication, JSON + CSV output, spot-check + scoring scripts, for_verifier.py handoff for workstream C. 29 offline tests pass. Pilot extraction run on 3 AMZN calls (12 claims). Use `python -m extractor.run` CLI.
- **C. Verification agent** — agentic search over SEC filings. *Iteration 1 (stubbed tools, deepagents + Pydantic, evidence/verdict modes) landed on `feature/build-agent-scaffold` on 2026-05-21; see README.md for setup and the CLI.*
- **D. Evaluation & writeup** — gold-set labeling, agent scoring, profile assembly, paper, defense prep

Gold-set labeling is a whole-team sprint on days 6–7, not loaded onto stream D alone.

## Open items

1. WRDS / Compustat access confirmation
2. LLM provider choice per stage
3. Capital allocation grading rubric (partial-credit policy — e.g., "announced $1B buyback over 12mo → executed $700M in 12mo" → partial? full?)
4. Labeling rubric finalization

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
