"""Reusable Xiaohongshu card layouts adapted from xhs-note-creator principles.

Fixed 3:4 canvas, separate title/body hierarchy, semantic blocks, safe margins.
Text is typeset locally; user photos retain every original pixel.
"""
import io
import math
import re

from PIL import Image, ImageDraw

LAYOUT_VERSION = 'xhs-editorial-v1'
NOTE_PREFIX = re.compile(r'^\s*(?:#{1,6}\s*|[-*]\s*)?(?:实拍建议|拍摄建议|拍摄提示|配图建议|排版说明|制作说明)\s*[:：]')
PALETTES = {
    'minimal': ('#F6F7F2', '#FFFFFF', '#195B49', '#E5EEE6', '#203C34'),
    'soft': ('#F7EFE5', '#FFFCF6', '#77543B', '#EDE0CD', '#493E34'),
    'duotone': ('#EAF0E8', '#FFFDF5', '#184B3D', '#F0C765', '#203A30'),
}


def split_production_notes(text):
    """Only explicit, standalone production paragraphs are excluded from artwork.

    Keep the editable source unchanged; return omitted paragraphs for disclosure.
    Never infer that ordinary medical/user-facing advice is a production note.
    """
    public, notes = [], []
    for paragraph in re.split(r'\n\s*\n', (text or '').strip()):
        normal = []
        note = []
        for line in paragraph.splitlines():
            if NOTE_PREFIX.match(line):
                if normal:
                    public.append('\n'.join(normal)); normal = []
                if note:
                    notes.append('\n'.join(note))
                note = [line]
            elif note:
                note.append(line)
            else:
                normal.append(line)
        if normal:
            public.append('\n'.join(normal))
        if note:
            notes.append('\n'.join(note))
    return '\n\n'.join(public), notes


def content_blocks(text):
    """Use existing paragraphs and explicit arrows; never invent or summarize copy."""
    blocks = []
    for paragraph in re.split(r'\n+', text.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if '→' in paragraph:
            parts = [p.strip() for p in paragraph.split('→')]
            if 2 <= len(parts) <= 8 and all(parts):
                blocks.extend(('step', part) for part in parts)
                continue
        blocks.append(('paragraph', paragraph))
    return blocks


def render_card(title, text, font_factory, wrap_text, *, theme='minimal', photo=None,
                background=None, page=None, total_pages=None, method=None):
    public, notes = split_production_notes(text)
    if not title.strip() and not public.strip() and photo is None:
        raise ValueError('成品没有可发布文字，请把制作提示改为面向读者的内容')
    original = None
    if photo:
        with Image.open(io.BytesIO(photo)) as source:
            source.load()
            original = source.convert('RGB')
        if original.width < 240:
            raise ValueError('实拍照片宽度至少240像素')
    if original is not None and not title.strip() and not public.strip():
        output = io.BytesIO(); original.save(output, format='PNG')
        return output.getvalue(), dict(width=original.width, height=original.height,
            photo_offset_x=0, photo_offset_y=0, method='local_layout_photo_passthrough',
            layout_version=LAYOUT_VERSION, production_notes=notes, public_text=public)

    theme = theme if theme in PALETTES else 'minimal'
    bg, surface, accent, tint, ink = PALETTES[theme]
    blocks = content_blocks(public)
    width = max(1080, original.width + 144 if original is not None else 1080)
    width = math.ceil(width / 3) * 3
    # Increase the canvas only when an unscaled photo cannot fit. Never crop it.
    for attempt in range(5):
        height = width * 4 // 3
        if width * height > 24_000_000:
            raise ValueError('图片与文字过多，请精简文字或使用较小照片')
        scale = width / 1080
        margin = round(76 * scale)
        available = width - 2 * margin
        measure = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        title_size = round((76 if page == 1 and original is None else 64) * scale)
        # A long title wraps; it does not collide with body or footer.
        while True:
            title_font = font_factory(title_size, bold=True)
            title_lines = wrap_text(title, measure, title_font, available)
            if len(title_lines) <= 3 or title_size <= round(40 * scale):
                break
            title_size -= max(1, round(2 * scale))
        title_step = round(title_size * 1.38)
        title_top = round(150 * scale)
        title_end = title_top + len(title_lines) * title_step
        content_top = title_end + round(56 * scale)
        frame_height = max(original.height + round(32 * scale), round(240 * scale)) if original is not None else 0
        if original is not None:
            content_top += frame_height + round(36 * scale)
        limit = height - round(125 * scale)
        for logical_size in range(48 if page == 1 and original is None else 42, 25, -2):
            body_size = round(logical_size * scale)
            body_font = font_factory(body_size)
            line_step = round(body_size * 1.55)
            gap = round(22 * scale)
            block_pad = round(25 * scale)
            number_w = round(62 * scale)
            laid = []
            y = content_top
            index = 0
            while index < len(blocks):
                kind, value = blocks[index]
                # Long flows become a readable two-column sequence, rather than
                # seven full-width rows that crowd the photograph off the card.
                grid = kind == 'step' and sum(k == 'step' for k, _ in blocks) > 4
                cells = [(kind, value)]
                if grid and index + 1 < len(blocks) and blocks[index+1][0] == 'step':
                    cells.append(blocks[index+1])
                cell_width = (available-gap)//2 if grid else available
                row = []
                for col, (cell_kind, cell_text) in enumerate(cells):
                    lines = wrap_text(cell_text, measure, body_font, cell_width-2*block_pad-number_w)
                    cell_height = max(round(76*scale), len(lines)*line_step+2*block_pad)
                    row.append((cell_kind, lines, margin+col*(cell_width+gap), y, cell_height, cell_width))
                row_height = max(cell[4] for cell in row)
                laid.extend((k, lines, x, yy, row_height, w) for k, lines, x, yy, h, w in row)
                y += row_height+gap
                index += len(cells)
            if y - gap <= limit:
                break
        else:
            if original is None:
                raise ValueError('本页文字过多，请精简内容或分到其他页后再生成')
            width = math.ceil(width * 1.22 / 3) * 3
            continue
        break
    else:
        raise ValueError('照片过高或文字过多，请换用横向照片或精简文字')

    image = Image.new('RGB', (width, height), bg)
    if background:
        from PIL import ImageOps
        with Image.open(io.BytesIO(background)) as source:
            image = ImageOps.fit(source.convert('RGB'), (width, height))
        # A solid panel keeps generated decoration away from actual text.
        overlay = ImageDraw.Draw(image)
        overlay.rounded_rectangle((round(34*scale), round(106*scale), width-round(34*scale), limit+round(20*scale)),
                                  radius=round(30*scale), fill=bg)
    draw = ImageDraw.Draw(image)
    small_font = font_factory(round(24 * scale))
    label = '实拍手记' if original is not None else ('主题笔记' if page == 1 else '内容笔记')
    draw.rounded_rectangle((margin, round(62*scale), margin+round(144*scale), round(104*scale)),
                           radius=round(21*scale), fill=accent)
    draw.text((margin+round(23*scale), round(67*scale)), label, font=small_font, fill='#FFFFFF')
    if total_pages:
        marker = f'{page or 1:02d} / {total_pages:02d}'
        draw.text((width-margin-draw.textlength(marker,font=small_font), round(67*scale)), marker, font=small_font, fill=accent)
    if theme == 'duotone':
        draw.rectangle((width-margin-round(170*scale), title_top-round(14*scale), width-margin, title_top+round(8*scale)), fill=tint)
    for i, line in enumerate(title_lines):
        draw.text((margin, title_top+i*title_step), line, font=title_font, fill=ink)
    draw.rounded_rectangle((margin, title_end+round(22*scale), margin+round(74*scale), title_end+round(29*scale)),
                           radius=round(3*scale), fill=accent)

    photo_x = photo_y = None
    if original is not None:
        frame_y = title_end + round(56*scale)
        draw.rounded_rectangle((margin, frame_y, width-margin, frame_y+frame_height), radius=round(24*scale), fill=tint)
        photo_x = (width-original.width)//2
        photo_y = frame_y+(frame_height-original.height)//2
        image.paste(original, (photo_x, photo_y))
    has_flow = any(kind == 'step' for kind, _ in blocks)
    for i, (kind, lines, x, y, block_height, block_width) in enumerate(laid):
        fill = tint if kind == 'step' else surface
        if theme == 'duotone' and i == 0:
            fill = tint
        draw.rounded_rectangle((x, y, x+block_width, y+block_height), radius=round(22*scale), fill=fill)
        cx, cy = x+round(25*scale), y+block_pad
        marker = '提示' if has_flow and kind != 'step' else f'{i+1:02d}'
        draw.text((cx, cy+round(2*scale)), marker, font=font_factory(round(25*scale), bold=True), fill=accent)
        for row, line in enumerate(lines):
            draw.text((cx+number_w, cy+row*line_step), line, font=body_font, fill=ink)
    footer_y = height-round(77*scale)
    draw.line((margin, footer_y-round(20*scale), width-margin, footer_y-round(20*scale)), fill=tint, width=max(1,round(scale*2)))
    draw.text((margin, footer_y), '阅读 · 了解 · 再确认', font=font_factory(round(22*scale)), fill=accent)
    if page and total_pages:
        stamp = f'{page:02d}'
        draw.text((width-margin-draw.textlength(stamp,font=small_font), footer_y), stamp, font=small_font, fill=accent)
    output = io.BytesIO(); image.save(output, format='PNG')
    meta = dict(width=width, height=height, method=method or f'program_{theme}',
                layout_version=LAYOUT_VERSION, layout='photo_notes' if original is not None else ('flow' if any(k=='step' for k,_ in blocks) else 'editorial'),
                production_notes=notes, public_text=public, body_font_size=body_size,
                content_bottom=y+block_height if laid else content_top, content_limit=limit)
    if original is not None:
        meta.update(photo_offset_x=photo_x, photo_offset_y=photo_y)
    return output.getvalue(), meta
