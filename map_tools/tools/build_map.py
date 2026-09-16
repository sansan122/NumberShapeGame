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

# 路径统一走 game_env：
#   源码模式 -> 项目根的 map_tools/data/tower.yaml
#   exe 模式 -> 打进包里的 map_tools/data/tower.yaml（临时解包目录）
# 直接写 Path(__file__).parent 的话，打包后读不到。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
try:
    import game_env as _E
    _RES = _E.resource_path()
    _HAS_ENV = True
except Exception:                       # noqa: BLE001
    # 独立跑这个脚本时（game_env 不在搜索路径上）退回老逻辑
    _E = None
    _RES = Path(__file__).resolve().parent.parent
    _HAS_ENV = False

DATA = _RES / "map_tools" / "data" / "tower.yaml"
if not DATA.exists():
    # 兼容老布局：data/ 就在同级
    DATA = _RES / "data" / "tower.yaml"
OUT = _RES / "map_tools" / "out"

# 默认随机种子。
#   - 直接跑：用这个固定值，每次生成结果一致（方便对比调试）
#   - 加 --random：不用它，改用系统随机源，每次地图都不一样
#   - 加 --seed 1234：用你指定的数字，想要可复现的特定地图时用
DEFAULT_SEED = 20260915


def build_in_memory(seed=None):
    """生成一整座塔的地图，直接返回 dict，**不落盘**。

    给游戏主程序用：每次开新一局就调一次，这样每局的节点布局
    都不一样（而不是反复读同一个 map.json）。

    seed=None  -> 用系统随机源，每局都不同
    seed=数字  -> 用指定种子，可复现（存档靠这个）
    """
    cfg = load_config()

    # 关键：先把种子定下来，**再用它建 rng**。
    # 以前写成 `rng = random.Random(seed)` + `used_seed = rng.randint(...)`，
    # 结果 seed=None 时：rng 是用系统熵播种的，而 used_seed 只是
    # 「这个 rng 的第一次抽样」—— 两者毫无关系。
    # 表现就是**报告出来的种子复现不出这张地图**，
    # 存档记的 seed 是假的 → 读档后地图变了。
    if seed is None:
        seed = random.SystemRandom().randint(1, 999999999)
    rng = random.Random(seed)

    result = {
        "tower_name": cfg["tower"]["name"],
        "seed": seed,
        "floors": [],
    }

    for floor in cfg["floors"]:
        nodes, edges = generate_floor(
            floor, cfg["node_types"], cfg["path_costs"], rng
        )
        cost_edges = [e for e in edges if e["cost"]]

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

    return result


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


def roll_node_type(node_types, rng, exclude=()):
    """按 weight 权重随机挑一个节点类型，可以排除掉几个 id。

    exclude 用来做「别连续出两行商店」这类软约束 —— 不是禁止，
    而是把候选池缩一下再掷。
    """
    pool = [t for t in node_types if t["id"] not in exclude]
    if not pool:
        pool = list(node_types)
    return weighted_choice(pool, rng)


# 每种节点每层至少要有几个（保证一层走下来不会「一个宝箱都没有」）
MIN_PER_FLOOR = {
    "rest": 2,      # 血量的主要来源，少于 2 个爬到一半会很难受
    "shop": 1,
    "event": 2,
    "treasure": 1,
}

# 每种节点每层最多几个（防止商店/宝箱泛滥）
MAX_PER_FLOOR = {
    "rest": 5,
    "shop": 4,
    "event": 6,
    "treasure": 4,
}

# 同一行最多几个特殊节点 —— 半屏都是商店/宝箱太怪，这里收一收
MAX_SPECIAL_PER_ROW = 2


def plan_floor_types(rows, width, node_types, rng):
    """
    给整层规划每格放什么节点。

    设计思路（第三次改，前两版都不行，这里记一下为什么）：

      第 1 版：「逐行独立掷骰子」+ 按 `r % 5 == 4` 指定特殊行。
        根因 bug：普通行池排除了 rest/shop/treasure 但漏了 event，
        权重 battle:elite:event = 45:15:12 抽 4 个位置，
        于是**每层都稳定出「3 个战斗 + 1 个事件」**；
        特殊行第一个位置定死特殊节点、剩下 3 格仍从池子里抽，
        变成「一行三家商店」。

      第 2 版：「先按权重算整层配额，再打散撒进各行」。
        修掉了上面那个 bug，但**引入了新的「太整齐」问题**：
          - 每层节点数几乎一样（实测 32/35/38），因为行数固定、
            `randint(2, width)` 的期望值恒定
          - 每种特殊节点数量被配额钉死，每层都是「休整 2、商店 2、事件 2~3」
          - 强制「每行最多 1 个特殊节点」，导致特殊节点像打格子一样
            均匀铺开，**看起来很假**
          - 剩下的格子全填 battle/elite，`normal_pool` 只有两个选项，
            battle 权重又占 3/4，所以一行里经常三四个 battle

      第 3 版（现在）：**每个格子独立掷骰子，只做轻量约束修正**。
        随机性交给概率自然生长，约束只在「明显不合理」时兜一下：

          1. 每行节点数：真的随机（1~width），不是 randint(2,width) ——
             允许出现只有 1 个节点的「独木桥」行，那是很好的节奏变化
          2. 每个格子：从**全部类型**（含特殊节点）按权重掷
          3. 软约束：同一行不出现两个同类型特殊节点；
             相邻两行不连续出同一种特殊节点
          4. 硬兜底：掷完之后检查每种特殊节点的总数，
             低于下限就补、高于上限就替换成普通战斗

        这样「每层几个休整点」会有自然波动（可能 2 个也可能 5 个），
        「特殊节点出现在哪几行」也不再均匀 —— 观感明显更随机。

      第 3 版补丁：单行最多 2 个特殊节点。
        上面「逐格掷骰子」有个副作用 —— 宽行（6 个格子）连中 3 个
        特殊节点的概率虽然不高，但 60 轮抽样里还是撞出 18 次（0.71%）。
        一行里半屏都是商店/宝箱，观感很怪，和「一队战斗里插一个休整点」
        的节奏预期不符。所以给每行加一条软上限：同一行特殊节点攒够
        MAX_SPECIAL_PER_ROW 个之后，后面格子只从「普通类型」里掷
        （battle / elite）。注意是软上限 —— 数量兜底阶段还能往上补。

    返回：{row_index: [类型 id, ...]}
    """
    type_by_id = {t["id"]: t for t in node_types}
    special_ids = tuple(k for k in MIN_PER_FLOOR)
    # 兜底用的普通类型：补/替换时用（精英不参与兜底，避免变相变难）
    filler = type_by_id.get("battle") or node_types[0]
    # 普通类型池（战斗 + 精英），一行特殊节点满了之后从这里掷
    normal_types = [t for t in node_types if t["id"] not in special_ids]
    if not normal_types:
        normal_types = list(node_types)

    # ---- 1. 每行几个节点：真的随机 ----
    # rows-1 是 Boss 行、0 是起点行，都固定 1 个，不参与
    mid_rows = list(range(1, rows - 1))
    row_counts = {}
    for r in mid_rows:
        # 25% 概率出「独木桥」（只有 1 个节点），
        # 剩下的在 2~width 之间随机 —— 这样整层的疏密有起伏
        if rng.random() < 0.25 and width >= 2:
            row_counts[r] = 1
        else:
            row_counts[r] = rng.randint(2, width)

    # 开局三行不能是独木桥！
    # 起点行只有 1 个节点，如果第二行也只有 1 个，那「第一回合选路」
    # 这个动作就不存在了 —— 单选不算选择，玩家一进游戏就少一拍。
    # 第二行必须 >= 2 个；第三行也留 >= 1 个余地，走起来才像爬塔。
    if rows >= 3:
        row_counts[1] = rng.randint(2, width)
    if rows >= 4 and row_counts[2] == 1:
        row_counts[2] = rng.randint(2, width)

    # ---- 2. 逐格掷骰子 ----
    plan = {r: [] for r in mid_rows}
    for r in mid_rows:
        prev_row = plan.get(r - 1, [])
        # 上一行出现过的特殊节点类型，这一行先避开
        # （只避开，不是禁止 —— 所以是「软」约束）
        avoid = {t for t in prev_row if t in special_ids}

        used_here = set()
        for _ in range(row_counts[r]):
            n_special_here = len(used_here)

            if n_special_here >= MAX_SPECIAL_PER_ROW:
                # 这行的特殊节点已经够多了，后面只掷普通类型
                nt = roll_node_type(normal_types, rng)
                plan[r].append(nt["id"])
                continue

            # 同一行先避开刚出过的特殊节点
            ex = tuple(avoid | used_here)
            nt = roll_node_type(node_types, rng, exclude=ex)

            # 兜一下：万一 exclude 把池子挤空，退化成普通类型
            if nt["id"] in special_ids and nt["id"] in used_here:
                nt = filler

            plan[r].append(nt["id"])
            if nt["id"] in special_ids:
                used_here.add(nt["id"])

    # ---- 3. 硬兜底：数量太离谱就修一下 ----
    def all_slots():
        """所有可以改的格子：(行, 下标)，跳过已经是特殊节点的。"""
        return [(r, i) for r in mid_rows for i in range(len(plan[r]))]

    def count_of(tid):
        return sum(row.count(tid) for row in plan.values())

    # 先把所有格子都记下来，兜底时要用
    slots = all_slots()

    def n_special_in(r):
        return sum(1 for x in plan[r] if x in special_ids)

    for tid in special_ids:
        n = count_of(tid)

        # 太少了 -> 找位置补上（优先补在普通战斗的格子上）
        #
        # 注意：这里的候选**必须按「行特殊节点最少」升序排**。
        # 一开始我写的是「一次挑够 need 个，然后一起改」，结果一行的
        # 计数在选中时还没更新，同一行被连补 2 个，冒出 3 个特殊节点
        # （正是第 2 步刚刚防住的那种扎堆）。所以改成**逐个补**，
        # 每补一个就重新排一次候选，让计数真实反映改动。
        lo = MIN_PER_FLOOR[tid]
        guard = 0
        while n < lo and guard < 200:
            guard += 1
            cand = [(r, i) for (r, i) in slots
                    if plan[r][i] == "battle"
                    and tid not in plan[r]
                    and n_special_in(r) < MAX_SPECIAL_PER_ROW]
            if not cand:
                # 实在找不到「不扎堆」的位置了（楼层很小才会这样），
                # 放宽到「这行还没出过这种节点」，宁可稍微挤一点也别缺项
                cand = [(r, i) for (r, i) in slots
                        if plan[r][i] == "battle" and tid not in plan[r]]
            if not cand:
                break
            # 挑特殊节点最少的行；同分随机，避免永远补在左边
            rng.shuffle(cand)
            r, i = min(cand, key=lambda ri: n_special_in(ri[0]))
            plan[r][i] = tid
            n += 1

        # 太多了 -> 把多出来的换成普通战斗
        hi = MAX_PER_FLOOR[tid]
        if n > hi:
            extra = [(r, i) for (r, i) in slots if plan[r][i] == tid]
            # 尽量挑「同一行特殊节点最多」的那些换掉，保留分散的
            extra.sort(key=lambda ri: -n_special_in(ri[0]))
            for (r, i) in extra[:n - hi]:
                plan[r][i] = "battle"

    # ---- 4. 收尾：确保每行至少 1 个节点 ----
    # （理论上不会空，但 rows 很小时 row_counts 可能给 0）
    for r in mid_rows:
        if not plan[r]:
            plan[r] = [filler["id"]]

    return plan


def _node_type_fields(ntype):
    """把 yaml 里的类型定义转成节点要写的几个字段。

    node dict 里 type / type_name / icon / desc 这四个是绑在一起的，
    换类型时必须**一起换**，否则地图上会画着「=」休整点图标、
    点进去却是战斗 —— 之前踩过这个坑。
    """
    return {
        "type": ntype["id"],
        "type_name": ntype["name"],
        "icon": ntype["icon"],
        "desc": ntype["desc"],
    }


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
        # 第一行和最后一行（Boss 行）固定只放 1 个节点；
        # 中间行的数量已经在 plan_floor_types 里随机定了，这里直接用，
        # 保证「类型规划」和「实际放几个」是同一份数据（不会对不上）
        if r == 0:
            count = 1
        elif r == rows - 1:
            count = 1
        else:
            count = len(type_plan.get(r) or []) or rng.randint(1, width)

        current = []
        # 横向布局：均匀铺开
        for c in range(count):
            # 位置：在 0~1 之间均匀分布（后面画图用）
            x = (c + 1) / (count + 1)

            # 决定节点类型
            if r == 0:
                # 起点：允许普通战斗或事件（事件没有战斗压力，
                # 开局先读一段世界观也不错），但**不用精英** ——
                # 一上来就遇精英太难。随机一下免得每局都一样。
                if rng.random() < 0.25:
                    tid = "event"
                else:
                    tid = "battle"
                ntype = type_by_id.get(tid) or type_by_id.get("battle") or {
                    "id": "battle", "name": "普通战斗", "icon": "×",
                    "desc": "常规敌人，掉落卡牌"}
            elif r == rows - 1:
                # boss 不在 node_types 里，是层主专属，这里兜一个默认
                ntype = type_by_id.get("boss") or {
                    "id": "boss", "name": "层主", "icon": "★",
                    "desc": "本层最终战"}
            else:
                tid = type_plan[r][c] if c < len(type_plan[r]) else "battle"
                ntype = type_by_id.get(tid) or {
                    "id": "battle", "name": "普通战斗", "icon": "×",
                    "desc": "常规敌人，掉落卡牌"}

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
            # 用位置比例决定连谁，保证线不交叉太多
            ux = nodes[uid]["x"]
            candidates = sorted(lower, key=lambda nid: abs(nodes[nid]["x"] - ux))

            # 起始行（只有一个节点）必须连到下一行所有节点，
            # 否则开局只有一条路，玩家没有选择余地。
            if r == 0:
                link_count = len(candidates)
            else:
                # 中间行：连几个也做随机，让「岔路多少」有起伏 ——
                # 全连通（每个节点都连满）看起来很规整、缺随机感；
                # 所以大部分情况下连 1~2 个，偶尔连 3 个（宽路口）。
                roll = rng.random()
                if roll < 0.40:
                    link_count = 1
                elif roll < 0.85:
                    link_count = 2
                else:
                    link_count = 3
                link_count = min(len(candidates), link_count)

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

    # ---- 死路检查：每个非 Boss 节点都必须有出边 ----
    # 上面按「最近的几个」连边，理论上不会漏；但加了随机连边数量之后
    # （上面 link_count 有 1 的路口），万一某个节点没连出去，
    # 玩家走到那儿就卡死了。这里兜一下：给没有出边的节点补一条到最近节点。
    has_out = {e["from"] for e in edges}
    for r in range(rows - 1):
        for uid in row_nodes[r]:
            if uid in has_out:
                continue
            ux = nodes[uid]["x"]
            near = min(row_nodes[r + 1],
                       key=lambda nid: abs(nodes[nid]["x"] - ux))
            edges.append({
                "id": edge_id, "from": uid, "to": near, "cost": None,
            })
            edge_id += 1
            has_out.add(uid)

    # ---- 开局保证：起点往上至少有一条舒服的路、一条划算的路 ----
    # 问题背景：起点行只有一个节点，它连到第二行时是「按 x 位置就近
    # 连 3 条」。如果第二行只有 2 个节点、又恰好都是战斗，那开局就是
    # 「两条路都打架」，没有任何抉择余地 —— 一进游戏就觉得地图很闷。
    # 这是「第一回合没得选」的根因，比"随机性不够"更致命。
    #
    # 做法：把第二行里最无聊的格子换掉，一个换休整点、一个换商店。
    # 注意：**不排除精英**。精英也能当"有风险的路"，
    # 这样开局就是「稳一手（休整）or 拼一把（精英）」，很像杀戮尖塔。
    if rows >= 3 and len(row_nodes[1]) >= 2:
        # 特殊类型 = MIN_PER_FLOOR 里列的那几个
        SPECIALS_SET = frozenset(MIN_PER_FLOOR)

        # 关键：这条开局保证**不能把这一行搞出扎堆**。
        # 踩过的坑：一开始只数「战斗/精英」够不够 2 个，
        # 结果第二行是 [事件, 宝箱, 战斗] 时也照样换 ——
        # 换完变成 [事件, 宝箱, 休整, 商店]，整层 3.45% 的行冒出
        # 3 个特殊节点，抽样脚本直接报警。
        # 所以这里必须按**整行宽度**算预算，而且要按当前实际
        # 特殊节点数动态扣减，不是拍一个固定值。
        budget = MAX_SPECIAL_PER_ROW - sum(
            1 for nid in row_nodes[1]
            if nodes[nid]["type"] in SPECIALS_SET)

        # 只从「战斗/精英」里挑，别的类型保持原样
        fightable = [nid for nid in row_nodes[1]
                     if nodes[nid]["type"] in ("battle", "elite")]
        # 随机洗一下，免得每次都是最左边那个被换成休整点
        rng.shuffle(fightable)
        # 战斗比精英更"无聊"，优先换战斗
        fightable.sort(key=lambda nid: 0 if nodes[nid]["type"] == "battle" else 1)

        # 只从「这一层真的配了」的类型里挑，别凭空造出没配的东西
        wants = [t for t in ("rest", "shop", "treasure", "event")
                 if t in type_by_id][:max(0, budget)]

        for nid, tid in zip(fightable, wants):
            nodes[nid].update(_node_type_fields(type_by_id[tid]))

    return nodes, edges


def build(seed=None):
    """命令行主流程：生成三层地图 -> 写出 out/map.json。

    生成逻辑全在 build_in_memory() 里，这里只负责打印 + 落盘，
    免得两处各写一遍、改一处忘了另一处。

    seed=None 时用系统随机源（每次都不一样）；
    传具体数字则结果可复现。
    """
    result = build_in_memory(seed=seed)

    # 输出目录要能写。打包成 exe 后 _RES 指向临时解包目录（退出即删），
    # 所以这里改用 game_env 的「可写目录」，落到 exe 同级的 map_tools/out/。
    try:
        out_dir = _E.user_data_path("map_tools", "out")
    except Exception:                   # noqa: BLE001
        out_dir = OUT
    out_dir.mkdir(parents=True, exist_ok=True)

    for fl in result["floors"]:
        s = fl["stats"]
        print(f"  第 {fl['id']} 层：{fl['name']} ...")
        print(f"    节点 {s['node_count']} 个｜连边 {s['edge_count']} 条"
              f"｜其中带代价 {s['cost_edge_count']} 条")
        # 把各类型数量也打出来，方便一眼看出分布是否合理
        dist = "  ".join("%s %d" % (k, v)
                         for k, v in sorted(s["by_type"].items()))
        print(f"    分布：{dist}")

    # ---- 写出 JSON（给程序用）----
    json_path = out_dir / "map.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n已生成：{json_path}")
    print(f"随机种子：{result['seed']}")

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
