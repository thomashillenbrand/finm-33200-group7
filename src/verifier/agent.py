"""Verification agent: builds deepagents agent + runs single-claim verifications.

Two modes:
  - "evidence": surface excerpts only, no verdict. Output schema: EvidenceBundle.
  - "verdict":  surface excerpts AND assign a verdict + reasoning. Output: Verdict.

The mode flag swaps the system prompt and the structured-output schema. The
tools, corpus, and trace format are identical across modes.

Structured output is enforced by a post-processing step (`_extract_structured`)
that runs the LLM with `.with_structured_output()` on the agent's final message.
Two LLM calls per verification — acceptable cost for iteration 1.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path
from typing import Literal

import openai
from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model
from langchain_community.cache import SQLiteCache
from langchain_core.globals import set_llm_cache
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from pydantic import ValidationError

from schemas import Claim, EvidenceBundle, Verdict
from verifier.corpus import SearchIndex
from verifier.index import IndexNotBuiltError
from verifier.tools import bind_search_filings
from verifier.trace import print_trace, save_trace, to_records

_logger = logging.getLogger(__name__)

# Per-claim retry on OpenAI rate limits. The OpenAI SDK already retries each
# individual request (max_retries=3 on the init_chat_model calls below); this
# coarser layer re-runs the whole verification when the SDK still surfaces a
# RateLimitError. At gold-set scale (dozens of claims back-to-back) the TPM cap
# gets hit routinely. The SQLite cache makes a re-run cheap — completions that
# already succeeded are served from cache. reraise=True so callers see the real
# RateLimitError (not tenacity's RetryError) once attempts are exhausted;
# before_sleep logs each backoff so retries are visible, not swallowed.
_retry_on_rate_limit = retry(
    retry=retry_if_exception_type(openai.RateLimitError),
    wait=wait_random_exponential(min=2, max=60),
    stop=stop_after_attempt(6),
    before_sleep=before_sleep_log(_logger, logging.WARNING),
    reraise=True,
)

_LLM_CACHE_PATH = Path("pulled_data") / ".cache" / "llm_cache.sqlite"


def _configure_cache(enabled: bool) -> None:
    """Process-global LLM cache toggle.

    On by default (enabled=True). The cache is keyed by (prompt, model,
    params), so prompt edits naturally invalidate. Pass enabled=False (e.g.
    via the CLI's --no-cache) for fresh runs.
    """
    if not enabled:
        set_llm_cache(None)
        return
    _LLM_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    set_llm_cache(SQLiteCache(database_path=str(_LLM_CACHE_PATH)))

Mode = Literal["evidence", "verdict"]


def _require_model_env(var: str) -> str:
    """Read a model identifier from the environment, raising if unset.

    Model identifiers are configuration with no hardcoded fallback — they must
    come from the environment (see ``.env.example``).
    """
    model = os.environ.get(var)
    if not model:
        raise RuntimeError(
            f"{var} is not set. Copy .env.example to .env (it sets the model "
            f"identifiers) or export {var} before running."
        )
    return model


def _resolve_agent_model() -> str:
    """Tool-using agent model from ``VERIFIER_AGENT_MODEL``."""
    return _require_model_env("VERIFIER_AGENT_MODEL")


def _resolve_parser_model() -> str:
    """Structured-output parser model from ``VERIFIER_PARSER_MODEL``.

    Independent of ``_resolve_agent_model`` so the parser can be a different
    (e.g. cheaper) model than the agent loop without code edits.
    """
    return _require_model_env("VERIFIER_PARSER_MODEL")

EVIDENCE_SYSTEM_PROMPT = """You are a financial research assistant helping label SEC filings.

For each user-provided claim, your job is to SURFACE THE MOST RELEVANT EXCERPTS \
from the firm's subsequent SEC filings. You MUST NOT propose a verdict on whether \
the claim was verified, partially verified, contradicted, or not yet resolvable. \
A human labeler will independently read the excerpts and assign the verdict.

Quote filing text directly. Do not paraphrase, summarize, or include judgment \
language (e.g., "the claim was met", "this contradicts"). The labeler reads only \
your excerpts; any verdict-flavored prose smuggled into them biases the label.

Do not answer from prior knowledge. Every excerpt must come from a `search_filings` \
result in this session.

Each tool result is a list of excerpts from a single firm's SEC filings filed \
after the call date. Cite excerpts verbatim, and include the bracketed \
`[form filed YYYY-MM-DD, accession ...]` header from the tool result on every \
excerpt you return.

Use the `search_filings` tool to retrieve evidence. Cite the source filing on \
every excerpt. Return only the structured `EvidenceBundle`."""

VERDICT_SYSTEM_PROMPT = """You are a financial research assistant verifying \
forward-looking management claims against subsequent SEC filings.

Use the `search_filings` tool to retrieve evidence, then assign exactly one \
verdict, grounded ONLY in filings that appear in your search results:
  - "verified": the claim's realization is clearly evidenced in a retrieved \
filing -- including if it occurred earlier than the stated horizon. A stated \
numeric target met within ~10% counts.
  - "partially_verified": retrieved filings show genuine partial progress, or a \
numeric outcome that is directionally right but materially off (more than ~10%).
  - "contradicted": a retrieved filing shows the opposite outcome, or -- when \
the horizon has elapsed -- the line item where the action would necessarily \
appear shows it did not happen.
  - "not_yet_resolvable": no retrieved filing supports the claim. This is the \
DEFAULT whenever neither full nor partial credit can be grounded in an existing \
filing.

If your first search returns no filing that addresses the claim's outcome, issue \
at least one more search with reformulated terms -- the specific facility or \
program name, or the relevant financial-statement line item -- before concluding \
"not_yet_resolvable".

Critical: grade only on filings that exist in your search results. Do NOT \
assume, infer, or extrapolate an outcome from filings that have not been \
published, and do NOT read realization into tangential mentions. If the claim's \
outcome window extends beyond the filings available to you and no filing yet \
evidences progress, the answer is "not_yet_resolvable" -- never a guess.

When genuinely between "verified" and "partially_verified", choose \
"partially_verified".

Do not answer from prior knowledge. Every cited excerpt must come from a \
`search_filings` result in this session.

Return only the structured `Verdict` with cited evidence items, the verdict \
label, and a short reasoning paragraph."""


def build_agent(mode: Mode, *, tools: list):
    """Construct a deepagents agent for the given mode with the supplied tools.

    The mode flag swaps the system prompt and the structured-output schema.
    Tools are passed in by `verify()` because the search tool is bound
    per-claim (see `tools.bind_search_filings`).
    """
    if mode == "evidence":
        system_prompt = EVIDENCE_SYSTEM_PROMPT
    elif mode == "verdict":
        system_prompt = VERDICT_SYSTEM_PROMPT
    else:
        raise ValueError(f"Unknown mode: {mode!r}. Expected 'evidence' or 'verdict'.")

    return create_deep_agent(
        model=init_chat_model(_resolve_agent_model(), max_retries=3, temperature=0.1),
        system_prompt=system_prompt,
        tools=tools,
    )


def _output_schema(mode: Mode) -> type[EvidenceBundle] | type[Verdict]:
    return EvidenceBundle if mode == "evidence" else Verdict


_DECISIVE_VERDICTS = {"verified", "partially_verified", "contradicted"}


def _enforce_evidence_grounding(output, mode):
    """A decisive verdict with no cited evidence is unfounded -> not_yet_resolvable.

    The only deterministically-forced rule of this pass: the agent may not claim
    verified / partially_verified / contradicted without citing at least one
    retrieved filing. An evidence-backed verdict (including a legitimately-early
    'verified') is left untouched. Verdict mode only; evidence mode is a no-op.
    """
    if mode != "verdict":
        return output
    if output.verdict in _DECISIVE_VERDICTS and not output.items:
        return output.model_copy(update={
            "verdict": "not_yet_resolvable",
            "reasoning": (output.reasoning
                          + " [auto: decisive verdict cited no evidence; "
                            "downgraded to not_yet_resolvable]"),
        })
    return output


def _empty_output(mode: Mode):
    """Safe degraded result when the parser can't produce structured output."""
    if mode == "evidence":
        return EvidenceBundle(items=[])
    return Verdict(items=[], verdict="not_yet_resolvable",
                   reasoning="parser failed to produce structured output")


def _parse_instruction(final_text: str) -> str:
    return (
        "Extract the agent's final answer into the schema. Preserve all evidence "
        "excerpts verbatim. Do not truncate, paraphrase, or merge excerpts. If the "
        "agent's answer is malformed or contains no excerpts, return an empty "
        "`items` list rather than inventing content. Agent answer follows:\n\n"
        f"{final_text}"
    )


def _extract_structured(final_text: str, mode: Mode, *, extractor_factory=None):
    """Coerce the agent's free-form output into the schema, with repair.

    The parser LLM occasionally returns an unparseable structured response
    ("no 'parsed' field nor 'refusal'") that `max_retries` does not cover. Retry
    once with a reattempt suffix (a different prompt -> a fresh, uncached LLM
    call); on persistent failure degrade to a safe empty result rather than
    raising, so one bad parse becomes not_yet_resolvable, not a lost claim.
    """
    schema = _output_schema(mode)
    factory = extractor_factory or (lambda: init_chat_model(
        _resolve_parser_model(), temperature=0, max_retries=3
    ).with_structured_output(schema))
    instruction = _parse_instruction(final_text)
    for suffix in ("", "\n\n(Reattempt: respond with valid structured JSON only.)"):
        try:
            return factory().invoke(instruction + suffix)
        except (ValueError, ValidationError):
            continue
    return _empty_output(mode)


def _stringify_content(content: object) -> str:
    """Coerce a LangChain message content to a flat string.

    `AIMessage.content` can be a `str` or a `list[dict]` (multi-modal chunks
    with a `text` key). Concatenate all text chunks; ignore non-text chunks.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for chunk in content:
            if isinstance(chunk, dict):
                text = chunk.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(chunk, str):
                parts.append(chunk)
        return "\n".join(parts)
    return str(content)


@_retry_on_rate_limit
def verify(
    claim: Claim,
    mode: Mode = "evidence",
    *,
    trace: bool = True,
    cache: bool = True,
) -> EvidenceBundle | Verdict:
    """Run the verification agent on a single claim. Returns mode-dependent output.

    Retries the whole verification on `openai.RateLimitError` (exponential
    backoff with jitter, up to 6 attempts), then re-raises the original error.

    Args:
        claim: Validated `Claim` (combined shape).
        mode: "evidence" (default; safe for labeling workflow) or "verdict".
        trace: If True, save JSON+MD trace files to data/traces/ and print.
            Note: a rate-limit retry re-runs the agent and writes a fresh
            (timestamped) trace per attempt.
        cache: If True (default), enable the SQLite chat-completion cache.
            Pass False (or `--no-cache` from the CLI) for fresh LLM calls.

    Raises:
        UnsupportedClaimTypeError: if claim.claim_type is not a capital-
            allocation type (current scope).
        openai.RateLimitError: if rate limits persist past the retry budget.
    """
    # Coverage context (verdict mode only): the latest filing period available
    # for this ticker tells the agent its evidence boundary. Index is cached, so
    # this is reused by bind_search_filings below.
    coverage_date = None
    fully_covered = None
    if mode == "verdict":
        try:
            coverage_date = SearchIndex.load(claim.ticker).max_report_date
        except IndexNotBuiltError:
            coverage_date = None
        fully_covered = _horizon_within_coverage(claim.horizon_end_date, coverage_date)

    user_message = _format_claim_for_agent(
        claim, coverage_date=coverage_date, fully_covered=fully_covered
    )  # raises UnsupportedClaimTypeError on unsupported types
    _configure_cache(cache)
    tool = bind_search_filings(claim.ticker, claim.call_date, claim.horizon_end_date)
    agent = build_agent(mode, tools=[tool])
    result = agent.invoke({"messages": [{"role": "user", "content": user_message}]})

    if trace:
        records = to_records(result["messages"])
        json_path, _md_path = save_trace(records, f"verify_{mode}")
        print(f"[trace saved] {json_path}")
        print_trace(records)

    final_text = _stringify_content(result["messages"][-1].content)
    return _enforce_evidence_grounding(_extract_structured(final_text, mode), mode)


def verify_from_dict(
    d: dict,
    mode: Mode = "evidence",
    *,
    trace: bool = True,
    cache: bool = True,
) -> EvidenceBundle | Verdict:
    """Thin entry point: validate dict → Claim, then delegate to verify().

    Pydantic `ValidationError` on malformed input is intentionally not wrapped —
    its error structure is already readable.
    """
    return verify(Claim(**d), mode, trace=trace, cache=cache)


SUPPORTED_CLAIM_TYPES = {"capital_allocation"}


class UnsupportedClaimTypeError(ValueError):
    """Raised when verify() is called with a claim_type iter-2 cannot handle."""


def _horizon_within_coverage(horizon_end, coverage):
    """True iff a filing reporting period reaches the claim's horizon — i.e. the
    outcome window has elapsed AND is covered by available filings. A filing
    whose period ends at/after the horizon is itself proof the horizon passed."""
    return (
        horizon_end is not None
        and coverage is not None
        and coverage >= horizon_end
    )


def _format_claim_for_agent(claim: Claim, *, coverage_date=None, fully_covered=None) -> str:
    """Render the user message the agent loop sees for `claim`.

    Deliberately omits the ticker — that's closed over in the tool binding, and
    naming it in prose would invite the LLM to second-guess the corpus. The
    search window (call-date floor, horizon ceiling) is enforced inside the
    tool binding too, so the message states it for context but gives the LLM no
    date knob to turn.

    Raises UnsupportedClaimTypeError on numerical_guidance (Compustat deferred
    to iter 3).
    """
    if claim.claim_type not in SUPPORTED_CLAIM_TYPES:
        raise UnsupportedClaimTypeError(
            f"Iter-2 verifies capital-allocation claims only; "
            f"got claim_type={claim.claim_type!r}. "
            f"Compustat-backed numerical_guidance lands in iter 3."
        )

    coverage_line = ""
    if coverage_date is not None:
        if fully_covered:
            coverage_line = (
                f"\nFilings are available through their {coverage_date.isoformat()} "
                f"reporting period, which is within this claim's horizon. "
                f"Grade only on filings that exist.\n"
            )
        else:
            horizon = (claim.horizon_end_date.isoformat()
                       if claim.horizon_end_date else "unspecified")
            coverage_line = (
                f"\nFilings are available only through their "
                f"{coverage_date.isoformat()} reporting period; this claim's "
                f"horizon ({horizon}) extends beyond available coverage. Grade "
                f"only on filings that exist — do not assume or infer outcomes "
                f"from filings not yet published.\n"
            )

    return (
        f"A management claim was made on {claim.call_date.isoformat()} "
        f"in the {claim.fiscal_period} earnings call.\n\n"
        f"Type: {claim.claim_type}\n"
        f"Quote: \"{claim.verbatim_quote}\"\n"
        f"Summary: {claim.summary}\n"
        f"Stated horizon: {claim.horizon_raw or 'unspecified'} "
        f"(resolved end: "
        f"{claim.horizon_end_date.isoformat() if claim.horizon_end_date else 'unknown'})\n"
        f"Speaker: {claim.speaker_name or 'unknown'} "
        f"({claim.speaker_type or 'unknown'})\n"
        f"{coverage_line}\n"
        f"Use search_filings to gather evidence. Results are already restricted "
        f"to filings within this claim's time window."
    )
