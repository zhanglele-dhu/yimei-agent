"""Standalone, user-operated XHS image/text reference collector. No LLM key needed."""
import argparse
import asyncio
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

ROOT = Path(__file__).resolve().parent


def parse_count(value):
    if value is None:
        return None
    text = str(value).strip().replace(',', '')
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*([万wW千kK]?)\+?', text)
    if not match:
        return None
    scale = {'万': 10000, 'w': 10000, '千': 1000, 'k': 1000}
    return int(float(match[1]) * scale.get(match[2].lower(), 1))


def safe_cell(value):
    text = '' if value is None else str(value)
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text


def export(rows, errors, keyword, stem, status):
    stamp = datetime.now().astimezone().isoformat(timespec='seconds')
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix('.json').write_text(json.dumps({
        'keyword': keyword, 'updated_at': stamp, 'status': status,
        'count': len(rows), 'items': rows, 'errors': errors,
        'note': '搜索顺序样本，不是爆款排名。互动数可能是页面缩略值；null表示未读取到。图片仅保存链接。',
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    fields = ['title', 'content', 'likes', 'favorites', 'comments', 'likes_raw',
              'favorites_raw', 'comments_raw', 'author', 'publish_time', 'tags',
              'image_urls', 'url', 'collected_at', 'missing_fields']
    with stem.with_suffix('.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(fields)
        for row in rows:
            writer.writerow([safe_cell(' | '.join(row[k]) if isinstance(row.get(k), list)
                                       else row.get(k)) for k in fields])


async def read_note(page, url):
    # Prefer the structured data already delivered to the normal web page.
    data = await page.evaluate('''() => {
      const m = window.__INITIAL_STATE__?.note?.noteDetailMap || {};
      const id = location.pathname.split('/').filter(Boolean).pop();
      const entry = m[id] || Object.values(m).find(v => v?.note?.noteId === id);
      return entry?.note || null;
    }''')
    async def text(selector):
        loc = page.locator(selector).first
        return (await loc.inner_text()).strip() if await loc.count() else ''

    async def count_raw(meta, selector):
        loc = page.locator(f'meta[name="{meta}"]')
        if await loc.count():
            value = await loc.first.get_attribute('content')
            if parse_count(value) is not None:
                return value
        return await text(selector)

    if data:
        kind = data.get('type')
        if kind != 'normal':
            return None  # Only positively identified image/text notes.
        info = data.get('interactInfo') or {}
        title, content = data.get('title', ''), data.get('desc', '')
        raw = [info.get(k) for k in ('likedCount', 'collectedCount', 'commentCount')]
        author = (data.get('user') or {}).get('nickname', '')
        tags = [t.get('name', '') for t in data.get('tagList', [])]
        pictures = [i.get('urlDefault') or i.get('urlPre') or i.get('url', '')
                    for i in data.get('imageList', [])]
        published = data.get('time')
        if isinstance(published, (float, int)):
            published = datetime.fromtimestamp(published / 1000).astimezone().isoformat()
    else:
        if await page.locator('.note-detail-mask video, #noteContainer video').count():
            return None
        pictures = await page.locator('.note-slider img, .swiper-slide img').evaluate_all(
            '(els) => els.map(e => e.currentSrc || e.src).filter(Boolean)')
        if not pictures:
            raise ValueError('无法确认图文类型；页面结构变化、尚未加载或需要登录')
        title = await text('#detail-title')
        content = await text('#detail-desc')
        author = await text('.author-container .username')
        published = await text('.bottom-container .date')
        tags = await page.locator('#detail-desc .tag').all_inner_texts()
        raw = [await count_raw(m, s) for m, s in (
            ('og:xhs:note_like', '.interact-container .like-wrapper .count'),
            ('og:xhs:note_collect', '.interact-container .collect-wrapper .count'),
            ('og:xhs:note_comment', '.interact-container .chat-wrapper .count'))]
    if not (title or content):
        raise ValueError('未取得笔记正文或标题')
    row = dict(title=title, content=content, author=author, publish_time=published,
               tags=tags, image_urls=list(dict.fromkeys(p for p in pictures if p)),
               url=url, collected_at=datetime.now().astimezone().isoformat(timespec='seconds'))
    for name, value in zip(('likes', 'favorites', 'comments'), raw):
        row[name + '_raw'] = value
        row[name] = parse_count(value)
    row['missing_fields'] = [k for k in ('title', 'content', 'author', 'publish_time',
                                        'image_urls', 'likes', 'favorites', 'comments')
                             if row.get(k) is None or row.get(k) == '' or row.get(k) == []]
    return row


async def collect(args):
    from playwright.async_api import async_playwright
    rows, errors = [], []
    stem = ROOT / 'data' / 'reference_notes' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    status = 'started'
    export(rows, errors, args.keyword, stem, status)
    print(f'结果文件：{stem}.csv\n首次运行将打开浏览器，请手动登录。无需模型 API Key。')
    try:
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                str(ROOT / 'data' / 'collector_profile'), headless=False,
                viewport={'width': 1360, 'height': 900})
            try:
                page = await context.new_page()
                await page.goto('https://www.xiaohongshu.com', wait_until='domcontentloaded')
                await asyncio.to_thread(input, '请确认浏览器中已登录，回到这里按回车继续：')
                await page.goto('https://www.xiaohongshu.com/search_result?keyword='
                                + quote(args.keyword) + '&source=web_explore_feed',
                                wait_until='domcontentloaded')
                await asyncio.to_thread(input, '请确认搜索结果可见（可手动切换到图文），再按回车采集：')
                links, seen = [], set()
                for _ in range(args.scrolls):
                    cards = await page.locator('section.note-item').all()
                    for card in cards:
                        if await card.locator('.video-badge, .play-icon, .duration').count():
                            continue
                        link = card.locator('a.cover').first
                        if not await link.count():
                            continue
                        href = await link.get_attribute('href')
                        if not href:
                            continue
                        url = urljoin('https://www.xiaohongshu.com', href)
                        parsed = urlsplit(url)
                        if parsed.hostname != 'www.xiaohongshu.com':
                            continue
                        identity = parsed.path
                        if identity not in seen:
                            seen.add(identity)
                            links.append(url)  # Keep query parameters needed by detail pages.
                    await page.mouse.wheel(0, 850)
                    await page.wait_for_timeout(1500)
                print(f'找到 {len(links)} 个候选链接，目标 {args.count} 条。')
                detail = await context.new_page()
                for url in links:
                    if len(rows) >= args.count:
                        break
                    try:
                        await detail.goto(url, wait_until='domcontentloaded', timeout=30000)
                        await detail.wait_for_timeout(2000)
                        if await detail.get_by_text(re.compile('访问频繁|安全验证|请完成验证')).count():
                            raise RuntimeError('页面要求验证或限制访问；已停止，请人工检查')
                        row = await read_note(detail, url)
                        if row:
                            rows.append(row)
                            print(f"[{len(rows)}] {row['title']} | 赞 {row['likes']} 收藏 {row['favorites']} 评论 {row['comments']}")
                    except RuntimeError:
                        raise
                    except Exception as exc:
                        errors.append({'url': url, 'reason': str(exc)})
                        print('未采到该条，原因已写入 JSON。')
                        if len(errors) >= 3 and not rows:
                            raise RuntimeError('连续3条未取得数据，停止以便检查登录或页面结构')
                    export(rows, errors, args.keyword, stem, 'collecting')
                status = 'completed' if len(rows) >= args.count else 'partial_or_empty'
            finally:
                await context.close()
    except Exception as exc:
        status = 'failed_or_interrupted'
        errors.append({'reason': str(exc)})
        print(f'停止：{exc}')
    finally:
        export(rows, errors, args.keyword, stem, status)
        print(f'已保存 {len(rows)} 条：{stem}.csv\nJSON包含来源、原始计数和错误记录。')
    return 0 if rows else 1


def main():
    parser = argparse.ArgumentParser(description='小红书图文参考笔记采集（人工登录）')
    parser.add_argument('--keyword', help='搜索词，省略时询问')
    parser.add_argument('--count', type=int, default=10)
    parser.add_argument('--scrolls', type=int, default=5)
    args = parser.parse_args()
    args.keyword = args.keyword or input('搜索词（回车默认 M22 科普）：').strip() or 'M22 科普'
    if not 1 <= args.count <= 200 or not 1 <= args.scrolls <= 100:
        parser.error('count需在1到200之间，scrolls需在1到100之间')
    return asyncio.run(collect(args))


if __name__ == '__main__':
    raise SystemExit(main())
