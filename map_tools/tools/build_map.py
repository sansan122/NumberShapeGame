"""
《数与形》地图生成器
------------------------------------------------------------
作用：读取 data/tower.yaml，生成可玩的爬塔地图。

怎么用（零基础照着抄）：
    打开命令行，粘贴这一行并回车：

    C:\\Users\\sanji\\.workbuddy\\binaries\\python\\envs\\naf\\Scripts\\python.exe tools/build_map.py

运行后会在 out/ 目录里生成 map.json（程序用）和 map.html（双击就能看）。
"""

import json
import random
import sys
from pathlib import Path

import yaml

# 项目根目录（这个文件在 tools/ 里，所以往上一级）
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "tower.yaml"
OUT = ROOT / "out"

# 随机种子：写死一个数字，保证每次生成的地图都一样，方便对比调试
SEED = 20260915


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

    for r in range(rows):
        # 第一行和最后一行（Boss 行）固定只放 1 个节点
        if r == 0:
            count = 1
        elif r == rows - 1:
            count = 1
        else:
            # 中间行随机 2~width 个节点
            count = rng.randint(2, width)

        current = []
        # 横向布局：均匀铺开
        for c in range(count):
            # 位置：在 0~1 之间均匀分布（后面画图用）
            x = (c + 1) / (count + 1)

            # 决定节点类型
            if r == rows - 1:
                ntype = {"id": "boss", "name": "层主", "icon": "★", "desc": "本层最终战"}
            elif r % 5 == 4:
                # 每 5 行放一个特殊节点（休整/商店/事件）
                ntype = rng.choice([t for t in node_types
                                    if t["id"] in ("rest", "shop", "event", "treasure")])
            else:
                ntype = weighted_choice(
                    [t for t in node_types if t["id"] not in ("rest", "shop", "treasure")],
                    rng,
                )

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
            link_count = 1 if rng.random() < 0.3 else 2
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


def build():
    """主流程：读配置 -> 生成三层地图 -> 写出结果。"""
    cfg = load_config()
    rng = random.Random(SEED)
    OUT.mkdir(exist_ok=True)

    result = {
        "tower_name": cfg["tower"]["name"],
        "seed": SEED,
        "floors": [],
    }

    for floor in cfg["floors"]:
        print(f"  正在生成第 {floor['id']} 层：{floor['name']} ...")
        nodes, edges = generate_floor(
            floor, cfg["node_types"], cfg["path_costs"], rng
        )
        cost_edges = [e for e in edges if e["cost"]]
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
            },
        })
        s = result["floors"][-1]["stats"]
        print(f"    节点 {s['node_count']} 个｜连边 {s['edge_count']} 条"
              f"｜其中带代价 {s['cost_edge_count']} 条")

    # ---- 写出 JSON（给程序用）----
    json_path = OUT / "map.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n已生成：{json_path}")

    return result


if __name__ == "__main__":
    print("=" * 56)
    print("  《数与形》地图生成器")
    print("=" * 56)
    build()
    print("\n完成。")
