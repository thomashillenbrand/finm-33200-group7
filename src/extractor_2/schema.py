from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from verifier.schema import Claim as VerifierClaim

NUMERICAL_CATEGORY = Literal[
    "revenue",
    "revenue_growth",
    "eps",
    "margins",
    "operating_income",
    "operating_income_growth",
    "capex",
    "volume",
    "units",
    "other_numerical",
]
_VALID_NUMERICAL_CATEGORIES = {
    "revenue", "revenue_growth", "eps", "margins",
    "operating_income", "operating_income_growth",
    "capex", "volume", "units", "other_numerical",
}
HORIZON = Literal["next_quarter", "next_year", "multi_year", "unspecified"]
CONFIDENCE = Literal["certain", "likely", "conditional", "hedged"]
CAPITAL_SUBCATEGORY = Literal["buyback", "dividend", "capex_plan", "debt"]


class _ClaimBase(BaseModel):
    claim_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_span: str = Field(min_length=1)
    horizon: HORIZON
    confidence_language: CONFIDENCE
    value_or_amount: str | None = None

    def to_verifier_claim(self, ticker: str, call_date: date) -> VerifierClaim:
        return VerifierClaim(ticker=ticker, call_date=call_date, text=self.source_span)


class NumericalGuidanceClaim(_ClaimBase):
    type: Literal["numerical"] = "numerical"
    category: NUMERICAL_CATEGORY
    metric: str = Field(min_length=1)


class CapitalAllocationClaim(_ClaimBase):
    type: Literal["capital_allocation"] = "capital_allocation"
    category: Literal["capital_allocation"] = "capital_allocation"
    subcategory: CAPITAL_SUBCATEGORY


ExtractorClaim = Annotated[
    Union[NumericalGuidanceClaim, CapitalAllocationClaim],
    Field(discriminator="type"),
]


class _FlatClaim(BaseModel):
    """Flat schema for OpenAI structured-output call (avoids oneOf which the API rejects)."""

    type: Literal["numerical", "capital_allocation"]
    source_span: str
    horizon: HORIZON
    confidence_language: CONFIDENCE
    value_or_amount: str | None
    # numerical fields (null for capital_allocation claims)
    category: str | None
    metric: str | None
    # capital allocation field (null for numerical claims)
    subcategory: Literal["buyback", "dividend", "capex_plan", "debt"] | None

    def to_typed(self) -> "NumericalGuidanceClaim | CapitalAllocationClaim":
        if self.type == "numerical":
            raw_cat = (self.category or "").lower().replace(" ", "_")
            safe_cat = raw_cat if raw_cat in _VALID_NUMERICAL_CATEGORIES else "other_numerical"
            return NumericalGuidanceClaim(
                source_span=self.source_span,
                horizon=self.horizon,
                confidence_language=self.confidence_language,
                value_or_amount=self.value_or_amount,
                category=safe_cat,  # type: ignore[arg-type]
                metric=self.metric or self.category or "unknown",
            )
        return CapitalAllocationClaim(
            source_span=self.source_span,
            horizon=self.horizon,
            confidence_language=self.confidence_language,
            value_or_amount=self.value_or_amount,
            subcategory=self.subcategory or "buyback",
        )


class _ClaimsWrapper(BaseModel):
    """Used only for the LLM structured-output call — no metadata fields."""

    claims: list[_FlatClaim] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    ticker: str
    transcript_id: int
    call_date: date
    claims: list[
        Annotated[
            Union[NumericalGuidanceClaim, CapitalAllocationClaim],
            Field(discriminator="type"),
        ]
    ] = Field(default_factory=list)
