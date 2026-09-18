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
import sfx
# 遗物池放在 player.py —— 地图的路线代价也要发遗物，
# 放在这个模块里的话 map_scene 反过来 import 本模块，绕成一个环。
# 卡牌类型的三件套（数字/图形/运算 的主色、浅底、标签）也统一从那里取，
# 免得战斗、牌组、商店三处各写一套 `number if ... else shape`。
from player import (RELIC_POOL, roll_unowned_relic,   # noqa: F401
                    NUMBER_SPECS, SQUARE_SPEC, Card,
                    card_color, card_soft, type_label)

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
# 数字牌一个个卖：牌组里想要哪个数字就买哪个数字（数字牌的伤害就是它
# 自己，9 号牌比 1 号牌值钱得多）。0 号牌不进商店 —— 它只值一张手牌，
# 没人会花金币买。
# 「平方」也在池子里：它是唯一一张能把数字变成平方的牌（见 battle_scene），
# 但**要等第一层层主被打掉之后才进货**，见下面的 shop_pool()。
CARD_POOL = NUMBER_SPECS[1:] + [
    SQUARE_SPEC,
    ("三角盾", "shape", 0, "获得 6 点格挡",   1, {"block": 6}),
    ("方阵",   "shape", 0, "获得 9 点格挡",   2, {"block": 9}),
    ("镜像",   "shape", 0, "抽 2 张牌",       1, {"draw": 2}),
    ("归零",   "shape", 0, "清空敌人格挡",    1, {"strip": True}),
    ("反证",   "shape", 0, "获得 5 点格挡并造成 4 点伤害", 1,
     {"block": 5, "dmg": 4}),
    ("换元",   "shape", 0, "抽 1 张牌并造成 4 点伤害", 1,
     {"draw": 1, "dmg": 4}),
]


def shop_pool(player):
    """这家商店能进的货。

    平方是**第一层层主的战利品**（player.unlock_square），解锁之前不进池子 ——
    否则玩家在第一层的柜台上就能花金币买到它，「打完层主才拿到」这条
    设计线等于白设，第一层「只能靠 0~9 慢慢磨」的难度也就没了。
    解锁之后照常卖，让后面两层能补第二、第三张。
    """
    if player.has_square():
        return list(CARD_POOL)
    return [c for c in CARD_POOL if c[0] != SQUARE_SPEC[0]]

#: 遗物池已搬到 player.py（见那边的 RELIC_POOL），这里只留名字导入。


def _card_color(ctype):
    """卡牌主色（数字蓝 / 图形绿 / 运算紫），统一从 player 那份定义取。"""
    return card_color(ctype)


# ==================== 卡片网格 / 强化 / 卡面（休整点与战利品共用）====================
CARD_W, CARD_H, CARD_GAP = 132, 176, 16


def fit_grid_rects(n, cw, ch, x_gap=16, y_gap=None, top=110, bottom=None):
    """把 n 个 cw×ch 的格子排成居中的网格，**保证全部落在 top..bottom 之间**。

    牌组会越买越大 —— 光数字牌 0~9 就有十张，加上形 / 运算卡，十六七张
    是常态。所以这里不能只「折行就完事」：行数一多就整体按比例缩小
    （宽高同步缩，卡面不会变形），而不是让最后一行掉到 y=720 之外 ——
    那样玩家看得见一半、点不到，还以为是鼠标坏了。

    强化选卡（休整点 / 战利品）和商店的「移除卡牌」都走这一份实现：
    这三处以前各写了一份折行逻辑，牌组一变就各自算错行高。
    """
    if bottom is None:
        bottom = HEIGHT - 80
    y_gap = x_gap if y_gap is None else y_gap
    if n <= 0:
        return []
    per_row = max(1, (WIDTH - 120) // (cw + x_gap))
    rows = max(1, (n + per_row - 1) // per_row)
    avail = bottom - top
    h = min(ch, (avail - (rows - 1) * y_gap) // rows)
    scale = h / float(ch)
    w = int(cw * scale)
    x_gap = max(6, int(x_gap * scale))
    y_gap = max(6, int(y_gap * scale))
    shown = min(per_row, n)
    x0 = WIDTH // 2 - (shown * w + (shown - 1) * x_gap) // 2
    grid_h = rows * h + (rows - 1) * y_gap
    y0 = top + max(0, (avail - grid_h) // 2)      # 在可用带里竖直居中
    return [pygame.Rect(x0 + (i % per_row) * (w + x_gap),
                        y0 + (i // per_row) * (h + y_gap), w, h)
            for i in range(n)]


def card_grid_rects(n):
    """强化选卡用的网格（132×176 的大卡）。"""
    return fit_grid_rects(n, CARD_W, CARD_H, CARD_GAP, 14)


def upgrade_card(player, card):
    """强化一张卡：数值 +3 / 抽牌 +1，名字加个加号。

    返回一句说明（"伤害 +3" 之类）；这张卡没有任何可强化的数值时
    （比如「归零」只有清格挡）返回 ""，而且**不会**给它加加号 ——
    以前是先无脑加个 "+" 再什么都不改，玩家白花一次强化机会。
    """
    eff = card.effect
    if "dmg" in eff:
        eff["dmg"] += 3
        card.desc = "造成 %d 点伤害" % eff["dmg"]
        what = "伤害 +3"
    elif "block" in eff:
        eff["block"] += 3
        card.desc = "获得 %d 点格挡" % eff["block"]
        what = "格挡 +3"
    elif "draw" in eff:
        eff["draw"] += 1
        card.desc = "抽 %d 张牌" % eff["draw"]
        what = "抽牌 +1"
    else:
        return ""
    card.name = card.name + "+"
    player.log("强化了「%s」（%s）" % (card.name, what))
    return what


def draw_card_tile(screen, r, card, hover, f_sml, f_tiny):
    """画一张「可点选」的卡（强化 / 移除界面用）。

    纵向尺寸按 r.h 算比例 —— 牌组大的时候 fit_grid_rects() 会整体缩小
    卡片，这里要是还写死 32 / 52 这些数字，缩下来的卡就会被字画花。
    """
    col = _card_color(card.ctype)
    r = r.move(0, -10 if hover else 0)
    pygame.draw.rect(screen, (228, 226, 218), r.move(0, 4), border_radius=10)
    pygame.draw.rect(screen, (255, 252, 240) if hover else PANEL, r,
                     border_radius=10)
    pygame.draw.rect(screen, col, r, 3, border_radius=10)

    bar_h = max(20, int(r.h * 0.18))
    bar = pygame.Rect(r.x, r.y, r.w, bar_h)
    pygame.draw.rect(screen, card_soft(card.ctype), bar,
                     border_top_left_radius=10, border_top_right_radius=10)

    nm = f_sml.render(card.name, True, TEXT)
    screen.blit(nm, nm.get_rect(center=(r.centerx, r.y + bar_h // 2)))

    # 费用
    cr = max(8, int(bar_h * 0.38))
    ccx = r.x + cr + 6
    pygame.draw.circle(screen, col, (ccx, r.y + bar_h // 2), cr)
    cst = f_tiny.render(str(card.cost), True, (255, 255, 255))
    screen.blit(cst, cst.get_rect(center=(ccx, r.y + bar_h // 2)))

    # 说明文字：卡片被缩得很小的时候就别画了，挤成一团比不画更难看
    if r.h >= 130:
        draw_wrapped(screen, card.desc, f_sml, TEXT_MUTE, r.x + 12,
                     r.y + bar_h + 16, r.w - 24)


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

    def ensure_card_layout(self):
        """进入强化界面时才排布卡片（不然第一帧就会画到屏幕外）。

        布局本身交给 card_grid_rects() —— 早先这里抄了一份「折行」的
        简化版，牌组一变大（数字牌 0~9 之后十六七张是常态）就算错了行高，
        第三行直接掉到 y=720 之外。共用一份实现就不会再分叉。
        """
        rects = card_grid_rects(len(self.cards))
        self.card_y = rects[0].y if rects else 200
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
                # 回血音是「暖流」型的（慢起音、上行三音），
                # 和打击音完全相反的听感 —— 一听就知道是好消息
                sfx.play("heal", gap_ms=0)
                return self.finish()
            if self.btn_upgrade.collidepoint(mouse):
                if not self.cards:
                    self.msg = "没有可强化的卡"
                    sfx.play("ui_deny", gap_ms=0)
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
        # 「打磨 + 定音」的金属上行音 —— 强化是永久收益，反馈要够分量
        sfx.play("upgrade", gap_ms=0)

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

        # 提示放在卡片网格正下方（和底部那行 msg 分开，别叠在一起）。
        # 网格行数多的时候网格底会往下压，这里夹一下，免得两行字压在一起。
        tip = self.F_SML.render("点击一张卡强化它（数值 +3）", True, TEXT_MUTE)
        grid_bottom = max(r.bottom for r in self.card_rects) if self.card_rects else 400
        tip_y = min(grid_bottom + 30, HEIGHT - 62)
        screen.blit(tip, tip.get_rect(center=(WIDTH // 2, tip_y)))

    def draw_card(self, screen, r, card, hover):
        draw_card_tile(screen, r, card, hover, self.F_SML, self.F_TINY)


# ==================== 商店 ====================
class ShopPanel(Panel):
    title = "商店"
    subtitle = "用金币买一点确定性"

    def __init__(self, player):
        super().__init__(player)
        self.stock = self.roll_stock()
        # 删牌**一次商店只能删一张**：删完这家店就不再提供这项服务。
        # 配合「每删一张就涨一档价」（player.removal_price），
        # 删牌才不会变成「金币全部倒进去把牌组清空」。
        self.removed_here = False
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

    @property
    def removal_price(self):
        """本店删牌的价钱 —— 直接问玩家（它记着删过几张，见 player.removal_price）。

        做成属性而不是 __init__ 里存一份，是因为**删完那一张之后价钱就变了**：
        存快照的话，同一家店里按钮上的数字会和实际扣的钱对不上。
        """
        return self.player.removal_price()

    def roll_stock(self):
        # shop_pool 会按「平方解锁了没有」过滤，见那边的注释
        picks = random.sample(shop_pool(self.player), 3)
        stock = []
        for name, ctype, value, desc, cost, eff in picks:
            # 数字牌按数字加价 —— 9 号牌一次 9 点伤害，跟 1 号牌一个价说不过去
            price = 40 + cost * 20 + (value * 4 if ctype == "number" else 0)
            stock.append({"kind": "card", "name": name, "ctype": ctype,
                          "value": value, "desc": desc, "cost": cost,
                          "effect": eff, "price": price, "sold": False})
        # 一件遗物
        # 一件遗物（抽玩家还没有的；全都有了就不摆这一格）
        got = roll_unowned_relic(self.player)
        if got:
            rname, rdesc = got
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
                    paid = self.player.buy_removal(c)
                    if paid is None:
                        # 钱在「点开选卡界面」之后可能被花掉过（虽然目前
                        # 商店里没有别的花销出口，但别把这件事交给运气）
                        self.msg = "金币不够（还差 %d）" % (
                            self.removal_price() - self.player.gold)
                        sfx.play("ui_deny", gap_ms=0)
                        return None
                    self.removed_here = True
                    self.player.log("花 %d 金币从牌库移除了「%s」"
                                    % (paid, c.name))
                    self.mode = "shop"
                    # 把「下次更贵」直接写在结果里，否则玩家只会觉得
                    # 下一家店的价钱莫名其妙涨了
                    self.msg = "已移除「%s」　下次删牌要 %d 金币" % (
                        c.name, self.player.removal_price())
                    sfx.play("coin", gap_ms=0)
                    return None
            return None

        # ---- 商品格子 ----
        for i, item in enumerate(self.stock):
            if self.item_rects[i].collidepoint(mouse):
                if item["sold"]:
                    self.msg = "这件已经卖掉了"
                    sfx.play("ui_deny", gap_ms=0)
                    return None
                if self.player.gold < item["price"]:
                    self.msg = "金币不够（还差 %d）" % (item["price"] - self.player.gold)
                    sfx.play("ui_deny", gap_ms=0)
                    return None
                self.buy(item)
                return None

        # ---- 移除卡牌服务 ----
        if self.btn_remove.collidepoint(mouse):
            if self.removed_here:
                # 一家店只做一单 —— 这既是难度控制，也让「去哪家店删牌」
                # 变成一个要规划的取舍，而不是「钱够就一直删」
                self.msg = "这家店已经用过了（一次只能删一张）"
                sfx.play("ui_deny", gap_ms=0)
                return None
            if self.player.gold < self.removal_price:
                self.msg = "金币不够（还差 %d）" % (self.removal_price - self.player.gold)
                sfx.play("ui_deny", gap_ms=0)
                return None
            if not self.player.deck_cards():
                self.msg = "牌库是空的"
                sfx.play("ui_deny", gap_ms=0)
                return None
            self.mode = "pick_remove"
            # 注意：card_rects 必须在这里（点击时）算好，
            # 不能在 draw_pick 里算 —— draw 会在点击之后才跑，
            # 那样第一帧点击就会命中失败
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
            sfx.play("coin", gap_ms=0)
        else:
            self.player.relics.append(item["name"])
            self.player.log("获得了遗物「%s」" % item["name"])
            self.msg = "获得遗物「%s」" % item["name"]
            # 花钱 →（0.2 秒）→ 遗物到手。错开是为了让「买到了什么」
            # 听得出来：两音连在一起就是一句「交易完成，这是你的东西」
            sfx.play("coin", gap_ms=0)
            sfx.play_after("relic", 0.20)

    def draw_body(self, screen, mouse, t):
        if self.mode == "pick_remove":
            self.draw_pick(screen, mouse)
            return

        for i, item in enumerate(self.stock):
            r = self.item_rects[i]  # 位置已在 __init__ 里算好
            self.draw_item(screen, r, item, mouse)

        # 底部：移除服务 + 离开
        # 「这家店删过了」和「钱不够」是两种不同的不可用，按钮上的字要分开写，
        # 否则玩家会一直以为是自己钱不够，在那儿反复攒钱
        usable = (not self.removed_here) and self.player.gold >= self.removal_price
        col = RED if usable else TEXT_FAINT
        hover = self.btn_remove.collidepoint(mouse) and usable
        pygame.draw.rect(screen, RED_SOFT if usable else (243, 242, 238),
                         self.btn_remove, border_radius=10)
        pygame.draw.rect(screen, col, self.btn_remove, 3 if hover else 2,
                         border_radius=10)
        if self.removed_here:
            label = "这家店删过了"
        else:
            label = "移除一张卡  %d" % self.removal_price
        bt = self.F_MID.render(label, True, col)
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
        soft = (card_soft(item.get("ctype")) if item.get("ctype")
                else (238, 237, 254))
        pygame.draw.rect(screen, soft, bar,
                         border_top_left_radius=12, border_top_right_radius=12)

        nm = self.F_MID.render(item["name"], True,
                               TEXT_FAINT if sold else TEXT)
        screen.blit(nm, nm.get_rect(center=(r.centerx, r.y + 20)))

        # 类型标签（遗物没有 ctype，单独给一个）
        tag = (type_label(item["ctype"]) + "卡" if item.get("ctype")
               else "遗物")
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
        """排布「选一张卡移除」的网格（小一号的卡，行数多也不会出屏）。"""
        cards = self.player.deck_cards()
        self.cards = cards
        return fit_grid_rects(len(cards), 110, 148, 14, 22,
                              bottom=HEIGHT - 100)

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


#: 事件结果的音效。**按 fn（发生的事）分类，不按文案猜** ——
#: 以后文案改了，声音不会跟着错。拿不准的就用 ui_click（中性的确认音）。
_EVENT_SFX = {
    "nothing": "ui_back",
    "lose_hp_gain_relic": "relic",
    "gain_max_hp": "heal",
    "gain_gold": "coin",
    "gold_cost_hp": "coin",
    "gold_for_maxhp": "heal",
    "remove_card": "card_play",
    "upgrade_card": "upgrade",
}


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
        ok = True          # 这件事成没成。金币不够 / 牌库空 = 没成，声音要换
        if fn == "nothing":
            self.msg = "你只是路过。"
        elif fn == "lose_hp_gain_relic":
            p.hp = max(1, p.hp - 10)
            got = roll_unowned_relic(p)
            if got:
                name, desc = got
                p.add_relic(name)
                self.msg = "失去 10 点生命，获得遗物「%s」：%s" % (name, desc)
                p.log("事件：获得遗物「%s」" % name)
            else:
                # 遗物全收齐了就别再塞重复的（效果按名字算，重复等于没给）
                self.msg = "失去 10 点生命 —— 但塔里的遗物都已在你手上"
                p.log("事件：遗物已集齐")
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
                ok = False
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
                ok = False
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
                ok = False

        # 结果音：办成了用奖励音，没办成用拒绝音
        sfx.play(_EVENT_SFX.get(fn, "ui_click") if ok else "ui_deny",
                 gap_ms=0)
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
        self.relic_gold = 0         # 遗物集齐时折现的金币
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
        sfx.play("card_draw", gap_ms=0)          # 掀开箱盖的「唰」
        got = roll_unowned_relic(self.player)
        if got:
            self.relic_name, self.relic_desc = got
            # 必须走 add_relic 而不是 relics.append ——
            # 「公理石」那种「拿到就改数值」的遗物在那里结算
            note = self.player.add_relic(self.relic_name)
            if note:
                # 补进描述里显示，不另开一行（面板下半部分是按钮，挤不下）
                self.relic_desc = self.relic_desc + "（" + note + "）"
            self.player.log("宝箱：获得遗物「%s」" % self.relic_name)
            # 延迟一点再响：让「开箱」和「拿到遗物」听成两件事，
            # 而不是糊成一声。0.22 秒是人耳能分开、又不觉得慢的间隔。
            sfx.play_after("relic", 0.22)
        else:
            self.relic_name = "遗物已集齐"
            self.relic_gold = 40
            self.relic_desc = ("塔里的遗物你都收下了，这一箱改成 %d 金币"
                               % self.relic_gold)
            self.player.gold += self.relic_gold
            self.player.log("宝箱：遗物已集齐，+%d 金币" % self.relic_gold)
            sfx.play_after("coin", 0.22)
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

            head = "遗物已集齐" if self.relic_gold else "获得遗物"
            tt = self.F_BIG.render(head, True, GOLD)
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


# ==================== 战利品（精英 / 层主战后）====================
class SpoilsPanel(Panel):
    """精英 / 层主倒下之后的战利品。

    和普通战斗只掉金币不同，这一档还有两样：

      1. **一件遗物** —— 自动收下，抽的是玩家还没有的那件
      2. **选一张卡强化** —— 精英 1 次、层主 2 次
         （次数写在 battle_scene.ENEMY_KINDS 里）

    两个阶段串成一条线：先看遗物、点「收下」，再进选卡界面。
    遗物集齐了就折现成金币；没牌可强化就直接结束。
    两样都给不出来的话 __init__ 里就 done 了，
    调用方看到 panel.done 直接回地图，不要开一个空面板。
    """

    title = "战利品"

    def __init__(self, player, kind="elite", relics=1, upgrades=1, unlock=None):
        """unlock：这一战附赠的「新卡解锁」，传一个卡牌 spec
        (name, ctype, value, desc, cost, effect)。

        目前只有第一层层主会传（送「平方」）。卡**不在这里发** ——
        发卡是 main.Game 的事（它才知道打的是第几层），本面板只负责
        把这件事大声告诉玩家。奖励和展示分开，是为了让「谁发的」
        只有一个地方可查。
        """
        super().__init__(player)
        self.kind = kind
        self.unlock = unlock
        self.subtitle = ("层主留下的东西" if kind == "boss"
                         else "精英留下的东西")
        self.upgrade_quota = max(0, int(upgrades))
        self.upgraded = []              # 这次强化过的卡名（只用于文案）

        # ---- 遗物（发一件；这里是「有没有」的语义，配置里也都是 1 件）----
        self.relic_name = None
        self.relic_desc = None
        self.relic_gold = 0
        if relics > 0:
            got = roll_unowned_relic(player)
            if got:
                self.relic_name, self.relic_desc = got
                # 走 add_relic（不是 relics.append）——「公理石」那类
                # 拿到就改数值的遗物要在那里结算
                note = player.add_relic(self.relic_name)
                if note:
                    self.relic_desc = self.relic_desc + "（" + note + "）"
                player.log("战利品：获得遗物「%s」" % self.relic_name)
                # 面板一打开就响钟琴 —— 打赢精英/层主之后该有的那份「贵重」感
                sfx.play("relic", gap_ms=0)
            else:
                # 遗物全拿完了就别硬塞重复的（效果按名字算，重复等于白给）
                self.relic_gold = 40
                player.gold += self.relic_gold
                player.log("战利品：遗物已集齐，折现 +%d 金币" % self.relic_gold)
                sfx.play("coin", gap_ms=0)

        # ---- 布局（和宝箱面板同一套尺寸，看着像一家人）----
        self.result_rect = pygame.Rect(WIDTH // 2 - 300, 190, 600, 250)
        self.btn_take = pygame.Rect(self.result_rect.centerx - 90,
                                    self.result_rect.bottom - 62, 180, 46)
        self.card_rects = []
        self.cards = []

        # ---- 阶段 ----
        # 顺序：先看新卡（最重要的东西，第一眼就该看到）-> 再看遗物 -> 最后强化
        if self.unlock:
            self.stage = "unlock"
            self.msg = ""
        elif self.relic_name or self.relic_gold:
            self.stage = "relic"
            self.msg = ""
        else:
            self._enter_upgrade()

    # ---------- 阶段流转 ----------
    def _after_unlock(self):
        """看完新卡，接着走原来的流程（遗物 -> 强化）。"""
        if self.relic_name or self.relic_gold:
            self.stage = "relic"
        else:
            self._enter_upgrade()

    def _enter_upgrade(self):
        """进「选一张卡强化」阶段；没牌可强化（或没次数）就直接结束。"""
        self.stage = "upgrade"
        self.cards = list(self.player.deck_cards())
        if self.upgrade_quota <= 0 or not self.cards:
            self.finish()
            return
        self.card_rects = card_grid_rects(len(self.cards))
        self.msg = "点击一张卡强化它（数值 +3）"

    # ---------- 事件 ----------
    def handle(self, event, mouse):
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        if self.stage == "unlock":
            if self.btn_take.collidepoint(mouse):
                self._after_unlock()
            return None

        if self.stage == "relic":
            if self.btn_take.collidepoint(mouse):
                self._enter_upgrade()
            return None

        for i, c in enumerate(self.cards):
            if self.card_rects[i].collidepoint(mouse):
                what = upgrade_card(self.player, c)
                if not what:
                    self.msg = "「%s」没有可强化的数值，换一张" % c.name
                    sfx.play("ui_deny", gap_ms=0)
                    return None
                self.upgraded.append(c.name)
                self.upgrade_quota -= 1
                self.cards.remove(c)        # 同一张卡在一次面板里只强化一次
                sfx.play("upgrade", gap_ms=0)
                if self.upgrade_quota <= 0 or not self.cards:
                    return self.finish()
                self.card_rects = card_grid_rects(len(self.cards))
                self.msg = "点击一张卡强化它（数值 +3）"
                return None
        return None

    # ---------- 绘制 ----------
    def draw_body(self, screen, mouse, t):
        if self.stage == "unlock":
            self.draw_unlock(screen, mouse)
        elif self.stage == "relic":
            self.draw_relic(screen, mouse)
        else:
            self.draw_pick(screen, mouse)

    def draw_unlock(self, screen, mouse):
        """「新卡到手」：把这张牌本身画出来，而不是只写一行字。

        玩家刚被层主用 n² 打过两下，这里让他**看见**那张「平方」牌 ——
        牌面、说明、费用一应俱全，下一场战斗就知道该拿它配数字卡。
        """
        box = self.result_rect
        pygame.draw.rect(screen, PANEL, box, border_radius=16)
        pygame.draw.rect(screen, ACCENT, box, 3, border_radius=16)

        name, ctype, value, desc, cost, effect = self.unlock
        tt = self.F_BIG.render("新卡到手", True, ACCENT)
        screen.blit(tt, tt.get_rect(center=(box.centerx, box.y + 44)))

        # 卡面画在左边，说明写在右边
        card = Card(name, ctype, value, desc, cost, effect)
        cr = pygame.Rect(box.x + 54, box.y + 84, CARD_W, CARD_H)
        draw_card_tile(screen, cr, card, False, self.F_SML, self.F_TINY)

        tx = cr.right + 36
        nm = self.F_BIG.render(name, True, TEXT)
        screen.blit(nm, (tx, box.y + 84))
        self.draw_wrapped(screen, desc, self.F_SML, TEXT_MUTE,
                          tx, box.y + 128, box.right - tx - 40)
        self.draw_wrapped(
            screen,
            "层主就是用它打你的：蓄一个数，下回合打出那个数的平方。",
            self.F_TINY, TEXT_FAINT, tx, box.y + 178, box.right - tx - 40)

        hover = self.btn_take.collidepoint(mouse)
        col = (20, 78, 135) if hover else ACCENT
        pygame.draw.rect(screen, col, self.btn_take, border_radius=10)
        bt = self.F_MID.render("收下", True, (255, 255, 255))
        screen.blit(bt, bt.get_rect(center=self.btn_take.center))

    def draw_relic(self, screen, mouse):
        box = self.result_rect
        pygame.draw.rect(screen, PANEL, box, border_radius=16)
        pygame.draw.rect(screen, PURPLE, box, 3, border_radius=16)

        tt = self.F_BIG.render("获得遗物", True, PURPLE)
        screen.blit(tt, tt.get_rect(center=(box.centerx, box.y + 44)))

        if self.relic_name:
            nm = self.F_BIG.render(self.relic_name, True, TEXT)
            screen.blit(nm, nm.get_rect(center=(box.centerx, box.y + 94)))
            self.draw_wrapped(screen, self.relic_desc, self.F_SML, TEXT_MUTE,
                              box.x + 40, box.y + 128, box.w - 80, center=True)
        else:
            nm = self.F_BIG.render("遗物已集齐", True, TEXT)
            screen.blit(nm, nm.get_rect(center=(box.centerx, box.y + 94)))
            gd = self.F_SML.render("折现 +%d 金币" % self.relic_gold, True, GOLD)
            screen.blit(gd, gd.get_rect(center=(box.centerx, box.y + 136)))

        hover = self.btn_take.collidepoint(mouse)
        col = (63, 56, 140) if hover else PURPLE
        pygame.draw.rect(screen, col, self.btn_take, border_radius=10)
        bt = self.F_MID.render("收下", True, (255, 255, 255))
        screen.blit(bt, bt.get_rect(center=self.btn_take.center))

    def draw_pick(self, screen, mouse):
        for i, c in enumerate(self.cards):
            r = self.card_rects[i]
            draw_card_tile(screen, r, c, r.collidepoint(mouse),
                           self.F_SML, self.F_TINY)

        grid_bottom = (max(r.bottom for r in self.card_rects)
                       if self.card_rects else 400)
        left = self.upgrade_quota - len(self.upgraded)
        prog = self.F_MID.render("还能强化 %d 次" % max(0, left), True, ACCENT)
        screen.blit(prog, prog.get_rect(center=(WIDTH // 2, grid_bottom + 34)))

        if self.upgraded:
            done = self.F_SML.render("已强化：" + "、".join(self.upgraded),
                                     True, TEXT_MUTE)
            screen.blit(done, done.get_rect(center=(WIDTH // 2,
                                                   grid_bottom + 62)))


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
