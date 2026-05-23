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

import os
from pathlib import Path
from typing import Literal

from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model
from langchain_community.cache import SQLiteCache
from langchain_core.globals import set_llm_cache

from schemas import Claim, EvidenceBundle, Verdict
from verifier.tools import bind_search_filings
from verifier.trace import to_records, save_trace, print_trace

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

For each user-provided claim, use the `search_filings` tool to retrieve evidence, \
then assign a verdict in one of:
  - "verified": the claim's realization is clearly evidenced
  - "partially_verified": the claim's realization is partial or ambiguous
  - "contradicted": evidence indicates the claim did not come true
  - "not_yet_resolvable": insufficient time has passed or evidence is unavailable

When in doubt between "verified" and "partially_verified", choose \
"partially_verified". A formal partial-credit rubric is forthcoming; until it \
lands, biasing toward the more conservative label keeps verdicts comparable.

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


def _extract_structured(final_text: str, mode: Mode) -> EvidenceBundle | Verdict:
    """Run a follow-up LLM call to coerce the agent's free-form output into the schema.

    Uses LangChain's `.with_structured_output()`, which under the hood requests
    a JSON object matching the pydantic schema. Deterministic and well-tested.
    """
    schema = _output_schema(mode)
    extractor = init_chat_model(_resolve_parser_model(), temperature=0, max_retries=3).with_structured_output(schema)
    instruction = (
        "Extract the agent's final answer into the schema. "
        "Preserve all evidence excerpts verbatim. Do not truncate, paraphrase, "
        "or merge excerpts. If the agent's answer is malformed or contains no "
        "excerpts, return an empty `items` list rather than inventing content. "
        "Agent answer follows:\n\n"
        f"{final_text}"
    )
    return extractor.invoke(instruction)


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


def verify(
    claim: Claim,
    mode: Mode = "evidence",
    *,
    trace: bool = True,
    cache: bool = True,
) -> EvidenceBundle | Verdict:
    """Run the verification agent on a single claim. Returns mode-dependent output.

    Args:
        claim: Validated `Claim` (iter-2 combined shape).
        mode: "evidence" (default; safe for labeling workflow) or "verdict".
        trace: If True, save JSON+MD trace files to data/traces/ and print.
        cache: If True (default), enable the SQLite chat-completion cache.
            Pass False (or `--no-cache` from the CLI) for fresh LLM calls.

    Raises:
        UnsupportedClaimTypeError: if claim.claim_type is not a capital-
            allocation type (iter-2 scope).
    """
    user_message = _format_claim_for_agent(claim)  # raises on unsupported types
    _configure_cache(cache)
    tool = bind_search_filings(claim.ticker, claim.call_date)
    agent = build_agent(mode, tools=[tool])
    result = agent.invoke({"messages": [{"role": "user", "content": user_message}]})

    if trace:
        records = to_records(result["messages"])
        json_path, _md_path = save_trace(records, f"verify_{mode}")
        print(f"[trace saved] {json_path}")
        print_trace(records)

    final_text = _stringify_content(result["messages"][-1].content)
    return _extract_structured(final_text, mode)


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


from datetime import date as _date_cls
from datetime import datetime as _dt_cls

SUPPORTED_CLAIM_TYPES = {"capital_allocation"}


class UnsupportedClaimTypeError(ValueError):
    """Raised when verify() is called with a claim_type iter-2 cannot handle."""


def _format_claim_for_agent(claim: Claim, *, today: _date_cls | None = None) -> str:
    """Render the user message the agent loop sees for `claim`.

    Deliberately omits the ticker — that's closed over in the tool binding, and
    naming it in prose would invite the LLM to second-guess the corpus.

    Raises UnsupportedClaimTypeError on numerical_guidance (Compustat deferred
    to iter 3).
    """
    if claim.claim_type not in SUPPORTED_CLAIM_TYPES:
        raise UnsupportedClaimTypeError(
            f"Iter-2 verifies capital-allocation claims only; "
            f"got claim_type={claim.claim_type!r}. "
            f"Compustat-backed numerical_guidance lands in iter 3."
        )
    today = today or _dt_cls.utcnow().date()
    horizon_hint = ""
    if claim.horizon_end_date is not None and claim.horizon_end_date < today:
        horizon_hint = (
            f"\nThe horizon ends {claim.horizon_end_date.isoformat()} — "
            f"narrow `before_date` accordingly when it helps."
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
        f"({claim.speaker_type or 'unknown'})\n\n"
        f"Use search_filings to gather evidence from filings filed after "
        f"{claim.call_date.isoformat()}.{horizon_hint}"
    )
