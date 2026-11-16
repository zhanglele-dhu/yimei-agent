"""Small, source-linked comparison of an imported M22 science sample."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, Field
from . import cases, llm, semantic


class Finding(BaseModel):
    observation: str = Field(min_length=1, max_length=180)
    sample_id: str
    quote: str = Field(min_length=1, max_length=240)


class ResearchConclusion(BaseModel):
    findings: list[Finding] = Field(min_length=1, max_length=3)
    audience: str = Field(min_length=1, max_length=80)
    direction: str = Field(min_length=1, max_length=45)
    reader_question: str = Field(min_length=1, max_length=100)
    approach: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=240)
    reference_ids: list[str] = Field(min_length=1, max_length=5)


INSTRUCTION = (
    '围绕固定选题M22科普，对给定的多篇小红书帖子文字做轻量内容调研，给出一个具体创作切入角度。'
    'findings只写样本实际内容及介绍结构，每条引用一个sample_id和该样本title/body/OCR中连续的原文quote，禁止拼接或改字。'
    '这是正文和OCR样本，没有评论正文，没有看图，不能声称读过评论、观察到构图或发现真实用户需求。'
    'audience是建议受众，reader_question是推测的读者困惑，direction/approach/reason是AI编辑建议；不把推测写成调研事实。'
    '参考互动快照不代表流量因果，不能说某种话术导致爆款或代表全平台；没有同类比较证据不宣称市场空白。'
    '优先根据样本具体知识与介绍结构提出普通读者能理解的分点科普，不写空泛建议或到店引流。'
    '只选一个适合MVP的方向，不把仪器/滤片/护理等所有主题塞在一起。样本只是表达参考，不作为医学事实依据。'
    'direction只写30字内的选题标题，不含做一篇等任务句；audience建议60字内，reader_question60字内，approach80字内。'
    'approach只写具体介绍顺序，不重复限制条件，不用MVP等内部术语。没有看图不得判断表格、配色、并排布局等画面形态。'
    'reference_ids引用本次样本编号。输出简短结论，不输出思维链。'
)


def normal(text):
    return re.sub(r'\s+', '', text)


def read(root, report_id):
    if not re.fullmatch(r'[a-f0-9]{32}', report_id):
        raise ValueError('调研记录编号无效')
    return json.loads((Path(root)/'research'/f'{report_id}.json').read_text(encoding='utf-8'))


def conclude(root, bundle_root):
    # Newest relevant bundle, one snapshot: never silently merge duplicate versions.
    for path in sorted(Path(bundle_root).glob('*.zip'), key=lambda p:p.stat().st_mtime, reverse=True):
        manifest = cases.load(bundle_root, path.stem)
        labels = {x['case_id']:x for x in semantic.catalog(root, manifest)['items']}
        pool = [c for c in manifest['cases'] if labels[c['id']]['project']=='M22/光子嫩肤'
                and labels[c['id']]['content_type'] in ('科普','对比选型','滤片解析')]
        if pool:
            break
    else:
        return {'status':'empty', 'message':'还没有可分析的 M22 科普案例，请先在案例资料中导入相关 ZIP。'}
    unique={}
    for c in pool:
        if any(x.strip() for x in [c['title'],c['body']]+[p['ocr'] for p in c['pages']]):
            unique.setdefault(c['url'],c)
    pool=list(unique.values())
    pool.sort(key=lambda c:-(c.get('likes') if c.get('likes') is not None else -1))
    # One per subtype first, then fill to five by snapshot likes.
    chosen=[]; kinds=set()
    for c in pool:
        kind=labels[c['id']]['content_type']
        if kind not in kinds:
            chosen.append(c); kinds.add(kind)
    chosen=(chosen+[c for c in pool if c not in chosen])[:5]
    samples=[{'sample_id':f'S{i+1}', 'title':c['title'], 'body':c['body'][:3000],
              'ocr':'\n'.join(p['ocr'] for p in c['pages'])[:6000],
              'likes':c.get('likes'), 'url':c['url'], 'content_type':labels[c['id']]['content_type']}
             for i,c in enumerate(chosen)]
    signature={'schema':ResearchConclusion.model_json_schema(),'policy':INSTRUCTION, 'bundle_id':manifest['bundle_id'], 'samples':samples}
    report_id=hashlib.sha256(json.dumps(signature,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:32]
    try:
        cached=read(root,report_id)
        ResearchConclusion.model_validate(cached['analysis'])
        return {**cached,'cached':True}
    except (FileNotFoundError,ValueError,KeyError):
        pass
    analysis,trace=llm.generate(ResearchConclusion, {'action':INSTRUCTION,'topic':'M22科普','samples':samples}, [])
    by_id={s['sample_id']:s for s in samples}
    for finding in analysis.findings:
        source=by_id.get(finding.sample_id)
        if not source or not normal(finding.quote) or not any(normal(finding.quote) in normal(source[key]) for key in ('title','body','ocr')):
            raise ValueError('调研引文与原帖不一致，请点击重试；本次结果未保存')
    if not set(analysis.reference_ids)<=set(by_id):
        raise ValueError('调研引用了样本外的帖子，请点击重试')
    report={'status':'ready','id':report_id,'bundle_id':manifest['bundle_id'],
            'created_at':datetime.now(timezone.utc).isoformat(),'eligible_count':len(pool),'sample_count':len(samples),
            'coverage':'已导入帖子正文与OCR；未读取评论正文，未进行原图视觉分析。',
            'sampling':'从最新相关资料包中，兼顾内容类型与点赞快照选取最多5篇；不是全平台市场调查。',
            'analysis':analysis.model_dump(),'samples':samples,'cached':False,
            'model':{'provider':trace.get('provider'),'model':trace.get('model')},'trace':trace}
    folder=Path(root)/'research';folder.mkdir(parents=True,exist_ok=True)
    temporary=folder/f'{report_id}.tmp';temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(folder/f'{report_id}.json')
    return report
