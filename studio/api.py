import hashlib
import hmac
import io
import json
import os
import re
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

from . import cases, llm, prompts, rendering, runlog, model_card, seedream_card, semantic, editorial, research, expression, writing_style, tones
from .models import (CreateTask, Revision, Analysis, AnalysisConfirmation, Draft, PageEdit,
                     CopyEdit, Progress, FeedbackInput, FeedbackAnalysis, AnalysisStageDecision,
                     ToneBatchInput, ToneVersion, ExpressionStudy, ExpressionConfirm, MaterialSheet, ExpressionCheck, CaseRanking, VisionRelevance, AnalysisCompact, CardModelSettings, IntentInput, CatalogInput, EditorialPlan, DraftContentReview)

ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env',override=False)
CARD_SETTINGS_PATH=Path(os.getenv('STUDIO_CARD_SETTINGS_FILE',str(ROOT/'.env.card-model')))
load_dotenv(CARD_SETTINGS_PATH,override=False)
DATA=Path(os.getenv('STUDIO_DATA_DIR',str(ROOT/'outputs/studio'))).resolve()
DATA.mkdir(parents=True,exist_ok=True)
BUNDLES=DATA/'bundles'
TOKEN=os.getenv('STUDIO_ACCESS_TOKEN','')
VERSION='cases-20261027-3'
ANALYSIS_STAGES=('retrieval','language','visual','facts','writing')
STAGE_LABELS_ZH={'retrieval':'第1步检索','language':'第2步语言分析','visual':'第3步视觉分析','facts':'第4步事实资料','writing':'第5步写作规则'}
MAX_VISION_PAGES=12  # 视觉轨单次看图上限：配合 llm.py 的 token 预算，超过则降级文字轨
if len(TOKEN)<24:raise RuntimeError('请使用启动脚本，或配置至少24字符的STUDIO_ACCESS_TOKEN')
Image.MAX_IMAGE_PIXELS=16_000_000

@contextmanager
def db():
    conn=sqlite3.connect(DATA/'tasks.sqlite3',timeout=15)
    try:
        with conn:
            conn.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, revision INTEGER, body TEXT)')
            yield conn
    finally:conn.close()

def auth(authorization: str=Header(default='')):
    if not hmac.compare_digest(authorization,'Bearer '+TOKEN):raise HTTPException(401,'本机访问验证已失效，请刷新页面')

app=FastAPI(title='一步一拍',version=VERSION,docs_url=None,redoc_url=None,openapi_url=None)
app.mount('/static',StaticFiles(directory=Path(__file__).parent/'static'),name='static')

@app.middleware('http')
async def headers(request,call_next):
    response=await call_next(request)
    response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
        'X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"})
    return response

@app.get('/')
def home():return FileResponse(Path(__file__).parent/'static/index.html')

@app.get('/healthz')
def health():return {'status':'ok','version':VERSION}


@app.get('/api/card-model-settings',dependencies=[Depends(auth)])
def card_model_settings():
    config=llm.card_model_config()
    return {'provider':config['provider'],'base_url':config['base_url'],'model':config['design_model'],
            'review_model':config['review_model'],'key_configured':bool(config['api_key']),
            'ready':bool(llm.supports_card_design()),'pipeline':'skill_model_html',
            'original_photo_layout':True,
            'seedream_ready':bool(seedream_card.config()['api_key']) and llm.supports_card_design(),
            'seedream_model':seedream_card.config()['model']}


@app.post('/api/card-model-settings',dependencies=[Depends(auth)])
def save_card_model_settings(body: 'CardModelSettings'):
    base=body.base_url.strip().rstrip('/')
    parsed=urlsplit(base)
    if (parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or '\\' in base):
        raise HTTPException(422,'请填写有效的API地址，不包含用户名、密码或查询参数')
    if parsed.scheme=='http' and parsed.hostname not in ('127.0.0.1','localhost','::1'):
        raise HTTPException(422,'远程API地址请使用HTTPS')
    current_config=llm.card_model_config()
    if not body.api_key.strip() and current_config['base_url']!=base:
        raise HTTPException(422,'更换接口地址时，请同时填写该平台的新密钥')
    if not body.model.strip():raise HTTPException(422,'请填写视觉模型名称')
    key=body.api_key.strip() or current_config['api_key']
    if not key:raise HTTPException(422,'请填写该视觉模型平台的API密钥')
    if '\n' in key or '\r' in key:raise HTTPException(422,'密钥中不能包含换行')
    values={'STUDIO_CARD_PROVIDER':'custom','STUDIO_CARD_BASE_URL':base,'STUDIO_CARD_API_KEY':key,
            'STUDIO_CARD_DESIGN_MODEL':body.model.strip(),'STUDIO_CARD_REVIEW_MODEL':body.review_model.strip() or body.model.strip()}
    path=CARD_SETTINGS_PATH;path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text('\n'.join(name+'='+json.dumps(value,ensure_ascii=False) for name,value in values.items())+'\n',encoding='utf-8')
    os.replace(temporary,path)
    os.environ.update(values)
    return card_model_settings()


@app.get('/api/local-session')
def local_session(request: Request):
    """Only the loopback launcher can bootstrap a same-origin browser session."""
    if os.getenv('STUDIO_LOCAL_SESSION') != '1':
        raise HTTPException(403, '当前启动方式不支持本机自动进入')
    if (not request.client or request.client.host not in ('127.0.0.1', '::1')
            or request.url.hostname not in ('127.0.0.1', 'localhost', '::1')
            or request.headers.get('x-studio-local') != '1'
            or request.headers.get('sec-fetch-site', '') not in ('', 'same-origin', 'none')
            or request.headers.get('origin', str(request.base_url).rstrip('/')) != str(request.base_url).rstrip('/')):
        raise HTTPException(403, '仅允许从本机页面打开')
    return {'access_token': TOKEN}

def get_task(task_id,editable=False):
    with db() as conn:row=conn.execute('SELECT body FROM tasks WHERE id=?',(task_id,)).fetchone()
    if row is None:raise HTTPException(404,'任务不存在')
    task=json.loads(row[0])
    if editable and task.get('schema_version')!=2:
        raise HTTPException(409,'这是旧版任务，可查看历史；请新建任务使用案例流程，旧数据不会被覆盖')
    return task

def save(task,previous):
    task['revision']=previous+1
    task['updated_at']=datetime.now(timezone.utc).isoformat()
    with db() as conn:
        cursor=conn.execute('UPDATE tasks SET revision=?,body=? WHERE id=? AND revision=?',
            (task['revision'],json.dumps(task,ensure_ascii=False),task['id'],previous))
        if cursor.rowcount!=1:raise HTTPException(409,'任务已变化，请刷新后重试')
    return task

def current(task_id,revision):
    task=get_task(task_id,True)
    if task['revision']!=revision:raise HTTPException(409,'任务已变化，请刷新后重试')
    return task

_KB_SEARCH_CACHE = {}


def kb_source(task):
    """RAG：按任务问题从知识库语义检索 top-k 片段，作为第4步事实资料的 KB 来源。
    知识库不存在或向量化失败时返回 None（不阻断主流程）。结果按问题缓存，避免重复调用 embedding。"""
    question = (task.get('request', {}) or {}).get('question') or ''
    evidence_dir = DATA / 'knowledge_base' / 'm22'
    subject = ((task.get('request') or {}).get('project', '') + ' ' + question).lower()
    if question.strip() and any(term in subject for term in ('m22', 'aopt', 'ipl', '光子', '强脉冲')) and (evidence_dir / 'manifest.json').exists():
        from .evidence import search_library
        request_data = task.get('request') or {}
        intent = task.get('intent') or {}
        query = request_data.get('project', '') + ' ' + (intent.get('goal') or question)
        query += ' ' + ' '.join(intent.get('must_cover') or [])
        if expression.enabled(task) and task.get('expression',{}).get('status')=='accepted':
            query = task['expression']['objective']+' '+' '.join(task['expression']['plan']['knowledge_needs'])
        try:
            fingerprint = (evidence_dir / 'manifest.json').stat().st_mtime_ns
        except OSError:
            return None
        cache_key = ('m22-evidence', str(evidence_dir), fingerprint, query)
        if cache_key not in _KB_SEARCH_CACHE:
            try:
                references = search_library(evidence_dir, query)
            except (OSError, ValueError, KeyError):
                return None
            if references:
                _KB_SEARCH_CACHE[cache_key] = {'id': 'KB', 'type': '按主题检索的M22分类资料（厂商、论文、共识与讨论分级）',
                    'content': [r.get('title_zh', r['title']) + '：' + '；'.join(r['facts']) + ' 来源：' + r['url'] for r in references],
                    'references': references}
        if cache_key in _KB_SEARCH_CACHE:
            return _KB_SEARCH_CACHE[cache_key]
        return None
    store_dir = DATA / 'knowledge_base' / 'store'
    if not question.strip() or not (store_dir / 'meta.json').exists():
        return None
    cached = _KB_SEARCH_CACHE.get(question)
    if cached is None:
        try:
            from .knowledge import KnowledgeStore, embed_texts
            store = KnowledgeStore.load(store_dir)
            qvec = embed_texts([question])[0]
            top = store.search(qvec, top_k=6, query_text=question)
            items = []
            for h in top:
                raw = h['meta']
                info = {}
                if isinstance(raw, dict):
                    inner = raw.get('source')
                    if isinstance(inner, str):
                        try:
                            info = json.loads(inner)
                        except ValueError:
                            info = {'file': inner[:40]}
                elif isinstance(raw, str):
                    try:
                        info = json.loads(raw)
                    except ValueError:
                        info = {'file': raw[:40]}
                tag = f"{info.get('category', '')}｜{info.get('file', '')}"
                items.append(f"{h['text']}（相关度{h['score']}｜{tag}｜{info.get('source_line', '')}）")
            cached = {'id': 'KB', 'type': 'RAG 检索的公开知识库摘录（网络采集+大模型分类+向量检索，未经独立核实，非医学证据）',
                      'content': items}
        except Exception as exc:
            _KB_SEARCH_CACHE[question] = None
            print('知识库检索失败（不阻断）：', str(exc)[:120])
            return None
        _KB_SEARCH_CACHE[question] = cached
    return dict(cached) if cached else None


def sources_for(task):
    if expression.enabled(task):
        if task.get('expression',{}).get('status')!='accepted':
            return [{'id':'CASE','type':'表达参考，尚未检索事实资料','content':task.get('case')}]
        if task.get('material_sources'):
            return expression.factual_sources(task['material_sources'])
    result=[{'id':'GUIDE','type':'人工确认的流程边界，非医学证据',
             'content':json.loads((ROOT/'knowledge/shooting_guide.json').read_text(encoding='utf-8-sig'))},
            {'id':'SHOP','type':'用户提供，未经独立核实','content':task['request']['facts']}]
    if 'm22' in task['request']['project'].lower():
        result.append({'id':'K1','type':'厂商资料摘要，非门店配置证明',
                       'content':(ROOT/'knowledge/procedures.md').read_text(encoding='utf-8-sig')})
    if task.get('case'):
        result.append({'id':'CASE','type':'参考笔记，仅借鉴结构，不作为医学事实证据','content':task['case']})
    if task.get('intent'):
        result.append({'id':'INTENT','type':'本次创作方向，控制选题，不提供医学事实','content':task['intent']})
    kb=kb_source(task)
    if kb:
        result.append(kb)
        for reference in kb.get('references', []):
            result.append({'id': reference['id'], 'type': reference['kind'] + '｜' + reference.get('scope', ''),
                'content': {k:reference[k] for k in ('title', 'url', 'kind', 'scope', 'access_level', 'facts', 'evidence_use',
                    'categories', 'limitations', 'design', 'population', 'doi', 'pmid', 'published_date') if k in reference}})
    return expression.factual_sources(result) if expression.enabled(task) else result

def invoke(task,schema,instruction,images=None,outline_anchor=None):
    sources=[] if schema is ExpressionStudy else sources_for(task)
    if task.get('writing_style'):
        instruction={**instruction,'writing_style':task['writing_style'] if schema is ExpressionStudy else writing_style.context(task)}
    if schema is MaterialSheet:
        sources=[s for s in sources if s['id'] not in ('CASE','GUIDE','INTENT','KB')]
    if expression.enabled(task) and schema is not ExpressionStudy:
        if task.get('expression',{}).get('status')=='accepted':
            instruction={**instruction,'confirmed_expression':expression.context(task),
                'expression_rule':'保持已确认的目的、叙述结构、语气和句式，以用户确认的prompt为表达执行准则，plan仅为摘要。资料只补知识，冲突单独列出；不得静默更改表达方案。'}
            if task.get('material_sheet'):instruction={**instruction,'material_sheet':task['material_sheet']}
    if task.get('research') and isinstance(instruction,dict) and schema is not ExpressionStudy and not expression.enabled(task):
        instruction={**instruction,'research_brief':task['research']['analysis'],
                     'research_scope':'样本内容观察和AI创作建议；不是医学事实来源或全平台需求结论'}
    if schema in (DraftContentReview,EditorialPlan):
        sources=[s for s in sources if s['id']!='INTENT']
    if task.get('intent') and isinstance(instruction,dict) and schema not in (DraftContentReview,EditorialPlan) and not expression.enabled(task):
        instruction={**instruction,'creation_intent':task['intent'],
                     'intent_rule':'严格围绕goal和must_cover创作，avoid中的方向不得成为主题。参考案例学习知识组织和信息密度；缺少事实补入待核实，不把科普偷换为到店咨询。'}
    if task.get('editorial_plan') and isinstance(instruction,dict):
        instruction={**instruction,'editorial_plan':task['editorial_plan'],
                     'intent_rule':'以用户原始问题和确认内容为准，遵循受众方案；creation_intent的自动推测不能无限扩充本篇知识点。'}
    try:
        if images:
            result,trace=llm.generate_vision(schema,instruction,sources,images,outline_anchor=outline_anchor)
        else:
            result,trace=llm.generate(schema,instruction,sources,outline_anchor=outline_anchor)
    except Exception as exc:
        task.setdefault('failures',[]).append({'action':schema.__name__,'error_type':type(exc).__name__,
                                               'detail':str(exc)[:300],
                                               'time':datetime.now(timezone.utc).isoformat()})
        runlog.event(task,DATA,'⚠ 模型调用失败',{'错误':[f"{schema.__name__} {type(exc).__name__}：{str(exc)[:120]}"],
                                                 '说明':['进度已保存，等待用户手动重试；不会自动循环调用']})
        save(task,task['revision'])
        raise HTTPException(502,'模型未完成，本次已停止。已保存进度，请手动重试；不会自动循环调用。') from None
    trace['sources']=sources
    trace['time']=datetime.now(timezone.utc).isoformat()
    trace['source_hashes']={s['id']:hashlib.sha256(json.dumps(s,ensure_ascii=False,sort_keys=True).encode()).hexdigest() for s in sources}
    task['traces'].append(trace)
    return result

@app.post('/api/bundles',dependencies=[Depends(auth)])
def import_bundle(bundle: UploadFile=File(...)):
    raw=bundle.file.read(cases.MAX_BUNDLE+1)
    try:manifest=cases.install(raw,BUNDLES)
    except Exception as exc:
        raise HTTPException(422,'资料包无效：'+(str(exc) if isinstance(exc,ValueError) else '文件结构或必需字段错误')) from None
    return {'bundle_id':manifest['bundle_id'],'version':manifest['version'],'count':len(manifest['cases'])}

@app.get('/api/bundles',dependencies=[Depends(auth)])
def bundles():
    result=[]
    for p in sorted(BUNDLES.glob('*.zip'),key=lambda p:p.stat().st_mtime,reverse=True):
        m=cases.load(BUNDLES,p.stem)
        result.append({'bundle_id':p.stem,'version':m['version'],'count':len(m['cases'])})
    return result

@app.post('/api/research/m22',dependencies=[Depends(auth)])
def research_m22():
    try:
        result=research.conclude(DATA,BUNDLES)
    except Exception as exc:
        message=str(exc) if isinstance(exc,ValueError) else '调研模型暂未完成，请点击重试；已有任务保持不变'
        raise HTTPException(502,message) from None
    return {key:value for key,value in result.items() if key!='trace'}


def tone_manifest(bundle_id=''):
    if bundle_id:
        try:return cases.load(BUNDLES,bundle_id)
        except (ValueError,FileNotFoundError):raise HTTPException(422,'案例资料包不存在') from None
    paths=sorted(BUNDLES.glob('*.zip'),key=lambda p:p.stat().st_mtime,reverse=True)
    return cases.load(BUNDLES,paths[0].stem) if paths else None


@app.get('/api/tone-presets',dependencies=[Depends(auth)])
def tone_presets():return {'presets':tones.PRESETS,'version':tones.VERSION}


@app.get('/api/tones',dependencies=[Depends(auth)])
def tone_catalog(bundle_id:str=''):
    manifest=tone_manifest(bundle_id)
    if not manifest:return {'bundle_id':None,'presets':[{**p,'count':0} for p in tones.PRESETS],
        'summary':{'total':0,'classified':0,'uncertain':0,'excluded':0,'pending':0},'items':[],'scope':'请先导入案例资料包'}
    return tones.catalog(DATA,manifest)


@app.post('/api/tones/analyze',dependencies=[Depends(auth)])
def analyze_tones(body:ToneBatchInput):
    manifest=tone_manifest(body.bundle_id)
    if not manifest:raise HTTPException(409,'请先导入案例资料包')
    try:return tones.analyze_batch(DATA,manifest)
    except Exception as exc:
        detail=str(exc) if isinstance(exc,ValueError) else '语义分类暂未完成，已完成的批次保留，可重试'
        raise HTTPException(502,detail) from None


@app.get('/api/catalog',dependencies=[Depends(auth)])
def case_catalog(bundle_id:str='',project:str='',content_type:str='',q:str=''):
    result=[]
    for p in sorted(BUNDLES.glob('*.zip')):
        if bundle_id and p.stem!=bundle_id:continue
        m=cases.load(BUNDLES,p.stem)
        result.extend(semantic.catalog(DATA,m)['items'])
    projects={};types={}
    for item in result:
        projects[item['project']]=projects.get(item['project'],0)+1
        types[item['content_type']]=types.get(item['content_type'],0)+1
    items=[i for i in result if (not project or i['project']==project) and (not content_type or i['content_type']==content_type)
           and (not q or q.lower() in json.dumps({k:i[k] for k in ('title','summary','topics')},ensure_ascii=False).lower())]
    items.sort(key=lambda i:-(i['likes'] if i['likes'] is not None else -1))
    return {'total':len(result),'matched':len(items),'model_classified':sum(i['method']=='model' for i in result),
            'projects':projects,'content_types':types,'items':items}

@app.post('/api/intent',dependencies=[Depends(auth)])
def creation_intent(body:IntentInput):
    intent,trace=semantic.understand(body.text,body.project,body.audience)
    return {'intent':intent.model_dump(),'understanding':trace}

@app.post('/api/catalog/classify',dependencies=[Depends(auth)])
def classify_cases(body:CatalogInput):
    try:m=cases.load(BUNDLES,body.bundle_id)
    except (ValueError,FileNotFoundError):raise HTTPException(422,'资料包不存在') from None
    data=semantic.enrich(DATA,m,batch_limit=1)
    return {'total':len(data['items']),'model_classified':data['model_classified'],'errors':len(data['errors'])}

@app.get('/api/tasks',dependencies=[Depends(auth)])
def list_tasks():
    result=[]
    with db() as conn:rows=conn.execute('SELECT body FROM tasks ORDER BY rowid DESC LIMIT 100').fetchall()
    for r in rows:
        t=json.loads(r[0])
        result.append({'id':t['id'],'project':t['request']['project'],'question':t['request']['question'],
                       'stage':t.get('stage',''),'legacy':t.get('schema_version')!=2,'revision':t.get('revision',0),
                       'updated_at':t.get('updated_at',''),'exported':bool(t.get('copy_review',{}) and t['copy_review'].get('confirmed'))})
    return result

def rank_and_select(manifest, project, question, audience, intent=None):
    """模型给相关性打分，代码用收益函数排序；模型失败回退关键词规则。"""
    pool = semantic.match_pool(manifest,intent,semantic.catalog(DATA,manifest)) if intent else cases.project_gate(manifest, project)
    pool = [c for c in pool if c.get('likes') is not None]
    if not pool:
        return None, {'eligible_count': 0, 'reason': '没有相关案例。请修改主题或导入相关资料，不套用其他主题。'}
    cards = [{'case_id': c['id'], 'title': c['title'], 'likes': c['likes'],
              'cover_ocr': c['pages'][0]['ocr'][:350],'body':c.get('body','')[:350]} for c in pool]
    try:
        ranking, trace = llm.generate(CaseRanking, {
            'action': prompts.RANK_SCORING,
            'question': question, 'audience': audience,'creation_intent':intent.model_dump() if intent else None},
            [{'id': 'CASELIST', 'type': '候选案例清单（标题/点赞/首图OCR摘要）', 'content': cards}])
    except Exception:
        selected, fallback = cases.select({**manifest,'cases':pool}, project, question)
        if selected:
            fallback['reason'] = '模型打分未完成，已回退关键词规则：' + fallback['reason']
        fallback['ranking_call'] = {'provider': 'deepseek', 'outcome': 'failed_fallback'}
        return selected, fallback
    selection_ranking_call = {'provider': trace.get('provider', 'deepseek'),
                              'elapsed_ms': trace.get('elapsed_ms'),
                              'usage': trace.get('usage'),
                              'attempts': [a.get('outcome') for a in trace.get('attempts', [])]}
    scores = {item.case_id: item.relevance for item in ranking.scores}
    # 视觉补判：首图OCR文字过少(<40字)但点赞高(≥500)的候选，文字依据不足，交视觉轨看图判相关度（每任务最多5篇）
    supplemented = 0
    if llm.supports_vision():
        sparse = [c for c in pool if len(c['pages'][0]['ocr'].strip()) < 40 and c['likes'] >= 500]
        sparse.sort(key=lambda c: -c['likes'])
        for c in sparse[:5]:
            try:
                img = cases.image_bytes(BUNDLES, manifest['bundle_id'], c['id'], 1)
                verdict, _ = llm.generate_vision(VisionRelevance,
                    {'action': prompts.VISION_RELEVANCE_JUDGE},
                    [{'id': 'FIRSTPAGE', 'type': '候选帖首图（文字信息不足，需看图判断）', 'content': {'title': c['title'], 'likes': c['likes']}}],
                    [{'number': 1, 'data': img}])
                scores[c['id']] = verdict.relevance
                supplemented += 1
            except Exception:
                continue
    ranked = cases.combine_ranking(pool, scores)
    if not ranked:
        selected, fallback = cases.select({**manifest,'cases':pool}, project, question)
        if selected:
            fallback['reason'] = '模型判定全部候选相关性不足，已回退关键词规则：' + fallback['reason']
        fallback['ranking_call'] = selection_ranking_call
        return selected, fallback
    top = ranked[0]
    top3 = [{'title': item['case']['title'], 'likes': item['case']['likes'],
             'relevance': item['relevance'], 'final': item['final']} for item in ranked[:3]]
    selection = {
        'eligible_count': len(pool),
        'reason': f"AI 读完 {len(pool)} 篇候选，认为《{top['case']['title']}》最能回答你的问题"
                  f"（相关度 {top['relevance']}/10，{top['case']['likes']} 赞）。"
                  f"点赞不是唯一标准：相关度不够的帖子再热门也不会被选中。"
                  + (f"另有 {supplemented} 篇文字过少的高赞帖由视觉模型看图补判。" if supplemented else ''),
        'metric': '综合分=相关性×7+点赞归一化×30，相关性≤3淘汰；相关性由模型判断，排序由代码计算',
        'candidate_ids': [item['case']['id'] for item in ranked],
        'method': 'llm_relevance_plus_likes',
        'ranking_call': selection_ranking_call,
        'scores': [{'case_id': item['case']['id'], 'relevance': item['relevance'], 'final': item['final']} for item in ranked],
        'top3': top3,
    }
    return top['case'], selection


@app.post('/api/tasks',dependencies=[Depends(auth)])
def create(body: CreateTask):
    try:m=cases.load(BUNDLES,body.bundle_id)
    except (ValueError,FileNotFoundError):raise HTTPException(422,'请先导入并选择案例资料包') from None
    research_report=None
    if body.research_id:
        try:research_report=research.read(DATA,body.research_id)
        except (ValueError,FileNotFoundError):raise HTTPException(422,'调研记录不存在，请返回选题重新调研') from None
        if research_report['bundle_id']!=body.bundle_id:raise HTTPException(422,'资料包已改变，请重新选择调研方向')
    intent,intent_trace=semantic.understand(body.question,body.project,body.audience)
    selected,selection=rank_and_select(m,intent.project,body.question,body.audience,intent=intent) if not intent.clarification else (None,{'eligible_count':0,'reason':intent.clarification})
    request_data=body.model_dump()
    request_data['project']=intent.project
    task={'schema_version':2,'id':uuid4().hex,'revision':0,'request':request_data,
          'intent':intent.model_dump(),'intent_understanding':intent_trace,
          'case':selected,'selection':selection,'stage':'candidate' if selected else 'no_match',
          'analysis':None,'confirmed_analysis':None,'draft':None,'assets':{},'renders':{},'page_reviews':{},
          'page_index':0,'traces':[],'failures':[],'feedback':[],'history':[],
          'updated_at':datetime.now(timezone.utc).isoformat(),
          'analysis_stages':{name:{'status':'ready' if name=='retrieval' and selected else 'blocked'} for name in ANALYSIS_STAGES},
          'analysis_decisions':[]}
    if research_report:task['research']=research_report
    if expression.enabled(task):task['writing_style']=writing_style.profile(DATA,m,body.writing_style)
    facts=request_data['facts']
    # 先写日志事件（确定日志文件名随任务存库），再入库；否则第二次事件会另起新文件
    runlog.event(task,DATA,'创建任务',{
        '输入':[f'主题：{body.project}；受众：{body.audience}',
                f'问题：{body.question}',
                (f'门店事实（{len(facts)}字）：{facts[:200]}…' if len(facts)>200 else f'门店事实：{facts}')]
               +[f'理解方向：{intent.content_type}；目标：{intent.goal}；识别方式：{intent_trace["method"]}'],
        '检索':[selection.get('reason',''),
                f"方式：{selection.get('method','规则')}；相关候选 {selection.get('eligible_count',0)} 篇"]
               + ([f"评分前三：{'；'.join(str(i+1)+'.《'+item['title']+'》' for i,item in enumerate(selection['top3']))}"] if selection.get('top3') else [])
               + ([f"打分调用：{runlog.trace_summary({'provider':selection['ranking_call'].get('provider'),'elapsed_ms':selection['ranking_call'].get('elapsed_ms'),'usage':selection['ranking_call'].get('usage'),'attempts':[{'outcome':o} for o in selection['ranking_call'].get('attempts',[])]})}"] if selection.get('ranking_call') else []),
        '结果':[('已选定案例：《'+task['case']['title']+'》（'+str(task['case'].get('likes'))+' 赞，'+str(len(task['case']['pages']))+'页）') if task['case'] else '没有相关案例（stage=no_match）']})
    with db() as conn:conn.execute('INSERT INTO tasks VALUES (?,?,?)',(task['id'],0,json.dumps(task,ensure_ascii=False)))
    return task

@app.post('/api/tasks/{task_id}/sharing-version',dependencies=[Depends(auth)])
def sharing_version(task_id:str,body:Revision):
    return tone_version(task_id,ToneVersion(revision=body.revision,writing_style='friend-sharing'))


@app.post('/api/tasks/{task_id}/tone-version',dependencies=[Depends(auth)])
def tone_version(task_id:str,body:ToneVersion):
    if body.writing_style not in tones.BY_ID:raise HTTPException(422,'语气类别不存在')
    original=current(task_id,body.revision)
    if not original.get('case'):raise HTTPException(409,'请先选定参考案例')
    manifest=cases.load(BUNDLES,original['request']['bundle_id'])
    # New editable version: no mutation of the original draft, renders or approvals.
    task={key:json.loads(json.dumps(original[key])) for key in
          ('schema_version','request','case','selection','intent','intent_understanding','research') if key in original}
    task['request'].update(workflow='expression-first',writing_style=body.writing_style)
    task.update(id=uuid4().hex,revision=0,parent_task_id=original['id'],stage='candidate',
        analysis=None,confirmed_analysis=None,draft=None,assets={},renders={},page_reviews={},page_index=0,
        traces=[],failures=[],feedback=[],history=[],analysis_stages={},analysis_decisions=[],
        writing_style=writing_style.profile(DATA,manifest,body.writing_style),updated_at=datetime.now(timezone.utc).isoformat())
    runlog.event(task,DATA,'创建语气新版本：'+tones.BY_ID[body.writing_style]['title'],{'说明':['保留原任务与成图，从固定目的按所选语气重新提炼表达'],
        '原任务':[original['id']]})
    with db() as conn:conn.execute('INSERT INTO tasks VALUES (?,?,?)',(task['id'],0,json.dumps(task,ensure_ascii=False)))
    return task


@app.get('/api/tasks/{task_id}',dependencies=[Depends(auth)])
def read(task_id:str):return get_task(task_id)

@app.delete('/api/tasks/{task_id}',dependencies=[Depends(auth)])
def delete_task(task_id:str,revision:int):
    """删除任务连同其照片、成品图、底图文件。要求 revision 匹配，防止误删别处刚更新过的任务。"""
    task=get_task(task_id)
    if task['revision']!=revision:raise HTTPException(409,'任务已变化，请刷新后重试')
    with db() as conn:
        cursor=conn.execute('DELETE FROM tasks WHERE id=? AND revision=?',(task_id,revision))
        if cursor.rowcount!=1:raise HTTPException(409,'任务已变化，请刷新后重试')
    for sub in ('assets','cards','backgrounds'):
        shutil.rmtree(DATA/sub/task_id,ignore_errors=True)
    return {'deleted':task_id}

@app.get('/api/tasks/{task_id}/reference/{number}',dependencies=[Depends(auth)])
def reference(task_id:str,number:int):
    task=get_task(task_id,True)
    if not task.get('case'):raise HTTPException(404,'没有选定案例')
    try:raw=cases.image_bytes(BUNDLES,task['request']['bundle_id'],task['case']['id'],number)
    except (ValueError,StopIteration,KeyError,FileNotFoundError):raise HTTPException(404,'原图缺失，请重新导入完整资料') from None
    with Image.open(io.BytesIO(raw)) as im:mime=Image.MIME.get(im.format,'image/png')
    return Response(raw,media_type=mime)

def _norm_text(s):
    """引文比对用的归一化：去空白与常见中英文标点，转小写。"""
    import re as _re
    return _re.sub(r'[\s，。；：、！？“”‘’（）《》【】·…\-\.,;:!?\(\)\[\]"\']+', '', (s or '')).lower()


def clean_ocr_quotes(output,task):
    """视觉模型的引文来自看图，可能与带识别噪声的库内OCR不逐字一致。
    归一化后仍不一致的引文清空（留待人工核对），不再一票否决整份分析。"""
    pages=task['case']['pages']
    for p in output.original_pages:
        if not p.ocr_quote:continue
        original=next(x for x in pages if x['number']==p.number)
        if p.ocr_quote not in original['ocr'] and _norm_text(p.ocr_quote) not in _norm_text(original['ocr']):
            p.ocr_quote=''


def validate_analysis(output,task):
    pages=task['case']['pages'];valid={p['number'] for p in pages}
    if [p.number for p in output.original_pages]!=[p['number'] for p in pages]:
        raise HTTPException(422,'拆解必须按原图顺序逐页对应，不能增删原帖页码')
    for p in output.original_pages:
        original=next(x for x in pages if x['number']==p.number)
        if p.ocr_quote and p.ocr_quote not in original['ocr'] and _norm_text(p.ocr_quote) not in _norm_text(original['ocr']):
            raise HTTPException(422,'OCR引文与原页不一致，请核对后重试')
    if any(not set(p.source_pages)<=valid for p in output.outline):
        raise HTTPException(422,'新页引用了不存在的原帖页码')

def _norm_purpose(s):
    """近重复页识别用的归一化：去掉"继续/补充/更多"这类接续词。"""
    return re.sub(r'^(继续|补充|进一步|更多|额外|又|再)', '', (s or '').strip())


def polish_analysis(task, result, pages_count, feedback=''):
    """Remove placeholders/duplicate questions without compressing to source length."""
    notes = []
    keep = []
    for o in result.outline:
        echo = '根据参考图填写' in (o.purpose + o.instruction) or '示例' in o.purpose[:4]
        if echo:
            notes.append(f'已删除占位页：{o.purpose[:16]}')
            continue
        a = _norm_purpose(o.reader_question or o.purpose)
        dup = False
        for k in keep:
            b = _norm_purpose(k.reader_question or k.purpose)
            if o.kind == k.kind and (a == b or (len(a) >= 4 and a in b) or (len(b) >= 4 and b in a)):
                dup = True
                break
        if dup:
            notes.append(f'已删除重复页：{o.purpose[:16]}')
            continue
        keep.append(o)
    if not keep:
        keep = result.outline[:1]
    if len(keep) != len(result.outline):
        result.outline = keep
    return result, notes


_VISION_BREAKER = {'fails': 0}   # 视觉轨熔断器：连续失败计数（跨任务，服务进程内）
VISION_BREAKER_THRESHOLD = 3     # 连续失败达到该次数后跳过视觉轨，直接文字轨


def analyze_via_llm(task, instruction, pages):
    """拆解调用统一入口：视觉轨优先；视觉失败自动降级文字轨重试一次（有限降级，不循环）。
    熔断器：视觉轨连续失败 VISION_BREAKER_THRESHOLD 次后，后续拆解直接走文字轨
    （真机场景：glm-4.5v 批量 10/10 失败时，每次重试都要空等数分钟的失败链）；
    用户在第3步退回重做（明确要求再试）或某次视觉调用成功时复位。
    返回 (Analysis, 视觉是否成功)。失败详情已由 invoke 记入 task['failures'] 与 traces。"""
    breaker_open = _VISION_BREAKER['fails'] >= VISION_BREAKER_THRESHOLD
    if llm.supports_vision() and len(pages) <= MAX_VISION_PAGES and not breaker_open:
        images = [{'number': p['number'],
                   'data': cases.image_bytes(BUNDLES, task['request']['bundle_id'], task['case']['id'], p['number'])}
                  for p in pages]
        try:
            result = invoke(task, AnalysisCompact, instruction, images=images, outline_anchor=len(pages))
            _VISION_BREAKER['fails'] = 0
            return (result.to_analysis() if isinstance(result, AnalysisCompact) else result), True
        except HTTPException:
            _VISION_BREAKER['fails'] += 1  # 已记录失败；降级文字轨按 OCR+正文重试一次
    text_instruction = {**instruction, 'visual_input': False,
                        'visual_rule': '本次没有看图结果，仅依据OCR和正文；不得判断配色、构图或画面元素。'}
    result = invoke(task, Analysis, text_instruction, outline_anchor=len(pages))
    return result, False


@app.post('/api/tasks/{task_id}/expression-study',dependencies=[Depends(auth)])
def expression_study(task_id:str,body:Revision,feedback:str=''):
    task=current(task_id,body.revision)
    if not expression.enabled(task):raise HTTPException(409,'已有任务保留原流程，请新建任务使用表达优先流程')
    if task.get('draft'):raise HTTPException(409,'已有草稿保留，请新建任务调整表达方案')
    if task.get('expression',{}).get('status')=='accepted' and not feedback.strip():
        raise HTTPException(409,'表达方案已确认；如需重做，请明确填写修改意见')
    if not task.get('case'):raise HTTPException(409,'请先选定相关参考')
    images=[]
    if llm.supports_vision():
        for p in task['case']['pages'][:2]:
            if p.get('image'):
                images.append({'number':p['number'],'role':'主参考原帖第'+str(p['number'])+'页',
                    'data':cases.image_bytes(BUNDLES,task['request']['bundle_id'],task['case']['id'],p['number'])})
    try:expression.study(task,invoke,feedback,images or None)
    except ValueError as exc:raise HTTPException(422,str(exc)) from None
    runlog.event(task,DATA,'同类表达分析',{'输出':['已提炼开头、结构、语气、句式与可复用提示词'],
        '说明':['此阶段未检索医学资料，等待用户确认表达方案']})
    return save(task,task['revision'])


@app.post('/api/tasks/{task_id}/confirm-expression',dependencies=[Depends(auth)])
def confirm_expression(task_id:str,body:ExpressionConfirm):
    task=current(task_id,body.revision)
    if not expression.enabled(task) or not task.get('expression'):raise HTTPException(409,'请先完成同类表达分析')
    if task.get('draft'):raise HTTPException(409,'已有草稿不能替换表达方案')
    try:expression.accept(task,body.prompt,DATA)
    except ValueError as exc:raise HTTPException(409,str(exc)) from None
    runlog.event(task,DATA,'确认表达方案',{'输出':['目的、叙述方式和语气已保存，后续资料用于补充知识']})
    return save(task,body.revision)


@app.get('/api/tasks/{task_id}/expression-skill',dependencies=[Depends(auth)])
def expression_skill(task_id:str):
    task=get_task(task_id)
    if task.get('expression',{}).get('status')!='accepted':raise HTTPException(409,'请先确认表达方案')
    return Response(task['expression']['prompt'],media_type='text/markdown',
        headers={'Content-Disposition':'attachment; filename="SKILL.md"'})


@app.post('/api/tasks/{task_id}/prepare-content',dependencies=[Depends(auth)])
def prepare_content(task_id:str,body:Revision):
    task=current(task_id,body.revision)
    if not expression.enabled(task) or task.get('expression',{}).get('status')!='accepted':
        raise HTTPException(409,'先确认表达方案，再检索资料')
    if task.get('draft') or task.get('confirmed_analysis'):raise HTTPException(409,'已确认大纲保留，请新建任务改变方向')
    try:
        observed=expression.materialize(task,invoke,sources_for(task))
        result=editorial.plan_outline(task,observed,invoke)
        validate_analysis(result,task)
    except ValueError as exc:raise HTTPException(422,str(exc)) from None
    task.update(analysis=result.model_dump(),stage='outline_review',analysis_basis='已确认表达方案 + 本篇资料单')
    runlog.event(task,DATA,'按表达方案检索资料并规划大纲',{'输出':[f'资料知识点{len(task["material_sheet"]["items"])}项，大纲{len(result.outline)}页']})
    return save(task,task['revision'])


@app.post('/api/tasks/{task_id}/analyze',dependencies=[Depends(auth)])
def analyze(task_id:str,body:Revision):
    if expression.enabled(get_task(task_id)):
        return expression_study(task_id,body)
    task=current(task_id,body.revision)
    if not task['case']:raise HTTPException(409,'没有相关案例，请调整主题或导入资料')
    if task['confirmed_analysis']:raise HTTPException(409,'已确认的拆解保留；需要新方向请新建任务')
    pages=task['case']['pages']
    if any(not p.get('image') for p in pages):raise HTTPException(409,'参考案例缺少原图，先补齐资料包，不猜测画面')
    if not any(p['ocr'].strip() for p in pages) and not task['case']['body'].strip() and not llm.supports_vision():
        raise HTTPException(409,'原帖缺少可分析文字，请补充OCR或正文')
    planned=llm.supports_vision() and len(pages)<=MAX_VISION_PAGES
    editorial.prepare(task,invoke)
    runlog.event(task,DATA,'确定受众与内容方向',{'输出':[
        task['editorial_plan']['audience_brief']['reader'],task['editorial_plan']['direction'],
        task['editorial_plan']['reading_goal']]})
    result,vision_ok=analyze_via_llm(task,{'action':prompts.analyze_instruction(len(pages),task.get('intent',{}).get('page_count',0)),
        'request':task['request'],'visual_input':planned},pages)
    clean_ocr_quotes(result,task)
    validate_analysis(result,task)
    try:result=editorial.plan_outline(task,result,invoke)
    except ValueError as exc:raise HTTPException(422,str(exc)) from None
    result,notes=polish_analysis(task,result,len(pages))
    runlog.event(task,DATA,'按读者问题与阅读负担分页',{'输出':[
        task['editorial_outline']['pagination_reason']]+[
        f'第{i+1}页：{p.reader_question}；{len(p.key_points)}个要点；{len(p.new_terms)}个新术语'
        for i,p in enumerate(result.outline)]})
    stages={name:{'status':'ready'} for name in ANALYSIS_STAGES}
    if task.get('analysis_stages',{}).get('retrieval',{}).get('status')=='accepted':
        stages['retrieval']={'status':'accepted'}
    if vision_ok:
        basis='原图+OCR+正文'
    elif llm.supports_vision() and len(pages)<=MAX_VISION_PAGES:
        if _VISION_BREAKER['fails']>=VISION_BREAKER_THRESHOLD:
            basis=(f'视觉轨连续{_VISION_BREAKER["fails"]}次失败已熔断，本次直接按OCR+正文拆解（更快）；'
                   '退回任一步重做会解除熔断、再给视觉轨一次机会')
        else:
            basis='视觉轨未完成（失败详情已记录），已自动降级按OCR+正文拆解；可退回重做让视觉轨再试'
    elif len(pages)>MAX_VISION_PAGES:
        basis=f'OCR+正文；原帖共{len(pages)}页，超出视觉模型单次看图上限（{MAX_VISION_PAGES}页），未做视觉解析，可对照下方原图自行核对'
    else:
        basis='OCR+正文；原图展示给用户核对，未进行模型视觉解析'
    task.update(analysis=result.model_dump(),stage='analysis_review',analysis_basis=basis,
                analysis_stages=stages,analysis_polish=notes)
    runlog.event(task,DATA,'拆解（'+('视觉轨' if vision_ok else '文字轨或降级')+'）',{
        '依据':[basis],
        '调用':[runlog.trace_summary(tr) for tr in task['traces'][-3:]],
        '输出':[f'摘要：{result.summary[:80]}']
               +[f'原帖第{p.number}页：{p.form}｜{p.observation[:36]}' for p in result.original_pages[:8]]
               +[f'大纲第{i+1}页：{o.kind}｜{o.purpose[:26]}（借鉴{o.source_pages}）' for i,o in enumerate(result.outline)]
               +(notes or [])})
    return save(task,task['revision'])

@app.post('/api/tasks/{task_id}/analysis-stage',dependencies=[Depends(auth)])
def analysis_stage(task_id:str,body:AnalysisStageDecision):
    task=current(task_id,body.revision)
    if expression.enabled(task):raise HTTPException(409,'新流程已合并重复确认，请使用表达方案和大纲确认')
    if not task.get('case'):raise HTTPException(409,'没有相关案例，不能确认检索步骤')
    if task.get('confirmed_analysis'):raise HTTPException(409,'拆解已经确认，请新建任务重新选择')
    stages=task.setdefault('analysis_stages',{name:{'status':'blocked'} for name in ANALYSIS_STAGES})
    decisions=task.setdefault('analysis_decisions',[])
    stage=body.stage
    position=ANALYSIS_STAGES.index(stage)
    previous=ANALYSIS_STAGES[:position]
    if any(stages.get(name,{}).get('status')!='accepted' for name in previous):
        raise HTTPException(409,'请先确认前一个步骤')
    if body.decision=='reject' and not body.feedback.strip():
        raise HTTPException(422,'拒绝当前结果时必须填写修改建议')
    if body.decision=='reject':
        _VISION_BREAKER['fails']=0  # 用户明确要求重做：解除视觉轨熔断，再给一次机会
    if stage=='retrieval':
        stages[stage]={'status':'accepted' if body.decision=='accept' else 'rejected','feedback':body.feedback}
        decisions.append({'stage':stage,'decision':body.decision,'feedback':body.feedback,'time':datetime.now(timezone.utc).isoformat()})
        if body.decision=='reject':task['stage']='candidate'
        runlog.event(task,DATA,f'第1步检索·{"采用" if body.decision=="accept" else "退回"}',{
            '用户输入':[('修改建议：'+body.feedback) if body.feedback.strip() else '（无文字建议）'],
            '说明':['退回会保留旧任务，并按建议重新检索创建新任务'] if body.decision=='reject' else ['检索结果已确认']})
        return save(task,body.revision)
    if not task.get('analysis'):
        raise HTTPException(409,'请先完成模型拆解，再确认分析步骤')
    if body.decision=='accept':
        stages[stage]={'status':'accepted','feedback':body.feedback}
        decisions.append({'stage':stage,'decision':'accept','feedback':body.feedback,'time':datetime.now(timezone.utc).isoformat()})
        runlog.event(task,DATA,f'{STAGE_LABELS_ZH.get(stage,stage)}·采用',{
            '用户输入':[('补充说明：'+body.feedback) if body.feedback.strip() else '（无补充）'],
            '说明':['该步结果已确认，解锁下一步']})
        return save(task,body.revision)
    if stage=='writing':editorial.prepare(task,invoke,feedback=body.feedback)
    result,vision_ok=analyze_via_llm(task,{
        'action':prompts.STAGE_RERUN.format(stage=stage,feedback=body.feedback),
        'previous_analysis':task['analysis'],
        'request':task['request'],
        'reference_pages':len(task['case']['pages']),
        'rules':'保留未被要求修改的部分；original_pages必须逐页对应原图，OCR引文逐字来自原页；不能新增未经资料支持的医学事实。新页按读者问题和阅读负担规划，不按原帖页数压缩。'},
        task['case']['pages'])
    clean_ocr_quotes(result,task)
    validate_analysis(result,task)
    if not task.get('editorial_plan'):editorial.prepare(task,invoke)
    try:result=editorial.plan_outline(task,result,lambda t,s,i:invoke(t,s,{**i,'feedback':body.feedback,'previous_outline':task['analysis']['outline']}))
    except ValueError as exc:raise HTTPException(422,str(exc)) from None
    result,notes=polish_analysis(task,result,len(task['case']['pages']),body.feedback)
    task.update(analysis=result.model_dump(),analysis_polish=notes,
                analysis_basis='原图+OCR+正文' if vision_ok else '本次未完成看图分析，当前为 OCR+正文结果；可点击“用原图重新分析”重试')
    for name in ANALYSIS_STAGES[position:]:stages[name]={'status':'ready'}
    stages[stage]['feedback']=body.feedback
    decisions.append({'stage':stage,'decision':'reject','feedback':body.feedback,'time':datetime.now(timezone.utc).isoformat()})
    task['stage']='analysis_review'
    runlog.event(task,DATA,f'{STAGE_LABELS_ZH.get(stage,stage)}·退回并重做',{
        '用户输入':[f'修改建议：{body.feedback}'],
        '调用':[runlog.trace_summary(tr) for tr in task['traces'][-2:]],
        '输出':[f'摘要：{result.summary[:60]}']
               +[f'大纲第{i+1}页：{o.kind}｜{o.purpose[:26]}' for i,o in enumerate(result.outline)]
               +(notes or [])})
    return save(task,task['revision'])

@app.post('/api/tasks/{task_id}/confirm-analysis',dependencies=[Depends(auth)])
def confirm_analysis(task_id:str,body:AnalysisConfirmation):
    task=current(task_id,body.revision)
    if expression.enabled(task) and (task.get('expression',{}).get('status')!='accepted' or not task.get('material_sheet')):
        raise HTTPException(409,'请先确认表达方案并准备本篇资料单')
    if not task['analysis'] or task['confirmed_analysis']:raise HTTPException(409,'请先完成拆解；已确认任务不能覆盖原决定')
    validate_analysis(body.analysis,task)
    task.update(confirmed_analysis=body.analysis.model_dump(),stage='ready_to_write',
                analysis_stages={name:{'status':'accepted'} for name in ANALYSIS_STAGES})
    runlog.event(task,DATA,'确认拆解（进入草稿）',{
        '输出':[f'大纲共{len(body.analysis.outline)}页：']
               +[f'第{i+1}页：{o.kind}｜{o.purpose[:26]}（借鉴{o.source_pages}）' for i,o in enumerate(body.analysis.outline)]})
    return save(task,body.revision)

@app.post('/api/tasks/{task_id}/draft',dependencies=[Depends(auth)])
def draft(task_id:str,body:Revision):
    task=current(task_id,body.revision)
    if not task['confirmed_analysis']:raise HTTPException(409,'请先确认原帖拆解和新内容大纲')
    editorial.prepare(task,invoke)
    outline=task['confirmed_analysis']['outline']
    expected=list(range(1,len(outline)+1))
    # 真机基线（evals/reports/baseline）：2/10 题草稿页数与大纲不一致直接 502。
    # 修复：带错误反馈自动重试一次（有限重试，不循环），重试仍失败才报错。
    writing_action=expression.WRITE if expression.enabled(task) else prompts.DRAFT
    result=None
    retry_note=None
    for attempt in (1, 2):
        action=writing_action
        if attempt == 2:
            action += (' ⚠ 系统提示：你上一次生成的 pages 数量与 outline 不一致被退回。'
                       f'必须恰好 {len(outline)} 页，number 从 1 开始连续编号，一页对应大纲一行，不要多也不要少。')
        result=invoke(task,Draft,{'action':action,
            'request':task['request'],'outline':outline})
        if [p.number for p in result.pages]==expected:
            break
        retry_note=f'第 {attempt} 次草稿页数不一致（{len(result.pages)}页/应{len(outline)}页），已自动重试'
    if [p.number for p in result.pages]!=expected:
        raise HTTPException(502,'生成页数与已确认大纲不一致（已自动重试一次仍未修复），请手动重试')
    valid={s['id'] for s in sources_for(task)}
    if any(not set(p.source_ids)<=valid for p in result.pages):raise HTTPException(502,'生成内容引用了不存在的来源')
    echo_notes=[]
    if retry_note:
        echo_notes.append(retry_note)
    for p in result.pages:
        cleaned,changed=_strip_title_echo(p.title,p.text)
        if changed:
            p.text=cleaned
            echo_notes.append(f'第{p.number}页正文开头复述了标题，已自动去除')
    result.audience_brief=EditorialPlan.model_validate(task['editorial_plan']).audience_brief
    candidate=result.model_dump()
    try:content_check=editorial.review(task,candidate,invoke)
    except ValueError as exc:raise HTTPException(422,str(exc)) from None
    if not content_check['passed']:
        revised=invoke(task,Draft,{'action':writing_action+' 按下面内容编辑意见修改这一次，保持确认的页数和问题顺序，不新增事实。',
            'request':task['request'],'outline':outline,'previous_draft':candidate,'content_feedback':content_check})
        if [p.number for p in revised.pages]==expected and all(set(p.source_ids)<=valid for p in revised.pages):
            revised.audience_brief=result.audience_brief
            for p in revised.pages:p.text=_strip_title_echo(p.title,p.text)[0]
            result=revised
            try:content_check=editorial.review(task,result.model_dump(),invoke)
            except ValueError as exc:raise HTTPException(422,str(exc)) from None
            echo_notes.append('已按内容检查意见修改一次；不继续自动循环')
    runlog.event(task,DATA,'草稿内容检查',{'输出':[content_check['summary']],
        '问题':editorial.issues_for(content_check),'说明':['通过后可设计成图' if content_check['passed'] else '先修改文字，再次生成时重新检查；未调用绘图模型']})
    if task['draft']:task['history'].append({'draft':task['draft'],'renders':task['renders'],'page_reviews':task['page_reviews']})
    task.update(draft=result.model_dump(),stage='making',renders={},page_reviews={},copy_review=None,page_index=0,
                generation_sources=sources_for(task))
    runlog.event(task,DATA,'生成逐页草稿',{
        '调用':[runlog.trace_summary(task['traces'][-1])],
        '输出':[f'标题：{result.title}']
               +[f'第{p.number}页：{p.title[:24]}（{"；".join(p.pending)[:40] or "无待核实"}）' for p in result.pages]
               +([f'整体待核实：{"；".join(result.missing_information)[:80]}'] if result.missing_information else [])
               +echo_notes})
    return save(task,body.revision)

def _norm_echo(s):
    """标题回声比对用的归一化：去空白与常见标点，转小写。"""
    return re.sub(r'[\s，。；：、！？“”‘’（）《》【】·…\-\.,;:!?"\'()]+', '', (s or '')).lower()


def _strip_title_echo(title, text):
    """草稿正文若以页面标题开头（模型写封面页的常见复述习惯，真机案例 20260926：
    标题由程序排版绘制，正文又复述一遍导致成品重复），去掉开头的标题部分。
    支持标题被拆成多行（如"第一次了解 M22"+"先弄清这几个问题"两行）。返回 (清理后文本, 是否清理)。"""
    t = _norm_echo(title)
    if not t or not (text or '').strip():
        return text, False
    lines = text.splitlines()
    matched = ''
    consumed = 0
    for line in lines:
        candidate = matched + line
        cn = _norm_echo(candidate)
        if cn and cn == t:
            return text[consumed + len(line) + 1:].lstrip('\n'), True
        if cn and t.startswith(cn):
            matched = candidate
            consumed += len(line) + 1
            continue
        break
    return text, False


def page_data(task,number):
    if not task.get('draft') or not 1<=number<=len(task['draft']['pages']):raise HTTPException(409,'请先生成有效的逐页草稿')
    return task['confirmed_analysis']['outline'][number-1],task['draft']['pages'][number-1]

@app.post('/api/tasks/{task_id}/pages/{number}/photo',dependencies=[Depends(auth)])
def upload(task_id:str,number:int,photo:UploadFile|None=File(None),caption:str=Form(...),revision:int=Form(...)):
    """上传实拍照片；已有照片时可不传文件、只更新照片说明。"""
    task=current(task_id,revision);outline,_=page_data(task,number)
    if outline['kind']!='photo':raise HTTPException(422,'文字卡无需上传照片')
    if not caption.strip() or len(caption)>2000:raise HTTPException(422,'请填写真实照片说明，最多2000字')
    if photo is None:
        if not task['assets'].get(str(number)):raise HTTPException(422,'请先选择一张照片')
        task['assets'][str(number)]['caption']=caption
        return save(task,revision)
    raw=photo.file.read(10*1024*1024+1)
    if len(raw)>10*1024*1024:raise HTTPException(413,'照片不能超过10MB')
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in {'JPEG','PNG','WEBP'} or im.width*im.height>16_000_000 or im.width<240:raise ValueError()
            im.load();width,height=im.size;fmt=im.format
    except (ValueError,OSError,Image.DecompressionBombError):raise HTTPException(422,'图片无效，支持JPEG/PNG/WebP，宽至少240像素、最多1600万像素') from None
    folder=DATA/'assets'/task_id;folder.mkdir(parents=True,exist_ok=True)
    filename=uuid4().hex+'.'+{'JPEG':'jpg','PNG':'png','WEBP':'webp'}[fmt]
    path=folder/filename;path.write_bytes(raw)
    task['assets'][str(number)]={'file':filename,'caption':caption,'width':width,'height':height,'sha256':hashlib.sha256(raw).hexdigest()}
    task['renders'].pop(str(number),None);task['page_reviews'].pop(str(number),None)
    task.update(stage='making',copy_review=None)
    runlog.event(task,DATA,f'第{number}页·上传实拍照片',{
        '用户输入':[f'照片说明：{caption[:80]}',f'尺寸：{width}x{height}'],
        '说明':['该页此前生成的成品图已作废，需重新确认生成']})
    try:return save(task,revision)
    except Exception:path.unlink(missing_ok=True);raise

@app.post('/api/tasks/{task_id}/pages/{number}',dependencies=[Depends(auth)])
def make_page(task_id:str,number:int,body:PageEdit):
    task=current(task_id,body.revision);outline,page=page_data(task,number)
    task.setdefault('render_preferences',{})[str(number)]={'generation_mode':body.generation_mode,'card_theme':body.card_theme,'mode_version':2}
    if not body.confirmed:
        page.update(title=body.title,text=body.text)
        task['draft_content_review']=None
        if task.get('content_review_candidate',{}).get('page')==number:task.pop('content_review_candidate',None)
        task['renders'].pop(str(number),None)
        task['page_reviews'][str(number)]={'confirmed':False,'resolution':body.resolution}
        task.update(copy_review=None,stage='making')
        runlog.event(task,DATA,f'第{number}页·保存文字草稿',{
            '用户输入':[f'标题：{body.title[:30]}','正文已修改（未确认生成）'],
            '说明':['该页此前生成的成品图已作废']})
        return save(task,body.revision)
    if page['pending'] and not body.resolution.strip():raise HTTPException(422,'本页有待核实内容，请说明已补充的依据，或删除了哪些未核实表述')
    candidate=json.loads(json.dumps(task['draft']))
    candidate['pages'][number-1].update(title=body.title,text=body.text)
    try:content_check=editorial.review(task,candidate,invoke)
    except ValueError as exc:raise HTTPException(422,str(exc)) from None
    if not content_check['passed']:
        task['content_review_candidate']={'page':number,'title':body.title,'text':body.text}
        runlog.event(task,DATA,f'第{number}页·内容检查需修改',{'问题':editorial.issues_for(content_check),
            '说明':['未调用绘图模型，原草稿和已生成图片保留']})
        save(task,body.revision)
        reasons=editorial.issues_for(content_check) or [content_check['summary']]
        raise HTTPException(422,'文字内容需要修改：'+'；'.join(reasons)[:500]+'。修改后再次生成会重新检查，原图已保留。')
    task.pop('content_review_candidate',None)
    raw=None
    if outline['kind']=='photo':
        asset=task['assets'].get(str(number))
        if not asset:raise HTTPException(409,'本页需要实拍，请先保存照片')
        raw=(DATA/'assets'/task_id/asset['file']).read_bytes()
    if outline['kind'] in ('text','chat') and not (body.title.strip() or body.text.strip()):
        raise HTTPException(422,'卡片不能空白')
    dialog=None
    if outline['kind']=='chat':
        dialog=rendering.parse_dialog(body.text)
        if not dialog and not body.text.strip():dialog=page.get('dialog',[])
        if len(dialog)<2:raise HTTPException(422,'对话卡每行一条“顾客：…”或“门店：…”，至少两轮')
    total=len(task['draft']['pages'])
    background_source=None
    bg_bytes=None
    audit_file=None
    try:
        if body.generation_mode in ('model','seedream'):
            references=[]
            for source_page in (outline.get('source_pages') or [1])[:2]:
                try:
                    data=cases.image_bytes(BUNDLES,task['request']['bundle_id'],task['case']['id'],source_page)
                    references.append({'data':data,'role':f'参考原帖第{source_page}页，仅借鉴视觉语言'})
                except (ValueError,StopIteration,KeyError,FileNotFoundError):
                    pass
            previous=None
            existing=task['renders'].get(str(number),{})
            if existing.get('design_audit_file'):
                old_audit=DATA/'designs'/task_id/existing['design_audit_file']
                if old_audit.exists():
                    previous=json.loads(old_audit.read_text(encoding='utf-8')).get('design')
            try:
                generator=seedream_card if body.generation_mode=='seedream' else model_card
                rendered,meta,audit=generator.generate(body.title,body.text,kind=outline['kind'],page=number,
                    total_pages=total,theme=body.card_theme,reference_images=references,photo=raw,
                    previous=previous,regenerate=body.regenerate_design,previous_image_sha256=existing.get('sha256'),
                    editorial_context={'plan':task['editorial_plan'],'page':outline,
                        'confirmed_expression':task.get('expression'),
                        'reference_structure':task.get('editorial_outline',{}).get('reference_takeaway',''),
                        'content_review_passed':content_check['passed']})
            except model_card.PipelineError as exc:
                text_check_failed=body.generation_mode=='seedream' and str(exc).startswith('成图检查未通过')
                folder=DATA/'designs'/task_id;folder.mkdir(parents=True,exist_ok=True)
                audit_file=f'failed_{number:02d}_{uuid4().hex}.json'
                if getattr(exc,'preview_png',None):
                    candidate=Path(audit_file).with_suffix('.png').name
                    (folder/candidate).write_bytes(exc.preview_png)
                    exc.audit['unchecked_candidate_file']=candidate
                (folder/audit_file).write_text(json.dumps(exc.audit,ensure_ascii=False,indent=2),encoding='utf-8')
                task.setdefault('generation_attempts',[]).append({'page':number,'status':'failed','mode':body.generation_mode,
                    'message':str(exc)[:500],'audit_file':audit_file,'time':datetime.now(timezone.utc).isoformat()})
                task['generation_attempts']=task['generation_attempts'][-20:]
                task.setdefault('failures',[]).append({'action':'model_card','error_type':type(exc.__cause__).__name__,
                    'detail':str(exc)[:500],'time':datetime.now(timezone.utc).isoformat()})
                runlog.event(task,DATA,f'第{number}页·AI设计或检查未完成',{'错误':[str(exc)[:500]],
                    '说明':['本次未替换原有成品，可点击重新生成重试；不会用固定模板冒充AI设计']})
                save(task,body.revision)
                if text_check_failed:
                    reason=str(exc).removeprefix('成图检查未通过：')[:150]
                    raise HTTPException(502,'Seedream 成图检查未通过：'+reason+'。旧图和 Seedream 选择已保留，可重新生成；也可手动选择 AI 视觉排版。') from None
                readable=model_card.public_error(str(exc))
                if readable:raise HTTPException(502,readable) from None
                raise HTTPException(502,'AI设计/成图检查未完成：'+str(exc)[:400]+'。本次未替换原图，可点击重新生成重试。') from None
            folder=DATA/'designs'/task_id;folder.mkdir(parents=True,exist_ok=True)
            audit_file=f'{number:02d}_{uuid4().hex}.json'
            (folder/audit_file).write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
            meta['design_audit_file']=audit_file
            task.setdefault('generation_attempts',[]).append({'page':number,'status':'passed','mode':body.generation_mode,
                'audit_file':audit_file,'time':datetime.now(timezone.utc).isoformat()})
            task['generation_attempts']=task['generation_attempts'][-20:]
        elif outline['kind']=='chat':
            # 对话卡：每行"顾客：…"或"门店：…"，程序绘制微信聊天样式；无需底图
            dialog=rendering.parse_dialog(body.text)
            if not dialog and not (body.text or '').strip():
                # 文本为空时才沿用模型生成的对话轮次；填了文本但格式不对会被下面拦下
                dialog=[{'speaker':t['speaker'],'text':t['text']} for t in page.get('dialog',[])]
            if len(dialog)<2:
                raise HTTPException(422,'对话卡每行一条"顾客：…"或"门店：…"，至少两轮')
            rendered,meta=rendering.render_chat(body.title,dialog,page=number,total_pages=total)
        else:
            # 文字卡底图：仅当用户选择"AI 底图"样式时才调用画图轨；
            # 默认走程序版式（简约留白/柔和卡片/双色几何），生成失败自动降级纯色底，不阻断流程
            background_source=None
            if outline['kind']=='text' and body.card_theme=='ai':
                task.setdefault('backgrounds',{})
                entry=task['backgrounds'].get(str(number))
                regenerated=False
                if body.regenerate_background or not entry:
                    spec=outline.get('visual_spec','')
                    bg_prompt=prompts.BACKGROUND.format(spec=spec or prompts.BACKGROUND_DEFAULT_SPEC)
                    try:
                        data=llm.generate_background(bg_prompt)
                        folder=DATA/'backgrounds'/task_id;folder.mkdir(parents=True,exist_ok=True)
                        filename=f'{number:02d}_{uuid4().hex[:8]}.img'
                        (folder/filename).write_bytes(data)
                        entry={'file':filename,'spec':spec,'generated_at':datetime.now(timezone.utc).isoformat()}
                        task['backgrounds'][str(number)]=entry
                        regenerated=True
                    except Exception as exc:
                        task.setdefault('failures',[]).append({'action':'generate_background','error_type':type(exc).__name__,
                                                               'detail':str(exc)[:300],
                                                               'time':datetime.now(timezone.utc).isoformat()})
                if entry:
                    bg_path=DATA/'backgrounds'/task_id/entry['file']
                    if bg_path.exists():
                        bg_bytes=bg_path.read_bytes()
                        background_source='ai_new' if regenerated else ('ai_stale' if body.regenerate_background else 'ai_reused')
                if bg_bytes is None:
                    background_source='plain'
            rendered,meta=rendering.render(body.title,body.text,raw,background=bg_bytes,
                                           page=number,total_pages=total,
                                           theme=None if outline['kind']!='text' or body.card_theme in ('ai','plain') else body.card_theme)
    except HTTPException:raise
    except ValueError as exc:raise HTTPException(422,str(exc)) from None
    folder=DATA/'cards'/task_id;folder.mkdir(parents=True,exist_ok=True)
    filename=f'{number:02d}_{uuid4().hex}.png';path=folder/filename;path.write_bytes(rendered)
    meta['generated_at']=datetime.now(timezone.utc).isoformat()
    page.update(title=body.title,text=body.text)
    if outline['kind']=='chat':
        page['dialog']=[{'speaker':t['speaker'],'text':t['text']} for t in dialog]
    task['renders'][str(number)]={'file':filename,'sha256':hashlib.sha256(rendered).hexdigest(),
                                  'background_source':background_source,
                                  'theme':body.card_theme if outline['kind']=='text' else None,'generation_mode':body.generation_mode,**meta}
    task['page_reviews'][str(number)]={'confirmed':True,'resolution':body.resolution,'pending_at_review':page['pending'],
                                      'time':datetime.now(timezone.utc).isoformat()}
    task.update(stage='making',copy_review=None)
    runlog.event(task,DATA,f'第{number}页·{"确认并生成成品" if body.confirmed else "保存文字草稿"}',{
        '用户输入':[f'标题：{body.title[:30]}',
                (f'待核实处理：{body.resolution[:80]}') if body.resolution.strip() else '（无待核实说明）']
               +([f'样式：{body.card_theme}；重新生成底图'] if body.regenerate_background else []),
        '输出':[f'生成方式：{body.generation_mode}；渲染方式：{meta.get("method")}'+(f'；底图来源：{background_source}' if background_source else ''),
                f'成品：{meta.get("width")}x{meta.get("height")} PNG（{len(rendered)//1024}KB）']
               +([f'制作提示单独保留，未写入图片：{len(meta["production_notes"])}段'] if meta.get('production_notes') else [])
               +([f'⚠ 底图生成失败已记录（共{len(task.get("failures", []))}条失败记录）'] if any(f['action']=='generate_background' for f in task.get('failures',[])[-1:]) else [])})
    try:return save(task,body.revision)
    except Exception:path.unlink(missing_ok=True);raise

@app.get('/api/tasks/{task_id}/pages/{number}/{kind}',dependencies=[Depends(auth)])
def page_image(task_id:str,number:int,kind:str):
    task=get_task(task_id,True)
    if kind not in {'photo','render'}:raise HTTPException(404,'图片类型不存在')
    entry=(task['assets'] if kind=='photo' else task['renders']).get(str(number))
    if not entry:raise HTTPException(404,'尚未保存图片')
    return FileResponse(DATA/('assets' if kind=='photo' else 'cards')/task_id/entry['file'])

@app.post('/api/tasks/{task_id}/progress',dependencies=[Depends(auth)])
def progress(task_id:str,body:Progress):
    task=current(task_id,body.revision);page_data(task,body.page_index+1)
    task['page_index']=body.page_index
    task['stage']='making'
    return save(task,body.revision)


@app.get('/api/tasks/{task_id}/assets/{asset_id}',dependencies=[Depends(auth)])
def legacy_asset(task_id:str,asset_id:str):
    task=get_task(task_id)
    if task.get('schema_version')==2 or not any(a.get('id')==asset_id for a in task.get('assets',[])):
        raise HTTPException(404,'历史照片不存在')
    return FileResponse(DATA/'assets'/task_id/f'{asset_id}.jpg')

@app.post('/api/tasks/{task_id}/copy',dependencies=[Depends(auth)])
def copy_review(task_id:str,body:CopyEdit):
    task=current(task_id,body.revision)
    if not task['draft']:raise HTTPException(409,'请先生成草稿')
    if len(task['renders'])!=len(task['draft']['pages']):raise HTTPException(409,'请先完成每一页图片')
    if not body.confirmed:raise HTTPException(422,'请核对标题正文再确认')
    if task['draft']['missing_information'] and not body.resolution.strip():raise HTTPException(422,'请说明待核实信息如何处理，不能直接混入正文')
    task['draft'].update(title=body.title,body=body.body)
    task.update(copy_review={'confirmed':True,'resolution':body.resolution,'time':datetime.now(timezone.utc).isoformat()},stage='ready_to_export')
    _inputs=[f'标题：{body.title[:40]}']
    if task['draft'].get('missing_information'):
        _inputs.append(f'待核实处理：{body.resolution[:80]}' if body.resolution.strip() else '⚠ 有待核实项但未填写处理说明')
    runlog.event(task,DATA,'确认标题正文（进入导出）',{
        '用户输入':_inputs,'结果':['全部页面已确认，可导出 ZIP']})
    return save(task,body.revision)

@app.get('/api/tasks/{task_id}/export',dependencies=[Depends(auth)])
def export(task_id:str):
    task=get_task(task_id,True)
    if not task.get('copy_review') or not task['copy_review']['confirmed']:raise HTTPException(409,'请先完成图片并确认标题正文')
    images=[]
    for number in range(1,len(task['draft']['pages'])+1):
        entry=task['renders'].get(str(number))
        if not entry or not task['page_reviews'].get(str(number),{}).get('confirmed'):raise HTTPException(409,'还有未确认页面')
        path=DATA/'cards'/task_id/entry['file']
        if not path.exists():raise HTTPException(409,'成品图片缺失，请重新制作该页')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise HTTPException(409,'成品图片已改变，请重新确认')
        images.append(raw)
    export_result=rendering.export_zip(task,images)
    runlog.event(task,DATA,'导出图文包',{
        '结果':[f'ZIP {len(export_result)//1024}KB；{len(images)} 张成品图 + 标题正文 + 来源记录 + 待核实记录'],
        '说明':['任务完成；发布由用户本人操作，本工具不代发']})
    return Response(export_result,media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="post_{task_id}.zip"'})

@app.post('/api/tasks/{task_id}/feedback',dependencies=[Depends(auth)])
def feedback(task_id:str,body:FeedbackInput):
    task=get_task(task_id,True)
    if not task['draft']:raise HTTPException(409,'请先完成草稿')
    result=invoke(task,FeedbackAnalysis,{'action':prompts.FEEDBACK,
                 'notice':body.notice,'posted_text':body.posted_text or task['draft']['body']})
    if any(q not in body.notice for q in result.platform_quotes):raise HTTPException(502,'平台引文不一致，请重试')
    task['feedback'].append({'input':body.model_dump(),'analysis':result.model_dump(),'status':'待人工复核，不自动更新规则'})
    runlog.event(task,DATA,'记录发布反馈',{
        '用户输入':[f'平台原文：{body.notice[:120]}'],
        '输出':[f'平台引文 {len(result.platform_quotes)} 条；假设 {len(result.hypotheses)} 条；下一步 {len(result.next_actions)} 条'],
        '说明':['分析结果待人工复核，不自动更新任何规则']})
    return save(task,task['revision'])
