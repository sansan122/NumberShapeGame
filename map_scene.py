"""
《数与形》地图场景（pygame 版）
================================================
参考《杀戮尖塔》的爬塔地图：起点在底部，往上爬，镜头跟随。

操作：
  - 鼠标左键点击节点
  - 鼠标滚轮 / 上下方向键 滚动视角
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

import game_env as E

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

# 世界坐标布局参数
ROW_H = 128          # 行间距（世界坐标）
NODE_R = 26          # 节点半径
COL_W = 190          # 列间距


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

    # ==================== 层与节点 ====================
    def load_floor(self, idx):
        """载入第 idx 层，把节点转成世界坐标。"""
        self.floor_index = idx
        fl = self.data["floors"][idx]
        self.floor = fl
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
        """结算一个路线代价。"""
        cid = cost["id"]
        self.push_log("代价「%s」：%s" % (cost["name"], cost["desc"]))
        if cid == "approximate":
            self.max_hp = max(1, self.max_hp - 8)
            self.hp = min(self.hp, self.max_hp)
        elif cid == "liability":
            self.enemy_hp_mult *= 1.15
            self.push_log("本层敌人生命 +15%")
        elif cid == "unproven":
            self.hide_next = True
            self.push_log("下一层节点类型不可见")
        elif cid == "open_interval":
            self.force_elite_next = True
            self.push_log("下一个节点必为精英")

    # ==================== 相机 ====================
    def camera_for(self, node, anchor=0.62):
        """
        让节点落在屏幕 anchor 比例处时，相机应在哪。

        anchor 越大 -> 节点越靠屏幕下方 -> 上方能看到更多「前路」。
        太小会把可达节点顶出屏幕；太大下半屏会空。
        0.62 是试出来的平衡点：当前位置在下部，上面能看到 2~3 行。
        """
        return node["wy"] + (anchor - 0.5) * HEIGHT

    def update(self, dt):
        # 相机平滑
        self.cam_y += (self.cam_target - self.cam_y) * min(1.0, dt * 8.0)

    def scroll(self, dy):
        self.cam_target += dy
        self.cam_y += dy

    def clamp_camera(self):
        """限制相机范围，别滚出地图。"""
        if not self.row_nodes or not self.row_nodes[-1]:
            return
        top = self.row_nodes[-1][0]["wy"]      # 最上面一行的 y（最小）
        bot = self.row_nodes[0][0]["wy"]       # 最下面一行的 y（最大）
        lo = top - HEIGHT * 0.5                # 能看到顶层
        hi = bot + HEIGHT * 0.30               # 能看到底层
        self.cam_target = max(lo, min(hi, self.cam_target))
        self.cam_y = max(lo, min(hi, self.cam_y))

    # ==================== 坐标换算 ====================
    def world_to_screen(self, wx, wy):
        return int(WIDTH / 2 + wx), int(HEIGHT / 2 + (wy - self.cam_y))

    def screen_to_world(self, sx, sy):
        return sx - WIDTH / 2, sy - HEIGHT / 2 + self.cam_y

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
            hidden = self.hide_next and is_reach and n["type"] != "boss"

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

            # 当前位置加个小人标记
            if is_cur:
                pygame.draw.circle(screen, GOLD, (sx, sy - NODE_R - 14), 6)

        # ---------- 3. 顶部信息栏 ----------
        self.draw_topbar(screen)

        # ---------- 4. 左侧战报 / 右下提示 ----------
        self.draw_side(screen)

        # ---------- 5. 悬停提示 ----------
        self.draw_tooltip(screen, mouse)

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
        # ---- 左：状态 ----
        box = pygame.Rect(20, 76, 210, 150)
        pygame.draw.rect(screen, PANEL, box, border_radius=12)
        pygame.draw.rect(screen, PANEL_LINE, box, 1, border_radius=12)

        y = box.y + 14
        # 角色名从玩家状态读，别再写死 —— 选了构形师却显示「演算者」会很怪
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
        y += 24

        # 血条
        bar = pygame.Rect(box.x + 14, y, box.w - 28, 14)
        pygame.draw.rect(screen, (238, 236, 230), bar, border_radius=7)
        if self.max_hp > 0:
            fw = int(bar.w * max(0, self.hp) / self.max_hp)
            if fw > 0:
                pygame.draw.rect(screen, RED, pygame.Rect(bar.x, bar.y, fw, bar.h),
                                 border_radius=7)
        y += 20
        screen.blit(self.F_SML.render("生命 %d / %d" % (self.hp, self.max_hp), True, TEXT),
                    (box.x + 14, y))
        y += 24
        screen.blit(self.F_SML.render("遗物 %d 件" % len(self.relics), True, TEXT_MUTE),
                    (box.x + 14, y))
        y += 24
        if self.hide_next:
            screen.blit(self.F_SML.render("未完待证：下一层未知", True, GOLD),
                        (box.x + 14, y))

        # ---- 右下：战报 ----
        lb = pygame.Rect(WIDTH - 330, 76, 310, 178)
        pygame.draw.rect(screen, PANEL, lb, border_radius=12)
        pygame.draw.rect(screen, PANEL_LINE, lb, 1, border_radius=12)
        screen.blit(self.F_SML.render("战报", True, TEXT_MUTE), (lb.x + 14, lb.y + 10))
        ly = lb.y + 34
        for line in self.log[:7]:
            txt = line if len(line) <= 19 else line[:18] + "…"
            screen.blit(self.F_SML.render(txt, True, TEXT), (lb.x + 14, ly))
            ly += 20

        # ---- 底部提示 ----
        tip = "滚轮 / ↑↓ 滚动视角　·　点击高亮节点移动　·　ESC 返回"
        tt = self.F_SML.render(tip, True, TEXT_MUTE)
        screen.blit(tt, (24, HEIGHT - 30))

    def draw_tooltip(self, screen, mouse):
        n = self.hovered_node(mouse)
        if n is None:
            return

        is_reach = n["id"] in self.reachable()
        e = self.edge_to(n["id"])

        pad = 14
        lines = []
        lines.append(("%s  %s" % (n["icon"], n["type_name"]), TEXT, self.F_MID))
        lines.append((n["desc"], TEXT_MUTE, self.F_SML))

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
                if ev.key == pygame.K_ESCAPE:
                    running = False
                elif ev.key in (pygame.K_UP, pygame.K_w):
                    scene.scroll(60)
                elif ev.key in (pygame.K_DOWN, pygame.K_s):
                    scene.scroll(-60)
            elif ev.type == pygame.MOUSEWHEEL:
                scene.scroll(ev.y * 50)
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
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
        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
