"""Deterministic cards; original photo pixels are pasted without resampling."""
import io
import os
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


def render(title, text, photo=None, background=None):
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
    pad=max(20,round(width*.065))
    scratch=Image.new('RGB',(width,10));draw=ImageDraw.Draw(scratch)
    size=max(16,round(width/19))
    while True:
        title_font=font(size);body_font=font(max(14,round(size*.6)))
        tl=wrap(title,draw,title_font,width-2*pad-max(12,width//50)) if title else []
        bl=wrap(text,draw,body_font,width-2*pad) if text else []
        title_step=round(size*1.45); body_step=round(max(14,round(size*.6))*1.6)
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
    if (title or text) and background is not None and original is None:
        # 半透明圆角面板垫在文字下方，保证任意底图上的可读性
        panel_bottom=min(total-8,pad*2+len(tl)*title_step+(pad if tl and bl else 0)+len(bl)*body_step+round(pad*.5))
        overlay=Image.new('RGBA',out.size,(0,0,0,0))
        ImageDraw.Draw(overlay).rounded_rectangle(
            (round(pad*.5),max(6,round(pad*.5)),width-round(pad*.5),panel_bottom),
            radius=round(width*.045),fill=(255,255,255,210))
        out=Image.alpha_composite(out.convert('RGBA'),overlay).convert('RGB')
    d=ImageDraw.Draw(out)
    if title or text:
        d.rectangle((pad,round(pad*.55),pad+max(5,width//140),pad+len(tl)*title_step),fill='#21634f')
    y=pad
    for line in tl:
        d.text((pad+max(12,width//50),y),line,font=title_font,fill='#163d32');y+=title_step
    if tl and bl:y+=pad
    for line in bl:
        d.text((pad,y),line,font=body_font,fill='#273b35');y+=body_step
    if original:out.paste(original,(0,header_height))
    b=io.BytesIO();out.save(b,format='PNG')
    return b.getvalue(), {'width':width,'height':total,'photo_offset_y':header_height,
                         'method':out_method}


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
                  'backgrounds':task.get('backgrounds',{}),
                  'copy_review':task.get('copy_review'), 'sources':task.get('generation_sources',[]),
                  'limitations':'参考结构不证明爆款或医学正确；内容经用户确认，不代表平台通过。文字卡底图由CogView生成（AI生成装饰，不含文字；标题正文由程序排版叠加）。'}
        z.writestr('来源记录.json',json.dumps(evidence,ensure_ascii=False,indent=2))
        z.writestr('待核实记录.txt','\n'.join(task['draft'].get('missing_information',[])) or '模型未列出额外待核实项，仍需发布前人工审核。')
    return buffer.getvalue()
