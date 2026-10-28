"""Source-aware M22 retrieval alongside the historical knowledge store."""
import hashlib
import json
from collections import Counter
from pathlib import Path

from .knowledge import KnowledgeStore, _hashing_embed

TOPIC_TERMS = {
    '设备与版本': '设备 仪器 版本 王者 OPT AOPT Stellar 平台 配置 区别 M22',
    '原理与光谱': '原理 是什么 光热 黑色素 血红蛋白 激光 IPL 机制 光谱',
    '滤片与脉冲': '滤片 滤光片 波长 波段 脉冲 双波 515 560 590 615 640 695 755',
    '色素与黄褐斑': '斑 色素 黄褐斑 雀斑 晒斑 melasma pigmentation',
    '泛红与血管': '泛红 血管 红血丝 玫瑰痤疮 酒糟 红斑 rosacea vascular',
    '痤疮与痘印': '痘 痤疮 痘印 acne',
    '光老化与肤质': '抗衰 光老化 肤质 细纹 毛孔 photoaging rejuvenation',
    '风险与适用人群': '风险 反黑 色沉 灼伤 水疱 不良反应 禁忌 适合 敏感 妊娠 安全',
    '护理与恢复': '术后 护理 恢复 防晒 保湿 化妆 清洁',
    '眼科独立应用': '干眼 眼科 睑板腺 meibomian dry eye',
    '研究与注册': '注册 认证 FDA NMPA 批准 临床试验',
    '专业讨论与常见问题': '论坛 经验 讨论 常见问题 医生问答',
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def build_library(base):
    base = Path(base)
    all_records = [read_json(p) for p in sorted((base / 'cards').glob('*.json'))]
    records = [r for r in all_records if r.get('kind') != 'paper' or r.get('abstract_check') == 'passed']
    if not records:
        raise ValueError('没有可入库的资料卡')
    ids = [r['id'] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError('来源id重复')
    store = KnowledgeStore()
    for record in records:
        if not record.get('url') or not record.get('facts') or not record.get('categories'):
            raise ValueError('资料卡缺少链接、知识内容或分类：' + record['id'])
        text = ' '.join([record.get('title_zh', record['title']), ' '.join(record['categories']),
                         ' '.join(record.get('keywords', [])), ' '.join(record['facts'])])
        store.add([{'text': text, 'pos': 0}], _hashing_embed([text]), source=json.dumps(record, ensure_ascii=False))
    version = hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
    store_dir = 'store-' + version
    store.save(base / store_dir)
    manifest = {'version': 'm22-evidence-v1', 'records': len(records), 'backend': 'hashing-512', 'store_dir': store_dir,
                'pending_abstract_check': len(all_records) - len(records),
                'source_types': dict(Counter(r['kind'] for r in records)),
                'categories': dict(Counter(c for r in records for c in r['categories'])),
                'note': '书目和来源已联网采集；论文卡为摘要级整理，个别人工卡记录所读页节。'}
    temporary = base / 'manifest.tmp'
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(base / 'manifest.json')
    folders = base / '分类资料'
    for category in TOPIC_TERMS:
        folder = folders / category
        folder.mkdir(parents=True, exist_ok=True)
        for record in records:
            if category not in record['categories']:
                continue
            lines = ['# ' + record.get('title_zh', record['title']), '',
                     '来源：[' + record['title'] + '](' + record['url'] + ')',
                     '资料类型：' + record['kind'] + '；范围：' + record.get('scope', ''),
                     '阅读范围：' + record.get('access_level', ''),
                     '日期：' + record.get('published_date', record.get('year', '')),
                     '采集日期：' + record.get('retrieved_at', ''), '', '## 可用于创作的知识', '']
            lines.extend('- ' + fact for fact in record['facts'])
            if record.get('design'):
                lines.extend(['', '研究设计：' + record['design'], '研究范围：' + record.get('population', '')])
            if record.get('limitations'):
                lines.extend(['', '## 使用范围', ''] + ['- ' + item for item in record['limitations']])
            if record.get('doi'):
                lines.extend(['', 'DOI：' + record['doi']])
            (folder / (record['id'] + '.md')).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    index = ['# M22 分类知识库', '', manifest['note'], '',
             f'当前入库 {len(records)} 个可追溯来源。书目检索记录、未入卡条目和错误见 discovery.json 与 summary_report.json。',
             '', '| 分类 | 条目数 |', '|---|---:|']
    index.extend(f'| [{category}](分类资料/{category}/) | {manifest["categories"].get(category, 0)} |' for category in TOPIC_TERMS)
    index.extend(['', '## 全部来源', '', '| 编号 | 类型 | 标题 |', '|---|---|---|'])
    index.extend(f'| {r["id"]} | {r["kind"]} | [{r.get("title_zh", r["title"])}]({r["url"]}) |' for r in records)
    index.extend(['', '## 更新', '', '`python -m studio.collect_m22 --discover --summarize --audit --as-of YYYY-MM-DD`',
                  '', '重新整理后运行 `python -m studio.evidence` 建立分类文件和检索索引。',
                  '', '未覆盖项：付费全文、登录后论坛、完整的中国注册证附件与门店实际设备配置。未把这些项目标记为已采集。'])
    (base / 'README.md').write_text('\n'.join(index) + '\n', encoding='utf-8')
    return manifest


def import_seeds(base, source_file):
    from datetime import datetime, timezone
    base = Path(base)
    (base / 'cards').mkdir(parents=True, exist_ok=True)
    for record in read_json(source_file):
        record = {**record, 'title_zh': record['title'], 'retrieved_at': '2026-10-24',
                  'extraction': '按所列网页或PDF节选人工整理', 'indexed_at': datetime.now(timezone.utc).isoformat()}
        (base / 'cards' / (record['id'] + '.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')


def search_library(base, question, top_k=8):
    base = Path(base)
    manifest = read_json(base / 'manifest.json')
    store = KnowledgeStore.load(base / manifest.get('store_dir', 'store'))
    query = question.lower()
    requested = {category for category, terms in TOPIC_TERMS.items()
                 if any(term.lower() in query for term in terms.split() if len(term) > 1 and term != 'M22')}
    ocular = '眼科独立应用' in requested
    discussion = '专业讨论与常见问题' in requested
    if not requested or requested == {'设备与版本'}:
        requested |= {'设备与版本', '原理与光谱', '滤片与脉冲'}
    expanded = question + ' ' + ' '.join(TOPIC_TERMS[c] for c in requested)
    hits = store.search(_hashing_embed([expanded])[0], top_k=len(store), query_text=expanded)
    ranked = []
    technical = requested <= {'设备与版本', '原理与光谱', '滤片与脉冲'} and not any(word in query for word in ('论文','研究','证据'))
    for hit in hits:
        record = json.loads(hit['meta']['source'])
        categories = set(record['categories'])
        if ('眼科独立应用' in categories or record.get('scope') == '眼科独立应用') and not ocular:
            continue
        if record['kind'] == 'discussion' and not discussion:
            continue
        overlap = len(requested & categories)
        if not overlap:
            continue
        authority = {'consensus': .13, 'official': .12, 'regulatory': .10, 'paper': .06, 'education': .02, 'discussion': 0}.get(record['kind'], 0)
        if technical and record['kind'] in ('official', 'education', 'consensus', 'regulatory'):
            authority += .65
        # The original request must outrank broad expansion vocabulary.
        original_grams = {query[i:i+2] for i in range(len(query)-1)}
        text = ' '.join([record.get('title_zh', ''), ' '.join(record.get('keywords', [])), ' '.join(record['facts'])]).lower()
        direct_match = sum(gram in text for gram in original_grams) / max(1, len(original_grams))
        headline = (record.get('title_zh', '') + ' ' + record['title']).lower()
        headline_match = sum(term.lower() in query and term.lower() in headline
                             for category in requested for term in TOPIC_TERMS[category].split() if len(term)>1)
        record['retrieval_score'] = round(direct_match * 1.8 + hit.get('lex', 0) * .35 + hit['score'] * .15 + overlap * .18 + authority + min(.9, headline_match * .3), 4)
        ranked.append(record)
    ranked.sort(key=lambda r: -r['retrieval_score'])
    # Cover the requested dimensions before filling with similar papers.
    selected, used = [], set()
    for category in sorted(requested):
        candidate = next((r for r in ranked if category in r['categories'] and r['id'] not in used), None)
        if candidate:
            selected.append(candidate)
            used.add(candidate['id'])
    for record in ranked:
        if record['id'] not in used:
            selected.append(record)
            used.add(record['id'])
        if len(selected) >= top_k:
            break
    return selected[:top_k]


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    base = root / 'outputs/studio/knowledge_base/m22'
    import_seeds(base, root / 'knowledge/m22_source_seeds.json')
    print(json.dumps(build_library(base), ensure_ascii=False, indent=2))
