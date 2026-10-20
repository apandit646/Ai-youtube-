from pydantic import BaseModel, Field


class Opportunity(BaseModel):
    topic: str
    language: str = ""
    format: str = ""
    why: str = ""


class TrendSummary(BaseModel):
    summary: str = Field(min_length=5, max_length=3000)
    observations: list[str] = Field(default_factory=list, max_length=20)
    hypotheses: list[str] = Field(default_factory=list, max_length=20)
    opportunities: list[Opportunity] = Field(default_factory=list, max_length=12)
    caveats: list[str] = Field(default_factory=list, max_length=12)
