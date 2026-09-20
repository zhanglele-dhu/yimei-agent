# -*- coding: utf-8 -*-
"""
程序 2（断点续跑版）：OCR 提取高赞图文中的图片文字内容（不使用大模型）
=====================================================================
功能：
  1. 读取 程序1 生成的 filtered_likes50.csv
  2. 对每条记录的每张本地图片调用 RapidOCR（本地 ONNX 推理，
     纯 OCR 引擎，不调用任何大模型）提取画面中的文字
  3. 按文字框坐标排序（从上到下、从左到右），还原阅读顺序
  4. 增量写入 + 断点续跑：
       - 每张图完成后立即追加写入 ocr_output.csv 并更新 ocr_row_text.json
       - 已处理的图片跳过（可随时中断、随时续跑）
  5. 输出：
       ocr_output.csv      —— 每张图的 OCR 明细（行索引 | 点赞 | 图片路径 | OCR文本）
       ocr_row_text.json   —— 每条图文合并后的完整文字（供大模型分析使用）
"""
import csv
import json
import os
import sys
import traceback

from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# ---------------- 配置 ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_CSV = os.path.join(BASE_DIR, "filtered_likes50.csv")
OUT_CSV = os.path.join(BASE_DIR, "ocr_output.csv")
OUT_JSON = os.path.join(BASE_DIR, "ocr_row_text.json")
ERR_LOG = os.path.join(BASE_DIR, "ocr_errors.log")
FIELDNAMES = ["row_index", "likes", "img_index", "image_path", "ocr_text"]


def split_paths(field):
    if not field:
        return []
    return [p.strip() for p in str(field).split("|") if p.strip()]


def sort_by_position(det_result):
    """RapidOCR 返回 [[box, text, score], ...]，按 (上边, 左边) 排序恢复阅读顺序"""
    if not det_result:
        return []
    items = []
    for box, text, score in det_result:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append((min(ys), min(xs), text, float(score)))
    items.sort(key=lambda t: (round(t[0] / 10), t[1]))   # 10px 内视为同行
    return items


def load_done():
    """读取已完成的图片路径集合（断点续跑）"""
    done = set()
    if os.path.exists(OUT_CSV):
        with open(OUT_CSV, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                done.add(row["image_path"])
    return done


def load_row_text():
    """读取已合并的条目文字（断点续跑）"""
    if os.path.exists(OUT_JSON):
        with open(OUT_JSON, "r", encoding="utf-8") as f:
            return {int(d["row_index"]): d for d in json.load(f)}
    return {}


def append_csv(row):
    new_file = not os.path.exists(OUT_CSV)
    with open(OUT_CSV, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def save_row_text(row_text):
    temporary = OUT_JSON + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump([row_text[k] for k in sorted(row_text)], f, ensure_ascii=False, indent=2)
    os.replace(temporary, OUT_JSON)


def main():
    with open(SRC_CSV, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    done = load_done()
    row_text = load_row_text()
    print(f"[读取] 待 OCR 条目 {len(rows)} 条，已完成图片 {len(done)} 张")

    cached = {}
    if os.path.exists(OUT_CSV):
        with open(OUT_CSV, encoding="utf-8-sig", newline="") as f:
            for record in csv.DictReader(f):
                cached[record["image_path"]] = record["ocr_text"]
    engine = None
    total_images = 0
    failed = 0

    for i, row in enumerate(rows):
        paths = split_paths(row.get("image_local_paths"))
        likes = row.get("likes")
        lines_all = []
        for j, img_path in enumerate(paths):
            total_images += 1
            if img_path in done:
                lines_all.append(cached[img_path])
                print(f"  [跳过] 已处理 {os.path.basename(img_path)}")
                continue
            if not os.path.exists(img_path):
                failed += 1
                with open(ERR_LOG, "a", encoding="utf-8") as f:
                    f.write(f"{img_path} : 文件不存在\n")
                continue
            try:
                if engine is None:
                    from rapidocr_onnxruntime import RapidOCR
                    engine = RapidOCR()
                result, _ = engine(img_path)
                ordered = sort_by_position(result)
                text = "\n".join(t for _, _, t, _ in ordered)
            except Exception:
                failed += 1
                with open(ERR_LOG, "a", encoding="utf-8") as f:
                    f.write(f"{img_path} :\n{traceback.format_exc()}\n")
                continue  # Failed OCR must remain retryable, not be cached as no text.
            append_csv({
                "row_index": i, "likes": likes, "img_index": j,
                "image_path": img_path, "ocr_text": text,
            })
            done.add(img_path)
            lines_all.append(text)
            print(f"  [{i+1}/{len(rows)}][图{j+1}/{len(paths)}] {os.path.basename(img_path)} OK")
        else:
            pass
        # 更新该条合并文字（无论是否新处理，保证一致性）
        row_text[i] = {
            "row_index": i,
            "likes": likes,
            "author": row.get("author", ""),
            "title": row.get("title", ""),
            "content": row.get("content", ""),
            "image_count": len(paths),
            "ocr_images_done": sum(p in done for p in paths),
            "ocr_combined": "\n=====\n".join(lines_all),
        }
        save_row_text(row_text)
        print(f"  --- 条目 {i+1}/{len(rows)} 已落盘")

    print(f"\n[完成] 图片明细累计 {len(done)} 张 -> {OUT_CSV}")
    print(f"[完成] 条目合并文字 {len(row_text)} 条 -> {OUT_JSON}")
    print(f"[统计] 本运行新增失败 {failed} 张（详见 ocr_errors.log）")


if __name__ == "__main__":
    lock = Path(BASE_DIR) / "ocr.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit("OCR锁已存在。确认没有其他OCR进程后才可删除ocr.lock并重试。")
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        main()
    finally:
        lock.unlink(missing_ok=True)
