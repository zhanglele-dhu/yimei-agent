"""Malformed model output regressions; no real API calls."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from studio import llm
from studio.models import CardDesign


DESIGN = {'direction':'调整分组', 'html':'<main><h1>{{TITLE}}</h1><p>{{BLOCK_1}}</p></main>',
          'css':'main { color: #1e293b; }\nmain::after { content: "} {"; }'}


def response(raw):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw))],
                           usage=SimpleNamespace(prompt_tokens=10,completion_tokens=20))


class CardJsonTests(unittest.TestCase):
    def test_extra_braces_preserve_escaped_css_and_slots(self):
        raw = json.dumps(DESIGN,ensure_ascii=False) + '}}'
        self.assertEqual(llm._parse(CardDesign,raw).model_dump(),DESIGN)

    def test_markdown_and_prose_wrappers(self):
        raw = '```json\n' + json.dumps(DESIGN) + '\n```\n排版完成。'
        self.assertEqual(llm._parse(CardDesign,raw).model_dump(),DESIGN)

    def test_truncation_and_multiple_objects_are_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            llm._parse(CardDesign,json.dumps(DESIGN)[:-2])
        with self.assertRaises(ValueError):
            llm._parse(CardDesign,json.dumps(DESIGN)+'\n'+json.dumps(DESIGN))

    def complete(self, raws):
        config={'provider':'ark','base_url':'https://example.invalid/v3','api_key':'mock-only',
                'design_model':'mock-design','review_model':'mock-review'}
        with patch('studio.llm.supports_card_design',return_value=True), \
             patch('studio.llm.card_model_config',return_value=config), \
             patch('openai.OpenAI') as client:
            create=client.return_value.chat.completions.create
            create.side_effect=[response(raw) for raw in raws]
            result=llm.card_completion(CardDesign,'设计',{},[],phase='design')
            return result,create.call_count

    def test_extra_brace_needs_no_additional_model_call(self):
        (design,trace),calls=self.complete([json.dumps(DESIGN)+'}'])
        self.assertEqual(calls,1)
        self.assertEqual(design.model_dump(),DESIGN)
        self.assertEqual(trace['json_recovery'],'local_object_decode')

    def test_invalid_json_gets_one_format_repair(self):
        (design,trace),calls=self.complete([json.dumps(DESIGN)[:-2],json.dumps(DESIGN)])
        self.assertEqual(calls,2)
        self.assertEqual(design.model_dump(),DESIGN)
        self.assertEqual(trace['json_recovery'],'single_format_repair')
        self.assertEqual(trace['usage']['completion_tokens'],40)

    def test_missing_design_fields_are_not_invented_by_format_repair(self):
        with self.assertRaisesRegex(RuntimeError,'设计字段缺失'):
            self.complete([json.dumps({'direction':'空设计'})])

    def test_conflicting_designs_require_regeneration(self):
        with self.assertRaisesRegex(RuntimeError,'多份设计'):
            self.complete([json.dumps(DESIGN)+json.dumps({**DESIGN,'direction':'另一版'})])

    def test_bad_repair_stops_with_readable_error(self):
        with self.assertRaisesRegex(RuntimeError,'已尝试一次格式修复'):
            self.complete(['{"css":','{"css":'])


if __name__=='__main__':
    unittest.main()
