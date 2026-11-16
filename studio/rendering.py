"""Deterministic cards; original photo pixels are pasted without resampling.

三类成品：
  实拍页：程序排版标题正文 + 照片像素直通（不重采样）；
  文字卡：三套小红书信息卡版式（清爽杂志/奶油卡片/撞色重点），AI 底图与纯色为可选；
  对话卡：微信聊天样式（顶栏+左右气泡+头像），完全程序绘制，文字准确性由代码保证。
"""
import io
import os
import re
import zipfile
import json
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


@lru_cache(maxsize=128)
def font(size, bold=False):
    paths = [os.getenv('STUDIO_FONT_BOLD' if bold else 'STUDIO_FONT', ''),
             'C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc',
             '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    for path in paths:
        if path and Path(path).is_file():
            return ImageFont.truetype(path, size)
    raise ValueError('缺少中文字体，请设置STUDIO_FONT为中文字体文件路径')


def wrap(text, draw, ft, width):
    lines=[]
    for paragraph in text.split('\n'):
        line=''
        for ch in paragraph:
            if draw.textlength(line+ch,font=ft)>width and line:
                lines.append(line);line=ch
            else:line+=ch
        lines.append(line)
    return lines


def render(title, text, photo=None, background=None, page=None, total_pages=None, theme=None):
    from .card_layout import render_card
    method = ('local_layout_photo_passthrough' if photo else
              'ai_background_composited' if background is not None else
              f'program_{theme}' if theme in ('minimal', 'soft', 'duotone') else 'plain_fallback_layout')
    return render_card(title, text, font, wrap, theme=theme or 'minimal', photo=photo,
                       background=background, page=page, total_pages=total_pages, method=method)


def render_themed(title, text, theme, page=None, total_pages=None):
    return render(title, text, theme=theme, page=page, total_pages=total_pages)


def _page_chip(d, width, total, page, total_pages, base_size=34):
    """右下角页码角标（多页时），与旧版式同款。"""
    if not (page and total_pages and total_pages > 1):
        return
    chip_font = font(max(14, round(base_size * .5)))
    chip = f'{page} / {total_pages}'
    cw = round(d.textlength(chip, font=chip_font)) + 22
    ch = round(base_size * .9)
    cx, cy = width - 46 - cw, total - 46 - ch
    d.rounded_rectangle((cx, cy, cx + cw, cy + ch), radius=ch // 2, fill='#21634f')
    d.text((cx + 10, cy + round(ch * .12)), chip, font=chip_font, fill='#ffffff')



# ---------------------------------------------------------------- 微信对话卡

_CUSTOMER_PREFIX = re.compile(r'^(顾客|顾|客户|买家|对方|客人|Q|问)[:：]\s*(.+)$')
_SHOP_PREFIX = re.compile(r'^(门店|店|我方|我|商家|机构|A|答)[:：]\s*(.+)$')


def parse_dialog(text):
    """把多行文本解析成对话轮次。每行一条，"顾客：…" 在左（白泡），"门店：…" 在右（绿泡）；
    无前缀的行并入上一轮；完全没有前缀时按整行文本原样返回空列表交由上层提示格式。"""
    turns = []
    for line in (text or '').splitlines():
        line = line.strip()
        if not line:
            continue
        m = _CUSTOMER_PREFIX.match(line)
        if m:
            turns.append({'speaker': 'customer', 'text': m.group(2).strip()[:300]})
            continue
        m = _SHOP_PREFIX.match(line)
        if m:
            turns.append({'speaker': 'shop', 'text': m.group(2).strip()[:300]})
            continue
        if turns:
            turns[-1]['text'] = (turns[-1]['text'] + line)[:300]
    return [t for t in turns if t['text']]


def render_chat(title, dialog, page=None, total_pages=None):
    """微信聊天样式：浅灰底 + 白色顶栏 + 左右气泡 + 圆形头像。全程序绘制。"""
    width = 1080
    pad, avatar, gap = 38, 76, 14
    bubble_pad_x, bubble_pad_y = 26, 20
    text_size = 34
    line_step = round(text_size * 1.5)
    header_h = 128
    row_gap = 30
    font_text, font_title, font_avatar = font(text_size), font(40), font(30)
    scratch = ImageDraw.Draw(Image.new('RGB', (8, 8)))
    max_bubble_text_w = width - (pad + avatar + gap + bubble_pad_x) * 2

    laid = []
    for turn in dialog:
        lines = wrap(turn['text'], scratch, font_text, max_bubble_text_w)
        h = len(lines) * line_step + bubble_pad_y * 2
        if h > 1200:
            raise ValueError('单条对话太长，请拆分')
        laid.append({'speaker': turn['speaker'], 'lines': lines, 'h': h})
    total = header_h + 46 + sum(item['h'] + row_gap for item in laid) + 120
    if total > 3200:
        raise ValueError('对话内容太多，请精简或拆成多页')

    img = Image.new('RGB', (width, total), '#EDEDED')
    d = ImageDraw.Draw(img)
    # 顶栏（微信样式：白底、居中联系人名、底缘细线）
    d.rectangle((0, 0, width, header_h), fill='#F7F7F7')
    title_text = (title or '顾客咨询').strip()[:16]
    tw = d.textlength(title_text, font=font_title)
    d.text(((width - tw) // 2, (header_h - 52) // 2), title_text, font=font_title, fill='#1F2329')
    d.line((0, header_h - 1, width, header_h - 1), fill='#DEDEDE', width=2)

    y = header_h + 46
    radius = 14
    for item in laid:
        lines_w = max(d.textlength(l, font=font_text) for l in item['lines'])
        bubble_w = round(lines_w) + bubble_pad_x * 2
        if item['speaker'] == 'customer':
            ax, bx = pad, pad + avatar + gap
            avatar_bg, avatar_ch = '#D5DAE0', '客'
            bubble_fill = '#FFFFFF'
            tail = [(bx, y + radius + 8), (bx, y + radius + 24), (bx - 10, y + radius + 16)]
        else:
            ax = width - pad - avatar
            bx = width - pad - avatar - gap - bubble_w
            avatar_bg, avatar_ch = '#8FCBB0', '店'
            bubble_fill = '#95EC69'
            tail = [(bx + bubble_w, y + radius + 8), (bx + bubble_w, y + radius + 24),
                    (bx + bubble_w + 10, y + radius + 16)]
        # 头像（圆形 + 单字）
        cy = y + item['h'] // 2
        d.ellipse((ax, cy - avatar // 2, ax + avatar, cy + avatar // 2), fill=avatar_bg)
        ch_w = d.textlength(avatar_ch, font=font_avatar)
        d.text((ax + (avatar - ch_w) / 2, cy - 21), avatar_ch, font=font_avatar, fill='#3D4750')
        # 气泡（圆角矩形 + 小尾巴）
        d.rounded_rectangle((bx, y, bx + bubble_w, y + item['h']), radius=radius, fill=bubble_fill)
        d.polygon(tail, fill=bubble_fill)
        ty = y + bubble_pad_y
        for line in item['lines']:
            d.text((bx + bubble_pad_x, ty), line, font=font_text, fill='#171A1F')
            ty += line_step
        y += item['h'] + row_gap
    _page_chip(d, width, total, page, total_pages)
    b = io.BytesIO()
    img.save(b, format='PNG')
    return b.getvalue(), {'width': width, 'height': total, 'method': 'wechat_dialog'}


def export_zip(task, image_files):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        for i,raw in enumerate(image_files,1):z.writestr(f'{i:02d}.png',raw)
        if task.get('expression',{}).get('status')=='accepted':
            z.writestr('SKILL.md',task['expression']['prompt'])
            z.writestr('本篇资料单.json',json.dumps(task.get('material_sheet',{}),ensure_ascii=False,indent=2))
        z.writestr('标题正文.txt',task['draft']['title']+'\n\n'+task['draft']['body'])
        evidence={'bundle_id':task['request']['bundle_id'],'case':task['case'],
                  'selection':task['selection'],'analysis':task['analysis'],
                  'analysis_stages':task.get('analysis_stages',{}),
                  'analysis_decisions':task.get('analysis_decisions',[]),
                  'confirmed_analysis':task['confirmed_analysis'],
                  'pages':task['draft']['pages'],'page_reviews':task.get('page_reviews',{}),
                  'assets':task.get('assets',{}),
                  'backgrounds':task.get('backgrounds',{}),'renders':task.get('renders',{}),
                  'generation_attempts':task.get('generation_attempts',[]),
                  'copy_review':task.get('copy_review'), 'sources':task.get('generation_sources',[]),
                  'limitations':'参考结构不证明爆款或医学正确；内容经用户确认，不代表平台通过。各页实际生成方式、设计模型、skill与视觉检查结果见renders；模板模式没有模型视觉设计。视觉检查只针对可读性与版式，不认证医学事实。'}
        z.writestr('来源记录.json',json.dumps(evidence,ensure_ascii=False,indent=2))
        z.writestr('待核实记录.txt','\n'.join(task['draft'].get('missing_information',[])) or '模型未列出额外待核实项，仍需发布前人工审核。')
    return buffer.getvalue()
