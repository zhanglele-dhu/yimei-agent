"""知识库 v1：把资料切成块、算成向量、存起来、按语义检索。

这是简历声明"知识库构建 / 切片与召回策略"的真实地基。v1 刻意手写：
- 切片：按字符窗口 + 重叠（chunk/overlap），简单可解释；
- 向量：智谱 embedding-3（OpenAI 兼容接口，复用 VISION_API_KEY）；
- 检索：纯 Python 余弦相似度，小语料（千级块）毫秒级；语料上万再升级专用向量库。
召回质量的度量走金标问题集（评测器后续接入），"召回率"会是跑出来的数字。
"""
import json
import os
from pathlib import Path

DEFAULT_CHUNK_CHARS = 500
DEFAULT_CHUNK_OVERLAP = 80


def chunk_text(text, size=DEFAULT_CHUNK_CHARS, overlap=DEFAULT_CHUNK_OVERLAP):
    """把长文本切成带重叠的窗口块。返回 [{'text': 块文本, 'pos': 第几块}]。
    短文本（<= size）原样成一块；重叠保证跨块的句子在相邻两块里都能被检索到。"""
    cleaned = ' '.join((text or '').split())
    if not cleaned:
        return []
    if size <= overlap:
        raise ValueError('切片窗口必须大于重叠')
    chunks = []
    start = 0
    while start < len(cleaned):
        piece = cleaned[start:start + size].strip()
        if piece:
            chunks.append({'text': piece, 'pos': len(chunks)})
        if start + size >= len(cleaned):
            break
        start += size - overlap
    return chunks


def embed_texts(texts):
    """把一批文本变成向量。后端可插拔：
    - hashing（默认，离线免费）：字符二元组哈希到 512 维并归一化——词法级检索，
      稳定永不断供，小而准的语料（几十~几百块）效果够用；
    - zhipu（真语义向量，需 STUDIO_EMBED_BACKEND=zhipu）：智谱 embedding-3，
      需要 EMBED_API_KEY/VISION_API_KEY 且账户有 embedding 资源包（2026-10-10 实测余额不足会 429）。
    两种后端都是"文本→定长向量"，余弦检索与存储格式完全一致，可随时切换重建。"""
    if not texts:
        return []
    backend = os.getenv('STUDIO_EMBED_BACKEND', 'hashing').lower()
    if backend == 'zhipu':
        from openai import OpenAI
        api_key = os.getenv('EMBED_API_KEY') or os.getenv('VISION_API_KEY')
        if not api_key:
            raise RuntimeError('zhipu 向量化需要 EMBED_API_KEY 或 VISION_API_KEY')
        client = OpenAI(api_key=api_key, base_url='https://open.bigmodel.cn/api/paas/v4', timeout=120, max_retries=0)
        model = os.getenv('STUDIO_EMBED_MODEL', 'embedding-3')
        response = client.embeddings.create(model=model, input=list(texts))
        return [item.embedding for item in response.data]
    return _hashing_embed(texts)


def _hashing_embed(texts, dims=512):
    """离线词法向量：字符二元组 md5 哈希分桶计数 + L2 归一化。"""
    import hashlib
    vectors = []
    for t in texts:
        clean = (t or '').replace(' ', '')
        v = [0.0] * dims
        for i in range(len(clean) - 1):
            bigram = clean[i:i + 2]
            bucket = int(hashlib.md5(bigram.encode('utf-8')).hexdigest(), 16) % dims
            v[bucket] += 1.0
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        vectors.append([round(x / norm, 6) for x in v])
    return vectors


def cosine(a, b):
    """纯 Python 余弦相似度：1=完全同向，0=无关。零向量返回 0。"""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


class KnowledgeStore:
    """知识库：块文本 + 向量，可保存/加载/语义检索。文件形态：meta.json + vectors.json。"""

    def __init__(self):
        self.meta = []     # [{'text': ..., 'meta': {'source': ..., 'pos': ...}}]
        self.vectors = []  # 与 meta 一一对应

    def add(self, chunks, vectors, source='unknown'):
        if len(chunks) != len(vectors):
            raise ValueError('块数与向量数不一致')
        for chunk, vec in zip(chunks, vectors):
            self.meta.append({'text': chunk['text'], 'meta': {'source': source, 'pos': chunk.get('pos', 0)}})
            self.vectors.append([round(float(x), 6) for x in vec])

    def save(self, path):
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        (path / 'meta.json').write_text(json.dumps(self.meta, ensure_ascii=False), encoding='utf-8')
        (path / 'vectors.json').write_text(json.dumps(self.vectors), encoding='utf-8')

    @classmethod
    def load(cls, path):
        path = Path(path)
        store = cls()
        store.meta = json.loads((path / 'meta.json').read_text(encoding='utf-8'))
        store.vectors = json.loads((path / 'vectors.json').read_text(encoding='utf-8'))
        return store

    def search(self, query_vector, top_k=4, query_text=None, rerank=True):
        """语义检索 top_k。两段式召回策略（query_text 给出时启用）：
        第一段：向量余弦召回，候选池放宽到 max(top_k*3, 12)（解决语料扩量后相关块被稀释的问题）；
        第二段：IDF 加权词法精排（迷你 BM25 思想）——查询词中越稀有、越有区分度的字组
        （如"反黑/终点/孕妇"）权重越高，常见词（"光子/嫩肤"）几乎不加分；
        按精排分排序，向量分做同分决胜。
        返回 [{'text', 'meta', 'score', 'lex'}]，lex 为 IDF 加权词法覆盖率（0-1）。"""
        import math
        scored = [{'text': m['text'], 'meta': m['meta'], 'score': round(cosine(query_vector, v), 4)}
                  for m, v in zip(self.meta, self.vectors)]
        scored.sort(key=lambda item: -item['score'])
        if query_text and rerank:
            qgrams = _char_bigrams(query_text)
            df = {}
            for m in self.meta:
                for gram in _char_bigrams(m['text']):
                    df[gram] = df.get(gram, 0) + 1
            n_docs = max(1, len(self.meta))
            pool = scored[:max(top_k * 3, 12)]
            for item in pool:
                grams = _char_bigrams(item['text'])
                weight_sum = hit_sum = 0.0
                for gram in qgrams:
                    idf = math.log(1 + n_docs / (1 + df.get(gram, 0)))
                    weight_sum += idf
                    if gram in grams:
                        hit_sum += idf
                item['lex'] = round(hit_sum / weight_sum, 4) if weight_sum else 0.0
            pool.sort(key=lambda item: (-item['lex'], -item['score']))
            return pool[:top_k]
        return scored[:top_k]

    def __len__(self):
        return len(self.meta)


def _char_bigrams(text):
    clean = (text or '').replace(' ', '')
    return {clean[i:i + 2] for i in range(len(clean) - 1)}


def build_from_files(file_paths, store_dir, source_names=None):
    """从一批 md/txt 文件建库：读文件→切片→向量化→保存。返回 (store, 报告dict)。"""
    all_chunks = []
    owners = []  # 每块属于哪个 source
    for i, fp in enumerate(file_paths):
        source = (source_names[i] if source_names else Path(fp).name)
        chunks = chunk_text(Path(fp).read_text(encoding='utf-8', errors='replace'))
        all_chunks.extend(chunks)
        owners.extend([source] * len(chunks))
    vectors = embed_texts([c['text'] for c in all_chunks])
    store = KnowledgeStore()
    for chunk, vec, source in zip(all_chunks, vectors, owners):
        store.add([chunk], [vec], source=source)
    store.save(store_dir)
    per_file = {}
    for s in owners:
        per_file[s] = per_file.get(s, 0) + 1
    return store, {'files': per_file, 'total_chunks': len(store)}
