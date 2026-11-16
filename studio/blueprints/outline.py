import os
import re
from pathlib import Path

from flask import Blueprint, jsonify, request
from openai import OpenAI

from .common import auth_required, safe_error

outline_blueprint = Blueprint('outline', __name__)
PROMPT_PATH = Path(__file__).resolve().parents[1] / 'prompts' / 'outline_prompt.txt'
PAGE_SEPARATOR = re.compile(r'^\s*<page\s*>\s*$', re.IGNORECASE | re.MULTILINE)
PAGE_TYPE = re.compile(r'^\s*\[(封面|内容|总结)\]\s*$', re.MULTILINE)


def _build_prompt(topic, count):
    template = PROMPT_PATH.read_text(encoding='utf-8')
    return template.replace('{{topic}}', topic).replace('{{page_count}}', str(count))


def _parse_outline(raw, count):
    sections = [part.strip() for part in PAGE_SEPARATOR.split(raw.strip()) if part.strip()]
    if len(sections) != count:
        raise ValueError(f'模型返回了 {len(sections)} 页大纲，要求恰好 {count} 页，请重试。')

    pages = []
    for index, section in enumerate(sections):
        marker = PAGE_TYPE.search(section)
        marker_type = marker.group(1) if marker else None
        content = PAGE_TYPE.sub('', section, count=1).strip()
        if not content:
            raise ValueError(f'第 {index + 1} 页大纲为空，请重试。')
        page_type = {'封面': 'cover', '内容': 'content', '总结': 'summary'}.get(marker_type)
        if page_type is None:
            page_type = 'cover' if index == 0 else ('summary' if index == count - 1 and count > 1 else 'content')
        pages.append({'index': index, 'type': page_type, 'content': content})

    # Keep the cover label stable for the UI even if the model omits its marker.
    pages[0]['type'] = 'cover'
    if count > 1:
        pages[-1]['type'] = 'summary'
    return pages


@outline_blueprint.post('/outline')
@auth_required
def create_outline():
    body = request.get_json(silent=True) or {}
    topic = str(body.get('topic') or '').strip()
    try:
        count = min(8, max(1, int(body.get('page_count') or 5)))
    except (TypeError, ValueError):
        return jsonify({'error': '图片数量必须为 1 到 8 张。'}), 422
    if not topic:
        return jsonify({'error': '请先输入一个创作主题。'}), 422
    if not os.getenv('DEEPSEEK_API_KEY'):
        return jsonify({'error': '尚未配置文本模型密钥。'}), 503

    try:
        prompt = _build_prompt(topic, count)
        response = OpenAI(
            api_key=os.environ['DEEPSEEK_API_KEY'],
            base_url=os.getenv('STUDIO_TEXT_BASE_URL', 'https://api.deepseek.com'),
            timeout=90,
            max_retries=0,
        ).chat.completions.create(
            model=os.getenv('STUDIO_TEXT_MODEL', os.getenv('STUDIO_MODEL', 'deepseek-chat')),
            max_tokens=3000,
            messages=[
                {
                    'role': 'system',
                    'content': '你是小红书图文内容策划。遵守用户主题、页数和指定分页格式；只输出大纲，不输出 JSON、代码围栏或额外说明。',
                },
                {'role': 'user', 'content': prompt},
            ],
        )
        raw = response.choices[0].message.content or ''
        pages = _parse_outline(raw, count)
        normalized_raw = '\n\n<page>\n\n'.join(page['content'] for page in pages)
        return jsonify({'raw': normalized_raw, 'pages': pages})
    except Exception as error:
        return jsonify({'error': safe_error(error, 500)}), 502
