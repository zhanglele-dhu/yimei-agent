"""Owned writing guidance plus verified, local-only source expression snippets."""
import hashlib
import json
import re
from pathlib import Path

GUIDE=Path(__file__).parent/'writing_styles/friend-sharing/SKILL.md'
ARTIFACTS=('以上文案仅供参考','你可以根据自己的实际体验进行修改','作为一个AI','作为一个人工智能')


def is_template(text):
    blocks=[s.strip() for s in text.splitlines() if len(s.strip())>25]
    return any(s in text for s in ARTIFACTS) or len(blocks)!=len(set(blocks))


def profile(root,manifest,style='friend-sharing'):
    from . import tones
    if style not in tones.BY_ID:raise ValueError('语气类别不存在')
    preset=tones.BY_ID[style]
    catalog=tones.catalog(root,manifest)
    labeled=[item for item in catalog['items'] if item['status']=='classified' and item.get('voice_id')==style]
    labeled.sort(key=lambda item:-item.get('confidence',0))
    examples=[{'case_id':item['case_id'],'title':item['title'],'url':item['url'],
               'quote':item['evidence'][0]['quote'],'lesson':item['reason']} for item in labeled[:3] if item.get('evidence')]
    guide=(GUIDE.read_text(encoding='utf-8-sig')+'\n\n'+tones.guide(style)) if style=='friend-sharing' else tones.guide(style)
    result={'id':style,'title':preset['title'],'guide':guide,'criteria':preset['criteria'],
            'source_examples':examples,'selection':'仅用同语气的语义分类原文，不按点赞数选文风。',
            'excluded_template_ids':[i['case_id'] for i in catalog['items'] if i['status']=='excluded'],
            'source_bundle_id':manifest['bundle_id'],'taxonomy_version':tones.VERSION,
            'version':hashlib.sha256(guide.encode()).hexdigest()[:16]}
    folder=Path(root)/'style_library';folder.mkdir(parents=True,exist_ok=True)
    (folder/(style+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def context(task):
    style=task.get('writing_style')
    if not style:return None
    return {key:style[key] for key in ('id','title','version','criteria','taxonomy_version') if key in style}


VOICE_POLICY = 'friend-sharing-v3-reader-side-no-lecture-chain'

def voice_issues(draft):
    issues=[]
    for page in draft.get('pages',[]):
        text=page.get('text','')
        if re.search(r'不是[^。\n]{0,70}也不是',text):
            issues.append(f"第{page['number']}页用不是、也不是连续否定纠错，仍像讲义；按具体特点正面介绍")
        if re.search(r'先(?:理解这一点|掌握这些概念|弄懂这些概念)',text):
            issues.append(f"第{page['number']}页用学习口令收尾；改为具体收获或自然衔接")
    return issues
