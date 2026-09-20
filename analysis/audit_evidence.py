"""Read-only audit of source assets; write separately named verified outputs."""
import csv
import hashlib
import html
import json
import statistics
from collections import Counter
from pathlib import Path

from PIL import Image

BASE = Path(__file__).resolve().parent
SOURCE = BASE.parent / 'reference_notes' / '20260915_203358_208240.json'


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def parts(value):
    return [s.strip() for s in (value or '').split('|') if s.strip()]


def main():
    raw = json.loads(SOURCE.read_text(encoding='utf-8'))['items']
    selected = read_csv(BASE / 'filtered_likes50.csv')
    ocr = read_csv(BASE / 'ocr_output.csv')
    keys = [r['image_path'] for r in ocr]
    errors = []
    if len(keys) != len(set(keys)):
        errors.append('duplicate_ocr_paths')
    expected = sorted([r for r in raw if isinstance(r.get('likes'), (int, float)) and r['likes'] >= 50],
                      key=lambda r: -r['likes'])
    if [r['url'] for r in selected] != [r['url'] for r in expected]:
        errors.append('selection_or_order_mismatch')
    by_path = {r['image_path']: r for r in ocr}
    index, combined = [], []
    for i, row in enumerate(selected):
        paths, urls = parts(row['image_local_paths']), parts(row['image_urls'])
        if len(paths) != len(urls):
            errors.append(f'row_{i}_image_alignment')
        texts = []
        for j, path in enumerate(paths):
            p = Path(path)
            entry = dict(row_index=i, img_index=j, image_path=path,
                         image_url=urls[j] if j < len(urls) else '',
                         note_url=row['url'], likes=row['likes'])
            try:
                with Image.open(p) as image:
                    image.load()  # Decode every image, not just check existence.
                    entry.update(width=image.width, height=image.height, format=image.format)
                entry.update(sha256=hashlib.sha256(p.read_bytes()).hexdigest(), image_status='decoded')
            except Exception as exc:
                entry.update(image_status='failed', error=str(exc))
                errors.append(f'image_{i}_{j}_failed')
            rec = by_path.get(path)
            if rec is None or int(rec['row_index']) != i or int(rec['img_index']) != j:
                errors.append(f'ocr_{i}_{j}_missing_or_misaligned')
            txt = rec['ocr_text'] if rec else ''
            entry.update(ocr_text=txt, ocr_status='legacy_text' if txt else 'empty_unverified')
            texts.append(txt)
            index.append(entry)
        combined.append(dict(row_index=i, title=row['title'], content=row['content'], url=row['url'],
                             likes=int(row['likes']), favorites=expected[i].get('favorites'),
                             comments=expected[i].get('comments'), image_count=len(paths),
                             ocr_combined='\n=====\n'.join(texts)))
    if len(index) != len(ocr):
        errors.append('image_ocr_count_mismatch')
    groups = {'high': expected, 'low': [r for r in raw if r.get('likes') is not None and r['likes'] < 50]}
    stats = {}
    for name, rows in groups.items():
        stats[name] = {'n': len(rows)}
        for field in ('likes', 'favorites', 'comments'):
            values = [r[field] for r in rows if isinstance(r.get(field), (float, int))]
            stats[name][field] = {'available_n': len(values), 'missing_n': len(rows)-len(values),
                                 'mean': round(statistics.mean(values), 2) if values else None,
                                 'median': statistics.median(values) if values else None}
        stats[name]['author_name_medical_terms_n'] = sum(any(k in (r.get('author') or '')
                                                          for k in ('医生', '主任', '医师')) for r in rows)
        stats[name]['body_keyword_counts'] = {k: sum(k in (r.get('content') or '') for r in rows)
                                               for k in ('注意事项', '术后', '怎么选', '避坑', '体验', '对比', '多少钱')}
    stats['ocr'] = {'note_n': len(combined), 'image_n': len(index),
                    'empty_image_n': sum(not r['ocr_text'].strip() for r in index),
                    'notes_over_10_newlines': sum(r['ocr_combined'].count('\n') > 10 for r in combined),
                    'warning': 'OCR换行数量不是图片形态标注；无低赞组OCR对照。'}
    stats['image_likes_pearson_high_only'] = round(statistics.correlation(
        [len(r.get('image_urls', [])) for r in expected], [r['likes'] for r in expected]), 3)
    stats['audit'] = {'source_n': len(raw), 'source_missing_likes': sum(r.get('likes') is None for r in raw),
                      'decoded_images': sum(r['image_status'] == 'decoded' for r in index),
                      'ocr_unique_paths': len(set(keys)), 'errors': errors,
                      'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest()}
    (BASE / 'verified_stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    (BASE / 'verified_row_text.json').write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding='utf-8')
    with (BASE / 'verified_image_index.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=sorted(set().union(*(r.keys() for r in index))))
        writer.writeheader()
        writer.writerows(index)
    cards = []
    for r in index:
        rel = Path(r['image_path']).relative_to(BASE).as_posix()
        cards.append(f'<article><h2>row{r["row_index"]:03d} / 图{r["img_index"]+1} · 赞{r["likes"]}</h2>'
                     f'<a href="{html.escape(rel, quote=True)}"><img loading="lazy" src="{html.escape(rel, quote=True)}"></a>'
                     f'<pre>{html.escape(r["ocr_text"])}</pre></article>')
    (BASE / 'image_review.html').write_text('<!doctype html><meta charset="utf-8"><title>图片与OCR逐张核对</title>'
        '<style>body{font-family:system-ui;background:#f3f5f7;padding:24px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px}'
        'article{background:white;padding:16px}img{width:100%;max-height:650px;object-fit:contain}pre{white-space:pre-wrap}</style>'
        '<h1>逐图索引：实图与非大模型OCR</h1><p>仅供内部研究；OCR文字不代表医学事实。</p><main>'
        + ''.join(cards) + '</main>', encoding='utf-8')
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
