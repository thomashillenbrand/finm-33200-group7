"""Run claim extraction over earnings calls with an OpenAI mini-tier model.

Per the workstream-B design decisions:
  - LLM: OpenAI mini tier (default ``openai:gpt-4o-mini``), matching the
    verification agent's model choice.
  - Input unit: per call -- one structured-output request per earnings call.
  - Schema: lightweight (type + verbatim quote + summary + horizon), two claim
    types -- ``numerical_guidance`` and ``capital_allocation``.
  - Horizons: resolved to absolute dates *and* kept raw.
  - Scope: numerical guidance must state a specific figure -- a directional-only
    guidance claim is dropped by ``filter_unquantified_guidance``;
    ``capital_allocation`` claims are kept regardless.

Structured output is enforced with LangChain's ``.with_structured_output()``
against ``ExtractionResponse`` -- the same pattern the verifier uses.
"""

from __future__ import annotations

import difflib
import os
import re
from collections.abc import Callable
from datetime import datetime, timezone

from langchain.chat_models import init_chat_model

from extractor.horizon import resolve_horizon
from extractor.prompt import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from extractor.provenance import locate_quote
from extractor.reader import EarningsCall, build_call_input, load_calls
from schemas import (
    Claim,
    ExtractedClaim,
    ExtractionResponse,
    make_claim_id,
)

def _resolve_extractor_model(explicit: str | None) -> str:
    """Resolve the extractor model: explicit arg > ``EXTRACTOR_MODEL`` env.

    There is no hardcoded fallback — the model identifier is configuration and
    must come from the environment (see ``.env.example``). Resolved at use time
    inside functions because ``.env`` is loaded in the CLI ``main()`` after this
    module is imported.
    """
    if explicit:
        return explicit
    model = os.environ.get("EXTRACTOR_MODEL")
    if not model:
        raise RuntimeError(
            "EXTRACTOR_MODEL is not set. Copy .env.example to .env (it sets the "
            "model identifiers) or export EXTRACTOR_MODEL before running."
        )
    return model

# Reasoning-family models (GPT-5 series, o-series) reject a custom temperature
# and must run at the model default. Matched as a prefix against the model name
# with any "provider:" prefix stripped.
_NO_TEMPERATURE_PREFIXES = ("gpt-5", "o1", "o3", "o4")

# Digit patterns that are labels, not financial figures: calendar years,
# quarter tags (Q1-Q4), SEC form names (10-K, 10-Q, 8-K, 20-F), and
# product/model designations such as "Model 3".
_NON_FIGURE_DIGITS = re.compile(
    r"\b(?:19|20)\d{2}\b"          # calendar years
    r"|\bQ[1-4]\b"                 # quarter labels
    r"|\b\d{1,2}-[KQF]\b"          # SEC form names (10-K, 10-Q, 8-K, 20-F)
    r"|\bmodel\s+\w+",             # product / model designations
    re.IGNORECASE,
)

# Minimum SequenceMatcher ratio for two same-turn quotes to count as the same
# claim in ``dedupe_similar_claims``.
_SIMILAR_QUOTE_THRESHOLD = 0.88


def _supports_temperature(model_name: str) -> bool:
    """Whether ``model_name`` accepts an explicit temperature setting."""
    bare = model_name.split(":", 1)[-1].lower()
    return not bare.startswith(_NO_TEMPERATURE_PREFIXES)


def build_extractor(model_name: str | None = None):
    """Return an LLM bound to ``ExtractionResponse`` (structured output).

    Temperature 0 is used for reproducible extraction where the model supports
    it; GPT-5 / o-series reasoning models reject a custom temperature and run
    at the model default instead. ``max_retries`` covers transient API errors.
    """
    model_name = _resolve_extractor_model(model_name)
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


def _has_number(text: str) -> bool:
    """True if ``text`` contains a digit that could be a financial figure.

    Digits that are really labels -- calendar years, quarter tags like 'Q4',
    SEC form names like '10-K', and product designations like 'Model 3' -- are
    stripped first so they are not mistaken for a quantitative figure (pilot
    false positives: claims survived only because they mentioned "Model 3" or
    "the 10-K").
    """
    stripped = _NON_FIGURE_DIGITS.sub("", text)
    return bool(re.search(r"\d", stripped))


def filter_unquantified_guidance(claims: list[Claim]) -> list[Claim]:
    """Drop ``numerical_guidance`` claims that state no specific figure.

    Per the workstream-B scope decision, numerical guidance is graded against
    Compustat line items, so a guidance claim with no number, percentage, or
    dollar amount cannot be verified -- it is dropped here as a deterministic
    safety net behind the prompt. ``capital_allocation`` claims are always
    kept: an announced program or committed action is verifiable against a
    subsequent 8-K or 10-Q even when no figure is stated.
    """
    kept: list[Claim] = []
    for claim in claims:
        if claim.claim_type == "numerical_guidance" and not _has_number(
            claim.verbatim_quote
        ):
            continue
        kept.append(claim)
    return kept


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


def _quote_key(quote: str) -> str:
    """Whitespace-normalised, lowercased quote for similarity comparison."""
    return " ".join(quote.split()).lower()


def dedupe_similar_claims(claims: list[Claim]) -> list[Claim]:
    """Drop near-duplicate claims emitted twice from the same source turn.

    ``dedupe_claims`` removes only exact ``claim_id`` collisions. The model
    sometimes emits the same claim twice from one turn with slightly different
    verbatim wording -- a different quote, hence a different ``claim_id`` --
    which that pass cannot catch (a pilot showed two copies of one claim
    surviving). This pass drops a claim when an earlier kept claim shares its
    *located* source turn and claim type and has a near-identical quote.
    Claims from different turns, and unlocated claims (``component_id`` 0), are
    never merged.
    """
    kept: list[Claim] = []
    for claim in claims:
        key = _quote_key(claim.verbatim_quote)
        is_dup = False
        for earlier in kept:
            if (
                earlier.component_id != 0
                and earlier.component_id == claim.component_id
                and earlier.claim_type == claim.claim_type
            ):
                ratio = difflib.SequenceMatcher(
                    None, _quote_key(earlier.verbatim_quote), key
                ).ratio()
                if ratio >= _SIMILAR_QUOTE_THRESHOLD:
                    is_dup = True
                    break
        if not is_dup:
            kept.append(claim)
    return kept


def extract_call(
    call: EarningsCall,
    extractor=None,
    *,
    model_name: str | None = None,
) -> list[Claim]:
    """Extract claims from one earnings call.

    Returns ``[]`` if the call has no management turns. Numerical-guidance
    claims with no stated figure are dropped, then exact-duplicate and
    same-turn near-duplicate claims are removed. Pass a pre-built ``extractor``
    (from ``build_extractor``) to avoid re-creating the client when processing
    many calls.
    """
    if not call.management_turns():
        return []
    model_name = _resolve_extractor_model(model_name)
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
    claims = filter_unquantified_guidance(claims)
    claims = dedupe_claims(claims)
    claims = dedupe_similar_claims(claims)
    return claims


def extract_transcript(
    parquet_path,
    *,
    limit: int | None = None,
    model_name: str | None = None,
    on_call: Callable[[EarningsCall, list[Claim]], None] | None = None,
) -> list[Claim]:
    """Extract claims from every call in a transcript parquet.

    Args:
        parquet_path: Path to a transcript parquet (one firm's calls).
        limit: If set, only process the first ``limit`` calls (by call date).
            Use ``limit=5`` for the day-4 pilot.
        model_name: Chat model identifier for ``init_chat_model``.
        on_call: Optional callback invoked after each call with
            ``(call, claims_from_that_call)`` -- handy for progress reporting.
    """
    calls = load_calls(parquet_path)
    if limit is not None:
        calls = calls[:limit]

    model_name = _resolve_extractor_model(model_name)
    extractor = build_extractor(model_name)
    claims: list[Claim] = []
    for call in calls:
        call_claims = extract_call(call, extractor, model_name=model_name)
        claims.extend(call_claims)
        if on_call is not None:
            on_call(call, call_claims)
    return claims
