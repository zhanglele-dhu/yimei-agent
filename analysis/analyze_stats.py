# -*- coding: utf-8 -*-
"""分析高赞 vs 低赞图文特征差异，输出统计 JSON 供报告使用
   高赞组：filtered_likes50.csv（87条，OCR row_index 与之对应）
   低赞组：原始 CSV 中点赞 < 50 的条目
"""
import csv
import json
import os
import statistics
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
BASE_DIR = r"E:\aiPM\xhs_content_agent\data\m22_analysis"
FILTERED = os.path.join(BASE_DIR, "filtered_likes50.csv")
SRC = r"E:\aiPM\xhs_content_agent\data\reference_notes\20260915_203358_208240.csv"
OCR_JSON = os.path.join(BASE_DIR, "ocr_row_text.json")


def to_int(v):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return 0


def split_urls(field):
    return [u.strip() for u in str(field).split("|") if u.strip()]


with open(FILTERED, "r", encoding="utf-8-sig") as f:
    high = list(csv.DictReader(f))
with open(SRC, "r", encoding="utf-8-sig") as f:
    all_rows = list(csv.DictReader(f))
low = [r for r in all_rows if to_int(r["likes"]) < 50]
with open(OCR_JSON, "r", encoding="utf-8") as f:
    ocr_list = json.load(f)
ocr_data = {d["row_index"]: d for d in ocr_list}

print(f"high={len(high)} low={len(low)} ocr={len(ocr_list)}")

stats = {}
for name, group in (("high", high), ("low", low)):
    likes = [to_int(r["likes"]) for r in group]
    favs = [to_int(r["favorites"]) for r in group]
    comm = [to_int(r["comments"]) for r in group]
    imgs = [len(split_urls(r["image_urls"])) for r in group]
    stats[name] = {
        "n": len(group),
        "avg_likes": round(sum(likes) / len(likes), 1),
        "median_likes": sorted(likes)[len(likes) // 2],
        "max_likes": max(likes),
        "avg_favs": round(sum(favs) / len(favs), 1),
        "avg_comments": round(sum(comm) / len(comm), 1),
        "avg_imgs": round(sum(imgs) / len(imgs), 1),
        "img_dist": dict(sorted(Counter(imgs).items())),
        "has_title": sum(1 for r in group if str(r.get("title", "")).strip()),
    }

def author_type(a):
    a = a or ""
    if "医生" in a or "主任" in a or "医师" in a:
        return "医生/医师"
    if any(k in a for k in ("医院", "机构", "中心", "门诊", "整形", "医疗", "诊所")):
        return "医院/机构"
    return "素人/其他"

for name, group in (("high", high), ("low", low)):
    stats[name]["author_type"] = dict(Counter(author_type(r["author"]) for r in group))

# 正文关键词：按每条出现率统计
kw_list = ["对比", "区别", "避坑", "攻略", "建议收藏", "干货", "总结", "多少钱",
           "怎么选", "适合", "功效", "体验", "术后", "恢复", "过程", "注意事项",
           "误区", "避雷", "性价比", "真实"]
def kw_rates(group):
    c = Counter()
    for r in group:
        txt = r["content"] or ""
        for k in kw_list:
            if k in txt:
                c[k] += 1
    return {k: round(v / len(group) * 100, 1) for k, v in c.items()}

stats["high_kw_rate"] = kw_rates(high)
stats["low_kw_rate"] = kw_rates(low)

# OCR 特征（仅高赞组，与 ocr_data 对齐）
ocr_feat = []
for i, r in enumerate(high):
    oc = ocr_data.get(i, {})
    txt = oc.get("ocr_combined", "") or ""
    ocr_feat.append({
        "row_index": i, "likes": to_int(r["likes"]),
        "ocr_len": len(txt),
        "has_compare": any(k in txt for k in ("对比", "区别", "怎么选", "如何选择", "适合什么", "一览", "一图看懂")),
        "has_price": any(k in txt for k in ("价格", "多少钱", "预算", "价位")),
        "has_steps": any(k in txt for k in ("步骤", "流程", "术后", "第1", "第2", "Day1", "Day2", "第一天", "第一天", "恢复期")),
        "has_list": txt.count("\n") > 10,   # 长清单/信息图特征
    })
stats["ocr_feat"] = ocr_feat

lens = [x["ocr_len"] for x in ocr_feat]
stats["ocr_summary"] = {
    "avg_len": round(statistics.mean(lens)),
    "median_len": sorted(lens)[len(lens) // 2],
    "pct_compare": round(sum(1 for x in ocr_feat if x["has_compare"]) / len(ocr_feat) * 100, 1),
    "pct_steps": round(sum(1 for x in ocr_feat if x["has_steps"]) / len(ocr_feat) * 100, 1),
    "pct_list": round(sum(1 for x in ocr_feat if x["has_list"]) / len(ocr_feat) * 100, 1),
}

imgs_high = [len(split_urls(r["image_urls"])) for r in high]
likes_high = [to_int(r["likes"]) for r in high]
stats["img_likes_corr_high"] = round(statistics.correlation(imgs_high, likes_high), 3) if len(imgs_high) > 1 else None

with open(os.path.join(BASE_DIR, "analysis_stats.json"), "w", encoding="utf-8") as f:
    json.dump(stats, f, ensure_ascii=False, indent=2)

print(json.dumps({"high": stats["high"], "low": stats["low"], "ocr_summary": stats["ocr_summary"],
                  "img_likes_corr_high": stats["img_likes_corr_high"]}, ensure_ascii=False, indent=1))
print("kw rate 高:", stats["high_kw_rate"])
print("kw rate 低:", stats["low_kw_rate"])
