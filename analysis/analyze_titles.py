# -*- coding: utf-8 -*-
"""统计 M22 高赞 vs 低赞标题特征（纯规则，不用大模型）"""
import csv, re, sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HIGH = Path(r"E:\aiPM\xhs_content_agent\data\m22_analysis\filtered_likes50.csv")
FULL = Path(r"E:\aiPM\xhs_content_agent\data\reference_notes\20260915_203358_208240.csv")

def load(p):
    rows = []
    with open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows

high = load(HIGH)
full = load(FULL)
by_id = {r.get("url", ""): r for r in full}
# 高赞集合
high_urls = {r["url"] for r in high}
low = [r for r in full if r.get("url") not in high_urls and r.get("likes", "0").isdigit() and int(r["likes"]) < 50]
print(f"高赞 {len(high)} 条，低赞 {len(low)} 条")

def feats(title):
    t = title.strip()
    n = len(t)
    emoji = len(re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]", t))
    return {
        "len": n,
        "question": 1 if re.search(r"[？?]|吗$|么$|能不能|能不能|怎么|为什么|多少|能$", t) else 0,
        "num": 1 if re.search(r"\d", t) else 0,
        "vs": 1 if re.search(r"VS|vs|对比|还是|区别|怎么选|如何选|PK", t) else 0,
        "guide": 1 if re.search(r"攻略|指南|一图|一张图|详解|大全|整理|答疑|Q&A|清单", t) else 0,
        "opinion": 1 if re.search(r"避雷|避坑|得罪人|劝退|注意|真相|实话|别|不要|后悔|警惕|防", t) else 0,
        "excl": 1 if "！" in t or "❗" in t or "❗️" in t else 0,
        "emoji": emoji,
        "percent": 1 if re.search(r"%|％|折|次|年|月|岁|天", t) else 0,
    }

def summarize(rows):
    agg = Counter()
    lens = []
    for r in rows:
        f = feats(r["title"])
        lens.append(f["len"])
        for k in ["question", "num", "vs", "guide", "opinion", "excl", "percent"]:
            agg[k] += f[k]
        agg["emoji_total"] += f["emoji"]
    n = len(rows)
    print(f"\n--- n={n} 平均字数 {sum(lens)/n:.1f} ---")
    for k in ["question", "num", "vs", "guide", "opinion", "excl", "percent"]:
        print(f"  {k}: {agg[k]} ({agg[k]/n*100:.0f}%)")
    print(f"  emoji: 平均 {agg['emoji_total']/n:.1f} 个")

print("\n========== 高赞组 ==========")
summarize(high)
print("\n========== 低赞组 ==========")
summarize(low)

# 高频词（简单：去除常见停用词后按字词出现）
def words(rows):
    c = Counter()
    stop = set("的了是在有要和就都这那也么啊我你他她它们什么怎么为能会").union("光子嫩肤M22医美")
    for r in rows:
        t = re.sub(r"[#\[\]#❗️！？?,.。、()（）【】\s\"']", "", r["title"])
        for ch in re.findall(r"[\u4e00-\u9fa5]{2,4}", t):
            c[ch] += 1
    return c

hc = words(high)
lc = words(low)
print("\n高赞标题高频词组 Top20:", hc.most_common(20))
print("低赞标题高频词组 Top20:", lc.most_common(20))
