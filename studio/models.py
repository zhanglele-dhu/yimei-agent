from typing import Literal
from pydantic import BaseModel, Field

class CaseScore(BaseModel):
    case_id: str
    relevance: int = Field(ge=1, le=10)
    reason: str = Field(default='', max_length=300)

class CaseRanking(BaseModel):
    scores: list[CaseScore] = Field(min_length=1)

class CreateTask(BaseModel):
    project: str = Field(min_length=1, max_length=100)
    audience: str = Field(min_length=1, max_length=300)
    question: str = Field(min_length=1, max_length=1000)
    facts: str = Field(default='', max_length=6000)
    bundle_id: str

class Revision(BaseModel):
    revision: int

class ObservedPage(BaseModel):
    number: int
    form: str
    observation: str
    ocr_quote: str = ''
    borrow: str
    uncertainty: str = ''

class OutlinePage(BaseModel):
    kind: Literal['text', 'photo']
    purpose: str
    instruction: str
    source_pages: list[int] = Field(min_length=1)

class Analysis(BaseModel):
    summary: str
    original_pages: list[ObservedPage]
    borrow: list[str]
    missing_information: list[str]
    outline: list[OutlinePage] = Field(min_length=1, max_length=8)

class AnalysisConfirmation(Revision):
    analysis: Analysis

class AnalysisStageDecision(Revision):
    stage: Literal['retrieval', 'language', 'visual', 'facts', 'writing']
    decision: Literal['accept', 'reject']
    feedback: str = Field(default='', max_length=2000)

class PageContent(BaseModel):
    number: int
    title: str = Field(max_length=60)
    text: str = Field(max_length=700)
    source_ids: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)

class Draft(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=8000)
    pages: list[PageContent]
    missing_information: list[str] = Field(default_factory=list)

class PageEdit(Revision):
    title: str = Field(max_length=60)
    text: str = Field(max_length=700)
    confirmed: bool
    resolution: str = Field(default='', max_length=2000)

class CopyEdit(Revision):
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=8000)
    confirmed: bool
    resolution: str = Field(default='', max_length=2000)

class Progress(Revision):
    page_index: int = Field(ge=0, le=7)

class FeedbackInput(BaseModel):
    notice: str = Field(min_length=1, max_length=6000)
    posted_text: str = Field(default='', max_length=10000)

class FeedbackAnalysis(BaseModel):
    platform_quotes: list[str]
    hypotheses: list[str]
    next_actions: list[str]
    missing_information: list[str]
