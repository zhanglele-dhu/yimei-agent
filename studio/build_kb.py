"""知识库构建流水线：语料 → 大模型分类 → 切片 → 向量化 → 落库 → 召回率自检。

用法（在项目根目录）：
    .venv-studio/Scripts/python.exe -m studio.build_kb

流水线（对应简历声明"数据清洗与知识库构建 / 大模型分类 / 向量切片 / 召回策略"）：
  1) 清洗：去掉一级标题与多余空白；
  2) 大模型分类：DeepSeek 给每篇语料判定类别、写摘要、抽关键词（结构化合同校验）；
  3) 切片：字符窗口+重叠（knowledge.chunk_text），每块前缀"[类别|文件名]"提升检索区分度；
  4) 向量化：智谱 embedding-3（knowledge.embed_texts），分批调用；
  5) 落库：KnowledgeStore（meta.json + vectors.json）；
  6) 召回率自检：金标问题集检索 top_k，统计期望关键词命中率（跑出来的真实数字）。
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from .knowledge import KnowledgeStore, chunk_text, embed_texts

ROOT = Path(__file__).resolve().parents[1]

# 金标召回率检查集：问题 → 命中任一期望关键词即算该题召回
GOLDEN = [
    {'q': 'M22的滤光片有哪些波长？', 'expect': ['515', '560', '695']},
    {'q': 'Vascular 血管滤光片是做什么的？', 'expect': ['血管', '530-650']},
    {'q': '做完光子嫩肤之后怎么防晒？', 'expect': ['SPF30', '防晒']},
    {'q': '光子嫩肤反黑是怎么回事？', 'expect': ['反黑', '色素沉着']},
    {'q': '光子嫩肤多少钱一次？', 'expect': ['1000-3000', '价格', '1980']},
    {'q': '光子嫩肤的原理是什么？', 'expect': ['选择性光热', '强脉冲光']},
    {'q': '哪些人不适合做光子嫩肤？', 'expect': ['孕妇', '光敏']},
    {'q': '医美科普内容有什么合规红线？', 'expect': ['医疗广告', '容貌焦虑']},
    {'q': 'AOPT和OPT有什么区别？', 'expect': ['完美脉冲', '只有M22']},
    {'q': 'Acne痤疮双效管理的双波原理是什么？', 'expect': ['卟啉', '400-600']},
    {'q': 'M22全面部治疗一次需要多久？', 'expect': ['15-20', '20-30']},
    {'q': 'Vascular血管滤光片治疗的终点是什么？', 'expect': ['变深或变白', '凝固', '回流']},
]


class DocClass(BaseModel):
    category: str = Field(description='文档类别，10字内，如：设备参数/治疗原理/适应症禁忌/术后护理/价格疗程/咨询面诊/合规法规/副作用风险')
    summary: str = Field(description='一句话摘要，60字内')
    keywords: list[str] = Field(description='3-6个检索关键词')


def read_corpus(corpus_dir):
    docs = []
    for fp in sorted(Path(corpus_dir).glob('*.md')):
        raw = fp.read_text(encoding='utf-8', errors='replace')
        source_line = next((l for l in raw.splitlines() if l.startswith('来源:')), f'来源: {fp.name}')
        body_start = raw.find('---', 3)
        body = raw[body_start + 3:].strip() if body_start > 0 else raw
        docs.append({'file': fp.name, 'source': source_line.strip(), 'body': body})
    return docs


def classify_docs(docs):
    """DeepSeek 逐篇分类。单篇失败不阻断：类别记为未分类。"""
    from . import llm
    results = {}
    for d in docs:
        try:
            parsed, trace = llm.generate(DocClass, {
                'action': '为医美知识库文档分类。只输出 JSON。',
                'file': d['file'], 'body': d['body'][:3000]}, [])
            results[d['file']] = {'category': parsed.category, 'summary': parsed.summary,
                                  'keywords': parsed.keywords, 'elapsed_ms': trace.get('elapsed_ms')}
            print(f"  分类 {d['file']} -> {parsed.category}")
        except Exception as exc:
            results[d['file']] = {'category': '未分类', 'summary': '', 'keywords': [],
                                  'error': str(exc)[:120]}
            print(f"  分类失败 {d['file']}: {str(exc)[:80]}（继续）")
    return results


def clean_body(body):
    lines = [l for l in body.splitlines() if not l.startswith('# ')]
    return ' '.join(' '.join(lines).split())


def build(corpus_dir, store_dir):
    docs = read_corpus(corpus_dir)
    print(f'语料 {len(docs)} 篇')
    classes = classify_docs(docs)

    texts, metas = [], []
    for d in docs:
        info = classes[d['file']]
        prefix = f"[{info['category']}|{d['file']}] "
        for chunk in chunk_text(clean_body(d['body'])):
            texts.append(prefix + chunk['text'])
            metas.append({'text': prefix + chunk['text'], 'pos': chunk['pos'],
                          'source': d['file'], 'category': info['category'],
                          'summary': info['summary'], 'source_line': d['source'],
                          'keywords': info['keywords']})
    print(f'切片 {len(texts)} 块（窗口500/重叠80）')

    vectors = []
    batch = 16
    for i in range(0, len(texts), batch):
        vectors.extend(embed_texts(texts[i:i + batch]))
        print(f'  向量化 {min(i + batch, len(texts))}/{len(texts)}')

    store = KnowledgeStore()
    for meta, vec in zip(metas, vectors):
        store.add([{'text': meta['text'], 'pos': meta['pos']}], [vec],
                  source=json.dumps({'file': meta['source'], 'category': meta['category'],
                                     'summary': meta['summary'], 'source_line': meta['source_line'],
                                     'keywords': meta['keywords']}, ensure_ascii=False))
    store.save(store_dir)
    print(f'落库 {len(store)} 块 -> {store_dir}')
    return store, classes


def recall_check(store_dir, top_k=6):
    """金标召回率：每题检索 top_k，命中任一期望关键词即算召回。返回 (recall, 明细)。"""
    store = KnowledgeStore.load(store_dir)
    hits, details = 0, []
    for g in GOLDEN:
        q = g['q']
        qvec = embed_texts([q])[0]
        top = store.search(qvec, top_k=top_k, query_text=q)
        joined = ' '.join(h['text'] for h in top)
        hit = any(kw in joined for kw in g['expect'])
        hits += hit
        details.append({'q': q, 'recall': hit,
                        'top': [{'score': h['score'], 'lex': h.get('lex', 0), 'meta': str(h['meta'])[:60]} for h in top[:2]]})
        print(f"  {'PASS' if hit else 'MISS'} {q}")
    recall = round(hits / len(GOLDEN) * 100, 1)
    print(f'召回率（top_{top_k}，两段式召回+词法精排，命中任一关键词）：{recall}% ({hits}/{len(GOLDEN)})')
    return recall, details


def main():
    parser = argparse.ArgumentParser(description='构建医美知识库（分类+切片+向量化+召回自检）')
    parser.add_argument('--corpus', default=str(ROOT / 'outputs/studio/knowledge_base/corpus'))
    parser.add_argument('--store', default=str(ROOT / 'outputs/studio/knowledge_base/store'))
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')

    build(args.corpus, args.store)
    recall, details = recall_check(args.store)
    report = {'built_at': datetime.now(timezone.utc).astimezone().isoformat(),
              'recall_rate': recall, 'golden_details': details}
    out = Path(args.store) / 'recall_report.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('召回报告：', out)


if __name__ == '__main__':
    main()
