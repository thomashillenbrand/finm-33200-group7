# Future optimizations (deferred)

Ideas that are out of scope for the current iteration but worth picking up
if/when performance becomes a constraint. Add new items at the bottom with a
date stamp.

---

## 2026-05-23 — Auto-researcher for chunking + indexing

**Context.** The iter-2 verifier ships with a naive chunker (fixed 600-token
windows / 100 overlap, no section awareness, XBRL noise survives at the top
of 10-K chunks) and a single embedding model (`text-embedding-3-small`). We
have not measured retrieval quality; we picked the configuration because it
was the simplest thing that compiled.

**Idea.** Stand up a driver that sweeps a cross-product of configurations and
scores each one on a held-out (claim → expected evidence) gold set:

- **Chunking**: window size {300, 600, 1200}, overlap {0, 100, 200},
  boundary strategy {fixed token, sentence, paragraph, item-aware}, noise
  filters {strip XBRL/HTML metadata, MD&A-only, full}.
- **Embedding**: model {`text-embedding-3-small`, `text-embedding-3-large`,
  e5, nomic}, normalization on/off.
- **Retrieval**: top-k, hybrid BM25 + dense, optional cross-encoder rerank.

Per config: build (or load cached) index → run eval queries → log
`{recall@k, MRR, nDCG, sample top-k}` to a parquet leaderboard. Claude Code
subagents are a natural fit for fan-out (one config per agent), aggregating
into a single results file.

**Load-bearing prerequisite.** A gold set of (claim → expected evidence
chunks). Without it, the autoresearcher measures variance, not quality.
Workstream D's labeling sprint (workplan days 6–7) IS that dataset, but it
does not exist yet. Two ways forward:

1. Bootstrap with a tiny pilot gold set (~20 claims, hand-labeled in an
   hour from `data/claims/pilot_claims.csv`) on TSLA only — the index that
   exists right now. Use it to A/B chunkers cheaply, then run the winning
   config on AMZN/KO/LLY.
2. Defer the autoresearcher until the real gold set lands; build all four
   tickers now with the current chunker as a deliberate baseline.

**Tradeoff.** Spinning this up before the gold set risks measuring noise;
deferring it risks paying to re-embed all four firms (~$0.50–$2 each) when
we eventually pick a better chunker.

**Adjacent known issues to fold in** (cheaper to fix during the sweep than
twice):

- `XMLParsedAsHTMLWarning` on TSLA 10-Ks — the primary doc is XML-flavored;
  parser choice should be `lxml-xml` for those filings.
- Chunk-0 of every 10-K is XBRL namespace / taxonomy noise — strip the
  XBRL header before chunking.
- `_edgar_url` in `verifier/corpus.py` is a placeholder that doesn't reach
  the actual filing; fix once we settle on the per-form URL shape.
