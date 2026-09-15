"""
《数与形》战斗场景
================================================
把原来 test_card.py 的「模块级主循环」重构为可被主程序调用的场景类。

用法：
    battle = BattleScene(player, enemy_kind="battle")
    while not battle.done:
        for ev in pygame.event.get():
            battle.handle(ev, mouse)
        battle.update(dt)
        battle.draw(screen, mouse, t)

结果：
    battle.result  in {"win", "lose"}   战斗结束后才有效
    battle.reward  胜利奖励（金币数）

战斗核心规则（沿用原 test_card.py）：
  - 想打出一张卡，必须先算对一道算术题
  - 算错 -> 卡牌白白进弃牌堆
"""

import math
import random

import pygame

import game_env as E
from player import Card

# ==================== 配色 ====================
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

WIDTH, HEIGHT = 1280, 720
CARD_W, CARD_H = 132, 176


# ==================== 敌人配置 ====================
ENEMY_KINDS = {
    "battle": {
        "name": "几何魔像",
        "hp": 50,
        "desc": "由最基础的多边形堆成",
        "gold": 28,
    },
    "elite": {
        "name": "方程组·三元",
        "hp": 78,
        "desc": "三个未知数互相牵制，解开一个才能动下一个",
        "gold": 55,
    },
    "boss": {
        "name": "不可解之影",
        "hp": 120,
        "desc": "它本身就是那个矛盾",
        "gold": 120,
    },
}


class BattleScene:
    """一场战斗。"""

    def __init__(self, player, enemy_kind="battle", enemy_hp_mult=1.0):
        self.player = player
        self.kind = enemy_kind
        cfg = ENEMY_KINDS.get(enemy_kind, ENEMY_KINDS["battle"])

        # ---- 玩家侧 ----
        self.p_max_hp = player.max_hp
        self.p_hp = player.hp
        self.p_block = 0
        self.p_energy = 3
        self.p_max_energy = 3
        self.p_residue = 0

        # ---- 敌人侧 ----
        self.e_name = cfg["name"]
        self.e_max_hp = int(cfg["hp"] * enemy_hp_mult)
        self.e_hp = self.e_max_hp
        self.e_block = 0
        self.e_intent = "attack"
        self.e_intent_val = 9
        self.reward_gold = cfg["gold"]

        # ---- 回合 ----
        self.turn = 1
        self.phase = "player"

        # ---- 牌 ----
        self.deck = [c.clone() for c in player.deck]
        random.shuffle(self.deck)
        self.hand = []
        self.discard = []
        self.draw_cards(5)

        # ---- 交互 ----
        self.sel_card = None
        self.pending_number = None
        self.log = ["遭遇 %s！算对才能出牌。" % self.e_name]
        self.quiz = None
        self.combo_hint = ""

        self.done = False
        self.result = None

        # ---- 遗物效果 ----
        self.extra_block_first = 0
        if player.has_relic("勾股定理"):
            self.extra_block_first = 3
        if player.has_relic("公理石"):
            # 战斗内生命上限加成由 Player 那边处理，这里不重复
            pass

        # ---- 字体 ----
        self.F_BIG = E.load_font(34)
        self.F_MID = E.load_font(22)
        self.F_SML = E.load_font(17)
        self.F_TINY = E.load_font(14)

        # ---- 布局 ----
        self.BTN_END = pygame.Rect(1080, 620, 160, 56)
        self.BTN_SUBMIT = pygame.Rect(560, 492, 160, 46)
        self.QUIZ_BOX = pygame.Rect(380, 300, 520, 290)

        self.layout_hand()  # 先算一次手牌位置，保证第一帧点得到

    # ==================== 牌库 ====================
    def draw_cards(self, n):
        """抽 n 张牌。
        注意：这个方法原来叫 draw()，会和「画一帧」的 draw(screen, mouse, t_ms)
        撞名，导致后者被覆盖 —— 所以改名成 draw_cards。"""
        for _ in range(n):
            if not self.deck:
                self.deck = self.discard[:]
                self.discard.clear()
                random.shuffle(self.deck)
            if self.deck and len(self.hand) < 8:
                self.hand.append(self.deck.pop())

    # ==================== 算术题 ====================
    def make_quiz(self, card):
        op = random.choice(["+", "×"])
        if op == "+":
            a, b = random.randint(3, 12), random.randint(3, 12)
            ans = a + b
        else:
            a, b = random.randint(2, 9), random.randint(2, 9)
            ans = a * b
        return {"a": a, "b": b, "op": op, "ans": ans, "input": "", "card": card}

    def submit_quiz(self):
        q = self.quiz
        if q is None:
            return
        try:
            got = int(q["input"]) if q["input"] else None
        except ValueError:
            got = None

        if got == q["ans"]:
            self.log.insert(0, "✓ %d %s %d = %d　算对了！"
                            % (q["a"], q["op"], q["b"], q["ans"]))
            self.resolve_card(q["card"])
        else:
            self.log.insert(0, "✗ %d %s %d = %d　算错了，卡牌失效"
                            % (q["a"], q["op"], q["b"], q["ans"]))
            # 遗物「换元法」：每回合第一次算错不消耗卡牌
            if (self.player.has_relic("换元法") and
                    not getattr(self, "_eq_used", False)):
                self._eq_used = True
                self.log.insert(0, "「换元法」生效：这张卡被留下了")
                if q["card"] in self.hand:
                    q["card"].selected = False
            else:
                if q["card"] in self.hand:
                    self.hand.remove(q["card"])
                self.discard.append(q["card"])
        self.quiz = None
        self.check_end()

    # ==================== 出牌结算 ====================
    def resolve_card(self, card):
        eff = card.effect
        bonus = 0
        if self.player.has_relic("约等号") and "dmg" in eff:
            bonus = 1

        if "dmg" in eff:
            dmg = eff["dmg"] + bonus
            actual = max(0, dmg - self.e_block)
            self.e_block = max(0, self.e_block - dmg)
            self.e_hp -= actual
            self.p_residue += 1
            self.log.insert(0, "造成 %d 点伤害（形值 +1）" % actual)

        if "block" in eff:
            gain = eff["block"]
            # 遗物「勾股定理」：本回合首次图形卡额外格挡
            if card.ctype == "shape" and self.extra_block_first > 0:
                gain += self.extra_block_first
                self.extra_block_first = 0
                self.log.insert(0, "「勾股定理」生效：+3 格挡")
            self.p_block += gain
            self.log.insert(0, "获得 %d 点格挡" % gain)

        if "draw" in eff:
            self.draw_cards(eff["draw"])
            self.log.insert(0, "抽了 %d 张牌" % eff["draw"])

        if eff.get("strip"):
            self.e_block = 0
            self.log.insert(0, "清空了敌人的格挡")

        if card in self.hand:
            self.hand.remove(card)
        self.discard.append(card)

        # 打完就要立刻结算胜负：不然把敌人打死之后
        # 战斗不会结束，还得等到「结束回合」才判胜。
        self.check_end()

    def check_end(self):
        if self.e_hp <= 0:
            self.e_hp = 0
            self.phase = "win"
            self.result = "win"
            self.done = True
            self.player.gold += self.reward_gold
            self.player.hp = max(0, self.p_hp)
            self.player.log("战斗胜利，+%d 金币" % self.reward_gold)
        elif self.p_hp <= 0:
            self.p_hp = 0
            self.phase = "lose"
            self.result = "lose"
            self.done = True
            self.player.hp = 0
            self.player.log("倒在了 %s 面前" % self.e_name)

    # ==================== 回合 ====================
    def end_turn(self):
        self.discard.extend(self.hand)
        self.hand.clear()
        self.p_block = 0
        self.phase = "enemy"

    def enemy_act(self):
        if self.e_intent == "attack":
            dmg = self.e_intent_val
            actual = max(0, dmg - self.p_block)
            self.p_block = max(0, self.p_block - dmg)
            self.p_hp -= actual
            self.log.insert(0, "敌人攻击，造成 %d 点伤害" % actual)
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
            self.p_residue = 0
            self._eq_used = False
            n = 5 + (1 if self.player.has_relic("对数尺") else 0)
            self.draw_cards(n)
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

    # ==================== 事件 ====================
    def handle(self, event, mouse):
        if self.done:
            # 结算后点任意处 / 按任意键离开
            if (event.type == pygame.MOUSEBUTTONDOWN or
                    event.type == pygame.KEYDOWN):
                return "leave"
            return None

        if event.type == pygame.KEYDOWN:
            if self.quiz is not None:
                if event.key == pygame.K_BACKSPACE:
                    self.quiz["input"] = self.quiz["input"][:-1]
                elif event.key == pygame.K_RETURN:
                    self.submit_quiz()
                elif event.unicode.isdigit() and len(self.quiz["input"]) < 4:
                    self.quiz["input"] += event.unicode
            else:
                if event.key == pygame.K_ESCAPE:
                    self.sel_card = None
                    for c in self.hand:
                        c.selected = False
            return None

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        # 答题弹窗优先
        if self.quiz is not None:
            if self.BTN_SUBMIT.collidepoint(mouse):
                self.submit_quiz()
            return None

        if self.phase == "player" and self.BTN_END.collidepoint(mouse):
            self.end_turn()
            return None

        # 手牌点击
        if self.phase == "player":
            for c in self.hand:
                if c.rect and c.rect.collidepoint(mouse):
                    if c.selected:
                        c.selected = False
                        self.sel_card = None
                        self.pending_number = None
                        return None
                    if self.p_energy < c.cost:
                        self.log.insert(0, "能量不足！")
                        return None
                    for x in self.hand:
                        x.selected = False
                    c.selected = True
                    self.sel_card = c
                    if c.ctype == "number":
                        self.pending_number = c
                        self.combo_hint = "已选数字 %d，可再点图形卡组合" % c.value
                    else:
                        self.combo_hint = ""
                    return None

            # 点空白 = 打出选中的卡
            if self.sel_card:
                card = self.sel_card
                self.p_energy -= card.cost
                self.quiz = self.make_quiz(card)
                card.selected = False
                self.sel_card = None
                self.pending_number = None
                self.combo_hint = ""
        return None

    def update(self, dt):
        # 敌人回合的自动推进
        if self.phase == "enemy" and not self.done:
            self._enemy_t = getattr(self, "_enemy_t", 0) + dt
            if self._enemy_t > 0.55:
                self._enemy_t = 0
                self.enemy_act()

    # ==================== 绘制 ====================
    def layout_hand(self):
        """计算手牌位置。"""
        n = len(self.hand)
        if n == 0:
            return
        gap = 16
        total = n * CARD_W + (n - 1) * gap
        x0 = WIDTH // 2 - total // 2
        y0 = HEIGHT - CARD_H - 26
        for i, c in enumerate(self.hand):
            c.rect = pygame.Rect(x0 + i * (CARD_W + gap), y0, CARD_W, CARD_H)

    def draw(self, screen, mouse, t_ms):
        screen.fill(BG)
        self.layout_hand()

        # ---------- 顶部 ----------
        top = pygame.Rect(0, 0, WIDTH, 52)
        pygame.draw.rect(screen, PANEL, top)
        pygame.draw.line(screen, PANEL_LINE, (0, 52), (WIDTH, 52))
        t1 = self.F_MID.render("《数与形》　卡牌战斗", True, TEXT)
        screen.blit(t1, (24, 13))
        t2 = self.F_SML.render("回合 %d" % self.turn, True, TEXT_MUTE)
        screen.blit(t2, (WIDTH - 130, 18))

        # ---------- 玩家区 ----------
        p_area = pygame.Rect(70, 130, 260, 250)
        self.panel(screen, p_area)
        pygame.draw.circle(screen, ACCENT, (200, 205), 46)
        pl = self.F_MID.render("演算者", True, (255, 255, 255))
        screen.blit(pl, pl.get_rect(center=(200, 205)))

        htxt = self.F_SML.render("生命 %d / %d" % (max(0, self.p_hp), self.p_max_hp),
                                 True, TEXT)
        screen.blit(htxt, (100, 290))
        self.bar(screen, 100, 314, 200, 14, self.p_hp, self.p_max_hp, RED,
                 (238, 236, 230))

        # 格挡
        if self.p_block > 0:
            pygame.draw.circle(screen, ACCENT, (112, 340), 16)
            bl = self.F_SML.render(str(self.p_block), True, (255, 255, 255))
            screen.blit(bl, bl.get_rect(center=(112, 340)))
        ry = self.F_SML.render("形值 %d" % self.p_residue, True, PURPLE)
        screen.blit(ry, (140, 331))

        # 能量
        en_lbl = self.F_SML.render("能量", True, TEXT_MUTE)
        screen.blit(en_lbl, (100, 356))
        for i in range(self.p_max_energy):
            cx = 150 + i * 24
            col = AMBER if i < self.p_energy else (228, 226, 218)
            pygame.draw.circle(screen, col, (cx, 364), 9)

        # ---------- 敌人区 ----------
        e_area = pygame.Rect(WIDTH - 330, 130, 260, 250)
        self.panel(screen, e_area)
        pygame.draw.circle(screen, RED, (WIDTH - 200, 205), 46)
        en = self.F_MID.render(self.e_name[:4], True, (255, 255, 255))
        screen.blit(en, en.get_rect(center=(WIDTH - 200, 205)))

        eht = self.F_SML.render("生命 %d / %d" % (max(0, self.e_hp), self.e_max_hp),
                                True, TEXT)
        screen.blit(eht, (WIDTH - 300, 290))
        self.bar(screen, WIDTH - 300, 314, 200, 14, self.e_hp, self.e_max_hp, RED,
                 (238, 236, 230))

        if self.e_block > 0:
            pygame.draw.circle(screen, ACCENT, (WIDTH - 290, 340), 16)
            bl = self.F_SML.render(str(self.e_block), True, (255, 255, 255))
            screen.blit(bl, bl.get_rect(center=(WIDTH - 290, 340)))

        intent = {"attack": "攻击 %d" % self.e_intent_val,
                  "block": "防御 8",
                  "buff": "强化 +3"}[self.e_intent]
        icol = {"attack": RED, "block": ACCENT, "buff": PURPLE}[self.e_intent]
        ii = self.F_SML.render("意图：" + intent, True, icol)
        screen.blit(ii, (WIDTH - 300, 358))

        # ---------- 战报 ----------
        lb = pygame.Rect(70, 420, 320, 250)
        self.panel(screen, lb)
        lt = self.F_SML.render("战报", True, TEXT_MUTE)
        screen.blit(lt, (lb.x + 14, lb.y + 10))
        ly = lb.y + 38
        for line in self.log[:9]:
            txt = line if len(line) <= 22 else line[:21] + "…"
            screen.blit(self.F_SML.render(txt, True, TEXT), (lb.x + 14, ly))
            ly += 22

        # ---------- 结束回合按钮 ----------
        if self.phase == "player" and not self.done:
            hover = self.BTN_END.collidepoint(mouse)
            col = (20, 78, 135) if hover else ACCENT
            pygame.draw.rect(screen, col, self.BTN_END, border_radius=10)
            bt = self.F_MID.render("结束回合", True, (255, 255, 255))
            screen.blit(bt, bt.get_rect(center=self.BTN_END.center))

        # ---------- 手牌 ----------
        for c in self.hand:
            self.draw_card(screen, c, mouse)

        # 提示（手牌顶部在 HEIGHT-CARD_H-26，这里再往上留出空隙，
        # 否则文字的降部会贴上卡牌顶端）
        if self.combo_hint:
            ht = self.F_SML.render(self.combo_hint, True, AMBER)
            screen.blit(ht, (WIDTH // 2 - ht.get_width() // 2, HEIGHT - CARD_H - 96))
        elif self.phase == "player" and not self.done:
            ht = self.F_TINY.render(
                "点卡选中 → 再点空白处打出（会先出一道题）", True, TEXT_MUTE)
            screen.blit(ht, (WIDTH // 2 - ht.get_width() // 2, HEIGHT - CARD_H - 92))

        # ---------- 答题弹窗 ----------
        if self.quiz is not None:
            self.draw_quiz(screen, mouse, t_ms)

        # ---------- 结算画面 ----------
        if self.done:
            self.draw_result(screen)

    def draw_card(self, screen, card, mouse):
        r = card.rect
        lift = 18 if card.selected else 0
        r = r.move(0, -lift)
        col = ACCENT if card.ctype == "number" else GREEN
        soft = ACCENT_SOFT if card.ctype == "number" else GREEN_SOFT
        face = CARD_SEL if card.selected else CARD_FACE
        hover = (not card.selected) and r.collidepoint(mouse)

        pygame.draw.rect(screen, SHADOW, r.move(0, 4), border_radius=10)
        pygame.draw.rect(screen, CARD_SEL if hover else face, r, border_radius=10)
        pygame.draw.rect(screen, col, r, 3, border_radius=10)

        bar = pygame.Rect(r.x, r.y, r.w, 34)
        pygame.draw.rect(screen, soft, bar, border_top_left_radius=10,
                         border_top_right_radius=10)

        pygame.draw.circle(screen, col, (r.x + 20, r.y + 17), 13)
        c_txt = self.F_SML.render(str(card.cost), True, (255, 255, 255))
        screen.blit(c_txt, c_txt.get_rect(center=(r.x + 20, r.y + 17)))

        nm = self.F_SML.render(card.name, True, TEXT)
        screen.blit(nm, nm.get_rect(center=(r.centerx + 8, r.y + 17)))

        # 类型标签
        tag = "数字" if card.ctype == "number" else "图形"
        tg = self.F_TINY.render(tag, True, col)
        screen.blit(tg, tg.get_rect(center=(r.centerx, r.y + 52)))

        # 描述
        cy = r.y + 78
        line = ""
        for ch in card.desc:
            if self.F_TINY.size(line + ch)[0] > r.w - 20:
                screen.blit(self.F_TINY.render(line, True, TEXT_MUTE),
                            (r.x + 10, cy))
                cy += 19
                line = ch
            else:
                line += ch
        if line:
            screen.blit(self.F_TINY.render(line, True, TEXT_MUTE), (r.x + 10, cy))

    def draw_quiz(self, screen, mouse, t_ms):
        veil = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 90))
        screen.blit(veil, (0, 0))

        box = self.QUIZ_BOX
        pygame.draw.rect(screen, PANEL, box, border_radius=16)
        pygame.draw.rect(screen, ACCENT, box, 3, border_radius=16)

        title = self.F_MID.render("解出这道题，卡牌才会生效", True, TEXT)
        screen.blit(title, title.get_rect(center=(box.centerx, box.y + 40)))

        q = self.quiz
        expr = self.F_BIG.render("%d %s %d =" % (q["a"], q["op"], q["b"]),
                                 True, ACCENT)
        expr_y = box.y + 100
        BLANK_W, GAP = 130, 18
        total_w = expr.get_width() + GAP + BLANK_W
        start_x = box.centerx - total_w // 2
        screen.blit(expr, (start_x, expr_y - expr.get_height() // 2))

        line_x0 = start_x + expr.get_width() + GAP
        line_x1 = line_x0 + BLANK_W
        line_y = expr_y + 34
        pygame.draw.line(screen, ACCENT, (line_x0, line_y), (line_x1, line_y), 3)

        typed = q["input"]
        cx_mid = line_x0 + BLANK_W // 2
        if typed:
            tt = self.F_BIG.render(typed, True, TEXT)
            screen.blit(tt, tt.get_rect(midbottom=(cx_mid, line_y - 4)))
            if (t_ms // 500) % 2 == 0:
                cur_x = cx_mid + tt.get_width() // 2 + 8
                pygame.draw.line(screen, ACCENT, (cur_x, line_y - 40),
                                 (cur_x, line_y - 4), 3)
        else:
            if (t_ms // 500) % 2 == 0:
                pygame.draw.line(screen, ACCENT, (cx_mid, line_y - 40),
                                 (cx_mid, line_y - 4), 3)

        hover = self.BTN_SUBMIT.collidepoint(mouse)
        col = (20, 78, 135) if hover else ACCENT
        pygame.draw.rect(screen, col, self.BTN_SUBMIT, border_radius=10)
        sb = self.F_MID.render("提交", True, (255, 255, 255))
        screen.blit(sb, sb.get_rect(center=self.BTN_SUBMIT.center))

        hint = self.F_TINY.render("直接敲数字键输入，回车提交，退格删除",
                                  True, TEXT_MUTE)
        screen.blit(hint, hint.get_rect(center=(box.centerx, box.bottom - 22)))

    def draw_result(self, screen):
        veil = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 120))
        screen.blit(veil, (0, 0))

        box = pygame.Rect(400, 250, 480, 230)
        pygame.draw.rect(screen, PANEL, box, border_radius=16)
        edge = GREEN if self.result == "win" else RED
        pygame.draw.rect(screen, edge, box, 3, border_radius=16)

        msg = "击败了 %s" % self.e_name if self.result == "win" else "被击倒了"
        mt = self.F_BIG.render(msg, True, edge)
        screen.blit(mt, mt.get_rect(center=(box.centerx, box.y + 62)))

        if self.result == "win":
            sub = "+%d 金币" % self.reward_gold
            st = self.F_MID.render(sub, True, AMBER)
            screen.blit(st, st.get_rect(center=(box.centerx, box.y + 112)))

        tip = self.F_SML.render("点击任意处继续", True, TEXT_MUTE)
        screen.blit(tip, tip.get_rect(center=(box.centerx, box.y + 172)))

    # ==================== 绘制辅助 ====================
    def bar(self, screen, x, y, w, h, cur, mx, fill, bg_col):
        pygame.draw.rect(screen, bg_col, (x, y, w, h), border_radius=h // 2)
        if mx > 0:
            pw = int(w * max(0, cur) / mx)
            if pw > 0:
                pygame.draw.rect(screen, fill, (x, y, pw, h), border_radius=h // 2)
        pygame.draw.rect(screen, PANEL_LINE, (x, y, w, h), 1, border_radius=h // 2)

    def panel(self, screen, rect, radius=12):
        pygame.draw.rect(screen, PANEL, rect, border_radius=radius)
        pygame.draw.rect(screen, PANEL_LINE, rect, 1, border_radius=radius)
