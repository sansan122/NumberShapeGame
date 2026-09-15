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

import sys
from pathlib import Path

import pygame

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import map_scene as M            # noqa: E402
import node_scenes as NS         # noqa: E402
import save_system               # noqa: E402
from player import Player        # noqa: E402
from battle_scene import BattleScene, ENEMY_KINDS   # noqa: E402

WIDTH, HEIGHT = 1280, 720

# 战斗类节点
BATTLE_TYPES = {"battle", "elite", "boss"}

# 节点图标（与 tower.yaml 保持一致）
TYPE_ICON = {
    "battle": "×", "elite": "◆", "rest": "=",
    "shop": "√", "event": "?", "treasure": "∑", "boss": "★",
}


class Game:
    """顶层状态机：map / node / battle。"""

    def __init__(self, save_data=None):
        """
        save_data=None  -> 开一局新的
        save_data=dict  -> 从存档接着玩（用 save_system.build_game_data 造出来）
        """
        self.save_mgr = save_system.SaveManager()
        self.floor_stats = {}       # 每层战绩：{"1": {"battle": 3, "win": 3}}

        try:
            base_map = M.load_map()
        except FileNotFoundError as e:
            print(e)
            raise

        if save_data:
            self._init_from_save(save_data, base_map)
        else:
            self._init_new(base_map)

        self.mode = "map"        # map / node / battle / dead
        self.panel = None
        self.battle = None
        self.msg = ""
        self.msg_t = 0.0
        self.pending_node = None

        self.F_MID = pygame.font.Font("C:/Windows/Fonts/msyh.ttc", 21)
        self.F_SML = pygame.font.Font("C:/Windows/Fonts/msyh.ttc", 16)
        self.F_TINY = pygame.font.Font("C:/Windows/Fonts/msyh.ttc", 14)

        self.fonts = {
            "BIG": pygame.font.Font("C:/Windows/Fonts/msyh.ttc", 30),
            "MID": self.F_MID, "SML": self.F_SML, "TINY": self.F_TINY,
        }

    # ---------- 两种开局 ----------
    def _init_new(self, base_map):
        self.player = Player(max_hp=80, gold=60)
        self.map = M.MapScene(base_map)
        self.map.player = self.player
        self.map.cam_y = self.map.camera_for(self.map.nodes[self.map.current])
        self.map.cam_target = self.map.cam_y

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
    def save_game(self, quiet=False):
        if self.mode == "battle":
            self.flash("战斗中不能存档")
            return False
        ok = self.save_mgr.save(self)
        if not quiet:
            if ok:
                self.flash("已存档")
            else:
                self.flash("存档失败：%s" % self.save_mgr.last_error)
        return ok

    def auto_save(self):
        """静默存档，不弹提示。"""
        return self.save_game(quiet=True)

    def load_game(self):
        """读档并重建整局。返回新的 Game 或 None。"""
        data = self.save_mgr.load()
        if data is None:
            self.flash("读档失败：%s" % self.save_mgr.last_error)
            return None
        try:
            built = save_system.build_game_data(data)
            return Game(save_data=built)
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
        """
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
                self.save_game()
                return None
            if event.key == pygame.K_l:
                ng = self.load_game()
                if ng is not None:
                    return ("replace", ng)
                return None
            if event.key in (pygame.K_UP, pygame.K_w):
                self.map.scroll(70)
            elif event.key == pygame.K_DOWN:
                self.map.scroll(-70)
            return None

        if event.type == pygame.MOUSEWHEEL:
            self.map.scroll(event.y * 55)
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
                self.flash("演算者倒下了 —— 按 R 重新开始", 6)
                self.mode = "dead"
            else:
                self.after_node()
        return None

    # ==================== 更新 ====================
    def update(self, dt):
        if self.msg_t > 0:
            self.msg_t = max(0.0, self.msg_t - dt)

        if self.mode == "map":
            self.map.update(dt)
        elif self.mode == "battle" and self.battle:
            self.battle.update(dt)

    # ==================== 绘制 ====================
    def draw(self, screen, mouse, t_ms):
        if self.mode == "map":
            self.map.draw(screen, mouse, t_ms)
            self.draw_player_panel(screen)
            self.draw_hint(screen, "滚轮/↑↓ 滚动　·　点击高亮节点进入　·　S 存档　L 读档　·　ESC 退出")
        elif self.mode == "node":
            self.panel.draw(screen, mouse, t_ms)
        elif self.mode == "battle":
            self.battle.draw(screen, mouse, t_ms)
        elif self.mode == "dead":
            self.draw_dead(screen)

        if self.msg_t > 0 and self.mode != "dead":
            self.draw_toast(screen)

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
        screen.blit(self.F_SML.render("演算者", True, M.TEXT_MUTE),
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
        msg = self.F_MID.render("演算者倒下了", True, (200, 70, 70))
        screen.blit(msg, msg.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 50)))

        tips = "按 R 重新开始　·　ESC 退出"
        if self.has_save():
            tips = "按 L 读档回到存档点　·　R 重新开始　·　ESC 退出"
        sub = self.F_SML.render(tips, True, M.TEXT_MUTE)
        screen.blit(sub, sub.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 10)))

        if self.has_save():
            info = self.F_TINY.render(self.save_summary(), True, M.TEXT_FAINT)
            screen.blit(info, info.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 46)))


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("数与形 · 公理塔")
    clock = pygame.time.Clock()

    try:
        game = Game()
    except FileNotFoundError:
        print("\n请先运行 2_gen_map.bat 生成地图。")
        input("按回车退出...")
        return

    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        mouse = pygame.mouse.get_pos()
        t_ms = pygame.time.get_ticks()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
                break

            # 死亡画面
            if game.mode == "dead":
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_r:
                        game = Game()
                        game.save_mgr.delete()
                    elif ev.key == pygame.K_l:
                        ng = game.load_game()
                        if ng is not None:
                            game = ng
                    elif ev.key == pygame.K_ESCAPE:
                        running = False
                continue

            r = game.handle(ev, mouse)
            if r == "quit":
                running = False
                break
            if isinstance(r, tuple) and r[0] == "replace":
                # 读档成功：整局换掉，继续跑
                game = r[1]
                continue

        game.update(dt)
        game.draw(screen, mouse, t_ms)
        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
