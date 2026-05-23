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

from typing import Literal

from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model

from schemas import Claim, EvidenceBundle, Verdict
from verifier.trace import to_records, save_trace, print_trace

Mode = Literal["evidence", "verdict"]
MODEL_NAME = "openai:gpt-4o-mini"

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


def build_agent(mode: Mode):
    """Construct a deepagents agent for the given mode.

    The agent runs free-form (no `response_format`). Structured output is
    enforced by a deterministic post-processor (`_extract_structured`) that
    uses LangChain's `.with_structured_output()` against the schema for `mode`.
    Two LLM calls per verification — one agent loop, one structured-output
    extraction — which is fine for iteration-1 scaffolding cost.

    Returns an object whose `.invoke({"messages": [...]})` runs the loop.
    """
    if mode == "evidence":
        system_prompt = EVIDENCE_SYSTEM_PROMPT
    elif mode == "verdict":
        system_prompt = VERDICT_SYSTEM_PROMPT
    else:
        raise ValueError(f"Unknown mode: {mode!r}. Expected 'evidence' or 'verdict'.")

    return create_deep_agent(
        model=init_chat_model(MODEL_NAME, max_retries=3, temperature=0.1),
        system_prompt=system_prompt,
        tools=[search_filings],
    )


def _output_schema(mode: Mode) -> type[EvidenceBundle] | type[Verdict]:
    return EvidenceBundle if mode == "evidence" else Verdict


def _extract_structured(final_text: str, mode: Mode) -> EvidenceBundle | Verdict:
    """Run a follow-up LLM call to coerce the agent's free-form output into the schema.

    Uses LangChain's `.with_structured_output()`, which under the hood requests
    a JSON object matching the pydantic schema. Deterministic and well-tested.
    """
    schema = _output_schema(mode)
    extractor = init_chat_model(MODEL_NAME, temperature=0, max_retries=3).with_structured_output(schema)
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
) -> EvidenceBundle | Verdict:
    """Run the verification agent on a single claim. Returns mode-dependent output.

    Return type is determined by `mode`: "evidence" → `EvidenceBundle`,
    "verdict" → `Verdict`.

    Args:
        claim: Validated `Claim` object.
        mode: "evidence" (default; safe for labeling workflow) or "verdict".
        trace: If True, save JSON+MD trace files to data/traces/ and print the
            trace to stdout. Pass False for smoke tests / notebook callers.
    """
    agent = build_agent(mode)
    user_message = (
        f"Claim made on {claim.call_date.isoformat()} by {claim.ticker}: \"{claim.text}\"\n\n"
        f"Use search_filings to gather evidence from filings after {claim.call_date.isoformat()}."
    )
    result = agent.invoke({"messages": [{"role": "user", "content": user_message}]})

    if trace:
        records = to_records(result["messages"])
        # Save before print: persistence is the durable artifact; print is
        # convenience. If print_trace errored on a malformed record, we'd lose
        # the trace entirely.
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
) -> EvidenceBundle | Verdict:
    """Thin entry point: validate dict → Claim, then delegate to verify().

    Pydantic `ValidationError` on malformed input is intentionally not wrapped —
    its error structure is already readable.
    """
    return verify(Claim(**d), mode, trace=trace)
