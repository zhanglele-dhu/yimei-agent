import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from studio import semantic


class SemanticTests(unittest.TestCase):
    def test_requested_page_count_overrides_reference_anchor(self):
        from studio import prompts
        self.assertIn('必须恰好4页',prompts.analyze_instruction(1,4))

    def notes(self):
        def note(i,title,likes):return {'id':i,'title':title,'body':'','likes':likes,'url':'https://www.xiaohongshu.com/explore/'+i,'pages':[{'ocr':title}]}
        return {'bundle_id':'a'*24,'cases':[note('science','M22基础科普与原理',80),note('consult','M22到店咨询流程',9999),note('care','M22术后护理',1000),note('other','水光科普',2000),note('contrast','M22仪器区别',200)]}

    def test_content_intent_filters_high_like_wrong_direction(self):
        manifest=self.notes()
        with tempfile.TemporaryDirectory() as root:
            data=semantic.catalog(root,manifest)
        intent=semantic.infer_rules('做M22知识科普，不写到店咨询')
        self.assertEqual({c['id'] for c in semantic.match_pool(manifest,intent,data)},{'science','contrast'})
        intent=semantic.infer_rules('光子嫩肤术后护理')
        self.assertEqual([c['id'] for c in semantic.match_pool(manifest,intent,data)],['care'])

    def test_model_intent_is_normalized_without_optional_clarification_blocking(self):
        result=semantic.CreationIntent(project='光子嫩肤',content_type='科普',goal='解释知识',must_cover=['原理'],clarification='型号可稍后补充')
        with patch('studio.llm.generate',return_value=(result,{'provider':'test','model':'test-model'})):
            parsed,trace=semantic.understand('M22科普')
        self.assertEqual(parsed.project,'M22/光子嫩肤')
        self.assertEqual(parsed.clarification,'')
        self.assertEqual(trace['method'],'model')

    def test_unavailable_model_has_visible_rule_fallback_and_no_secret_error(self):
        with patch('studio.llm.generate',side_effect=RuntimeError('secret-should-not-be-shown')):
            result,trace=semantic.understand('我想做光子术后护理')
        self.assertEqual(result.content_type,'术后护理')
        self.assertEqual(trace['method'],'rules')
        self.assertNotIn('secret',str(trace))

    def test_semantic_index_preserves_raw_data_and_requires_complete_ids(self):
        manifest=self.notes();before=copy.deepcopy(manifest)
        labels=semantic.CaseLabels(items=[semantic.CaseLabel(case_id='science',project='M22',content_type='科普',topics=[],summary='知识')])
        with tempfile.TemporaryDirectory() as root,patch('studio.llm.generate',return_value=(labels,{})):
            data=semantic.enrich(root,manifest)
            self.assertEqual(data['model_classified'],0)
            self.assertEqual(len(data['errors']),1)
        self.assertEqual(manifest,before)

    def test_valid_model_labels_are_persisted_with_source_identity(self):
        manifest=self.notes();manifest['cases']=manifest['cases'][:1]
        labels=semantic.CaseLabels(items=[semantic.CaseLabel(case_id='science',project='光子嫩肤',content_type='科普',topics=['原理基础'],summary='介绍M22基础知识')])
        with tempfile.TemporaryDirectory() as root,patch('studio.llm.generate',return_value=(labels,{'provider':'test','model':'test-model'})):
            data=semantic.enrich(root,manifest)
            self.assertEqual(data['model_classified'],1)
            item=semantic.catalog(root,manifest)['items'][0]
            self.assertEqual(item['project'],'M22/光子嫩肤')
            self.assertTrue(item['source_sha256'])
            self.assertEqual(item['url'],manifest['cases'][0]['url'])


class SemanticApiTests(unittest.TestCase):
    def setUp(self):
        import test_studio
        self.fixtures=test_studio
        self.fixture=test_studio.StudioTests('test_auth_cache_and_page_contract');self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client=self.fixture.client;self.api=test_studio.api

    @patch('studio.llm.generate')
    def test_intent_endpoint_does_not_create_tasks(self,generate):
        generate.return_value=(semantic.infer_rules('M22科普'),{'provider':'test'})
        before=self.client.get('/api/tasks').json()
        r=self.client.post('/api/intent',json={'text':'M22科普'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['intent']['content_type'],'科普')
        self.assertEqual(self.client.get('/api/tasks').json(),before)

    def test_catalog_filter_and_creation_propagate_intent_without_demo_facts(self):
        r=self.client.get('/api/catalog?content_type=术后护理&bundle_id='+self.fixture.bundle_id)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['matched'],1)
        with patch('studio.llm.generate',side_effect=self.fixtures.fake_generate) as model:
            task=self.client.post('/api/tasks',json={'project':'自动识别','question':'M22科普','audience':'新手','facts':'','bundle_id':self.fixture.bundle_id}).json()
            self.assertTrue(task['case'])
            self.assertEqual(task['request']['facts'],'')
            self.assertEqual(task['intent']['content_type'],'科普')
            r=self.client.post('/api/tasks/'+task['id']+'/analyze',json={'revision':task['revision']})
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(model.call_args.args[1]['creation_intent']['content_type'],'科普')
            sources=model.call_args.args[2]
            self.assertIn('INTENT',[s['id'] for s in sources])
