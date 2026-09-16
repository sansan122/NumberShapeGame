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
import char_art
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

# ---- 战斗背景（渐变 + 装饰，纯代码绘制，无外部贴图）----
BG_TOP      = (240, 244, 250)   # 背景渐变：顶部偏冷蓝
BG_BOT      = (248, 244, 238)   # 底部偏暖米
FLOOR       = (226, 232, 240)   # 地面 / 地平线
DECO_SYMBOL = (222, 228, 238)   # 漂浮数学符号（淡，不抢字）
DECO_LINE   = (234, 238, 246)   # 背景网格 / 函数曲线（比符号更淡）
DECO_GRAPH  = (228, 234, 244)   # 几何图形描边
DECO_FORMULA= (210, 216, 230)   # 公式文字（最淡可读层）
GLOW_ALLY   = (200, 224, 248)   # 玩家头像外圈光晕
GLOW_FOE    = (248, 216, 216)   # 敌人头像外圈光晕
BATTLE_LINE = (232, 236, 244)   # 中央对决区底衬

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
        # 玩家立绘动画（无素材的角色 has_art=False，draw 会退回符号占位）
        self.p_anim = char_art.get_char_art(player.char_id)

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
        self.BTN_END = pygame.Rect(1112, 545, 160, 56)
        self.BTN_SUBMIT = pygame.Rect(560, 492, 160, 46)
        self.QUIZ_BOX = pygame.Rect(380, 300, 520, 290)

        # ---- 舞台锚点（杀戮尖塔式：角色立于场地左右，血条画在脚边）----
        self.P_X, self.P_FOOT = 250, 486      # 玩家：站位 / 脚底
        self.P_SYM_CY = 360                   # 无立绘时占位圆的圆心
        self.E_X = 1000                       # 敌人站位
        # 敌人体型随档次变大（底边统一落在 y=435 的「地面」上）
        self.E_R = {"battle": 78, "elite": 88, "boss": 100}.get(self.kind, 84)
        self.E_CY = 435 - self.E_R

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
            self.p_anim.play("attack")     # 打出伤害 -> 播攻击动作
            self.log.insert(0, "造成 %d 点伤害" % actual)

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
            if actual > 0:
                self.p_anim.play("hit")    # 真的挨了打 -> 播受击动作
                self.log.insert(0, "敌人攻击，造成 %d 点伤害" % actual)
            else:
                self.log.insert(0, "敌人攻击，被格挡挡下了")
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
        # 推进玩家立绘动画（dt 是秒，帧时长是毫秒）
        self.p_anim.tick(dt * 1000.0)
        # 敌人回合的自动推进
        if self.phase == "enemy" and not self.done:
            self._enemy_t = getattr(self, "_enemy_t", 0) + dt
            if self._enemy_t > 0.55:
                self._enemy_t = 0
                self.enemy_act()

    # ==================== 绘制 ====================
    def layout_hand(self):
        """计算手牌位置。牌多时向中间叠起来（像杀戮尖塔那样互相叠压），
        给左右两角的能量球 / 牌堆图标让位。"""
        n = len(self.hand)
        if n == 0:
            return
        gap = 16
        total = n * CARD_W + (n - 1) * gap
        if total > 940:
            total = 940
            # 间距算成负数 -> 卡牌左右叠压；后画的压在先画的上面
            gap = (940 - n * CARD_W) / max(1, n - 1)
        x0 = WIDTH // 2 - total // 2
        y0 = HEIGHT - CARD_H - 26
        for i, c in enumerate(self.hand):
            c.rect = pygame.Rect(int(x0 + i * (CARD_W + gap)), y0, CARD_W, CARD_H)

    # ==================== 背景（美术布置） ====================
    def draw_backdrop(self, screen, t_ms):
        """战斗背景：垂直渐变 + 地面线 + 漂浮数学符号。

        全部用代码画（不依赖贴图），因为项目是「免安装单 exe」，
        带资源文件会很麻烦。渐变方向：顶部偏冷蓝、底部偏暖米，
        营造「塔内由冷转暖」的空间纵深感。
        """
        # 1) 垂直渐变（逐行插值，比一整块纯色有层次）
        for y in range(HEIGHT):
            t = y / max(1, HEIGHT - 1)
            r = int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t)
            g = int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t)
            b = int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t)
            pygame.draw.line(screen, (r, g, b), (0, y), (WIDTH, y))

        # 2) 地面：底部一条浅色地平线，把手牌区「托」起来
        pygame.draw.rect(screen, FLOOR, (0, HEIGHT - CARD_H - 52, WIDTH, CARD_H + 52))
        pygame.draw.line(screen, (210, 217, 228),
                         (0, HEIGHT - CARD_H - 52), (WIDTH, HEIGHT - CARD_H - 52), 2)

        # 3) 数学装饰：坐标网格 / 函数曲线 / 几何图形 / 公式（都在前景之下）
        self.draw_math_decor(screen)

        # 4) 漂浮的数学符号（半透明，慢速上下漂移，呼应「数与形」主题）
        symbols = ["∑", "√", "π", "∞", "△", "=", "×", "∫",
                   "α", "β", "θ", "λ", "φ", "∈", "→", "≈"]
        spots = [
            (150, 120), (420, 90), (700, 130), (980, 100),
            (300, 210), (620, 200), (900, 210), (1180, 170),
            (80, 320), (1150, 340), (540, 70), (1080, 60),
            (240, 90), (860, 330), (60, 200), (1220, 250),
        ]
        big = E.load_font(64)
        for i, (sym, (sx, sy)) in enumerate(zip(symbols, spots)):
            # 用 t_ms 做正弦漂移，每个符号相位/幅度不同，看起来是「漂浮」而非固定
            phase = i * 0.7
            amp = 6 + (i % 3) * 3
            dy = int(amp * math.sin(t_ms / 1400.0 + phase))
            # 半透明：画到一张带 alpha 的临时表面再 blit
            s = big.render(sym, True, DECO_SYMBOL)
            s.set_alpha(90)
            screen.blit(s, s.get_rect(center=(sx, sy + dy)))

    def draw_math_decor(self, screen):
        """在渐变背景上铺一层数学元素：网格、函数曲线、几何图形、公式。

        全部用极淡的颜色，画在玩家/敌人面板之下，只做氛围、不抢前景。
        坐标都是固定值（不引入随机抖动），保证画面稳定、可测试。

        布局约束（必须避开前景）：
          玩家面板 x70~330 / y130~380；敌人面板 x950~1210 / y130~380；
          顶部标题栏 y0~52；中央竖线 cx=640。
        可见区 = 顶部横带 y60~125 + 中央区 x340~940（y60~470）。
        """
        # ---- 3.1 坐标网格：淡色横竖细线，像坐标纸 ----
        # 只在中央可见区铺网格，避开左右面板
        gy0, gy1 = 70, 470
        for gx in range(360, 940, 90):
            pygame.draw.line(screen, DECO_LINE, (gx, gy0), (gx, gy1), 1)
        for gy in range(gy0, gy1, 60):
            pygame.draw.line(screen, DECO_LINE, (340, gy), (930, gy), 1)

        # ---- 3.2 函数曲线：正弦波 + 抛物线，用折线绘制 ----
        # 正弦波（中央区左半，起伏平缓，不压到面板）
        pts = []
        for x in range(360, 560):
            y = 150 + int(22 * math.sin((x - 360) / 32.0))
            pts.append((x, y))
        if len(pts) > 1:
            pygame.draw.lines(screen, DECO_GRAPH, False, pts, 2)

        # 抛物线（中央区右半，开口朝上）
        pts = []
        for x in range(720, 920):
            t = (x - 820) / 100.0
            y = 180 + int(90 * t * t)
            pts.append((x, y))
        if len(pts) > 1:
            pygame.draw.lines(screen, DECO_GRAPH, False, pts, 2)

        # ---- 3.3 几何图形（描边，呼应「形」）----
        # 圆（顶部横带，靠左）
        pygame.draw.circle(screen, DECO_GRAPH, (430, 90), 26, 2)
        # 正方形（中央区下段）
        sq = pygame.Rect(500, 320, 38, 38)
        pygame.draw.rect(screen, DECO_GRAPH, sq, 2)
        # 三角形（中央区右段）
        pygame.draw.polygon(screen, DECO_GRAPH,
                            [(880, 330), (920, 330), (900, 298)], 2)
        # 同心圆（中央区左段）
        pygame.draw.circle(screen, DECO_GRAPH, (380, 300), 28, 2)
        pygame.draw.circle(screen, DECO_GRAPH, (380, 300), 16, 1)

        # ---- 3.4 公式（小字，最淡可读层）----
        formulas = [
            "E = mc²", "a² + b² = c²", "πr²", "y = f(x)",
            "√2", "lim", "Σ", "d/dx",
        ]
        fpos = [
            (420, 62), (830, 62), (660, 96), (560, 210),
            (720, 380), (480, 430), (820, 430), (380, 200),
        ]
        f = E.load_font(22)
        for txt, (fx, fy) in zip(formulas, fpos):
            s = f.render(txt, True, DECO_FORMULA)
            s.set_alpha(110)
            screen.blit(s, s.get_rect(center=(fx, fy)))

    def draw_battle_stage(self, screen, t_ms):
        """玩家和敌人之间的「对决区」：一条淡色中线 + 呼吸光点。

        把原本空荡荡的中央填上一点存在感，又不抢注意力。
        """
        # 中央淡色竖线，像对战场地的分界
        cx = WIDTH // 2
        pygame.draw.line(screen, BATTLE_LINE, (cx, 80), (cx, 430), 2)

        # 呼吸的「对决」光点，画在玩家与敌人之间的中点
        my = 300
        pulse = 3 + int(2 * (1 + math.sin(t_ms / 500.0)))
        pygame.draw.circle(screen, BATTLE_LINE, (cx, my), 26)
        pygame.draw.circle(screen, (208, 214, 226), (cx, my), 14 + pulse, 2)
        pygame.draw.circle(screen, (180, 190, 208), (cx, my), 4)

    # ==================== 舞台（杀戮尖塔式布局） ====================
    def draw_stage(self, screen):
        """对峙舞台：玩家大立绘在左、敌人在右，都「站」在地面上，
        血条和格挡画在角色脚边，意图悬在敌人头顶。

        参照杀戮尖塔的战斗排版重做：场面开阔，不再用面板框住角色，
        角色体型放大到撑得起场面；名字、金币这些信息收进顶栏。
        """
        ch = self.player.char

        # ---- 左：玩家 ----
        self._ground_shadow(screen, (self.P_X, 492), 190)
        # 有立绘就画大号像素小人（高 280，脚点 y=486，站在影子上）；
        # 没素材的角色用大号符号圆占位，规格和敌人一致
        if not self.p_anim.draw(screen, (self.P_X, self.P_FOOT), 280):
            pygame.draw.circle(screen, GLOW_ALLY,
                               (self.P_X, self.P_SYM_CY), self.E_R + 10)
            pygame.draw.circle(screen, ch["color"],
                               (self.P_X, self.P_SYM_CY), self.E_R)
            pygame.draw.circle(screen, (255, 255, 255),
                               (self.P_X, self.P_SYM_CY), self.E_R, 2)
            icon = self.F_BIG.render(ch["icon"], True, (255, 255, 255))
            screen.blit(icon, icon.get_rect(center=(self.P_X, self.P_SYM_CY)))

        # 血条贴着脚边，格挡徽章在条左外侧
        self.hp_bar(screen, self.P_X, 494, self.p_hp, self.p_max_hp)
        self._block_badge(screen, (self.P_X - 122, 505), self.p_block)

        # ---- 右：敌人 ----
        # 意图框悬在头顶（下回合要干什么，提前告诉你）
        intent = {"attack": "攻击 %d" % self.e_intent_val,
                  "block": "防御 8",
                  "buff": "强化 +3"}[self.e_intent]
        icol = {"attack": RED, "block": ACCENT, "buff": PURPLE}[self.e_intent]
        isoft = {"attack": RED_SOFT, "block": ACCENT_SOFT,
                 "buff": PURPLE_SOFT}[self.e_intent]
        ibox = pygame.Rect(0, 0, 116, 34)
        ibox.center = (self.E_X, self.E_CY - self.E_R - 34)
        pygame.draw.rect(screen, isoft, ibox, border_radius=17)
        pygame.draw.rect(screen, icol, ibox, 2, border_radius=17)
        it = self.F_SML.render(intent, True, icol)
        screen.blit(it, it.get_rect(center=ibox.center))

        self._ground_shadow(screen, (self.E_X, 492), 190)
        pygame.draw.circle(screen, GLOW_FOE, (self.E_X, self.E_CY), self.E_R + 10)
        pygame.draw.circle(screen, RED, (self.E_X, self.E_CY), self.E_R)
        pygame.draw.circle(screen, (255, 255, 255),
                           (self.E_X, self.E_CY), self.E_R, 2)
        # 圆里只放名字前两个字（完整名字写在血条右侧，不占手牌区）
        en = self.F_BIG.render(self.e_name[:2], True, (255, 255, 255))
        screen.blit(en, en.get_rect(center=(self.E_X, self.E_CY)))

        self.hp_bar(screen, self.E_X, 494, self.e_hp, self.e_max_hp)
        self._block_badge(screen, (self.E_X - 122, 505), self.e_block)
        nt = self.F_SML.render(self.e_name, True, TEXT_MUTE)
        screen.blit(nt, (self.E_X + 114, 497))

    def _ground_shadow(self, screen, center, w):
        """角色脚下的一片椭圆影子，把人「钉」在地面上。"""
        r = pygame.Rect(0, 0, w, 24)
        r.center = center
        pygame.draw.ellipse(screen, (225, 227, 222), r)

    def _block_badge(self, screen, center, block):
        """格挡徽章：蓝色圆片 + 白字，画在血条外侧（有格挡才出现）。"""
        if block <= 0:
            return
        pygame.draw.circle(screen, ACCENT, center, 16)
        pygame.draw.circle(screen, (255, 255, 255), center, 16, 2)
        bl = self.F_SML.render(str(block), True, (255, 255, 255))
        screen.blit(bl, bl.get_rect(center=center))

    def draw_energy(self, screen):
        """左下角能量球：大圆盘 + 「当前/上限」，取代原来的一排小圆点。"""
        cx, cy, r = 84, 588, 40
        pygame.draw.circle(screen, AMBER_SOFT, (cx, cy), r + 6)
        pygame.draw.circle(screen, AMBER, (cx, cy), r)
        pygame.draw.circle(screen, (255, 255, 255), (cx, cy), r, 2)
        txt = "%d/%d" % (self.p_energy, self.p_max_energy)
        sh = self.F_MID.render(txt, True, (46, 42, 38))
        wt = self.F_MID.render(txt, True, (255, 255, 255))
        screen.blit(sh, sh.get_rect(center=(cx + 1, cy + 1)))
        screen.blit(wt, wt.get_rect(center=(cx, cy)))

    def draw_pile(self, screen, cx, cy, count):
        """角落的牌堆图标：两张错开的小卡 + 琥珀色数量角标。"""
        for dx, dy in ((4, 4), (0, 0)):
            r = pygame.Rect(cx - 17 + dx, cy - 23 + dy, 34, 46)
            pygame.draw.rect(screen, CARD_FACE, r, border_radius=6)
            pygame.draw.rect(screen, PANEL_LINE, r, 1, border_radius=6)
        pygame.draw.circle(screen, AMBER, (cx + 16, cy + 20), 13)
        pygame.draw.circle(screen, (255, 255, 255), (cx + 16, cy + 20), 13, 1)
        num = self.F_SML.render(str(count), True, (255, 255, 255))
        screen.blit(num, num.get_rect(center=(cx + 16, cy + 20)))

    def draw(self, screen, mouse, t_ms):
        screen.fill(BG)
        self.draw_backdrop(screen, t_ms)
        self.draw_battle_stage(screen, t_ms)
        self.layout_hand()

        # ---------- 顶栏（角色名在左，金币 / 回合 / 牌组提示在右）----------
        top = pygame.Rect(0, 0, WIDTH, 52)
        pygame.draw.rect(screen, PANEL, top)
        pygame.draw.line(screen, PANEL_LINE, (0, 52), (WIDTH, 52))
        ch = self.player.char
        t1 = self.F_MID.render("%s · %s" % (ch["name"], ch["title"]), True, TEXT)
        screen.blit(t1, (24, 13))

        t2 = self.F_SML.render("回合 %d" % self.turn, True, TEXT_MUTE)
        screen.blit(t2, (WIDTH - 130, 18))
        hint = self.F_SML.render("D 查看牌组", True, ACCENT)
        hx = WIDTH - 130 - 24 - hint.get_width()
        screen.blit(hint, (hx, 18))
        # 金币：小硬币 + 数字（抽/弃牌堆的计数挪到了左右下角的牌堆图标上）
        gt = self.F_SML.render(str(self.player.gold), True, TEXT)
        gx = hx - 24 - gt.get_width() - 22
        pygame.draw.circle(screen, AMBER, (gx, 27), 9)
        pygame.draw.circle(screen, (255, 255, 255), (gx, 27), 9, 1)
        screen.blit(gt, (gx + 14, 18))

        # ---------- 舞台：角色立于场地左右（杀戮尖塔式布局） ----------
        self.draw_stage(screen)

        # ---------- 左下角：能量球 ----------
        self.draw_energy(screen)

        # ---------- 结束回合按钮（右下，弃牌堆上方） ----------
        if self.phase == "player" and not self.done:
            hover = self.BTN_END.collidepoint(mouse)
            col = (20, 78, 135) if hover else ACCENT
            pygame.draw.rect(screen, col, self.BTN_END, border_radius=10)
            bt = self.F_MID.render("结束回合", True, (255, 255, 255))
            screen.blit(bt, bt.get_rect(center=self.BTN_END.center))

        # ---------- 左右下角的牌堆（抽牌在左、弃牌在右，计数在角标里） ----------
        self.draw_pile(screen, 84, 672, len(self.deck))
        self.draw_pile(screen, 1196, 672, len(self.discard))

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

    def hp_bar(self, screen, cx, y, cur, mx, w=210, h=22):
        """一条血条：水平居中在 cx，顶边在 y。血量数字**压在条里面**。

        设计要点：
          · 数字放进条里 -> 不用再单独占一行文字，视觉更干净，
            也正好能把条紧贴在角色头像下面
          · 颜色随剩余比例变（绿 -> 琥珀 -> 红）—— 不读数字也知道危不危险
          · 数字画两层（深色描边 + 白字），浅色底和深色底上都看得清
        """
        cur = max(0, cur)
        mx = max(1, mx)
        ratio = min(1.0, float(cur) / mx)

        r = pygame.Rect(int(cx - w / 2), int(y), int(w), int(h))
        # 底槽（未填充部分）
        pygame.draw.rect(screen, (216, 213, 204), r, border_radius=h // 2)
        pygame.draw.rect(screen, (200, 197, 188), r, 1, border_radius=h // 2)

        inner = r.inflate(-4, -4)
        fw = int(round(inner.width * ratio))
        if ratio > 0:
            # 至少留一个圆头的宽度，否则低血量时条会缩成看不见的一点
            fw = max(fw, inner.height)
            col = ((86, 152, 46) if ratio > 0.55 else
                   (214, 148, 30) if ratio > 0.28 else
                   (196, 62, 58))
            pygame.draw.rect(screen, col,
                             pygame.Rect(inner.x, inner.y, fw, inner.height),
                             border_radius=inner.height // 2)

        txt = "%d / %d" % (cur, mx)
        shadow = self.F_SML.render(txt, True, (46, 42, 38))
        white = self.F_SML.render(txt, True, (255, 255, 255))
        c = r.center
        screen.blit(shadow, shadow.get_rect(center=(c[0] + 1, c[1] + 1)))
        screen.blit(white, white.get_rect(center=c))
