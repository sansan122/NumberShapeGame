"""
《数与形》主程序
================================================
把地图、节点内容、战斗串成一个完整循环：

    地图（选路线）
      └─ 点节点 ──> 战斗 / 休整 / 商店 / 事件 / 宝箱
                      └─ 结束 ──> 回到地图

按键：
    滚轮 / ↑↓   滚动地图
    左键        进入高亮节点（远处节点 = 预览路径）
    S           存档
    L           读档
    ESC         退出

运行：双击 3_run_game.bat
"""

import os
import sys
from pathlib import Path

import pygame

import game_env as E             # 路径与字体的统一入口（见 game_env.py）

ROOT = E.resource_path()          # 打包后指向临时解包目录，别再自己算 __file__
sys.path.insert(0, str(ROOT))
# 地图生成器放在 map_tools/tools/ 下，加进搜索路径才能 import
sys.path.insert(0, str(ROOT / "map_tools" / "tools"))

import map_scene as M            # noqa: E402
import node_scenes as NS         # noqa: E402
import save_system               # noqa: E402
import player as P               # noqa: E402
import ui_scenes as UI           # noqa: E402
import deck_view                 # noqa: E402
import build_map as B            # noqa: E402
from player import Player        # noqa: E402
from battle_scene import BattleScene, ENEMY_KINDS   # noqa: E402

WIDTH, HEIGHT = 1280, 720

# 窗口标题：发给别人时，任务栏上显示的是这个
WINDOW_TITLE = "数与形 · 公理塔"

# 战斗类节点
BATTLE_TYPES = {"battle", "elite", "boss"}

# 节点图标（与 tower.yaml 保持一致）
TYPE_ICON = {
    "battle": "×", "elite": "◆", "rest": "=",
    "shop": "√", "event": "?", "treasure": "∑", "boss": "★",
}


class Game:
    """顶层状态机：map / node / battle。"""

    def __init__(self, save_data=None, char=None, save_slot=0):
        """
        save_data=None  -> 开一局新的
        save_data=dict  -> 从存档接着玩（用 save_system.build_game_data 造出来）
        char=dict       -> 本局用哪个角色（player.CHARACTERS 里的一项）
        save_slot       -> 这局关联哪个存档槽（自动存档、S 存档默认写这里）
        """
        self.save_slot = save_slot
        self.save_mgr = save_system.SaveManager(slot=save_slot)
        self.floor_stats = {}       # 每层战绩：{"1": {"battle": 3, "win": 3}}

        if save_data:
            # 读档：地图直接用存档里的（种子复现），不再现算
            base_map = save_data.get("map_data") or self._fresh_map()
            self._init_from_save(save_data, base_map)
        else:
            # 新的一局：**每次现生成一张新地图**，所以每局的节点布局都不同
            self._init_new(self._fresh_map(), char)

        self.mode = "map"        # map / node / battle / dead
        self.panel = None
        self.battle = None
        self.msg = ""
        self.msg_t = 0.0
        self.pending_node = None

        # 牌组查看覆盖层。放在 Game 这一层统一管，
        # 于是地图上 / 节点面板里 / 战斗里 按 D 都能打开，逻辑只有一份。
        self.deck_view = deck_view.DeckView()

        self.F_MID = E.load_font(21)
        self.F_SML = E.load_font(16)
        self.F_TINY = E.load_font(14)

        self.fonts = {
            "BIG": E.load_font(30),
            "MID": self.F_MID, "SML": self.F_SML, "TINY": self.F_TINY,
        }

    # ---------- 两种开局 ----------
    @staticmethod
    def _fresh_map():
        """现生成一张新地图（不落盘）。

        以前这里读的是 map_tools/out/map.json —— 那个文件是**静态的**，
        所以每次运行游戏看到的节点布局完全一样，用户反馈过
        「不管运行几次都是一样的」。改成现场生成后，
        每开一局都是一张新图；而存档里带了 seed，
        读档时用同一个 seed 重新生成，照样能精确复现。
        """
        try:
            return B.build_in_memory()
        except FileNotFoundError:
            # 配置读不到时退回磁盘上的旧地图，至少能进游戏
            return M.load_map()

    def _init_new(self, base_map, char=None):
        self.player = Player(char=char)
        self.map = M.MapScene(base_map)
        self.map.player = self.player
        self.map.cam_y = self.map.camera_for(self.map.nodes[self.map.current])
        self.map.cam_target = self.map.cam_y
        self.map.push_log("种子 %d" % base_map.get("seed", 0))

    def _init_from_save(self, save_data, base_map):
        """从存档恢复。地图种子对得上就完全复现，对不上就只恢复玩家。"""
        self.player = save_data["player"]

        md = save_data.get("map_data") or base_map
        floor_index = save_data.get("floor_index", 0)
        # 楼层越界保护：存档是三层塔时代的，现在塔层数变了
        floor_index = max(0, min(floor_index, len(md["floors"]) - 1))

        self.map = M.MapScene(md, floor_index=floor_index)
        self.map.player = self.player

        # 恢复地图副作用
        fx = save_data.get("map_effects", {})
        self.map.hide_next = fx.get("hide_next", False)
        self.map.enemy_hp_mult = fx.get("enemy_hp_mult", 1.0)
        self.map.force_elite_next = fx.get("force_elite_next", False)

        # 恢复站位（节点 id 每层都是局部的，必须和当前层一起理解）
        cur = save_data.get("current")
        if cur is not None and cur in self.map.nodes:
            self.map.current = cur
        vis = set(save_data.get("visited", []))
        vis = {v for v in vis if v in self.map.nodes}
        vis.add(self.map.current)
        self.map.visited = vis

        self.map.cam_y = self.map.camera_for(self.map.nodes[self.map.current])
        self.map.cam_target = self.map.cam_y

        self.floor_stats = dict(save_data.get("floor_stats") or {})

        if save_data.get("seed_ok"):
            self.map.push_log("读档成功，接着爬")
        else:
            self.map.push_log("读档：地图已重新生成，只恢复了状态")

    # ==================== 节点派发 ====================
    def enter_node(self, node):
        """点击一个节点：先移动过去，再进入它的内容。"""
        nid = node["id"]
        ntype = node["type"]

        if not self.map.can_move_to(nid):
            self.flash("只能走到高亮的下一个节点")
            return

        # 付代价 + 移动
        self.map.move_to(nid)
        self.pending_node = node

        if ntype in BATTLE_TYPES:
            mult = getattr(self.map, "enemy_hp_mult", 1.0)
            self.battle = BattleScene(self.player, ntype, mult)
            self.mode = "battle"
            self.flash("遭遇 %s！" % ENEMY_KINDS[ntype]["name"])
        else:
            panel = NS.make_panel(ntype, self.player)
            if panel is None:
                # 没有内容的类型，直接返回地图
                self.flash("这里空无一物")
                self.after_node()
                return
            panel.fonts = self.fonts
            self.panel = panel
            self.mode = "node"

    def after_node(self):
        """节点内容结束，回地图。"""
        node = self.pending_node
        self.pending_node = None
        self.panel = None
        self.mode = "map"

        if node and node["row"] == self.map.row_count - 1:
            self.flash("本层通过！前往下一层")
            self.next_floor()

    def next_floor(self):
        nxt = self.map.floor_index + 1
        if nxt < len(self.map.data["floors"]):
            self.map.load_floor(nxt)
            self.map.cam_y = self.map.camera_for(
                self.map.nodes[self.map.current])
            self.map.cam_target = self.map.cam_y
            # 换层时自动存一次：这是最自然的存档点
            self.auto_save()
        else:
            self.mode = "map"
            self.flash("公理塔已到顶 —— 全剧终", 8)
            # 通关了就把存档清掉，免得下次一进来就是「已通关」状态
            self.save_mgr.delete()

    # ==================== 存档 / 读档 ====================
    def save_game(self, quiet=False, slot=None):
        if self.mode == "battle":
            self.flash("战斗中不能存档")
            return False
        if slot is not None:
            # 显式指定槽位：换一个 SaveManager 存过去，并记住本局绑这个槽
            self.save_slot = slot
            self.save_mgr = save_system.SaveManager(slot=slot)
        ok = self.save_mgr.save(self)
        if not quiet:
            if ok:
                self.flash("已存档（槽 %d）" % (self.save_slot + 1))
            else:
                self.flash("存档失败：%s" % self.save_mgr.last_error)
        return ok

    def auto_save(self):
        """静默存档，不弹提示（换层时用，写到本局绑定的槽）。"""
        return self.save_game(quiet=True)

    def load_game(self, slot=None):
        """从指定槽读档并重建整局。返回新的 Game 或 None。"""
        if slot is not None:
            mgr = save_system.SaveManager(slot=slot)
        else:
            mgr = self.save_mgr
        data = mgr.load()
        if data is None:
            self.flash("读档失败：%s" % mgr.last_error)
            return None
        try:
            built = save_system.build_game_data(data)
            return Game(save_data=built, save_slot=(slot if slot is not None else 0))
        except Exception as e:              # noqa: BLE001
            self.flash("存档内容有问题：%s" % e)
            return None

    def has_save(self):
        return self.save_mgr.exists()

    def save_summary(self):
        """给提示语用的一句话描述。"""
        info = self.save_mgr.info()
        if not info:
            return "没有存档"
        return "%s　第 %d 层　生命 %d/%d" % (
            info["saved_at"], info["floor_index"] + 1,
            info["hp"], info["max_hp"])

    def flash(self, text, secs=2.6):
        self.msg = text
        self.msg_t = secs

    # ==================== 事件 ====================
    def handle(self, event, mouse):
        """把事件转给当前模式的处理函数。

        注意这里必须 return —— handle_map / handle_node / handle_battle
        会返回 "quit" 或 ("replace", game) 这类信号，
        丢掉返回值就等于「按 ESC 不退出、按 L 不换局」。

        牌组面板是个**覆盖层**，它开着的时候要优先吃掉事件，
        否则在战斗里按 ↑↓ 翻牌组会连带把战场也操作了。
        """
        if self.deck_view.open:
            self.deck_view.handle(event, mouse)
            return None

        # D 打开牌组 —— 三种模式（地图 / 节点 / 战斗）都支持。
        # 两种情况下不开：
        #   · 战斗中正在答题（会干扰输入）
        #   · 战斗已结算（那时候按任意键都该是「离开」，别把按键吞掉）
        if event.type == pygame.KEYDOWN and event.key == pygame.K_d:
            b = self.battle
            blocked = (self.mode == "battle" and b
                       and (b.quiz is not None or b.done))
            if not blocked:
                self.deck_view.open_with(self.player.deck, self.player.char)
                return None

        # M 返回主菜单 —— 地图 / 节点 / 战斗都能回，不用再「只能退出程序」。
        # 战斗答题时例外（M 会让位给数字输入，避免误触）。
        if event.type == pygame.KEYDOWN and event.key == pygame.K_m:
            b = self.battle
            blocked = (self.mode == "battle" and b and b.quiz is not None)
            if not blocked:
                return "menu"

        if self.mode == "map":
            return self.handle_map(event, mouse)
        if self.mode == "node":
            return self.handle_node(event, mouse)
        if self.mode == "battle":
            return self.handle_battle(event, mouse)
        return None

    def handle_map(self, event, mouse):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return "quit"
            if event.key == pygame.K_s:
                return "save_menu"
            if event.key == pygame.K_l:
                return "load_menu"
            if event.key in (pygame.K_UP, pygame.K_w):
                self.map.scroll_up(70)
            elif event.key in (pygame.K_DOWN,):
                self.map.scroll_down(70)
            return None

        if event.type == pygame.MOUSEWHEEL:
            # ev.y > 0 = 滚轮往上滚 -> 往塔的上方看（方向约定见 MapScene.scroll_up）
            if event.y > 0:
                self.map.scroll_up(event.y * 55)
            else:
                self.map.scroll_down(-event.y * 55)
            return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            nd = self.map.hovered_node(mouse)
            if nd is None:
                return None
            if self.map.can_move_to(nd["id"]):
                self.enter_node(nd)
            else:
                # 远处节点：只预览路径
                p = self.map.find_path(nd["id"])
                if p:
                    self.map.target = nd["id"]
                    self.map.path_hint = p
                    self.map.push_log("查看路径：%d 步" % len(p))
                else:
                    self.flash("从当前位置无法到达")
        return None

    def handle_node(self, event, mouse):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            # 面板不允许 ESC 跳过（避免白嫖），提示一下
            self.flash("请先做出选择")
            return None

        r = self.panel.handle(event, mouse)
        if r == "leave":
            self.after_node()
        return None

    def handle_battle(self, event, mouse):
        r = self.battle.handle(event, mouse)
        if r == "leave":
            result = self.battle.result
            self.battle = None
            if result == "lose":
                self.flash("%s倒下了 —— 按 R 重新开始" % self.player.char["name"], 6)
                self.mode = "dead"
            else:
                self.after_node()
        return None

    # ==================== 更新 ====================
    def update(self, dt):
        if self.msg_t > 0:
            self.msg_t = max(0.0, self.msg_t - dt)

        self.deck_view.update(dt)

        if self.mode == "map":
            self.map.update(dt)
        elif self.mode == "battle" and self.battle:
            self.battle.update(dt)

    # ==================== 绘制 ====================
    def draw(self, screen, mouse, t_ms):
        if self.mode == "map":
            self.map.draw(screen, mouse, t_ms)
            self.draw_player_panel(screen)
            self.draw_hint(screen, "滚轮/↑↓ 滚动　·　点击高亮节点进入　·　D 看牌组　·　S 存档　L 读档　·　M 主菜单　·　ESC 退出")
        elif self.mode == "node":
            self.panel.draw(screen, mouse, t_ms)
        elif self.mode == "battle":
            self.battle.draw(screen, mouse, t_ms)
        elif self.mode == "dead":
            self.draw_dead(screen)

        if self.msg_t > 0 and self.mode != "dead":
            self.draw_toast(screen)

        # 牌组面板画在最上层（它是覆盖层，要盖住地图/面板/战斗）
        self.deck_view.draw(screen, mouse, t_ms)

    def draw_player_panel(self, screen):
        """地图上显示的玩家状态（覆盖地图自带的简化版）。"""
        p = self.player
        has_save = self.has_save()

        # 面板高度按内容算：多一行「有存档」就高一点，
        # 否则那行字会画到面板外面去（看起来像和「记录」叠住了）
        rows = 4 + (1 if has_save else 0)
        box_h = 12 + 24 + 20 + 24 * 3 + 22 * (rows - 4) + 22 + 6
        box = pygame.Rect(20, 76, 210, box_h)
        pygame.draw.rect(screen, M.PANEL, box, border_radius=12)
        pygame.draw.rect(screen, M.PANEL_LINE, box, 1, border_radius=12)

        y = box.y + 12
        # 角色名从玩家状态读，别写死 —— 选了构形师却显示「演算者」会很怪。
        # （这是 main.py 自己画的面板，会盖掉 map_scene 里那版，两处都要改）
        ch = getattr(p, "char", None)
        who = "%s · %s" % (ch["name"], ch["title"]) if ch else "演算者"
        if ch:
            # 头像占位：主题色方框 + 角色符号
            pip = pygame.Rect(box.x + 12, y - 1, 22, 22)
            pygame.draw.rect(screen, tuple(ch["color"]), pip, 2,
                             border_radius=5)
            ic = self.F_TINY.render(ch["icon"], True, tuple(ch["color"]))
            screen.blit(ic, ic.get_rect(center=pip.center))
            screen.blit(self.F_SML.render(who, True, M.TEXT_MUTE),
                        (pip.right + 7, y))
        else:
            screen.blit(self.F_SML.render(who, True, M.TEXT_MUTE),
                        (box.x + 14, y))
        y += 24

        bar = pygame.Rect(box.x + 14, y, box.w - 28, 14)
        pygame.draw.rect(screen, (238, 236, 230), bar, border_radius=7)
        if p.max_hp > 0 and p.hp > 0:
            fw = int(bar.w * p.hp / p.max_hp)
            if fw > 0:
                pygame.draw.rect(screen, (200, 70, 70),
                                 pygame.Rect(bar.x, bar.y, fw, bar.h),
                                 border_radius=7)
        y += 20
        screen.blit(self.F_SML.render("生命 %d / %d" % (p.hp, p.max_hp),
                                      True, M.TEXT), (box.x + 14, y))
        y += 24
        screen.blit(self.F_SML.render("金币 %d" % p.gold, True, (196, 148, 30)),
                    (box.x + 14, y))
        y += 24
        screen.blit(self.F_SML.render("遗物 %d 件" % len(p.relics), True, M.TEXT_MUTE),
                    (box.x + 14, y))
        y += 24
        screen.blit(self.F_SML.render("牌库 %d 张" % len(p.deck), True, M.TEXT_MUTE),
                    (box.x + 14, y))

        # 有存档就在面板底部提示一下，免得玩家忘了
        if has_save:
            y += 22
            screen.blit(self.F_TINY.render("有存档　L 读档", True, M.GOLD),
                        (box.x + 14, y))

        # 最近的事件日志（紧贴在状态面板下方）
        if p.log_lines:
            ly = box.bottom + 12
            lb = pygame.Rect(20, ly, 250, 150)
            pygame.draw.rect(screen, M.PANEL, lb, border_radius=12)
            pygame.draw.rect(screen, M.PANEL_LINE, lb, 1, border_radius=12)
            screen.blit(self.F_TINY.render("记录", True, M.TEXT_MUTE),
                        (lb.x + 12, lb.y + 8))
            yy = lb.y + 28
            for line in p.log_lines[:6]:
                txt = line if len(line) <= 16 else line[:15] + "…"
                screen.blit(self.F_TINY.render(txt, True, M.TEXT), (lb.x + 12, yy))
                yy += 19

    def draw_hint(self, screen, text):
        """底部提示。
        地图自己也会在同一个位置画一行提示，所以先把那条区域
        盖成背景色，避免两行字叠在一起糊掉。"""
        strip = pygame.Rect(0, HEIGHT - 36, WIDTH, 36)
        pygame.draw.rect(screen, M.BG, strip)
        tt = self.F_TINY.render(text, True, M.TEXT_MUTE)
        screen.blit(tt, (24, HEIGHT - 30))

    def draw_toast(self, screen):
        """底部中央的短暂提示。"""
        surf = self.F_MID.render(self.msg, True, (255, 255, 255))
        pad = 22
        box = pygame.Rect(0, 0, surf.get_width() + pad * 2,
                          surf.get_height() + pad)
        box.center = (WIDTH // 2, 150)
        veil = pygame.Surface(box.size, pygame.SRCALPHA)
        veil.fill((30, 30, 28, 225))
        screen.blit(veil, box.topleft)
        screen.blit(surf, surf.get_rect(center=box.center))

    def draw_dead(self, screen):
        screen.fill((246, 245, 240))
        # 角色名从玩家状态读 —— 选了构形师却写「演算者倒下了」会很出戏
        ch = self.player.char
        msg = self.F_MID.render("%s倒下了" % ch["name"], True, (200, 70, 70))
        screen.blit(msg, msg.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 50)))

        tips = "按 R 重新开始　·　M 回主菜单　·　ESC 退出"
        if self.has_save():
            tips = "按 L 读档回到存档点　·　R 重新开始　·　M 主菜单　·　ESC 退出"
        sub = self.F_SML.render(tips, True, M.TEXT_MUTE)
        screen.blit(sub, sub.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 10)))

        if self.has_save():
            info = self.F_TINY.render(self.save_summary(), True, M.TEXT_FAINT)
            screen.blit(info, info.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 46)))


def make_window_icon():
    """画一个窗口/任务栏图标（免安装 exe 没法带资源文件，索性代码画）。

    图案：深蓝底 + 金色「∑」，和主菜单的视觉一致。
    """
    size = 64
    icon = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.rect(icon, (24, 95, 165), (0, 0, size, size), border_radius=12)
    pygame.draw.rect(icon, (196, 148, 30), (0, 0, size, size), 4, border_radius=12)
    glyph = E.load_font(42).render("∑", True, (250, 249, 245))
    icon.blit(glyph, glyph.get_rect(center=(size // 2, size // 2 + 2)))
    return icon


def main():
    """主循环。

    场景流转：
        主菜单 ──「开始」──> 选角色 ──「出发」──> 过渡 ──> 爬塔地图
           │                    │
           └─「继续」读档 ───────┴────────────────────────> 爬塔地图
    """
    # 在 pygame.init() 之前关掉 IME（中文输入法）。
    # 这是中文 Windows 上「键盘按键全都没反应」的头号原因：
    # 系统输入法处于中文状态时会把按键拦走做候选词，pygame 收不到
    # 正常的 KEYDOWN。这个环境变量必须在 init 之前设置才会生效。
    os.environ["SDL_IME_SHOW_UI"] = "0"

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption(WINDOW_TITLE)
    pygame.display.set_icon(make_window_icon())
    clock = pygame.time.Clock()

    # 游戏全程不需要文字输入，主动停掉 SDL 的 text input 通道，
    # 进一步保证 IME 不会拦走按键（战斗答题用的是 KEYDOWN 的 key 码，
    # 不依赖 text input 事件）。
    pygame.key.stop_text_input()

    # 主菜单。用 list_slots() 反映当前所有槽位的存档状态。
    scene = _menu_scene()
    game = None                 # 正式开局后才建
    paused_game = None          # 非 None = 游戏暂停在存档槽选择界面

    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        mouse = pygame.mouse.get_pos()
        t_ms = pygame.time.get_ticks()

        # 当前这一帧要画谁：
        #   游戏暂停在存档槽界面 -> 画存档槽
        #   否则有 game -> 画游戏，没有 -> 画 UI 场景
        if paused_game is not None:
            active = scene
        else:
            active = game if game is not None else scene

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
                break

            # ---------- 游戏暂停在存档槽选择界面 ----------
            if paused_game is not None:
                r = scene.handle(ev, mouse)
                if r == "back":
                    # 取消，回到游戏
                    paused_game = None
                    scene = None
                elif isinstance(r, tuple) and r[0] == "save":
                    _, slot = r
                    if paused_game.save_game(slot=slot):
                        paused_game = None
                        scene = None
                elif isinstance(r, tuple) and r[0] == "load":
                    _, slot = r
                    ng = _load_from_disk(slot)
                    if ng is None:
                        paused_game.flash("读档失败")
                        paused_game = None
                        scene = None
                    else:
                        game = ng
                        paused_game = None
                        scene = None
                continue

            # ---------- UI 场景（主菜单 / 选角色 / 过渡）----------
            if game is None:
                r = scene.handle(ev, mouse)

                if r == "quit":
                    running = False
                    break

                if isinstance(r, tuple) and r[0] == "pick":
                    # 选定角色 -> 走过渡，再开新局
                    scene = UI.LoadingScene(r[1])
                    continue

                if r == "new":
                    scene = UI.CharSelectScene()
                    continue

                if r == "load":
                    # 主菜单「继续」-> 进存档槽选择（读档）
                    scene = UI.SaveSlotScene(mode="load")
                    continue

                if r == "back":
                    # 从选角色/存档槽退回主菜单，重读存档状态
                    scene = _menu_scene()
                    continue

                continue    # 场景内部的小动作（切换选中等）

            # ---------- 正式游戏 ----------
            if game.mode == "dead":
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_r:
                        game = None
                        scene = UI.CharSelectScene()
                    elif ev.key == pygame.K_l:
                        # 死亡画面读档：也走槽选择
                        paused_game = game
                        scene = UI.SaveSlotScene(mode="load")
                    elif ev.key == pygame.K_m:
                        game = None
                        scene = _menu_scene()
                    elif ev.key == pygame.K_ESCAPE:
                        running = False
                continue

            r = game.handle(ev, mouse)
            if r == "quit":
                running = False
                break
            if r == "menu":
                # M 键：回主菜单（不是退出程序）
                game = None
                scene = _menu_scene()
                continue
            if r == "save_menu":
                # S 键：暂停游戏，进存档槽选择（存档）
                paused_game = game
                scene = UI.SaveSlotScene(mode="save")
                continue
            if r == "load_menu":
                # L 键：暂停游戏，进存档槽选择（读档）
                paused_game = game
                scene = UI.SaveSlotScene(mode="load")
                continue
            if isinstance(r, tuple) and r[0] == "replace":
                # 读档成功：整局换掉，继续跑
                game = r[1]
                continue

        if not running:
            break

        # 过渡场景自己倒数，到点就真的开一局
        if paused_game is None and game is None:
            r = scene.update(dt)
            if r == "done":
                try:
                    game = Game(char=scene.char)
                except FileNotFoundError:
                    print("\n找不到地图配置，请先运行 2_gen_map.bat。")
                    input("按回车退出...")
                    break
                scene = None
                continue
        elif paused_game is None:
            game.update(dt)

        active.draw(screen, mouse, t_ms)
        pygame.display.flip()

    pygame.quit()
    sys.exit()


def _save_line():
    """主菜单要显示的一行存档摘要（有多个槽时，显示最近的那个）。"""
    slots = save_system.list_slots()
    # 挑一个「最近保存」的有档槽位来显示
    best = None
    for s in slots:
        if s["exists"] and s["info"]:
            if best is None or s["info"]["saved_at"] > best["info"]["saved_at"]:
                best = s
    if best is None:
        return ""
    info = best["info"]
    return "最近存档：槽 %d　第 %d 层　生命 %d/%d" % (
        best["slot"] + 1, info["floor_index"] + 1,
        info["hp"], info["max_hp"])


def _has_any_save():
    """有没有任意一个槽位有存档（主菜单「继续」按钮是否可用）。"""
    return any(s["exists"] for s in save_system.list_slots())


def _menu_scene():
    """造一个反映当前存档状态的主菜单。"""
    return UI.MenuScene(has_save=_has_any_save(), save_info=_save_line())


def _load_from_disk(slot):
    """从指定槽位读档并造一局新的。失败返回 None。"""
    mgr = save_system.SaveManager(slot=slot)
    data = mgr.load()
    if data is None:
        return None
    try:
        built = save_system.build_game_data(data)
        return Game(save_data=built, save_slot=slot)
    except Exception as e:                  # noqa: BLE001
        print("[读档失败] 存档内容有问题：%s" % e)
        return None


if __name__ == "__main__":
    main()
