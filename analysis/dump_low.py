# -*- coding: utf-8 -*-
"""对比分析：低赞组典型内容 + 收藏率 + 发布时间分布"""
import csv
import json
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

SRC = r"E:\aiPM\xhs_content_agent\data\reference_notes\20260915_203358_208240.csv"
FILTERED = r"E:\aiPM\xhs_content_agent\data\m22_analysis\filtered_likes50.csv"

def to_int(v):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return 0

with open(SRC, "r", encoding="utf-8-sig") as f:
    all_rows = list(csv.DictReader(f))
with open(FILTERED, "r", encoding="utf-8-sig") as f:
    high = list(csv.DictReader(f))

low = [r for r in all_rows if to_int(r["likes"]) < 50]
high_ids = {r["url"] for r in high}
low = [r for r in low if r["url"] not in high_ids]
print(f"high={len(high)} low={len(low)}")

# 收藏率
for name, group in (("high", high), ("low", low)):
    ratio = [to_int(r["favorites"]) / max(to_int(r["likes"]), 1) for r in group if to_int(r["likes"]) > 0]
    print(f"{name} 收藏/赞 均值: {sum(ratio)/len(ratio):.2f}")

# 发布时间（小时）分布
def hour_of(p):
    try:
        return datetime.fromisoformat(p).hour
    except Exception:
        return None

for name, group in (("high", high), ("low", low)):
    hours = [hour_of(r["publish_time"]) for r in group]
    hours = [h for h in hours if h is not None]
    c = Counter(hours)
    top3 = c.most_common(3)
    print(f"{name} 发布小时TOP3: {top3}")

# 低赞组典型内容抽样（点赞最低的10条）
low_sorted = sorted(low, key=lambda r: to_int(r["likes"]))
print("\n=== 低赞组样例（点赞最低）===")
for r in low_sorted[:8]:
    print(f"[赞{to_int(r['likes'])}] {r['author']} | 图{len([u for u in str(r['image_urls']).split('|') if u.strip()])}张")
    print("  正文:", (r["content"] or "").replace("\n", " / ")[:110])
