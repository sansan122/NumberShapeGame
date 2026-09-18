"""
《数与形》牌组查看覆盖层
================================================
一个可以盖在任何场景上的「我的牌组」面板 —— 按 D 打开，ESC / D 关掉。

为什么要单独一个模块：
    地图上想看牌组、战斗里也想看、在商店买东西之前更想看。
    这三个地方分别属于 main.py / battle_scene.py / node_scenes.py，
    如果各自画一遍，改一次样式要改三处（本项目已经吃过这种亏：
    玩家面板被 map_scene 和 main 各画了一遍，改一处没效果）。

    所以收口到这里：谁想用就 `deck_view.open_with(player.deck)`，
    然后把事件丢给 `handle()`、把绘制丢给 `draw()`。

用法（在宿主的事件循环里）：
    if self.deck_view.open:
        self.deck_view.handle(event, mouse)   # 打开时它优先吃掉事件
        return None
    if event.type == pygame.KEYDOWN and event.key == pygame.K_d:
        self.deck_view.open_with(self.player.deck)
    ...
    self.deck_view.draw(screen, mouse, t_ms)  # 画在所有东西之上
"""

import pygame

import game_env as E
import art_shapes
import sfx
# 卡牌类型的三件套（数字 / 图形 / 运算）统一从 player 取 ——
# 战斗、牌组、商店三处必须同色，否则玩家会以为「平方」是一种新东西。
from player import CARD_TYPE_STYLE, card_color, card_soft, type_label

# ==================== 配色（和 battle_scene 保持一致）====================
PANEL       = (255, 255, 255)
PANEL_LINE  = (215, 213, 205)
TEXT        = (44, 44, 42)
TEXT_MUTE   = (110, 108, 102)
ACCENT      = (24, 95, 165)      # 数字卡
ACCENT_SOFT = (230, 241, 251)
GREEN       = (59, 109, 17)      # 图形卡
GREEN_SOFT  = (234, 243, 222)
AMBER       = (186, 117, 23)
SHADOW      = (226, 224, 216)
TRACK       = (226, 224, 216)    # 滚动条底槽

WIDTH, HEIGHT = 1280, 720

# ==================== 布局 ====================
CARD_W, CARD_H = 104, 142
GAP_X, GAP_Y = 12, 14
PAD = 28
HEADER_H = 64
FOOTER_H = 44
PANEL_W = 1060          # 固定宽度
PANEL_MAX_H = 620       # 高度上限，超过就滚动（牌多的时候）
PANEL_MIN_H = 260       # 高度下限，牌少的时候别缩成一条


def wrap_text(font, text, max_w):
    """按像素宽度折行。中文逐字折行就够用，不需要按词断。"""
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if font.size(cur + ch)[0] <= max_w:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


class DeckView:
    """牌组覆盖层。默认关闭。"""

    def __init__(self):
        self.open = False
        self.cards = []
        self.char_name = ""
        self.char_color = ACCENT

        # 滚动：scroll 是当前值，scroll_target 是目标值（用于平滑）
        self.scroll = 0.0
        self.scroll_target = 0.0
        self.max_scroll = 0.0

        self.panel = pygame.Rect(0, 0, PANEL_W, PANEL_MIN_H)
        self.BTN_CLOSE = pygame.Rect(0, 0, 96, 30)
        self._relayout()

        self.F_BIG = E.load_font(28)
        self.F_MID = E.load_font(19)
        self.F_SML = E.load_font(15)
        self.F_TINY = E.load_font(13)

    # ==================== 开关 ====================
    def open_with(self, cards, char=None):
        """打开并显示这批卡。char 传角色 dict 就用它的名字和主题色。"""
        # 排一下序：数字卡在前、图形卡在后，同类型按费用、再按名字。
        # 这样同名卡自然聚成一堆，一眼能看出「我有几张三角盾」。
        order = {t: i for i, t in enumerate(CARD_TYPE_STYLE)}
        self.cards = sorted(
            list(cards),
            key=lambda c: (order.get(c.ctype, len(order)), c.cost, c.name))
        if char:
            self.char_name = char.get("name", "")
            self.char_color = char.get("color", ACCENT)
        else:
            self.char_name = ""
            self.char_color = ACCENT

        self.open = True
        self.scroll = 0.0
        self.scroll_target = 0.0
        self._relayout()
        sfx.play("card_draw", gap_ms=0)      # 翻开牌组的「唰」

    def close(self):
        self.open = False
        sfx.play("ui_back", gap_ms=0)

    def toggle(self, cards, char=None):
        if self.open:
            self.close()
        else:
            self.open_with(cards, char)

    # ==================== 布局计算 ====================
    def _per_row(self):
        """每行放几张。只看宽度，和面板高度无关。"""
        avail_w = PANEL_W - 2 * PAD
        return max(1, (avail_w + GAP_X) // (CARD_W + GAP_X))

    def _grid_metrics(self):
        """算出每行几张、起始 x、可见高度。"""
        per_row = self._per_row()
        avail_w = self.panel.w - 2 * PAD
        row_w = per_row * CARD_W + (per_row - 1) * GAP_X
        x0 = self.panel.x + PAD + (avail_w - row_w) // 2
        top = self.panel.y + HEADER_H
        bottom = self.panel.bottom - FOOTER_H
        return per_row, x0, top, bottom - top

    def _visible_rows(self):
        """一屏能放下几整行。"""
        view_h = self.panel.h - HEADER_H - FOOTER_H
        return max(1, (view_h + GAP_Y) // (CARD_H + GAP_Y))

    def _relayout(self):
        """按卡片数量算面板高度并居中，顺带重算滚动范围。

        为什么要自适应：牌少的时候（开局就 10 张）如果面板高度固定，
        下面会空出一大片，看着像没画完。牌多了再撑到上限并开始滚动。
        """
        per_row = self._per_row()
        rows = max(1, (len(self.cards) + per_row - 1) // per_row)
        content_h = rows * (CARD_H + GAP_Y) - GAP_Y

        h = HEADER_H + content_h + FOOTER_H + 16
        h = max(PANEL_MIN_H, min(PANEL_MAX_H, h))
        self.panel = pygame.Rect(
            (WIDTH - PANEL_W) // 2, (HEIGHT - h) // 2, PANEL_W, h)
        # 关闭按钮跟着面板走
        self.BTN_CLOSE = pygame.Rect(
            self.panel.right - PAD - 96, self.panel.bottom - FOOTER_H + 6, 96, 30)

        view_h = max(0, self.panel.h - HEADER_H - FOOTER_H)
        self.max_scroll = max(0.0, float(content_h - view_h))
        self.scroll_target = max(0.0, min(self.max_scroll, self.scroll_target))
        self.scroll = max(0.0, min(self.max_scroll, self.scroll))

    # ==================== 事件 ====================
    def handle(self, event, mouse):
        """打开状态下处理事件。返回 True 表示「这个事件我吃了」，宿主别再处理。"""
        if not self.open:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_d, pygame.K_TAB):
                self.close()
            elif event.key == pygame.K_UP:
                self.scroll_target -= 60
            elif event.key == pygame.K_DOWN:
                self.scroll_target += 60
            elif event.key == pygame.K_PAGEUP:
                self.scroll_target -= 300
            elif event.key == pygame.K_PAGEDOWN:
                self.scroll_target += 300
            elif event.key == pygame.K_HOME:
                self.scroll_target = 0
            elif event.key == pygame.K_END:
                self.scroll_target = self.max_scroll
            self.scroll_target = max(0.0, min(self.max_scroll, self.scroll_target))
            return True

        if event.type == pygame.MOUSEWHEEL:
            # 滚轮上滚 = 往上看（和地图的约定一致）
            self.scroll_target -= event.y * 60
            self.scroll_target = max(0.0, min(self.max_scroll, self.scroll_target))
            return True

        if event.type == pygame.MOUSEBUTTONDOWN:
            # 点「关闭」按钮，或点面板外面 = 关掉（点面板里面不关，避免误触）
            if self.BTN_CLOSE.collidepoint(mouse) or not self.panel.collidepoint(mouse):
                self.close()
            return True

        # 其它事件（比如 QUIT）不拦，交回宿主
        return False

    def update(self, dt):
        if not self.open:
            return
        self.scroll += (self.scroll_target - self.scroll) * min(1.0, dt * 14.0)

    # ==================== 绘制 ====================
    def draw(self, screen, mouse, t_ms):
        if not self.open:
            return

        # ---------- 1. 背景压暗 ----------
        dim = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        dim.fill((18, 20, 26, 176))
        screen.blit(dim, (0, 0))

        # ---------- 2. 面板 ----------
        pygame.draw.rect(screen, (16, 18, 22), self.panel.move(0, 6),
                         border_radius=16)
        pygame.draw.rect(screen, PANEL, self.panel, border_radius=16)
        pygame.draw.rect(screen, PANEL_LINE, self.panel, 2, border_radius=16)

        self._draw_header(screen)
        self._draw_cards(screen)
        self._draw_footer(screen, mouse)

    def _draw_header(self, screen):
        n = len(self.cards)
        # 按类型统计（数字 / 图形 / 运算），类型和颜色都从 player 那份定义来
        counts = {t: 0 for t in CARD_TYPE_STYLE}
        for c in self.cards:
            counts[c.ctype] = counts.get(c.ctype, 0) + 1

        title = "我的牌组"
        if self.char_name:
            title = "%s · 我的牌组" % self.char_name
        t = self.F_BIG.render(title, True, TEXT)
        screen.blit(t, (self.panel.x + PAD, self.panel.y + 18))

        # 统计：总数 + 各类型张数
        x = self.panel.x + PAD + t.get_width() + 18
        y = self.panel.y + 26
        st = self.F_MID.render("共 %d 张" % n, True, TEXT_MUTE)
        screen.blit(st, (x, y))

        bw = st.get_width() + 22
        bx = x + bw
        for ctype, cnt in counts.items():
            if not cnt:
                continue                      # 没有这一类就不占位置
            col = card_color(ctype)
            txt = self.F_SML.render("%s %d" % (type_label(ctype), cnt), True, col)
            w = txt.get_width() + 18
            r = pygame.Rect(bx, y - 4, w, 26)
            pygame.draw.rect(screen, card_soft(ctype), r, border_radius=13)
            pygame.draw.rect(screen, col, r, 1, border_radius=13)
            screen.blit(txt, txt.get_rect(center=r.center))
            bx += w + 8

        # 右上角：关闭提示
        hint = self.F_SML.render("D / ESC 关闭", True, TEXT_MUTE)
        screen.blit(hint, (self.panel.right - PAD - hint.get_width(),
                           self.panel.y + 30))

        pygame.draw.line(screen, PANEL_LINE,
                         (self.panel.x + 18, self.panel.y + HEADER_H - 6),
                         (self.panel.right - 18, self.panel.y + HEADER_H - 6))

    def _draw_cards(self, screen):
        if not self.cards:
            msg = self.F_MID.render("牌组是空的", True, TEXT_MUTE)
            screen.blit(msg, msg.get_rect(center=self.panel.center))
            return

        per_row, x0, top, view_h = self._grid_metrics()

        # 裁剪：卡片滚动时不能画到面板外面去
        clip = pygame.Rect(self.panel.x + 6, top, self.panel.w - 12, view_h)
        prev_clip = screen.get_clip()
        screen.set_clip(clip)

        for i, c in enumerate(self.cards):
            row, col = divmod(i, per_row)
            x = x0 + col * (CARD_W + GAP_X)
            y = top + row * (CARD_H + GAP_Y) - self.scroll
            if y + CARD_H < top - 4 or y > top + view_h + 4:
                continue                       # 屏幕外，跳过
            self._draw_mini_card(screen, c, pygame.Rect(x, int(y), CARD_W, CARD_H))

        screen.set_clip(prev_clip)

        self._draw_scrollbar(screen, top, view_h)

    def _draw_scrollbar(self, screen, top, view_h):
        if self.max_scroll <= 0:
            return
        track = pygame.Rect(self.panel.right - 18, top, 7, view_h)
        pygame.draw.rect(screen, TRACK, track, border_radius=4)

        per_row, _, _, _ = self._grid_metrics()
        rows = (len(self.cards) + per_row - 1) // per_row
        content_h = rows * (CARD_H + GAP_Y) - GAP_Y
        ratio = float(view_h) / content_h
        h = max(36, int(view_h * ratio))
        y = track.y + int((view_h - h) * (self.scroll / self.max_scroll))
        pygame.draw.rect(screen, ACCENT,
                         pygame.Rect(track.x, y, track.w, h), border_radius=4)

    def _draw_mini_card(self, screen, card, r):
        col = card_color(card.ctype)
        soft = card_soft(card.ctype)

        pygame.draw.rect(screen, SHADOW, r.move(0, 3), border_radius=9)
        pygame.draw.rect(screen, (255, 255, 255), r, border_radius=9)
        pygame.draw.rect(screen, col, r, 2, border_radius=9)

        # 类型色条
        band = pygame.Rect(r.x + 8, r.y + 8, r.w - 16, 5)
        pygame.draw.rect(screen, soft, band, border_radius=3)
        pygame.draw.rect(screen, col, band, border_radius=3)

        # 费用徽标
        if card.cost > 0:
            cx, cy = r.x + 17, r.y + 30
            pygame.draw.circle(screen, AMBER, (cx, cy), 11)
            cs = self.F_TINY.render(str(card.cost), True, (255, 255, 255))
            screen.blit(cs, cs.get_rect(center=(cx, cy)))

        # 卡名（太长就截断加省略号）
        name_max = r.w - 42
        nm = card.name
        while nm and self.F_TINY.size(nm)[0] > name_max:
            nm = nm[:-1]
        if nm != card.name:
            while nm and self.F_TINY.size(nm + "…")[0] > name_max:
                nm = nm[:-1]
            nm = nm + "…"
        nt = self.F_TINY.render(nm, True, TEXT)
        screen.blit(nt, nt.get_rect(midtop=(r.centerx + 8, r.y + 22)))

        # 图案区：卡面中部的几何图案（和战斗大卡同一套，只是缩放更小）。
        # 原来这里是一条分割线，改成图案后它自己就起到分隔作用了。
        art_shapes.draw_card_icon(screen, card.name,
                                  (r.centerx, r.y + 63), r.w * 0.40, col)

        # 说明文字（折行，放不下就省略）
        lines = wrap_text(self.F_TINY, card.desc or "", r.w - 18)
        ly = r.y + 88
        for ln in lines[:3]:
            screen.blit(self.F_TINY.render(ln, True, TEXT_MUTE), (r.x + 9, ly))
            ly += 16

    def _draw_footer(self, screen, mouse):
        y = self.panel.bottom - FOOTER_H + 12

        if self.max_scroll > 0:
            # 只说「可滚动」，不报「正在看第几张」——
            # 滚动位置落在两行之间时那个区间很难算准，报出来反而不准。
            # 位置信息交给右边的滚动条表达，更直观。
            tip = "滚轮 / ↑↓ 滚动　·　共 %d 张（一屏 %d 张）" % (
                len(self.cards), self._per_row() * self._visible_rows())
        else:
            tip = "共 %d 张，已全部显示" % len(self.cards)
        screen.blit(self.F_SML.render(tip, True, TEXT_MUTE),
                    (self.panel.x + PAD, y))

        # 右下角的「关闭」按钮
        hover = self.BTN_CLOSE.collidepoint(mouse)
        pygame.draw.rect(screen, ACCENT if hover else (236, 234, 228),
                         self.BTN_CLOSE, border_radius=15)
        bt = self.F_SML.render("关闭", True,
                               (255, 255, 255) if hover else TEXT)
        screen.blit(bt, bt.get_rect(center=self.BTN_CLOSE.center))
