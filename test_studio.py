import base64
import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

TEMP=tempfile.TemporaryDirectory()
os.environ['STUDIO_DATA_DIR']=TEMP.name
os.environ['STUDIO_ACCESS_TOKEN']='test-only-access-key-not-for-production'# 测试隔离：离线测试默认关闭视觉轨（本机 .env 可能已配置真实 key，
# 不关闭会让未 mock 的视觉调用打到真实 API，慢、花钱、结果不确定）。
# 视觉相关用例自行用 patch.dict(os.environ, ...) 打开。
os.environ['VISION_PROVIDER']=''
from fastapi.testclient import TestClient
from PIL import Image,ImageChops
from studio import api,cases,llm,rendering,runlog
from studio.models import Analysis,AnalysisCompact,Draft,FeedbackAnalysis,CaseRanking


def picture():
    im=Image.new('RGB',(320,240),'#b64721')
    for x in range(50):im.putpixel((x,40),(10,80,180))
    b=io.BytesIO();im.save(b,format='PNG');return b.getvalue()


def bundle(missing=False,case_empty=False):
    data=picture();member='images/row000_01.png'
    page={'number':1,'ocr':'M22仪器有什么区别？对比清单','image':None if missing else member,
          'image_sha256':hashlib.sha256(data).hexdigest(),'ocr_status':'available'}
    note={'id':'row000','title':'M22仪器对比','body':'结构说明','likes':2122,'author':'样本作者',
          'url':'https://www.xiaohongshu.com/explore/example','collected_at':'2026-09-15','pages':[page], 'research':None}
    lower=copy.deepcopy(note);lower.update(id='row001',likes=80)
    irrelevant=copy.deepcopy(note);irrelevant.update(id='row002',title='肺结节分析',likes=99999)
    irrelevant['pages'][0]['ocr']='肺结节分型'
    manifest={'schema_version':1,'version':'test1','cases':[] if case_empty else [note,lower,irrelevant]}
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
        if not missing:z.writestr(member,data)
    return b.getvalue()


def bundle_many_pages(count=13):
    """超过视觉页数上限的案例：用于验证自动降级文字轨。"""
    data=picture();member='images/row000_01.png'
    pages=[{'number':i,'ocr':f'M22光子嫩肤科普第{i}页','image':member,
            'image_sha256':hashlib.sha256(data).hexdigest(),'ocr_status':'available'} for i in range(1,count+1)]
    note={'id':'row000','title':'M22超多页案例','body':'结构说明','likes':3000,'author':'样本作者',
          'url':'https://www.xiaohongshu.com/explore/example','collected_at':'2026-09-15','pages':pages,'research':None}
    manifest={'schema_version':1,'version':'test-many','cases':[note]}
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
        z.writestr(member,data)
    return b.getvalue()


def fake_generate(schema,instruction,sources,images=None,outline_anchor=None):
    if schema in (Analysis,AnalysisCompact):
        c=next(s['content'] for s in sources if s['id']=='CASE')
        data=dict(summary='原帖用固定字段比较，新内容借鉴组织顺序。',
            original_pages=[{'number':p['number'],'form':'仅按OCR推测为对比文字','observation':'有对比问句',
                             'ocr_quote':p['ocr'][:8],'borrow':'固定比较维度','uncertainty':'布局需对照原图'} for p in c['pages']],
            borrow=['从同一问题展开'],missing_information=[],
            outline=[{'kind':'text','purpose':'封面问题','instruction':'制作文字封面','visual_spec':'简洁浅色底','source_pages':[1]},
                     {'kind':'text','purpose':'三个确认问题','instruction':'制作问题清单','visual_spec':'编号列表样式','source_pages':[1]}])
        result=schema.model_validate(data)
    elif schema is Draft:
        pages=[]
        for i,item in enumerate(instruction['outline'],1):
            page={'number':i,'title':'了解M22' if i==1 else '先确认的信息','text':'名称、资料与咨询问题。',
                  'source_ids':['SHOP'],'pending':[]}
            if item.get('kind')=='chat':
                page['text']='顾客：第一次做要注意什么？\n门店：先到店面诊评估，以医生意见为准。'
                page['dialog']=[{'speaker':'customer','text':'第一次做要注意什么？'},
                                {'speaker':'shop','text':'先到店面诊评估，以医生意见为准。'}]
            pages.append(page)
        result=Draft(title='第一次了解M22，先确认这些信息',body='先确认设备名称，再核对资料出处。',
            pages=pages,missing_information=[])
    elif schema is CaseRanking:
        question=instruction.get('question','')
        if '咖啡拉花' in question:
            result=CaseRanking(scores=[{'case_id':'row000','relevance':2,'reason':'主题不符'},
                                       {'case_id':'row001','relevance':1,'reason':'主题不符'}])
        else:
            result=CaseRanking(scores=[{'case_id':'row000','relevance':9,'reason':'直接回答该问题'},
                                       {'case_id':'row001','relevance':5,'reason':'部分相关，可借鉴角度'}])
    else:
        result=FeedbackAnalysis(platform_quotes=[instruction['notice']],hypotheses=['仍需核实'],next_actions=['补充通知'],missing_information=[])
    return result,{'prompt':json.dumps(instruction,ensure_ascii=False),'response':result.model_dump(),'reference_image_pages':[]}


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(api.app)
        self.client.headers['Authorization']='Bearer '+os.environ['STUDIO_ACCESS_TOKEN']
        r=self.client.post('/api/bundles',files={'bundle':('cases.zip',bundle(),'application/zip')})
        self.assertEqual(r.status_code,200,r.text);self.bundle_id=r.json()['bundle_id']

    def create(self,question='M22仪器有什么区别',bundle_id=None):
        r=self.client.post('/api/tasks',json={'project':'M22','audience':'第一次了解的顾客','question':question,
                                            'facts':'本篇只整理咨询问题，不提供治疗建议。','bundle_id':bundle_id or self.bundle_id})
        self.assertEqual(r.status_code,200,r.text);return r.json()

    def post(self,task,path,**extra):
        r=self.client.post('/api/tasks/'+task['id']+path,json={'revision':task['revision'],**extra})
        self.assertEqual(r.status_code,200,r.text);return r.json()

    def ready(self,photo=False):
        t=self.create();t=self.post(t,'/analyze')
        analysis=t['analysis']
        if photo:analysis['outline'][1]['kind']='photo'
        t=self.post(t,'/confirm-analysis',analysis=analysis)
        return self.post(t,'/draft')

    def make_all(self,t):
        for p in t['draft']['pages']:
            t=self.post(t,f"/pages/{p['number']}",title=p['title'],text=p['text'],confirmed=True)
        return t

    def test_auth_cache_and_page_contract(self):
        self.assertEqual(TestClient(api.app).get('/api/tasks').status_code,401)
        import re
        html=self.client.get('/');script=self.client.get('/static/app.js?v='+api.VERSION)
        ids=set(re.findall(r'id="([^"]+)"',html.text));required=set(re.findall(r"\$\('([^']+)'\)",script.text))
        self.assertFalse(required-ids);self.assertEqual(html.headers['cache-control'],'no-store')
        self.assertEqual(script.headers['cache-control'],'no-store')
        self.assertNotIn('catch(e){}await render()',script.text)

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_selection_and_no_match(self,mock):
        t=self.create();self.assertEqual(t['case']['id'],'row000');self.assertEqual(t['selection']['eligible_count'],2)
        self.assertEqual(t['selection']['method'],'llm_relevance_plus_likes')
        self.assertIn('相关度',t['selection']['reason']);self.assertIn('M22仪器对比',t['selection']['reason'])
        self.assertEqual(t['selection']['top3'][0]['title'],'M22仪器对比')
        rows=self.client.get('/api/tasks').json()
        self.assertTrue(all(k in rows[0] for k in ('stage','revision','updated_at','exported','legacy')))
        t=self.create('咖啡拉花课程');self.assertEqual(t['stage'],'no_match');self.assertIsNone(t['case'])
        r=self.client.post('/api/tasks/'+t['id']+'/analyze',json={'revision':0});self.assertEqual(r.status_code,409)

    def test_combine_ranking_prefers_relevance(self):
        pool=[{'id':'a','likes':2000},{'id':'b','likes':100},{'id':'c','likes':500},{'id':'d','likes':900}]
        ranked=cases.combine_ranking(pool,{'a':4,'b':9,'c':8,'d':3})
        self.assertEqual([r['case']['id'] for r in ranked],['b','c','a'])

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_ai_background_render_and_fallback(self,mock):
        t=self.ready()
        # 选"AI 底图"样式但未配置画图轨：自动降级纯色底，不阻断流程
        t=self.post(t,'/pages/1',title=t['draft']['pages'][0]['title'],text=t['draft']['pages'][0]['text'],confirmed=True,card_theme='ai')
        self.assertEqual(t['renders']['1']['method'],'plain_fallback_layout')
        self.assertEqual(t['renders']['1']['background_source'],'plain')
        # 配置画图轨后：AI 底图成功，标记为合成渲染并保留底图记录
        with patch('studio.llm.generate_background',return_value=picture()),\
             patch.dict(os.environ,{'VISION_PROVIDER':'glm','VISION_API_KEY':'test-key'}):
            t=self.post(t,'/pages/2',title=t['draft']['pages'][1]['title'],text=t['draft']['pages'][1]['text'],confirmed=True,card_theme='ai')
        self.assertEqual(t['renders']['2']['method'],'ai_background_composited')
        self.assertEqual(t['renders']['2']['background_source'],'ai_new')
        self.assertIn('2',t['backgrounds'])
        self.assertTrue((api.DATA/'backgrounds'/t['id']/t['backgrounds']['2']['file']).exists())

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_text_card_default_program_theme(self,mock):
        t=self.ready()
        # 默认样式：程序版式，不调用画图轨
        t=self.post(t,'/pages/1',title=t['draft']['pages'][0]['title'],text=t['draft']['pages'][0]['text'],confirmed=True)
        self.assertEqual(t['renders']['1']['method'],'program_minimal')
        self.assertEqual(t['renders']['1']['theme'],'minimal')
        self.assertIsNone(t['renders']['1']['background_source'])
        self.assertNotIn('1',t.get('backgrounds',{}))
        t=self.post(t,'/pages/1',title='标题',text='内容',confirmed=True,card_theme='soft')
        self.assertEqual(t['renders']['1']['method'],'program_soft')
        t=self.post(t,'/pages/1',title='标题',text='内容',confirmed=True,card_theme='duotone')
        self.assertEqual(t['renders']['1']['method'],'program_duotone')

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_chat_page_renders_wechat_dialog(self,mock):
        t=self.create();t=self.post(t,'/analyze')
        analysis=t['analysis'];analysis['outline'][1]['kind']='chat'
        t=self.post(t,'/confirm-analysis',analysis=analysis)
        t=self.post(t,'/draft')
        # 草稿为对话页生成 dialog 轮次
        self.assertEqual(t['draft']['pages'][1]['dialog'][0]['speaker'],'customer')
        chat_text='顾客：第一次做M22要注意什么？\n门店：先到店面诊评估，孕期或光敏体质要提前告知医生。'
        t=self.post(t,'/pages/2',title='顾客咨询',text=chat_text,confirmed=True)
        self.assertEqual(t['renders']['2']['method'],'wechat_dialog')
        self.assertEqual(t['draft']['pages'][1]['dialog'][1]['text'],'先到店面诊评估，孕期或光敏体质要提前告知医生。')
        # 格式不合格：没有两轮对话时明确报错
        r=self.client.post('/api/tasks/'+t['id']+'/pages/2',json={'revision':t['revision'],
            'title':'顾客咨询','text':'只有一句没有前缀的话','confirmed':True})
        self.assertEqual(r.status_code,422)

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_background_regen_failure_marks_stale(self,mock):
        t=self.ready()
        with patch('studio.llm.generate_background',return_value=picture()),\
             patch.dict(os.environ,{'VISION_PROVIDER':'glm','VISION_API_KEY':'test-key'}):
            t=self.post(t,'/pages/1',title='封面',text='内容',confirmed=True,card_theme='ai')
            self.assertEqual(t['renders']['1']['background_source'],'ai_new')
            # 用户要求重新生成但画图失败：保留旧底图继续渲染，标记 ai_stale 而非静默复用
            with patch('studio.llm.generate_background',side_effect=RuntimeError('画图服务超时')):
                t=self.post(t,'/pages/1',title='封面',text='内容',confirmed=True,regenerate_background=True,card_theme='ai')
        self.assertEqual(t['renders']['1']['background_source'],'ai_stale')
        self.assertEqual(t['renders']['1']['method'],'ai_background_composited')
        self.assertTrue(any(f['action']=='generate_background' for f in t['failures']))

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_vision_analyze_uses_reference_images(self,mock):
        t=self.create()
        def vision_fake(schema,instruction,sources,images,outline_anchor=None):
            assert images,'视觉分析必须携带参考图'
            return fake_generate(schema,instruction,sources,images)
        with patch.dict(os.environ,{'VISION_PROVIDER':'glm','VISION_API_KEY':'test-key'}),\
             patch('studio.llm.generate_vision',side_effect=vision_fake):
            t=self.post(t,'/analyze')
        self.assertIn('原图',t['analysis_basis'])

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_polish_analysis_dedupes_and_compresses(self,mock):
        """polish_analysis：删占位页/近重复页；超页自动压缩（mock 压缩调用）。"""
        t=self.create()
        from studio.models import Analysis as AModel
        def compress(schema,instruction,sources,images=None,outline_anchor=None):
            if schema is Analysis and instruction.get('rules'):
                data=copy.deepcopy(instruction['previous_analysis'])
                data['outline']=data['outline'][:2]
                return Analysis.model_validate(data),{'prompt':'x','response':{},'reference_image_pages':[]}
            return fake_generate(schema,instruction,sources,images)
        task_obj=api.get_task(t['id'],True)
        pages_count=len(task_obj['case']['pages'])
        analysis=task_obj['analysis'] or {'original_pages':[{'number':1,'form':'x','observation':'y','borrow':'b'}]}
        bad=AModel.model_validate({'summary':'s','original_pages':analysis['original_pages'],'borrow':[],
                                   'missing_information':[],'outline':[
              {'kind':'text','purpose':'封面总领','instruction':'制作封面','visual_spec':'','source_pages':[1]},
              {'kind':'text','purpose':'根据参考图填写','instruction':'填写','visual_spec':'','source_pages':[1]},
              {'kind':'text','purpose':'问题清单','instruction':'列出问题','visual_spec':'','source_pages':[1]},
              {'kind':'text','purpose':'继续问题清单','instruction':'列出问题','visual_spec':'','source_pages':[1]}]})
        with patch('studio.llm.generate',side_effect=compress):
            polished,notes=api.polish_analysis(task_obj,bad,pages_count)
        self.assertEqual(len(polished.outline),2)          # 占位页+重复页已删，2<=1+1 合规，无需再压缩
        self.assertTrue(any('占位页' in n for n in notes))
        self.assertTrue(any('重复页' in n for n in notes))

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_runlog_written_for_task_lifecycle(self,mock):
        t=self.make_all(self.ready())
        self.post(t,'/copy',title=t['draft']['title'],body=t['draft']['body'],confirmed=True)
        r=self.client.get('/api/tasks/'+t['id']+'/export')
        self.assertEqual(r.status_code,200)
        logdir=api.DATA/'runlogs'
        mine=list(logdir.glob('*'+t['id'][:8]+'*.md'))
        self.assertEqual(len(mine),1)
        content=mine[0].read_text(encoding='utf-8')
        for frag in ('创建任务','拆解','生成逐页草稿','导出图文包','问题：'):
            self.assertIn(frag,content)
        self.assertIn(t['id'][:8],mine[0].name)

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_vision_failure_falls_back_to_text_track(self,mock):
        t=self.create()
        def vision_fail(schema,instruction,sources,images,outline_anchor=None):
            raise RuntimeError('视觉模型输出质量不合格')
        with patch.dict(os.environ,{'VISION_PROVIDER':'glm','VISION_API_KEY':'test-key'}),\
             patch('studio.llm.generate_vision',side_effect=vision_fail):
            t=self.post(t,'/analyze')
        self.assertIn('降级',t['analysis_basis'])
        self.assertIn('OCR+正文',t['analysis_basis'])
        self.assertTrue(t['failures'])                       # 视觉失败已留档
        args,kwargs=mock.call_args
        self.assertNotIn('images',kwargs)                    # 降级后走文字轨不带图

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_many_pages_falls_back_to_text_track(self,mock):
        r=self.client.post('/api/bundles',files={'bundle':('many.zip',bundle_many_pages(),'application/zip')})
        self.assertEqual(r.status_code,200,r.text)
        t=self.create(bundle_id=r.json()['bundle_id'])
        self.assertEqual(len(t['case']['pages']),13)
        with patch.dict(os.environ,{'VISION_PROVIDER':'glm','VISION_API_KEY':'test-key'}):
            t=self.post(t,'/analyze')
        self.assertIn('上限',t['analysis_basis'])
        self.assertIn('未做视觉解析',t['analysis_basis'])
        args,kwargs=mock.call_args
        self.assertNotIn('images',kwargs)  # 走文字轨：不带图

    def test_vision_overload_retry_shrinks_payload(self):
        """1210 超长（输入+输出>16384）时：图文各减半重试一次并成功。"""
        good=json.dumps({'summary':'实拍对比','original_pages':[{'number':1,'form':'文字卡','observation':'清单式排版',
                     'ocr_quote':'','borrow':'列表结构'}],'borrow':['按时间线组织'],'missing_information':[],
                     'outline':[{'kind':'text','purpose':'封面提问','instruction':'制作封面','source_pages':[1]}]},ensure_ascii=False)
        big=io.BytesIO();Image.new('RGB',(1600,2100),'#3a6ea5').save(big,format='PNG');big=big.getvalue()
        class _Resp:
            def __init__(self,content):
                self.choices=[type('C',(),{'message':type('M',(),{'content':content})()})()]
                self.usage=type('U',(),{'prompt_tokens':10,'completion_tokens':5})()
        calls=[]
        class _Comp:
            def create(self,**kw):
                calls.append(kw)
                if len(calls)==1:
                    raise ValueError("Error code: 400 - {'error': {'code': '1210', 'message': "
                                     "'Input validation error: `inputs` tokens + `max_new_tokens` must be "
                                     "<= 16384. Given: 14801 `inputs` tokens and 2048 `max_new_t...'}}")
                return _Resp(good)
        class _Client:
            def __init__(self,**kw):self.chat=type('Chat',(),{'completions':_Comp()})()
        with patch.dict(os.environ,{'VISION_PROVIDER':'glm','VISION_API_KEY':'test-key'}),\
             patch('openai.OpenAI',_Client):
            parsed,trace=llm.generate_vision(AnalysisCompact,{'q':'问题'+'细'*8000},[],
                                             [{'number':1,'data':big}])
        self.assertEqual(parsed.summary,'实拍对比')
        self.assertEqual([a['outcome'] for a in trace['attempts']],['parse_shrunk'])
        def dims(call):
            url=call['messages'][1]['content'][0]['image_url']['url']
            with Image.open(io.BytesIO(base64.b64decode(url.split(',',1)[1]))) as im:return im.size
        first,second=dims(calls[0]),dims(calls[1])
        self.assertLessEqual(first[0]*first[1],1_920_000)      # 首次已按预算压缩
        self.assertLess(second[0]*second[1],first[0]*first[1]) # 超限自愈：图片进一步压到最小预算

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_analysis_stage_gates_and_reject_reruns_current_step(self,mock):
        t=self.create()
        self.assertEqual(self.client.post('/api/tasks/'+t['id']+'/analysis-stage',json={'revision':0,'stage':'language','decision':'accept'}).status_code,409)
        t=self.post(t,'/analysis-stage',stage='retrieval',decision='accept')
        t=self.post(t,'/analyze')
        self.assertEqual(self.client.post('/api/tasks/'+t['id']+'/analysis-stage',json={'revision':t['revision'],'stage':'facts','decision':'accept'}).status_code,409)
        t=self.post(t,'/analysis-stage',stage='language',decision='accept')
        self.assertEqual(self.client.post('/api/tasks/'+t['id']+'/analysis-stage',json={'revision':t['revision'],'stage':'visual','decision':'reject'}).status_code,422)
        t=self.post(t,'/analysis-stage',stage='visual',decision='reject',feedback='请把视觉不确定项单独列出')
        self.assertEqual(t['analysis_stages']['visual']['status'],'ready')
        self.assertEqual([d['stage'] for d in t['analysis_decisions']],['retrieval','language','visual'])
        self.assertEqual(mock.call_count,3)

    def test_import_idempotent_and_malformed(self):
        r=self.client.post('/api/bundles',files={'bundle':('cases.zip',bundle(),'application/zip')})
        self.assertEqual(r.status_code,200)
        self.assertEqual(len(list(api.BUNDLES.glob(self.bundle_id+'.zip'))),1)
        for bad in (b'notzip',bundle(case_empty=True)):
            self.assertEqual(self.client.post('/api/bundles',files={'bundle':('a.zip',bad)}).status_code,422)
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:z.writestr('../outside.txt','no')
        self.assertEqual(self.client.post('/api/bundles',files={'bundle':('a.zip',b.getvalue())}).status_code,422)

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_missing_reference_image_blocks_analysis(self,mock):
        r=self.client.post('/api/bundles',files={'bundle':('a.zip',bundle(missing=True))})
        t=self.create(bundle_id=r.json()['bundle_id'])
        with patch('studio.llm.generate') as mock:
            r=self.client.post('/api/tasks/'+t['id']+'/analyze',json={'revision':0})
        self.assertEqual(r.status_code,409);mock.assert_not_called()

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_text_only_end_to_end_and_resume(self,mock):
        t=self.ready();self.assertFalse(t['assets'])
        t=self.make_all(t)
        t=self.post(t,'/progress',page_index=1)
        other=TestClient(api.app);other.headers.update(self.client.headers)
        restored=other.get('/api/tasks/'+t['id']).json()
        self.assertEqual(restored['page_index'],1);self.assertEqual(restored['renders'],t['renders'])
        t=self.post(restored,'/copy',title=t['draft']['title'],body=t['draft']['body'],confirmed=True)
        r=self.client.get('/api/tasks/'+t['id']+'/export');self.assertEqual(r.status_code,200)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            self.assertEqual(set(z.namelist()),{'01.png','02.png','标题正文.txt','来源记录.json','待核实记录.txt'})
            self.assertIn('M22',z.read('标题正文.txt').decode())
            evidence=json.loads(z.read('来源记录.json'))
            self.assertEqual(evidence['case']['id'],'row000')
            self.assertTrue(evidence['copy_review']['confirmed'])
            self.assertTrue(all(v['status']=='accepted' for v in evidence['analysis_stages'].values()))
            Image.open(io.BytesIO(z.read('01.png'))).verify()
        self.assertEqual(mock.call_count,3)

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_photo_pixels_unchanged(self,mock):
        t=self.ready(photo=True)
        r=self.client.post('/api/tasks/'+t['id']+'/pages/2/photo',data={'revision':t['revision'],'caption':'测试图，不冒充门店照片'},files={'photo':('photo.png',picture(),'image/png')})
        self.assertEqual(r.status_code,200,r.text);t=r.json()
        # 已有照片时可只更新说明，不必重传文件
        r=self.client.post('/api/tasks/'+t['id']+'/pages/2/photo',data={'revision':t['revision'],'caption':'更新后的说明'},files={})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['assets']['2']['caption'],'更新后的说明')
        t=r.json()
        self.assertEqual(t['assets']['2']['sha256'],hashlib.sha256(picture()).hexdigest())
        t=self.make_all(t)
        raw=self.client.get('/api/tasks/'+t['id']+'/pages/2/render').content
        rendered=Image.open(io.BytesIO(raw));offset=t['renders']['2']['photo_offset_y']
        original=Image.open(io.BytesIO(picture())).convert('RGB')
        self.assertIsNone(ImageChops.difference(original,rendered.crop((0,offset,320,offset+240))).getbbox())
        t=self.post(t,'/copy',title='主题',body='正文',confirmed=True)
        r=self.client.get('/api/tasks/'+t['id']+'/export');self.assertEqual(r.status_code,200)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            evidence=json.loads(z.read('来源记录.json'))
            self.assertEqual(evidence['assets']['2']['caption'],'更新后的说明')

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_delete_task_removes_row_and_files(self,mock):
        t=self.ready(photo=True)
        r=self.client.post('/api/tasks/'+t['id']+'/pages/2/photo',data={'revision':t['revision'],'caption':'说明'},files={'photo':('photo.png',picture(),'image/png')})
        self.assertEqual(r.status_code,200);t=r.json()
        self.assertTrue((api.DATA/'assets'/t['id']).exists())
        self.assertEqual(self.client.delete('/api/tasks/'+t['id'],params={'revision':t['revision']+5}).status_code,409)
        self.assertEqual(self.client.delete('/api/tasks/'+t['id'],params={'revision':t['revision']}).status_code,200)
        self.assertFalse((api.DATA/'assets'/t['id']).exists())
        self.assertEqual(self.client.get('/api/tasks/'+t['id']).status_code,404)

    @patch('studio.llm.generate',side_effect=RuntimeError('secret-value'))
    def test_model_failure_saved_no_loop(self,mock):
        t=self.create();r=self.client.post('/api/tasks/'+t['id']+'/analyze',json={'revision':0})
        self.assertEqual(r.status_code,502);self.assertNotIn('secret-value',r.text);self.assertEqual(mock.call_count,2)
        saved=self.client.get('/api/tasks/'+t['id']).json();self.assertIsNone(saved['analysis'])
        self.assertEqual(saved['stage'],'candidate');self.assertEqual(len(saved['failures']),1)
        with patch('studio.llm.generate',side_effect=fake_generate):saved=self.post(saved,'/analyze')
        self.assertEqual(saved['stage'],'analysis_review')

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_confirmation_and_conflict(self,mock):
        t=self.create()
        self.assertEqual(self.client.post('/api/tasks/'+t['id']+'/draft',json={'revision':0}).status_code,409)
        t=self.post(t,'/analyze')
        self.assertEqual(self.client.post('/api/tasks/'+t['id']+'/confirm-analysis',json={'revision':0,'analysis':t['analysis']}).status_code,409)
        bad=copy.deepcopy(t['analysis']);bad['original_pages'][0]['ocr_quote']='凭空编造的原文'
        self.assertEqual(self.client.post('/api/tasks/'+t['id']+'/confirm-analysis',json={'revision':t['revision'],'analysis':bad}).status_code,422)

    def test_missing_facts_require_resolution(self):
        def pending(schema,instruction,sources,images=None,outline_anchor=None):
            result,trace=fake_generate(schema,instruction,sources,images)
            if schema is Draft:
                result.pages[0].pending=['型号资料未核实'];result.missing_information=['不具备治疗参数依据']
            return result,trace
        with patch('studio.llm.generate',side_effect=pending):t=self.ready()
        r=self.client.post('/api/tasks/'+t['id']+'/pages/1',json={'revision':t['revision'],'title':'咨询清单','text':'先记录问题','confirmed':True})
        self.assertEqual(r.status_code,422)
        t=self.post(t,'/pages/1',title='咨询清单',text='先记录问题',confirmed=True,resolution='移除型号断言，只保留问题清单')
        t=self.post(t,'/pages/2',title='再确认资料',text='记录出处',confirmed=True)
        self.assertEqual(self.client.post('/api/tasks/'+t['id']+'/copy',json={'revision':t['revision'],'title':'咨询前','body':'准备问题','confirmed':True}).status_code,422)
        t=self.post(t,'/copy',title='咨询前',body='准备问题',confirmed=True,resolution='正文不含治疗参数')
        self.assertEqual(self.client.get('/api/tasks/'+t['id']+'/export').status_code,200)

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_export_blocks_incomplete_and_edit_invalidates(self,mock):
        t=self.ready();self.assertEqual(self.client.get('/api/tasks/'+t['id']+'/export').status_code,409)
        t=self.make_all(t);t=self.post(t,'/copy',title='主题',body='正文',confirmed=True)
        t=self.post(t,'/pages/1',title='已保存新标题',text='新内容',confirmed=False)
        self.assertIsNone(t['copy_review']);self.assertNotIn('1',t['renders'])
        self.assertEqual(self.client.get('/api/tasks/'+t['id']+'/export').status_code,409)
        self.assertEqual(self.client.get('/api/tasks/'+t['id']).json()['draft']['pages'][0]['title'],'已保存新标题')

    def test_legacy_preserved(self):
        old={'id':'legacy-test','revision':0,'request':{'project':'M22','question':'旧任务'},'stage':'shooting','assets':[],'draft':None}
        with api.db() as conn:conn.execute('INSERT OR REPLACE INTO tasks VALUES (?,?,?)',(old['id'],0,json.dumps(old)))
        self.assertEqual(self.client.get('/api/tasks/legacy-test').json(),old)
        self.assertEqual(self.client.post('/api/tasks/legacy-test/analyze',json={'revision':0}).status_code,409)

if __name__=='__main__':unittest.main()
