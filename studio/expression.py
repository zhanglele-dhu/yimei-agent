"""Expression first: confirmed purpose/style controls retrieval and writing."""
import hashlib
import json
import re
from datetime import datetime,timezone
from .models import ExpressionStudy, MaterialSheet, Analysis, ObservedPage
from . import writing_style

STUDY = (
 '你是同类内容编辑，只学习提供的小红书样本怎样表达。目的由用户request确定，不能另换选题或改成术语分类课。'
 '提炼开头、叙述顺序、语气、具体句式、信息展示方式和正反例，供后续文章实际沿用；不是泛泛建议。'
 '结构要适应用户目的。opening必须是可直接发布的开头，不能说将采用闺蜜口吻或介绍写作计划。'
 'writing_style是用户选择的文风目标，优先于技术型原帖的中性语气；不要把平实客观自动当作目标。'
 '先学习writing_style.source_examples中的具体衔接方法，再结合本篇参考提炼结构；不将原帖经历和功效作为自己的事实。'
 '知识范围以用户明确要介绍的内容为准，参考帖的对象清单不能变成本篇必须覆盖的清单。'
 '例如只介绍滤片作用，不自动扩成逐张滤片、波段与疗程大全。knowledge_needs只列完成此目的需查证的知识，最多6项。'
 'evidence每条选择quote_options里真实存在的quote_id与sample_id，quote留空由程序填回原文；lesson说明该片段的表达方法。不能编造编号或拼接原文。'
 'good_example/bad_example只示范句式，用[知识点]等占位符示范组织方法，不写具体参数、功效、疗程或真实经历。若看图仅观察本次确有图片输入的页面；'
 '其余样本只分析正文与OCR；不能把OCR顺序推断成颜色与画面布局。presentation可写本篇展示建议。'
 '只输出schema要求的简短JSON，不输出思维链。'
)
MATERIALS = (
 '根据confirmed_expression的固定目的与knowledge_needs，整理本篇资料单。'
 '每个item说明需要讲的知识、资料支持的answer、具体supports及scope。supports选择quote_options里的source_id和quote_id，quote留空由程序回填原文。'
 '支持引文必须实际支持answer，不能用资料标题或链接冒充知识依据；无对应片段就放missing。'
 '资料提供知识，不改变已确认的叙述顺序、语气、受众和目的。不要把查到的所有术语与参数都塞入本篇。'
 '仅使用所附FACT资料；缺少支持的知识放missing，不从小红书参考帖推断医学答案，不编造引文。'
 '必要事实冲突明确放missing请求人工决定，不能为保持表达而写错误知识。'
)
CHECK = (
 '只检查成稿是否保持confirmed_expression的目的、叙述结构和语气，分别判断purpose_kept/structure_kept/tone_kept。'
 '尤其检查是否被知识检索结果改成术语分类课、到店提问清单或免责说明；参考原帖的具体组织方式是否落实。'
 '准确改写、为必要全称合理分页允许；结构指信息关系而非必须相同字数或页数。'
 '真实偏离放issues，轻微措辞优化只放suggestions。expression_check是本次审稿必填子对象，包含purpose_kept、structure_kept、tone_kept、issues、summary；不能省略。不以事实核查为由扩题或换叙述方式。'
)

WRITE = (
 '按照已确认的confirmed_expression.prompt写小红书图文，objective为固定目的。'
 '保留确认的叙述关系、语气、句式和展示方式；plan仅为摘要，用户确认的prompt是表达执行准则。'
 '正文知识只取自本篇资料单和可靠来源；表达提示词中的参考句式不是医学依据。'
 'writing_style提供所选类别的逐条语气标准和表达正反例；在实际句子中逐条落实所选标准，不能把所有类别都写成分享口吻。直接介绍知识，不对读者解释自己的写作计划。'
 '语气样本只借句式，不借知识；换语气不能新增资料单以外的机制、效果、配置或操作建议。即使是常见知识，也不能为让一句话更有说服力而补进来。'
 '按word_budget写具体小标题加短解释，每点只新增一项信息；直接说它做什么，不给知识再套一层它很值得了解或比较好理解的评价。'
 '类比后不再换几种说法重复同一机制。'
 '先介绍特点与分工，再补必要原理，不能只把术语换成口语词。'
 '资料单和可靠来源用于补知识，不能因查到更多术语改变文章目的或改成技术分类课。'
 '按确认outline的页数、顺序、kind与每页问题起草；不要重规划受众与内容方向。'
 'pages.title为图片标题，pages.text为直接给读者看的正文，不复述标题、不含Markdown加粗符号。'
 '发布title/body表达本篇价值，短段自然衔接；audience_brief沿用editorial_plan。'
 '每个专业缩写首次出现时展开英文全称和中文；M22等型号不硬编全称。'
 '支持事实的来源编号放source_ids，具体资料缺口放pending/missing_information，允许为空；'
 '涉及读者判断的适用条件随对应知识解释，内部审稿、拍摄、排版说明留在内部字段。'
 '资料不足或冲突时指出具体缺口，不编事实，也不自行更换已确认的目的与表达。'
 'chat页按dialog输出customer/shop示意问答并在text保留同内容；photo不虚构照片中的事实。'
)
REVIEW = (
 '你是独立内容编辑，在成图前一次检查知识与表达。以用户原始需求、确认表达prompt和确认大纲为准。'
 '检查audience_fit、direction_fit、question_coverage、readable、source_supported；逐页输出passed/issues/suggestions。'
 '来源编号存在不等于支持句子，核对具体关系、版本与适用范围；小红书原帖不作医学证据。'
 '逐句检查语气改写有没有额外补进机制、效果、配置或操作建议。资料只支持筛选波段时，不能据此声称吸收更集中；样本句式、常识和模型记忆都不补足缺失依据。'
 '检查必要专业缩写首次释义；品牌型号不编全称。准确通俗类比允许，不要求来源逐字出现。'
 '表达方式以已确认方案为准，不额外套固定口吻或页数。真实偏题、难懂、具体事实无依据属于必改issues，'
 '仅可润色的措辞或可选细节放suggestions，不阻断成图；不得扩充确认大纲或塞入通用免责声明。'
)


def enabled(task):
    return task.get('request',{}).get('workflow')=='expression-first'


def context(task):
    e=task['expression']
    # After adoption, retain the writing contract, not raw competitor medical text.
    return {key:e[key] for key in ('objective','status','hash','prompt')}


def factual_sources(sources):
    return [s for s in sources if s['id'] not in ('CASE','GUIDE','INTENT')
            and not (s['id']=='KB' and s.get('references'))]


def samples(task):
    c=task['case'];rows=[]
    if not writing_style.is_template(c.get('body','')):
        rows.append({'sample_id':'MAIN','title':c['title'],'body':c['body'],
                     'ocr':'\n'.join(p['ocr'] for p in c['pages']),'url':c['url']})
    # Actual conversational snippets have their own provenance and quote options.
    for example in task.get('writing_style',{}).get('source_examples',[]):
        if not any(row['url']==example['url'] for row in rows):
            rows.append({'sample_id':'STYLE_'+example['case_id'],'title':example['title'],
                         'body':example['quote'],'ocr':'','url':example['url']})
    for row in task.get('research',{}).get('samples',[]):
        if not writing_style.is_template(row.get('body','')) and not any(x['url']==row['url'] for x in rows):
            rows.append(dict(row))
    return rows[:7]


def normalize(value):
    return re.sub(r'\s+','',value)


def quote_options(rows):
    options=[]
    for row in rows:
        chunks=[]
        for field in ('title','body','ocr'):
            text=row.get(field,'')
            # Bound each literal excerpt; never ask the model to retype OCR.
            for block in re.split(r'\n\s*\n',text):
                for start in range(0,len(block),220):
                    snippet=block[start:start+220].strip()
                    if snippet and snippet not in chunks:chunks.append(snippet)
        for index,quote in enumerate(chunks[:12],1):
            options.append({'sample_id':row['sample_id'],'quote_id':row['sample_id']+'-Q'+str(index),'quote':quote})
    return options


def study(task, invoke, feedback='', images=None):
    rows=samples(task)
    if not rows:raise ValueError("没有可用的表达样本，请补充相关参考内容")
    options=quote_options(rows)
    result=invoke(task,ExpressionStudy,{'action':STUDY,'request':task['request'],
        'quote_options':options,
        'samples':rows,'visual_input':bool(images),'feedback':feedback,
        'previous_expression':task.get('expression',{}).get('plan')},images=images)
    for item in result.evidence:
        if item.quote_id:
            chosen=next((q for q in options if q['quote_id']==item.quote_id and q['sample_id']==item.sample_id),None)
            if not chosen:raise ValueError('表达分析引用了不存在的原文片段，请重试')
            item.quote=chosen['quote']
        source=next((s for s in rows if s['sample_id']==item.sample_id),None)
        if not source or not normalize(item.quote) or not any(normalize(item.quote) in normalize(source.get(k,'')) for k in ('title','body','ocr')):
            raise ValueError('表达分析引文与参考原文不一致，请重试')
    prompt=compile_prompt(task,result)
    previous=task.get('expression')
    if previous:task.setdefault('expression_history',[]).append(previous)
    task['expression']={'status':'proposed','plan':result.model_dump(),'prompt':prompt,
                        'samples':rows,'basis':'主参考原图与样本文字' if images else '样本正文与OCR',
                        'objective':task['request']['question']}
    for key in ('material_sheet','material_sources','confirmed_analysis','analysis','editorial_plan','editorial_outline','draft_content_review'):
        task.pop(key,None)
    # Required nullable fields remain compatible with existing task serialization.
    task.update(analysis=None,confirmed_analysis=None,stage='expression_review')
    return task


def compile_prompt(task,plan):
    style=task.get('writing_style',{})
    return '\n'.join(['---','name: xhs-expression-'+task['id'][:8],
        'description: '+json.dumps('按已确认的受众、结构和语气撰写本篇小红书图文；知识资料只补充事实。',ensure_ascii=False),
        '---','# 本篇表达提示词','', '## 文风目标',style.get('guide','沿用用户确认的表达口吻'), '## 固定目的',task['request']['question'],
        '## 受众',plan.audience,'## 开头',plan.opening,'## 叙述顺序',
        *[f'- {s}' for s in plan.structure], '## 语气',plan.tone,'## 句式',plan.sentence_pattern,
        '## 展示方式',plan.presentation,'## 正例（仅示范表达）',plan.good_example,
        '## 反例（应避免的表达）',plan.bad_example,'## 需要补充的知识',
        *[f'- {s}' for s in plan.knowledge_needs],
        '## 执行要求','检索资料只补充知识，保持上述目的、叙述关系和语气；事实冲突或资料不足单独列出，由用户决定。',
        '每个专业缩写首次出现时展开英文全称和中文名称；型号和商标不硬编全称。'])


def accept(task,prompt,root):
    e=task['expression']
    if e['status']=='accepted':raise ValueError('表达方案已确认，需要修改请明确重做同类分析')
    signature=hashlib.sha256((e['objective']+'\n'+prompt).encode()).hexdigest()
    e.update(status='accepted',prompt=prompt,hash=signature,confirmed_at=datetime.now(timezone.utc).isoformat())
    folder=root/'expression_skills'/signature;folder.mkdir(parents=True,exist_ok=True)
    (folder/'SKILL.md').write_text(prompt,encoding='utf-8')
    p=e['plan']
    task['editorial_plan']={'audience_brief':{'reader':p['audience'],'questions':p['knowledge_needs'][:5],
        'approach':p['tone']+'；'+p['sentence_pattern'],'defer_topics':[]},
        'direction':e['objective'][:300],'reading_goal':e['objective'][:300],'reference_use':'；'.join(p['structure'])[:600]}
    task['stage']='materials_pending'


def source_text(value):
    if isinstance(value,str):return value
    if isinstance(value,dict):return '\n'.join(source_text(v) for v in value.values())
    if isinstance(value,list):return '\n'.join(source_text(v) for v in value)
    return str(value)


def materialize(task,invoke,sources):
    options=[]
    for source in sources:
        if source['id'] in ('CASE','GUIDE','INTENT','KB'):continue
        content=source['content']
        if isinstance(content,dict) and content.get('facts'):
            chunks=[source_text(value) for value in content['facts']]
        else:
            chunks=[p.strip() for p in re.split(r'\n+',source_text(content)) if p.strip()]
        excerpts=[]
        for chunk in chunks:
            excerpts.extend(chunk[start:start+450] for start in range(0,len(chunk),450))
        for index,quote in enumerate(excerpts[:24],1):
            options.append({'source_id':source['id'],'quote_id':source['id']+'-Q'+str(index),'quote':quote})
    result=invoke(task,MaterialSheet,{'action':MATERIALS,'knowledge_needs':task['expression']['plan']['knowledge_needs'],
                                   'quote_options':options})
    allowed={s['id']:s for s in sources if s['id'] not in ('CASE','GUIDE','INTENT','KB')}
    for item in result.items:
        for support in item.supports:
            if support.quote_id:
                chosen=next((q for q in options if q['quote_id']==support.quote_id and q['source_id']==support.source_id),None)
                if not chosen:raise ValueError('资料单引用了不存在的资料片段，请重试')
                support.quote=chosen['quote']
            source=allowed.get(support.source_id)
            if not source or not normalize(support.quote) or normalize(support.quote) not in normalize(source_text(source['content'])):
                raise ValueError('资料单的支持引文与实际资料不一致，请重试')
    task['material_sheet']=result.model_dump()
    task['material_sources']=sources
    pages=[ObservedPage(number=p['number'],form='参考原文',observation=p['ocr'][:500],
        borrow=task['expression']['plan']['presentation']) for p in task['case']['pages']]
    return Analysis.model_construct(summary=task['expression']['objective'], original_pages=pages,borrow=task['expression']['plan']['structure'],
                    missing_information=result.missing,outline=[])

