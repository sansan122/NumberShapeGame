"""
《数与形》地图生成器
------------------------------------------------------------
作用：读取 data/tower.yaml，生成可玩的爬塔地图。

怎么用（零基础照着抄）：
    打开命令行，粘贴这一行并回车：

    C:\\Users\\sanji\\.workbuddy\\binaries\\python\\envs\\naf\\Scripts\\python.exe tools/build_map.py

运行后会在 out/ 目录里生成 map.json（程序用）和 map.html（双击就能看）。
"""

import argparse
import json
import random
import sys
from pathlib import Path

import yaml

# 项目根目录（这个文件在 tools/ 里，所以往上一级）
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "tower.yaml"
OUT = ROOT / "out"

# 默认随机种子。
#   - 直接跑：用这个固定值，每次生成结果一致（方便对比调试）
#   - 加 --random：不用它，改用系统随机源，每次地图都不一样
#   - 加 --seed 1234：用你指定的数字，想要可复现的特定地图时用
DEFAULT_SEED = 20260915


def load_config():
    """读取 tower.yaml 配置文件。"""
    if not DATA.exists():
        print(f"[错误] 找不到配置文件：{DATA}")
        sys.exit(1)
    with open(DATA, encoding="utf-8") as f:
        return yaml.safe_load(f)


def weighted_choice(node_types, rng):
    """按 weight 权重随机挑一个节点类型。"""
    total = sum(t["weight"] for t in node_types)
    roll = rng.uniform(0, total)
    upto = 0.0
    for t in node_types:
        upto += t["weight"]
        if roll <= upto:
            return t
    return node_types[-1]


def plan_floor_types(rows, width, node_types, rng):
    """
    先给整层规划好每种节点各要几个，再随机撒到各行里去。

    为什么这么做（这是「一直生成 3 战斗 + 1 事件」的根因）：
      旧写法是「逐行独立掷骰子」，还按 `r % 5 == 4` 硬性指定特殊行。
      结果特殊行里第一个特殊节点定死之后，**同一行剩下的位置仍然从
      「不含休整/商店/宝箱」的池子里抽**，于是整行变成
      `=休整 √商店 √商店 √商店` 这种清一色。同时普通池里 event
      权重 12、其他特殊节点被排除，所以普通行几乎永远是
      「3 个战斗 + 1 个事件」。

    新写法的思路：
      1. 先按权重算出整层各种特殊节点各要几个（带上下限约束）
      2. 把这些特殊节点**打散撒进不同行**，每行最多 1 个
      3. 剩下的位置全部填普通战斗/精英

    返回：{row_index: [类型 id, ...]}
    """
    # ---- 1. 可用的类型池 ----
    # 普通行只能出这些（精英可以出现在普通行）
    normal_pool = [t for t in node_types if t["id"] in ("battle", "elite")]
    # 特殊节点：一批是「每层该有几个」的稀缺资源
    special_defs = [t for t in node_types
                    if t["id"] in ("rest", "shop", "event", "treasure")]

    # ---- 2. 先决定每行几个节点（后面要按这个填类型）----
    mid_rows = list(range(1, rows - 1))
    row_counts = {r: rng.randint(2, width) for r in mid_rows}

    # ---- 3. 按权重算特殊节点的目标数量 ----
    # 用「整层节点数 × 权重占比」来定，再夹在合理区间内，
    # 避免某一层一个休整点都没有、或者商店泛滥。
    special_weight = sum(t["weight"] for t in special_defs)
    normal_weight = sum(t["weight"] for t in normal_pool)
    all_weight = special_weight + normal_weight

    # 每种特殊节点的配额（上下限写死，保证体验稳定）
    # 下限一律为 1：**每种特殊节点每层至少出现一次**，
    # 否则会出现「这一层一个宝箱都没有」的干瘪感。
    quota_bounds = {
        "rest":     (1, 4),    # 每层至少 1 个休整点，不然血量无以为继
        "shop":     (1, 3),
        "event":    (1, 5),
        "treasure": (1, 3),
    }

    est_total = 2 + sum(row_counts.values())

    quotas = {}
    for t in special_defs:
        lo, hi = quota_bounds.get(t["id"], (1, 3))
        share = t["weight"] / all_weight
        want = int(round(est_total * share))
        # ★ 关键：在目标值上下浮动 ±1，让「每层各几个」也有随机性。
        #   不加这个的话，权重固定 -> 配额固定 -> 每层数量永远一样，
        #   随机模式看起来也像"每次都差不多"。
        want += rng.choice([-1, 0, 0, 1])
        quotas[t["id"]] = max(lo, min(hi, want))

    # 特殊节点总数不能超过「可用行数」，否则一行要放两个，
    # 又会退回「一行两三个商店」的观感。
    # 可用行数 = 中间行里扣掉起点附近和 Boss 前一行
    usable_rows = [r for r in mid_rows if 2 <= r <= rows - 3] or list(mid_rows)
    max_special = len(usable_rows)

    # 先砍超出部分：从配额最大、且还大于下限的那个开始砍
    while sum(quotas.values()) > max_special:
        reducible = [k for k in quotas
                     if quotas[k] > quota_bounds.get(k, (1, 3))[0]]
        if not reducible:
            break
        biggest = max(reducible, key=lambda k: quotas[k])
        quotas[biggest] -= 1

    # ---- 4. 组装每一行的类型列表 ----
    plan = {r: ["_pending"] * row_counts[r] for r in mid_rows}

    # 特殊节点打散到不同行：每行最多 1 个，而且尽量互相隔开
    # （避免第 3/4/5 行连着三家商店）
    rng.shuffle(usable_rows)
    row_queue = list(usable_rows)

    # 按「出现次数少的优先放」排一下，保证宝箱（通常只有 1 个）
    # 也有位置，不会被商店/事件把行占满
    todo = []
    for tid, cnt in quotas.items():
        for _ in range(cnt):
            todo.append(tid)
    rng.shuffle(todo)

    placed_rows = []
    for tid in todo:
        if not row_queue:
            # 行不够了，插到已有特殊行的空位上（一行最多 2 个）
            for r in sorted(plan, key=lambda x: len(
                    [i for i in plan[x] if i != "_pending"])):
                if len(plan[r]) >= 3:
                    for i in range(len(plan[r])):
                        if plan[r][i] == "_pending":
                            plan[r][i] = tid
                            break
                    break
            continue

        # 优先挑「离已放置的行最远」的那一行
        if placed_rows:
            row_queue.sort(key=lambda r: -min(abs(r - p) for p in placed_rows))
        r = row_queue.pop(0)
        for i in rng.sample(range(len(plan[r])), len(plan[r])):
            if plan[r][i] == "_pending":
                plan[r][i] = tid
                break
        placed_rows.append(r)

    # 剩下的位置填普通/精英
    for r in mid_rows:
        for i in range(len(plan[r])):
            if plan[r][i] == "_pending":
                plan[r][i] = weighted_choice(normal_pool, rng)["id"]

    return plan


def generate_floor(floor, node_types, cost_pool, rng):
    """
    生成单层地图。

    结构说明：
      - 每层有 rows 行（策划案要求 12–18）
      - 每行有 1~width 个节点
      - 相邻两行之间连边，玩家只能往上走
      - 部分边带「路线代价」标签
    """
    rows = floor["rows"]
    width = floor["width"]
    nodes = []
    edges = []

    node_id = 0
    row_nodes = []  # 记录每行的节点 id，用于连边

    # 整层的类型规划：先算好每种要几个，再撒到各行
    type_plan = plan_floor_types(rows, width, node_types, rng)
    type_by_id = {t["id"]: t for t in node_types}

    for r in range(rows):
        # 第一行和最后一行（Boss 行）固定只放 1 个节点
        if r == 0:
            count = 1
        elif r == rows - 1:
            count = 1
        else:
            count = len(type_plan.get(r) or []) or rng.randint(2, width)

        current = []
        # 横向布局：均匀铺开
        for c in range(count):
            # 位置：在 0~1 之间均匀分布（后面画图用）
            x = (c + 1) / (count + 1)

            # 决定节点类型
            if r == 0:
                # 起点固定为普通战斗：一上来就遇精英太难
                ntype = type_by_id.get("battle") or {
                    "id": "battle", "name": "普通战斗", "icon": "×",
                    "desc": "常规敌人，掉落卡牌与形值"}
            elif r == rows - 1:
                # boss 不在 node_types 里，是层主专属，这里兜一个默认
                ntype = type_by_id.get("boss") or {
                    "id": "boss", "name": "层主", "icon": "★",
                    "desc": "本层最终战"}
            else:
                tid = type_plan[r][c] if c < len(type_plan[r]) else "battle"
                ntype = type_by_id.get(tid) or {
                    "id": "battle", "name": "普通战斗", "icon": "×",
                    "desc": "常规敌人，掉落卡牌与形值"}

            nodes.append({
                "id": node_id,
                "row": r,
                "col": c,
                "x": round(x, 3),
                "type": ntype["id"],
                "type_name": ntype["name"],
                "icon": ntype["icon"],
                "desc": ntype["desc"],
                "floor": floor["id"],
            })
            current.append(node_id)
            node_id += 1

        row_nodes.append(current)

    # ---- 连边：相邻行之间连接 ----
    edge_id = 0
    for r in range(rows - 1):
        upper = row_nodes[r]
        lower = row_nodes[r + 1]

        for i, uid in enumerate(upper):
            # 每个节点连到下一行的 1~2 个节点
            # 用位置比例决定连谁，保证线不交叉太多
            ux = nodes[uid]["x"]
            candidates = sorted(lower, key=lambda nid: abs(nodes[nid]["x"] - ux))

            # 起始行（只有一个节点）必须连到下一行所有节点，
            # 否则开局只有一条路，玩家没有选择余地。
            if r == 0:
                link_count = len(candidates)
            else:
                # 中间行：连 1~2 个，保证有分岔但又不会太乱
                link_count = min(len(candidates),
                                 2 if rng.random() > 0.3 else 1)

            targets = candidates[:link_count]

            for tid in targets:
                cost = None
                # 约 15% 的边带代价标签
                if rng.random() < 0.15:
                    c = rng.choice(cost_pool)
                    cost = {
                        "id": c["id"],
                        "name": c["name"],
                        "desc": c["desc"],
                        "math_note": c["math_note"],
                    }
                edges.append({
                    "id": edge_id,
                    "from": uid,
                    "to": tid,
                    "cost": cost,
                })
                edge_id += 1

    return nodes, edges


def build(seed=None):
    """主流程：读配置 -> 生成三层地图 -> 写出结果。

    seed=None 时用系统随机源（每次都不一样）；
    传具体数字则结果可复现。
    """
    cfg = load_config()
    rng = random.Random(seed)
    OUT.mkdir(exist_ok=True)

    # 记下真正用的种子：用户传了就用用户的，没传就是随机的那个
    used_seed = seed if seed is not None else rng.randint(1, 999999999)

    result = {
        "tower_name": cfg["tower"]["name"],
        "seed": used_seed,
        "floors": [],
    }

    for floor in cfg["floors"]:
        print(f"  正在生成第 {floor['id']} 层：{floor['name']} ...")
        nodes, edges = generate_floor(
            floor, cfg["node_types"], cfg["path_costs"], rng
        )
        cost_edges = [e for e in edges if e["cost"]]

        # 统计各种节点各有多少个
        type_names = {}
        for n in nodes:
            type_names[n["type_name"]] = type_names.get(n["type_name"], 0) + 1

        result["floors"].append({
            "id": floor["id"],
            "name": floor["name"],
            "stage": floor["stage"],
            "grade": floor["grade"],
            "desc": floor["desc"],
            "boss": floor["boss"],
            "boss_hp": floor["boss_hp"],
            "theme_color": floor["theme_color"],
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "cost_edge_count": len(cost_edges),
                "battle_count": sum(1 for n in nodes if n["type"] == "battle"),
                "elite_count": sum(1 for n in nodes if n["type"] == "elite"),
                "rest_count": sum(1 for n in nodes if n["type"] == "rest"),
                "by_type": type_names,
            },
        })
        s = result["floors"][-1]["stats"]
        print(f"    节点 {s['node_count']} 个｜连边 {s['edge_count']} 条"
              f"｜其中带代价 {s['cost_edge_count']} 条")
        # 把各类型数量也打出来，方便一眼看出分布是否合理
        dist = "  ".join("%s %d" % (k, v) for k, v in sorted(type_names.items()))
        print(f"    分布：{dist}")

    # ---- 写出 JSON（给程序用）----
    json_path = OUT / "map.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n已生成：{json_path}")
    print(f"随机种子：{used_seed}")

    return result


def main():
    """命令行入口。

    用法：
        python tools/build_map.py              # 固定种子，结果每次一样
        python tools/build_map.py --random     # 每次随机，地图都不一样
        python tools/build_map.py --seed 1234  # 指定种子，可复现
    """
    ap = argparse.ArgumentParser(
        description="《数与形》地图生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python tools/build_map.py              固定种子（默认）\n"
            "  python tools/build_map.py --random     每次都不一样\n"
            "  python tools/build_map.py --seed 1234  指定种子\n"
        ),
    )
    ap.add_argument("--random", action="store_true",
                    help="用系统随机源，每次生成的地图都不一样")
    ap.add_argument("--seed", type=int, default=None,
                    help="指定随机种子（数字），用于复现某张特定地图")
    args = ap.parse_args()

    if args.random:
        seed = None
    elif args.seed is not None:
        seed = args.seed
    else:
        seed = DEFAULT_SEED

    print("=" * 56)
    print("  《数与形》地图生成器")
    print("=" * 56)
    if seed is None:
        print("  模式：每次随机（--random）")
    else:
        print(f"  模式：固定种子 {seed}")
    print()
    build(seed=seed)
    print("\n完成。")


if __name__ == "__main__":
    main()
