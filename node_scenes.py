"""
《数与形》节点内容面板
================================================
地图上点击一个节点之后，进入对应的内容：

  rest     休整点  —— 回血 or 强化一张卡
  shop     商店    —— 用金币买卡 / 移除卡
  event    事件    —— 三选一抉择
  treasure 宝箱    —— 直接获得一件遗物

战斗节点（battle / elite / boss）由 battle_scene.py 负责，
这里不处理。

设计原则：每个面板都是一个自己的小状态机，接口统一：
    panel = SomePanel(player)      # player 是共享的玩家状态
    panel.handle(event, mouse)     # 返回 None 表示还没结束，返回 str 表示结果
    panel.draw(screen, mouse, t)
    panel.done -> bool

结果字符串：
    "leave"   正常离开，回到地图
"""

import math
import random

import pygame

import game_env as E

# ==================== 配色（与地图/战斗统一）====================
BG          = (246, 245, 240)
PANEL       = (255, 255, 255)
PANEL_LINE  = (215, 213, 205)
TEXT        = (44, 44, 42)
TEXT_MUTE   = (110, 108, 102)
TEXT_FAINT  = (170, 168, 160)
ACCENT      = (24, 95, 165)
ACCENT_SOFT = (230, 241, 251)
GOLD        = (196, 148, 30)
GOLD_SOFT   = (253, 246, 226)
RED         = (200, 70, 70)
RED_SOFT    = (250, 236, 236)
GREEN       = (59, 109, 17)
GREEN_SOFT  = (234, 243, 222)
PURPLE      = (83, 74, 183)
BORDER_SEL  = (24, 95, 165)

WIDTH, HEIGHT = 1280, 720


# ==================== 卡片池（商店/宝箱用）====================
# 与 test_card.py 的 build_deck 保持同一套命名风格
CARD_POOL = [
    ("加一",   "number", 3, "造成 3 点伤害",   1, {"dmg": 3}),
    ("凑十",   "number", 7, "造成 7 点伤害",   1, {"dmg": 7}),
    ("平方",   "number", 4, "造成 4 点伤害",   1, {"dmg": 4}),
    ("开方",   "number", 6, "造成 6 点伤害",   2, {"dmg": 6}),
    ("三角盾", "shape",  0, "获得 6 点格挡",   1, {"block": 6}),
    ("方阵",   "shape",  0, "获得 9 点格挡",   2, {"block": 9}),
    ("镜像",   "shape",  0, "抽 2 张牌",       1, {"draw": 2}),
    ("归零",   "shape",  0, "清空敌人格挡",    1, {"strip": True}),
]

RELIC_POOL = [
    ("勾股定理", "每回合首次打出图形卡，额外获得 3 点格挡"),
    ("质数筛",   "战斗开始时，从牌库移除 1 张最弱的卡"),
    ("换元法",   "每回合第一次算错不消耗卡牌"),
    ("对数尺",   "每回合多抽 1 张牌"),
    ("约等号",   "所有『造成伤害』的卡 +1 伤害"),
    ("公理石",   "最大生命 +12"),
]


def _card_color(ctype):
    return ACCENT if ctype == "number" else GREEN


# ==================== 面板基类 ====================
class Panel:
    """所有节点面板的基类。"""

    #: 面板标题
    title = "节点"
    #: 顶部副标题
    subtitle = ""

    def __init__(self, player):
        self.player = player
        self.done = False
        self.result = None          # None / "leave"
        self.msg = ""               # 底部提示
        self.F_BIG = E.load_font(30)
        self.F_MID = E.load_font(21)
        self.F_SML = E.load_font(16)
        self.F_TINY = E.load_font(14)

    # ---- 子类覆盖 ----
    def handle(self, event, mouse):
        """处理事件。子类覆盖。"""
        return None

    def draw_body(self, screen, mouse, t):
        """画面板主体。子类必须覆盖。"""
        raise NotImplementedError

    # ---- 通用 ----
    def finish(self, result="leave"):
        self.done = True
        self.result = result
        return result

    def draw(self, screen, mouse, t):
        screen.fill(BG)
        self.draw_header(screen)
        self.draw_body(screen, mouse, t)
        self.draw_footer(screen)

    def draw_header(self, screen):
        top = pygame.Rect(0, 0, WIDTH, 96)
        pygame.draw.rect(screen, PANEL, top)
        pygame.draw.line(screen, PANEL_LINE, (0, 96), (WIDTH, 96))

        t1 = self.F_BIG.render(self.title, True, TEXT)
        screen.blit(t1, (32, 20))

        if self.subtitle:
            t2 = self.F_SML.render(self.subtitle, True, TEXT_MUTE)
            screen.blit(t2, (32 + t1.get_width() + 18, 32))

        # 右侧玩家状态
        hp = "%d / %d" % (self.player.hp, self.player.max_hp)
        self.draw_stat(screen, WIDTH - 330, 26, "生命", hp, RED)
        self.draw_stat(screen, WIDTH - 220, 26, "金币", str(self.player.gold), GOLD)
        self.draw_stat(screen, WIDTH - 110, 26, "遗物",
                       str(len(self.player.relics)), PURPLE)

    def draw_stat(self, screen, x, y, label, value, color):
        lb = self.F_TINY.render(label, True, TEXT_MUTE)
        screen.blit(lb, (x, y))
        vb = self.F_MID.render(value, True, color)
        screen.blit(vb, (x, y + 18))

    def draw_footer(self, screen):
        if self.msg:
            m = self.F_SML.render(self.msg, True, TEXT_MUTE)
            screen.blit(m, m.get_rect(center=(WIDTH // 2, HEIGHT - 34)))


# ==================== 休整点 ====================
class RestPanel(Panel):
    title = "休整点"
    subtitle = "在塔身的裂隙里喘口气"

    def __init__(self, player):
        super().__init__(player)
        self.mode = "menu"          # menu / pick_card
        self.cards = list(player.deck_cards())   # 可强化的卡
        self.heal_amount = int(player.max_hp * 0.30)
        self.msg = "选择一项"

        # ---- 布局固定（不要依赖 draw 的副作用）----
        self.btn_heal = pygame.Rect(WIDTH // 2 - 480, 220, 420, 220)
        self.btn_upgrade = pygame.Rect(WIDTH // 2 + 60, 220, 420, 220)
        self.btn_back = pygame.Rect(32, HEIGHT - 74, 130, 42)

        # 「选一张卡强化」才有卡片网格。一开始是空的，
        # 等玩家真的进了强化界面（没别的可选路径了）再排布。
        self.card_rects = []
        self.card_y = 250

    def ensure_card_layout(self):
        """进入强化界面时才排布卡片（不然第一帧就会画到屏幕外）。"""
        cw, ch, gap = 132, 176, 16
        n = max(1, len(self.cards))
        # 一行放不下就折行，别硬挤出去
        per_row = max(1, (WIDTH - 120) // (cw + gap))
        rows = max(1, (n + per_row - 1) // per_row)
        shown = min(per_row, n) if n else 1
        x0 = WIDTH // 2 - (shown * (cw + gap) - gap) // 2
        self.card_y = 200 if rows == 1 else 176
        rects = []
        for i in range(n):
            row, ci = divmod(i, per_row)
            rects.append(pygame.Rect(x0 + ci * (cw + gap),
                                     self.card_y + row * (ch + 14), cw, ch))
        self.card_rects = rects
        return rects

    def handle(self, event, mouse):
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        if self.mode == "menu":
            if self.btn_heal.collidepoint(mouse):
                before = self.player.hp
                self.player.hp = min(self.player.max_hp,
                                     self.player.hp + self.heal_amount)
                gained = self.player.hp - before
                self.player.log("休整：回复 %d 点生命" % gained)
                return self.finish()
            if self.btn_upgrade.collidepoint(mouse):
                if not self.cards:
                    self.msg = "没有可强化的卡"
                    return None
                self.mode = "pick_card"
                self.ensure_card_layout()
                self.msg = "点击一张卡来强化"
                return None

        elif self.mode == "pick_card":
            if self.btn_back.collidepoint(mouse):
                self.mode = "menu"
                self.msg = "选择一项"
                return None
            for i, c in enumerate(self.cards):
                if self.card_rects[i].collidepoint(mouse):
                    self.upgrade(c)
                    return self.finish()
        return None

    def upgrade(self, card):
        """强化一张卡：数值提升，名字加个加号。"""
        eff = card.effect
        if "dmg" in eff:
            eff["dmg"] += 3
            card.desc = "造成 %d 点伤害" % eff["dmg"]
        elif "block" in eff:
            eff["block"] += 3
            card.desc = "获得 %d 点格挡" % eff["block"]
        elif "draw" in eff:
            eff["draw"] += 1
            card.desc = "抽 %d 张牌" % eff["draw"]
        card.name = card.name + "+"
        self.player.log("强化了「%s」" % card.name)

    def draw_body(self, screen, mouse, t):
        if self.mode == "menu":
            self.draw_menu(screen, mouse)
        else:
            self.draw_pick(screen, mouse)

    def draw_menu(self, screen, mouse):
        self.draw_choice(screen, self.btn_heal, "回复生命",
                         "+%d 点生命" % self.heal_amount,
                         "把伤口盖上，继续往上", GREEN, GREEN_SOFT,
                         mouse, "=")

        self.draw_choice(screen, self.btn_upgrade, "强化一张卡",
                         "永久提升一张卡的数值",
                         "让某一步算得更锋利", ACCENT, ACCENT_SOFT,
                         mouse, "+")

    def draw_choice(self, screen, rect, title, line1, line2, color, soft,
                    mouse, icon):
        hover = rect.collidepoint(mouse)
        pygame.draw.rect(screen, soft, rect, border_radius=16)
        pygame.draw.rect(screen, color, rect, 3 if hover else 2, border_radius=16)

        # 图标
        cx, cy = rect.centerx, rect.y + 62
        pygame.draw.circle(screen, color, (cx, cy), 30)
        ic = self.F_BIG.render(icon, True, (255, 255, 255))
        screen.blit(ic, ic.get_rect(center=(cx, cy)))

        tt = self.F_MID.render(title, True, TEXT)
        screen.blit(tt, tt.get_rect(center=(rect.centerx, rect.y + 122)))

        l1 = self.F_SML.render(line1, True, color)
        screen.blit(l1, l1.get_rect(center=(rect.centerx, rect.y + 158)))
        l2 = self.F_TINY.render(line2, True, TEXT_MUTE)
        screen.blit(l2, l2.get_rect(center=(rect.centerx, rect.y + 186)))

    def draw_pick(self, screen, mouse):
        pygame.draw.rect(screen, PANEL, self.btn_back, border_radius=8)
        pygame.draw.rect(screen, PANEL_LINE, self.btn_back, 1, border_radius=8)
        bt = self.F_SML.render("返回", True, TEXT)
        screen.blit(bt, bt.get_rect(center=self.btn_back.center))

        for i, c in enumerate(self.cards):
            r = self.card_rects[i]
            hover = r.collidepoint(mouse)
            self.draw_card(screen, r, c, hover)

        # 提示放在卡片网格正下方（和底部那行 msg 分开，别叠在一起）
        tip = self.F_SML.render("点击一张卡强化它（数值 +3）", True, TEXT_MUTE)
        grid_bottom = max(r.bottom for r in self.card_rects) if self.card_rects else 400
        screen.blit(tip, tip.get_rect(center=(WIDTH // 2, grid_bottom + 30)))

    def draw_card(self, screen, r, card, hover):
        col = _card_color(card.ctype)
        lift = 10 if hover else 0
        r = r.move(0, -lift)
        pygame.draw.rect(screen, (228, 226, 218), r.move(0, 4), border_radius=10)
        pygame.draw.rect(screen, (255, 252, 240) if hover else PANEL, r,
                         border_radius=10)
        pygame.draw.rect(screen, col, r, 3, border_radius=10)

        bar = pygame.Rect(r.x, r.y, r.w, 32)
        pygame.draw.rect(screen, ACCENT_SOFT if card.ctype == "number" else GREEN_SOFT,
                         bar, border_top_left_radius=10, border_top_right_radius=10)

        nm = self.F_SML.render(card.name, True, TEXT)
        screen.blit(nm, nm.get_rect(center=(r.centerx, r.y + 17)))

        # 费用
        pygame.draw.circle(screen, col, (r.x + 18, r.y + 17), 12)
        cst = self.F_TINY.render(str(card.cost), True, (255, 255, 255))
        screen.blit(cst, cst.get_rect(center=(r.x + 18, r.y + 17)))

        # 描述
        self.draw_wrapped(screen, card.desc, self.F_SML, TEXT_MUTE,
                          r.x + 12, r.y + 52, r.w - 24)


# ==================== 商店 ====================
class ShopPanel(Panel):
    title = "商店"
    subtitle = "用金币买一点确定性"

    def __init__(self, player):
        super().__init__(player)
        self.stock = self.roll_stock()
        self.removal_price = 60
        self.msg = "点击商品购买"
        self.mode = "shop"      # shop / pick_remove

        # 布局固定下来（不要依赖 draw 的副作用，
        # 否则第一帧还没画完时点击会命中不了）
        ITEM_W, ITEM_H, GAP = 200, 240, 24
        n = len(self.stock)
        total = n * ITEM_W + (n - 1) * GAP
        x0 = WIDTH // 2 - total // 2
        self.y0 = 170
        self.item_rects = [
            pygame.Rect(x0 + i * (ITEM_W + GAP), self.y0, ITEM_W, ITEM_H)
            for i in range(n)
        ]
        by = self.y0 + ITEM_H + 34
        self.btn_remove = pygame.Rect(WIDTH // 2 - 300, by, 280, 54)
        self.btn_leave = pygame.Rect(WIDTH // 2 + 20, by, 280, 54)
        self.btn_back = pygame.Rect(32, HEIGHT - 74, 130, 42)
        self.card_rects = []

    def roll_stock(self):
        picks = random.sample(CARD_POOL, 3)
        stock = []
        for name, ctype, value, desc, cost, eff in picks:
            price = 40 + cost * 20
            stock.append({"kind": "card", "name": name, "ctype": ctype,
                          "value": value, "desc": desc, "cost": cost,
                          "effect": eff, "price": price, "sold": False})
        # 一件遗物
        rname, rdesc = random.choice(RELIC_POOL)
        stock.append({"kind": "relic", "name": rname, "desc": rdesc,
                      "price": 120, "sold": False})
        return stock

    def handle(self, event, mouse):
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        if self.mode == "pick_remove":
            if self.btn_back.collidepoint(mouse):
                self.mode = "shop"
                self.msg = "点击商品购买"
                return None
            for i, c in enumerate(self.cards):
                if self.card_rects[i].collidepoint(mouse):
                    self.player.remove_card(c)
                    self.player.gold -= self.removal_price
                    self.player.log("从牌库移除了「%s」" % c.name)
                    self.mode = "shop"
                    self.msg = "已移除「%s」" % c.name
                    return None
            return None

        # ---- 商品格子 ----
        for i, item in enumerate(self.stock):
            if self.item_rects[i].collidepoint(mouse):
                if item["sold"]:
                    self.msg = "这件已经卖掉了"
                    return None
                if self.player.gold < item["price"]:
                    self.msg = "金币不够（还差 %d）" % (item["price"] - self.player.gold)
                    return None
                self.buy(item)
                return None

        # ---- 移除卡牌服务 ----
        if self.btn_remove.collidepoint(mouse):
            if self.player.gold < self.removal_price:
                self.msg = "金币不够（还差 %d）" % (self.removal_price - self.player.gold)
                return None
            if not self.player.deck_cards():
                self.msg = "牌库是空的"
                return None
            self.mode = "pick_remove"
            # 注意：card_rects 必须在这里（点击时）算好，
            # 不能在 draw_pick 里算 —— draw 会在点击之后才跑，
            # 那样第一帧点击就会命中失败
            self.card_rects = self._layout_remove_cards() if False else self.card_rects
            self.cards = self.player.deck_cards()
            self.card_rects = self._layout_remove_cards()
            self.msg = "选择要移除的卡"
            return None

        # ---- 离开 ----
        if self.btn_leave.collidepoint(mouse):
            return self.finish()
        return None

    def buy(self, item):
        self.player.gold -= item["price"]
        item["sold"] = True
        if item["kind"] == "card":
            self.player.add_card_to_deck(
                item["name"], item["ctype"], item["value"],
                item["desc"], item["cost"], item["effect"])
            self.player.log("买下了「%s」" % item["name"])
            self.msg = "买下「%s」" % item["name"]
        else:
            self.player.relics.append(item["name"])
            self.player.log("获得了遗物「%s」" % item["name"])
            self.msg = "获得遗物「%s」" % item["name"]

    def draw_body(self, screen, mouse, t):
        if self.mode == "pick_remove":
            self.draw_pick(screen, mouse)
            return

        for i, item in enumerate(self.stock):
            r = self.item_rects[i]  # 位置已在 __init__ 里算好
            self.draw_item(screen, r, item, mouse)

        # 底部：移除服务 + 离开
        affordable = self.player.gold >= self.removal_price
        col = RED if affordable else TEXT_FAINT
        hover = self.btn_remove.collidepoint(mouse) and affordable
        pygame.draw.rect(screen, RED_SOFT if affordable else (243, 242, 238),
                         self.btn_remove, border_radius=10)
        pygame.draw.rect(screen, col, self.btn_remove, 3 if hover else 2,
                         border_radius=10)
        bt = self.F_MID.render("移除一张卡  %d" % self.removal_price, True, col)
        screen.blit(bt, bt.get_rect(center=self.btn_remove.center))

        pygame.draw.rect(screen, PANEL, self.btn_leave, border_radius=10)
        pygame.draw.rect(screen, PANEL_LINE, self.btn_leave, 2, border_radius=10)
        lt = self.F_MID.render("离开商店", True, TEXT)
        screen.blit(lt, lt.get_rect(center=self.btn_leave.center))

    def draw_item(self, screen, r, item, mouse):
        sold = item["sold"]
        can = self.player.gold >= item["price"] and not sold
        hover = r.collidepoint(mouse) and can

        if item["kind"] == "card":
            col = _card_color(item["ctype"])
        else:
            col = PURPLE

        bg = (248, 247, 242) if sold else ((255, 252, 240) if hover else PANEL)
        pygame.draw.rect(screen, bg, r, border_radius=12)
        pygame.draw.rect(screen, (222, 220, 213) if sold else col, r,
                         3 if hover else 2, border_radius=12)

        bar = pygame.Rect(r.x, r.y, r.w, 40)
        soft = (ACCENT_SOFT if item.get("ctype") == "number" else
                GREEN_SOFT if item.get("ctype") == "shape" else
                (238, 237, 254))
        pygame.draw.rect(screen, soft, bar,
                         border_top_left_radius=12, border_top_right_radius=12)

        nm = self.F_MID.render(item["name"], True,
                               TEXT_FAINT if sold else TEXT)
        screen.blit(nm, nm.get_rect(center=(r.centerx, r.y + 20)))

        # 类型标签
        tag = {"number": "数字卡", "shape": "图形卡"}.get(
            item.get("ctype"), "遗物")
        tg = self.F_TINY.render(tag, True, col)
        screen.blit(tg, tg.get_rect(center=(r.centerx, r.y + 58)))

        self.draw_wrapped(screen, item["desc"], self.F_SML,
                          TEXT_FAINT if sold else TEXT_MUTE,
                          r.x + 14, r.y + 84, r.w - 28)

        # 价格
        if sold:
            pr = self.F_MID.render("已售出", True, TEXT_FAINT)
        else:
            pr = self.F_MID.render("%d 金币" % item["price"], True,
                                   GOLD if can else RED)
        screen.blit(pr, pr.get_rect(center=(r.centerx, r.bottom - 28)))

    def _layout_remove_cards(self):
        """排布「选一张卡移除」的网格。"""
        cards = self.player.deck_cards()
        self.cards = cards
        cw, ch, gap = 110, 148, 14
        per_row = max(1, (WIDTH - 160) // (cw + gap))
        rows = max(1, (len(cards) + per_row - 1) // per_row)
        shown = min(per_row, len(cards)) if cards else 1
        x0 = WIDTH // 2 - (shown * (cw + gap) - gap) // 2
        y0 = 170
        rects = []
        for i in range(len(cards)):
            row, ci = divmod(i, per_row)
            rects.append(pygame.Rect(x0 + ci * (cw + gap),
                                     y0 + row * (ch + 22), cw, ch))
        return rects

    def draw_pick(self, screen, mouse):
        pygame.draw.rect(screen, PANEL, self.btn_back, border_radius=8)
        pygame.draw.rect(screen, PANEL_LINE, self.btn_back, 1, border_radius=8)
        bt = self.F_SML.render("返回", True, TEXT)
        screen.blit(bt, bt.get_rect(center=self.btn_back.center))

        for i, c in enumerate(self.cards):
            r = self.card_rects[i]  # 位置已在 _layout_remove_cards 里算好
            hover = r.collidepoint(mouse)
            self.draw_mini_card(screen, r, c, hover)

    def draw_mini_card(self, screen, r, card, hover):
        col = _card_color(card.ctype)
        lift = 6 if hover else 0
        r = r.move(0, -lift)
        pygame.draw.rect(screen, (228, 226, 218), r.move(0, 3), border_radius=8)
        pygame.draw.rect(screen, (255, 252, 240) if hover else PANEL, r,
                         border_radius=8)
        pygame.draw.rect(screen, col, r, 2 if not hover else 3, border_radius=8)
        nm = self.F_SML.render(card.name, True, TEXT)
        screen.blit(nm, nm.get_rect(center=(r.centerx, r.y + 18)))
        self.draw_wrapped(screen, card.desc, self.F_TINY, TEXT_MUTE,
                          r.x + 8, r.y + 40, r.w - 16)


# ==================== 事件 ====================
EVENTS = [
    {
        "title": "断裂的等式",
        "body": "墙上刻着一行等式，中间被劈开了一道缝。\n\n"
                "你伸手去摸，指尖传来轻微的震动——它还在运转。",
        "options": [
            {"label": "补上缺口", "hint": "失去 10 点生命，获得一件遗物",
             "fn": "lose_hp_gain_relic"},
            {"label": "绕过去", "hint": "什么也不发生",
             "fn": "nothing"},
            {"label": "铭记它", "hint": "最大生命 +8",
             "fn": "gain_max_hp"},
        ],
    },
    {
        "title": "未完成的证明",
        "body": "一页纸飘在半空，写满了推导，最后一行是「显然」。\n\n"
                "显然之后什么都没有。",
        "options": [
            {"label": "替它写完", "hint": "获得 40 金币，但最大生命 -6",
             "fn": "gold_cost_hp"},
            {"label": "撕掉它", "hint": "移除牌库里一张卡",
             "fn": "remove_card"},
            {"label": "折起来收好", "hint": "获得 25 金币",
             "fn": "gain_gold"},
        ],
    },
    {
        "title": "沉默的演算者",
        "body": "另一个演算者坐在台阶上，面前的算式已经算到第几千行。\n\n"
                "他抬头看你，没有说话。",
        "options": [
            {"label": "交换经验", "hint": "强化一张卡",
             "fn": "upgrade_card"},
            {"label": "分他一半补给", "hint": "失去 20 金币，最大生命 +10",
             "fn": "gold_for_maxhp"},
            {"label": "点头走过", "hint": "获得 15 金币",
             "fn": "gain_gold"},
        ],
    },
]


class EventPanel(Panel):
    title = "事件"
    subtitle = ""

    def __init__(self, player):
        super().__init__(player)
        self.ev = random.choice(EVENTS)
        self.subtitle = self.ev["title"]
        self.chosen = None
        self.msg = "选择一项"

        # 布局在 __init__ 里一次算好（不能等 draw_body，
        # 否则第一帧还没画完就点击会命中不了）
        n = len(self.ev["options"])
        bw, bh, gap = 290, 150, 30
        total = n * bw + (n - 1) * gap
        x0 = WIDTH // 2 - total // 2
        y0 = 386
        self.opt_rects = [pygame.Rect(x0 + i * (bw + gap), y0, bw, bh)
                          for i in range(n)]

    def handle(self, event, mouse):
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None
        if self.chosen is not None:
            # 已经选完，点任意处离开
            return self.finish()

        for i, opt in enumerate(self.ev["options"]):
            if self.opt_rects[i].collidepoint(mouse):
                self.apply(opt)
                return None
        return None

    def apply(self, opt):
        fn = opt["fn"]
        p = self.player
        if fn == "nothing":
            self.msg = "你只是路过。"
        elif fn == "lose_hp_gain_relic":
            p.hp = max(1, p.hp - 10)
            name, desc = random.choice(RELIC_POOL)
            p.relics.append(name)
            self.msg = "失去 10 点生命，获得遗物「%s」：%s" % (name, desc)
            p.log("事件：获得遗物「%s」" % name)
        elif fn == "gain_max_hp":
            p.max_hp += 8
            p.hp += 8
            self.msg = "最大生命 +8"
            p.log("事件：最大生命 +8")
        elif fn == "gold_cost_hp":
            p.gold += 40
            p.max_hp = max(1, p.max_hp - 6)
            p.hp = min(p.hp, p.max_hp)
            self.msg = "获得 40 金币，最大生命 -6"
            p.log("事件：+40 金币 / -6 最大生命")
        elif fn == "gain_gold":
            p.gold += 25
            self.msg = "获得 25 金币"
            p.log("事件：+25 金币")
        elif fn == "gold_for_maxhp":
            if p.gold < 20:
                self.msg = "金币不够，他摆摆手让你过去。"
            else:
                p.gold -= 20
                p.max_hp += 10
                p.hp += 10
                self.msg = "失去 20 金币，最大生命 +10"
                p.log("事件：-20 金币 / +10 最大生命")
        elif fn == "remove_card":
            cards = p.deck_cards()
            if cards:
                c = random.choice(cards)
                p.remove_card(c)
                self.msg = "移除了牌库里的「%s」" % c.name
                p.log("事件：移除「%s」" % c.name)
            else:
                self.msg = "牌库是空的，什么也没发生。"
        elif fn == "upgrade_card":
            cards = p.deck_cards()
            if cards:
                c = random.choice(cards)
                eff = c.effect
                if "dmg" in eff:
                    eff["dmg"] += 3
                    c.desc = "造成 %d 点伤害" % eff["dmg"]
                elif "block" in eff:
                    eff["block"] += 3
                    c.desc = "获得 %d 点格挡" % eff["block"]
                elif "draw" in eff:
                    eff["draw"] += 1
                    c.desc = "抽 %d 张牌" % eff["draw"]
                c.name += "+"
                self.msg = "「%s」被强化了" % c.name
                p.log("事件：强化「%s」" % c.name)
            else:
                self.msg = "牌库是空的，什么也没发生。"

        self.chosen = opt
        p.hp = max(0, min(p.hp, p.max_hp))

    def draw_body(self, screen, mouse, t):
        # 事件描述
        box = pygame.Rect(WIDTH // 2 - 460, 140, 920, 200)
        pygame.draw.rect(screen, PANEL, box, border_radius=14)
        pygame.draw.rect(screen, PANEL_LINE, box, 2, border_radius=14)

        title = self.F_BIG.render(self.ev["title"], True, ACCENT)
        screen.blit(title, (box.x + 34, box.y + 26))

        y = box.y + 74
        for line in self.ev["body"].split("\n"):
            if line:
                lb = self.F_SML.render(line, True, TEXT_MUTE)
            else:
                lb = None
            if lb:
                screen.blit(lb, (box.x + 34, y))
            y += 26

        # 选项
        self.opt_rects = []
        n = len(self.ev["options"])
        bw, bh = 290, 150
        gap = 30
        total = n * bw + (n - 1) * gap
        x0 = WIDTH // 2 - total // 2
        y0 = 386
        for i, opt in enumerate(self.ev["options"]):
            r = pygame.Rect(x0 + i * (bw + gap), y0, bw, bh)
            self.opt_rects.append(r)
            picked = (self.chosen is opt)
            hover = r.collidepoint(mouse) and self.chosen is None
            self.draw_option(screen, r, opt, hover, picked)

    def draw_option(self, screen, r, opt, hover, picked):
        if picked:
            bg, edge = GOLD_SOFT, GOLD
        elif hover:
            bg, edge = ACCENT_SOFT, ACCENT
        else:
            bg, edge = PANEL, PANEL_LINE

        pygame.draw.rect(screen, bg, r, border_radius=12)
        pygame.draw.rect(screen, edge, r, 3 if (hover or picked) else 2,
                         border_radius=12)

        lb = self.F_MID.render(opt["label"], True, TEXT)
        screen.blit(lb, lb.get_rect(center=(r.centerx, r.y + 44)))

        # 提示（自动折行）
        self.draw_wrapped(screen, opt["hint"], self.F_SML, TEXT_MUTE,
                          r.x + 20, r.y + 80, r.w - 40, center=True)

        if picked:
            tag = self.F_TINY.render("已选择", True, GOLD)
            screen.blit(tag, tag.get_rect(center=(r.centerx, r.bottom - 20)))


# ==================== 宝箱 ====================
class TreasurePanel(Panel):
    title = "宝箱"
    subtitle = "一件遗物，静静地躺在里面"

    def __init__(self, player):
        super().__init__(player)
        self.opened = False
        self.relic_name = None
        self.relic_desc = None
        self.msg = "点击宝箱打开它"
        self.box_rect = pygame.Rect(WIDTH // 2 - 120, 220, 240, 200)
        # 打开后那张卡片的矩形 + 收下按钮，一起在 __init__ 里定好
        self.result_rect = pygame.Rect(WIDTH // 2 - 300, 210, 600, 230)
        self.btn_ok = pygame.Rect(self.result_rect.centerx - 90,
                                  self.result_rect.bottom - 62, 180, 46)

    def handle(self, event, mouse):
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        if not self.opened:
            if self.box_rect.inflate(80, 60).collidepoint(mouse):
                self.open()
            return None

        if self.btn_ok.collidepoint(mouse):
            return self.finish()
        return None

    def open(self):
        self.opened = True
        name, desc = random.choice(RELIC_POOL)
        self.relic_name, self.relic_desc = name, desc
        self.player.relics.append(name)
        self.player.log("宝箱：获得遗物「%s」" % name)
        self.msg = ""

    def draw_body(self, screen, mouse, t):
        if not self.opened:
            hover = self.box_rect.inflate(80, 60).collidepoint(mouse)
            bob = math.sin(t / 400.0) * 5
            r = self.box_rect.move(0, int(bob))

            pygame.draw.rect(screen, (232, 230, 222), r.move(0, 8),
                             border_radius=14)
            pygame.draw.rect(screen, GOLD_SOFT, r, border_radius=14)
            pygame.draw.rect(screen, GOLD, r, 4 if hover else 3, border_radius=14)

            # ∑ 符号
            ic = self.F_BIG.render("∑", True, GOLD)
            screen.blit(ic, ic.get_rect(center=r.center))

            # 盖子的缝
            pygame.draw.line(screen, GOLD, (r.x + 8, r.y + 62),
                             (r.right - 8, r.y + 62), 3)

            tip = self.F_MID.render("点击打开", True, TEXT_MUTE)
            screen.blit(tip, tip.get_rect(center=(WIDTH // 2, r.bottom + 56)))
        else:
            box = self.result_rect
            pygame.draw.rect(screen, PANEL, box, border_radius=16)
            pygame.draw.rect(screen, GOLD, box, 3, border_radius=16)

            tt = self.F_BIG.render("获得遗物", True, GOLD)
            screen.blit(tt, tt.get_rect(center=(box.centerx, box.y + 48)))

            nm = self.F_BIG.render(self.relic_name, True, TEXT)
            screen.blit(nm, nm.get_rect(center=(box.centerx, box.y + 104)))

            self.draw_wrapped(screen, self.relic_desc, self.F_SML, TEXT_MUTE,
                              box.x + 40, box.y + 140, box.w - 80, center=True)

            hover = self.btn_ok.collidepoint(pygame.mouse.get_pos())
            col = (20, 78, 135) if hover else ACCENT
            pygame.draw.rect(screen, col, self.btn_ok, border_radius=10)
            bt = self.F_MID.render("收下", True, (255, 255, 255))
            screen.blit(bt, bt.get_rect(center=self.btn_ok.center))


# ==================== 通用文字折行 ====================
def draw_wrapped(screen, text, font, color, x, y, max_w, center=False):
    """把 text 按 max_w 折行画出来。返回末尾 y。"""
    lines = []
    cur = ""
    for ch in text:
        test = cur + ch
        if font.size(test)[0] > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = test
    if cur:
        lines.append(cur)

    cy = y
    for ln in lines:
        surf = font.render(ln, True, color)
        if center:
            screen.blit(surf, surf.get_rect(center=(x + max_w // 2, cy)))
        else:
            screen.blit(surf, (x, cy))
        cy += font.get_height() + 3
    return cy


Panel.draw_wrapped = staticmethod(draw_wrapped)


# ==================== 工厂 ====================
def make_panel(node_type, player):
    """按节点类型造一个面板。战斗类型返回 None（交给 battle_scene）。"""
    return {
        "rest": lambda: RestPanel(player),
        "shop": lambda: ShopPanel(player),
        "event": lambda: EventPanel(player),
        "treasure": lambda: TreasurePanel(player),
    }.get(node_type, lambda: None)()
