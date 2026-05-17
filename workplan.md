# Workplan — Truthfulness Profiles Project

*Group 7 · FINM 33200 · Spring 2026*
*Window: 2026-05-17 → 2026-05-27 (10 days)*

## Working assumptions

- 4 team members all available through 2026-05-27
- Transcript corpus accessible
- WRDS/Compustat access (needs explicit confirmation — see Open Items below)
- LLM API access already set up
- One workstream per person — adjust if pairing makes sense
- Final scope: 4 firms × ~20 calls × 2020–2025; numerical guidance + capital allocation; SEC filings only; fallback to numerical-only if needed

---

## Four workstreams

### A. Data infrastructure

**Goal:** clean, accessible, reproducible data layer that the other streams pull from.

**Tasks:**
- Pick the 4 firms (one each from tech, healthcare, energy, consumer)
- Pull 20 quarters of earnings call transcripts per firm (~80 total)
- Pull all 10-Qs, 10-Ks, and 8-Ks for those firms over the same window from SEC EDGAR
- Pull quarterly Compustat fundamentals for the 4 firms (revenue, EPS, margins, capex, buybacks, dividends, debt issuance/repayment)
- Daily prices for the 4 firms (only needed if anyone pursues the optional alpha extension)
- Build a unified loader: given (firm, quarter), return (transcript, subsequent N filings, realized Compustat metrics)

**Owner:** TBD
**Time estimate:** 2 days for the pull + loader; ongoing maintenance throughout

### B. Claim extraction pipeline

**Goal:** for every call, output a structured list of typed forward claims with category, metric, value/event, horizon, and source span.

**Tasks:**
- Finalize the claim schema (types + required fields per type)
- Write extraction prompts with few-shot examples
- Validate structured outputs (Pydantic / JSON schema)
- Run extraction across all 80 calls
- Hand-spot-check a sample (~30 claims) for precision/recall — informs schema iteration
- Decide which LLM (cost-quality tradeoff)

**Owner:** TBD
**Time estimate:** 1 day schema design, 2 days build + iterate, 1 day to run + spot-check; ~4 days
**Depends on:** none (can start day 1)

### C. Verification agent

**Goal:** given a forward claim + the firm's subsequent filings, output a verdict (verified / partially verified / contradicted / not yet resolvable) with cited evidence.

**Tasks:**
- Design tool interface (EDGAR full-text search over the filing corpus, fetch full filing, extract relevant sections)
- For numerical claims: auto-grader against Compustat (no agent needed for this branch)
- For capital allocation claims: agentic search through subsequent 10-Q/K/8-K filings + structured output
- Build the agent loop (tool calls, iteration limit, evidence collection)
- Define verdict schema + citation format
- Test on a small sample to debug

**Owner:** TBD — strong fit for Thomas based on stated preferences
**Time estimate:** 1 day scaffolding, 2 days build + iterate, 1 day full run; ~4 days
**Depends on:** A (filings need to be pulled), B (claims need to be extracted)

### D. Evaluation & writeup

**Goal:** validate the agent's grading accuracy, build the per-firm truthfulness profiles, write the paper, prep the defense.

**Tasks:**
- Define labeling rubric (verdict definitions, partial-credit rules)
- Build a labeling UI (could be a Notion table, Google Sheet, or a tiny Streamlit app)
- Hand-label ~200–300 claims (gold set, spread across firms and categories) — *labor distributed across whole team, not just this person*
- Compute inter-annotator agreement (Cohen's κ on ~50 double-annotated)
- Run agent against gold set; compute accuracy, confusion matrices
- Assemble per-firm truthfulness profile visualizations
- Write the paper / GitHub Pages writeup
- Defense prep

**Owner:** TBD
**Time estimate:** 1 day rubric+UI, 1 day labeling (distributed), 2 days eval + writeup, 1 day defense prep; ~5 days
**Depends on:** B (claims), C (agent verdicts for comparison)

---

## Day-by-day milestones

| Day | Date | Critical path | What runs in parallel |
|---|---|---|---|
| 1 | 5/17 (today) | Team kickoff: assign workstreams, confirm WRDS access, pick 4 firms, agree schema sketch | — |
| 2 | 5/18 | A: data pulls begin. B: schema v1 + prompts. C: tool interface design. D: rubric draft. | All four streams active |
| 3 | 5/19 | A: data layer done. B: extraction running on pilot 5 calls. | C scaffolds in parallel. D builds labeling UI |
| 4 | 5/20 | **Pilot end-to-end on 5 calls.** Identify schema + extraction bugs. | All streams iterate |
| 5 | 5/21 | B: full extraction across 80 calls. C: numerical auto-grader working. | D begins labeling pilot subset |
| 6 | 5/22 | C: capital allocation agentic grading on pilot. | D: labeling at scale — *everyone labels* |
| 7 | 5/23 | C: agent run on full claim set. | D: labeling continues |
| 8 | 5/24 | D: gold set complete, agent vs gold scored. | Profile visualizations start |
| 9 | 5/25 | D: profiles done, writeup in progress. | Polish + bug-fixes |
| 10 | 5/26 | Writeup finalized, defense prep. | — |
| Submit | 5/27 | Submission. | — |

---

## Critical path

**Schema (day 2)** → **Extraction (days 3–5)** → **Agent verdicts (days 5–7)** → **Eval (day 8)** → **Writeup (days 9–10)**.

The single most schedule-load-bearing step is the **pilot at day 4**. If extraction or agent scaffolding is broken on the pilot, the whole rest of the plan slips. Plan to do an explicit "pilot review" together as a team that evening.

## Open items / risks

1. **WRDS/Compustat access** — needs explicit confirmation. If anyone on the team has used it before, they should own setup early on day 1.
2. **Firm selection** — needs to happen day 1. Suggested anchors: large-cap, ~20 quarters of clean transcript data, ideally with at least 1–2 buyback or capex announcements during the window for capital-allocation grading to have signal.
3. **Capital allocation grading rubric** — needs a clear partial-credit policy. E.g., "announced $1B buyback over 12 months → executed $700M in 12 months" is partial. Worth deciding day 1–2.
4. **Labeling distribution** — gold set labeling should be split across all four members, not loaded onto stream D. Build it in as a "team labeling sprint" on days 6–7.
5. **Fallback trigger** — agree in advance when you'd switch to numerical-only. Suggested: if by end of day 6 the capital-allocation grading is below 50% precision on pilot claims, fall back.
