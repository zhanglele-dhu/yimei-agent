"""Deterministic cards; original photo pixels are pasted without resampling.

三类成品：
  实拍页：程序排版标题正文 + 照片像素直通（不重采样）；
  文字卡：三套程序版式（简约留白/柔和卡片/双色几何），AI 底图与纯色为可选；
  对话卡：微信聊天样式（顶栏+左右气泡+头像），完全程序绘制，文字准确性由代码保证。
"""
import io
import os
import re
import zipfile
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def font(size):
    paths = [os.getenv('STUDIO_FONT', ''), 'C:/Windows/Fonts/msyh.ttc',
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
    original = None
    if photo:
        with Image.open(io.BytesIO(photo)) as im:
            im.load()
            original = im.convert('RGB')
        width=original.width
        if width<240:
            raise ValueError('实拍照片宽度至少240像素，避免标题无法阅读')
    else:
        width=1080
    if original is None and theme in ('minimal','soft','duotone'):
        return render_themed(title,text,theme,page,total_pages)
    pad=max(20,round(width*.065))
    scratch=Image.new('RGB',(width,10));draw=ImageDraw.Draw(scratch)
    size=max(16,round(width/19))
    while True:
        title_font=font(size);body_font=font(max(14,round(size*.6)))
        tl=wrap(title,draw,title_font,width-2*pad-max(12,width//50)) if title else []
        bl=wrap(text,draw,body_font,width-2*pad) if text else []
        title_step=round(size*1.45); body_step=round(max(14,round(size*.6))*1.75)
        height=pad*2+len(tl)*title_step+(pad if tl and bl else 0)+len(bl)*body_step
        if original or height<=1380:break
        size-=2
        if size<24:raise ValueError('文字过多，请拆分页面或精简内容')
    if original:
        # If no text was requested, keep the decoded photo pixel-for-pixel.
        header_height=height if title or text else 0
        total=header_height+original.height
        out_method='local_layout_photo_passthrough'
    else:
        header_height=0;total=1440
        out_method='ai_background_composited' if background is not None else 'plain_fallback_layout'
    if width*total>24_000_000:raise ValueError('输出像素过大，请减少文字或使用较小照片')
    if background is not None and original is None:
        # AI 生成底图：cover-fit 铺满画布（装饰层，允许缩放；实拍照片不走此分支）
        with Image.open(io.BytesIO(background)) as bg:
            bg=bg.convert('RGB')
        scale=max(width/bg.width,total/bg.height)
        bg=bg.resize((max(width,round(bg.width*scale)),max(total,round(bg.height*scale))),Image.LANCZOS)
        left=(bg.width-width)//2;top=(bg.height-total)//2
        out=bg.crop((left,top,left+width,top+total))
    else:
        out=Image.new('RGB',(width,total),'#f5f3eb')
    use_bg = background is not None and original is None
    if (title or text):
        if use_bg:
            # 内容块垂直居中（略偏上），避免文字挤在顶部、下方大片空白
            content_top=max(pad,(total-height)//2-round(total*0.04))
            overlay=Image.new('RGBA',out.size,(0,0,0,0))
            ImageDraw.Draw(overlay).rounded_rectangle(
                (round(pad*.5),max(8,content_top-round(pad*.6)),
                 width-round(pad*.5),min(total-8,content_top+height+round(pad*.4))),
                radius=round(width*.045),fill=(255,255,255,225))
            out=Image.alpha_composite(out.convert('RGBA'),overlay).convert('RGB')
        else:
            content_top=pad
        d=ImageDraw.Draw(out)
        # 标题左侧强调竖条
        d.rectangle((pad,content_top+round(pad*.1),pad+max(5,width//140),
                     content_top+round(pad*.1)+len(tl)*title_step),fill='#21634f')
        y=content_top
        for line in tl:
            d.text((pad+max(12,width//50),y),line,font=title_font,fill='#163d32');y+=title_step
        if tl and bl:y+=round(pad*.9)
        for line in bl:
            d.text((pad,y),line,font=body_font,fill='#273b35');y+=body_step
        # 页码角标（右下角），仅多页时显示
        if page and total_pages and total_pages>1:
            chip_font=font(max(14,round(size*.5)))
            chip=f'{page} / {total_pages}'
            cw=round(draw.textlength(chip,font=chip_font))+round(pad*.8)
            ch=round(size*.9)
            cx,cy=width-pad-cw,total-pad-ch
            d.rounded_rectangle((cx,cy,cx+cw,cy+ch),radius=ch//2,fill='#21634f')
            d.text((cx+round(pad*.4),cy+round(ch*.12)),chip,font=chip_font,fill='#ffffff')
    if original:out.paste(original,(0,header_height))
    b=io.BytesIO();out.save(b,format='PNG')
    return b.getvalue(), {'width':width,'height':total,'photo_offset_y':header_height,
                         'method':out_method}


# ---------------------------------------------------------------- 程序版式文字卡

SOFT_TINTS = ['#EAF2EC', '#FBF1E6', '#ECEFF7', '#F8ECEF']


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


def render_themed(title, text, theme, page=None, total_pages=None):
    """三套程序绘制的文字卡版式：minimal=简约留白，soft=柔和卡片，duotone=双色几何。"""
    width, total = 1080, 1440
    bg = {'minimal': '#F7F5F0', 'soft': SOFT_TINTS[(max(1, page or 1) - 1) % len(SOFT_TINTS)],
          'duotone': '#F5F0E5'}[theme]
    img = Image.new('RGB', (width, total), bg)

    if theme == 'minimal':
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.rectangle((0, 0, width, 12), fill='#2E7A58')                     # 顶部绿条
        for r in range(6):                                                   # 右下点阵
            for c in range(6):
                cx, cy = width - 190 + c * 26, total - 190 + r * 26
                od.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=(46, 122, 88, 70))
        img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')

    elif theme == 'soft':
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.ellipse((width - 420, -110, width + 160, 470), fill=(255, 255, 255, 95))
        od.ellipse((width - 250, 60, width + 90, 400), fill=(46, 122, 88, 45))
        od.ellipse((-90, total - 240, 170, total + 20), fill=(224, 176, 101, 55))
        img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')

    else:  # duotone
        od = ImageDraw.Draw(img)
        od.ellipse((-120, total - 460, 520, total + 180), fill='#E0B065')
        od.ellipse((-260, total - 620, 360, total), fill='#2E7A58')
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        od2 = ImageDraw.Draw(overlay)
        for i in range(4):                                                   # 右上斜线组
            x = width - 330 + i * 52
            od2.line((x, 0, x + 170, 150), fill=(46, 122, 88, 60), width=8)
        img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')

    d = ImageDraw.Draw(img)
    # 字号自适应：minimal 直接排在底上；soft 限制在中央卡片；duotone 用半透明面板
    margin = {'minimal': 96, 'soft': 150, 'duotone': 96}[theme]
    max_w = width - margin * 2
    size = 56
    while True:
        title_font = font(size)
        body_font = font(max(20, round(size * .52)))
        tl = wrap(title, d, title_font, max_w) if title else []
        bl = wrap(text, d, body_font, max_w) if text else []
        title_step = round(size * 1.42)
        body_step = round(max(20, round(size * .52)) * 1.78)
        gap_tb = 42 if tl and bl else 0
        content_h = len(tl) * title_step + gap_tb + len(bl) * body_step
        if content_h <= 980 or size <= 30:
            break
        size -= 3
    if content_h > 1060:
        raise ValueError('文字过多，请拆分页面或精简内容')

    if theme == 'soft':
        card_w = width - 128
        card_h = min(total - 220, content_h + 130)
        cx0, cy0 = 64, (total - card_h) // 2
        sh = Image.new('RGBA', img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((cx0, cy0 + 12, cx0 + card_w, cy0 + card_h + 12),
                                             radius=36, fill=(60, 80, 70, 26))
        img = Image.alpha_composite(img.convert('RGBA'), sh).convert('RGB')
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((cx0, cy0, cx0 + card_w, cy0 + card_h), radius=36, fill='#FFFFFF')
        tx0 = cx0 + 62
        ty = cy0 + 65
        title_fill, body_fill, underline = '#1F4438', '#46534D', '#2E7A58'
    elif theme == 'duotone':
        content_top = max(80, (total - content_h) // 2 - round(total * .03))
        panel = Image.new('RGBA', img.size, (0, 0, 0, 0))
        ImageDraw.Draw(panel).rounded_rectangle(
            (72, content_top - 52, width - 72, min(total - 26, content_top + content_h + 52)),
            radius=40, fill=(255, 255, 255, 216))
        img = Image.alpha_composite(img.convert('RGBA'), panel).convert('RGB')
        d = ImageDraw.Draw(img)
        tx0 = 128
        ty = content_top
        title_fill, body_fill, underline = '#143C31', '#3A463F', '#2E7A58'
    else:  # minimal
        content_top = max(110, (total - content_h) // 2 - round(total * .02))
        tx0 = margin
        ty = content_top
        title_fill, body_fill, underline = '#143C31', '#3E4C46', '#2E7A58'

    if tl:
        for line in tl:
            d.text((tx0, ty), line, font=title_font, fill=title_fill)
            ty += title_step
        first_w = d.textlength(tl[0], font=title_font)
        d.rectangle((tx0, ty + 8, tx0 + max(110, round(first_w * .55)), ty + 14), fill=underline)
        ty += 46
    ty += gap_tb
    for line in bl:
        d.text((tx0, ty), line, font=body_font, fill=body_fill)
        ty += body_step
    _page_chip(d, width, total, page, total_pages)
    b = io.BytesIO()
    img.save(b, format='PNG')
    return b.getvalue(), {'width': width, 'height': total, 'method': f'program_{theme}'}


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
        z.writestr('标题正文.txt',task['draft']['title']+'\n\n'+task['draft']['body'])
        evidence={'bundle_id':task['request']['bundle_id'],'case':task['case'],
                  'selection':task['selection'],'analysis':task['analysis'],
                  'analysis_stages':task.get('analysis_stages',{}),
                  'analysis_decisions':task.get('analysis_decisions',[]),
                  'confirmed_analysis':task['confirmed_analysis'],
                  'pages':task['draft']['pages'],'page_reviews':task.get('page_reviews',{}),
                  'assets':task.get('assets',{}),
                  'backgrounds':task.get('backgrounds',{}),
                  'copy_review':task.get('copy_review'), 'sources':task.get('generation_sources',[]),
                  'limitations':'参考结构不证明爆款或医学正确；内容经用户确认，不代表平台通过。文字卡底图由CogView生成（AI生成装饰，不含文字；标题正文由程序排版叠加）。'}
        z.writestr('来源记录.json',json.dumps(evidence,ensure_ascii=False,indent=2))
        z.writestr('待核实记录.txt','\n'.join(task['draft'].get('missing_information',[])) or '模型未列出额外待核实项，仍需发布前人工审核。')
    return buffer.getvalue()
