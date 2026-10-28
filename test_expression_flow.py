import copy,io,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import test_studio
from fastapi.testclient import TestClient
from studio import api,cases,editorial,expression,llm,rendering
from studio.models import ExpressionStudy,MaterialSheet,DraftContentReview,ExpressionCheck,ExpressionDraftReview,SharingDraftReview,SharingExpressionCheck,ToneDraftReview


def fake_expression(schema,instruction,sources,**kwargs):
    if schema is ExpressionStudy:
        sample=instruction['samples'][0]
        result=schema(audience='刚了解M22的普通读者',opening='先给读者一个直观介绍',structure=['先介绍对象','按相同字段比较特点'],
            tone='自然具体，像给朋友介绍',sentence_pattern='具体小标题加两句短解释',presentation='按同一字段分点介绍；图片布局是建议',
            good_example='先认识这台设备，再看不同部分各自的分工。',bad_example='先分四层，接下来背定义。',
            knowledge_needs=['M22是什么','不同手具是什么关系'],
            evidence=[{'sample_id':sample['sample_id'],'quote':sample['title'],'lesson':'使用明确的对比介绍方向'}])
    elif schema is MaterialSheet:
        source=next(s for s in sources if s['id']=='K1')
        result=schema(items=[{'need':'M22是什么','answer':'测试资料支持的设备介绍','supports':[{'source_id':'K1','quote':source['content'][:40]}]}])
    else:
        result,trace=test_studio.fake_generate(DraftContentReview if schema in (ExpressionDraftReview,SharingDraftReview,ToneDraftReview) else schema,instruction,sources,**kwargs)
        if schema in (DraftContentReview,ExpressionDraftReview,SharingDraftReview,ToneDraftReview):
            result.expression_check=(SharingExpressionCheck(sharing_voice=True,draft_quotes=[instruction["draft"]["pages"][0]["text"][:200]],purpose_kept=True,structure_kept=True,tone_kept=True,issues=[],summary='保持分享表达') if schema is SharingDraftReview else ExpressionCheck(purpose_kept=True,structure_kept=True,tone_kept=True,issues=[],summary='保持原定表达'))
            data=result.model_dump(serialize_as_any=True)
            if schema is ToneDraftReview:
                data['tone_check']={'style_id':instruction['writing_style']['id'],'passed':True,'summary':'符合所选标准',
                    'criteria':[{'rule_id':rule['id'],'passed':True,'quote':instruction['draft']['pages'][0]['text'][:200],
                                 'reason':'本段体现该标准'} for rule in instruction['writing_style']['criteria']]}
            result=schema.model_validate(data)
        return result,trace
    return result,{'provider':'offline-test','prompt':json.dumps(instruction,ensure_ascii=False)}


class ExpressionFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.bundles=self.root/'bundles'
        self.bid=cases.install(test_studio.bundle(),self.bundles)['bundle_id']
        for obj,key,value in [(api,'DATA',self.root),(api,'BUNDLES',self.bundles),(llm,'supports_vision',lambda:False)]:
            p=patch.object(obj,key,value);p.start();self.addCleanup(p.stop)
        p=patch.object(llm,'generate',side_effect=fake_expression);self.model=p.start();self.addCleanup(p.stop)
        self.client=TestClient(api.app);self.client.headers['Authorization']='Bearer '+api.TOKEN
        self.task=self.client.post('/api/tasks',json={'project':'M22','question':'M22仪器区别科普','audience':'普通读者',
            'bundle_id':self.bid,'workflow':'expression-first'}).json()
    def post(self,path,**extra):
        r=self.client.post('/api/tasks/'+self.task['id']+path,json={'revision':self.task['revision'],**extra})
        self.assertEqual(r.status_code,200,r.text);self.task=r.json();return self.task
    def prepare(self):
        self.post('/analyze');self.post('/confirm-expression',prompt=self.task['expression']['prompt']);self.post('/prepare-content')
    def test_new_version_preserves_original_and_does_not_call_model(self):
        self.prepare();self.post('/confirm-analysis',analysis=self.task['analysis']);self.post('/draft')
        before=copy.deepcopy(self.task);calls=self.model.call_count
        r=self.client.post('/api/tasks/'+self.task['id']+'/sharing-version',json={'revision':self.task['revision']})
        self.assertEqual(r.status_code,200,r.text)
        version=r.json();self.assertEqual(version['parent_task_id'],before['id'])
        self.assertEqual(version['request']['question'],before['request']['question'])
        self.assertEqual(version['writing_style']['id'],'friend-sharing')
        self.assertIsNone(version['draft']);self.assertEqual(version['renders'],{})
        self.assertEqual(self.model.call_count,calls)
        self.assertEqual(self.client.get('/api/tasks/'+before['id']).json(),before)

    def test_model_approval_does_not_override_known_lecture_copy(self):
        self.prepare();self.post('/confirm-analysis',analysis=self.task['analysis']);self.post('/draft')
        self.task['draft']['pages'][0]['text']='换滤片，本质是换波段，不是按功能按钮，也不是叠加效果。'
        def approves(task,schema,instruction):
            result,_=fake_expression(schema,instruction,api.sources_for(task))
            return result
        record=editorial.review(self.task,self.task['draft'],approves)
        self.assertFalse(record['passed'])
        self.assertFalse(record['expression_check']['sharing_voice'])
        self.assertTrue(any('连续否定' in s for s in record['issues']))

    def test_neutral_voice_cannot_pass_friend_sharing_review(self):
        self.prepare();self.post('/confirm-analysis',analysis=self.task['analysis']);self.post('/draft')
        self.task['draft']['body']+='修改用于重审'
        def neutral(task,schema,instruction):
            self.assertIn(schema,(SharingDraftReview,ToneDraftReview))
            result,_=fake_expression(schema,instruction,api.sources_for(task))
            if schema is ToneDraftReview:
                result.tone_check.passed=False;result.tone_check.criteria[0].passed=False
            else:result.expression_check.sharing_voice=False
            return result
        record=editorial.review(self.task,self.task['draft'],neutral)
        self.assertFalse(record['passed'])
        self.assertTrue(record['expression_check']['tone_kept'])
        self.assertFalse(record['expression_check']['sharing_voice'])
        self.assertTrue(any('分享口吻' in s or 'friend-sharing.1' in s for s in record['issues']))

    def test_quote_ids_resolve_to_original_text(self):
        def quoted(schema,instruction,sources,**kwargs):
            result,trace=fake_expression(schema,instruction,sources,**kwargs)
            if schema is ExpressionStudy:
                option=instruction['quote_options'][0]
                result.evidence[0].sample_id=option['sample_id']
                result.evidence[0].quote_id=option['quote_id']
                result.evidence[0].quote=''
            elif schema is MaterialSheet:
                option=next(q for q in instruction['quote_options'] if q['source_id']=='K1')
                result.items[0].supports[0].quote_id=option['quote_id']
                result.items[0].supports[0].quote=''
            return result,trace
        with patch.object(llm,'generate',side_effect=quoted):self.prepare()
        self.assertTrue(self.task['expression']['plan']['evidence'][0]['quote'])
        self.assertTrue(self.task['material_sheet']['items'][0]['supports'][0]['quote'])

    def test_visual_expression_schema_has_no_legacy_page_contract(self):
        from types import SimpleNamespace
        rows=[{'sample_id':'MAIN','title':'M22仪器对比','body':'','ocr':'M22仪器对比','url':'https://www.xiaohongshu.com/explore/test'}]
        result,_=fake_expression(ExpressionStudy,{'samples':rows},[])
        response=SimpleNamespace(usage=None,choices=[SimpleNamespace(message=SimpleNamespace(content=result.model_dump_json()))])
        config={'provider':'ark','base_url':'https://example.invalid','api_key':'offline-test','model':'offline-vision'}
        instruction={'samples':rows,'padding':'测'*19000,'quote_options':[{'quote_id':'MAIN-Q1','quote':'M22仪器对比'}]}
        with patch.dict('os.environ',{'VISION_PROVIDER':'glm'}),patch.object(llm,'analysis_vision_config',return_value=config),patch('openai.OpenAI') as client:
            client.return_value.chat.completions.create.return_value=response
            _,trace=llm.generate_vision(ExpressionStudy,instruction,[],[{'number':1,'data':test_studio.picture()}])
        self.assertNotIn('original_pages数组必须',trace['prompt'])
        self.assertIn('MAIN-Q1',trace['prompt'])

    def test_no_knowledge_retrieval_before_expression_confirmation(self):
        with patch.object(api,'kb_source',side_effect=AssertionError('retrieved too early')):
            self.post('/analyze')
        self.assertIsNone(self.task['analysis'])
        self.assertEqual(self.task['expression']['status'],'proposed')
        self.assertFalse((self.root/'expression_skills').exists())
        r=self.client.post('/api/tasks/'+self.task['id']+'/prepare-content',json={'revision':self.task['revision']})
        self.assertEqual(r.status_code,409)
    def test_confirmed_prompt_persists_retrieval_and_outline_follow_it(self):
        self.prepare()
        e=self.task['expression'];self.assertEqual(e['status'],'accepted')
        saved=self.root/'expression_skills'/e['hash']/'SKILL.md';self.assertEqual(saved.read_text(encoding='utf-8'),e['prompt'])
        self.assertEqual(self.task['material_sheet']['items'][0]['need'],'M22是什么')
        calls=self.model.call_args_list
        materials=next(c for c in calls if c.args[0] is MaterialSheet)
        self.assertTrue(all(s['id'] not in ('CASE','GUIDE','INTENT','KB') for s in materials.args[2]))
        self.assertEqual(materials.args[1]['confirmed_expression']['hash'],e['hash'])
        self.assertNotIn('samples',materials.args[1]['confirmed_expression'])
        self.assertNotIn('research_brief',materials.args[1])
        r=self.client.get('/api/tasks/'+self.task['id']+'/expression-skill');self.assertEqual(r.text,e['prompt'])
        self.post('/confirm-analysis',analysis=self.task['analysis']);self.post('/draft')
        self.assertTrue(self.task['draft_content_review']['expression_check']['tone_kept'])
        output=rendering.export_zip(self.task,[])
        with zipfile.ZipFile(io.BytesIO(output)) as z:self.assertIn('SKILL.md',z.namelist());self.assertIn('本篇资料单.json',z.namelist())
    def test_old_stage_bypass_rejected(self):
        r=self.client.post('/api/tasks/'+self.task['id']+'/analysis-stage',json={'revision':0,'stage':'retrieval','decision':'accept'})
        self.assertEqual(r.status_code,409)
    def test_bad_expression_quote_rejected_without_replacing_state(self):
        def wrong(*args,**kwargs):
            result,trace=fake_expression(*args,**kwargs)
            if args[0] is ExpressionStudy:result.evidence[0].quote='不存在的样本原文'
            return result,trace
        with patch.object(llm,'generate',side_effect=wrong):
            r=self.client.post('/api/tasks/'+self.task['id']+'/analyze',json={'revision':0})
        self.assertEqual(r.status_code,422)
        stored=self.client.get('/api/tasks/'+self.task['id']).json();self.assertNotIn('expression',stored)
    def test_tone_drift_blocks_generation_and_cache_invalidates(self):
        self.prepare();self.post('/confirm-analysis',analysis=self.task['analysis']);self.post('/draft')
        original=self.task['expression']['prompt']
        self.task['expression']['prompt']+='\n保持清晰对比，不改成定义课。'
        def drift(task,schema,instruction):
            result,trace=fake_expression(schema,instruction,api.sources_for(task))
            result.expression_check.tone_kept=False;result.expression_check.issues=['改成了说明书语气']
            return result
        record=editorial.review(self.task,self.task['draft'],drift)
        self.assertFalse(record['passed']);self.assertIn('改成了说明书语气',record['issues'])
        self.assertNotEqual(original,self.task['expression']['prompt'])
    def test_explicit_redo_invalidates_downstream_before_retrieval(self):
        self.prepare()
        with patch.object(api,'kb_source',side_effect=AssertionError('redo retrieved facts')):
            self.post('/expression-study?feedback=语气再自然一点')
        self.assertIsNone(self.task['analysis']);self.assertNotIn('material_sheet',self.task)
        self.assertEqual(self.task['expression']['status'],'proposed');self.assertTrue(self.task['expression_history'])

if __name__=='__main__':unittest.main()
