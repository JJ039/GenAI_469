#purpose of this file is to run the LLM output thru pydantic validation model , checks if output matches schema. 
#dont match, rerun. else it is safe to score. 

from pydantic import BaseModel, Field, ValidationError

class HermesBankDecision(BaseModel):
    """
    Schema for the decision output.
    """
    news_label: str = Field(description="unverified, false, or credible") 
    action: str = Field(description="draw_central_bank_facility, borrow_interbank, or hold")
    amount: float = Field(ge=0) #adds robustness by defining the possible values of the variable
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(description="reason for the action")


def validate_decision(decision: dict) -> tuple[bool, list[str]]:
    """Validate a decision against the schema."""
    try:
        HermesBankDecision(**decision)
        return True, []
    except ValidationError as e:
        return False, [str(error) for error in e.errors()]
        