# -*- coding: utf-8 -*-
"""导出 Top10 高赞条目的互动数据与内容类型"""
import csv
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

FILTERED = r"E:\aiPM\xhs_content_agent\data\m22_analysis\filtered_likes50.csv"

with open(FILTERED, "r", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

rows.sort(key=lambda r: -int(r["likes"]))
out = []
for i, r in enumerate(rows[:12]):
    out.append({
        "rank": i + 1,
        "author": r["author"],
        "likes": r["likes"],
        "favs": r["favorites"],
        "comments": r["comments"],
        "imgs": len([u for u in str(r["image_urls"]).split("|") if u.strip()]),
    })

print(json.dumps(out, ensure_ascii=False, indent=1))
