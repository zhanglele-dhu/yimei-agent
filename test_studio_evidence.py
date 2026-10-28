import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_studio  # Shared isolated API configuration; never reads production tasks.
from studio import api, evidence, llm, prompts


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.base = self.data / 'knowledge_base/m22'
        evidence.import_seeds(self.base, Path('knowledge/m22_source_seeds.json'))
        evidence.build_library(self.base)
        api._KB_SEARCH_CACHE.clear()
        self.addCleanup(api._KB_SEARCH_CACHE.clear)

    def test_topics_and_eye_discussion_separation(self):
        hits = evidence.search_library(self.base, 'M22是什么 IPL OPT AOPT区别')
        self.assertTrue(any(r['kind'] == 'official' for r in hits))
        self.assertTrue(all(r['kind'] != 'discussion' and r['scope'] != '眼科独立应用' for r in hits))
        filters = evidence.search_library(self.base, 'M22双波滤片波长')
        self.assertIn('M22-CONSENSUS-2024', {r['id'] for r in filters})
        eyes = evidence.search_library(self.base, 'M22干眼眼科注册认证')
        self.assertIn('M22-FDA-DRYEYE', {r['id'] for r in eyes})
        discussion = evidence.search_library(self.base, 'M22论坛医生问答经验')
        self.assertTrue(any(r['kind'] == 'discussion' for r in discussion))

    def test_sources_have_individual_traceable_ids_and_no_shop_claim(self):
        task = {'request': {'project':'M22', 'question':'M22是什么，滤片与OPT的区别', 'facts':''}}
        with patch.object(api, 'DATA', self.data):
            sources = api.sources_for(task)
        records = [s for s in sources if s['id'].startswith('M22-')]
        self.assertGreaterEqual(len(records), 3)
        self.assertEqual(len({s['id'] for s in sources}), len(sources))
        self.assertTrue(all(s['content']['url'].startswith('https://') for s in records))
        self.assertTrue(all('facts' in s['content'] and 'scope' in s['content'] for s in records))

    def test_library_publish_invalidates_query_cache(self):
        task = {'request': {'project':'M22', 'question':'M22滤片', 'facts':''}}
        with patch.object(api, 'DATA', self.data):
            first = api.kb_source(task)
            record_path = self.base / 'cards/M22-CN-AOPT.json'
            record = evidence.read_json(record_path)
            record['facts'].append('索引更新验证标记')
            record_path.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
            evidence.build_library(self.base)
            second = api.kb_source(task)
        self.assertNotEqual(first, second)
        self.assertEqual(len(api._KB_SEARCH_CACHE), 2)

    def test_missing_index_and_unrelated_queries_do_not_block(self):
        (self.base/'manifest.json').write_text('{"store_dir":"missing"}', encoding='utf-8')
        with patch.object(api, 'DATA', self.data):
            self.assertIsNone(api.kb_source({'request':{'project':'M22','question':'M22原理'}}))
            self.assertIsNone(api.kb_source({'request':{'project':'其他','question':'咖啡拉花'}}))

    def test_pending_abstract_cards_are_not_retrieved(self):
        record = copy.deepcopy(evidence.read_json(self.base/'cards/M22-CN-AOPT.json'))
        record.update(id='M22-test-paper', kind='paper', doi='test', abstract_check='pending')
        (self.base/'cards/M22-test-paper.json').write_text(json.dumps(record), encoding='utf-8')
        manifest = evidence.build_library(self.base)
        self.assertEqual(manifest['pending_abstract_check'], 1)
        self.assertNotIn('M22-test-paper', {r['id'] for r in evidence.search_library(self.base, 'M22')})

    def test_prompts_use_sources_without_blanket_disqualification(self):
        self.assertNotIn('仅作科普背景参考，不作为医学事实', llm.SYSTEM_PROMPT)
        self.assertIn('论文不必来自官方', llm.SYSTEM_PROMPT)
        self.assertIn('不因缺少门店资料而拒绝一般科普', prompts.analyze_instruction(2))
        self.assertIn('不在正文反复声明没有官方医学依据', prompts.DRAFT)


if __name__ == '__main__':
    unittest.main()
