"""Run claim extraction over earnings calls with an OpenAI mini-tier model.

Per the workstream-B design decisions:
  - LLM: OpenAI mini tier (default ``openai:gpt-4o-mini``), matching the
    verification agent's model choice.
  - Input unit: per call -- one structured-output request per earnings call.
  - Schema: lightweight (type + verbatim quote + summary + horizon).
  - Horizons: resolved to absolute dates *and* kept raw.

Structured output is enforced with LangChain's ``.with_structured_output()``
against ``ExtractionResponse`` -- the same pattern the verifier uses.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from langchain.chat_models import init_chat_model

from extractor.horizon import resolve_horizon
from extractor.prompt import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from extractor.provenance import locate_quote
from extractor.reader import EarningsCall, build_call_input, load_calls
from extractor.schema import (
    Claim,
    ExtractedClaim,
    ExtractionResponse,
    make_claim_id,
)

# Mini-tier model, provider-prefixed for ``init_chat_model``. Override via the
# ``--model`` CLI flag or the ``model_name`` argument.
MODEL_NAME = "openai:gpt-4o-mini"

# Reasoning-family models (GPT-5 series, o-series) reject a custom temperature
# and must run at the model default. Matched as a prefix against the model name
# with any "provider:" prefix stripped.
_NO_TEMPERATURE_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def _supports_temperature(model_name: str) -> bool:
    """Whether ``model_name`` accepts an explicit temperature setting."""
    bare = model_name.split(":", 1)[-1].lower()
    return not bare.startswith(_NO_TEMPERATURE_PREFIXES)


def build_extractor(model_name: str = MODEL_NAME):
    """Return an LLM bound to ``ExtractionResponse`` (structured output).

    Temperature 0 is used for reproducible extraction where the model supports
    it; GPT-5 / o-series reasoning models reject a custom temperature and run
    at the model default instead. ``max_retries`` covers transient API errors.
    """
    kwargs: dict = {"max_retries": 3}
    if _supports_temperature(model_name):
        kwargs["temperature"] = 0
    llm = init_chat_model(model_name, **kwargs)
    return llm.with_structured_output(ExtractionResponse)


def _enrich(
    extracted: ExtractedClaim,
    call: EarningsCall,
    model_name: str,
    extracted_at: datetime,
) -> Claim:
    """Turn one LLM-returned claim into a full, CSV-bound ``Claim`` record.

    Provenance is recovered deterministically: the quote is matched back to a
    management turn (``locate_quote``) rather than trusted from the model.
    """
    match = locate_quote(call.management_turns(), extracted.verbatim_quote)
    turn = match.turn
    component_id = turn.component_id if turn else 0
    horizon_period, horizon_end = resolve_horizon(extracted.horizon_raw, call.call_date)
    return Claim(
        claim_id=make_claim_id(
            call.ticker, call.call_date, component_id, extracted.verbatim_quote
        ),
        ticker=call.ticker,
        company=call.company,
        call_date=call.call_date,
        fiscal_period=call.fiscal_period,
        source_call=call.headline,
        claim_type=extracted.claim_type,
        verbatim_quote=extracted.verbatim_quote,
        quote_verbatim=match.verbatim,
        summary=extracted.summary,
        horizon_raw=extracted.horizon_raw,
        horizon_period=horizon_period,
        horizon_end_date=horizon_end,
        transcript_id=call.transcript_id,
        component_id=component_id,
        speaker_name=turn.speaker_name if turn else "",
        speaker_type=turn.speaker_type if turn else "",
        extraction_model=model_name,
        prompt_version=PROMPT_VERSION,
        extracted_at=extracted_at,
    )


def dedupe_claims(claims: list[Claim]) -> list[Claim]:
    """Drop exact-duplicate claims, keeping the first occurrence of each.

    The LLM occasionally emits the same claim twice within one call (markedly
    more often on larger models). Duplicates share a ``claim_id`` -- it is a
    content hash of ticker, call date, source turn, and quote -- so a repeated
    id would collide on the join key workstream C relies on to attach verdicts.
    Deduplicating here guarantees ``claim_id`` is unique in the output.
    """
    seen: set[str] = set()
    unique: list[Claim] = []
    for claim in claims:
        if claim.claim_id in seen:
            continue
        seen.add(claim.claim_id)
        unique.append(claim)
    return unique


def extract_call(
    call: EarningsCall,
    extractor=None,
    *,
    model_name: str = MODEL_NAME,
) -> list[Claim]:
    """Extract claims from one earnings call.

    Returns ``[]`` if the call has no management turns; exact-duplicate claims
    are removed. Pass a pre-built ``extractor`` (from ``build_extractor``) to
    avoid re-creating the client when processing many calls.
    """
    if not call.management_turns():
        return []
    if extractor is None:
        extractor = build_extractor(model_name)

    call_input = build_call_input(call)
    user_prompt = build_user_prompt(
        call.company, call.fiscal_period, call.call_date, call_input
    )
    response: ExtractionResponse = extractor.invoke(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
    )

    extracted_at = datetime.now(timezone.utc)
    claims = [_enrich(ec, call, model_name, extracted_at) for ec in response.claims]
    return dedupe_claims(claims)


def extract_transcript(
    csv_path,
    *,
    limit: int | None = None,
    model_name: str = MODEL_NAME,
    on_call: Callable[[EarningsCall, list[Claim]], None] | None = None,
) -> list[Claim]:
    """Extract claims from every call in a transcript CSV.

    Args:
        csv_path: Path to a transcript CSV.
        limit: If set, only process the first ``limit`` calls (by call date).
            Use ``limit=5`` for the day-4 pilot.
        model_name: Chat model identifier for ``init_chat_model``.
        on_call: Optional callback invoked after each call with
            ``(call, claims_from_that_call)`` -- handy for progress reporting.
    """
    calls = load_calls(csv_path)
    if limit is not None:
        calls = calls[:limit]

    extractor = build_extractor(model_name)
    claims: list[Claim] = []
    for call in calls:
        call_claims = extract_call(call, extractor, model_name=model_name)
        claims.extend(call_claims)
        if on_call is not None:
            on_call(call, call_claims)
    return claims
