"""
《数与形》主程序
================================================
把地图、节点内容、战斗串成一个完整循环：

    地图（选路线）
      └─ 点节点 ──> 战斗 / 休整 / 商店 / 事件 / 宝箱
                      └─ 结束 ──> 回到地图

按 M 可以随时看地图全景，ESC 返回上一层 / 退出。

运行：双击 3_run_game.bat
"""

import sys
from pathlib import Path

import pygame

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import map_scene as M            # noqa: E402
import node_scenes as NS         # noqa: E402
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

    def __init__(self):
        self.player = Player(max_hp=80, gold=60)

        try:
            data = M.load_map()
        except FileNotFoundError as e:
            print(e)
            raise

        self.map = M.MapScene(data)
        self.map.player = self.player          # 让地图读到共享状态
        self.map.cam_y = self.map.camera_for(self.map.nodes[self.map.current])
        self.map.cam_target = self.map.cam_y

        self.mode = "map"        # map / node / battle
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
        else:
            self.mode = "map"
            self.flash("公理塔已到顶 —— 全剧终")

    def flash(self, text, secs=2.6):
        self.msg = text
        self.msg_t = secs

    # ==================== 事件 ====================
    def handle(self, event, mouse):
        if self.mode == "map":
            self.handle_map(event, mouse)
        elif self.mode == "node":
            self.handle_node(event, mouse)
        elif self.mode == "battle":
            self.handle_battle(event, mouse)

    def handle_map(self, event, mouse):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return "quit"
            if event.key in (pygame.K_UP, pygame.K_w):
                self.map.scroll(70)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
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
            self.draw_hint(screen, "滚轮/↑↓ 滚动　·　点击高亮节点进入　·　ESC 退出")
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
        box = pygame.Rect(20, 76, 210, 176)
        pygame.draw.rect(screen, M.PANEL, box, border_radius=12)
        pygame.draw.rect(screen, M.PANEL_LINE, box, 1, border_radius=12)

        y = box.y + 12
        screen.blit(self.F_SML.render("演算者", True, M.TEXT_MUTE),
                    (box.x + 14, y))
        y += 24

        bar = pygame.Rect(box.x + 14, y, box.w - 28, 14)
        pygame.draw.rect(screen, (238, 236, 230), bar, border_radius=7)
        p = self.player
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
        y += 22
        screen.blit(self.F_SML.render("牌库 %d 张" % len(p.deck), True, M.TEXT_MUTE),
                    (box.x + 14, y))

        # 最近的事件日志
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
        screen.blit(msg, msg.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 30)))
        sub = self.F_SML.render("按 R 重新开始　·　ESC 退出", True, M.TEXT_MUTE)
        screen.blit(sub, sub.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 30)))


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
                    elif ev.key == pygame.K_ESCAPE:
                        running = False
                continue

            r = game.handle(ev, mouse)
            if r == "quit":
                running = False
                break

        game.update(dt)
        game.draw(screen, mouse, t_ms)
        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
