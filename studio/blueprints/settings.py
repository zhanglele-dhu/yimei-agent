import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from flask import Blueprint, jsonify, request
from .. import creator_storage
from ..seedream_card import config as image_config
from .common import auth_required

settings_blueprint=Blueprint('settings',__name__)
SETTINGS_FILE=Path(os.getenv('STUDIO_CARD_SETTINGS_FILE', str(creator_storage.ROOT/'.env.card-model')))


@settings_blueprint.get('/settings')
@auth_required
def read_settings():
    config=image_config()
    return jsonify({'text_model':os.getenv('STUDIO_TEXT_MODEL',os.getenv('STUDIO_MODEL','deepseek-chat')),
        'text_base_url':os.getenv('STUDIO_TEXT_BASE_URL','https://api.deepseek.com'),
        'text_key_configured':bool(os.getenv('DEEPSEEK_API_KEY')),
        'provider':'图片模型','model':config['model'],'image_base_url':config['base_url'],
        'ready':bool(config['api_key']),'key_configured':bool(config['api_key'])})


@settings_blueprint.put('/settings')
@auth_required
def write_settings():
    body=request.get_json(silent=True) or {}
    text_base=str(body.get('text_base_url') or '').strip().rstrip('/'); text_model=str(body.get('text_model') or '').strip()
    image_base=str(body.get('image_base_url') or '').strip().rstrip('/'); image_model=str(body.get('image_model') or '').strip()
    text_key=str(body.get('text_api_key') or '').strip(); image_key=str(body.get('image_api_key') or '').strip()
    text_url=urlsplit(text_base); image_url=urlsplit(image_base)
    valid_text=text_url.scheme=='https' and bool(text_url.hostname) and not (text_url.username or text_url.password or text_url.query or text_url.fragment)
    valid_image=image_url.scheme=='https' and bool(image_url.hostname) and not (image_url.username or image_url.password or image_url.query or image_url.fragment)
    if not valid_text or not text_model or not valid_image or not image_model:
        return jsonify({'error':'请填写两个模型的 HTTPS 接口地址和模型名称。'}),422
    if any('\n' in key or '\r' in key for key in (text_key,image_key)): return jsonify({'error':'密钥格式无效。'}),422
    old=image_config()
    text_key=text_key or os.getenv('DEEPSEEK_API_KEY','')
    image_key=image_key or old['api_key']
    if not text_key or not image_key: return jsonify({'error':'请填写尚未配置的模型 API Key。'}),422
    values={'DEEPSEEK_API_KEY':text_key,'STUDIO_TEXT_BASE_URL':text_base,'STUDIO_TEXT_MODEL':text_model,
            'ARK_API_KEY':image_key,'ARK_BASE_URL':image_base,'SEEDREAM_MODEL':image_model}
    SETTINGS_FILE.write_text('\n'.join(f'{name}={json.dumps(value,ensure_ascii=False)}' for name,value in values.items())+'\n',encoding='utf-8')
    os.environ.update(values)
    return jsonify({'success':True})
