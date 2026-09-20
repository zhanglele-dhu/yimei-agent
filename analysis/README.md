# analysis/ — 小红书高赞图文归因分析

这一目录回答一个问题：**为什么有的科普图文能拿高赞，有的不行。**

## 它在整个项目里的位置

```
collector/（采集笔记和图片） → analysis/（本目录：找出高赞规律） → studio/（把规律用进创作工作台）
```

## 脚本说明

| 脚本 | 作用 |
|---|---|
| `step1_filter_download.py` | 筛选点赞≥50 的条目，批量下载图片，回填本地路径 |
| `step2_ocr.py` | 逐图 OCR 提取文字（支持中断续跑） |
| `analyze_stats.py` | 高赞组 vs 低赞组多维度对照统计 |
| `analyze_titles.py` | 标题特征分析 |
| `audit_evidence.py` / `build_pattern_review.py` | 人工复核与规律评审的辅助导出 |
| `dump_top.py` / `dump_low.py` / `dump_top12.py` | 定性样本导出 |
| `make_thumbnails.py` | 报告用缩略图生成 |
| `dedupe_ocr.py` | OCR 结果去重（一次性修复工具） |

`analysis_stats.json` / `verified_stats.json` 是一次真实分析的聚合统计结果（87 条高赞 vs 113 条低赞）。

## 运行说明

脚本在**本地数据目录**中运行（图片、OCR 明细等原始数据**不入本仓库**——它们是从小红书采集的第三方内容）。依赖：`requests`、`pillow`、`numpy`、`rapidocr_onnxruntime`。

## 核心结论（来自 2026-09-15 的一次完整分析）

- 高赞组平均点赞 326.7 vs 低赞组 14.8（22 倍差距），且收藏、评论全维度领先
- 四个驱动因素：**专业身份**（医生账号占比 3.3 倍）、**图片形态**（82.8% 是结构化信息图）、**决策型内容**（术后/注意事项/功效高频）、**图片数量无关**（相关系数 0.049）

完整报告（含图表）在本地 `data/m22_analysis/report/report.html`，不在仓库中。
