# -*- coding: utf-8 -*-
"""
程序 1：筛选高赞条目 + 下载图片 + 回填 CSV
=================================================
功能：
  1. 读取小红书提取的原始 CSV（200 条）
  2. 筛选出点赞数 >= 50 的条目（独立成表）
  3. 逐条打开（下载）该部分条目的所有图片到本地 images/ 目录
  4. 把本地图片路径回填到筛选后的 CSV 中（新增列 image_local_paths，
     与 image_urls 一一对应，用 | 分隔）
输出：
  filtered_likes50.csv  —— 筛选+回填后的 CSV（交付物）
  images/               —— 下载的图片文件
"""
import csv
import os
import sys
import time
import requests

sys.stdout.reconfigure(encoding="utf-8")

# ---------------- 配置 ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_CSV = r"E:\aiPM\xhs_content_agent\data\reference_notes\20260915_203358_208240.csv"
OUT_CSV = os.path.join(BASE_DIR, "filtered_likes50.csv")
IMG_DIR = os.path.join(BASE_DIR, "images")
LIKE_THRESHOLD = 50          # 点赞阈值
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://www.xiaohongshu.com/",
}
RETRY = 2                    # 每张图失败重试次数
TIMEOUT = 30                 # 单张图超时（秒）


def to_int(v):
    """安全转 int，兼容空值/字符串数字"""
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return 0


def split_urls(field):
    """把 image_urls / image_local_paths 字段拆成列表"""
    if not field:
        return []
    return [u.strip() for u in str(field).split("|") if u.strip()]


def download_image(url, save_path):
    """下载单张图片，返回 True/False"""
    for attempt in range(1, RETRY + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200 and len(r.content) > 0:
                with open(save_path, "wb") as f:
                    f.write(r.content)
                return True
            print(f"    [失败] HTTP {r.status_code} - {url[:80]}")
        except Exception as e:
            print(f"    [重试 {attempt}/{RETRY}] {url[:80]} -> {e}")
            time.sleep(1.5)
    return False


def main():
    # 1. 读取原始 CSV
    with open(SRC_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)
    print(f"[读取] 原始数据共 {len(rows)} 条")

    # 2. 筛选点赞 >= 阈值
    filtered = [r for r in rows if to_int(r.get("likes")) >= LIKE_THRESHOLD]
    filtered.sort(key=lambda r: -to_int(r.get("likes")))
    print(f"[筛选] 点赞 >= {LIKE_THRESHOLD} 的条目共 {len(filtered)} 条")

    # 3. 逐条下载图片
    os.makedirs(IMG_DIR, exist_ok=True)
    total_img = 0
    ok_img = 0
    fail_log = []
    for i, row in enumerate(filtered):
        urls = split_urls(row.get("image_urls"))
        if not urls:
            row["image_local_paths"] = ""
            continue
        local_paths = []
        for j, url in enumerate(urls):
            ext = ".webp"
            low = url.lower()
            for cand in (".jpg", ".jpeg", ".png", ".webp"):
                if cand in low:
                    ext = cand
                    break
            save_name = f"row{i:03d}_img{j:02d}{ext}"
            save_path = os.path.join(IMG_DIR, save_name)
            total_img += 1
            if download_image(url, save_path):
                ok_img += 1
                local_paths.append(save_path)
            else:
                fail_log.append((i, url))
        row["image_local_paths"] = " | ".join(local_paths)
        print(f"  [{i+1}/{len(filtered)}] 点赞{row.get('likes')} 图片 {len(urls)} 张 -> "
              f"成功 {len(local_paths)} 张")

    # 4. 新增列并写回 CSV
    if "image_local_paths" not in fieldnames:
        fieldnames = fieldnames + ["image_local_paths"]
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(filtered)

    print(f"\n[完成] 筛选后 {len(filtered)} 条已写入: {OUT_CSV}")
    print(f"[图片] 共需下载 {total_img} 张，成功 {ok_img} 张，失败 {len(fail_log)} 张")
    if fail_log:
        print("[失败明细] 行索引 -> URL 前80字符:")
        for idx, url in fail_log:
            print(f"  row{idx:03d} -> {url[:80]}")


if __name__ == "__main__":
    main()
