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

---

## 2026-05-23 — Iter-3 robustness backlog

Surfaced during the iter-2 Task 25 smoke run (5 capital-allocation claims against
the real TSLA index). None blocked iter-2 done-criteria, all worth addressing
before the gold-set labeling sprint where they'll bite at scale.

1. **Rate-limit / retry layer.** Day-of-smoke run hit OpenAI's 200k TPM cap on
   1/5 claims (smoke_2). At gold-set scale (dozens of claims back-to-back) this
   becomes routine. Two-step fix:
   - Quick: add `max_retries=5` to `init_chat_model` in `verifier/agent.py`
     (langchain native, exponential backoff with jitter).
   - Substantive: wrap `verify()` in a `tenacity.retry` keyed on
     `openai.RateLimitError`, so retries are per-claim and logged into the
     trace file rather than swallowed.

2. **`before_date <= call_date` agent reasoning bug.** 3/5 smoke traces had the
   agent pass a `before_date` equal to the call_date — empty window, zero hits.
   smoke_2 returned 0 evidence purely because of this. Fix candidates:
   - Tool docstring: warn explicitly that `before_date` must be > call_date.
   - Tool layer: silently widen the window when `before_date <= after_date`
     and emit a tool-log warning the agent can read.

3. **SQLite LLM cache fragility.** The `langchain_community.cache.SQLiteCache`
   serialized entries from one structured-output schema fail to deserialize
   under a different schema's call, raising `ValueError: Structured Output
   response does not have a 'parsed' field` on cache hit. Killing the cache
   fixes it but it re-emerges. Options:
   - Version the cache key on the output schema's hash.
   - Migrate off `langchain_community` (which is being sunset) to a
     standalone integration package.
   - Drop SQLite for an in-process LRU + per-claim cache file.

4. **`datetime.utcnow()` deprecation in `agent.py:232`.** Trivially fix to
   `datetime.now(datetime.UTC)`. One-liner.

---

## 2026-05-23 — Externalize model/third-party specs to env vars

**Goal.** Move every hardcoded model identifier to a per-task env var with a
baked-in fallback. One knob per task type — no shared `MODEL` value, so we can
A/B different models per stage without code edits. Naming convention:
`<TASK>_MODEL` suffix.

| Env var | Replaces | Used in |
|---|---|---|
| `EXTRACTOR_MODEL` | `MODEL_NAME` in `src/extractor/extract.py` | Claim extraction (transcripts → CSV) |
| `VERIFIER_AGENT_MODEL` | `MODEL_NAME` in `src/verifier/agent.py` (agent call site) | Tool-using verifier agent |
| `VERIFIER_PARSER_MODEL` | same constant, separate use (structured-output call site) | Structured-output JSON parser in verdict mode |
| `EMBEDDING_MODEL` | `EMBED_MODEL` in `src/verifier/index.py` | FAISS doc + query embeddings |

All four default to current values (`openai:gpt-4o-mini` for the three chat
models, `text-embedding-3-small` for embeddings) if unset.

**Implementation gotcha.** Env vars must be read **at use time inside functions**,
not at module import. The entrypoints call `load_dotenv()` inside `main()` — by
then the agent/extractor modules have already been imported and any
module-level constants would already be captured. Pattern: a small
`_resolve_model_name(explicit_arg)` helper that does
`explicit or os.environ.get(VAR) or DEFAULT_FALLBACK` on each call.

**Blast radius.**

- `src/extractor/extract.py` — replace constant + thread the resolver through
  `build_extractor`, `extract_call`, `extract_transcript`.
- `src/extractor/run.py` — drop `MODEL_NAME` import; make `--model` default
  `None` so the resolver picks env-or-fallback at use time.
- `src/verifier/agent.py` — split into two getters; update the two
  `init_chat_model` calls (agent loop + structured-output parser).
- `src/verifier/index.py` — replace `EMBED_MODEL` with a getter; update
  `_make_embeddings_client`.
- `.env.example` — append a commented "Model selection (optional)" block with
  all four vars.
- `README.md` — one-liner in the iter-2 section pointing at the env knobs.
- `CLAUDE.md` — update open item #2 (currently names a specific file:line ref).
- Tests — no changes; existing tests already pass explicit model strings, not
  the module constants.

**Out of scope.** Tokenizer (`cl100k_base`) stays tied to the embedding model
family in code — no env var. If someone swaps in a non-OpenAI embed model
later, they'll need to think about the tokenizer separately. API key envs
(`OPENAI_API_KEY`, `WRDS_USERNAME`, `SEC_USER_AGENT`) already env-driven, no
changes.
