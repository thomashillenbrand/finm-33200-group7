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
    "capex",
    "volume",
    "units",
    "other_numerical",
]
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


class _ClaimsWrapper(BaseModel):
    """Used only for the LLM structured-output call — no metadata fields."""
    claims: list[
        Annotated[
            Union[NumericalGuidanceClaim, CapitalAllocationClaim],
            Field(discriminator="type"),
        ]
    ] = Field(default_factory=list)


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
