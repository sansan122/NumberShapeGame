"""
《数与形》卡牌战斗 - 可运行原型
================================================
操作：
  1. 点击手牌选中一张卡（会浮起）
  2. 数字卡需要先「选数字」再打出：点数字卡 -> 点敌人/自己
  3. 按「结束回合」轮到敌人行动

数学机制：
  - 数字卡：打出时需要做算术题，算对才生效
  - 图形卡：提供格挡或特殊效果
  - 数形结合：数字卡 + 图形卡可以合成更强效果
"""

import math
import random
import sys

import pygame

# ==================== 基础设置 ====================
pygame.init()
WIDTH, HEIGHT = 1280, 720
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("数与形 - 卡牌战斗原型")
clock = pygame.time.Clock()

# 字体（用微软雅黑，没有就退回默认）
FONT_PATH = "C:/Windows/Fonts/msyh.ttc"
try:
    F_BIG = pygame.font.Font(FONT_PATH, 34)
    F_MID = pygame.font.Font(FONT_PATH, 22)
    F_SML = pygame.font.Font(FONT_PATH, 17)
    F_TINY = pygame.font.Font(FONT_PATH, 14)
except Exception:
    F_BIG = pygame.font.Font(None, 34)
    F_MID = pygame.font.Font(None, 22)
    F_SML = pygame.font.Font(None, 17)
    F_TINY = pygame.font.Font(None, 14)

# ==================== 配色（浅色主题）====================
BG          = (246, 245, 240)
PANEL       = (255, 255, 255)
PANEL_LINE  = (215, 213, 205)
TEXT        = (44, 44, 42)
TEXT_MUTE   = (110, 108, 102)
ACCENT      = (24, 95, 165)
ACCENT_SOFT = (230, 241, 251)
RED         = (200, 70, 70)
RED_SOFT    = (250, 236, 236)
GREEN       = (59, 109, 17)
GREEN_SOFT  = (234, 243, 222)
AMBER       = (186, 117, 23)
AMBER_SOFT  = (250, 238, 218)
PURPLE      = (83, 74, 183)
PURPLE_SOFT = (238, 237, 254)
CARD_FACE   = (255, 255, 255)
CARD_SEL    = (255, 244, 200)
SHADOW      = (228, 226, 218)

# ==================== 卡牌定义 ====================
CARD_W, CARD_H = 132, 176


class Card:
    """一张卡。type 有 number（数字卡）/ shape（图形卡）两种。"""

    def __init__(self, name, ctype, value, desc, cost=1, effect=None):
        self.name = name
        self.ctype = ctype           # number / shape
        self.value = value
        self.desc = desc
        self.cost = cost
        self.effect = effect or {}
        self.selected = False
        self.rect = pygame.Rect(0, 0, CARD_W, CARD_H)
        self.hover = False

    def draw(self, surf, x, y):
        """把手牌画在 (x, y) 位置。"""
        lift = 18 if self.selected else 0
        self.rect.topleft = (x, y - lift)

        # 选中态描边色
        if self.ctype == "number":
            base, edge = ACCENT_SOFT, ACCENT
        else:
            base, edge = GREEN_SOFT, GREEN

        face = CARD_SEL if self.selected else CARD_FACE

        # 投影
        shadow = self.rect.move(0, 4)
        pygame.draw.rect(surf, SHADOW, shadow, border_radius=10)
        # 卡面 + 边框
        pygame.draw.rect(surf, face, self.rect, border_radius=10)
        pygame.draw.rect(surf, edge, self.rect, 3, border_radius=10)
        # 顶部色条
        bar = pygame.Rect(self.rect.x, self.rect.y, self.rect.w, 34)
        pygame.draw.rect(surf, base, bar, border_top_left_radius=10,
                         border_top_right_radius=10)

        # 费用圆点
        pygame.draw.circle(surf, edge, (self.rect.x + 20, self.rect.y + 17), 13)
        c_txt = F_SML.render(str(self.cost), True, (255, 255, 255))
        surf.blit(c_txt, c_txt.get_rect(center=(self.rect.x + 20, self.rect.y + 17)))

        # 卡名
        nm = F_SML.render(self.name, True, TEXT)
        surf.blit(nm, nm.get_rect(center=(self.rect.centerx, self.rect.y + 74)))

        # 大数值（数字卡显示数字，图形卡显示符号）
        if self.ctype == "number":
            big = F_BIG.render(str(self.value), True, ACCENT)
            surf.blit(big, big.get_rect(center=(self.rect.centerx, self.rect.y + 112)))
        else:
            big = F_BIG.render("△", True, GREEN)
            surf.blit(big, big.get_rect(center=(self.rect.centerx, self.rect.y + 112)))

        # 描述（自动换行）
        wrap_text(surf, self.desc, F_TINY, TEXT_MUTE,
                  self.rect.x + 8, self.rect.y + 136, self.rect.w - 16)

        return self.rect


def wrap_text(surf, text, font, color, x, y, max_w):
    """按宽度自动换行画文字，返回下一行的 y。"""
    line = ""
    lines = []
    for ch in text:
        test = line + ch
        if font.size(test)[0] > max_w:
            lines.append(line)
            line = ch
        else:
            line = test
    if line:
        lines.append(line)
    for i, ln in enumerate(lines[:2]):   # 最多两行，避免溢出
        img = font.render(ln, True, color)
        surf.blit(img, (x, y + i * (font.get_height() + 1)))
    return y + len(lines[:2]) * (font.get_height() + 1)


# ==================== 游戏状态 ====================
class Game:
    def __init__(self):
        self.reset()

    def reset(self):
        # 玩家
        self.p_hp = 80
        self.p_max_hp = 80
        self.p_block = 0
        self.p_energy = 3
        self.p_max_energy = 3

        # 敌人
        self.e_hp = 50
        self.e_max_hp = 50
        self.e_block = 0
        self.e_intent = "attack"
        self.e_intent_val = 9

        # 回合
        self.turn = 1
        self.phase = "player"       # player / enemy / win / lose

        # 手牌
        self.hand = []
        self.deck = self.build_deck()
        self.discard = []
        random.shuffle(self.deck)
        self.draw(5)

        # 交互状态
        self.sel_card = None        # 当前选中的卡
        self.pending_number = None  # 已选中的数字（等待与图形卡结合）
        self.log = ["战斗开始！计算正确才能打出卡片。"]
        self.quiz = None            # 当前算术题 {a, b, op, ans, input, target_card}
        self.combo_hint = ""

    def build_deck(self):
        """构造初始牌组。"""
        return [
            Card("加一", "number", 3, "造成 3 点伤害", 1, {"dmg": 3}),
            Card("加一", "number", 3, "造成 3 点伤害", 1, {"dmg": 3}),
            Card("凑十", "number", 7, "造成 7 点伤害", 1, {"dmg": 7}),
            Card("凑十", "number", 7, "造成 7 点伤害", 1, {"dmg": 7}),
            Card("平方", "number", 4, "造成 4 点伤害", 1, {"dmg": 4}),
            Card("三角盾", "shape", 0, "获得 6 点格挡", 1, {"block": 6}),
            Card("三角盾", "shape", 0, "获得 6 点格挡", 1, {"block": 6}),
            Card("方阵", "shape", 0, "获得 9 点格挡", 2, {"block": 9}),
            Card("镜像", "shape", 0, "抽 2 张牌", 1, {"draw": 2}),
            Card("归零", "shape", 0, "清空敌人格挡", 1, {"strip": True}),
        ]

    def draw(self, n):
        """抽 n 张牌。"""
        for _ in range(n):
            if not self.deck:
                # 弃牌堆洗回牌库
                self.deck = self.discard[:]
                self.discard.clear()
                random.shuffle(self.deck)
            if self.deck and len(self.hand) < 8:
                self.hand.append(self.deck.pop())

    # ---------- 算术题 ----------
    def make_quiz(self, card):
        """生成一道与卡牌数值相关的算术题。"""
        ops = ["+", "×"]
        op = random.choice(ops)
        if op == "+":
            a, b = random.randint(3, 12), random.randint(3, 12)
            ans = a + b
        else:
            a, b = random.randint(2, 9), random.randint(2, 9)
            ans = a * b
        return {"a": a, "b": b, "op": op, "ans": ans,
                "input": "", "card": card}

    def submit_quiz(self):
        """提交答案，判定对错。"""
        q = self.quiz
        if q is None:
            return
        try:
            got = int(q["input"]) if q["input"] else None
        except ValueError:
            got = None

        if got == q["ans"]:
            self.log.insert(0, f"✓ {q['a']} {q['op']} {q['b']} = {q['ans']}　算对了！")
            self.resolve_card(q["card"])
        else:
            self.log.insert(0, f"✗ {q['a']} {q['op']} {q['b']} = {q['ans']}　算错了，卡牌失效")
            # 算错 = 卡牌浪费，进入弃牌堆
            if q["card"] in self.hand:
                self.hand.remove(q["card"])
            self.discard.append(q["card"])
        self.quiz = None
        self.check_end()

    # ---------- 出牌结算 ----------
    def resolve_card(self, card):
        """卡牌效果生效。"""
        eff = card.effect

        if "dmg" in eff:
            dmg = eff["dmg"]
            actual = max(0, dmg - self.e_block)
            self.e_block = max(0, self.e_block - dmg)
            self.e_hp -= actual
            self.log.insert(0, f"造成 {actual} 点伤害")

        if "block" in eff:
            self.p_block += eff["block"]
            self.log.insert(0, f"获得 {eff['block']} 点格挡")

        if "draw" in eff:
            self.draw(eff["draw"])
            self.log.insert(0, f"抽了 {eff['draw']} 张牌")

        if eff.get("strip"):
            self.e_block = 0
            self.log.insert(0, "清空了敌人的格挡")

        # 移除手牌
        if card in self.hand:
            self.hand.remove(card)
        self.discard.append(card)

    def check_end(self):
        if self.e_hp <= 0:
            self.e_hp = 0
            self.phase = "win"
        elif self.p_hp <= 0:
            self.p_hp = 0
            self.phase = "lose"

    # ---------- 回合流转 ----------
    def end_turn(self):
        # 弃掉手牌
        self.discard.extend(self.hand)
        self.hand.clear()
        self.p_block = 0
        self.phase = "enemy"

    def enemy_act(self):
        """敌人行动。"""
        if self.e_intent == "attack":
            dmg = self.e_intent_val
            actual = max(0, dmg - self.p_block)
            self.p_block = max(0, self.p_block - dmg)
            self.p_hp -= actual
            self.log.insert(0, f"敌人攻击，造成 {actual} 点伤害")
        elif self.e_intent == "block":
            self.e_block += 8
            self.log.insert(0, "敌人获得 8 点格挡")
        elif self.e_intent == "buff":
            self.e_intent_val += 3
            self.log.insert(0, "敌人强化，下次攻击 +3")

        self.check_end()
        if self.phase == "enemy":
            self.turn += 1
            self.p_energy = self.p_max_energy
            self.p_block = 0
            self.draw(5)
            self.roll_intent()
            self.phase = "player"

    def roll_intent(self):
        r = random.random()
        if r < 0.65:
            self.e_intent = "attack"
            self.e_intent_val = random.randint(7, 12)
        elif r < 0.85:
            self.e_intent = "block"
        else:
            self.e_intent = "buff"


# ==================== 绘制辅助 ====================
def draw_bar(surf, x, y, w, h, cur, mx, fill, bg_col):
    """画血条。"""
    pygame.draw.rect(surf, bg_col, (x, y, w, h), border_radius=h // 2)
    if mx > 0:
        pw = int(w * max(0, cur) / mx)
        if pw > 0:
            pygame.draw.rect(surf, fill, (x, y, pw, h), border_radius=h // 2)
    pygame.draw.rect(surf, PANEL_LINE, (x, y, w, h), 1, border_radius=h // 2)


def draw_panel(surf, rect, radius=12):
    pygame.draw.rect(surf, PANEL, rect, border_radius=radius)
    pygame.draw.rect(surf, PANEL_LINE, rect, 1, border_radius=radius)


# ==================== 主循环 ====================
game = Game()
running = True

BTN_END = pygame.Rect(1080, 620, 160, 56)
BTN_SUBMIT = pygame.Rect(560, 492, 160, 46)
QUIZ_BOX = pygame.Rect(380, 300, 520, 290)

while running:
    mouse = pygame.mouse.get_pos()

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.KEYDOWN:
            # 答题时接收数字键盘输入
            if game.quiz is not None:
                if event.key == pygame.K_BACKSPACE:
                    game.quiz["input"] = game.quiz["input"][:-1]
                elif event.key == pygame.K_RETURN:
                    game.submit_quiz()
                elif event.unicode.isdigit() and len(game.quiz["input"]) < 4:
                    game.quiz["input"] += event.unicode
            else:
                if event.key == pygame.K_ESCAPE:
                    game.sel_card = None
                    for c in game.hand:
                        c.selected = False
                if event.key == pygame.K_r and game.phase in ("win", "lose"):
                    game.reset()

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # ------- 答题弹窗优先 -------
            if game.quiz is not None:
                if BTN_SUBMIT.collidepoint(mouse):
                    game.submit_quiz()
                continue

            # ------- 结束回合 -------
            if game.phase == "player" and BTN_END.collidepoint(mouse):
                game.end_turn()
                continue

            # ------- 结算完毕，点任意处重开 -------
            if game.phase in ("win", "lose"):
                game.reset()
                continue

            # ------- 手牌点击 -------
            if game.phase == "player":
                clicked = False
                for c in game.hand:
                    if c.rect.collidepoint(mouse):
                        clicked = True
                        # 再点同一张 = 取消
                        if c.selected:
                            c.selected = False
                            game.sel_card = None
                            game.pending_number = None
                            break

                        # 检查能量
                        if game.p_energy < c.cost:
                            game.log.insert(0, "能量不足！")
                            break

                        for x in game.hand:
                            x.selected = False
                        c.selected = True
                        game.sel_card = c

                        if c.ctype == "number":
                            game.pending_number = c
                            game.combo_hint = f"已选数字 {c.value}，可再点图形卡组合"
                        else:
                            game.combo_hint = ""
                        break

                if clicked:
                    continue

                # ------- 点击空白 = 打出选中的卡 -------
                if game.sel_card:
                    card = game.sel_card
                    game.p_energy -= card.cost
                    # 出牌前先答题
                    game.quiz = game.make_quiz(card)
                    card.selected = False
                    game.sel_card = None
                    game.pending_number = None
                    game.combo_hint = ""

    # ==================== 绘制 ====================
    screen.fill(BG)

    # ---------- 顶部信息 ----------
    top = pygame.Rect(0, 0, WIDTH, 52)
    pygame.draw.rect(screen, PANEL, top)
    pygame.draw.line(screen, PANEL_LINE, (0, 52), (WIDTH, 52))

    t1 = F_MID.render("《数与形》　卡牌战斗原型", True, TEXT)
    screen.blit(t1, (24, 13))

    t2 = F_SML.render(f"回合 {game.turn}", True, TEXT_MUTE)
    screen.blit(t2, (WIDTH - 130, 18))

    # ---------- 玩家区 ----------
    p_area = pygame.Rect(70, 130, 260, 250)
    draw_panel(screen, p_area)

    pygame.draw.circle(screen, ACCENT, (200, 205), 46)
    pl = F_MID.render("演算者", True, (255, 255, 255))
    screen.blit(pl, pl.get_rect(center=(200, 205)))

    draw_bar(screen, 100, 268, 200, 16, game.p_hp, game.p_max_hp, RED, RED_SOFT)
    htxt = F_SML.render(f"生命 {game.p_hp}/{game.p_max_hp}", True, TEXT)
    screen.blit(htxt, (100, 290))

    # 能量球
    pygame.draw.circle(screen, AMBER, (112, 340), 22)
    et = F_MID.render(str(game.p_energy), True, (255, 255, 255))
    screen.blit(et, et.get_rect(center=(112, 340)))
    el = F_SML.render(f"能量 / {game.p_max_energy}", True, TEXT_MUTE)
    screen.blit(el, (142, 331))

    # 格挡
    if game.p_block > 0:
        bl = F_SML.render(f"格挡 {game.p_block}", True, ACCENT)
        screen.blit(bl, (142, 356))

    # ---------- 敌人区 ----------
    e_area = pygame.Rect(950, 130, 260, 250)
    draw_panel(screen, e_area)

    pygame.draw.rect(screen, RED, (1010, 168, 140, 120), border_radius=12)
    en = F_MID.render("几何魔像", True, (255, 255, 255))
    screen.blit(en, en.get_rect(center=(1080, 228)))

    draw_bar(screen, 980, 300, 200, 16, game.e_hp, game.e_max_hp, RED, RED_SOFT)
    eht = F_SML.render(f"生命 {game.e_hp}/{game.e_max_hp}", True, TEXT)
    screen.blit(eht, (980, 322))

    # 敌人意图
    if game.e_intent == "attack":
        itxt, icol = f"意图：攻击 {game.e_intent_val}", RED
    elif game.e_intent == "block":
        itxt, icol = "意图：格挡", ACCENT
    else:
        itxt, icol = "意图：强化", AMBER
    ii = F_SML.render(itxt, True, icol)
    screen.blit(ii, (980, 348))

    if game.e_block > 0:
        eb = F_SML.render(f"格挡 {game.e_block}", True, ACCENT)
        screen.blit(eb, (1140, 348))

    # ---------- 手牌区 ----------
    hand_rect = pygame.Rect(60, 520, 900, 190)
    draw_panel(screen, hand_rect)

    n = len(game.hand)
    if n:
        total_w = n * CARD_W + (n - 1) * 14
        start_x = hand_rect.x + (hand_rect.w - total_w) // 2
        for i, c in enumerate(game.hand):
            c.draw(screen, start_x + i * (CARD_W + 14), hand_rect.y + 8)

    # 组合提示
    if game.combo_hint:
        ch = F_SML.render(game.combo_hint, True, GREEN)
        screen.blit(ch, (75, 500))

    # ---------- 结束回合按钮 ----------
    if game.phase == "player":
        hover = BTN_END.collidepoint(mouse)
        col = (86, 158, 86) if hover else GREEN
        pygame.draw.rect(screen, col, BTN_END, border_radius=10)
        bt = F_MID.render("结束回合", True, (255, 255, 255))
        screen.blit(bt, bt.get_rect(center=BTN_END.center))
    elif game.phase == "enemy":
        et2 = F_MID.render("敌人行动中…", True, RED)
        screen.blit(et2, et2.get_rect(center=BTN_END.center))

    # ---------- 底部提示 ----------
    tip = F_SML.render(
        "操作：点手牌选中 → 再点任意空白处打出 → 输入算式答案 → 回车提交",
        True, TEXT_MUTE)
    screen.blit(tip, (24, HEIGHT - 30))

    # ---------- 答题弹窗（最上层）----------
    if game.quiz is not None:
        veil = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 90))
        screen.blit(veil, (0, 0))

        pygame.draw.rect(screen, PANEL, QUIZ_BOX, border_radius=16)
        pygame.draw.rect(screen, ACCENT, QUIZ_BOX, 3, border_radius=16)

        title = F_MID.render("解出这道题，卡牌才会生效", True, TEXT)
        screen.blit(title, title.get_rect(center=(QUIZ_BOX.centerx, QUIZ_BOX.y + 40)))

        q = game.quiz
        expr = F_BIG.render(f"{q['a']} {q['op']} {q['b']} =", True, ACCENT)
        expr_y = QUIZ_BOX.y + 100

        # 算式整体居中：文字 + 间距 + 下划线填空区
        BLANK_W = 130            # 下划线长度
        GAP = 18                 # 等号与下划线之间的间距
        total_w = expr.get_width() + GAP + BLANK_W
        start_x = QUIZ_BOX.centerx - total_w // 2

        screen.blit(expr, (start_x, expr_y - expr.get_height() // 2))

        # ---- 下划线（填空线）---- 离算式留足 34px，给数字腾出显示空间
        line_x0 = start_x + expr.get_width() + GAP
        line_x1 = line_x0 + BLANK_W
        line_y = expr_y + 34
        pygame.draw.line(screen, ACCENT, (line_x0, line_y), (line_x1, line_y), 3)

        # ---- 输入的数字显示在下划线上方 ----
        typed = q["input"]
        cx_mid = line_x0 + BLANK_W // 2
        if typed:
            t = F_BIG.render(typed, True, TEXT)
            # 数字底边紧贴下划线上方 4px
            screen.blit(t, t.get_rect(midbottom=(cx_mid, line_y - 4)))
            # 光标紧跟数字右侧（闪烁）
            if (pygame.time.get_ticks() // 500) % 2 == 0:
                cur_x = cx_mid + t.get_width() // 2 + 8
                pygame.draw.line(screen, ACCENT, (cur_x, line_y - 40),
                                 (cur_x, line_y - 4), 3)
        else:
            # 空值时给个闪烁光标提示可以输入
            if (pygame.time.get_ticks() // 500) % 2 == 0:
                pygame.draw.line(screen, ACCENT, (cx_mid, line_y - 40),
                                 (cx_mid, line_y - 4), 3)

        # 提交按钮
        hover = BTN_SUBMIT.collidepoint(mouse)
        col = (20, 78, 135) if hover else ACCENT
        pygame.draw.rect(screen, col, BTN_SUBMIT, border_radius=10)
        sb = F_MID.render("提交", True, (255, 255, 255))
        screen.blit(sb, sb.get_rect(center=BTN_SUBMIT.center))

        hint = F_TINY.render("直接敲数字键输入，回车提交，退格删除", True, TEXT_MUTE)
        screen.blit(hint, hint.get_rect(center=(QUIZ_BOX.centerx, QUIZ_BOX.bottom - 22)))

    # ---------- 胜负画面 ----------
    if game.phase in ("win", "lose"):
        veil = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 120))
        screen.blit(veil, (0, 0))

        box = pygame.Rect(400, 260, 480, 200)
        pygame.draw.rect(screen, PANEL, box, border_radius=16)
        edge = GREEN if game.phase == "win" else RED
        pygame.draw.rect(screen, edge, box, 3, border_radius=16)

        msg = "公理暂时稳固了" if game.phase == "win" else "被不可解吞没"
        mt = F_BIG.render(msg, True, edge)
        screen.blit(mt, mt.get_rect(center=(box.centerx, box.y + 68)))

        sub = F_SML.render("点击任意处，或按 R 重新开始", True, TEXT_MUTE)
        screen.blit(sub, sub.get_rect(center=(box.centerx, box.y + 128)))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()
