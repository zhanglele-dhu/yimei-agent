import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from studio import llm
from studio.models import Draft, DraftContentReview


class WriterRoutingTests(unittest.TestCase):
    def test_draft_uses_author_role_and_records_actual_system(self):
        response = SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            'title': '认识设备', 'body': '按手具认识设备。',
            'pages': [{'number': 1, 'title': '先认识设备', 'text': '从手具的分工开始了解。'}]
        }, ensure_ascii=False)))])
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'offline-test'}), patch('openai.OpenAI') as client:
            client.return_value.chat.completions.create.return_value = response
            result, trace = llm.generate(Draft, {'action': '写草稿'}, [])
        messages = client.return_value.chat.completions.create.call_args.kwargs['messages']
        self.assertEqual(messages[0]['content'], llm.WRITER_SYSTEM_PROMPT)
        self.assertEqual(trace['system'], messages[0]['content'])
        self.assertEqual(result.pages[0].number, 1)

    def test_review_retains_evidence_role(self):
        self.assertEqual(llm.system_for(DraftContentReview), llm.SYSTEM_PROMPT)
        self.assertNotEqual(llm.system_for(Draft), llm.system_for(DraftContentReview))


if __name__ == '__main__':
    unittest.main()
