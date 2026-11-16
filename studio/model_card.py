"""Skill -> model-authored HTML/CSS -> isolated Chromium -> visual model review."""
import base64
import hashlib
import html
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re

from PIL import Image

from . import llm
from .card_layout import content_blocks, split_production_notes
from .models import CardDesign, CardVisualCheck

SKILL_DIR = Path(__file__).parent / 'design_skills' / 'xhs-note-creator'
VERSION = 'skill-model-html-v2'
TOKEN = re.compile(r'\{\{([A-Z][A-Z0-9_]*)\}\}')


class PipelineError(RuntimeError):
    def __init__(self, message, audit):
        super().__init__(message)
        self.audit = audit


def public_error(message):
    """Present actionable reading problems; keep raw geometry in the audit."""
    if any(term in message for term in ('clipped','outside canvas','safe margins','PHOTO: hidden','font too small','overlapping text')):
        issues=[]
        if any(term in message for term in ('BLOCK_','TITLE:')):issues.append('部分文字超出了图片边界或被遮挡')
        if 'PHOTO:' in message:issues.append('照片没有完整显示')
        return '这次排版未通过检查：'+ '，'.join(issues or ['内容没有完整显示'])+'。原图已保留，请重新生成。'
    return None


class Fragment(HTMLParser):
    tags = {'div','section','header','footer','article','main','aside','h1','h2','h3','p','strong','em','span','ul','ol','li','br','hr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.tokens = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.tags:
            raise ValueError('设计包含不允许的HTML标签：'+tag)
        for key, value in attrs:
            if key != 'class' or not re.fullmatch(r'[a-zA-Z0-9_\- ]{1,200}', value or ''):
                raise ValueError('设计只能使用class属性，不能加载外部资源或事件')
        if tag not in ('br','hr'):
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in ('br','hr'):
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            raise ValueError('设计HTML标签未正确闭合')

    def handle_data(self, data):
        self.tokens.extend(TOKEN.findall(data))
        if TOKEN.sub('', data).strip():
            raise ValueError('设计添加了未经确认的文字，请只使用给定槽位')

    def handle_decl(self, decl):
        raise ValueError('只允许卡片内部HTML片段')


def validate_design(design, slots, required):
    fragment = Fragment()
    fragment.feed(design.html)
    fragment.close()
    if fragment.stack:
        raise ValueError('设计HTML标签未正确闭合')
    for name in required:
        if fragment.tokens.count(name) != 1:
            raise ValueError('每个发布内容槽位必须恰好使用一次：'+name)
    if any(name not in slots or fragment.tokens.count(name) > 1 for name in fragment.tokens):
        raise ValueError('设计引用了未知或重复槽位')
    css = design.css
    if re.search(r'url\s*\(|@|\\|</|expression\s*\(|javascript|animation|transition|behavior\s*:', css, re.I):
        raise ValueError('设计CSS禁止外部资源、脚本和动态内容')
    for value in re.findall(r'(?<![\w-])content\s*:\s*([^;}]+)', css, re.I):
        if value.strip() not in ('""', "''", 'none', 'normal'):
            raise ValueError('CSS不能添加未确认的文字')


def prune_unapproved_diagrams(fragment):
    """Remove label-only diagram subtrees, not the approved text or decorations.

    Stripping invented labels alone leaves empty boxes with large fixed heights.
    Remove the whole unapproved subtree so it cannot push real copy off canvas.
    """
    class Pruner(HTMLParser):
        def __init__(self):
            super().__init__();self.stack=[];self.ranges=[];self.invalid=False
            self.lines=[0]
            for match in re.finditer('\n',fragment):self.lines.append(match.end())
        def source_pos(self):
            line,col=self.getpos();return self.lines[line-1]+col
        def handle_starttag(self,tag,attrs):
            if tag not in Fragment.tags:self.invalid=True
            if tag not in ('br','hr'):self.stack.append({'tag':tag,'start':self.source_pos(),'bad':False,'slot':False})
        def handle_data(self,data):
            has_slot=bool(TOKEN.search(data));has_bad=bool(TOKEN.sub('',data).strip())
            for node in self.stack:
                node['slot'] |= has_slot;node['bad'] |= has_bad
        def handle_endtag(self,tag):
            if not self.stack or self.stack[-1]['tag']!=tag:self.invalid=True;return
            node=self.stack.pop()
            if node['bad'] and not node['slot']:
                self.ranges.append((node['start'],fragment.find('>',self.source_pos())+1))
    parser=Pruner();parser.feed(fragment)
    if parser.invalid or parser.stack:return fragment,0
    kept=[];end=0;count=0
    for start,stop in sorted(parser.ranges,key=lambda r:(r[0],-r[1])):
        if start<end:continue
        kept.append(fragment[end:start]);end=stop;count+=1
    kept.append(fragment[end:])
    return ''.join(kept),count


def compose(design, slots):
    def substitute(match):
        name = match.group(1)
        if name in ('PHOTO', 'VISUAL'):
            return slots[name]
        value = slots[name]
        escaped = html.escape(value)
        if name.startswith('BLOCK_'):
            # A short, author-approved lead becomes a visual heading. Keep every
            # source character, including the colon; never invent a summary.
            match = re.match(r'^([^：:\n]{1,14}[：:])(.+)$', value, re.S)
            if match:
                escaped = '<strong class="point-lead">'+html.escape(match.group(1))+'</strong><span class="point-detail">'+html.escape(match.group(2))+'</span>'
        return '<span class="content-slot" data-slot="'+name+'">'+escaped+'</span>'
    fragment = TOKEN.sub(substitute, design.html)
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; script-src \'none\'">'
            '<style>*{box-sizing:border-box}body{font-family:"Microsoft YaHei","Noto Sans CJK SC",sans-serif}'
            +design.css+
            'html,body{margin:0!important;width:1080px!important;height:1440px!important;overflow:hidden!important}'
            '#card{width:1080px!important;height:1440px!important;overflow:hidden!important;position:relative}'
            '.content-slot{display:block;white-space:pre-wrap;text-transform:none!important;font-variant:normal!important}.source-photo{display:block!important;width:100%!important;height:320px!important;'
            'object-fit:contain!important;object-position:center!important;flex-shrink:0!important}'
            '.generated-visual{display:block!important;width:100%!important;height:auto!important;max-height:240px!important;object-fit:contain!important;object-position:center!important;flex-shrink:0!important}'
            '.point-lead{display:block;font-size:1.22em;font-weight:750;line-height:1.3;margin-bottom:.28em}.point-detail{display:block}'
            '</style></head><body><div id="card">'+fragment+'</div></body></html>')


def render_html(document, required, scale=1):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={'width':1080,'height':1440}, device_scale_factor=scale,
                                          java_script_enabled=False, service_workers='block')
            context.route('**/*', lambda route: route.abort())
            page = context.new_page()
            page.set_content(document, wait_until='load', timeout=15000)
            page.evaluate('() => document.fonts.ready')
            report = page.evaluate('''required => {
              const problems = [], boxes = [], sizes = {}, slot_texts = {};
              const root = document.getElementById('card');
              for (const name of required) {
                const node = document.querySelector('[data-slot="'+name+'"]');
                if (!node) { problems.push(name+': missing'); continue; }
                const style = getComputedStyle(node), rect = node.getBoundingClientRect();
                sizes[name] = parseFloat(style.fontSize);
                slot_texts[name] = node.textContent;
                if (name === 'PHOTO' || name === 'VISUAL') {
                  if (!node.complete || !node.naturalWidth || rect.width < 120 || rect.height < 80) problems.push('PHOTO: invalid or too small');
                } else if (node.textContent.trim()) {
                  if (parseFloat(style.fontSize) < (name === 'TITLE' ? 40 : 28)) problems.push(name+': font too small');
                  const range = document.createRange(); range.selectNodeContents(node);
                  for (const line of range.getClientRects()) {
                    if (line.left < 30 || line.top < 30 || line.right > 1050 || line.bottom > 1410) problems.push(name+': clipped/outside safe margins');
                  }
                  boxes.push({name,x:rect.x,y:rect.y,right:rect.right,bottom:rect.bottom});
                }
                for (let ancestor=node; ancestor && ancestor!==document.body; ancestor=ancestor.parentElement) {
                  const s=getComputedStyle(ancestor), a=ancestor.getBoundingClientRect();
                  if(s.display==='none'||s.visibility==='hidden'||parseFloat(s.opacity)<.8||a.width<=0||a.height<=0) problems.push(name+': hidden');
                  if (ancestor!==root && (s.overflow==='hidden'||s.overflow==='clip'||s.overflow==='auto'||s.overflow==='scroll') &&
                    (rect.left<a.left-1||rect.top<a.top-1||rect.right>a.right+1||rect.bottom>a.bottom+1)) problems.push(name+': clipped by container');
                }
                if(rect.left<0||rect.top<0||rect.right>1080||rect.bottom>1440) problems.push(name+': outside canvas');
              }
              for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){
                const a=boxes[i],b=boxes[j];
                if(Math.min(a.right,b.right)-Math.max(a.x,b.x)>3 && Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y)>3) problems.push(a.name+'/'+b.name+': overlapping text');
              }
              return {passed:!problems.length,issues:[...new Set(problems)],font_sizes:sizes,slot_texts};
            }''', required)
            if not report['passed']:
                raise ValueError('；'.join(report['issues'][:8]))
            return page.screenshot(type='png', animations='disabled'), report
        finally:
            browser.close()


def generate(title, text, *, kind, page, total_pages, theme, reference_images, photo=None,
             previous=None, regenerate=False, previous_image_sha256=None, generated_visual=None, render_scale=1, editorial_context=None):
    audit = {'version':VERSION,'steps':[],'traces':[]}
    try:
        if not llm.supports_card_design():
            raise RuntimeError('请先在成品预览右侧点击“设置设计模型”，配置可用的视觉模型接口')
        skill = (SKILL_DIR/'SKILL.md').read_text(encoding='utf-8')
        style_reference = (SKILL_DIR/'professional.css').read_text(encoding='utf-8')
        audit['skill'] = {'name':'xhs-note-creator','sha256':hashlib.sha256(skill.encode()).hexdigest()}
        audit['steps'].append({'step':'skill','status':'completed'})
        public, notes = split_production_notes(text)
        blocks = content_blocks(public)
        slots = {'TITLE':title,'KICKER':'实拍手记' if kind=='photo' else '', 'PAGE':f'{page:02d} / {total_pages:02d}'}
        required = ['TITLE'] if title.strip() else []
        for i, (block_kind, value) in enumerate(blocks,1):
            slots[f'BLOCK_{i}'] = value
            if block_kind == 'step':
                slots[f'INDEX_{i}'] = f'{i:02d}'
            required.append(f'BLOCK_{i}')
        images = list(reference_images[:2])
        photo_info = None
        if photo:
            with Image.open(io.BytesIO(photo)) as image:
                photo_info = {'width':image.width,'height':image.height,'sha256':hashlib.sha256(photo).hexdigest()}
                fmt = Image.MIME.get(image.format,'image/png')
            slots['PHOTO'] = '<img class="source-photo" data-slot="PHOTO" src="data:'+fmt+';base64,'+base64.b64encode(photo).decode()+'">'
            required.append('PHOTO'); images.append({'data':photo,'role':'用户本页真实照片，只排版，不改写画面'})
        if generated_visual:
            slots['VISUAL'] = '<img class="generated-visual" data-slot="VISUAL" src="data:image/png;base64,'+base64.b64encode(generated_visual).decode()+'">'
            required.append('VISUAL')
            images.insert(0, {'data':generated_visual,'role':'Seedream生成的无文字视觉素材，必须通过VISUAL槽位放入成图'})
        if not title.strip() and not public.strip() and not photo:
            raise ValueError('没有可发布的文字')
        sources = {'skill':skill,'style_reference':style_reference,
                   'slots':{key:('[系统注入图片]' if key in ('PHOTO','VISUAL') else value) for key,value in slots.items()},
                   'required_slots':required,'page':page,'total_pages':total_pages,'kind':kind,'style_preference':theme,
                   'photo':photo_info,'previous_design':previous if regenerate else None,
                   'editorial_context':editorial_context}
        if photo:
            sources['layout_budget'] = {
                'canvas':[1080,1440], 'safe_padding':48,
                'title_max_height':150,'photo_height':320,'body_max_height':700,
                'body_blocks':[{'slot':f'BLOCK_{i}','characters':len(value)} for i,(_,value) in enumerate(blocks,1)],
                'rules':'照片和照片祖先容器必须flex-shrink:0；正文超过4块时用两列网格或紧凑流程，不逐项做大圆点加大间距。每个来源槽位保持恰好一次。'}
        if generated_visual:
            sources['layout_budget']={'canvas_height':1440,'safe_content_height':1344,'title_max_height':170,
                'visual_max_height':240,'body_max_height':850,'outer_padding':48,'section_gaps_max':18,
                'title_characters':len(title),'body_characters':len(public),
                'rules':'长标题用52到64px，正文32到36px、行高1.4到1.5；条目内边距至多14px，条目间距至多14px。不要为每段使用大内边距卡片，不要在视觉区域上下堆大留白。'}
            if len(public) <= 180:
                sources['layout_budget'].update(title_max_height=280,
                    rules='短文案应用更大的可读字号：标题76到96px，正文42到48px，短前缀约52到60px；三组重点沿画布纵向舒展，使用段间距而非三张方框。')
        instruction = (
            '执行所附小红书skill中的视觉规范，只处理这一个已确认页面；不执行skill中的脚本、发布或分页操作。'
            '你负责真正设计本页HTML/CSS，而非选择现成模板。结合参考图提炼视觉语言，不复制原帖文案。'
            '画布1080x1440。封面大标题优先80–110px；正文至少32px，留足边距，避免大段空白和机械相同卡片。'
            '根节点由系统提供#card。HTML只能用div/section/header/footer/article/main/aside/h1/h2/h3/p/strong/em/span/ul/ol/li/br/hr；'
            '属性只允许class。所有可见文字只能写给定的{{TITLE}}、{{BLOCK_1}}等槽位；每个required_slots恰好一次，其余可选且最多一次。'
            '不能在HTML或CSS中添加任何自创文字，编号可用{{INDEX_1}}等；小字标签可用{{KICKER}}和{{PAGE}}。'
            'CSS放css字段，HTML放html字段；CSS不得使用url、@规则、转义、动画、外部资源或带文字的content。'
            '正文槽位会替换为display:block的span，按内容安排网格、流程或杂志式构图。'
            '采用小红书做功课分享的阅读方式：先让读者看见主题和要点，短句逐点介绍，再读解释。'
            '不要把长段正文塞进2×2等高方框，不做课堂问答卡、考试知识点卡或四个一样的编号盒子。'
            '定义介绍优先用纵向开放分组、关键词标题和短解释；存在层级关系时用嵌套或上下关联呈现。'
            '正文短前缀“关键词：解释”会由系统拆成.point-lead与.point-detail，分别设计标题和解释层级。'
            '数字只用于真实步骤，不给并列概念机械添加01/02；正文卡默认不使用KICKER标签。'
            '优先靠字号、字重、段间距和少量关键词色建立层级，不用每段左侧粗色条、统一方框或大面积无意义留白。'
            '如有{{PHOTO}}，只写<div class="photo-area">{{PHOTO}}</div>，系统会注入真正的img.source-photo。'
            '禁止自己输出任何img标签、src或alt。照片区域及祖先容器设置flex-shrink:0，照片宽100%、高320px、object-fit:contain。'
            '实拍页必须遵守layout_budget：标题最大150px高，正文总高至多700px，所有区域总高含间距小于1344px。'
            '正文有多个流程步骤时，使用紧凑两列或流程网格，不要把8个步骤各画成大卡片纵向堆叠。'
            '不要压小文字以硬塞内容；实在放不下时应合理组织版式。代码简洁，完整JSON尽量控制在6000字符内。'
            + ('本次为重新生成：保留全部文字和真实照片，设计明显不同的布局，结合上一版设计避免重复。' if regenerate else '整组图文保持协调，但封面与内页有明确区别。'))
        feedback = ''
        if generated_visual:
            instruction += ('本页包含Seedream生成的无文字插画。必须使用{{VISUAL}}槽位，作为标题旁或边角的小面积视觉点缀；'
                            '不要为其单独安排整条无信息横幅。系统注入img.generated-visual，宽随父容器，等比显示，最高240px。'
                            '建议父容器宽150到180px，保持图片可见，不覆盖正文。'
                            '本页必须优先遵守layout_budget；长标题不要使用80到110px大字号。'
                            '正文与标题全部使用原文槽位，结合素材设计整体配色与层级；不要生成其他图片。')
        for attempt in range(2):
            design, trace = llm.card_completion(CardDesign, instruction, {**sources,'revision_feedback':feedback}, images, phase='design')
            # Some compatible models repeat the system-owned root ID. Remove
            # only that exact first-element ID; all other attributes stay validated.
            design.html = re.sub(r'^(\s*<[a-zA-Z0-9]+\b[^>]*?)\s+id=[\"\']card[\"\'](?=[\s>])',
                                 r'\1', design.html, count=1)
            if photo and '{{PHOTO}}' not in design.html:
                # An empty model-generated image is only a placeholder; replace
                # exactly one with the system-owned original photo slot.
                class PhotoPlaceholder(HTMLParser):
                    def __init__(self):super().__init__();self.candidates=[]
                    def handle_starttag(self,tag,attrs):
                        values=dict(attrs)
                        if (tag=='img' and set(values)<= {'class','src','alt'} and
                                values.get('src','')=='' and values.get('class')=='source-photo'):
                            self.candidates.append(self.get_starttag_text())
                    handle_startendtag=handle_starttag
                parser=PhotoPlaceholder();parser.feed(design.html)
                if len(parser.candidates)==1:
                    design.html=design.html.replace(parser.candidates[0],'{{PHOTO}}',1)
                    audit.setdefault('normalizations',[]).append('empty image placeholder replaced by original PHOTO slot')
            # Discard model-invented decorative labels. Approved text still enters
            # only through mandatory slots, which are validated exactly once.
            discarded = [TOKEN.sub('',match.group(2)).strip() for match in re.finditer(r'(^|>)([^<>]*)(?=<|$)',design.html)
                         if TOKEN.sub('',match.group(2)).strip()]
            design.html, pruned = prune_unapproved_diagrams(design.html)
            if pruned:audit.setdefault('pruned_unapproved_diagrams',[]).append(pruned)
            def slots_only(match):
                data = match.group(2)
                extra = TOKEN.sub('', data).strip()
                if not extra:
                    return match.group(0)
                return match.group(1) + ''.join('{{'+name+'}}' for name in TOKEN.findall(data))
            design.html = re.sub(r'(^|>)([^<>]*)(?=<|$)', slots_only, design.html)
            if discarded:
                audit.setdefault('discarded_unapproved_labels', []).append(discarded)
            audit['traces'].append(trace)
            audit['steps'].append({'step':'design','attempt':attempt+1,'status':'completed','model':trace['model']})
            try:
                validate_design(design, slots, required)
                document = compose(design, slots)
                raw, geometry = render_html(document, required, scale=render_scale) if render_scale != 1 else render_html(document, required)
                for name in required:
                    if name not in ('PHOTO','VISUAL') and geometry['slot_texts'].get(name) != slots[name].replace('\r\n','\n').replace('\r','\n'):
                        raise ValueError('排版文字与已确认原文不一致：'+name)
                geometry['exact_text_passed'] = True
                if regenerate and previous_image_sha256 and hashlib.sha256(raw).hexdigest()==previous_image_sha256:
                    raise ValueError('重新设计的成图与上一张完全相同，请更换构图')
                audit['steps'].append({'step':'render','attempt':attempt+1,'status':'completed'})
            except (ValueError, RuntimeError) as exc:
                feedback = '上一版未通过本地排版校验：'+str(exc)
                audit['steps'].append({'step':'render','attempt':attempt+1,'status':'failed','message':str(exc)[:600]})
                sources['previous_design'] = design.model_dump()
                if attempt == 0:
                    continue
                raise
            check, check_trace = llm.card_completion(CardVisualCheck,
                '检查给定成图：逐项看标题/正文是否完整清晰，有无遮挡、溢出、小字、大面积无效留白；实拍是否完整。'
                '对照给定文字判断明显漏字，但不要做医学正确性认证。任何可见问题都应passed=false并列出可执行修改。'
                '只检查上述客观阅读问题，不自行设定配色、装饰或分类标签要求，不因个人风格偏好拒绝。'
                '短文案的合理留白可以接受；只在文字被挤成难读小字或分布明显失衡时报告留白问题，不建议新增文案来填空。'
                '有原始实拍照片时对照检查：照片内本来就有的墙面、地面、留白，以及保持全图产生的适配边距，不当作排版缺陷。',
                {'approved_title':title,'approved_blocks':[v for _,v in blocks],'source_photo':photo_info},
                [{'data':raw,'role':'待检查的最终成图'}]+([{'data':photo,'role':'原始实拍照片，用于比对完整性及区分原画面留白'}] if photo else []), phase='review')
            audit['traces'].append(check_trace)
            passed = check.passed and not check.issues
            audit['steps'].append({'step':'review','attempt':attempt+1,'status':'passed' if passed else 'failed','model':check_trace['model'],'summary':check.summary,'issues':check.issues})
            if passed:
                audit['design'] = design.model_dump(); audit['review'] = check.model_dump()
                meta = {'width':1080,'height':1440,'method':'skill_model_html','layout_version':VERSION,
                        'generation_mode':'model','skill':audit['skill'],'design_model':trace['model'],
                        'review_model':check_trace['model'],'design_direction':design.direction,
                        'visual_review':check.model_dump(),'geometry_check':geometry,'pipeline':audit['steps'],
                        'production_notes':notes,'public_text':public,'source_photo':photo_info}
                return raw, meta, audit
            feedback = '上一版视觉检查未通过：'+check.summary+'；'+'；'.join(check.issues)
            sources['previous_design'] = design.model_dump()
        raise ValueError('视觉检查仍未通过：'+feedback)
    except Exception as exc:
        message = str(exc)
        key = llm.card_model_config().get('api_key')
        if key:
            message = message.replace(key, '[redacted]')
        audit['error'] = message[:1500]
        raise PipelineError(message, audit) from exc
