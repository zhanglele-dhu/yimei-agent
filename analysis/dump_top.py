# -*- coding: utf-8 -*-
"""导出高赞条目的图文内容快照，供定性分析"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

with open(r"E:\aiPM\xhs_content_agent\data\m22_analysis\ocr_row_text.json", "r", encoding="utf-8") as f:
    data = json.load(f)

data.sort(key=lambda d: -int(d["likes"]))
for d in data[:10]:
    print("=" * 72)
    print(f"[#{d['row_index']}] 赞{d['likes']} | {d['author']}")
    body = (d["content"] or "").replace("\n", " / ")
    print("正文:", body[:150])
    ocr = d["ocr_combined"] or ""
    print(f"OCR图文字数: {len(ocr)}")
    print(ocr[:450])
    print()
