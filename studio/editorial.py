"""Reader-first planning and content acceptance before image generation."""
import hashlib
import json

from . import prompts, expression, writing_style, tones
from .models import EditorialPlan, QuestionOutline, DraftContentReview, ExpressionDraftReview, SharingDraftReview, ToneDraftReview, OutlinePage
from .card_layout import split_production_notes


def prepare(task, invoke, feedback=''):
    if not task.get('editorial_plan') or feedback:
        result = invoke(task, EditorialPlan, {
            'action': prompts.EDITORIAL_PLAN, 'request': task['request'],
            'reference_title': task.get('case', {}).get('title', ''),
            'feedback': feedback, 'previous_plan': task.get('editorial_plan'),
        })
        task['editorial_plan'] = result.model_dump()
    return task['editorial_plan']


def plan_outline(task, observed, invoke):
    plan = prepare(task, invoke)
    result = invoke(task, QuestionOutline, {
        'action': prompts.QUESTION_OUTLINE, 'request': task['request'],
        'editorial_plan': plan,
        'reference_observations': [p.model_dump() for p in observed.original_pages],
        'requested_pages': task.get('intent', {}).get('page_count', 0),
    })
    requested = task.get('intent', {}).get('page_count', 0)
    if requested and len(result.pages) != requested:
        raise ValueError(f'大纲应为用户指定的{requested}页，当前为{len(result.pages)}页')
    valid = {p['number'] for p in task['case']['pages']}
    if any(not set(p.source_pages) <= valid for p in result.pages):
        raise ValueError('大纲引用了不存在的参考页')
    task['editorial_outline'] = result.model_dump()
    # Only replace the new-content outline. Visual observations remain immutable.
    return observed.model_copy(update={
        'outline': [OutlinePage.model_validate(p.model_dump()) for p in result.pages],
    })


def content_payload(task, draft):
    pages = []
    for p in draft['pages']:
        public, _ = split_production_notes(p['text'])
        pages.append({**p, 'text': public})
    return {'review_policy':hashlib.sha256((expression.REVIEW if expression.enabled(task) else prompts.DRAFT_CONTENT_REVIEW).encode()).hexdigest(),
            'editorial_plan': task['editorial_plan'],
            'outline': task['confirmed_analysis']['outline'],
            'draft': {**draft, 'pages': pages},
            'confirmed_expression':expression.context(task) if expression.enabled(task) else None,
            'expression_check_policy':expression.CHECK if expression.enabled(task) else None,
            'writing_style':writing_style.context(task),
            'tone_review_policy':tones.TONE_REVIEW if task.get('writing_style',{}).get('criteria') else None,
            'voice_policy':writing_style.VOICE_POLICY if task.get('writing_style',{}).get('id')=='friend-sharing' else None}


def review(task, draft, invoke):
    prepare(task, invoke)
    payload = content_payload(task, draft)
    signature = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    previous = task.get('draft_content_review')
    if previous and previous.get('content_hash') == signature:
        return previous
    sharing=expression.enabled(task) and task.get('writing_style',{}).get('id')=='friend-sharing'
    strict_tone=expression.enabled(task) and bool(task.get('writing_style',{}).get('criteria'))
    review_schema=ToneDraftReview if strict_tone else SharingDraftReview if sharing else ExpressionDraftReview if expression.enabled(task) else DraftContentReview
    style_check=('同时必填expression_check.sharing_voice，依据confirmed_expression.prompt中的文风正反例判断是否像朋友介绍，'
        '而非中性讲义。draft_quotes必须从当前draft.pages.text摘取1到3条连续短句作为判断依据。'
        '风格问题只能依据当前正文，不能把来源、提示词反例或上一轮反馈的句子当作当前正文；已改掉的问题应通过。'
        '仅出现你、可以这样理解、亲近称谓或表情不足以通过；必须实际像完整正例那样直接介绍特点，避免套话和重复解释。'
        '没有姐妹或表情不构成缺陷。若分享口吻未落实，'
        '将具体问题写入expression_check.issues，给出保留事实与结构的改法。' if sharing else '')
    if strict_tone:style_check=tones.TONE_REVIEW
    result = invoke(task, review_schema, {'action': ((expression.REVIEW + expression.CHECK + style_check) if expression.enabled(task) else prompts.DRAFT_CONTENT_REVIEW), **payload})
    numbers = [p['number'] for p in draft['pages']]
    if sorted(p.number for p in result.pages) != sorted(numbers):
        raise ValueError('内容检查未逐页对应草稿，本次不进入图片生成')
    passed = all([result.audience_fit, result.direction_fit, result.question_coverage, result.readable, result.source_supported])
    passed = passed and not result.issues and all(p.passed and not p.issues for p in result.pages)
    record = {**result.model_dump(), 'passed': passed, 'content_hash': signature}
    if expression.enabled(task):
        if task.get('expression',{}).get('status')!='accepted':raise ValueError('请先确认表达方案')
        if result.expression_check is None:raise ValueError('内容检查未核对已确认表达方案，请重试')
        check=result.expression_check.model_dump()
        if sharing and not strict_tone:
            public_text='\n'.join(p['text'] for p in payload['draft']['pages'])
            if any(not expression.normalize(q) or expression.normalize(q) not in expression.normalize(public_text) for q in check.get('draft_quotes',[])):
                raise ValueError('文风审稿引用了当前正文中不存在的句子，请重新检查')
        if sharing:
            deterministic=writing_style.voice_issues(draft)
            if deterministic:
                check['sharing_voice']=False
                check['issues']+=deterministic
        if strict_tone:
            tone_check=result.tone_check.model_dump()
            tone_passed=tones.validate_check(tone_check,task['writing_style'],payload['draft'])
            if sharing and writing_style.voice_issues(draft):tone_passed=False
            tone_check['passed']=tone_passed
            record['tone_check']=tone_check
            if sharing:check['sharing_voice']=tone_passed
            if not tone_passed:
                record['passed']=False
                failures=[r['rule_id']+'：'+r['reason'] for r in tone_check['criteria'] if not r['passed']]
                record['issues']+=failures or ['语言未符合所选语气标准，请按正反例修改']
        record['expression_check']=check
        if sharing and not strict_tone and check.get('sharing_voice') is not True:
            record['passed']=False
            record['issues'].append('分享口吻未落实：请按文风正例重写，保留原定知识与结构')
        if not all(check[key] for key in ('purpose_kept','structure_kept','tone_kept')) or check['issues']:
            record['passed']=False
            record['issues']+=check['issues'] or ['草稿未保持已确认的目的、结构或语气']

    task['draft_content_review'] = record
    task.setdefault('content_review_history', []).append(record)
    task['content_review_history'] = task['content_review_history'][-10:]
    return record


def issues_for(record):
    return record['issues'] + [f"第{p['number']}页：{issue}" for p in record['pages'] for issue in p['issues']]
