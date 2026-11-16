import json
import os
import re
from flask import Blueprint, jsonify, request
from openai import OpenAI
from .. import creator_storage
from .common import auth_required, safe_error

content_blueprint = Blueprint('content', __name__)


@content_blueprint.post('/content')
@auth_required
def create_copy():
    body=request.get_json(silent=True) or {}; topic=str(body.get('topic') or '').strip(); outline=str(body.get('outline') or '')
    if not topic: return jsonify({'error':'创作主题不能为空。'}),422
    if not os.getenv('DEEPSEEK_API_KEY'): return jsonify({'error':'尚未配置文本模型密钥。'}),503
    try:
        response=OpenAI(api_key=os.environ['DEEPSEEK_API_KEY'],base_url=os.getenv('STUDIO_TEXT_BASE_URL','https://api.deepseek.com'),timeout=90,max_retries=0).chat.completions.create(
            model=os.getenv('STUDIO_TEXT_MODEL',os.getenv('STUDIO_MODEL','deepseek-chat')),max_tokens=2200,
            messages=[{'role':'system','content':'你是中文社交平台内容编辑。基于主题和大纲写自然、清楚的标题与正文。不得伪造亲历或专业资质。只输出 JSON。'},
                      {'role':'user','content':f'主题：{topic}\n大纲：{outline}\n返回格式：{{"titles":["标题1","标题2","标题3"],"copywriting":"正文","tags":["#标签"]}}'}])
        raw=response.choices[0].message.content or ''; match=re.search(r'\{[\s\S]*\}',raw); data=json.loads(match.group(0) if match else raw)
        return jsonify({'titles':data.get('titles',[]),'copywriting':data.get('copywriting',''),'tags':data.get('tags',[])})
    except Exception as error: return jsonify({'error':safe_error(error)}),502
