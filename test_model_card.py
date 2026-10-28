"""Offline contract tests: model responses mocked, Chromium rendering is real."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from studio import llm, model_card
from studio.models import CardDesign, CardVisualCheck


def fake_card_completion(schema, instruction, sources, images, *, phase):
    if phase == 'review':
        result=CardVisualCheck(passed=True,summary='离线模拟：版式可读，无可见遮挡。',issues=[])
    else:
        blocks=[name for name in sources['required_slots'] if name.startswith('BLOCK_')]
        body=''.join('<p>{{'+name+'}}</p>' for name in blocks)
        photo='<div class="photo">{{PHOTO}}</div>' if 'PHOTO' in sources['required_slots'] else ''
        visual='<div class="visual">{{VISUAL}}</div>' if 'VISUAL' in sources['required_slots'] else ''
        result=CardDesign(direction='离线测试用设计，不代表真实模型效果',
            html='<main class="layout"><header><div class="tag">{{KICKER}}</div><h1>{{TITLE}}</h1></header>'+photo+visual+'<section>'+body+'</section><footer>{{PAGE}}</footer></main>',
            css='.layout{height:1440px;padding:76px;background:#f6f4ed;color:#163d32;display:flex;flex-direction:column;gap:26px}.tag{font-size:30px;color:#397456}h1{font-size:76px;line-height:1.3;margin:15px 0 0}section{font-size:34px;line-height:1.55}p{margin:0 0 18px}footer{margin-top:auto;font-size:28px}.source-photo{width:100%;height:240px}')
        if sources.get('previous_design'):
            result.css=result.css.replace('#f6f4ed','#e9f0e8')
    return result, {'model':'offline-test-model','phase':phase,'provider':'mock','response':result.model_dump()}


class ModelCardTests(unittest.TestCase):
    def test_short_point_lead_is_emphasized_without_rewriting_copy(self):
        original='滤片可切换：IPL通过更换滤片，选择不同的光谱范围。'
        design=CardDesign(direction='短标题与解释',html='<main><p>{{BLOCK_1}}</p></main>',
            css='main{padding:70px}p{font-size:36px;line-height:1.5;margin:0}')
        document=model_card.compose(design,{'BLOCK_1':original})
        self.assertIn('class="point-lead"',document)
        _,report=model_card.render_html(document,['BLOCK_1'])
        self.assertEqual(report['slot_texts']['BLOCK_1'],original)

    def test_geometry_errors_have_readable_chinese_summary(self):
        message=model_card.public_error('BLOCK_8: outside canvas; PHOTO: hidden; PHOTO: clipped by container')
        self.assertIn('照片没有完整显示',message)
        self.assertNotIn('BLOCK_',message)
        self.assertNotIn('hidden',message)
        self.assertIsNone(model_card.public_error('请先设置模型'))

    @patch('studio.llm.supports_card_design',return_value=True)
    def test_photo_placeholder_normalization_and_layout_budget(self,enabled):
        def completion(schema,*args,**kwargs):
            result,trace=fake_card_completion(schema,*args,**kwargs)
            if kwargs['phase']=='design':
                self.assertEqual(args[1]['layout_budget']['photo_height'],320)
                self.assertEqual(len(args[1]['layout_budget']['body_blocks']),8)
                result.html=result.html.replace('{{PHOTO}}','<img class="source-photo" src="" alt="门店照片" />')
            return result,trace
        stream=io.BytesIO();Image.new('RGB',(320,240),'#abc').save(stream,format='PNG')
        with patch('studio.llm.card_completion',side_effect=completion):
            _,meta,audit=model_card.generate('到店流程','\n'.join('流程'+str(i) for i in range(8)),kind='photo',page=2,total_pages=3,theme='minimal',reference_images=[],photo=stream.getvalue())
        self.assertEqual(meta['source_photo']['width'],320)
        self.assertTrue(audit['normalizations'])
        self.assertIn('{{PHOTO}}',audit['design']['html'])

    @patch('openai.OpenAI')
    def test_completion_uses_custom_endpoint_and_model(self,client_type):
        result=CardVisualCheck(passed=True,summary='测试检查',issues=[])
        client_type.return_value.chat.completions.create.return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=result.model_dump_json()))],usage=None)
        stream=io.BytesIO();Image.new('RGB',(240,240),'white').save(stream,format='PNG')
        with patch.dict(os.environ,{'STUDIO_CARD_PROVIDER':'custom','STUDIO_CARD_BASE_URL':'https://new-provider.example/v1',
            'STUDIO_CARD_API_KEY':'offline-custom-key','STUDIO_CARD_DESIGN_MODEL':'vision-design',
            'STUDIO_CARD_REVIEW_MODEL':'vision-review'}):
            parsed,trace=llm.card_completion(CardVisualCheck,'检查',{},[{'data':stream.getvalue(),'role':'成图'}],phase='review')
        self.assertEqual(client_type.call_args.kwargs['base_url'],'https://new-provider.example/v1')
        self.assertEqual(client_type.call_args.kwargs['api_key'],'offline-custom-key')
        self.assertEqual(client_type.return_value.chat.completions.create.call_args.kwargs['model'],'vision-review')
        self.assertEqual(trace['provider'],'custom')
        self.assertTrue(parsed.passed)

    def test_validation_rejects_new_copy_scripts_and_external_css(self):
        slots={'TITLE':'标题','BLOCK_1':'已确认文字'}
        model_card.validate_design(CardDesign(direction='测试', html='<h1>{{TITLE}}</h1><p>{{BLOCK_1}}</p>',
            css='p{display:flex;justify-content:center;align-content:start}'), slots, list(slots))
        for fragment,css in [('<h1>{{TITLE}}</h1><p>擅自新增疗效承诺{{BLOCK_1}}</p>','p{color:red}'),
                             ('<script>{{TITLE}}{{BLOCK_1}}</script>','p{color:red}'),
                             ('<h1>{{TITLE}}</h1><p>{{BLOCK_1}}</p>','p{background:url(https://example.com)}'),
                             ('<h1>{{TITLE}}</h1><p>{{BLOCK_1}}</p>','p:before{content:"新增文字"}'),
                             ('<h1>{{TITLE}}</h1>','p{color:red}')]:
            with self.subTest(fragment=fragment,css=css),self.assertRaises(ValueError):
                model_card.validate_design(CardDesign(direction='测试',html=fragment,css=css),slots,list(slots))

    @patch('studio.llm.supports_card_design',return_value=True)
    @patch('studio.llm.card_completion',side_effect=fake_card_completion)
    def test_real_browser_and_review_pipeline(self,completion,enabled):
        image,meta,audit=model_card.generate('咨询前，先准备好问题','整理自己的疑问。\n\n实拍建议：拍摄接待区域。',
            kind='text',page=1,total_pages=3,theme='minimal',reference_images=[])
        self.assertEqual(Image.open(io.BytesIO(image)).size,(1080,1440))
        self.assertEqual([call.kwargs['phase'] for call in completion.call_args_list],['design','review'])
        self.assertEqual(meta['method'],'skill_model_html')
        self.assertEqual(meta['skill']['name'],'xhs-note-creator')
        self.assertTrue(meta['visual_review']['passed'])
        self.assertEqual(meta['public_text'],'整理自己的疑问。')
        self.assertEqual(len(meta['production_notes']),1)
        self.assertTrue(audit['design']['css'])

    @patch('studio.llm.supports_card_design',return_value=True)
    def test_failed_review_repairs_once_then_stops(self,enabled):
        def failed(schema,*args,**kwargs):
            if kwargs['phase']=='review':
                return CardVisualCheck(passed=False,summary='模拟检查不通过',issues=['需要更清晰的层级']),{'model':'mock'}
            return fake_card_completion(schema,*args,**kwargs)
        with patch('studio.llm.card_completion',side_effect=failed) as completion:
            with self.assertRaises(model_card.PipelineError) as failure:
                model_card.generate('咨询前','整理问题。',kind='text',page=1,total_pages=1,theme='minimal',reference_images=[])
            self.assertEqual(completion.call_count,4)
            self.assertEqual(len([step for step in failure.exception.audit['steps'] if step['step']=='review']),2)

    @patch('studio.llm.supports_card_design',return_value=True)
    @patch('studio.llm.card_completion',side_effect=fake_card_completion)
    def test_photo_passed_as_real_asset_and_to_design_model(self,completion,enabled):
        stream=io.BytesIO();Image.new('RGB',(320,240),'#def').save(stream,format='PNG')
        _,meta,_=model_card.generate('到店流程','先核对信息。',kind='photo',page=2,total_pages=3,theme='minimal',reference_images=[],photo=stream.getvalue())
        self.assertEqual(meta['source_photo']['width'],320)
        self.assertEqual(completion.call_args_list[0].args[3][0]['data'],stream.getvalue())

    def test_small_or_hidden_text_is_rejected_by_browser(self):
        for css in ('.small{font-size:8px}', '.small{display:none}'):
            design=CardDesign(direction='测试',html='<div class="small">{{TITLE}}</div>',css=css)
            with self.assertRaises(ValueError):
                model_card.render_html(model_card.compose(design,{'TITLE':'可读性检查'}),['TITLE'])

    def test_invented_diagram_is_removed_with_its_empty_layout_space(self):
        source='<main><h1>{{TITLE}}</h1><p>{{BLOCK_1}}</p><section class="diagram"><div>虚构模块A</div><div>虚构模块B</div></section><p>{{BLOCK_2}}</p></main>'
        cleaned,count=model_card.prune_unapproved_diagrams(source)
        self.assertEqual(count,1)
        self.assertNotIn('diagram',cleaned)
        self.assertIn('{{BLOCK_1}}',cleaned);self.assertIn('{{BLOCK_2}}',cleaned)
        design=CardDesign(direction='模型排版保留原文',html=cleaned,
            css='main{padding:60px;font-size:40px}h1{font-size:64px}.diagram{height:1400px}')
        _,geometry=model_card.render_html(model_card.compose(design,{'TITLE':'M22平台','BLOCK_1':'平台可搭载不同模块。','BLOCK_2':'IPL是其中一部分。'}),['TITLE','BLOCK_1','BLOCK_2'])
        self.assertTrue(geometry['passed'])

    def test_custom_provider_does_not_reuse_other_platform_key(self):
        with patch.dict(os.environ,{'STUDIO_CARD_PROVIDER':'custom','STUDIO_CARD_BASE_URL':'https://vision.example/v1',
                                   'STUDIO_CARD_API_KEY':'','STUDIO_CARD_DESIGN_MODEL':'vision-model','VISION_API_KEY':'old-key'}):
            self.assertFalse(llm.supports_card_design())
            self.assertEqual(llm.card_model_config()['api_key'],'')

    @patch('studio.llm.supports_card_design',return_value=True)
    def test_model_repeated_system_root_id_is_normalized(self, enabled):
        def completion(schema,*args,**kwargs):
            result, trace = fake_card_completion(schema,*args,**kwargs)
            if kwargs['phase']=='design':
                result.html=result.html.replace('<main class=', '<main id="card" class=',1).replace('</header>','<span>模型自创标签</span></header>')
            return result, trace
        with patch('studio.llm.card_completion',side_effect=completion):
            _,_,audit=model_card.generate('咨询前','整理问题。',kind='text',page=1,total_pages=1,theme='minimal',reference_images=[])
        self.assertNotIn('id="card"',audit['design']['html'])
        self.assertNotIn('模型自创标签',audit['design']['html'])
        self.assertEqual(audit['discarded_unapproved_labels'][0],['模型自创标签'])


class ModelCardApiTests(unittest.TestCase):
    def setUp(self):
        import test_studio as fixtures
        self.fixtures=fixtures
        self.fixture=fixtures.StudioTests('test_auth_cache_and_page_contract')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.api=fixtures.api
        self.client=self.fixture.client

    @patch('studio.llm.card_completion',side_effect=fake_card_completion)
    @patch('studio.llm.supports_card_design',return_value=True)
    def test_default_model_generation_and_regeneration_keep_approved_copy(self,enabled,completion):
        with patch('studio.llm.generate',side_effect=self.fixtures.fake_generate):
            task=self.fixture.ready()
        payload={'revision':task['revision'],'title':'已确认标题','text':'已确认文字。','confirmed':True}
        response=self.client.post('/api/tasks/'+task['id']+'/pages/1',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        task=response.json();first=task['renders']['1']['file']
        self.assertEqual(task['renders']['1']['generation_mode'],'model')
        payload.update(revision=task['revision'],regenerate_design=True)
        response=self.client.post('/api/tasks/'+task['id']+'/pages/1',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        task=response.json()
        self.assertNotEqual(task['renders']['1']['file'],first)
        self.assertEqual(task['draft']['pages'][0]['text'],'已确认文字。')
        self.assertIn('previous_design',completion.call_args_list[2].args[2])
        self.assertIsNotNone(completion.call_args_list[2].args[2]['previous_design'])

    def test_failure_preserves_previous_render_and_records_attempt(self):
        with patch('studio.llm.generate',side_effect=self.fixtures.fake_generate):
            task=self.fixture.ready()
        task=self.fixture.post(task,'/pages/1',title='旧成品',text='已确认文字。',confirmed=True)
        previous=task['renders']['1']
        with patch('studio.model_card.generate',side_effect=model_card.PipelineError('模拟额度不足',{'steps':[],'error':'模拟额度不足'})):
            response=self.client.post('/api/tasks/'+task['id']+'/pages/1',json={'revision':task['revision'],'title':'旧成品','text':'已确认文字。','confirmed':True})
        self.assertEqual(response.status_code,502)
        latest=self.client.get('/api/tasks/'+task['id']).json()
        self.assertEqual(latest['renders']['1'],previous)
        self.assertEqual(latest['generation_attempts'][-1]['status'],'failed')
        self.assertEqual(latest['revision'],task['revision']+1)

    def test_geometry_failure_is_short_and_raw_detail_stays_in_audit(self):
        self.assertTrue(self.client.get('/api/card-model-settings').json()['original_photo_layout'])
        with patch('studio.llm.generate',side_effect=self.fixtures.fake_generate):
            task=self.fixture.ready()
        task=self.fixture.post(task,'/pages/1',title='旧成品',text='已确认文字。',confirmed=True)
        previous=task['renders']['1']
        detail='BLOCK_8: outside canvas; PHOTO: hidden; PHOTO: clipped by container'
        with patch('studio.model_card.generate',side_effect=model_card.PipelineError(detail,{'steps':[]})):
            response=self.client.post('/api/tasks/'+task['id']+'/pages/1',json={'revision':task['revision'],'title':'旧成品','text':'已确认文字。','confirmed':True})
        self.assertEqual(response.status_code,502)
        self.assertNotIn('BLOCK_',response.text)
        self.assertIn('照片没有完整显示',response.text)
        latest=self.client.get('/api/tasks/'+task['id']).json()
        self.assertEqual(latest['renders']['1'],previous)
        self.assertEqual(latest['generation_attempts'][-1]['message'],detail)

    def test_model_settings_are_redacted_and_saved_without_cross_provider_key_reuse(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(self.api,'CARD_SETTINGS_PATH',Path(directory)/'card.env'),patch.dict(os.environ,{
            'STUDIO_CARD_PROVIDER':'custom','STUDIO_CARD_BASE_URL':'https://old.example/v1',
            'STUDIO_CARD_API_KEY':'old-provider-key','STUDIO_CARD_DESIGN_MODEL':'old-model'}):
            response=self.client.post('/api/card-model-settings',json={'base_url':'https://new.example/v1','model':'vision-new','api_key':''})
            self.assertEqual(response.status_code,422)
            response=self.client.post('/api/card-model-settings',json={'base_url':'https://new.example/v1','model':'vision-new','api_key':'test-new-provider-secret'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertNotIn('test-new-provider-secret',response.text)
            self.assertTrue(response.json()['key_configured'])
            self.assertEqual(llm.card_model_config()['api_key'],'test-new-provider-secret')
            self.assertTrue((Path(directory)/'card.env').exists())
            self.assertNotIn('api_key',self.client.get('/api/card-model-settings').json())
