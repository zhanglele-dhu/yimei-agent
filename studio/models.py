from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

class CaseScore(BaseModel):
    case_id: str
    relevance: int = Field(ge=1, le=10)
    reason: str = Field(default='', max_length=300)

class CaseRanking(BaseModel):
    scores: list[CaseScore] = Field(min_length=1)

class VisionRelevance(BaseModel):
    relevance: int = Field(ge=1, le=10)
    reason: str = Field(default='', max_length=300)

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

class ObservedPageCompact(BaseModel):
    number: int
    form: str = ''
    observation: str = ''
    ocr_quote: str = ''
    borrow: str = ''
    uncertainty: str = ''

class OutlinePage(BaseModel):
    kind: Literal['text', 'photo']
    purpose: str
    instruction: str
    visual_spec: str = Field(default='', max_length=600)
    source_pages: list[int] = Field(min_length=1)

class OutlinePageCompact(BaseModel):
    kind: Literal['text', 'photo']
    purpose: str
    instruction: str = ''
    visual_spec: str = ''
    source_pages: list[int] = Field(min_length=1)

    @field_validator('kind', mode='before')
    @classmethod
    def coerce_kind(cls, v):
        """视觉模型常用中文填 kind，统一映射回枚举值。"""
        if isinstance(v, str):
            s = v.strip().lower()
            if any(w in s for w in ('实拍', '照片', '图片', 'photo', '拍照')):
                return 'photo'
            if any(w in s for w in ('文字', '文本', 'text', '清单', '卡')):
                return 'text'
        return v

    @field_validator('source_pages', mode='before')
    @classmethod
    def coerce_pages(cls, v):
        """视觉模型常把页码写成 '1-3'、'1,2' 或单个数字，这里统一矫正成整数数组。"""
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            s = v.strip().replace('，', ',').replace('、', ',')
            if '-' in s or '～' in s or '~' in s or '到' in s:
                parts = [p for p in s.replace('～', '-').replace('~', '-').replace('到', '-').split('-') if p.strip()]
                if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
                    return list(range(int(parts[0]), int(parts[1]) + 1))
            out = [int(x) for x in s.split(',') if x.strip().isdigit()]
            return out or [1]
        if isinstance(v, list):
            out = []
            for x in v:
                if isinstance(x, int):
                    out.append(x)
                elif isinstance(x, str) and x.strip().isdigit():
                    out.append(int(x.strip()))
            return out or [1]
        return v

class Analysis(BaseModel):
    summary: str
    original_pages: list[ObservedPage]
    borrow: list[str]
    missing_information: list[str]
    outline: list[OutlinePage] = Field(min_length=1, max_length=8)

class AnalysisCompact(BaseModel):
    """视觉轨专用瘦身版拆解：GLM-4V 的 max_tokens 上限 2048 且指令遵循弱，
    因此不设字段长度硬约束（超长由 to_analysis 截断），只约束结构；
    进入合同前先经 normalize 矫正常见的弱模型输出习惯。"""

    @model_validator(mode='before')
    @classmethod
    def normalize(cls, data):
        if not isinstance(data, dict):
            return data
        # 字符串列表字段：弱模型常输出 [{'text': x}]、[123] 或单个字符串
        for key in ('borrow', 'missing_information'):
            v = data.get(key)
            if isinstance(v, str):
                data[key] = [v]
            elif isinstance(v, list):
                fixed = []
                for item in v:
                    if isinstance(item, dict):
                        item = next((x for x in item.values() if isinstance(x, str)), str(item))
                    fixed.append(item if isinstance(item, str) else str(item))
                data[key] = fixed
        # 逐页列表：number 缺失或非数字时按位置补号（页序=图序，prompt 已约定按原序）
        pages = data.get('original_pages')
        if isinstance(pages, list):
            fixed = []
            for idx, p in enumerate(pages, 1):
                if not isinstance(p, dict):
                    continue
                n = p.get('number')
                if not isinstance(n, int) and not (isinstance(n, str) and n.strip().isdigit()):
                    p = dict(p)
                    p['number'] = idx
                fixed.append(p)
            data['original_pages'] = fixed
        return data

    summary: str
    original_pages: list[ObservedPageCompact]
    borrow: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    outline: list[OutlinePageCompact] = Field(min_length=1, max_length=8)

    def to_analysis(self) -> Analysis:
        clip = lambda s, n: (s or '').strip()[:n]
        pages = [{'number': p.number, 'form': clip(p.form, 20), 'observation': clip(p.observation, 160),
                  'ocr_quote': clip(p.ocr_quote, 100), 'borrow': clip(p.borrow, 80),
                  'uncertainty': clip(p.uncertainty, 100)} for p in self.original_pages[:8]]
        return Analysis(
            summary=clip(self.summary, 300),
            original_pages=pages,
            borrow=[clip(x, 60) for x in self.borrow[:5]],
            missing_information=[clip(x, 80) for x in self.missing_information[:5]],
            outline=[{'kind': o.kind, 'purpose': clip(o.purpose, 60), 'instruction': clip(o.instruction, 120),
                      'visual_spec': clip(o.visual_spec, 200), 'source_pages': o.source_pages}
                     for o in self.outline[:6]])

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
    regenerate_background: bool = False

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
