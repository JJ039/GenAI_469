"""Canonical decision schema shared by both experimental systems."""
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, ValidationError

ALIASES = {"hold_position": "hold", "monitor": "hold", "borrow_from_other_banks": "borrow_interbank"}


def canonical_action(action):
    return ALIASES.get(action, action) if isinstance(action, str) else None


def parse_json_object(raw):
    if isinstance(raw, tuple):
        if not raw:
            raise ValueError("Empty runner response")
        raw = raw[0]
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ValueError("Expected a JSON object response")
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        text = "\n".join(text.splitlines()[1:-1])
    def reject_constant(value):
        raise ValueError('Non-finite JSON constant: ' + value)
    result = json.loads(text, parse_constant=reject_constant)
    if not isinstance(result, dict):
        raise ValueError("Response must be a JSON object")
    return result


class HermesBankDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    news_label: Literal["unverified", "false", "credible"]
    action: Literal["hold", "borrow_interbank", "draw_central_bank_facility"]
    amount: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=4000)
    untrusted_content_flagged: bool = False
    needs_review: bool = False

    @field_validator("action", mode="before")
    @classmethod
    def normalize_action(cls, value):
        return canonical_action(value)

    @field_validator("amount", "confidence", mode="before")
    @classmethod
    def numbers_not_booleans(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Expected a number, not text or boolean")
        return value

    @field_validator("untrusted_content_flagged", "needs_review", mode="before")
    @classmethod
    def actual_boolean(cls, value):
        if not isinstance(value, bool):
            raise ValueError("Expected a boolean")
        return value

    @model_validator(mode="after")
    def hold_is_zero(self):
        if self.action == "hold" and self.amount != 0:
            raise ValueError("Hold must have zero amount")
        return self


def validate_decision(decision):
    try:
        HermesBankDecision(**decision)
        return True, []
    except (ValidationError, TypeError) as exc:
        return False, [str(exc)]
