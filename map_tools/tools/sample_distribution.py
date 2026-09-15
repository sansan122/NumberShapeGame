# -*- coding: utf-8 -*-
"""
地图生成分布抽样：跑 N 次，看看各种节点的数量是否合理且有变化。
重点检查：
  1. 每次生成的地图是否真的不同（随机性）
  2. 每种特殊节点是否每层都至少出现 1 次
  3. 是否还会出现「一行三个商店」这种扎堆
"""
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

import build_map as B  # noqa: E402

ROUNDS = 40
SPECIALS = ["rest", "shop", "event", "treasure"]

sig_seen = set()
missing = Counter()          # 某类型在某层没出现 -> 计数
row_of_three_special = 0     # 一行里特殊节点 >= 3 的次数
per_type_counts = {t: [] for t in SPECIALS}

print("=" * 62)
print("地图生成分布抽样（%d 轮）" % ROUNDS)
print("=" * 62)

cfg = B.load_config()

for i in range(ROUNDS):
    import random
    rng = random.Random()          # 每轮全新随机
    floor_sigs = []
    for floor in cfg["floors"]:
        nodes, edges = B.generate_floor(
            floor, cfg["node_types"], cfg["path_costs"], rng)

        # 1) 本层签名：只看类型序列，用来判断地图是否重复
        sig = tuple(n["type"] for n in nodes)
        floor_sigs.append(sig)

        # 2) 每种特殊节点是否至少 1 个
        cnt = Counter(n["type"] for n in nodes)
        for t in SPECIALS:
            per_type_counts[t].append(cnt.get(t, 0))
            if cnt.get(t, 0) == 0:
                missing[(floor["id"], t)] += 1

        # 3) 有没有某一行堆了 3 个以上特殊节点
        rows = {}
        for n in nodes:
            rows.setdefault(n["row"], []).append(n["type"])
        for r, types in rows.items():
            if sum(1 for x in types if x in SPECIALS) >= 3:
                row_of_three_special += 1

    sig_seen.add(tuple(floor_sigs))

print("\n[1] 随机性")
print("  %d 轮生成了 %d 张互不相同的地图" % (ROUNDS, len(sig_seen)))
if len(sig_seen) == ROUNDS:
    print("  [OK] 每轮都不一样，随机性充足")
else:
    print("  [!!] 有重复：只有 %d 种" % len(sig_seen))

print("\n[2] 每种特殊节点的数量分布")
for t in SPECIALS:
    lst = per_type_counts[t]
    nums = Counter(lst)
    dist = "  ".join("%d个:%d次" % (k, v) for k, v in sorted(nums.items()))
    print("  %-9s 最少 %d  最多 %d  ｜ %s"
          % (t, min(lst), max(lst), dist))

print("\n[3] 「某层完全没有某类型」的情况")
if not missing:
    print("  [OK] 三层 x 四类型全部出现过，没有缺项")
else:
    for (fid, t), n in sorted(missing.items()):
        print("  [!!] 第 %d 层缺 %s，共 %d 次" % (fid, t, n))

print("\n[4] 特殊节点扎堆")
print("  一行 >= 3 个特殊节点：%d 次" % row_of_three_special)
if row_of_three_special == 0:
    print("  [OK] 没有扎堆")
else:
    print("  [!!] 仍有扎堆，建议继续调")

print("\n" + "=" * 62)
