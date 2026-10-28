"""Offline image endpoint and approval contracts; no paid model calls."""
import base64
import io
import os
import unittest
from unittest.mock import patch

from PIL import Image

from studio import llm, seedream_card
from studio.model_card import PipelineError
from studio.models import CardVisualCheck
import test_model_card


def poster():
    stream = io.BytesIO()
    Image.new('RGB', (1728, 2304), '#e7eee6').save(stream, format='PNG')
    return stream.getvalue()


def review(*args, **kwargs):
    return CardVisualCheck(passed=True, summary='离线模拟检查通过', issues=[]), {'model': 'mock'}


class SeedreamTests(unittest.TestCase):
    def setUp(self):
        configured=patch('studio.llm.supports_card_design',return_value=True)
        configured.start()
        self.addCleanup(configured.stop)
    def test_ark_fallback_and_explicit_custom_key_isolation(self):
        with patch.dict(os.environ, {'ARK_API_KEY': 'ark-test-secret', 'STUDIO_CARD_PROVIDER': 'custom',
                                    'STUDIO_CARD_BASE_URL': '', 'STUDIO_CARD_API_KEY': '',
                                    'STUDIO_CARD_DESIGN_MODEL': '', 'STUDIO_CARD_REVIEW_MODEL': ''}):
            self.assertEqual(llm.card_model_config()['provider'], 'ark')
            os.environ['STUDIO_CARD_BASE_URL'] = 'https://another.example/v1'
            self.assertEqual(llm.card_model_config()['api_key'], '')

    @patch('studio.seedream_card.httpx.Client')
    def test_dedicated_image_endpoint_and_valid_high_resolution(self, client):
        response = client.return_value.__enter__.return_value.post.return_value
        response.status_code = 200
        response.json.return_value = {'data': [{'b64_json': base64.b64encode(poster()).decode()}]}
        with patch.dict(os.environ, {'ARK_API_KEY': 'image-secret'}):
            data, trace = seedream_card.request_image('已确认文字', [])
        request = client.return_value.__enter__.return_value.post.call_args
        self.assertTrue(request.args[0].endswith('/images/generations'))
        self.assertEqual(request.kwargs['json']['size'], '1728x2304')
        self.assertTrue(request.kwargs['json']['watermark'])
        self.assertEqual(Image.open(io.BytesIO(data)).size, (1728, 2304))
        self.assertNotIn('image-secret', str(trace))

    @patch('studio.llm.card_completion', side_effect=test_model_card.fake_card_completion)
    @patch('studio.seedream_card.request_image', return_value=(poster(), {'model': 'mock'}))
    def test_skill_and_approved_copy_pass_to_generator(self, generate, completion):
        _, meta, audit = seedream_card.generate('已确认标题', '已确认文字。\n\n实拍建议：拍摄接待台。',
            kind='text', page=1, total_pages=3, theme='minimal', reference_images=[])
        prompt = generate.call_args.args[0]
        self.assertIn('已确认标题', prompt)
        self.assertNotIn('已确认文字。', prompt)
        self.assertIn('不画任何文字',prompt)
        self.assertNotIn('拍摄接待台', prompt)
        self.assertEqual(meta['method'], 'skill_seedream_image')
        self.assertEqual(meta['public_text'], '已确认文字。')
        self.assertTrue(audit['skill_sha256'])
        self.assertEqual(completion.call_count, 3)  # Preflight, layout design, final review.
        self.assertEqual(meta['text_rendering'],'browser_exact_slots')
        self.assertEqual(meta['width'],1728)
        self.assertEqual(Image.open(io.BytesIO(_)).size,(1728,2304))
        self.assertTrue(completion.call_args_list[0].args[3])  # Probe actual image access, not only text access.

    @patch('studio.seedream_card.request_image')
    @patch('studio.llm.card_completion', side_effect=RuntimeError('ModelNotOpen'))
    def test_unavailable_review_model_does_not_spend_image_call(self, completion, generate):
        with self.assertRaises(PipelineError):
            seedream_card.generate('标题', '正文', kind='text', page=1, total_pages=1, theme='minimal', reference_images=[])
        generate.assert_not_called()

    @patch('studio.llm.card_completion', side_effect=test_model_card.fake_card_completion)
    @patch('studio.seedream_card.request_image', return_value=(poster(), {'model':'mock'}))
    def test_mixed_chinese_device_names_are_exact_browser_text(self, image, completion):
        title='M22、IPL、OPT、AOPT、ResurFX，一层层分清'
        text=('M22是强脉冲光与激光多功能平台，厂商把IPL、ResurFX等列为不同模块。\n\n'
              'IPL是宽谱、非相干的脉冲光，和通常单波长的激光不同；滤片改变到达皮肤的光谱范围。\n\n'
              'OPT与AOPT是脉冲控制技术。双波滤片保留两个波段。\n\n'
              'ResurFX是1565nm非剥脱点阵激光模块，不属于IPL滤片。')
        _,meta,_=seedream_card.generate(title,text,kind='text',page=1,total_pages=1,theme='minimal',reference_images=[])
        geometry=meta['geometry_check']
        self.assertTrue(geometry['exact_text_passed'])
        self.assertEqual(geometry['slot_texts']['TITLE'],title)
        self.assertEqual(geometry['slot_texts']['BLOCK_1'],text.split('\n\n')[0])
        self.assertEqual(geometry['slot_texts']['BLOCK_4'],text.split('\n\n')[3])
        self.assertEqual(image.call_count,1)

    @patch('studio.seedream_card.request_image', return_value=(poster(), {'model': 'mock'}))
    @patch('studio.llm.card_completion', side_effect=review)
    def test_failed_layout_keeps_seedream_audit_and_does_not_redraw_copy(self, completion, generate):
        with patch('studio.model_card.generate',side_effect=PipelineError('版式未通过',{'steps':[]})), self.assertRaises(PipelineError) as caught:
            seedream_card.generate('标题', '正文', kind='text', page=1, total_pages=1, theme='minimal', reference_images=[])
        self.assertEqual(generate.call_count,1)
        self.assertEqual(caught.exception.audit['pipeline'],'skill_seedream_hybrid')
        self.assertIn('layout',caught.exception.audit)

    @patch('studio.llm.card_completion', side_effect=review)
    @patch('studio.seedream_card.request_image', side_effect=RuntimeError('image-secret invalid'))
    def test_failure_redacts_key(self, generate, completion):
        with patch.dict(os.environ, {'ARK_API_KEY': 'image-secret'}), self.assertRaises(PipelineError) as caught:
            seedream_card.generate('标题', '正文', kind='text', page=1, total_pages=1, theme='minimal', reference_images=[])
        self.assertNotIn('image-secret', str(caught.exception))
        self.assertNotIn('image-secret', str(caught.exception.audit))


class SeedreamApiTests(unittest.TestCase):
    def setUp(self):
        test_model_card.ModelCardApiTests.setUp(self)
        configured=patch('studio.llm.supports_card_design',return_value=True)
        configured.start()
        self.addCleanup(configured.stop)
    def test_seedream_success_then_failed_regeneration_preserves_previous(self):
        with patch('studio.llm.generate', side_effect=self.fixtures.fake_generate):
            task = self.fixture.ready()
        payload = {'revision': task['revision'], 'title': '已确认标题', 'text': '已确认正文。',
                   'confirmed': True, 'generation_mode': 'seedream'}
        with patch('studio.llm.card_completion', side_effect=test_model_card.fake_card_completion), patch('studio.seedream_card.request_image', return_value=(poster(), {'model': 'mock'})):
            response = self.client.post('/api/tasks/' + task['id'] + '/pages/1', json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        task = response.json()
        previous = task['renders']['1']
        self.assertEqual(previous['method'], 'skill_seedream_image')
        payload.update(revision=task['revision'], regenerate_design=True)
        with patch('studio.seedream_card.generate', side_effect=PipelineError('成图检查未通过：M22 错写为 M23', {'attempts': []})):
            response = self.client.post('/api/tasks/' + task['id'] + '/pages/1', json=payload)
        self.assertEqual(response.status_code, 502)
        self.assertIn('M23',response.text)
        self.assertIn('AI 视觉排版',response.json()['detail'])
        task = self.client.get('/api/tasks/' + task['id']).json()
        self.assertEqual(task['renders']['1'], previous)
        self.assertEqual(task['generation_attempts'][-1]['mode'], 'seedream')
        self.assertEqual(task['draft']['pages'][0]['text'], '已确认正文。')
        self.assertEqual(task['render_preferences']['1']['generation_mode'],'seedream')
        self.assertIn('M23',task['generation_attempts'][-1]['message'])
        payload.update(revision=task['revision'], generation_mode=task['render_preferences']['1']['generation_mode'])
        with patch('studio.model_card.generate') as model_generate, patch('studio.seedream_card.generate',return_value=(poster(),{'method':'skill_seedream_image'},{'attempts':[]})) as seedream_generate:
            response=self.client.post('/api/tasks/'+task['id']+'/pages/1',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        model_generate.assert_not_called()
        seedream_generate.assert_called_once()
