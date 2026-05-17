# Project Proposal: An Agent for Building Historical Truthfulness Profiles of Public Companies (Group 7\)

Brendan Kehoe, Seback Oh, Tejaswini Shashidhar, Thomas Hillenbrand  
*FINM 33200 — Generative and Agentic AI for Finance, Spring 2026* *Four-person team* *Final submission target: 2026-05-27*

## Summary

We will build an agentic system that produces auditable *historical truthfulness profiles* for public companies — multi-year track records of whether management's forward-looking claims on earnings calls actually came true. The system extracts forward claims from earnings call transcripts, autonomously researches subsequent SEC filings, press releases, and news to verify each claim, and produces a graded verdict with cited evidence. The deliverables are (1) a working verification agent, (2) historical truthfulness profiles for a focused set of S\&P 500 firms over 2011–2023, and (3) a hand-labeled validation set that establishes the agent's grading accuracy.

We are seeking instructor feedback on the framing, the sample design (three options below), and the scope of the optional finance extension.

## Problem Statement

Every quarter, the CEOs and CFOs of public companies make hundreds of forward-looking claims on earnings calls — about product launches, margin expansion, M\&A intent, geographic moves, capital allocation, regulatory milestones, and revenue trajectories. Markets react to these statements in real time, and investors, analysts, and journalists track whether management can be trusted.

Quantitative claims (revenue growth, margin guidance) can be graded against subsequent filings. Qualitative claims — about products, deals, expansion, capital allocation — generally require digging through later 10-Qs, 8-Ks, press releases, and news.

We are interested in exploring how an agentic LLM system might produce auditable historical records of forward-claim accuracy, and what those records look like across firms and over time.

## What We Will Build

1. **A verification agent.** Given a forward-looking management claim from an earnings call, the agent autonomously decides what to research — subsequent SEC filings, press releases, news, and later earnings calls — and produces a graded verdict (*verified / partially verified / contradicted / not yet resolvable*) with cited evidence.  
     
2. **Historical truthfulness profiles.** For a selected panel of S\&P 500 firms, we will produce a multi-year track record showing every forward claim, its graded outcome, and the supporting evidence. These profiles are the primary user-facing deliverable and the centerpiece of the defense-day demo.  
     
3. **A validated gold-standard dataset.** A subset of claims will be hand-labeled to measure the agent's grading accuracy, with inter-annotator agreement reported. This is what makes the system *auditable* rather than just *plausible*.

## Scope

The system covers **forward-looking claims whose realization is a publicly observable discrete event or quantitative outcome**. Claims requiring evaluative business judgment ("the margin improvement was driven by mix shift," "guidance was appropriately conservative") are explicitly out of scope. This focus enables reliable ground-truth labels without deep accounting or industry expertise, matches the design pattern of fact-verification benchmarks like FEVER, and gives the agent a well-posed task with discrete outcomes.

Within that scope, claim categories are tiered by verification feasibility:

**Tier 1 — Must have** (highest automation, lowest labeling effort):

- Numerical guidance (graded automatically against Compustat)  
- M\&A closings (SEC 8-K filings, news)  
- Leadership transitions (SEC 8-K filings, news)  
- Capital actions: buybacks, dividends, debt issuance (8-Ks and financials)

**Tier 2 — Nice to have** (verifiable but partial-credit rules needed):

- Product launches (press releases, with date-tolerance rubric)  
- Geographic expansion (defined-event rubric needed: first sale? Office opening? regulatory approval?)  
- Regulatory milestones (industry-specific: FDA approvals, license grants)

## Methodology

**Pipeline:**

1. **Claim extraction** — an LLM extracts typed, forward-looking claims from each call's transcript according to a structured schema (category, metric, value/event, horizon).  
2. **Auto-grading (Tier 1 numerical)** — quantitative claims are matched against Compustat realized fundamentals at the relevant horizon, scored within tolerance bands.  
3. **Agentic grading (Tier 1 event \+ Tier 2\)** — for qualitative event claims, the agent autonomously searches SEC EDGAR, news APIs, and the company's own subsequent filings/press releases to find evidence. It produces a verdict and citations.  
4. **Validation** — a hand-labeled gold set of \~200–300 claims (sampled across categories and firms) is used to measure agent grading accuracy and inter-annotator agreement.

**Labeling workflow:** the agent itself serves as the labelers' research assistant during gold-set construction. The agent surfaces candidate evidence (filing excerpts, press release URLs, news) *without proposing a verdict*. Human labelers read the evidence and assign the verdict independently. This collapses per-claim labeling time from minutes to under one and preserves label independence (the agent does not bias the labeler).

**Model choice:** the pipeline uses different models for different tasks (e.g., one model for extraction, another for grading). Model selection is *not* a benchmark deliverable; we will simply use what works best for each component.

**Tool stack:** SEC EDGAR API (free), a news/web search API (TBD — likely Brave Search or NewsAPI), the team's existing transcript corpus, and Compustat via WRDS.

## Sample Design (open for team discussion)

We have committed to a focused track-record framing but have not yet committed to a specific sample. Three options are on the table:

- 4 firms × earnings call history 2020–2025 (20 calls per firm) \= **80 calls**  
- Strongest defense demo: "Here is firm X's truthfulness over the past five years"  
- Sector spread: one firm each from tech, healthcare, energy, consumer

## Workstream

1. **Data infrastructure** — transcript ingestion, Compustat integration, daily price/return data, sample selection and stratification.  
2. **Claim extraction pipeline** — LLM prompts, structured-output schemas, the typed forward-claim taxonomy, the small hand-labeled extraction-quality gold set.  
3. **Verification agent** — autonomous tool-using agent that researches and grades each qualitative claim. The defense-day demo lives here.  
4. **Evaluation & writeup** — leaderboard against the validation gold set, calibration analysis, profile visualizations, paper.

## Risks

- **Tool access and cost** — agent needs a news/web search API. SEC EDGAR is free; news search may cost $$$.  
- **Labeling time** — even with agent-assisted research, the gold set is the load-bearing eval. Risk if labeling rubric is unclear and inter-annotator agreement is low — mitigation is a calibration pass on a small subset before scaling labeling.  
- **Agent grading reliability** — if the agent is consistently wrong on Tier 2 claims (partial-credit cases), we may have to fall back to Tier 1-only.  
- **Disclosure gaps** — some Tier 2/3 events are reported inconsistently. Mitigation: tiered scope lets us cut categories that turn out to be untractable.

