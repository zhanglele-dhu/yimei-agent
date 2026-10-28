import base64
import copy
import hashlib
import io
import json
import os
import shutil
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
os.environ['ARK_API_KEY']=''
os.environ['STUDIO_CARD_PROVIDER']=''
os.environ['DEEPSEEK_API_KEY']=''  # Unmocked calls fail locally, never spend live API quota.
from fastapi.testclient import TestClient
from PIL import Image,ImageChops
from studio import api,cases,llm,rendering,runlog
from studio.models import Analysis,AnalysisCompact,Draft,FeedbackAnalysis,CaseRanking,EditorialPlan,QuestionOutline,DraftContentReview


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
    nursing=copy.deepcopy(note);nursing.update(id='row003',title='M22术后护理',likes=55)
    nursing['pages'][0]['ocr']='M22术后护理与恢复'
    manifest={'schema_version':1,'version':'test1','cases':[] if case_empty else [note,lower,irrelevant,nursing]}
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
    note={'id':'row000','title':'M22仪器对比多页案例','body':'结构说明','likes':3000,'author':'样本作者',
          'url':'https://www.xiaohongshu.com/explore/example','collected_at':'2026-09-15','pages':pages,'research':None}
    manifest={'schema_version':1,'version':'test-many','cases':[note]}
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
        z.writestr(member,data)
    return b.getvalue()


def fake_generate(schema,instruction,sources,images=None,outline_anchor=None):
    if schema is EditorialPlan:
        result=EditorialPlan(audience_brief={'reader':instruction['request']['audience'],
            'questions':['M22是什么？','怎样理解不同特点？'],'approach':'按读者问题分点介绍','defer_topics':[]},
            direction='M22入门科普',reading_goal='理解基础知识',reference_use='借鉴固定维度的介绍方法')
    elif schema is QuestionOutline:
        result=QuestionOutline(reference_takeaway='固定维度对比',adaptation='借鉴逐点介绍',pagination_reason='每页一个问题',
            pages=[{'kind':'text','purpose':name,'instruction':'分点介绍','reader_question':name,
                    'key_points':['一个特点','另一个特点'],'new_terms':['M22'],'source_pages':[1]}
                   for name in ('封面问题','三个确认问题')])
    elif schema is DraftContentReview:
        result=DraftContentReview(audience_fit=True,direction_fit=True,question_coverage=True,readable=True,source_supported=True,
            summary='内容适合读者，可进入成图',pages=[{'number':p['number'],'passed':True} for p in instruction['draft']['pages']])
    elif schema.__name__=='CreationIntent':
        from studio.semantic import infer_rules
        result=infer_rules(instruction['user_text'],instruction.get('project_hint',''),instruction.get('audience_hint',''))
    elif schema in (Analysis,AnalysisCompact):
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
    def test_reference_vision_reuses_ark_and_sends_images(self):
        from types import SimpleNamespace
        result = {'summary':'参考原图分析', 'original_pages':[{'number':1,'form':'对比表格',
            'observation':'横向比较设备，蓝色标题与绿色标记','ocr_quote':'','borrow':'沿用同维度对照'}],
            'borrow':['固定维度对照'], 'missing_information':[],
            'outline':[{'kind':'text','purpose':'M22基础科普','instruction':'分层讲解原理','source_pages':[1]}]}
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(result,ensure_ascii=False)))],usage=None)
        with patch.dict(os.environ,{'VISION_PROVIDER':'glm','ARK_API_KEY':'test-ark-key',
                'ARK_CARD_REVIEW_MODEL':'test-doubao-vision','STUDIO_CARD_PROVIDER':''}), patch('openai.OpenAI') as client:
            client.return_value.chat.completions.create.return_value=response
            parsed,trace=llm.generate_vision(AnalysisCompact,{'goal':'M22科普'},[],[{'number':1,'data':picture()}])
            self.assertTrue(llm.supports_vision())
            self.assertEqual(client.call_args.kwargs['api_key'],'test-ark-key')
            call=client.return_value.chat.completions.create.call_args.kwargs
            self.assertEqual(call['model'],'test-doubao-vision')
            self.assertTrue(call['messages'][1]['content'][0]['image_url']['url'].startswith('data:image/jpeg;base64,'))
            self.assertEqual(call['extra_body']['thinking']['type'],'disabled')
            self.assertEqual(trace['provider'],'ark-vision')
            self.assertEqual(parsed.original_pages[0].form,'对比表格')

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_visual_redo_updates_basis_and_keeps_prior_approvals(self,mock):
        t=self.create()
        t=self.post(t,'/analyze')
        for stage in ('retrieval','language'):
            t=self.post(t,'/analysis-stage',stage=stage,decision='accept')
        def vision(schema,instruction,sources,images,outline_anchor=None):
            output,trace=fake_generate(schema,instruction,sources,images,outline_anchor)
            trace['reference_image_pages']=[p['number'] for p in images]
            return output,trace
        with patch('studio.llm.supports_vision',return_value=True),patch('studio.llm.generate_vision',side_effect=vision) as visual:
            t=self.post(t,'/analysis-stage',stage='visual',decision='reject',feedback='直接看原图后提出创作建议')
        self.assertTrue(visual.called)
        self.assertEqual(t['analysis_basis'],'原图+OCR+正文')
        self.assertEqual(t['analysis_stages']['language']['status'],'accepted')
        self.assertEqual(t['analysis_stages']['visual']['status'],'ready')
        with patch('studio.llm.supports_vision',return_value=True),patch('studio.llm.generate_vision',side_effect=RuntimeError('offline simulated error')):
            t=self.post(t,'/analysis-stage',stage='visual',decision='reject',feedback='再看原图')
        self.assertNotEqual(t['analysis_basis'],'原图+OCR+正文')
        text_call=next(call.args[1] for call in reversed(mock.call_args_list) if 'visual_input' in call.args[1])
        self.assertFalse(text_call['visual_input'])

    def setUp(self):
        offline=patch('studio.llm.generate',side_effect=fake_generate)
        offline.start();self.addCleanup(offline.stop)
        api._VISION_BREAKER['fails']=0  # 测试隔离：熔断计数不复位会跨用例泄漏
        self.client=TestClient(api.app)
        self.client.headers['Authorization']='Bearer '+os.environ['STUDIO_ACCESS_TOKEN']
        r=self.client.post('/api/bundles',files={'bundle':('cases.zip',bundle(),'application/zip')})
        self.assertEqual(r.status_code,200,r.text);self.bundle_id=r.json()['bundle_id']

    def create(self,question='M22仪器有什么区别',bundle_id=None):
        r=self.client.post('/api/tasks',json={'project':'M22','audience':'第一次了解的顾客','question':question,
                                            'facts':'本篇只整理咨询问题，不提供治疗建议。','bundle_id':bundle_id or self.bundle_id})
        self.assertEqual(r.status_code,200,r.text);return r.json()

    def post(self,task,path,**extra):
        if path.startswith('/pages/') and not path.endswith('/photo'):extra.setdefault('generation_mode','template')
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

    def test_local_session_only_bootstraps_loopback_same_origin(self):
        local = TestClient(api.app, base_url='http://127.0.0.1:8010', client=('127.0.0.1', 50000))
        headers = {'X-Studio-Local': '1', 'Sec-Fetch-Site': 'same-origin'}
        with patch.dict(os.environ, {'STUDIO_LOCAL_SESSION': ''}):
            self.assertEqual(local.get('/api/local-session', headers=headers).status_code, 403)
        with patch.dict(os.environ, {'STUDIO_LOCAL_SESSION': '1'}):
            response = local.get('/api/local-session', headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(local.get('/api/tasks').status_code, 401)
            self.assertEqual(local.get('/api/tasks', headers={'Authorization': 'Bearer '+response.json()['access_token']}).status_code, 200)
            for extra in ({'Host': 'evil.example'}, {'Origin': 'http://localhost:9999'},
                          {'Sec-Fetch-Site': 'cross-site'}, {'X-Studio-Local': ''}):
                self.assertEqual(local.get('/api/local-session', headers={**headers, **extra}).status_code, 403)
            remote = TestClient(api.app, base_url='http://127.0.0.1:8010', client=('192.168.1.20', 50000))
            self.assertEqual(remote.get('/api/local-session', headers=headers).status_code, 403)
        html = local.get('/').text
        self.assertNotIn('id="accessModal"', html)
        self.assertNotIn('连接工作台', html)

    def test_auth_cache_and_page_contract(self):
        self.assertEqual(TestClient(api.app).get('/api/tasks').status_code,401)
        import re
        html=self.client.get('/');script=self.client.get('/static/app.js?v='+api.VERSION)
        ids=set(re.findall(r'id="([^"]+)"',html.text));required=set(re.findall(r"\$\('([^']+)'\)",script.text))
        self.assertFalse(required-ids);self.assertEqual(html.headers['cache-control'],'no-store')
        self.assertEqual(script.headers['cache-control'],'no-store')
        self.assertNotIn('catch(e){}await render()',script.text)

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_create_preserves_empty_facts_without_demo_marketing(self,mock):
        """科普不自动插入示例门店价格和到店引流要求。"""
        from studio.prompts import DEMO_SHOP_FACTS
        r=self.client.post('/api/tasks',json={'project':'M22','audience':'第一次了解的顾客','question':'M22仪器有什么区别',
                                             'facts':'','bundle_id':self.bundle_id})
        self.assertEqual(r.status_code,200,r.text)
        t=r.json()
        self.assertEqual(t['request']['facts'],'')

    def test_demo_facts_front_back_consistent(self):
        """前端预填与后端兜底必须是同一份示例资料（防止两边漂移）。"""
        from studio.prompts import DEMO_SHOP_FACTS
        js=(Path(__file__).parent/'studio/static/app.js').read_text(encoding='utf-8')
        for line in DEMO_SHOP_FACTS.splitlines():
            if line.strip():
                self.assertIn(line,js,f'示例资料行在前端缺失：{line[:30]}')

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

    def test_vision_model_chain_and_tokens(self):
        """视觉梯队：.env 主模型优先，自动补备用；glm-4v 系 2048、新模型 4096。"""
        with patch.dict(os.environ,{'STUDIO_VISION_MODEL':'glm-4.5v'}):
            self.assertEqual(llm._vision_model_chain(),['glm-4.5v','glm-4v-plus'])
        with patch.dict(os.environ,{'STUDIO_VISION_MODEL':''}):
            self.assertEqual(llm._vision_model_chain()[0],'glm-4.5v')
        with patch.dict(os.environ,{'STUDIO_VISION_MODEL':'glm-4v-plus'}):
            self.assertEqual(llm._vision_model_chain(),['glm-4v-plus','glm-4.5v'])
        self.assertEqual(llm._vision_max_tokens('glm-4v-plus'),2048)
        self.assertEqual(llm._vision_max_tokens('glm-4.5v'),4096)

    def test_vision_tier_fallback_to_backup_model(self):
        """主模型连续输出坏结构时，自动换备用模型并成功。"""
        good=json.dumps({'summary':'备忘录截图科普','original_pages':[{'number':1,'form':'备忘录截图','observation':'文字清单',
                         'ocr_quote':'','borrow':'逐条罗列'}],'borrow':['编号列表'],'missing_information':[],
                         'outline':[{'kind':'text','purpose':'封面提问','instruction':'制作封面','source_pages':[1]}]},ensure_ascii=False)
        bad='{"summary":"x","original_pages":[],"borrow":[],"missing_information":[],"outline":[]}'
        calls=[]
        class _Resp:
            def __init__(self,content):
                self.choices=[type('C',(),{'message':type('M',(),{'content':content})()})()]
                self.usage=type('U',(),{'prompt_tokens':10,'completion_tokens':5})()
        class _Comp:
            def create(self,**kw):
                calls.append((kw.get('model'),kw.get('max_tokens')))
                return _Resp(good if kw.get('model')=='glm-4.5v' else bad)
        class _Client:
            def __init__(self,**kw):self.chat=type('Chat',(),{'completions':_Comp()})()
        big=io.BytesIO();Image.new('RGB',(800,1000),'#3a6ea5').save(big,format='PNG');big=big.getvalue()
        with patch.dict(os.environ,{'VISION_PROVIDER':'glm','VISION_API_KEY':'test-key',
                                    'STUDIO_VISION_MODEL':'glm-4v-plus'}),\
             patch('openai.OpenAI',_Client):
            parsed,trace=llm.generate_vision(AnalysisCompact,{'q':1},[],[{'number':1,'data':big}])
        self.assertEqual(parsed.summary,'备忘录截图科普')
        models_called=[m for m,_ in calls]
        self.assertEqual(models_called,['glm-4v-plus','glm-4v-plus','glm-4.5v'])  # 主模型 parse+自纠 → 备用接替
        self.assertEqual([a['provider'] for a in trace['attempts']][0],'glm-vision/glm-4v-plus')
        self.assertEqual(trace['vision_model'],'glm-4.5v')
        self.assertEqual(calls[0][1],2048)   # glm-4v 系输出上限 2048
        self.assertEqual(calls[-1][1],4096)  # 新模型放宽到 4096

    def test_eval_harness_offline_run_and_report(self):
        """评测器离线跑通：mock 模型下两道题全成功，报告与状态口径正确。"""
        from studio import evals
        questions = [{'id': 'q01', 'question': 'M22仪器有什么区别', 'audience': '第一次了解的顾客'},
                     {'id': 'q02', 'question': '做完M22怎么护理', 'audience': '第一次了解的顾客'}]
        with patch('studio.llm.generate', side_effect=fake_generate):
            results = evals.run_suite(api, questions, os.environ['STUDIO_ACCESS_TOKEN'],generation_mode='template')
        self.assertEqual([r['status'] for r in results], ['success', 'success'])
        report, summary = evals.write_report(results, api.DATA / 'evals', label='离线验证')
        self.assertEqual(summary['total'], 2)
        self.assertEqual(summary['bad_case_rate'], 0.0)
        self.assertTrue(report.exists())

    def test_eval_classify_tags(self):
        """三级标签：合同拒收/超长/降级/占位清洗各归其位。"""
        from studio import evals
        # 1) 模型调用失败带 1210 → token_budget
        err = ValueError("Error code: 400 - {'error': {'code': '1210', 'message': '... 16384 ...'}}")
        status, l1, l2, l3, _ = evals.classify({}, {'retrieval': True, 'analyze': False}, error=err)
        self.assertEqual(status, 'bad_case');self.assertEqual(l1, 'analyze')
        self.assertIn('token_budget', l3)
        # 2) 视觉降级 → success_degraded + degraded_vision
        task = {'case': {'title': 'x'}, 'analysis_basis': '视觉轨未完成，已自动降级按OCR+正文拆解', 'failures': []}
        status, _, l2, l3, _ = evals.classify(task, {'retrieval': True, 'analyze': True, 'draft': True, 'make_page': True})
        self.assertEqual(status, 'success_degraded');self.assertIn('degraded_vision', l2)
        # 3) 大纲自动压缩 → page_count_drift；占位清洗 → placeholder_echo
        task = {'case': {'title': 'x'}, 'analysis_basis': '原图+OCR+正文',
                'analysis_polish': ['已删除占位页：x', '大纲 6 页超出原帖 2 页±1，已自动压缩为 3 页'], 'failures': []}
        status, _, l2, _, _ = evals.classify(task, {'retrieval': True, 'analyze': True, 'draft': True, 'make_page': True})
        self.assertEqual(status, 'success_degraded')
        self.assertIn('placeholder_echo', l2);self.assertIn('page_count_drift', l2)
        # 4) 无匹配案例 → data_quality
        status, l1, l2, l3, _ = evals.classify({'case': None}, {'retrieval': False})
        self.assertEqual(status, 'bad_case');self.assertIn('data_quality', l3)

    def test_knowledge_hashing_embed(self):
        """离线词法向量：同文=1，共享二元组得分更高，零向量=0；默认后端不调任何 API。"""
        from studio import knowledge as kb
        v1, = kb._hashing_embed(['光子嫩肤术后防晒SPF30'])
        v2, = kb._hashing_embed(['光子嫩肤术后防晒SPF30'])
        v3, = kb._hashing_embed(['光子嫩肤术后防晒'])
        self.assertAlmostEqual(kb.cosine(v1, v2), 1.0)
        self.assertGreater(kb.cosine(v1, v3), 0.5)   # 共享前缀二元组，明显相关
        z, = kb._hashing_embed([''])
        self.assertEqual(kb.cosine(z, v1), 0.0)

    def test_knowledge_chunk_and_store(self):
        """知识库 v1：切片带重叠、存储读写往返、余弦检索排序正确。"""
        from studio import knowledge as kb
        # 切片：长文本切成多块，块间有重叠，块长不超上限
        chunks = kb.chunk_text('字' * 1200)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(c['text']) <= kb.DEFAULT_CHUNK_CHARS for c in chunks))
        self.assertEqual(chunks[1]['text'][:kb.DEFAULT_CHUNK_OVERLAP],
                         chunks[0]['text'][-kb.DEFAULT_CHUNK_OVERLAP:])  # 重叠区一致
        self.assertEqual([c['pos'] for c in chunks], list(range(len(chunks))))
        self.assertEqual(kb.chunk_text('短文本'), [{'text': '短文本', 'pos': 0}])
        self.assertEqual(kb.chunk_text('   '), [])
        with self.assertRaises(ValueError):
            kb.chunk_text('x' * 100, size=50, overlap=50)
        # 余弦：同向=1，正交=0
        self.assertAlmostEqual(kb.cosine([1, 0], [2, 0]), 1.0)
        self.assertAlmostEqual(kb.cosine([1, 0], [0, 3]), 0.0)
        # 存储读写往返 + 检索排序
        store = kb.KnowledgeStore()
        store.add([{'text': '关于价格', 'pos': 0}, {'text': '关于护理', 'pos': 0}],
                  [[1.0, 0.0], [0.0, 1.0]], source='测试文档')
        self.assertEqual(len(store), 2)
        store_dir = Path(api.DATA) / 'kb-test'
        store.save(store_dir)
        loaded = kb.KnowledgeStore.load(store_dir)
        hits = loaded.search([1.0, 0.0], top_k=2)
        self.assertEqual(hits[0]['text'], '关于价格')
        self.assertEqual(hits[0]['meta']['source'], '测试文档')
        self.assertEqual(hits[1]['text'], '关于护理')
        shutil.rmtree(store_dir, ignore_errors=True)

    def test_knowledge_build_from_files(self):
        """从文件建库：切片数与来源归属正确（向量化打桩）。"""
        from studio import knowledge as kb
        src = Path(api.DATA) / 'kb-src'
        src.mkdir(parents=True, exist_ok=True)
        (src / 'a.md').write_text('甲' * 1200, encoding='utf-8')
        (src / 'b.md').write_text('乙' * 600, encoding='utf-8')
        fake_vectors = [[float(len(t)), 1.0] for t in []]  # 占位，真正打桩见下
        with patch.object(kb, 'embed_texts', side_effect=lambda texts: [[float(len(t)), 1.0] for t in texts]):
            store, report = kb.build_from_files([src / 'a.md', src / 'b.md'], src / 'store')
        self.assertEqual(report['files'], {'a.md': 3, 'b.md': 2})
        self.assertEqual(report['total_chunks'], 5)
        self.assertEqual(len(store), 5)
        hits = store.search([float(kb.DEFAULT_CHUNK_CHARS), 1.0], top_k=5)
        self.assertTrue(all(h['meta']['source'] in ('a.md', 'b.md') for h in hits))
        shutil.rmtree(src, ignore_errors=True)

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_draft_retry_on_page_count_mismatch(self,mock):
        """真机基线 bad case 修复：草稿页数与大纲不一致时自动重试一次并成功。"""
        t=self.create()
        t=self.post(t,'/analysis-stage',stage='retrieval',decision='accept')
        t=self.post(t,'/analyze')
        t=self.post(t,'/confirm-analysis',analysis=t['analysis'])
        calls={'draft':0}
        def flaky_generate(schema,instruction,sources,images=None,outline_anchor=None):
            result,trace=fake_generate(schema,instruction,sources,images)
            if schema is Draft:
                calls['draft']+=1
                if calls['draft']==1:
                    result=result.model_copy(update={'pages':result.pages[:1]})  # 第一次少给页
            return result,trace
        with patch('studio.llm.generate',side_effect=flaky_generate):
            t=self.post(t,'/draft')
        self.assertEqual(calls['draft'],2)
        self.assertEqual(len(t['draft']['pages']),len(t['confirmed_analysis']['outline']))
        # 重试动作写进了草稿日志
        with api.db() as conn:
            self.assertIn('runlog',json.loads(conn.execute('SELECT body FROM tasks WHERE id=?',(t['id'],)).fetchone()[0]))
        log=(api.DATA/'runlogs'/json.loads(json.dumps(t.get('runlog')))).read_text(encoding='utf-8') if t.get('runlog') else ''
        if log:
            self.assertIn('已自动重试',log)

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_render_separates_production_notes_and_keeps_editable_source(self,mock):
        task=self.ready()
        text='先把自己的咨询问题整理好。\n\n实拍建议：拍摄前台，不出现顾客信息。'
        task=self.post(task,'/pages/1',title='咨询前先准备',text=text,confirmed=True,card_theme='soft')
        self.assertEqual(task['draft']['pages'][0]['text'],text)
        meta=task['renders']['1']
        self.assertEqual(meta['layout_version'],'xhs-editorial-v1')
        self.assertEqual(meta['public_text'],'先把自己的咨询问题整理好。')
        self.assertEqual(len(meta['production_notes']),1)
        response=self.client.get('/api/tasks/'+task['id']+'/pages/1/render')
        self.assertEqual(response.status_code,200)
        self.assertEqual(Image.open(io.BytesIO(response.content)).size,(1080,1440))

    def test_render_themed_fits_max_text(self):
        """真机基线 bad case 修复：上限文本(700字+标题)在新版式容量下不再溢出。"""
        title='第一次了解M22的顾客最关心的问题与解答'
        text=('术后当天会有轻微泛红和 Pun 热感，属于正常反应。' * 16)[:700]
        for theme in ('minimal','soft','duotone'):
            data,meta=rendering.render_themed(title,text,theme,page=1,total_pages=2)
            self.assertEqual(meta['width'],1080)
        # 仍然拒绝明显超量的文字
        with self.assertRaises(ValueError):
            rendering.render_themed(title,'超' * 2000,'minimal')

    def test_kb_source_rag_in_facts(self):
        """第4步事实资料的 RAG：知识库存在时 sources_for 注入 KB 检索片段。"""
        from studio import knowledge as kb
        store_dir = Path(api.DATA) / 'knowledge_base' / 'store'
        store = kb.KnowledgeStore()
        store.add([{'text': 'KB片段：光子嫩肤术后需SPF30防晒', 'pos': 0},
                   {'text': 'KB片段：515nm改善浅表色斑', 'pos': 0}],
                  [[1.0, 0.0], [0.0, 1.0]],
                  source=json.dumps({'file': 't.md', 'category': '测试', 'source_line': '来源: 测试'}, ensure_ascii=False))
        store.save(store_dir)
        self.addCleanup(shutil.rmtree, store_dir.parent, ignore_errors=True)
        self.addCleanup(api._KB_SEARCH_CACHE.clear)
        task = {'request': {'question': 'kb-test-唯一问题-防晒', 'project': 'M22', 'facts': ''}, 'case': {'id': 'x'}}
        with patch('studio.knowledge.embed_texts', side_effect=lambda texts: [[1.0, 0.0] for _ in texts]):
            sources = api.sources_for(task)
        kb_sources = [s for s in sources if s['id'] == 'KB']
        self.assertEqual(len(kb_sources), 1)
        self.assertIn('SPF30', kb_sources[0]['content'][0])
        self.assertIn('未经独立核实', kb_sources[0]['type'])

    def test_build_kb_pipeline_mocked(self):
        """建库流水线：分类+切片+落库（embedding 打桩），meta 携带类别与来源。"""
        from studio import build_kb
        corpus = Path(api.DATA) / 'kb-build-src'
        corpus.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, corpus, ignore_errors=True)
        (corpus / 'x.md').write_text('来源: 测试来源\n\n# 标题\n\n正文' + '内容' * 300, encoding='utf-8')

        def fake_class(schema, instruction, sources, images=None, outline_anchor=None):
            return build_kb.DocClass(category='测试类', summary='摘要', keywords=['k1']), {'elapsed_ms': 1}

        with patch('studio.llm.generate', side_effect=fake_class), \
             patch('studio.build_kb.embed_texts', side_effect=lambda texts: [[float(len(t)), 0.0] for t in texts]):
            store, classes = build_kb.build(str(corpus), str(corpus / 'store'))
        self.assertEqual(classes['x.md']['category'], '测试类')
        self.assertGreater(len(store), 0)
        entry_meta = store.meta[0]['meta']
        info = json.loads(entry_meta['source']) if isinstance(entry_meta['source'], str) else entry_meta['source']
        self.assertEqual(info['category'], '测试类')
        self.assertIn('来源: 测试来源', info['source_line'])
        self.assertTrue((corpus / 'store' / 'meta.json').exists())

    def test_vision_breaker_opens_and_resets(self):
        """视觉轨熔断器：连续失败3次后跳过视觉轨直走文字轨；用户退回重做时复位再试。"""
        t=self.create()
        self.addCleanup(lambda: api._VISION_BREAKER.update(fails=0))
        with patch.dict(os.environ,{'VISION_PROVIDER':'glm','VISION_API_KEY':'test-key'}):
            with patch('studio.llm.generate_vision', side_effect=RuntimeError('视觉失败')):
                t=self.post(t,'/analyze')
                t=self.post(t,'/analyze')
            self.assertEqual(api._VISION_BREAKER['fails'],2)
            with patch('studio.llm.generate_vision', side_effect=RuntimeError('视觉失败')) as mv:
                t=self.post(t,'/analyze')
                mv.assert_not_called()                      # 熔断打开：不再调用视觉轨
            self.assertEqual(api._VISION_BREAKER['fails'],3)
            self.assertIn('熔断',t['analysis_basis'])
            # 用户退回重做 = 明确要求再试：先让前置步骤处于已确认，退回 visual 时熔断复位、视觉轨恢复尝试
            t=self.post(t,'/analysis-stage',stage='retrieval',decision='accept')
            t=self.post(t,'/analysis-stage',stage='language',decision='accept')
            t=self.post(t,'/analysis-stage',stage='facts',decision='accept')
            with patch('studio.llm.generate_vision', side_effect=RuntimeError('重做再试')) as mv:
                r=self.client.post('/api/tasks/'+t['id']+'/analysis-stage',
                                   json={'revision':t['revision'],'stage':'visual','decision':'reject',
                                         'feedback':'再给视觉轨一次机会'})
                self.assertEqual(r.status_code,200,r.text)
                mv.assert_called()                          # 熔断复位：视觉轨恢复尝试（仍失败则重新计数）
            t=r.json()
            self.assertEqual(api._VISION_BREAKER['fails'],1)

    def test_launcher_netstat_parsing(self):
        import run_studio
        sample='\r\n'.join([
            '  协议  本地地址          外部地址        状态           PID',
            '  TCP    127.0.0.1:8010         0.0.0.0:0              LISTENING       8744',
            '  TCP    127.0.0.1:8011         0.0.0.0:0              LISTENING       9999',
            '  TCP    192.168.1.5:139        0.0.0.0:0              LISTENING       4'])
        self.assertEqual(run_studio._parse_listener_pid(sample,8010),8744)
        self.assertEqual(run_studio._parse_listener_pid(sample,8011),9999)
        self.assertIsNone(run_studio._parse_listener_pid(sample,9999))
        self.assertIsNone(run_studio._parse_listener_pid('',8010))

    def test_strip_title_echo(self):
        """草稿正文开头复述标题（含拆成多行）时自动去除；正常内容不动。"""
        f=api._strip_title_echo
        # 用户真机案例：标题被拆成两行复述（"第一次了解 M22"+"先弄清这几个问题"）
        cleaned,changed=f('第一次了解M22，先弄清这几个问题','第一次了解 M22\n先弄清这几个问题\n\n· 是哪台机器？')
        self.assertTrue(changed);self.assertEqual(cleaned,'· 是哪台机器？')
        # 单行复述
        cleaned,changed=f('咨询清单','咨询清单\n先记录问题')
        self.assertTrue(changed);self.assertEqual(cleaned,'先记录问题')
        # 无复述：内容不动
        cleaned,changed=f('咨询清单','先记录问题，再核对出处')
        self.assertFalse(changed);self.assertEqual(cleaned,'先记录问题，再核对出处')
        # 正文只是包含标题字样但不在开头：不动
        cleaned,changed=f('咨询清单','关于咨询清单的说明\n先记录问题')
        self.assertFalse(changed)
        # 空标题/空正文
        self.assertEqual(f('', '内容')[1],False);self.assertEqual(f('标题','')[1],False)

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_draft_generation_strips_title_echo(self,mock):
        """草稿生成时的确定性去重：假模型复述标题，保存的草稿应已清理。"""
        def echoing_generate(schema,instruction,sources,images=None,outline_anchor=None):
            result,trace=fake_generate(schema,instruction,sources,images)
            if schema is Draft:
                for p in result.pages:
                    p.text=p.title+'\n'+p.text
            return result,trace
        with patch('studio.llm.generate',side_effect=echoing_generate):
            t=self.ready()
        for p in t['draft']['pages']:
            self.assertFalse(p['text'].startswith(p['title']))
        self.assertIn(t['draft']['pages'][0]['text'][:6],t['draft']['pages'][0]['text'])

    @patch('studio.llm.generate',side_effect=fake_generate)
    def test_reader_workflow_call_order_and_content_review_cache(self,mock):
        task=self.ready()
        names=[call.args[0] for call in mock.call_args_list]
        self.assertLess(names.index(EditorialPlan),names.index(Analysis))
        self.assertLess(names.index(Analysis),names.index(QuestionOutline))
        self.assertLess(names.index(QuestionOutline),names.index(Draft))
        self.assertLess(names.index(Draft),names.index(DraftContentReview))
        def count():return sum(call.args[0] is DraftContentReview for call in mock.call_args_list)
        self.assertEqual(count(),1)
        page=task['draft']['pages'][0]
        task=self.post(task,'/pages/1',title=page['title'],text=page['text'],confirmed=True)
        self.assertEqual(count(),1)  # Same copy reuses the accepted review.
        task=self.post(task,'/pages/1',title=page['title'],text='修改后的科普文字',confirmed=True)
        self.assertEqual(count(),2)

    def test_reader_pagination_does_not_compress_to_reference_length(self):
        def five_pages(schema,instruction,sources,images=None,outline_anchor=None):
            output,trace=fake_generate(schema,instruction,sources,images,outline_anchor)
            if schema is QuestionOutline:
                seed=output.pages[0]
                output.pages=[seed.model_copy(update={'purpose':f'知识点{i}','reader_question':f'读者问题{i}？'}) for i in range(5)]
            return output,trace
        with patch('studio.llm.generate',side_effect=five_pages):task=self.ready()
        self.assertEqual(len(task['case']['pages']),1)
        self.assertEqual(len(task['analysis']['outline']),5)
        self.assertEqual(len(task['draft']['pages']),5)
        self.assertNotIn('压缩',json.dumps(task.get('analysis_polish',[]),ensure_ascii=False))

    def test_content_rejection_prevents_image_calls_and_preserves_old_result(self):
        with patch('studio.llm.generate',side_effect=fake_generate):
            task=self.ready();page=task['draft']['pages'][0]
            task=self.post(task,'/pages/1',title=page['title'],text=page['text'],confirmed=True)
        old=copy.deepcopy(task['renders']['1'])
        def reject(schema,instruction,sources,images=None,outline_anchor=None):
            output,trace=fake_generate(schema,instruction,sources,images,outline_anchor)
            if schema is DraftContentReview:
                output.readable=False;output.pages[0].passed=False
                output.pages[0].issues=['同一页堆了多个不相关术语']
                output.pages[0].suggestions=['只解释本页问题，其他概念后移']
            return output,trace
        with patch('studio.llm.generate',side_effect=reject),patch('studio.seedream_card.generate') as image:
            response=self.client.post(f"/api/tasks/{task['id']}/pages/1",json={'revision':task['revision'],
                'title':page['title'],'text':'需要检查的新文案','confirmed':True,'generation_mode':'seedream'})
        self.assertEqual(response.status_code,422,response.text);image.assert_not_called()
        saved=api.get_task(task['id'],True)
        self.assertEqual(saved['renders']['1'],old)
        self.assertEqual(saved['draft']['pages'][0]['text'],page['text'])
        self.assertEqual(saved['content_review_candidate']['text'],'需要检查的新文案')

    def test_failed_content_review_has_only_one_automatic_copy_revision(self):
        def reject(schema,instruction,sources,images=None,outline_anchor=None):
            output,trace=fake_generate(schema,instruction,sources,images,outline_anchor)
            if schema is DraftContentReview:
                output.readable=False;output.issues=['入门文案术语过密']
            return output,trace
        with patch('studio.llm.generate',side_effect=reject) as model:
            task=self.ready()
        self.assertFalse(task['draft_content_review']['passed'])
        self.assertEqual(sum(c.args[0] is Draft for c in model.call_args_list),2)
        self.assertFalse(task['renders'])

    def test_audience_brief_survives_draft_save_without_becoming_public_copy(self):
        brief={'reader':'正在了解M22的普通读者','questions':['不同模块各有什么分工？'],
               'approach':'用三个具体小标题逐点介绍','defer_topics':['不相关的版本参数']}
        def audience_generate(schema,instruction,sources,images=None,outline_anchor=None):
            result,trace=fake_generate(schema,instruction,sources,images,outline_anchor)
            if schema is EditorialPlan:
                result=result.model_copy(update={'audience_brief':__import__('studio.models',fromlist=['AudienceBrief']).AudienceBrief.model_validate(brief)})
            if schema is Draft:
                result=Draft.model_validate({**result.model_dump(),'audience_brief':brief})
            return result,trace
        with patch('studio.llm.generate',side_effect=audience_generate):
            task=self.ready()
        with api.db() as conn:
            saved=json.loads(conn.execute('SELECT body FROM tasks WHERE id=?',(task['id'],)).fetchone()[0])
        self.assertEqual(saved['draft']['audience_brief'],brief)
        public_copy=saved['draft']['body']+'\n'+'\n'.join(p['text'] for p in saved['draft']['pages'])
        self.assertNotIn(brief['reader'],public_copy)
        legacy=Draft(title='旧草稿',body='已有正文',pages=[])
        self.assertIsNone(legacy.audience_brief)

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
        # 创建任务时日志文件名必须随任务入库（否则后续事件会另起新文件）
        with api.db() as conn:
            import json as _json
            self.assertIn('runlog',_json.loads(conn.execute('SELECT body FROM tasks WHERE id=?',(t['id'],)).fetchone()[0]))
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
        self.assertEqual(len(trace['attempts']),1)
        self.assertTrue(trace['attempts'][0]['outcome'].endswith('parse_shrunk'))
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
        self.assertEqual(sum(c.args[0] is Analysis for c in mock.call_args_list),2)

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
        self.assertEqual(sum(c.args[0] is Draft for c in mock.call_args_list),1)
        self.assertTrue(any(c.args[0] is DraftContentReview for c in mock.call_args_list))

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
        self.assertIsNone(ImageChops.difference(original,rendered.crop((t['renders']['2'].get('photo_offset_x',0),offset,t['renders']['2'].get('photo_offset_x',0)+320,offset+240))).getbbox())
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
        self.assertEqual(r.status_code,502);self.assertNotIn('secret-value',r.text);self.assertEqual(mock.call_count,3)
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
