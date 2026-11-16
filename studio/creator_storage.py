"""与旧任务表分开的图文记录存储；用于新创作台的服务端历史 API。"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv('STUDIO_DATA_DIR', str(ROOT / 'outputs' / 'studio'))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
DATABASE = DATA / 'tasks.sqlite3'


def _now():
    return datetime.now(timezone.utc).isoformat()


def _connect():
    conn = sqlite3.connect(DATABASE, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE IF NOT EXISTS creator_records (id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, body TEXT NOT NULL)')
    return conn


def save_record(record):
    record['updated_at'] = _now()
    with _connect() as conn:
        conn.execute('INSERT INTO creator_records(id,updated_at,body) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, body=excluded.body',
                     (record['id'], record['updated_at'], json.dumps(record, ensure_ascii=False)))
    return record


def get_record(record_id):
    with _connect() as conn:
        row = conn.execute('SELECT body FROM creator_records WHERE id=?', (record_id,)).fetchone()
    return json.loads(row['body']) if row else None


def list_records(page=1, page_size=24, keyword='', status=''):
    page = max(1, page); page_size = min(100, max(1, page_size)); keyword = '%' + keyword.strip() + '%'
    with _connect() as conn:
        total = conn.execute('SELECT count(*) FROM creator_records WHERE body LIKE ?', (keyword,)).fetchone()[0]
        if status in ('completed', 'draft'):
            rows = conn.execute('SELECT body FROM creator_records WHERE body LIKE ? ORDER BY updated_at DESC', (keyword,)).fetchall()
        else:
            rows = conn.execute('SELECT body FROM creator_records WHERE body LIKE ? ORDER BY updated_at DESC LIMIT ? OFFSET ?',
                                (keyword, page_size, (page - 1) * page_size)).fetchall()
    records = [json.loads(row['body']) for row in rows]
    if status in ('completed', 'draft'):
        records = [record for record in records if record.get('status') == status]
        total = len(records)
        records = records[(page - 1) * page_size:page * page_size]
    summaries = [{key: record.get(key) for key in ('id','title','created_at','updated_at','status','thumbnail','page_count','task_id')} for record in records]
    return {'records': summaries, 'total': total, 'page': page, 'total_pages': (total + page_size - 1) // page_size}


def delete_record(record_id):
    record = get_record(record_id)
    if not record:
        return False
    with _connect() as conn:
        conn.execute('DELETE FROM creator_records WHERE id=?', (record_id,))
    task_id = (record.get('images') or {}).get('task_id')
    if task_id:
        import shutil
        shutil.rmtree(DATA / 'cards' / task_id, ignore_errors=True)
    return True
