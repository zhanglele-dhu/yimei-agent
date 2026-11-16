import io
import json
import zipfile
from uuid import uuid4
from flask import Blueprint, jsonify, request, send_file
from .. import creator_storage
from .common import auth_required

history_blueprint = Blueprint('history', __name__)


@history_blueprint.post('/history')
@auth_required
def create_history():
    body = request.get_json(silent=True) or {}; topic = str(body.get('topic') or '').strip(); outline = body.get('outline') or {}
    if not topic or not outline.get('pages'): return jsonify({'error':'主题和大纲不能为空。'}),422
    record_id = uuid4().hex
    creator_storage.save_record({'id':record_id,'title':topic,'created_at':creator_storage._now(),'updated_at':creator_storage._now(),
        'status':'draft','thumbnail':None,'page_count':len(outline['pages']),'task_id':None,'outline':outline,
        'images':{'task_id':None,'generated':[]},'content':{'titles':[],'copywriting':'','tags':[]}})
    return jsonify({'record_id':record_id})


@history_blueprint.get('/history')
@auth_required
def list_history():
    return jsonify(creator_storage.list_records(request.args.get('page',1,type=int), request.args.get('page_size',24,type=int), request.args.get('keyword',''), request.args.get('status','')))


@history_blueprint.get('/history/<record_id>')
@auth_required
def read_history(record_id):
    record=creator_storage.get_record(record_id)
    return (jsonify(record),200) if record else (jsonify({'error':'历史记录不存在。'}),404)


@history_blueprint.put('/history/<record_id>')
@auth_required
def update_history(record_id):
    record=creator_storage.get_record(record_id)
    if not record: return jsonify({'error':'历史记录不存在。'}),404
    body=request.get_json(silent=True) or {}
    for field in ('outline','images','content','status','thumbnail','task_id'):
        if field in body: record[field]=body[field]
    record['page_count']=len((record.get('outline') or {}).get('pages') or [])
    return jsonify(creator_storage.save_record(record))


@history_blueprint.delete('/history/<record_id>')
@auth_required
def remove_history(record_id):
    if not creator_storage.delete_record(record_id): return jsonify({'error':'历史记录不存在。'}),404
    return jsonify({'success':True})


@history_blueprint.get('/history/<record_id>/download')
@auth_required
def download_images(record_id):
    record=creator_storage.get_record(record_id)
    if not record: return jsonify({'error':'历史记录不存在。'}),404
    task_id=(record.get('images') or {}).get('task_id'); files=(record.get('images') or {}).get('generated') or []
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for index, filename in enumerate(files):
            path=creator_storage.DATA/'cards'/str(task_id)/str(filename)
            if path.is_file(): archive.write(path, f'{index+1:02d}.png')
    output.seek(0)
    return send_file(output,mimetype='application/zip',as_attachment=True,download_name='图文图片.zip')
