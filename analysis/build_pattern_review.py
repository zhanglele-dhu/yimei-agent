"""Build a review-only case library from existing CSV/OCR; no model or OCR calls."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'report' / 'pattern_review'

# Interpretation written by the assistant after reading the selected page OCR and body.
CASES = [
 (14, '价格差异提问', '光子嫩肤，有些',
  ['第1页：直接提出不同报价带来的选择疑问；无后续图片'],
  '同一服务名称＋两个不同报价＋怎么选；它是提问帖，不是已经给出答案的攻略。',
  '同样写着【服务名称】，报价为什么不一样？',
  ['纯文字封面：提出报价疑问', '正文：列出需要确认的计价范围与项目内容；没有真实报价时不编数字'],
  ['可核实的报价及包含内容'], '不能把评论讨论型提问自动包装成专业结论。'),
 (75, '人群限定的文字封面＋正文问答', '初次做M22光子嫩肤',
  ['第1页：初次接触者＋需要知道的事', '正文：先铺垫，再连续Q/A，最后预告下篇'],
  '封面只承诺主题，解释放在正文；图片无需承载全文。',
  '第一次了解【项目】\n先弄清这几个问题',
  ['纯文字封面：对象＋问题范围', '正文：按你确认的问题逐项写Q/A；没有证据的答案留待补充'],
  ['确认的问题清单', '每个答案的独立事实来源'], '原帖效果、疗程及适用性表述没有在本次分析中核实，不能照搬。'),
 (18, '提醒式开头＋可执行问题清单', '以下问题一定要问',
  ['第1页：面诊前的提醒与继续阅读提示', '第2页：14条编号问题，涵盖费用、操作、后续联系等'],
  '先给一个具体场景，再把不知道问什么变成可带走的问题清单。',
  '第一次到店咨询\n这些问题可以提前准备',
  ['纯文字封面：到店场景', '文字清单：用户确认的3至5个问题，数量为本次设计选择', '可选真实照片：帮助解释门店流程，而非强制拍照'],
  ['门店实际咨询流程', '用户真正关心的问题'], '不复制辱骂式标题、不从清单反推治疗方案。'),
 (0, '同维度对照', '一图看懂光子嫩肤',
  ['第1页：围绕不同仪器重复列出相同维度', '第2页：以设备、特点等字段进一步对照'],
  '固定比较维度，让读者横向查找；不是把很多文字塞进一张图。',
  '【A】和【B】\n先看这几个区别',
  ['文字封面：明确比较对象', '对照卡：每一行回答同一个问题；缺证据的单元格明确待核实'],
  ['两方同口径资料', '每个比较字段的来源'], '不能复制样本滤片参数、适应范围或优劣判断。'),
 (27, '连续快问快答', '光子嫩肤快问快答',
  ['第1页：原理与常见顾虑等问答', '第2页：适用问题与频次等问答', '第3页：操作前后及感受等问答', '第4页：后续反应与护理等问答'],
  '各页沿用问题→短答→补充解释结构；问句负责导航。',
  '关于【主题】\n你想问的，逐条说明',
  ['文字封面或第一组Q/A', '按问题分组生成文字卡，每页信息量由预览决定', '正文：补充资料出处和仍需询问专业人员的事项'],
  ['真实常见问题', '经核实的答案'], 'OCR中的医学回答和广告审批文字均不自动继承到新内容。'),
 (47, '目录封面＋逐页兑现', '01什么是M22黄金超光子？',
  ['第1页：四个问题构成目录', '第2页：回答是什么', '第3页：回答工作原理', '第4页：回答优点', '第5页：回答适用人群'],
  '封面提供阅读地图，后续页面逐一对应；标题承诺与正文能逐项核对。',
  '认识【主题】\n从这4个问题开始',
  ['目录封面：只列实际准备回答的问题', '后续每页：一个问题＋核实后的解释', '最后：列出仍需确认的内容；可与末页合并'],
  ['目录与答案一一对应', '所有事实的可靠来源'], '原帖机构身份、研发背书及效果描述均不可移植。'),
 (76, '优点与局限分开讲', '真实优缺点',
  ['第1页：优缺点主题', '第2至3页：分批列优点', '第4至5页：分批列缺点', '第6页：疗程建议'],
  '用正反两面组织信息；不能据此证明内容客观或可信。',
  '了解【项目】之前\n也看看它的局限',
  ['文字封面：能力与局限主题', '内容页：分别列经核实的信息和不能回答的问题', '结尾：下一步需要确认什么，不复用原帖疗程建议'],
  ['能力和局限的可核实证据'], '本案例62赞，不能宣称头部爆款；优缺点里的具体医学断言未核实。'),
 (9, '总览＋逐个细节解释', '右滑对比！',
  ['第1页：真伪话题引入', '第2页：展示整机并提示继续滑动', '第3至6页：围绕不同外观细节加文字指示'],
  '先让读者知道整体，再把注意力引到单个局部；只借鉴总览到细节的顺序。',
  '想了解店里的设备？\n先看名称，再查资料',
  ['自家设备全景或文字封面', '真实型号标识细节＋准确说明', '单独信息卡：提供经过核实的官方资料入口'],
  ['自有设备照片', '公开型号信息', '真实官方查询入口'], '不复制他人图片，不依据外观宣布真伪，也不复制原帖的外观判真规则。'),
]


def main():
    notes = list(csv.DictReader((ROOT / 'filtered_likes50.csv').open(encoding='utf-8-sig')))
    pages = list(csv.DictReader((ROOT / 'ocr_output.csv').open(encoding='utf-8-sig')))
    result = []
    for index, name, anchor, observed, mechanism, title, proposed, required, boundary in CASES:
        note = notes[index]
        imgs = sorted([p for p in pages if int(p['row_index']) == index], key=lambda p: int(p['img_index']))
        evidence = next(p for p in imgs if anchor in p['ocr_text'])
        source = {'row_id': f'row{index:03}', 'title': note['title'] or '原始采集标题为空（不补造）',
                  'author': note['author'], 'url': note['url'],
                  'likes': int(note['likes']), 'favorites': note['favorites'], 'comments': note['comments'],
                  'collected_at': note['collected_at']}
        result.append({'pattern': name, 'source': source,
                       'ocr_evidence': {'quote': anchor, 'page_number': int(evidence['img_index']) + 1,
                                        'local_image': evidence['image_path']},
                       'original_page_structure': observed, 'interpretation_not_causal': mechanism,
                       'new_cover_sentence_pattern': title, 'proposed_new_structure': proposed,
                       'required_facts': required, 'boundary': boundary,
                       'review_status': '待用户审核，未接入Agent', 'visual_review': '本轮仅分析OCR与正文，未审查配色字体构图'})
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {'status': 'review_only', 'scope': '87条高赞样本标题/首图OCR概览；选8条细读，非87条逐页完整分析',
               'origin': '现有filtered_likes50.csv与ocr_output.csv；本轮未重跑OCR',
               'limits': '点赞为采集快照；没有曝光、增粉和低赞同结构对照，不能证明该结构导致高赞。',
               'cases': result}
    (OUT / 'patterns_review.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    md = ['# 高赞内容写法案例库：首批8例（待审核）', '',
          '本稿用于让你选“借鉴哪种写法”，不是新的行为指南；没有修改或接入Agent。', '',
          '## 范围与阅读方式', '', payload['scope']+'。'+payload['origin']+'。', '', payload['limits'], '',
          '“原帖结构”来自采集正文与逐图OCR；“新内容结构”是本次设计建议，两者分开。OCR片段保留识别结果，不自动纠错为医学事实。', '',
          '## 推荐先试的三个方向', '',
          '- 想直接生成文字封面：先看案例2（row075）。',
          '- 想做有用的问题清单：看案例3（row018）。',
          '- 想制作多页科普：看案例6（row047）的目录与逐页对应方式。', '',
          '这些选择依据操作形式与你的需求匹配，不是点赞排名或效果保证。', '']
    for number,c in enumerate(result,1):
        s=c['source']; ev=c['ocr_evidence']
        md += [f"## 案例{number}：{c['pattern']}", '',
               f"原帖：[{s['title']}]({s['url']}) · 作者：{s['author']} · {s['row_id']} · 采集时{s['likes']}赞", '',
               f"OCR证据（第{ev['page_number']}张）：「{ev['quote']}」", '',
               f"[查看对应本地原图](<{ev['local_image']}>)", '', '**原帖怎样展开**', '']
        md += ['- '+x for x in c['original_page_structure']]
        md += ['', '**可借鉴的写法（我的解读）**：'+c['interpretation_not_causal'], '',
               '**新的封面句式**：'+c['new_cover_sentence_pattern'].replace('\n',' / '), '', '**新内容结构建议，非原帖原样复刻**', '']
        md += ['- '+x for x in c['proposed_new_structure']]
        md += ['', '**需要你提供或核实**：'+'；'.join(c['required_facts']), '', '**不迁移的内容**：'+c['boundary'], '']
    md += ['## 确认后才做的下一步', '',
           '你选择希望先实现的写法后，再给出对应功能大纲：输入哪些事实、生成哪些封面候选、在哪里确认、哪几张直接排版、哪几张必须实拍。', '',
           '审查重点：这里有没有把原帖内容读错？新结构是否适合你？是否确实减少了你不知道写什么、下一页放什么的困难？', '']
    (OUT / '案例库_待审核.md').write_text('\n'.join(md), encoding='utf-8')
    print('Created 8 review cases; each OCR anchor validated against its original page. Agent unchanged.')


if __name__ == '__main__':
    main()
