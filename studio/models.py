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
    research_id: str = Field(default="", max_length=32)
    workflow: Literal["legacy", "expression-first"] = "legacy"
    writing_style: Literal["friend-sharing", "concise-direct", "patient-explainer", "neutral", "cautionary", "enthusiastic"] = "friend-sharing"

class IntentInput(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    project: str = Field(default='', max_length=100)
    audience: str = Field(default='', max_length=300)

class CatalogInput(BaseModel):
    bundle_id: str = Field(min_length=24,max_length=24)

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
    number: int = Field(description='原帖页码，整数')
    form: str = Field(default='', description='这一页的形态，10字内，如：信息图/实拍/纯文字')
    observation: str = Field(default='', description='描述这一页的画面与文字内容，40字内')
    ocr_quote: str = Field(default='', description='逐字摘抄本页OCR原文片段，没有则留空')
    borrow: str = Field(default='', description='这一页可借鉴的组织方式，20字内')
    uncertainty: str = Field(default='', description='不确定之处，没有则留空')

class DialogTurn(BaseModel):
    """微信对话卡的一轮发言。speaker：customer=顾客（左侧白泡），shop=门店（右侧绿泡）。"""
    speaker: Literal['customer', 'shop']
    text: str = Field(min_length=1, max_length=300)

class OutlinePage(BaseModel):
    kind: Literal['text', 'photo', 'chat']
    purpose: str
    instruction: str
    visual_spec: str = Field(default='', max_length=600)
    source_pages: list[int] = Field(min_length=1)
    reader_question: str = ''
    key_points: list[str] = Field(default_factory=list)
    new_terms: list[str] = Field(default_factory=list)
    word_budget: int = 180

class OutlinePageCompact(BaseModel):
    kind: Literal['text', 'photo', 'chat'] = Field(description='页面类型：text=文字卡，photo=实拍页，chat=微信对话卡')
    purpose: str = Field(description='这一页要讲什么，15字内')
    instruction: str = Field(description='制作或拍摄说明，20字内')
    visual_spec: str = Field(default='', description='底图视觉风格描述，30字内，不提任何文字内容')
    source_pages: list[int] = Field(min_length=1, description='借鉴的原帖页码数组')

    @field_validator('kind', mode='before')
    @classmethod
    def coerce_kind(cls, v):
        """视觉模型常用中文填 kind，统一映射回枚举值。"""
        if isinstance(v, str):
            s = v.strip().lower()
            if any(w in s for w in ('对话', '聊天', '微信', 'chat')):
                return 'chat'
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
        # 弱模型会把整个结果包进外层键（如 task/analysis）里：解包还原
        if 'original_pages' not in data:
            for v in data.values():
                if isinstance(v, dict) and 'original_pages' in v:
                    data = v
                    break
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

    summary: str = Field(description='概括原帖讲了什么、用什么形式，40字内')
    original_pages: list[ObservedPageCompact] = Field(description='逐页观察，每张原图一条')
    borrow: list[str] = Field(default_factory=list, description='整体可借鉴的组织方式列表')
    missing_information: list[str] = Field(default_factory=list, description='缺少依据、需要门店补充的事实')
    outline: list[OutlinePageCompact] = Field(min_length=1, max_length=8, description='新内容的逐页大纲')

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
    dialog: list[DialogTurn] = Field(default_factory=list)

class AudienceBrief(BaseModel):
    reader: str = Field(min_length=1, max_length=300, description='根据用户需求判断的目标读者及已有知识，不猜测人口属性')
    questions: list[str] = Field(min_length=1, max_length=5, description='这些读者希望本篇回答的具体问题')
    approach: str = Field(min_length=1, max_length=500, description='本篇如何用读者熟悉的说法、分点顺序和例子解释；不输出推理过程')
    defer_topics: list[str] = Field(default_factory=list, description='本篇不必展开的次要术语或细节，不能遗漏用户明确要求的内容')

class Draft(BaseModel):
    audience_brief: AudienceBrief | None = Field(default=None, description='写作前的受众与表达方案；兼容旧草稿，可为空；新生成时应填写')
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=8000)
    pages: list[PageContent]
    missing_information: list[str] = Field(default_factory=list)

class EditorialPlan(BaseModel):
    audience_brief: AudienceBrief
    direction: str = Field(min_length=1, max_length=300)
    reading_goal: str = Field(min_length=1, max_length=300)
    reference_use: str = Field(min_length=1, max_length=600)

class QuestionPage(OutlinePage):
    reader_question: str = Field(min_length=1)
    key_points: list[str] = Field(min_length=1, max_length=4)
    new_terms: list[str] = Field(default_factory=list, max_length=3)
    word_budget: int = Field(default=180, ge=80, le=260)

class QuestionOutline(BaseModel):
    reference_takeaway: str = Field(min_length=1)
    adaptation: str = Field(min_length=1)
    pagination_reason: str = Field(min_length=1)
    pages: list[QuestionPage] = Field(min_length=1, max_length=8)

class PageContentCheck(BaseModel):
    number: int
    passed: bool
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)

class ExpressionCheck(BaseModel):
    purpose_kept: bool
    structure_kept: bool
    tone_kept: bool
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    summary: str


class DraftContentReview(BaseModel):
    expression_check: ExpressionCheck | None = None
    audience_fit: bool
    direction_fit: bool
    question_coverage: bool
    readable: bool
    source_supported: bool
    summary: str
    issues: list[str] = Field(default_factory=list)
    pages: list[PageContentCheck] = Field(min_length=1)

class ExpressionDraftReview(DraftContentReview):
    expression_check: ExpressionCheck


class SharingExpressionCheck(ExpressionCheck):
    sharing_voice: bool
    draft_quotes: list[str] = Field(min_length=1, max_length=3)

class SharingDraftReview(ExpressionDraftReview):
    expression_check: SharingExpressionCheck


class PageEdit(Revision):
    title: str = Field(max_length=60)
    text: str = Field(max_length=2000)
    confirmed: bool
    resolution: str = Field(default='', max_length=2000)
    regenerate_background: bool = False
    card_theme: Literal['minimal', 'soft', 'duotone', 'ai', 'plain'] = 'minimal'
    generation_mode: Literal['model', 'seedream', 'template'] = 'model'
    regenerate_design: bool = False


class CardDesign(BaseModel):
    direction: str = Field(min_length=1, max_length=500, description='简短说明本页的构图、层级与配色设计')
    html: str = Field(min_length=1, max_length=16000, description='卡片内部HTML片段，仅使用给定内容槽位，不带script/style/外部链接')
    css: str = Field(min_length=1, max_length=18000, description='为这页定制的CSS，1080x1440；无外部资源、无新增文字')


class CardModelSettings(BaseModel):
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    review_model: str = Field(default='', max_length=200)
    api_key: str = Field(default='', max_length=5000)


class CardVisualCheck(BaseModel):
    passed: bool = Field(description='文字可读、无截断遮挡、图片完整、层级清晰时才为true；不做医学事实认证')
    summary: str = Field(min_length=1, max_length=500)
    issues: list[str] = Field(default_factory=list, max_length=10)

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


class ExpressionEvidence(BaseModel):
    sample_id: str
    quote_id: str = ''
    quote: str = Field(default='', max_length=240)
    lesson: str = Field(min_length=1, max_length=240)

class ExpressionStudy(BaseModel):
    audience: str = Field(min_length=1, max_length=200)
    opening: str = Field(min_length=1, max_length=240)
    structure: list[str] = Field(min_length=1, max_length=6)
    tone: str = Field(min_length=1, max_length=240)
    sentence_pattern: str = Field(min_length=1, max_length=240)
    presentation: str = Field(min_length=1, max_length=300)
    good_example: str = Field(min_length=1, max_length=300)
    bad_example: str = Field(min_length=1, max_length=300)
    knowledge_needs: list[str] = Field(min_length=1, max_length=6)
    evidence: list[ExpressionEvidence] = Field(min_length=1, max_length=5)

class ExpressionConfirm(Revision):
    prompt: str = Field(min_length=40, max_length=8000)

class MaterialSupport(BaseModel):
    source_id: str
    quote_id: str = ''
    quote: str = Field(default='', max_length=500)

class MaterialItem(BaseModel):
    need: str = Field(min_length=1, max_length=240)
    answer: str = Field(min_length=1, max_length=700)
    supports: list[MaterialSupport] = Field(min_length=1, max_length=4)
    scope: str = Field(default='', max_length=300)

class MaterialSheet(BaseModel):
    items: list[MaterialItem] = Field(default_factory=list, max_length=10)
    missing: list[str] = Field(default_factory=list, max_length=10)



class ToneBatchInput(BaseModel):
    bundle_id: str = Field(default='', max_length=24)

class ToneVersion(Revision):
    writing_style: str = Field(min_length=1, max_length=50)

class ToneRuleCheck(BaseModel):
    rule_id: str
    passed: bool
    quote: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=400)

class ToneCheck(BaseModel):
    style_id: str
    passed: bool
    criteria: list[ToneRuleCheck] = Field(min_length=1, max_length=8)
    summary: str

class ToneDraftReview(ExpressionDraftReview):
    tone_check: ToneCheck
