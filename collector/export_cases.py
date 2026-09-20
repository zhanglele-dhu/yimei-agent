"""Export a portable evidence bundle. Never writes into the creation workspace."""
import argparse
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent


def build_bundle(source: Path, destination: Path):
    with (source / 'filtered_likes50.csv').open(encoding='utf-8-sig') as f:
        notes = list(csv.DictReader(f))
    with (source / 'ocr_output.csv').open(encoding='utf-8-sig') as f:
        ocr = list(csv.DictReader(f))
    keys = [(int(r['row_index']), int(r['img_index'])) for r in ocr]
    if len(keys) != len(set(keys)):
        raise ValueError('OCR页码重复，请先核对数据')
    review_file = source / 'report/pattern_review/patterns_review.json'
    reviews = json.loads(review_file.read_text(encoding='utf-8'))['cases'] if review_file.exists() else []
    review_map = {r['source']['row_id']: r for r in reviews}
    cases, images = [], {}
    for i, note in enumerate(notes):
        case_id = f'row{i:03d}'
        paths = [p.strip() for p in note['image_local_paths'].split('|') if p.strip()]
        evidence_pages = []
        for j, old_path in enumerate(paths):
            # Portable fallback for copied datasets; never include arbitrary files from the CSV.
            name = Path(old_path).name
            path = (source / 'images' / name).resolve()
            if path.parent != (source / 'images').resolve():
                raise ValueError('图片路径越界')
            records = [r for r in ocr if int(r['row_index']) == i and int(r['img_index']) == j]
            entry = {'number': j + 1, 'ocr': records[0]['ocr_text'] if records else '',
                     'ocr_status': 'available' if records and records[0]['ocr_text'].strip() else 'missing',
                     'image': None, 'image_sha256': None, 'image_status': 'missing'}
            if path.is_file():
                raw = path.read_bytes()
                with Image.open(io.BytesIO(raw)) as im:
                    im.verify()
                member = f'images/{case_id}_{j+1:02d}{path.suffix.lower()}'
                images[member] = raw
                entry.update(image=member, image_sha256=hashlib.sha256(raw).hexdigest(), image_status='available')
            evidence_pages.append(entry)
        likes = int(note['likes']) if note['likes'].strip().isdigit() else None
        research = review_map.get(case_id)
        if research:
            research = json.loads(json.dumps(research))
            evidence = research.get('ocr_evidence', {})
            evidence.pop('local_image', None)
            evidence['bundle_page'] = evidence.get('page_number')
        cases.append({'id': case_id, 'title': note['title'], 'body': note['content'],
                      'url': note['url'], 'author': note['author'], 'likes': likes,
                      'collected_at': note['collected_at'], 'pages': evidence_pages,
                      'research': research, 'status': 'reference_only'})
    if not cases:
        raise ValueError('无可导出案例')
    manifest = {'schema_version': 1, 'source_dataset_sha256': hashlib.sha256((source / 'filtered_likes50.csv').read_bytes()).hexdigest(),
                'scope': '已采集且点赞>=50的搜索样本，不代表全平台',
                'selection_metric': '采集快照点赞数，缺失不视为零', 'cases': cases}
    serialized = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode('utf-8')
    manifest['version'] = hashlib.sha256(serialized).hexdigest()[:16]
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix('.tmp')
    with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as z:
        def write(name, data):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
        write('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        for name, raw in images.items():
            write(name, raw)
    temp.replace(destination)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'data/m22_analysis')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/exports/m22_cases.zip')
    args = parser.parse_args()
    result = build_bundle(args.source, args.output)
    print(f"Exported {len(result['cases'])} cases, version {result['version']}: {args.output}")
