# -*- coding: utf-8 -*-
"""清理并发写入的 OCR 结果：按图片路径去重，重建合并文字"""
import csv
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
BASE_DIR = r"E:\aiPM\xhs_content_agent\data\m22_analysis"
SRC_CSV = os.path.join(BASE_DIR, "filtered_likes50.csv")
OUT_CSV = os.path.join(BASE_DIR, "ocr_output.csv")
OUT_JSON = os.path.join(BASE_DIR, "ocr_row_text.json")
FIELDNAMES = ["row_index", "likes", "img_index", "image_path", "ocr_text"]

# 1. 去重
seen = {}
with open(OUT_CSV, "r", encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        p = row["image_path"]
        if p not in seen:
            seen[p] = row
print(f"[去重] 原始行 {len(seen) + 0} 唯一图片 {len(seen)} 张")

with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=FIELDNAMES)
    w.writeheader()
    for row in seen.values():
        w.writerow(row)

# 2. 重建合并文字
with open(SRC_CSV, "r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

by_row = {}
for row in seen.values():
    by_row.setdefault(int(row["row_index"]), []).append(row)

row_text = {}
for i, r in enumerate(rows):
    imgs = sorted(by_row.get(i, []), key=lambda x: int(x["img_index"]))
    row_text[str(i)] = {
        "row_index": i,
        "likes": r.get("likes"),
        "author": r.get("author", ""),
        "title": r.get("title", ""),
        "content": r.get("content", ""),
        "image_count": len([p for p in str(r.get("image_local_paths", "")).split("|") if p.strip()]),
        "ocr_combined": "\n=====\n".join(x["ocr_text"] for x in imgs),
        "ocr_images_done": len(imgs),
    }

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(list(row_text.values()), f, ensure_ascii=False, indent=2)

print(f"[重建] ocr_output.csv {len(seen)} 张, ocr_row_text.json {len(row_text)} 条")
done_total = sum(1 for r in row_text.values() if r["ocr_images_done"] == r["image_count"])
print(f"[进度] 完整条目 {done_total}/{len(row_text)}")
