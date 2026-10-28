import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test_studio
from fastapi.testclient import TestClient
from studio import api, cases, research


def fake_research(schema, instruction, sources, **kwargs):
    if schema is not research.ResearchConclusion:
        return test_studio.fake_generate(schema,instruction,sources,**kwargs)
    sample=instruction['samples'][0]
    result=schema(findings=[{'observation':'样本用对比介绍仪器','sample_id':sample['sample_id'],'quote':sample['title']}],
        audience='刚了解M22的读者',direction='认识M22的仪器区别',reader_question='这些仪器有什么区别？',
        approach='用相同字段分点比较',reason='样本采用对比结构，可借鉴介绍方式',reference_ids=[sample['sample_id']])
    return result, {'provider':'offline-test','model':'mock','prompt':instruction}


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.bundles=self.root/'bundles'
        self.manifest=cases.install(test_studio.bundle(),self.bundles)

    def test_grounded_report_deduplicates_and_caches(self):
        with patch.object(research.llm,'generate',side_effect=fake_research) as model:
            report=research.conclude(self.root,self.bundles)
            again=research.conclude(self.root,self.bundles)
        self.assertEqual(model.call_count,1)
        self.assertTrue(again['cached'])
        self.assertEqual(report['sample_count'],1) # duplicate URLs are one sample
        self.assertIn('未读取评论正文',report['coverage'])
        self.assertTrue(all('肺结节' not in s['title'] for s in report['samples']))
        with patch.object(research,'INSTRUCTION',research.INSTRUCTION+' 新规则'),patch.object(research.llm,'generate',side_effect=fake_research) as model:
            changed=research.conclude(self.root,self.bundles)
        self.assertNotEqual(changed['id'],report['id']);self.assertEqual(model.call_count,1)

    def test_unverifiable_quote_not_saved(self):
        def wrong(*args,**kwargs):
            result,trace=fake_research(*args,**kwargs)
            result.findings[0].quote='评论里大家都想知道'
            return result,trace
        with patch.object(research.llm,'generate',side_effect=wrong):
            with self.assertRaisesRegex(ValueError,'引文'):research.conclude(self.root,self.bundles)
        self.assertFalse((self.root/'research').exists())

    def test_api_auth_empty_and_failure(self):
        client=TestClient(api.app);headers={'Authorization':'Bearer '+api.TOKEN}
        self.assertEqual(client.post('/api/research/m22').status_code,401)
        with patch.object(api,'DATA',self.root),patch.object(api,'BUNDLES',self.root/'empty'),patch.object(research.llm,'generate') as model:
            response=client.post('/api/research/m22',headers=headers)
        self.assertEqual(response.json()['status'],'empty');model.assert_not_called()
        with patch.object(api,'DATA',self.root),patch.object(api,'BUNDLES',self.bundles),patch.object(research.llm,'generate',side_effect=RuntimeError('private provider details')):
            response=client.post('/api/research/m22',headers=headers)
        self.assertEqual(response.status_code,502);self.assertNotIn('private provider',response.text)

    def test_adopted_report_persists_in_task(self):
        client=TestClient(api.app);headers={'Authorization':'Bearer '+api.TOKEN}
        with patch.object(api,'DATA',self.root),patch.object(api,'BUNDLES',self.bundles),patch.object(research.llm,'generate',side_effect=fake_research):
            response=client.post('/api/research/m22',headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            report=response.json();self.assertNotIn('trace',report)
            with api.db() as db:db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, revision INTEGER, body TEXT)')
            response=client.post('/api/tasks',headers=headers,json={'project':'M22','audience':'入门读者','question':'M22仪器区别科普',
                'bundle_id':self.manifest['bundle_id'],'research_id':report['id']})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['research']['id'],report['id'])


if __name__=='__main__':unittest.main()
