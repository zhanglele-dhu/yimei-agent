"""Skill-guided Seedream posters, followed by independent visual review."""
import base64
import hashlib
import io
import json
import os
import time

import httpx
from PIL import Image

from . import llm
from .card_layout import split_production_notes
from .model_card import PipelineError, SKILL_DIR
from .models import CardVisualCheck


def config():
    return {'api_key': os.getenv('ARK_API_KEY', '').strip(),
            'base_url': os.getenv('ARK_BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3').rstrip('/'),
            'model': os.getenv('SEEDREAM_MODEL', 'doubao-seedream-5-0-260128')}


def request_image(prompt, references):
    cfg = config()
    if not cfg['api_key']:
        raise ValueError('请在本地 .env 保存 ARK_API_KEY 后重新启动')
    body = {'model': cfg['model'], 'prompt': prompt, 'size': '1728x2304',
            'response_format': 'b64_json', 'watermark': True,
            'sequential_image_generation': 'disabled'}
    if references:
        body['image'] = ['data:image/jpeg;base64,' + llm._image_b64(item['data']) for item in references[:2]]
    started = time.monotonic()
    with httpx.Client(timeout=240) as client:
        response = client.post(cfg['base_url'] + '/images/generations', json=body,
                               headers={'Authorization': 'Bearer ' + cfg['api_key']})
        if response.status_code != 200:
            raise RuntimeError('Seedream HTTP ' + str(response.status_code) + ': ' + response.text[:500])
        payload = response.json()
    entries = payload.get('data') or []
    if not entries or not entries[0].get('b64_json'):
        raise ValueError('Seedream 未返回可用的 Base64 图片')
    data = base64.b64decode(entries[0]['b64_json'], validate=True)
    if len(data) > 30_000_000:
        raise ValueError('生成图片超过大小限制')
    with Image.open(io.BytesIO(data)) as image:
        width, height = image.size
        if (width, height) != (1728, 2304):
            raise ValueError('生成图片不符合 3:4 高清尺寸要求')
        output = io.BytesIO()
        image.convert('RGB').save(output, format='PNG')
    return output.getvalue(), {'model': cfg['model'], 'usage': payload.get('usage'),
                              'elapsed_ms': round((time.monotonic() - started) * 1000)}


def generate(title, text, *, kind, page, total_pages, theme, reference_images,
             photo=None, previous=None, regenerate=False, previous_image_sha256=None, editorial_context=None):
    """Seedream visual asset + model-authored layout + exact original text slots."""
    from . import model_card
    audit = {'pipeline':'skill_seedream_hybrid', 'attempts':[]}
    try:
        if kind == 'photo' or photo:
            raise ValueError('实拍页请使用 AI 视觉排版，以保留原始照片')
        if not llm.supports_card_design():
            raise ValueError('请先配置视觉设计与检查模型')
        # Check image access before spending on an image generation.
        probe = io.BytesIO()
        Image.new('RGB',(64,64),'white').save(probe,format='PNG')
        _, audit['review_preflight'] = llm.card_completion(CardVisualCheck,
            '图片接口连通测试。返回passed=false，summary为已连通，issues为空。',
            {}, [{'data':probe.getvalue(),'role':'连通测试'}],phase='review')
        skill = (SKILL_DIR/'SKILL.md').read_text(encoding='utf-8')
        audit['skill_sha256'] = hashlib.sha256(skill.encode()).hexdigest()
        public, notes = split_production_notes(text)
        prompt = ('为小红书科普信息卡设计一张无文字视觉素材，竖版3:4，1728×2304。'
                  '抽象光线、透明色块与滤光片质感，清爽、精致、有层次。视觉主体置于画面中央横向区域，便于用作横幅。'
                  '只做视觉设计，不画任何文字、汉字、字母、数字、标识、伪文字或署名。'
                  '不画真实医疗设备、人物或疗效对比图。参考图只借鉴色彩和视觉语言，不复制其中的字。'
                  '颜色主题：'+str(theme)+'。本页主题只用于理解，不得将主题画进图里：'+title)
        visual, generation_trace = request_image(prompt, reference_images)
        audit['attempts'].append({'mode':'text_free_visual','generation':generation_trace})
        audit['prompt'] = prompt
        audit['visual_sha256'] = hashlib.sha256(visual).hexdigest()
        audit['visual_asset_b64'] = base64.b64encode(visual).decode()
        # No generated text is used as publication copy. The existing model
        # designs real HTML/CSS; Chromium inserts the approved strings literally.
        data, meta, layout_audit = model_card.generate(title, public, kind=kind,
            page=page,total_pages=total_pages,theme=theme,reference_images=reference_images,
            previous=previous,regenerate=regenerate,previous_image_sha256=previous_image_sha256,
            generated_visual=visual,render_scale=1.6,editorial_context=editorial_context)
        audit['layout'] = layout_audit
        audit['design'] = layout_audit.get('design')
        audit['status'] = 'passed'
        meta.update(method='skill_seedream_image',layout_version='seedream-exact-text-v2',
            generation_mode='seedream',width=1728,height=2304,pipeline='skill_seedream_hybrid',
            image_model=config()['model'],text_rendering='browser_exact_slots',
            visual_sha256=audit['visual_sha256'],production_notes=notes,
            design_direction='Seedream生成无文字视觉素材，视觉模型设计版式，浏览器逐字排入已确认原文')
        return data, meta, audit
    except Exception as exc:
        if isinstance(exc, PipelineError):
            audit['layout'] = exc.audit
        message = str(exc)
        for key in (config()['api_key'],llm.card_model_config().get('api_key')):
            if key:message=message.replace(key,'[redacted]')
        audit.update(status='failed',error=message[:1500])
        raise PipelineError(message,audit) from exc
