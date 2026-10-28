"""Versioned, validated bundles; no imports or writes into the research project."""
import hashlib
import io
import json
import re
import zipfile
from urllib.parse import urlparse

from PIL import Image

MAX_BUNDLE = 100 * 1024 * 1024


def validate_bundle(raw):
    if len(raw) > MAX_BUNDLE:
        raise ValueError('资料包超过100MB')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        if len(names) != len(set(names)) or len(names) > 2000:
            raise ValueError('资料包有重复路径或文件过多')
        if sum(i.file_size for i in z.infolist()) > MAX_BUNDLE:
            raise ValueError('解压内容超过100MB')
        for name in names:
            if name != 'manifest.json' and not re.fullmatch(r'images/[A-Za-z0-9_-]+\.(png|jpg|jpeg|webp)', name):
                raise ValueError('资料包包含不允许的路径')
        if z.getinfo('manifest.json').file_size > 8_000_000:
            raise ValueError('资料清单过大')
        manifest = json.loads(z.read('manifest.json'))
        if manifest.get('schema_version') != 1 or not isinstance(manifest.get('cases'), list) or not 1 <= len(manifest['cases']) <= 300:
            raise ValueError('不支持的资料格式或案例数量')
        if not isinstance(manifest.get('version'), str) or not 1 <= len(manifest['version']) <= 100:
            raise ValueError('资料包缺少有效版本')
        ids = set()
        for c in manifest['cases']:
            if any(not isinstance(c.get(key), str) for key in ('id', 'title', 'body', 'url')):
                raise ValueError('案例缺少必需文字字段')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,60}', c['id']) or c['id'] in ids:
                raise ValueError('案例编号无效或重复')
            ids.add(c['id'])
            u = urlparse(c['url'])
            if u.scheme != 'https' or not (u.hostname == 'xiaohongshu.com' or (u.hostname or '').endswith('.xiaohongshu.com')):
                raise ValueError('原帖链接必须属于小红书')
            if c['likes'] is not None and (type(c['likes']) is not int or c['likes'] < 0):
                raise ValueError('点赞数格式错误')
            if not 1 <= len(c['pages']) <= 20:
                raise ValueError('案例缺少页面或页面过多')
            if [p['number'] for p in c['pages']] != list(range(1, len(c['pages']) + 1)):
                raise ValueError('页面编号必须连续')
            for p in c['pages']:
                if not isinstance(p['ocr'], str):
                    raise ValueError('OCR必须为文字')
                if p.get('image'):
                    if p['image'] not in names:
                        raise ValueError('清单引用的原图不存在')
                    data = z.read(p['image'])
                    if hashlib.sha256(data).hexdigest() != p['image_sha256']:
                        raise ValueError('原图校验失败')
                    with Image.open(io.BytesIO(data)) as im:
                        if im.width * im.height > 16_000_000:
                            raise ValueError('原图像素过大')
                        im.verify()
        # Content identity cannot be chosen by an untrusted manifest.
        manifest['bundle_id'] = hashlib.sha256(raw).hexdigest()[:24]
        return manifest


def install(raw, root):
    manifest = validate_bundle(raw)
    root.mkdir(parents=True, exist_ok=True)
    target = root / (manifest['bundle_id'] + '.zip')
    if not target.exists():
        tmp = root / (manifest['bundle_id'] + '.tmp')
        tmp.write_bytes(raw)
        tmp.replace(target)
    return manifest


def load(root, bundle_id):
    if not re.fullmatch(r'[a-f0-9]{24}', bundle_id):
        raise ValueError('资料版本编号无效')
    with zipfile.ZipFile(root / (bundle_id + '.zip')) as z:
        result = json.loads(z.read('manifest.json'))
    result['bundle_id'] = bundle_id
    return result


def image_bytes(root, bundle_id, case_id, page_number):
    manifest = load(root, bundle_id)
    case = next(c for c in manifest['cases'] if c['id'] == case_id)
    page = next(p for p in case['pages'] if p['number'] == page_number)
    if not page.get('image'):
        raise ValueError('这页缺少原图')
    with zipfile.ZipFile(root / (bundle_id + '.zip')) as z:
        return z.read(page['image'])


ASPECTS = {
    '比较': ('区别', '对比', '怎么选', '选择', '比较', 'vs'),
    '费用': ('价格', '费用', '预算', '报价', '多少钱', '几百', '一千'),
    '咨询': ('面诊', '咨询', '到店', '要问', '问题清单'),
    '护理': ('术后', '护理', '恢复', '注意事项'),
    '真伪': ('验真', '真假', '真伪', '辨别', '鉴别'),
    '滤片': ('滤片', '滤光片', '波段', '波长'),
}


def project_gate(manifest, project):
    """硬性主题闸门（确定性，模型不参与）：项目名必须出现在标题或首图OCR中。"""
    project = project.lower().strip()
    projects = ('m22', '光子', 'ipl') if 'm22' in project or '光子' in project else (project,)
    matches = []
    for c in manifest['cases']:
        cover = (c['title'] + '\n' + c['pages'][0]['ocr']).lower()
        if any(p and p in cover for p in projects) and c['likes'] is not None:
            matches.append(c)
    return matches


def combine_ranking(pool, scores):
    """收益函数（确定性）：综合分 = 相关性(1-10)×7 + 点赞归一化×30。
    相关性≤3 淘汰；同分按点赞高者优先。模型只打分，排序由本函数计算。"""
    if not pool:
        return []
    likes = [c['likes'] for c in pool]
    lo, hi = min(likes), max(likes)
    ranked = []
    for c in pool:
        rel = scores.get(c['id'])
        if rel is None or rel <= 3:
            continue
        like_norm = 1.0 if hi == lo else (c['likes'] - lo) / (hi - lo)
        ranked.append({'case': c, 'relevance': rel, 'final': round(7 * rel + 30 * like_norm, 1)})
    ranked.sort(key=lambda item: (-item['final'], -item['case']['likes'], item['case']['id']))
    return ranked


def select(manifest, project, question):
    query = question.lower()
    project = project.lower().strip()
    projects = ('m22', '光子', 'ipl') if 'm22' in project or '光子' in project else (project,)
    aspects = [name for name, words in ASPECTS.items() if any(w in query for w in words)]
    matches = []
    for c in manifest['cases']:
        # Require the primary subject in the title/cover; hashtags alone are not sufficient.
        cover = (c['title'] + '\n' + c['pages'][0]['ocr']).lower()
        if not any(p and p in cover for p in projects) or c['likes'] is None:
            continue
        if aspects:
            hits = [a for a in aspects if any(w in cover for w in ASPECTS[a])]
            if len(hits) != len(aspects):
                continue
            reason = '标题或首图同时包含主题方向：' + '、'.join(hits)
        else:
            normalized = re.sub(r'[^\w\u4e00-\u9fff]', '', query)
            for word in (*projects, '了解', '介绍', '科普', '什么', '怎么', '一下', '想写', '一篇', '关于', '请问', '第一次', '新手', '基础'):
                normalized = normalized.replace(word, '')
            if len(normalized) >= 2 and not any(normalized[i:i+2] in cover for i in range(len(normalized)-1)):
                continue
            reason = '项目名称与主题文字匹配（规则筛选，需人工确认相关性）'
        matches.append((c, reason))
    matches.sort(key=lambda x: (-x[0]['likes'], x[0]['id']))
    if not matches:
        return None, {'eligible_count': 0, 'reason': '没有相关案例。请修改主题或导入相关资料，不套用其他主题。'}
    return matches[0][0], {'eligible_count': len(matches), 'reason': matches[0][1],
                           'metric': '相关候选中采集快照点赞数最高；同赞按案例编号排序',
                           'candidate_ids': [c['id'] for c, _ in matches]}
