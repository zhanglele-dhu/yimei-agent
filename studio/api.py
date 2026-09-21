import hashlib
import hmac
import io
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

from . import cases, llm, rendering
from .models import (CreateTask, Revision, Analysis, AnalysisConfirmation, Draft, PageEdit,
                     CopyEdit, Progress, FeedbackInput, FeedbackAnalysis, AnalysisStageDecision)

ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env',override=False)
DATA=Path(os.getenv('STUDIO_DATA_DIR',str(ROOT/'outputs/studio'))).resolve()
DATA.mkdir(parents=True,exist_ok=True)
BUNDLES=DATA/'bundles'
TOKEN=os.getenv('STUDIO_ACCESS_TOKEN','')
VERSION='cases-20260920-1'
ANALYSIS_STAGES=('retrieval','language','visual','facts','writing')
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
    if not hmac.compare_digest(authorization,'Bearer '+TOKEN):raise HTTPException(401,'请连接工作台')

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

def sources_for(task):
    result=[{'id':'GUIDE','type':'人工确认的流程边界，非医学证据',
             'content':json.loads((ROOT/'knowledge/shooting_guide.json').read_text(encoding='utf-8-sig'))},
            {'id':'SHOP','type':'用户提供，未经独立核实','content':task['request']['facts']}]
    if 'm22' in task['request']['project'].lower():
        result.append({'id':'K1','type':'厂商资料摘要，非门店配置证明',
                       'content':(ROOT/'knowledge/procedures.md').read_text(encoding='utf-8-sig')})
    if task.get('case'):
        result.append({'id':'CASE','type':'参考笔记，仅借鉴结构，不作为医学事实证据','content':task['case']})
    return result

def invoke(task,schema,instruction,images=None):
    sources=sources_for(task)
    try:
        result,trace=llm.generate(schema,instruction,sources,images=images)
    except Exception as exc:
        task.setdefault('failures',[]).append({'action':schema.__name__,'error_type':type(exc).__name__,
                                               'time':datetime.now(timezone.utc).isoformat()})
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

@app.get('/api/tasks',dependencies=[Depends(auth)])
def list_tasks():
    with db() as conn:rows=conn.execute('SELECT body FROM tasks ORDER BY rowid DESC LIMIT 100').fetchall()
    return [{'id':(t:=json.loads(r[0]))['id'],'project':t['request']['project'],'question':t['request']['question'],
             'stage':t['stage'],'legacy':t.get('schema_version')!=2} for r in rows]

@app.post('/api/tasks',dependencies=[Depends(auth)])
def create(body: CreateTask):
    try:m=cases.load(BUNDLES,body.bundle_id)
    except (ValueError,FileNotFoundError):raise HTTPException(422,'请先导入并选择案例资料包') from None
    selected,selection=cases.select(m,body.project,body.question)
    task={'schema_version':2,'id':uuid4().hex,'revision':0,'request':body.model_dump(),
          'case':selected,'selection':selection,'stage':'candidate' if selected else 'no_match',
          'analysis':None,'confirmed_analysis':None,'draft':None,'assets':{},'renders':{},'page_reviews':{},
          'page_index':0,'traces':[],'failures':[],'feedback':[],'history':[],
          'analysis_stages':{name:{'status':'ready' if name=='retrieval' and selected else 'blocked'} for name in ANALYSIS_STAGES},
          'analysis_decisions':[]}
    with db() as conn:conn.execute('INSERT INTO tasks VALUES (?,?,?)',(task['id'],0,json.dumps(task,ensure_ascii=False)))
    return task

@app.get('/api/tasks/{task_id}',dependencies=[Depends(auth)])
def read(task_id:str):return get_task(task_id)

@app.get('/api/tasks/{task_id}/reference/{number}',dependencies=[Depends(auth)])
def reference(task_id:str,number:int):
    task=get_task(task_id,True)
    if not task.get('case'):raise HTTPException(404,'没有选定案例')
    try:raw=cases.image_bytes(BUNDLES,task['request']['bundle_id'],task['case']['id'],number)
    except (ValueError,StopIteration,KeyError,FileNotFoundError):raise HTTPException(404,'原图缺失，请重新导入完整资料') from None
    with Image.open(io.BytesIO(raw)) as im:mime=Image.MIME.get(im.format,'image/png')
    return Response(raw,media_type=mime)

def validate_analysis(output,task):
    pages=task['case']['pages'];valid={p['number'] for p in pages}
    if [p.number for p in output.original_pages]!=[p['number'] for p in pages]:
        raise HTTPException(422,'拆解必须按原图顺序逐页对应，不能增删原帖页码')
    for p in output.original_pages:
        original=next(x for x in pages if x['number']==p.number)
        if p.ocr_quote and p.ocr_quote not in original['ocr']:
            raise HTTPException(422,'OCR引文与原页不一致，请核对后重试')
    if any(not set(p.source_pages)<=valid for p in output.outline):
        raise HTTPException(422,'新页引用了不存在的原帖页码')

@app.post('/api/tasks/{task_id}/analyze',dependencies=[Depends(auth)])
def analyze(task_id:str,body:Revision):
    task=current(task_id,body.revision)
    if not task['case']:raise HTTPException(409,'没有相关案例，请调整主题或导入资料')
    if task['confirmed_analysis']:raise HTTPException(409,'已确认的拆解保留；需要新方向请新建任务')
    pages=task['case']['pages']
    if any(not p.get('image') for p in pages):raise HTTPException(409,'参考案例缺少原图，先补齐资料包，不猜测画面')
    if not any(p['ocr'].strip() for p in pages) and not task['case']['body'].strip():
        raise HTTPException(409,'原帖缺少可分析文字，请补充OCR或正文')
    images=[]
    # Only reference images, never user photos, may be sent for optional visual analysis.
    if llm.supports_vision():
        images=[{'number':p['number'],'data':cases.image_bytes(BUNDLES,task['request']['bundle_id'],task['case']['id'],p['number'])} for p in pages]
    result=invoke(task,Analysis,{'action':'逐页拆解原帖，区分原帖观察、可借鉴组织方式与新内容大纲。original_pages必须每原图一条，number按原序；ocr_quote逐字摘取本页OCR，缺字留空。无视觉输入时form注明仅按OCR推测，不能判断配色或布局。outline按帖子结构搭配页面类型：默认门店具备实拍条件，第一页优先文字卡作封面总领，中间按内容安排实拍页（instruction写清建议拍摄的对象与要点，供门店照着拍）或文字卡（清单、对比、说明），最后可安排引导页；避免所有页面同一类型。仅当资料明确说明无法拍摄时才全文字卡。每页附source_pages来源页码，不为凑图虚构必须实拍的画面。不给未经核实的医学答案，只列缺少哪些事实。',
        'request':task['request'],'visual_input':bool(images)},images=images)
    validate_analysis(result,task)
    stages={name:{'status':'ready'} for name in ANALYSIS_STAGES}
    if task.get('analysis_stages',{}).get('retrieval',{}).get('status')=='accepted':
        stages['retrieval']={'status':'accepted'}
    task.update(analysis=result.model_dump(),stage='analysis_review',analysis_basis='原图+OCR+正文' if images else 'OCR+正文；原图展示给用户核对，未进行模型视觉解析',
                analysis_stages=stages)
    return save(task,body.revision)

@app.post('/api/tasks/{task_id}/analysis-stage',dependencies=[Depends(auth)])
def analysis_stage(task_id:str,body:AnalysisStageDecision):
    task=current(task_id,body.revision)
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
    if stage=='retrieval':
        stages[stage]={'status':'accepted' if body.decision=='accept' else 'rejected','feedback':body.feedback}
        decisions.append({'stage':stage,'decision':body.decision,'feedback':body.feedback,'time':datetime.now(timezone.utc).isoformat()})
        if body.decision=='reject':task['stage']='candidate'
        return save(task,body.revision)
    if not task.get('analysis'):
        raise HTTPException(409,'请先完成模型拆解，再确认分析步骤')
    if body.decision=='accept':
        stages[stage]={'status':'accepted','feedback':body.feedback}
        decisions.append({'stage':stage,'decision':'accept','feedback':body.feedback,'time':datetime.now(timezone.utc).isoformat()})
        return save(task,body.revision)
    images=[]
    if stage=='visual' and llm.supports_vision():
        images=[{'number':p['number'],'data':cases.image_bytes(BUNDLES,task['request']['bundle_id'],task['case']['id'],p['number'])} for p in task['case']['pages']]
    result=invoke(task,Analysis,{
        'action':'只重做当前分析步骤，不改变用户任务。当前步骤：'+stage,
        'feedback':'用户拒绝上一版结果，修改建议：'+body.feedback,
        'previous_analysis':task['analysis'],
        'request':task['request'],
        'rules':'保留未被要求修改的部分；original_pages必须逐页对应原图，OCR引文逐字来自原页；不能新增未经资料支持的医学事实。'},
        images=images)
    validate_analysis(result,task)
    task['analysis']=result.model_dump()
    for name in ANALYSIS_STAGES[position:]:stages[name]={'status':'ready'}
    stages[stage]['feedback']=body.feedback
    decisions.append({'stage':stage,'decision':'reject','feedback':body.feedback,'time':datetime.now(timezone.utc).isoformat()})
    task['stage']='analysis_review'
    return save(task,body.revision)

@app.post('/api/tasks/{task_id}/confirm-analysis',dependencies=[Depends(auth)])
def confirm_analysis(task_id:str,body:AnalysisConfirmation):
    task=current(task_id,body.revision)
    if not task['analysis'] or task['confirmed_analysis']:raise HTTPException(409,'请先完成拆解；已确认任务不能覆盖原决定')
    validate_analysis(body.analysis,task)
    task.update(confirmed_analysis=body.analysis.model_dump(),stage='ready_to_write',
                analysis_stages={name:{'status':'accepted'} for name in ANALYSIS_STAGES})
    return save(task,body.revision)

@app.post('/api/tasks/{task_id}/draft',dependencies=[Depends(auth)])
def draft(task_id:str,body:Revision):
    task=current(task_id,body.revision)
    if not task['confirmed_analysis']:raise HTTPException(409,'请先确认原帖拆解和新内容大纲')
    result=invoke(task,Draft,{'action':'按照已确认outline逐页起草，pages数量顺序必须一致，number从1开始。文字卡不需要实拍。标题正文面向读者，不写分析报告，不插来源编号；source_ids单独记录。CASE只供结构借鉴，GUIDE只管流程，医学事实只能引用可靠资料，不能从竞品OCR抄医学答案。门店事实仅来自SHOP。缺少依据的内容不要出现在成品文字中，列入每页pending或missing_information。未知参数/价格/疗程不猜测。photo页只建议文字与拍摄内容，不声称看过照片。',
        'request':task['request'],'outline':task['confirmed_analysis']['outline']})
    if [p.number for p in result.pages]!=list(range(1,len(task['confirmed_analysis']['outline'])+1)):
        raise HTTPException(502,'生成页数与已确认大纲不一致，请手动重试')
    valid={s['id'] for s in sources_for(task)}
    if any(not set(p.source_ids)<=valid for p in result.pages):raise HTTPException(502,'生成内容引用了不存在的来源')
    if task['draft']:task['history'].append({'draft':task['draft'],'renders':task['renders'],'page_reviews':task['page_reviews']})
    task.update(draft=result.model_dump(),stage='making',renders={},page_reviews={},copy_review=None,page_index=0,
                generation_sources=sources_for(task))
    return save(task,body.revision)

def page_data(task,number):
    if not task.get('draft') or not 1<=number<=len(task['draft']['pages']):raise HTTPException(409,'请先生成有效的逐页草稿')
    return task['confirmed_analysis']['outline'][number-1],task['draft']['pages'][number-1]

@app.post('/api/tasks/{task_id}/pages/{number}/photo',dependencies=[Depends(auth)])
def upload(task_id:str,number:int,photo:UploadFile=File(...),caption:str=Form(...),revision:int=Form(...)):
    task=current(task_id,revision);outline,_=page_data(task,number)
    if outline['kind']!='photo':raise HTTPException(422,'文字卡无需上传照片')
    if not caption.strip() or len(caption)>2000:raise HTTPException(422,'请填写真实照片说明，最多2000字')
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
    try:return save(task,revision)
    except Exception:path.unlink(missing_ok=True);raise

@app.post('/api/tasks/{task_id}/pages/{number}',dependencies=[Depends(auth)])
def make_page(task_id:str,number:int,body:PageEdit):
    task=current(task_id,body.revision);outline,page=page_data(task,number)
    if not body.confirmed:
        page.update(title=body.title,text=body.text)
        task['renders'].pop(str(number),None)
        task['page_reviews'][str(number)]={'confirmed':False,'resolution':body.resolution}
        task.update(copy_review=None,stage='making')
        return save(task,body.revision)
    if page['pending'] and not body.resolution.strip():raise HTTPException(422,'本页有待核实内容，请说明已补充的依据，或删除了哪些未核实表述')
    raw=None
    if outline['kind']=='photo':
        asset=task['assets'].get(str(number))
        if not asset:raise HTTPException(409,'本页需要实拍，请先保存照片')
        raw=(DATA/'assets'/task_id/asset['file']).read_bytes()
    if outline['kind']=='text' and not (body.title.strip() or body.text.strip()):raise HTTPException(422,'文字卡不能空白')
    try:rendered,meta=rendering.render(body.title,body.text,raw)
    except ValueError as exc:raise HTTPException(422,str(exc)) from None
    folder=DATA/'cards'/task_id;folder.mkdir(parents=True,exist_ok=True)
    filename=f'{number:02d}_{uuid4().hex}.png';path=folder/filename;path.write_bytes(rendered)
    page.update(title=body.title,text=body.text)
    task['renders'][str(number)]={'file':filename,'sha256':hashlib.sha256(rendered).hexdigest(),**meta}
    task['page_reviews'][str(number)]={'confirmed':True,'resolution':body.resolution,'pending_at_review':page['pending'],
                                      'time':datetime.now(timezone.utc).isoformat()}
    task.update(stage='making',copy_review=None)
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
    return Response(rendering.export_zip(task,images),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="post_{task_id}.zip"'})

@app.post('/api/tasks/{task_id}/feedback',dependencies=[Depends(auth)])
def feedback(task_id:str,body:FeedbackInput):
    task=get_task(task_id,True)
    if not task['draft']:raise HTTPException(409,'请先完成草稿')
    result=invoke(task,FeedbackAnalysis,{'action':'区分平台原文与推测，不保证修改后通过。platform_quotes逐字摘自notice。',
                 'notice':body.notice,'posted_text':body.posted_text or task['draft']['body']})
    if any(q not in body.notice for q in result.platform_quotes):raise HTTPException(502,'平台引文不一致，请重试')
    task['feedback'].append({'input':body.model_dump(),'analysis':result.model_dump(),'status':'待人工复核，不自动更新规则'})
    return save(task,task['revision'])
