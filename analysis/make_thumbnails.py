# -*- coding: utf-8 -*-
"""生成高赞条目首图缩略图，用于报告视觉证据"""
import os
import sys
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

IMG_DIR = r"E:\aiPM\xhs_content_agent\data\m22_analysis\images"
ASSET_DIR = r"E:\aiPM\xhs_content_agent\data\m22_analysis\report\assets"
os.makedirs(ASSET_DIR, exist_ok=True)

# (源文件名, 目标文件名, 说明)
targets = [
    ("row000_img00.webp", "top1_ichart.jpg", "赞2122·一图看懂光子仪器区别"),
    ("row001_img00.webp", "top2_compare.jpg", "赞1601·黑金超光子VS黄金超光子"),
    ("row002_img00.webp", "top3_table.jpg", "赞1467·热门光子嫩肤仪器对比表"),
    ("row003_img00.webp", "top4_guide.jpg", "赞1390·滤光片搭配攻略图"),
    ("row009_img00.webp", "top10_antifake.jpg", "赞737·真假仪器鉴别图"),
]

for src, dst, label in targets:
    sp = os.path.join(IMG_DIR, src)
    dp = os.path.join(ASSET_DIR, dst)
    try:
        im = Image.open(sp)
        im = im.convert("RGB")
        w, h = im.size
        nw = 640
        nh = int(h * nw / w)
        im = im.resize((nw, nh), Image.LANCZOS)
        im.save(dp, "JPEG", quality=80)
        print(f"OK {dst} {nw}x{nh} <- {src}")
    except Exception as e:
        print(f"FAIL {src}: {e}")
