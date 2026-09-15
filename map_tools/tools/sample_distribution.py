# -*- coding: utf-8 -*-
"""
地图生成分布抽样：跑 N 次，定量检查「随机性够不够」。

用户反馈过两次「不够随机」，所以这里不只检查「有没有缺项」，
更要检查**波动幅度** —— 如果每种节点的数量每次都差不多，
即使地图不同，观感上也会觉得「每次都一样」。

检查项：
  1. 随机性       每轮地图是否都不同
  2. 数量波动     每种节点的「最少/最多/标准差」，越大越随机
  3. 缺项         是否出现「某层一个宝箱都没有」
  4. 扎堆         一行里 >= 3 个特殊节点（观感差）
  5. 全战斗行     整行都是 battle/elite（观感单调）
  6. 死路         是否存在没有出边的节点（会导致卡死）
  7. 连通         从起点能否走到 Boss
"""
import os
import sys
import statistics
from collections import Counter

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

import build_map as B  # noqa: E402

ROUNDS = 60
SPECIALS = ["rest", "shop", "event", "treasure"]
ALL_TYPES = ["battle", "elite", "rest", "shop", "event", "treasure"]

sig_seen = set()
missing = Counter()
row_of_three_special = 0
all_combat_rows = 0
total_rows = 0
dead_ends = 0
unreachable_boss = 0

per_type = {t: [] for t in ALL_TYPES}
node_counts = []
floor_type_counts = {t: [] for t in SPECIALS}

print("=" * 66)
print("地图生成分布抽样（%d 轮）" % ROUNDS)
print("=" * 66)

cfg = B.load_config()

for i in range(ROUNDS):
    import random
    rng = random.Random()
    floor_sigs = []
    for floor in cfg["floors"]:
        nodes, edges = B.generate_floor(
            floor, cfg["node_types"], cfg["path_costs"], rng)

        floor_sigs.append(tuple(n["type"] for n in nodes))
        node_counts.append(len(nodes))

        cnt = Counter(n["type"] for n in nodes)
        for t in ALL_TYPES:
            per_type[t].append(cnt.get(t, 0))
        for t in SPECIALS:
            floor_type_counts[t].append(cnt.get(t, 0))
            if cnt.get(t, 0) == 0:
                missing[(floor["id"], t)] += 1

        # 按行统计
        rows = {}
        for n in nodes:
            rows.setdefault(n["row"], []).append(n["type"])
        for r, types in rows.items():
            total_rows += 1
            n_special = sum(1 for x in types if x in SPECIALS)
            if n_special >= 3:
                row_of_three_special += 1
            # 整行都是战斗（且不是最后一行的 Boss 行）
            if all(x in ("battle", "elite") for x in types) and len(types) >= 2:
                all_combat_rows += 1

        # 死路检查
        has_out = {e["from"] for e in edges}
        max_row = max(n["row"] for n in nodes)
        for n in nodes:
            if n["row"] < max_row and n["id"] not in has_out:
                dead_ends += 1

        # 连通性：从起点 BFS 能否到 Boss
        out = {}
        for e in edges:
            out.setdefault(e["from"], []).append(e["to"])
        start = [n["id"] for n in nodes if n["row"] == 0][0]
        boss = [n["id"] for n in nodes if n["row"] == max_row][0]
        seen, stack = {start}, [start]
        while stack:
            cur = stack.pop()
            for nxt in out.get(cur, []):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        if boss not in seen:
            unreachable_boss += 1

    sig_seen.add(tuple(floor_sigs))

print("\n[1] 随机性")
print("  %d 轮生成 %d / %d 张互不相同的地图" % (ROUNDS, len(sig_seen), ROUNDS))
print("  [%s] %s" % ("OK" if len(sig_seen) == ROUNDS else "!!",
                     "每轮都不一样" if len(sig_seen) == ROUNDS else "有重复"))

print("\n[2] 每层节点总数（波动越大越有随机感）")
print("  最少 %d　最多 %d　平均 %.1f　标准差 %.2f"
      % (min(node_counts), max(node_counts),
         statistics.mean(node_counts), statistics.pstdev(node_counts)))
ok_spread = (max(node_counts) - min(node_counts)) >= 6
print("  [%s] 极差 %d%s" % ("OK" if ok_spread else "!!",
                            max(node_counts) - min(node_counts),
                            "" if ok_spread else "　—— 波动偏小"))

print("\n[3] 每种节点的数量波动（每层计）")
print("  %-9s %-5s %-5s %-6s %s" % ("类型", "最少", "最多", "标准差", "分布"))
for t in ALL_TYPES:
    # 每层单独看，这里用「每层的数量」列表
    lst = per_type[t]
    nums = Counter(lst)
    sd = statistics.pstdev(lst)
    dist = " ".join("%d:%d" % (k, v) for k, v in sorted(nums.items()))
    print("  %-9s %-5d %-5d %-6.2f %s" % (t, min(lst), max(lst), sd, dist))

print("\n[4] 缺项检查（某层完全没有某类型）")
if not missing:
    print("  [OK] 三层 x 四类型全部出现过")
else:
    for (fid, t), n in sorted(missing.items()):
        print("  [!!] 第 %d 层缺 %s，共 %d 次" % (fid, t, n))

print("\n[5] 观感检查")
print("  一行 >= 3 个特殊节点：%d 次 / %d 行（%.2f%%）"
      % (row_of_three_special, total_rows,
         row_of_three_special * 100.0 / total_rows))
print("  整行纯战斗的行：%d 次 / %d 行（%.2f%%）"
      % (all_combat_rows, total_rows,
         all_combat_rows * 100.0 / total_rows))
if row_of_three_special == 0:
    print("  [OK] 没有特殊节点扎堆")
else:
    print("  [!!] 有 %d 次扎堆" % row_of_three_special)

print("\n[6] 正确性")
print("  死路节点：%d 个" % dead_ends)
print("  [%s] %s" % ("OK" if dead_ends == 0 else "!!",
                     "零死路" if dead_ends == 0 else "有节点走不出去！"))
print("  走不到 Boss 的地图：%d 张" % unreachable_boss)
print("  [%s] %s" % ("OK" if unreachable_boss == 0 else "!!",
                     "三层都能从起点走到 Boss"
                     if unreachable_boss == 0 else "存在走不通的地图！"))

print("\n" + "=" * 66)

bad = (len(sig_seen) != ROUNDS or dead_ends or unreachable_boss
       or missing or not ok_spread)
sys.exit(1 if bad else 0)
