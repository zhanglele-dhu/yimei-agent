"""Collect public M22 literature metadata and build a source-addressable library.

python -m studio.collect_m22 --discover
python -m studio.collect_m22 --summarize
No login, paywall bypass, treatment presets, or user task writes.
"""
import argparse
import hashlib
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'outputs/studio/knowledge_base/m22'
CATEGORIES = ['设备与版本', '原理与光谱', '滤片与脉冲', '色素与黄褐斑', '泛红与血管',
              '痤疮与痘印', '光老化与肤质', '风险与适用人群', '护理与恢复',
              '眼科独立应用', '研究与注册', '专业讨论与常见问题']
QUERIES = [
    ('M22直接研究', '((M22 OR "Stellar M22") AND ("intense pulsed light" OR IPL)) OR TITLE_ABS:ResurFX'),
    ('IPL综述', 'TITLE_ABS:"intense pulsed light" AND (TITLE:"systematic review" OR TITLE:"meta-analysis" OR TITLE:"review") AND (TITLE_ABS:rosacea OR TITLE_ABS:melasma OR TITLE_ABS:acne OR TITLE_ABS:photorejuvenation OR TITLE_ABS:safety)'),
    ('关键论文', 'EXT_ID:39152889 OR EXT_ID:35913536 OR EXT_ID:34089264 OR EXT_ID:30091207 OR EXT_ID:41273013'),
]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def get_json(url):
    request = Request(url, headers={'User-Agent': 'YimeiAgent-M22-Knowledge/1.0 (public research metadata)'})
    with urlopen(request, timeout=45) as response:
        return json.load(response)


def plain(value):
    return ' '.join(html.unescape(re.sub('<[^>]+>', ' ', value or '')).split())


def discover(cutoff):
    records, searches, excluded = {}, [], []
    for label, query in QUERIES:
        cursor = '*'
        search = {'label': label, 'query': query, 'retrieved': 0, 'pages': 0, 'complete': False}
        try:
            for _ in range(8):
                url = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search?' + urlencode({
                    'query': '(' + query + f') AND FIRST_PDATE:[1900-01-01 TO {cutoff}]',
                    'format': 'json', 'resultType': 'core', 'pageSize': 100, 'cursorMark': cursor})
                data = get_json(url)
                search['hit_count'] = data['hitCount']
                search['pages'] += 1
                rows = data['resultList']['result']
                search['retrieved'] += len(rows)
                for item in rows:
                    key = (item.get('doi') or (item.get('source', '') + ':' + item['id'])).lower()
                    if item.get('isRetracted') == 'Y' or 'retracted' in item.get('title', '').lower():
                        excluded.append({'key': key, 'reason': 'retracted'})
                        continue
                    pmid = item.get('pmid') or (item['id'] if item.get('source') == 'MED' else '')
                    record = records.get(key)
                    if record is None:
                        record = {'id': 'M22-' + (pmid or hashlib.sha256(key.encode()).hexdigest()[:12]),
                            'title': plain(item.get('title')), 'doi': item.get('doi', ''), 'pmid': pmid,
                            'pmcid': item.get('pmcid', ''), 'authors': item.get('authorString', ''),
                            'journal': item.get('journalInfo', {}).get('journal', {}).get('title', ''),
                            'published_date': item.get('firstPublicationDate', ''), 'year': item.get('pubYear', ''),
                            'publication_types': item.get('pubTypeList', {}).get('pubType', []),
                            'abstract': plain(item.get('abstractText')), 'queries': [],
                            'url': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/' if pmid else f'https://europepmc.org/article/{item.get("source")}/{item["id"]}',
                            'retrieved_at': datetime.now(timezone.utc).isoformat(),
                            'access_level': 'abstract' if item.get('abstractText') else 'metadata_only'}
                        records[key] = record
                    record['queries'].append(label)
                next_cursor = data.get('nextCursorMark')
                if not rows or not next_cursor or next_cursor == cursor or search['retrieved'] >= data['hitCount']:
                    search['complete'] = True
                    break
                cursor = next_cursor
        except Exception as exc:
            search['error'] = type(exc).__name__ + ': ' + str(exc)[:160]
        searches.append(search)
        print(label, search, flush=True)
    payload = {'as_of': cutoff, 'searches': searches, 'excluded': excluded, 'records': list(records.values())}
    write_json(BASE / 'discovery.json', payload)
    return payload


class PaperCard(BaseModel):
    id: str
    title_zh: str = Field(max_length=120)
    categories: list[str]
    scope: str = Field(description='M22直接研究 / IPL通用研究 / ResurFX独立模块 / 眼科独立应用')
    design: str = Field(description='按摘要识别研究设计；未写明就写摘要未说明')
    population: str = Field(description='研究人群、样本量或综述纳入范围；不猜测')
    facts: list[str] = Field(min_length=1, max_length=8, description='中文概括摘要可支持的发现，建议1到3项；不添加摘要外结论，不输出操作剂量')
    limitations: list[str] = Field(max_length=8, description='具体的设计/随访/人群限制；无具体信息时说明只读到摘要')
    keywords: list[str]


class CardBatch(BaseModel):
    cards: list[PaperCard]


class CheckedCard(BaseModel):
    id: str
    facts: list[str] = Field(min_length=1, max_length=6)
    scope: str
    corrections: list[str] = Field(default_factory=list)


class CheckedBatch(BaseModel):
    cards: list[CheckedCard]


def audit_cards(discovery):
    """Second pass against each original abstract; records corrections, never medical certification."""
    from . import llm
    original = {r['id']:r for r in discovery['records']}
    pending = []
    for path in sorted((BASE/'cards').glob('*.json')):
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('kind') == 'paper' and record['id'] in original and record.get('abstract_check') != 'passed':
            pending.append((path, record))
    failures = []

    def audit(rows):
        result, trace = llm.generate(CheckedBatch, {
            'action': '对照原始英文摘要，逐篇核对中文知识卡facts。纠正数字、频次、比较关系、研究对象、联合干预归因和不恰当外推。'
                      '只保留摘要支持的发现，不补充摘要外医学事实。不输出通用免责声明。'
                      '公众科普卡保留样本量和研究发现即可，不提供能量/脉宽/治疗间隔处方。'
                      '注意three monthly sessions是每月一次共三次，不是每月三次。'
                      'scope只依据摘要/标题：写出M22才可标M22直接研究；只写IPL则IPL通用研究；眼科独立；ResurFX独立模块。'
                      '每篇facts不超过4项，每项80字以内。corrections简短记录纠正了什么，没改则为空。'},
            [{'id':r['id'], 'content': {'title':original[r['id']]['title'], 'abstract':original[r['id']]['abstract'],
                                       'proposed_facts':r['facts'], 'proposed_scope':r['scope']}} for _,r in rows])
        if {r.id for r in result.cards} != {r['id'] for _,r in rows} or len(result.cards) != len(rows):
            raise ValueError('核对结果id不匹配')
        by_id = {r.id:r for r in result.cards}
        for path, record in rows:
            checked = by_id[record['id']]
            record.update(facts=checked.facts, scope=checked.scope, abstract_check='passed',
                          abstract_check_model=trace.get('model', ''), corrections=checked.corrections)
            write_json(path, record)
        print('摘要对照完成', ','.join(by_id), flush=True)

    groups = [pending[i:i+4] for i in range(0, len(pending), 4)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [(rows, pool.submit(audit, rows)) for rows in groups]
        for rows, future in futures:
            try:
                future.result()
            except Exception as exc:
                failures.append({'ids':[r['id'] for _,r in rows], 'error':type(exc).__name__ + ': ' + str(exc)[:200]})
    write_json(BASE/'abstract_check_report.json', {'checked_candidates':len(pending), 'failures':failures,
               'method':'第二次模型调用对照原始摘要，非临床审查或全文审查'})


def candidates(discovery):
    selected = []
    for record in discovery['records']:
        abstract = record['abstract'].lower()
        title = record['title'].lower()
        if not abstract:
            continue
        direct = 'M22直接研究' in record['queries'] or any(term in title + ' ' + abstract for term in ('m22', 'resurfx', 'lumenis'))
        background = ('intense pulsed light' in title and any(term in title for term in ('review', 'meta-analysis')))
        if direct or background or '关键论文' in record['queries']:
            selected.append(record)
    # Direct platform literature first, then recent background reviews; keep all in discovery.
    selected.sort(key=lambda r: (any(t in r['title'].lower() for t in ('meibomian', 'dry eye', 'ocular', 'eyelid', 'chalazion', 'hordeolum', 'blephar')),
                                 'm22' not in (r['title'] + r['abstract']).lower(), -int(r.get('year') or 0), r['id']))
    return selected


def summarize(discovery, limit=250):
    from . import llm
    selected = candidates(discovery)[:limit]
    cards_dir = BASE / 'cards'
    cards_dir.mkdir(parents=True, exist_ok=True)
    pending = [r for r in selected if not (cards_dir / (r['id'] + '.json')).exists()]
    groups = [pending[i:i+4] for i in range(0, len(pending), 4)]
    failures = []

    def batch(rows):
        result, trace = llm.generate(CardBatch, {
            'action': '为M22知识库建立逐篇中文资料卡。仅概括所给摘要，不把背景引用当本文发现。'
                      '每篇必须一一对应id。直接讲清研究做了什么、发现什么，保留研究范围。'
                      '不输出“无官方医学依据”“未经独立核实”等空泛免责声明。'
                      '不写治疗能量/脉宽处方，不推断中国注册适应证，不把眼科结论外推到皮肤。'
                      '每个facts条目80汉字以内；只选择当前文献真正涉及的分类，不为凑分类扩展内容。',
            'allowed_categories': CATEGORIES,
        }, [{'id': r['id'], 'content': {k:r[k] for k in ('title','abstract','publication_types','url')}} for r in rows])
        if {c.id for c in result.cards} != {r['id'] for r in rows} or len(result.cards) != len(rows):
            raise ValueError('资料卡id与输入不一致')
        by_id = {r['id']: r for r in rows}
        for card in result.cards:
            if not set(card.categories) <= set(CATEGORIES):
                raise ValueError('不支持的分类')
            record = by_id[card.id]
            payload = {k:v for k,v in record.items() if k != 'abstract'}
            payload.update(card.model_dump())
            payload.update(kind='paper', extraction='AI摘要整理，链接与书目来自Europe PMC/PubMed',
                           evidence_use='研究发现，按本文人群与设计表述',
                           abstract_excerpt=' '.join(record['abstract'].split()[:150]),
                           extraction_model=trace.get('model', ''),
                           summary_input_sha256=hashlib.sha256(record['abstract'].encode()).hexdigest())
            write_json(cards_dir / (card.id + '.json'), payload)
        print('资料卡完成', ','.join(by_id), flush=True)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [(rows, pool.submit(batch, rows)) for rows in groups]
        for rows, future in futures:
            try:
                future.result()
            except Exception as exc:
                failures.append({'ids':[r['id'] for r in rows], 'error':type(exc).__name__ + ': ' + str(exc)[:200]})
                print('资料卡失败', failures[-1], flush=True)
    write_json(BASE / 'summary_report.json', {'eligible': len(candidates(discovery)), 'selected':len(selected), 'failures':failures})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--discover', action='store_true')
    parser.add_argument('--summarize', action='store_true')
    parser.add_argument('--audit', action='store_true')
    parser.add_argument('--as-of', default=date.today().isoformat())
    parser.add_argument('--limit', type=int, default=250)
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    discovery = discover(args.as_of) if args.discover else json.loads((BASE/'discovery.json').read_text(encoding='utf-8'))
    if args.summarize:
        summarize(discovery, args.limit)
    if args.audit:
        audit_cards(discovery)


if __name__ == '__main__':
    main()
