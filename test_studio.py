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
os.environ['STUDIO_ACCESS_TOKEN']='test-only-access-key-not-for-production'
from fastapi.testclient import TestClient
from PIL import Image,ImageChops
from studio import api,cases,rendering
from studio.models import Analysis,Draft,FeedbackAnalysis,CaseRanking


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


def fake_generate(schema,instruction,sources,images=None):
    if schema is Analysis:
        c=next(s['content'] for s in sources if s['id']=='CASE')
        result=Analysis(summary='原帖用固定字段比较，新内容借鉴组织顺序。',
            original_pages=[{'number':p['number'],'form':'仅按OCR推测为对比文字','observation':'有对比问句',
                             'ocr_quote':p['ocr'][:8],'borrow':'固定比较维度','uncertainty':'布局需对照原图'} for p in c['pages']],
            borrow=['从同一问题展开'],missing_information=[],
            outline=[{'kind':'text','purpose':'封面问题','instruction':'制作文字封面','source_pages':[1]},
                     {'kind':'text','purpose':'三个确认问题','instruction':'制作问题清单','source_pages':[1]}])
    elif schema is Draft:
        result=Draft(title='第一次了解M22，先确认这些信息',body='先确认设备名称，再核对资料出处。',
            pages=[{'number':i+1,'title':'了解M22' if i==0 else '先确认的信息','text':'名称、资料与咨询问题。',
                    'source_ids':['SHOP'],'pending':[]} for i,_ in enumerate(instruction['outline'])],missing_information=[])
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
        t=self.create('咖啡拉花课程');self.assertEqual(t['stage'],'no_match');self.assertIsNone(t['case'])
        r=self.client.post('/api/tasks/'+t['id']+'/analyze',json={'revision':0});self.assertEqual(r.status_code,409)

    def test_combine_ranking_prefers_relevance(self):
        pool=[{'id':'a','likes':2000},{'id':'b','likes':100},{'id':'c','likes':500},{'id':'d','likes':900}]
        ranked=cases.combine_ranking(pool,{'a':4,'b':9,'c':8,'d':3})
        self.assertEqual([r['case']['id'] for r in ranked],['b','c','a'])

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
        self.assertEqual(t['assets']['2']['sha256'],hashlib.sha256(picture()).hexdigest())
        t=self.make_all(t)
        raw=self.client.get('/api/tasks/'+t['id']+'/pages/2/render').content
        rendered=Image.open(io.BytesIO(raw));offset=t['renders']['2']['photo_offset_y']
        original=Image.open(io.BytesIO(picture())).convert('RGB')
        self.assertIsNone(ImageChops.difference(original,rendered.crop((0,offset,320,offset+240))).getbbox())

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
        def pending(schema,instruction,sources,images=None):
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
