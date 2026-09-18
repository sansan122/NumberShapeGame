"""
《数与形》地图场景（pygame 版）
================================================
参考《杀戮尖塔》的爬塔地图：起点在底部，往上爬，镜头跟随。

操作：
  - 鼠标左键点击节点
  - 鼠标滚轮 / 上下方向键 滚动视角
  - 点左侧「遗物 N 件」看遗物图鉴（ESC / 点面板外关掉）
  - R（或点左侧「查找遗物」）在地图上把出遗物的节点找出来
  - ESC 返回

规则：
  - 只有「下一行」的节点是真正可移动的（高亮显示）
  - 点击更远的节点 = 设为目标，高亮出从当前位置到它的路径
  - 走带「路线代价」的边会立即结算代价

这个文件可以单独运行，也会被后面的主程序 import。
"""

import json
import math
import sys
from pathlib import Path

import pygame

import char_art
import game_env as E
import player as P      # 路线代价要发遗物，用 P.roll_unowned_relic
import sfx

# 打包成 exe 后 __file__ 指向临时解包目录，所以一律用 game_env 算路径
ROOT = E.resource_path()

# 屏幕尺寸（必须在类定义前，类方法里会用到）
WIDTH, HEIGHT = 1280, 720

# map.json 可能在两个位置：本目录的 out/，或 map_tools/out/
MAP_CANDIDATES = [
    ROOT / "out" / "map.json",
    ROOT / "map_tools" / "out" / "map.json",
]

# ==================== 配色（浅色主题，与战斗界面统一）====================
BG          = (246, 245, 240)
PANEL       = (255, 255, 255)
PANEL_LINE  = (215, 213, 205)
TEXT        = (44, 44, 42)
TEXT_MUTE   = (110, 108, 102)
TEXT_FAINT  = (170, 168, 160)
ACCENT      = (24, 95, 165)
GOLD        = (196, 148, 30)
RED         = (200, 70, 70)
GREEN       = (59, 109, 17)
SHADOW      = (228, 226, 218)

# 节点类型 -> 颜色（描边）
TYPE_COLOR = {
    "battle":   (200, 70, 70),
    "elite":    (150, 60, 150),
    "rest":     (59, 109, 17),
    "shop":     (186, 117, 23),
    "event":    (24, 95, 165),
    "treasure": (196, 148, 30),
    "boss":     (120, 30, 30),
}

# 遗物紫（与 node_scenes.PURPLE 同色）：角标、查找高亮、图鉴面板都用它，
# 玩家看到紫色就知道和遗物有关。
RELIC_COL  = (83, 74, 183)
RELIC_SOFT = (238, 236, 252)

#: 哪些节点会出遗物 —— 用于 ① 节点角标 ②「查找遗物」高亮 ③ 悬停提示。
#: 值 = (短标签, 说明)。
#:
#: ⚠️ 这张表是**给人看的**，真正发遗物的另有其处：
#:     宝箱 -> node_scenes.TreasurePanel（必得 1 件；集齐后折现 40 金币）
#:     精英 -> battle_scene.ENEMY_KINDS["elite"]["relic"] = 1
#:     层主 -> battle_scene.ENEMY_KINDS["boss"]["relic"] = 1
#:     商店 -> node_scenes.ShopPanel 货架上有一格遗物（要花金币）
#:     事件 -> node_scenes.EVENTS「断裂的等式 · 补上缺口」（三选一里的一条）
#:   所以它们会漂移：改了 ENEMY_KINDS 或 EVENTS 却忘了改这里，地图就会
#:   指着普通战斗说「这里有遗物」。tmp/verify_relic_find.py 里有一条断言
#:   专门**去真的读那几个源头**再和这张表对账，对不上就红 ——
#:   地图上说错「哪里有遗物」，比干脆不标更糟。
RELIC_SOURCE = {
    "treasure": ("宝箱", "必得 1 件"),
    "elite":    ("精英", "战后 1 件"),
    "boss":     ("层主", "战后 1 件"),
    "shop":     ("商店", "柜上有 1 件"),
    "event":    ("事件", "三选一里有 1 条"),
}


def relic_source_of(ntype):
    """这个节点类型会不会出遗物 -> (短标签, 说明)；不会出就 None。"""
    return RELIC_SOURCE.get(ntype)


# 世界坐标布局参数
ROW_H = 128          # 行间距（世界坐标）
NODE_R = 26          # 节点半径
COL_W = 190          # 列间距

# 左侧状态面板
PANEL_X, PANEL_Y, PANEL_W = 20, 76, 210


def player_panel_layout(has_save=False, hide_next=False):
    """左侧状态面板的**唯一**布局来源（画和点击共用这一份坐标）。

    为什么要抽成一个函数：这块面板从前被画了两遍 —— 地图自己画一版
    （draw_side），main.py 又画一版（draw_player_panel）盖在上面，
    两版的行数还不一样（一个多「未完待证」，一个多「金币 / 牌库」）。
    改一处没效果是常事（README 踩坑里记着）。

    现在合并成一版，但**点击命中的矩形必须和画出来的完全一致** ——
    面板上要放「遗物 / 查找」两个按钮，如果按钮位置靠 draw 里那一串
    `y += 24` 推出来，就会变成「按下去的地方不一定是画出来的地方」。
    所以坐标在这里一次算清，draw 和 handle 都来取。
    """
    x, y0 = PANEL_X, PANEL_Y
    y = y0 + 12

    lay = {"y_who": y}
    y += 24
    lay["bar"] = pygame.Rect(x + 14, y, PANEL_W - 28, 14)
    y += 20
    lay["y_hp"] = y
    y += 24
    lay["y_gold"] = y
    y += 24
    # 「遗物 N 件」本身就是一个按钮（点开图鉴）
    lay["btn_relics"] = pygame.Rect(x + 12, y - 4, PANEL_W - 24, 27)
    y += 28
    lay["y_deck"] = y
    y += 24
    lay["y_hide"] = y if hide_next else None
    y += 22 if hide_next else 0
    lay["y_save"] = y if has_save else None
    y += 22 if has_save else 0
    y += 10
    # 「查找遗物」开关（按 R 同效）
    lay["btn_find"] = pygame.Rect(x + 12, y, PANEL_W - 24, 34)
    y += 34
    lay["box"] = pygame.Rect(x, y0, PANEL_W, y + 12 - y0)
    return lay



def load_map(path=None):
    """读取 map.json。会自动在几个常见位置里找。"""
    if path:
        candidates = [Path(path)]
    else:
        candidates = MAP_CANDIDATES

    for p in candidates:
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f)

    raise FileNotFoundError(
        "找不到地图数据，找过这些位置：\n  %s\n"
        "请先运行 map_tools/2_gen_map.bat 生成地图。"
        % "\n  ".join(str(c) for c in candidates)
    )


class MapScene:
    """一整座塔的地图场景（含三层切换）。"""

    def __init__(self, data, floor_index=0, font_path=None):
        self.data = data
        self.floor_index = floor_index

        # 字体：交给 game_env 做兜底（自带确定能用的降级链），
        # font_path 参数保留是为了兼容老调用方，一般不用传。
        self.F_BIG = E.load_font(26)
        self.F_MID = E.load_font(19)
        self.F_SML = E.load_font(15)
        self.F_TINY = E.load_font(13)
        self.F_ICON = E.load_font(22)

        # 玩家状态（如果外部注入了共享的 Player 对象，就用它的数据）
        self.player = None          # 由 main.Game 注入
        self._max_hp = 80
        self._hp = 80
        self._gold = 50
        self._relics = []
        self.log = []
        self.hide_next = False      # 「未完待证」效果
        self.enemy_hp_mult = 1.0    # 「负债增量」效果
        # 左侧面板顶部那行「有存档」提示由 main 每帧塞进来（它才知道存档文件
        # 在不在）；地图单独跑的时候恒为 False。
        self.has_save_hint = False
        # 遗物图鉴覆盖层：None = 关着，否则是一个 RelicPanel
        self.relic_panel = None
        # 「查找遗物」模式：开了之后不出遗物的节点压暗、出遗物的加环
        self.find_relic = False

        self.load_floor(floor_index)

    # ==================== 玩家状态代理 ====================
    # 如果 main.Game 注入了共享的 Player，就读写它；否则退回本地字段。
    # 这样地图单独运行时也能跑（2_run_map.bat）。
    @property
    def max_hp(self):
        return self.player.max_hp if self.player else self._max_hp

    @max_hp.setter
    def max_hp(self, v):
        if self.player:
            self.player.max_hp = v
        else:
            self._max_hp = v

    @property
    def hp(self):
        return self.player.hp if self.player else self._hp

    @hp.setter
    def hp(self, v):
        if self.player:
            self.player.hp = v
        else:
            self._hp = v

    @property
    def gold(self):
        return self.player.gold if self.player else self._gold

    @gold.setter
    def gold(self, v):
        if self.player:
            self.player.gold = v
        else:
            self._gold = v

    @property
    def relics(self):
        return self.player.relics if self.player else self._relics

    def deck_count(self):
        """牌库张数。地图单独跑（没有 Player）时显示 0。"""
        return len(self.player.deck) if self.player else 0

    # ==================== 层与节点 ====================
    def load_floor(self, idx):
        """载入第 idx 层，把节点转成世界坐标。"""
        self.floor_index = idx
        fl = self.data["floors"][idx]
        self.floor = fl
        # 「负债增量」罚的是「本层所有敌人血量 +15%」，所以换层必须归位。
        # 以前这里没有这一行，代价一旦选过就**永久**跟着玩家爬到塔顶 ——
        # 而它的收益（1 件遗物）只兑现一次，等于越往后越纯亏。
        # 读档时 main._init_from_save 会用存档里的值覆盖回来，顺序是对的。
        self.enemy_hp_mult = 1.0
        self.theme = tuple(
            int(fl["theme_color"][i:i + 2], 16) for i in (1, 3, 5)
        )

        # 建立节点索引
        self.nodes = {n["id"]: dict(n) for n in fl["nodes"]}

        # 计算每行的最大宽度，用于横向居中
        rows = {}
        for n in self.nodes.values():
            rows.setdefault(n["row"], []).append(n)
        self.row_count = max(rows) + 1
        self.row_nodes = [sorted(rows.get(r, []), key=lambda n: n["x"])
                          for r in range(self.row_count)]

        # 世界坐标：row 0 在最下面（起点），越往上 row 越大
        # world_y 越小越靠上
        for r, ns in enumerate(self.row_nodes):
            for n in ns:
                n["wx"] = int((n["x"] - 0.5) * COL_W * (max(2, len(ns))))
                # row 0 应该在屏幕底部 -> y 随 row 增大而减小
                n["wy"] = -(r * ROW_H)

        # 邻接表（向上）
        self.out_edges = {}
        for e in fl["edges"]:
            self.out_edges.setdefault(e["from"], []).append(e)

        # 玩家起点：第 0 行（最底部）唯一的节点
        self.current = self.row_nodes[0][0]["id"] if self.row_nodes[0] else None

        # 已访问节点
        self.visited = {self.current} if self.current is not None else set()
        self.target = None          # 被点中的远期节点
        self.path_hint = []         # 高亮的路径（边列表）

        # 相机：让当前节点位于屏幕下部 1/4 处
        self.cam_y = 0.0
        self.cam_target = 0.0
        self.log = []
        self.push_log("进入 %s" % fl["name"])

    def push_log(self, text):
        self.log.insert(0, text)
        self.log = self.log[:8]

    # ==================== 可达性 ====================
    def reachable(self):
        """从当前位置可以直达的节点 id 集合。"""
        if self.current is None:
            return set()
        return {e["to"] for e in self.out_edges.get(self.current, [])}

    def edge_to(self, tid):
        """找 current -> tid 的边，没有则 None。"""
        for e in self.out_edges.get(self.current, []):
            if e["to"] == tid:
                return e
        return None

    def find_path(self, dst, max_depth=40):
        """
        从 current 到 dst 的路径（BFS，返回边的列表）。
        用于「点击远期节点 -> 高亮路径」。
        """
        if self.current is None or dst is None:
            return []
        if dst == self.current:
            return []

        # BFS
        import collections
        q = collections.deque([(self.current, [])])
        seen = {self.current}
        while q:
            cur, path = q.popleft()
            if len(path) >= max_depth:
                continue
            for e in self.out_edges.get(cur, []):
                nid = e["to"]
                if nid == dst:
                    return path + [e]
                if nid not in seen:
                    seen.add(nid)
                    q.append((nid, path + [e]))
        return []

    def can_move_to(self, tid):
        return tid in self.reachable()

    # ==================== 移动 ====================
    def move_to(self, tid):
        """
        移动到 tid（只允许下一行节点）。
        会结算路线代价。
        """
        e = self.edge_to(tid)
        if e is None:
            return False

        # ---- 结算路线代价 ----
        if e.get("cost"):
            self.apply_cost(e["cost"])

        self.current = tid
        self.visited.add(tid)
        self.target = None
        self.path_hint = []

        n = self.nodes[tid]
        self.push_log("到达 %s" % n["type_name"])

        # 镜头跟随
        self.cam_target = self.camera_for(self.nodes[tid])

        # 到达最后一行 = 本层通过
        if n["row"] == self.row_count - 1:
            self.push_log("已抵达 %s，本层通过！" % self.floor["boss"])
        return True

    def apply_cost(self, cost):
        """结算一个路线代价。

        代价都是「一罚一奖」成对设计的，两边**都要**落地。
        以前 liability 只加了敌人血量、open_interval 只锁了精英，
        承诺的那半句（遗物 / 战后额外强化）一句都没实现，
        玩家等于白亏 —— 别再只写罚的那一半。
        """
        cid = cost["id"]
        self.push_log("代价「%s」：%s" % (cost["name"], cost["desc"]))
        if cid == "approximate":
            self.max_hp = max(1, self.max_hp - 8)
            self.hp = min(self.hp, self.max_hp)
        elif cid == "liability":
            self.enemy_hp_mult *= 1.15
            self.push_log("本层敌人生命 +15%")
            self._grant_cost_reward()
        elif cid == "unproven":
            self.hide_next = True
            self.push_log("下一层节点类型不可见")
        elif cid == "open_interval":
            self.force_elite_next = True
            self.push_log("下一个节点必为精英")
            # 「战后额外获得 1 次强化」先挂在玩家身上，
            # 打赢下一场由战利品面板（main.open_spoils）兑现
            if self.player:
                self.player.pending_upgrades += 1
                self.push_log("战后额外强化 1 次")

    def _grant_cost_reward(self):
        """「负债增量」奖励的那一半：获得 1 件随机遗物（集齐了折现金币）。"""
        if not self.player:
            return
        got = P.roll_unowned_relic(self.player)
        if got:
            note = self.player.add_relic(got[0])
            self.push_log("获得遗物「%s」：%s" % (got[0], got[1]))
            if note:
                self.push_log(note)
        else:
            self.player.gold += 40
            self.push_log("遗物已集齐，折现 +40 金币")

    # ==================== 相机 ====================
    def camera_for(self, node, anchor=0.62):
        """
        让节点落在屏幕某个高度时，相机应在哪。

        先把这条式子推对（原来的注释写反了，别再照着它改符号）：

            画面 y = HEIGHT/2 + (wy - cam_y)
            代入 cam_y = wy + (anchor - 0.5) * HEIGHT
            => 画面 y = HEIGHT * (1 - anchor)

        所以 anchor=0.62 时，当前节点落在 y ≈ 274，也就是屏幕**上**三分之一处，
        它上方自然留出 274px 给「前路」，正好能看到 2~3 行。
        换句话说 anchor 越大 -> 节点越靠上 -> 上方空间越少（不是越多）。

        为什么不让节点靠下？因为在起点时「身后」没有行可显示，
        节点放得越低、下半屏越空。现在这个位置是四行以内构图的最优解：
        顶端看得到 4 行，起点看得到 2~3 行（见 clamp_camera 的实测数字）。
        """
        return node["wy"] + (anchor - 0.5) * HEIGHT

    def update(self, dt):
        # 相机平滑
        self.cam_y += (self.cam_target - self.cam_y) * min(1.0, dt * 8.0)

    def scroll(self, dy):
        self.cam_target += dy
        self.cam_y += dy

    # ------------------------------------------------------------------
    # 滚动的「正方向」约定 —— 别再在事件层直接调 scroll() 了
    # ------------------------------------------------------------------
    # 记清楚这条链条，就不会再写反：
    #     画面 y = HEIGHT/2 + (世界 y - cam_y)
    # 所以 cam_y **变大** -> 画面上的内容整体**上移** -> 我们看到的是塔的**下方**。
    # 也就是说：cam_y 变大 = 视野往下走。
    #
    # 「往上看」（滚轮上滚 / ↑）和 cam_y 的正方向是**相反**的。
    # 这里用两个名字点明意图，调用方就不用再自己推符号了。
    def scroll_up(self, amount):
        """视野往塔的上方走（能看到更高的楼层）。"""
        self.scroll(-amount)

    def scroll_down(self, amount):
        """视野往塔的下方走（能看到更低的楼层）。"""
        self.scroll(amount)

    def clamp_camera(self):
        """限制相机范围，别滚出地图。

        上下界直接复用 camera_for —— 那是「走到某一行时镜头会停的位置」。
        钳在这里，等于说：无论玩家怎么滚，镜头落点都和正常行走时的构图一致，
        不会出现「滚到顶却只看到一行、大半个屏幕是空的」这种死角。

        （旧写法是 top - HEIGHT*0.5 / bot + HEIGHT*0.30，符号推反了：
          实测滚到顶时 12 行里只剩 1 行在屏内，而且那行还贴在屏幕最下边。
          改成 camera_for 之后，两端各能看到 3~4 行。）
        """
        if not self.row_nodes or not self.row_nodes[-1]:
            return
        lo = self.camera_for(self.row_nodes[-1][0])   # 顶层构图（wy 最小）
        hi = self.camera_for(self.row_nodes[0][0])    # 底层构图（wy 最大）
        self.cam_target = max(lo, min(hi, self.cam_target))
        self.cam_y = max(lo, min(hi, self.cam_y))

    # ==================== 坐标换算 ====================
    def world_to_screen(self, wx, wy):
        return int(WIDTH / 2 + wx), int(HEIGHT / 2 + (wy - self.cam_y))

    def screen_to_world(self, sx, sy):
        return sx - WIDTH / 2, sy - HEIGHT / 2 + self.cam_y

    # ==================== 遗物：查看 / 查找 ====================
    def panel_layout(self):
        """左侧状态面板的当前布局（画和点击都走这里）。"""
        return player_panel_layout(self.has_save_hint, self.hide_next)

    def node_is_hidden(self, nid, n, reach=None):
        """这个节点现在是不是「看不清」。

        「未完待证」会让下一行的类型变成问号，所以：
          · 角标不能标（标了等于把谜底漏了）
          · 悬停提示也不能照实说类型和描述
        标记和提示必须**用同一条判据** —— 否则会出现「节点画着问号、
        悬停却告诉你那是宝箱」，白送的剧透。
        """
        if not self.hide_next:
            return False
        if reach is None:
            reach = self.reachable()
        return nid in reach and n["type"] != "boss"

    def relic_nodes(self):
        """本层所有「可能出遗物」的节点（看不清的那些不算）。"""
        return [n for nid, n in self.nodes.items()
                if relic_source_of(n["type"]) and not self.node_is_hidden(nid, n)]

    def relic_summary(self):
        """本层遗物来源的分类统计：[("宝箱", 1), ("精英", 2), ...]。

        顺序跟着 RELIC_SOURCE 走（dict 保持插入序），每次刷新都一样 ——
        不然横幅上的「宝箱 2 · 精英 1」会自己跳来跳去。
        """
        cnt = {}
        for n in self.relic_nodes():
            cnt[n["type"]] = cnt.get(n["type"], 0) + 1
        return [(RELIC_SOURCE[t][0], cnt[t]) for t in RELIC_SOURCE if t in cnt]

    def toggle_find_relic(self):
        """开 / 关「查找遗物」。返回切换后的状态。"""
        self.find_relic = not self.find_relic
        sfx.play("ui_click" if self.find_relic else "ui_back", gap_ms=0)
        if self.find_relic:
            parts = ["%s %d" % (lbl, n) for lbl, n in self.relic_summary()]
            self.push_log("查找遗物：本层 %d 处（%s）"
                          % (sum(n for _, n in self.relic_summary()),
                             " · ".join(parts) if parts else "无"))
        return self.find_relic

    def open_relics(self):
        """打开遗物图鉴。"""
        self.relic_panel = RelicPanel(self.relics)
        sfx.play("ui_click", gap_ms=0)
        return self.relic_panel

    def close_relics(self):
        """关掉遗物图鉴。返回它原本是不是开着的（好决定要不要响一声）。"""
        if self.relic_panel is None:
            return False
        self.relic_panel = None
        sfx.play("ui_back", gap_ms=0)
        return True

    def handle_side_click(self, mouse):
        """左侧面板上的点击。返回 True = 这次点击被面板吃掉了。

        ⚠️ 必须在**判定节点之前**问这一句：面板和地图叠在同一块屏幕上，
        少了这一层，「点遗物按钮」会顺手把按钮底下的节点也点进去 ——
        玩家想查个遗物，结果人往旁边走了一格。
        """
        lay = self.panel_layout()
        if lay["btn_relics"].collidepoint(mouse):
            self.open_relics()
            return True
        if lay["btn_find"].collidepoint(mouse):
            self.toggle_find_relic()
            return True
        return False

    def handle_relic_panel(self, event, mouse):
        """把事件转给遗物图鉴。返回 True = 面板还开着。

        面板开着的时候它**独占**输入：不然点「关闭」会连带把地图也点一下。
        """
        if self.relic_panel is None:
            return False
        if self.relic_panel.handle(event, mouse) == "close":
            self.close_relics()
            return False
        return True

    def draw_relic_overlay(self, screen, mouse):
        """画遗物图鉴（盖在地图上，含左侧面板之上）。"""
        if self.relic_panel is not None:
            self.relic_panel.draw(screen, mouse)

    # ==================== 绘制 ====================
    def draw(self, screen, mouse, t_ms):
        screen.fill(BG)
        self.clamp_camera()

        reach = self.reachable()
        cx, cy = self.world_to_screen(0, 0)

        # ---------- 1. 先画边 ----------
        for e in self.floor["edges"]:
            a, b = self.nodes[e["from"]], self.nodes[e["to"]]
            ax, ay = self.world_to_screen(a["wx"], a["wy"])
            bx, by = self.world_to_screen(b["wx"], b["wy"])

            on_path = any(pe["id"] == e["id"] for pe in self.path_hint)
            from_cur = (e["from"] == self.current)

            # 只画屏幕附近的边，省性能
            if max(ay, by) < -80 or min(ay, by) > HEIGHT + 80:
                continue

            if on_path:
                col, w = GOLD, 4
            elif from_cur and e["to"] in reach:
                col, w = ACCENT, 3
            elif e["from"] in self.visited:
                col, w = (150, 165, 185), 2
            else:
                col, w = (222, 220, 212), 2

            pygame.draw.line(screen, col, (ax, ay), (bx, by), w)

            # 带代价的边：画一个标记
            if e.get("cost"):
                mx, my = (ax + bx) // 2, (ay + by) // 2
                r = 11
                c_col = GOLD if on_path else (214, 176, 96)
                pygame.draw.circle(screen, PANEL, (mx, my), r)
                pygame.draw.circle(screen, c_col, (mx, my), r, 2)
                lb = self.F_TINY.render(e["cost"]["name"][:1], True, c_col)
                screen.blit(lb, lb.get_rect(center=(mx, my)))

        # ---------- 2. 再画节点 ----------
        for nid, n in self.nodes.items():
            sx, sy = self.world_to_screen(n["wx"], n["wy"])
            if sy < -60 or sy > HEIGHT + 60:
                continue

            is_cur = (nid == self.current)
            is_reach = nid in reach
            is_visited = nid in self.visited
            is_target = (nid == self.target)
            hovered = (sx - mouse[0]) ** 2 + (sy - mouse[1]) ** 2 <= (NODE_R + 4) ** 2

            color = TYPE_COLOR.get(n["type"], TEXT_MUTE)

            # 未知节点（未完待证）
            hidden = self.node_is_hidden(nid, n, reach)

            # 这个节点会不会出遗物（看不清的节点不算：标出来等于剧透）
            src = None if hidden else relic_source_of(n["type"])

            # 「查找遗物」模式：不出遗物的节点压暗，让来源节点跳出来。
            # 只是换颜色、不盖半透明纱 —— 盖纱会把「可到达」的呼吸高亮
            # 一起糊掉，而「这一行我能点哪儿」比找遗物更要紧。
            # 站着的这个节点永远保持原色，不然玩家会一时找不到自己。
            dim = self.find_relic and src is None and not is_cur
            if dim:
                color = (210, 208, 202)

            # 阴影
            pygame.draw.circle(screen, SHADOW, (sx, sy + 4), NODE_R)

            # 底色
            if is_cur:
                fill = ACCENT
            elif is_target:
                fill = (255, 240, 200)
            elif is_visited:
                fill = (238, 240, 236)
            elif is_reach:
                fill = (255, 255, 255)
            else:
                fill = (244, 243, 238)
            if dim:
                fill = (250, 249, 245)

            pygame.draw.circle(screen, fill, (sx, sy), NODE_R)

            # 描边
            if is_cur:
                pygame.draw.circle(screen, GOLD, (sx, sy), NODE_R + 4, 3)
                pygame.draw.circle(screen, ACCENT, (sx, sy), NODE_R, 3)
            elif is_target:
                pygame.draw.circle(screen, GOLD, (sx, sy), NODE_R, 4)
            elif is_reach:
                # 可到达的呼吸高亮
                pulse = 2 + int(1.5 * (1 + math.sin(t_ms / 300.0)))
                pygame.draw.circle(screen, ACCENT, (sx, sy), NODE_R + pulse, 2)
                pygame.draw.circle(screen, color, (sx, sy), NODE_R, 3)
            elif hovered and is_visited:
                pygame.draw.circle(screen, color, (sx, sy), NODE_R, 3)
            else:
                pygame.draw.circle(screen, (214, 212, 205), (sx, sy), NODE_R, 2)

            # 图标
            if hidden:
                icon, icol = "?", TEXT_MUTE
            else:
                icon, icol = n["icon"], (255, 255, 255) if is_cur else color
            it = self.F_ICON.render(icon, True, icol)
            screen.blit(it, it.get_rect(center=(sx, sy)))

            # 遗物来源的标记：平时一个小角标；查找模式下加环 + 写出处
            if src:
                if self.find_relic:
                    pygame.draw.circle(screen, RELIC_COL, (sx, sy), NODE_R + 7, 3)
                    # 标签挂在节点**下方**：上方是当前位置的立绘小人，
                    # 挂上去正好糊在人家脸上。
                    self._draw_relic_tag(screen, sx, sy + NODE_R + 18, src)
                else:
                    self._draw_relic_badge(screen, sx, sy)

            # 当前位置加个小人标记：有立绘素材就让像素小人站在节点上
            # （待机动画），没素材保持原来的金色小圆点
            if is_cur:
                cid = None
                if self.player is not None:
                    ch = getattr(self.player, "char", None)
                    if ch:
                        cid = ch.get("id")
                drawn = False
                if cid:
                    drawn = char_art.draw_idle(
                        screen, cid, (sx, sy - NODE_R - 2), 42, t_ms)
                if not drawn:
                    pygame.draw.circle(screen, GOLD, (sx, sy - NODE_R - 14), 6)

        # ---------- 3. 顶部信息栏 ----------
        self.draw_topbar(screen)

        # ---------- 4. 左侧状态 / 底部提示 ----------
        self.draw_side(screen)

        # ---------- 5. 查找遗物的横幅（盖在顶栏下缘）----------
        if self.find_relic:
            self.draw_find_banner(screen)

        # ---------- 6. 悬停提示 ----------
        self.draw_tooltip(screen, mouse)

    def _draw_relic_badge(self, screen, sx, sy):
        """节点右上角的紫色小角标 —— 意思是「这里能出遗物」。

        画在斜上方而不是正上方：正上方要留给当前位置的立绘小人。
        """
        bx = sx + int(NODE_R * 0.74)
        by = sy - int(NODE_R * 0.74)
        pygame.draw.circle(screen, PANEL, (bx, by), 11)
        pygame.draw.circle(screen, RELIC_COL, (bx, by), 10)
        t = self.F_TINY.render("遗", True, (255, 255, 255))
        screen.blit(t, t.get_rect(center=(bx, by + 1)))

    def _draw_relic_tag(self, screen, cx, cy, src):
        """查找模式下挂在来源节点下方的标签：遗物 · 宝箱 必得 1 件。"""
        t = self.F_TINY.render("遗物 · %s %s" % src, True, (255, 255, 255))
        box = pygame.Rect(0, 0, t.get_width() + 16, t.get_height() + 8)
        box.center = (cx, cy)
        pygame.draw.rect(screen, RELIC_COL, box, border_radius=8)
        screen.blit(t, t.get_rect(center=box.center))

    def draw_find_banner(self, screen):
        """查找遗物模式下的横幅：本层一共几处、分别是什么。"""
        summary = self.relic_summary()
        if summary:
            body = "　".join("%s %d" % (lbl, n) for lbl, n in summary)
            text = "查找遗物　本层 %d 处：%s　·　再按 R 退出查找" % (
                sum(n for _, n in summary), body)
        else:
            text = "本层没有遗物来源　·　再按 R 退出查找"

        t = self.F_SML.render(text, True, (255, 255, 255))
        box = pygame.Rect(0, 0, t.get_width() + 44, 36)
        box.midtop = (WIDTH // 2, 62)
        pygame.draw.rect(screen, RELIC_COL, box, border_radius=10)
        screen.blit(t, t.get_rect(center=box.center))

    def hovered_node(self, mouse):
        for nid, n in self.nodes.items():
            sx, sy = self.world_to_screen(n["wx"], n["wy"])
            if (sx - mouse[0]) ** 2 + (sy - mouse[1]) ** 2 <= (NODE_R + 4) ** 2:
                return n
        return None

    def draw_topbar(self, screen):
        bar = pygame.Rect(0, 0, WIDTH, 56)
        pygame.draw.rect(screen, PANEL, bar)
        pygame.draw.line(screen, PANEL_LINE, (0, 56), (WIDTH, 56))

        t = self.F_BIG.render("公理塔　·　%s" % self.floor["name"], True, TEXT)
        screen.blit(t, (24, 15))

        sub = self.F_SML.render("%s　%s" % (self.floor["grade"], self.floor["stage"]),
                                True, TEXT_MUTE)
        screen.blit(sub, (24 + t.get_width() + 16, 22))

        # 右下角进度
        prog = "%d / %d 层" % (self.floor_index + 1, len(self.data["floors"]))
        pt = self.F_MID.render(prog, True, TEXT_MUTE)
        screen.blit(pt, (WIDTH - pt.get_width() - 28, 18))

    def draw_side(self, screen):
        """左侧状态面板 + 底部提示。

        ⚠️ 坐标全部来自 `self.panel_layout()`，不在这里现推 ——
        面板上有两个可点的按钮（遗物 / 查找），画和点必须是同一份矩形。
        这块面板从前在 map_scene 和 main.py 里各画了一版（行数还不一样），
        现在只剩这一版，main.draw_player_panel 直接调它。
        """
        lay = self.panel_layout()
        box = lay["box"]
        pygame.draw.rect(screen, PANEL, box, border_radius=12)
        pygame.draw.rect(screen, PANEL_LINE, box, 1, border_radius=12)

        mouse = pygame.mouse.get_pos()

        # ---- 角色名 ----
        # 从玩家状态读，别再写死 —— 选了构形师却显示「演算者」会很怪
        y = lay["y_who"]
        who, who_col, who_icon = "演算者", TEXT_MUTE, ""
        if self.player is not None:
            ch = getattr(self.player, "char", None)
            if ch:
                who = "%s · %s" % (ch["name"], ch["title"])
                who_col = tuple(ch["color"])
                who_icon = ch["icon"]
        if who_icon:
            # 头像占位：主题色的小方框 + 角色符号
            pip = pygame.Rect(box.x + 12, y - 2, 22, 22)
            pygame.draw.rect(screen, who_col, pip, 2, border_radius=5)
            ic = self.F_TINY.render(who_icon, True, who_col)
            screen.blit(ic, ic.get_rect(center=pip.center))
            screen.blit(self.F_SML.render(who, True, TEXT_MUTE),
                        (pip.right + 7, y))
        else:
            screen.blit(self.F_SML.render(who, True, who_col), (box.x + 14, y))

        # ---- 血条 ----
        bar = lay["bar"]
        pygame.draw.rect(screen, (238, 236, 230), bar, border_radius=7)
        if self.max_hp > 0:
            fw = int(bar.w * max(0, self.hp) / self.max_hp)
            if fw > 0:
                pygame.draw.rect(screen, RED, pygame.Rect(bar.x, bar.y, fw, bar.h),
                                 border_radius=7)

        screen.blit(self.F_SML.render("生命 %d / %d" % (self.hp, self.max_hp), True, TEXT),
                    (box.x + 14, lay["y_hp"]))
        screen.blit(self.F_SML.render("金币 %d" % self.gold, True, GOLD),
                    (box.x + 14, lay["y_gold"]))

        # ---- 遗物按钮：点开图鉴 ----
        # 以前这里只是一行死文字「遗物 N 件」—— 玩家能看见数字，
        # 却没地方查这几件遗物到底干什么用（效果按名字结算，散在
        # battle_scene 各处，记不住就只能猜）。
        btn = lay["btn_relics"]
        hv = btn.collidepoint(mouse)
        pygame.draw.rect(screen, RELIC_SOFT if hv else (247, 246, 242), btn,
                         border_radius=7)
        pygame.draw.rect(screen, RELIC_COL if hv else PANEL_LINE, btn,
                         1, border_radius=7)
        rt = self.F_SML.render("遗物 %d 件" % len(self.relics), True, RELIC_COL)
        screen.blit(rt, (btn.x + 8, btn.y + 5))
        ft = self.F_TINY.render("查看 ›", True, RELIC_COL if hv else TEXT_FAINT)
        screen.blit(ft, (btn.right - ft.get_width() - 8, btn.y + 7))

        screen.blit(self.F_SML.render("牌库 %d 张" % self.deck_count(), True, TEXT_MUTE),
                    (box.x + 14, lay["y_deck"]))

        if lay["y_hide"] is not None:
            screen.blit(self.F_SML.render("未完待证：下一层未知", True, GOLD),
                        (box.x + 14, lay["y_hide"]))
        if lay["y_save"] is not None:
            screen.blit(self.F_TINY.render("有存档　L 读档", True, GOLD),
                        (box.x + 14, lay["y_save"]))

        # ---- 查找遗物开关 ----
        fb = lay["btn_find"]
        fhv = fb.collidepoint(mouse)
        if self.find_relic:
            bg = RELIC_COL if not fhv else (110, 100, 205)
            pygame.draw.rect(screen, bg, fb, border_radius=8)
            label, fg = "查找中 · 按 R 退出", (255, 255, 255)
        else:
            pygame.draw.rect(screen, RELIC_SOFT if fhv else (247, 246, 242), fb,
                             border_radius=8)
            pygame.draw.rect(screen, RELIC_COL if fhv else PANEL_LINE, fb,
                             1, border_radius=8)
            label, fg = "查找遗物 · R", RELIC_COL
        lt = self.F_SML.render(label, True, fg)
        screen.blit(lt, lt.get_rect(center=fb.center))

        # ---- 底部提示 ----
        tip = "滚轮 / ↑↓ 滚动视角　·　点击高亮节点移动　·　ESC 返回"
        tt = self.F_SML.render(tip, True, TEXT_MUTE)
        screen.blit(tt, (24, HEIGHT - 30))

    def tooltip_lines(self, n):
        """悬停提示要显示哪几行 —— (文字, 颜色, 字体) 的列表。

        单独抽出来是为了**能被断言**：折行/文案这种东西画到屏幕上之后
        测试就看不见了，于是「未完待证不许剧透」这条规则只能靠肉眼。
        现在测试可以直接把这几行拿去过一遍。
        """
        is_reach = n["id"] in self.reachable()
        e = self.edge_to(n["id"])
        # 同一套「看不清」判据（node_is_hidden）—— 以前提示不看 hide_next，
        # 于是「未完待证」的下一行虽然画着问号，鼠标一放上去还是老实交代了
        # 类型和描述，等于白送剧透。
        hidden = self.node_is_hidden(n["id"], n)

        lines = []
        if hidden:
            lines.append(("？  未探明", TEXT, self.F_MID))
            lines.append(("未完待证：这一格要走到才看得清", TEXT_MUTE, self.F_SML))
        else:
            lines.append(("%s  %s" % (n["icon"], n["type_name"]), TEXT, self.F_MID))
            lines.append((n["desc"], TEXT_MUTE, self.F_SML))
            src = relic_source_of(n["type"])
            if src:
                lines.append(("遗物来源 · %s：%s" % src, RELIC_COL, self.F_SML))

        if e and e.get("cost"):
            c = e["cost"]
            lines.append(("", TEXT, self.F_SML))
            lines.append(("路线代价 · %s" % c["name"], GOLD, self.F_SML))
            lines.append((c["desc"], TEXT_MUTE, self.F_TINY))
            lines.append((c["math_note"], TEXT_FAINT, self.F_TINY))

        if is_reach:
            hint = "点击移动过去"
        elif n["id"] == self.current:
            hint = "你在这里"
        else:
            p = self.find_path(n["id"])
            hint = "点击查看路径（%d 步）" % len(p) if p else "从当前位置无法到达"
        lines.append(("", TEXT, self.F_SML))
        lines.append((hint, ACCENT, self.F_SML))
        return lines

    def draw_tooltip(self, screen, mouse):
        n = self.hovered_node(mouse)
        if n is None:
            return

        pad = 14
        lines = self.tooltip_lines(n)

        # 计算尺寸
        w = max(f.render(t, True, c).get_width() for t, c, f in lines) + pad * 2
        h = sum(f.get_height() + 4 for _, _, f in lines) + pad * 2
        w = max(w, 200)

        x = min(mouse[0] + 18, WIDTH - w - 10)
        y = min(mouse[1] + 18, HEIGHT - h - 10)
        box = pygame.Rect(x, y, w, h)

        pygame.draw.rect(screen, PANEL, box, border_radius=10)
        pygame.draw.rect(screen, PANEL_LINE, box, 2, border_radius=10)

        cy = box.y + pad
        for text, col, f in lines:
            if text:
                screen.blit(f.render(text, True, col), (box.x + pad, cy))
            cy += f.get_height() + 4


# ==================== 遗物图鉴（覆盖层）====================


class RelicPanel:
    """地图上的遗物图鉴：整池一次列全，拿到的高亮、没拿到的灰着。

    为什么值得单独做一块面板：左侧只写了「遗物 3 件」一个数字，
    而遗物效果是**按名字结算**、代码散在 battle_scene / player 各处
    （见 player.RELIC_POOL 上面那段注释），玩家不查就只能靠猜 ——
    「容错区间」是省一张牌还是加伤害？「等周不等式」什么时候触发？
    这里把每件的名字、效果、有没有到手一次讲清楚。

    卡片高度是按**行数**算出来的，不是写死的：遗物池从 6 件涨到 10 件时，
    写死的那套尺寸算出 928 高，最后一行整个掉出 720 的屏幕下沿（还点不到）。
    现在池子再怎么涨，也只是卡片变矮，面板**永远留在屏幕里**。

    接口跟其它覆盖层一致：handle() / draw()，宿主负责在它开着的时候
    优先把事件喂过来（见 MapScene.handle_relic_panel）。
    """

    COLS = 4
    #: 卡片的目标尺寸（高度只是**上限**，实际高度按行数算，见 __init__）
    TILE_W, TILE_H, GAP = 236, 146, 18
    #: 面板里卡片区上下要留掉的固定高度：标题那一行 + 底部「来源 / 关闭」
    TOP_PAD, BOTTOM_PAD = 78, 96

    def __init__(self, owned):
        self.owned = set(owned)

        self.F_TITLE = E.load_font(21)
        self.F_SML = E.load_font(15)
        self.F_TINY = E.load_font(13)

        pool = P.RELIC_POOL
        rows = max(1, (len(pool) + self.COLS - 1) // self.COLS)
        gw = self.COLS * self.TILE_W + (self.COLS - 1) * self.GAP

        # 高度：先算「屏幕里还剩多少高度可以给卡片」，再和 TILE_H 取小的那个。
        # 3 列 × 172 高那套 6 件时刚好卡在 720 边上；遗物池加到 10 件变成
        # 4 行，直接算出 928 高 —— 最后一行整个掉出屏幕（而且点不到）。
        # 所以卡片高度**必须按行数算出来**，池子以后再涨也只是卡片变矮。
        # 104 是「名字两行 + 效果两行」还装得下的下限；真涨到装不下那天，
        # tmp/verify_relic_find.py 里那条「卡片都在面板框里」会先红。
        avail = (HEIGHT - 32 - self.TOP_PAD - self.BOTTOM_PAD
                 - (rows - 1) * self.GAP)
        tile_h = max(104, min(self.TILE_H, avail // rows))
        gh = rows * tile_h + (rows - 1) * self.GAP
        self.tile_h = tile_h

        # 宽度按卡片数算出来，不写死 —— 遗物池以后加一件，
        # 面板自己会变宽，不会把最后一列挤出屏幕（这个坑在
        # 牌组面板上踩过，见 README 踩坑）。
        self.box = pygame.Rect(0, 0, gw + 64, self.TOP_PAD + gh + self.BOTTOM_PAD)
        # 故意偏右一点：左边是状态面板，别一打开就把它整个盖住
        # （玩家刚点的就是那块面板上的按钮，盖住会让人以为点错了）
        self.box.center = (700, 384)

        self.tiles = []
        for i, item in enumerate(pool):
            r, c = divmod(i, self.COLS)
            rect = pygame.Rect(self.box.x + 32 + c * (self.TILE_W + self.GAP),
                               self.box.y + 74 + r * (tile_h + self.GAP),
                               self.TILE_W, tile_h)
            self.tiles.append((item, rect, item[0] in self.owned))

        self.btn_close = pygame.Rect(self.box.right - 182, self.box.bottom - 70,
                                     150, 40)

    # ---------- 输入 ----------
    def handle(self, event, mouse):
        """返回 "close" 表示要关掉；其余返回 None。"""
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "close"
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # 点「关闭」或者点面板外都关 —— 只给一个按钮的话，
            # 小朋友会去点旁边「空白处」然后以为界面卡死了
            if self.btn_close.collidepoint(mouse):
                return "close"
            if not self.box.collidepoint(mouse):
                return "close"
        return None

    # ---------- 绘制 ----------
    def draw(self, screen, mouse):
        # 背后压一层暗纱：地图还在，但不抢眼
        veil = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        veil.fill((26, 26, 34, 96))
        screen.blit(veil, (0, 0))

        pygame.draw.rect(screen, (228, 226, 218), self.box.move(0, 4),
                         border_radius=16)
        pygame.draw.rect(screen, PANEL, self.box, border_radius=16)
        pygame.draw.rect(screen, RELIC_COL, self.box, 2, border_radius=16)

        # 标题
        t = self.F_TITLE.render("遗物图鉴", True, TEXT)
        screen.blit(t, (self.box.x + 32, self.box.y + 22))
        got, total = len(self.owned), len(P.RELIC_POOL)
        sub = self.F_SML.render("已收集 %d / %d 件" % (got, total), True, RELIC_COL)
        screen.blit(sub, (self.box.x + 32 + t.get_width() + 16,
                          self.box.y + 28))
        note = "遗物效果按名字结算，重复拿到不会叠加" if got else \
            "还没有遗物 —— 看下面那行「来源」去找"
        nt = self.F_TINY.render(note, True, TEXT_MUTE)
        screen.blit(nt, (self.box.right - 32 - nt.get_width(), self.box.y + 30))

        for item, rect, has in self.tiles:
            self._draw_tile(screen, mouse, item, rect, has)

        # 底部：来源图例 + 关闭
        src = "来源：" + "　".join(
            "%s（%s）" % (lbl, note_) for lbl, note_ in RELIC_SOURCE.values())
        st = self.F_TINY.render(src, True, TEXT_MUTE)
        screen.blit(st, (self.box.x + 32, self.box.bottom - 60))

        hv = self.btn_close.collidepoint(mouse)
        pygame.draw.rect(screen, (110, 100, 205) if hv else RELIC_COL,
                         self.btn_close, border_radius=10)
        bt = self.F_SML.render("关闭（ESC）", True, (255, 255, 255))
        screen.blit(bt, bt.get_rect(center=self.btn_close.center))

    def _draw_tile(self, screen, mouse, item, r, has):
        """一张遗物卡：名字 + 效果 + 到手了没有。"""
        name, desc = item
        hv = r.collidepoint(mouse)

        if has:
            pygame.draw.rect(screen, PANEL, r, border_radius=10)
            pygame.draw.rect(screen, RELIC_COL, r, 3 if hv else 2,
                             border_radius=10)
        else:
            pygame.draw.rect(screen, (246, 245, 241), r, border_radius=10)
            pygame.draw.rect(screen, (219, 217, 209) if hv else (230, 228, 220),
                             r, 1, border_radius=10)

        # 状态角标（右上角）
        tag = "已获得" if has else "未获得"
        tag_bg = RELIC_COL if has else (206, 204, 197)
        tt = self.F_TINY.render(tag, True, (255, 255, 255))
        tbox = pygame.Rect(0, 0, tt.get_width() + 16, tt.get_height() + 6)
        tbox.topright = (r.right - 12, r.y + 12)
        pygame.draw.rect(screen, tag_bg, tbox, border_radius=7)
        screen.blit(tt, tt.get_rect(center=tbox.center))

        nm = self.F_TITLE.render(name, True, TEXT if has else TEXT_FAINT)
        screen.blit(nm, (r.x + 14, r.y + 14))

        # 效果文案：按真实行数往下排（别写死 y —— 文案一改就会被压住，
        # 上一轮「新卡到手」就是这么被按钮盖掉半行的）
        cy = r.y + 52
        for ln in E.wrap_text(self.F_SML, desc, r.w - 28):
            screen.blit(self.F_SML.render(
                ln, True, TEXT_MUTE if has else TEXT_FAINT), (r.x + 14, cy))
            cy += self.F_SML.get_height() + 3


# ==================== 自立运行时 ====================


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("数与形 · 公理塔地图")
    clock = pygame.time.Clock()

    data = load_map()
    scene = MapScene(data)
    scene.cam_y = scene.camera_for(scene.nodes[scene.current])
    scene.cam_target = scene.cam_y

    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        mouse = pygame.mouse.get_pos()
        t_ms = pygame.time.get_ticks()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                # 遗物图鉴开着时它独占输入（ESC 只关面板，不退出程序）
                if scene.relic_panel is not None:
                    scene.handle_relic_panel(ev, mouse)
                    continue
                if ev.key == pygame.K_ESCAPE:
                    running = False
                elif ev.key == pygame.K_r:
                    scene.toggle_find_relic()
                elif ev.key in (pygame.K_UP, pygame.K_w):
                    scene.scroll_up(60)
                elif ev.key in (pygame.K_DOWN, pygame.K_s):
                    scene.scroll_down(60)
            elif ev.type == pygame.MOUSEWHEEL:
                # ev.y > 0 = 滚轮往上滚 -> 往塔的上方看
                if ev.y > 0:
                    scene.scroll_up(ev.y * 50)
                else:
                    scene.scroll_down(-ev.y * 50)
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if scene.handle_relic_panel(ev, mouse):
                    continue
                # 先问左侧面板上的按钮，再判节点 —— 否则点「遗物」会顺带走动
                if scene.handle_side_click(mouse):
                    continue
                n = scene.hovered_node(mouse)
                if n is not None:
                    if scene.can_move_to(n["id"]):
                        scene.move_to(n["id"])
                    else:
                        p = scene.find_path(n["id"])
                        if p:
                            scene.target = n["id"]
                            scene.path_hint = p
                            scene.push_log("查看路径：%d 步" % len(p))
                        else:
                            scene.push_log("无法到达该节点")

        scene.update(dt)
        scene.draw(screen, mouse, t_ms)
        scene.draw_relic_overlay(screen, mouse)
        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
