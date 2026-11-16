import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock, RLock, Semaphore

from flask import Blueprint, Response, jsonify, request, send_file

from .. import creator_storage
from ..seedream_card import request_image
from .common import auth_required, safe_error

generation_blueprint = Blueprint('generation', __name__)
PROMPT_PATH = Path(__file__).resolve().parents[1] / 'prompts' / 'image_prompt.txt'
try:
    MAX_WORKERS = max(1, min(8, int(os.getenv('CARD_GENERATION_WORKERS', '1'))))
except ValueError:
    MAX_WORKERS = 1
try:
    REQUEST_INTERVAL = max(0.0, float(os.getenv('CARD_GENERATION_INTERVAL_SECONDS', '3')))
except ValueError:
    REQUEST_INTERVAL = 3.0


class ImageRequestLimiter:
    def __init__(self):
        self._slots = Semaphore(MAX_WORKERS)
        self._clock = Lock()
        self._last_started = 0.0

    def generate(self, prompt, references):
        with self._slots:
            with self._clock:
                wait = REQUEST_INTERVAL - (time.monotonic() - self._last_started)
                if self._last_started and wait > 0:
                    time.sleep(wait)
                self._last_started = time.monotonic()
            return request_image(prompt, references)


image_limiter = ImageRequestLimiter()


def _prompt(topic, page, index, total, outline, has_reference=False):
    page_types = {'cover': '封面', 'summary': '总结页', 'content': '内容页'}
    reference_instruction = (
        '本页提供了封面参考图。请借鉴其配色、字体气质、图形语言和整体氛围，保持整组视觉统一；不要复制参考图中的文字或照搬布局。'
        if has_reference else
        '本页是封面，请为整组建立清晰、可复用的视觉风格。'
        if page_types.get(page.get('type'), '内容页') == '封面' else
        '当前没有可用的封面参考图；仍请依据主题和完整大纲保持风格连贯。'
    )
    template = PROMPT_PATH.read_text(encoding='utf-8')
    values = {
        '{{topic}}': str(topic or '未提供'),
        '{{page_number}}': str(index + 1),
        '{{total_pages}}': str(total),
        '{{page_type}}': page_types.get(page.get('type'), '内容页'),
        '{{page_content}}': str(page.get('content') or ''),
        '{{full_outline}}': str(outline or ''),
        '{{reference_instruction}}': reference_instruction,
    }
    for key, value in values.items():
        template = template.replace(key, value)
    return template


def _image_path(task_id, index):
    folder = creator_storage.DATA / 'cards' / task_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f'page_{index + 1}.png'


def _cover_index(pages):
    return next((i for i, page in enumerate(pages) if page.get('type') == 'cover'), 0)


def _event(name, data):
    return f'event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


def _completed_filename(generated, index, task_id):
    filename = generated[index] if index < len(generated) else ''
    if not filename or not re.fullmatch(r'page_\d+\.png', filename):
        return None
    return filename if _image_path(task_id, index).is_file() else None


def _references(cover_bytes):
    return [{'data': cover_bytes, 'role': '封面风格参考'}] if cover_bytes else []


def _store_success(record, task_id, pages, index, filename, lock):
    with lock:
        images = record.setdefault('images', {'task_id': task_id, 'generated': []})
        images['task_id'] = task_id
        generated = images.setdefault('generated', [])
        while len(generated) < len(pages):
            generated.append('')
        generated[index] = filename
        record['outline'] = record.get('outline') or {'raw': '', 'pages': pages}
        record['status'] = 'completed' if all(generated[:len(pages)]) else 'draft'
        if index == _cover_index(pages):
            record['thumbnail'] = f'/api/images/{task_id}/{filename}'
        creator_storage.save_record(record)


@generation_blueprint.post('/generate')
@auth_required
def generate_pages():
    body = request.get_json(silent=True) or {}
    topic = str(body.get('topic') or '')
    outline = body.get('outline') or {}
    record_id = body.get('record_id')
    task_id = body.get('task_id')
    pages = outline.get('pages') or []
    if not isinstance(task_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', task_id):
        return jsonify({'error': '任务编号无效。'}), 422
    record = creator_storage.get_record(record_id or '')
    if not record or not pages:
        return jsonify({'error': '创作记录或大纲不存在，请返回重新打开。'}), 422

    def events():
        generated = list((record.get('images') or {}).get('generated') or [])
        while len(generated) < len(pages):
            generated.append('')
        lock = RLock()
        cover_index = _cover_index(pages)
        record['status'] = 'generating'
        record['task_id'] = task_id
        record['outline'] = outline
        record['page_count'] = len(pages)
        record['images'] = {'task_id': task_id, 'generated': generated}
        creator_storage.save_record(record)

        cover_bytes = None
        cover_filename = _completed_filename(generated, cover_index, task_id)
        if cover_filename:
            cover_bytes = _image_path(task_id, cover_index).read_bytes()
            yield _event('complete', {'index': cover_index, 'status': 'done',
                                      'image_url': f'/api/images/{task_id}/{cover_filename}', 'phase': 'cover'})
        else:
            yield _event('progress', {'index': cover_index, 'status': 'generating',
                                      'current': sum(bool(x) for x in generated), 'total': len(pages), 'phase': 'cover'})
            try:
                image, _meta = image_limiter.generate(
                    _prompt(topic, pages[cover_index], cover_index, len(pages), outline.get('raw', ''), False), []
                )
                path = _image_path(task_id, cover_index)
                path.write_bytes(image)
                filename = path.name
                _store_success(record, task_id, pages, cover_index, filename, lock)
                generated[cover_index] = filename
                cover_bytes = image
                yield _event('complete', {'index': cover_index, 'status': 'done',
                                          'image_url': f'/api/images/{task_id}/{filename}', 'phase': 'cover'})
            except Exception as error:
                record['status'] = 'draft'
                creator_storage.save_record(record)
                yield _event('error', {'index': cover_index, 'status': 'error',
                                       'error': safe_error(error, 300), 'phase': 'cover'})

        remaining = [i for i in range(len(pages)) if i != cover_index]
        pending = []
        for index in remaining:
            filename = _completed_filename(generated, index, task_id)
            if filename:
                yield _event('complete', {'index': index, 'status': 'done',
                                          'image_url': f'/api/images/{task_id}/{filename}', 'phase': 'content'})
                continue
            yield _event('progress', {'index': index, 'status': 'generating',
                                      'current': sum(bool(x) for x in generated), 'total': len(pages), 'phase': 'content'})
            pending.append(index)

        if pending:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                jobs = {}
                for index in pending:
                    prompt = _prompt(topic, pages[index], index, len(pages), outline.get('raw', ''), bool(cover_bytes))
                    future = executor.submit(image_limiter.generate, prompt, _references(cover_bytes))
                    jobs[future] = index
                for future in as_completed(jobs):
                    index = jobs[future]
                    try:
                        image, _meta = future.result()
                        path = _image_path(task_id, index)
                        path.write_bytes(image)
                        filename = path.name
                        _store_success(record, task_id, pages, index, filename, lock)
                        generated[index] = filename
                        yield _event('complete', {'index': index, 'status': 'done',
                                                  'image_url': f'/api/images/{task_id}/{filename}', 'phase': 'content'})
                    except Exception as error:
                        with lock:
                            record['status'] = 'draft'
                            creator_storage.save_record(record)
                        yield _event('error', {'index': index, 'status': 'error',
                                               'error': safe_error(error, 300), 'phase': 'content'})

        completed = sum(bool(_completed_filename(generated, i, task_id)) for i in range(len(pages)))
        with lock:
            record['status'] = 'completed' if completed == len(pages) else 'draft'
            creator_storage.save_record(record)
        yield _event('finish', {'task_id': task_id, 'completed': completed, 'total': len(pages)})

    return Response(events(), mimetype='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@generation_blueprint.post('/regenerate')
@auth_required
def regenerate_page():
    body = request.get_json(silent=True) or {}
    record = creator_storage.get_record(body.get('record_id', ''))
    if not record:
        return jsonify({'error': '历史记录不存在。'}), 404
    task_id = body.get('task_id')
    if not isinstance(task_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', task_id):
        return jsonify({'error': '任务编号无效。'}), 422
    try:
        page = body.get('page') or {}
        index = int(page.get('index', 0))
        pages = (record.get('outline') or {}).get('pages') or []
        if index < 0 or index >= len(pages):
            return jsonify({'error': '页面编号无效。'}), 422
        cover_index = _cover_index(pages)
        cover_path = _image_path(task_id, cover_index)
        cover_bytes = cover_path.read_bytes() if index != cover_index and cover_path.is_file() else None
        topic = str(body.get('topic') or record.get('title') or '')
        outline = str(body.get('full_outline') or (record.get('outline') or {}).get('raw') or '')
        image, _meta = image_limiter.generate(
            _prompt(topic, page, index, len(pages), outline, bool(cover_bytes)), _references(cover_bytes)
        )
        path = _image_path(task_id, index)
        path.write_bytes(image)
        images = record.setdefault('images', {'task_id': task_id, 'generated': []})
        images['task_id'] = task_id
        generated = images.setdefault('generated', [])
        while len(generated) < len(pages):
            generated.append('')
        generated[index] = path.name
        record['status'] = 'completed' if all(generated[:len(pages)]) else 'draft'
        if index == cover_index:
            record['thumbnail'] = f'/api/images/{task_id}/{path.name}'
        creator_storage.save_record(record)
        return jsonify({'image_url': f'/api/images/{task_id}/{path.name}'})
    except Exception as error:
        return jsonify({'error': safe_error(error)}), 502


@generation_blueprint.get('/images/<task_id>/<filename>')
@auth_required
def get_image(task_id, filename):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', task_id) or not re.fullmatch(r'page_\d+\.png', filename):
        return jsonify({'error': '图片地址无效。'}), 404
    path = creator_storage.DATA / 'cards' / task_id / filename
    if not path.is_file():
        return jsonify({'error': '图片不存在。'}), 404
    return send_file(path, mimetype='image/png', conditional=True)
