# -*- coding: utf-8 -*-
"""
《数与形》开场界面
================================================
两个界面，串在正式游戏之前：

    主菜单  ──「开始游戏」──>  选角色  ──「出发」──>  爬塔地图
       │                        │
       └──「继续游戏」读档 ──────┘（直接进地图）

美术资源后面再补，现在全部用「文字 + 方框 + 数学符号」占位 ——
所有框的位置都在 __init__ 里算好，美术图上来了直接换成 blit 就行。

注意：这个文件里**不要**再把「渲染」叫 draw 以外的名字，
也不要让动作方法占用 draw（踩过坑，见 README 避坑记录第 4 条）。
"""

import pygame

import player as P

# ==================== 配色（浅色主题，与地图/战斗界面统一）====================
BG         = (246, 245, 240)
PANEL      = (255, 255, 255)
PANEL_LINE = (215, 213, 205)
TEXT       = (44, 44, 42)
TEXT_MUTE  = (110, 108, 102)
TEXT_FAINT = (170, 168, 160)
ACCENT     = (24, 95, 165)
GOLD       = (196, 148, 30)
SHADOW     = (228, 226, 218)
LINE       = (198, 195, 186)

W, H = 1280, 720
FONT_PATH = "C:/Windows/Fonts/msyh.ttc"


def _font(size):
    return pygame.font.Font(FONT_PATH, size)


# ==================== 小工具 ====================
def draw_box(surf, rect, fill=PANEL, border=PANEL_LINE, radius=10,
             width=2, shadow=True):
    """画一个圆角方框。整套 UI 的基本零件。"""
    if shadow:
        sh = pygame.Rect(rect.x + 3, rect.y + 4, rect.w, rect.h)
        pygame.draw.rect(surf, SHADOW, sh, border_radius=radius)
    pygame.draw.rect(surf, fill, rect, border_radius=radius)
    if border and width:
        pygame.draw.rect(surf, border, rect, width=width, border_radius=radius)


def center_text(surf, text, font, color, cx, cy):
    s = font.render(text, True, color)
    surf.blit(s, s.get_rect(center=(cx, cy)))
    return s.get_rect(center=(cx, cy))


def bar(surf, rect, ratio, color, bg=(228, 226, 218), radius=5):
    """画一条进度条（血条用）。"""
    ratio = max(0.0, min(1.0, ratio))
    pygame.draw.rect(surf, bg, rect, border_radius=radius)
    if ratio > 0:
        inner = pygame.Rect(rect.x, rect.y, max(6, int(rect.w * ratio)),
                            rect.h)
        pygame.draw.rect(surf, color, inner, border_radius=radius)
    pygame.draw.rect(surf, PANEL_LINE, rect, width=1, border_radius=radius)


# ==================== 界面一：主菜单 ====================
class MenuScene:
    """标题 + 两个按钮（开始 / 继续）。

    返回值约定（外层拿到后决定做什么）：
        "new"    -> 去选角色
        "load"   -> 读档进地图
        "quit"   -> 退出
        None     -> 什么都不做
    """

    name = "menu"

    def __init__(self, has_save=False, save_info=""):
        self.has_save = has_save
        self.save_info = save_info

        self.f_title = _font(56)
        self.f_sub   = _font(19)
        self.f_btn   = _font(23)
        self.f_tiny  = _font(14)

        self.btn_new  = pygame.Rect(0, 0, 300, 58)
        self.btn_new.center = (W // 2, 420)
        self.btn_load = pygame.Rect(0, 0, 300, 58)
        self.btn_load.center = (W // 2, 492)
        self.btn_quit = pygame.Rect(0, 0, 300, 40)
        self.btn_quit.center = (W // 2, 566)

        self.hover = None       # "new" / "load" / "quit"
        self.t = 0.0

    # ---------- 输入 ----------
    def handle(self, event, mouse):
        if event.type == pygame.MOUSEMOTION:
            self.hover = self._hit(mouse)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            hit = self._hit(mouse)
            if hit == "new":
                return "new"
            if hit == "load" and self.has_save:
                return "load"
            if hit == "quit":
                return "quit"

        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                return "new"
            if event.key == pygame.K_l and self.has_save:
                return "load"
            if event.key == pygame.K_ESCAPE:
                return "quit"

        return None

    def _hit(self, mouse):
        if self.btn_new.collidepoint(mouse):
            return "new"
        if self.has_save and self.btn_load.collidepoint(mouse):
            return "load"
        if self.btn_quit.collidepoint(mouse):
            return "quit"
        return None

    def update(self, dt):
        self.t += dt

    # ---------- 绘制 ----------
    def draw(self, surf, mouse=(0, 0), t_ms=0):
        surf.fill(BG)

        # 背景：几个淡数学符号做点缀
        deco = _font(120)
        for sym, (dx, dy) in (("∑", (170, 150)), ("√", (1080, 190)),
                              ("π", (250, 560)), ("∞", (1010, 545)),
                              ("△", (640, 120))):
            s = deco.render(sym, True, (236, 234, 227))
            surf.blit(s, s.get_rect(center=(dx, dy)))

        # 标题
        center_text(surf, "数 与 形", self.f_title, TEXT, W // 2, 232)
        center_text(surf, "公 理 塔", self.f_sub, ACCENT, W // 2, 292)
        center_text(surf, "—— 一座由数学公理支撑的塔，越往上，越不可解 ——",
                    self.f_tiny, TEXT_FAINT, W // 2, 330)

        self._button(surf, self.btn_new, "开始游戏", "new", ACCENT)
        self._button(surf, self.btn_load, "继续游戏", "load",
                     GOLD if self.has_save else LINE,
                     enabled=self.has_save)

        if self.has_save and self.save_info:
            center_text(surf, self.save_info, self.f_tiny, TEXT_MUTE,
                        W // 2, 534)
        elif not self.has_save:
            center_text(surf, "（暂无存档）", self.f_tiny, TEXT_FAINT,
                        W // 2, 534)

        self._button(surf, self.btn_quit, "退出", "quit", LINE)

        center_text(surf, "回车 = 开始　L = 读档　ESC = 退出",
                    self.f_tiny, TEXT_FAINT, W // 2, H - 28)

    def _button(self, surf, rect, label, key, color, enabled=True):
        hot = (self.hover == key) and enabled
        fill = (250, 249, 245) if hot else PANEL
        draw_box(surf, rect, fill=fill, border=color, width=2)
        if hot:
            # 悬停时左侧加一个小三角，给一点反馈
            cx = rect.x + 22
            cy = rect.centery
            pygame.draw.polygon(surf, color, [
                (cx - 7, cy - 7), (cx - 7, cy + 7), (cx + 4, cy)])
        col = TEXT if enabled else TEXT_FAINT
        center_text(surf, label, self.f_btn, col, rect.centerx, rect.centery)


# ==================== 界面二：选角色 ====================
class CharSelectScene:
    """三个角色卡片，横排。

    返回值：
        ("pick", char_dict)  -> 定了这个角色，去开新局
        "back"               -> 返回主菜单
        None                 -> 什么都不做
    """

    name = "charselect"

    def __init__(self):
        self.f_title = _font(30)
        self.f_name  = _font(26)
        self.f_title2 = _font(16)
        self.f_body  = _font(15)
        self.f_tiny  = _font(14)
        self.f_btn   = _font(21)

        # 三张角色卡横排
        cw, ch, gap = 336, 396, 28
        total = len(P.CHARACTERS) * cw + (len(P.CHARACTERS) - 1) * gap
        x0 = W // 2 - total // 2
        y0 = 150
        self.cards = []
        for i, c in enumerate(P.CHARACTERS):
            r = pygame.Rect(x0 + i * (cw + gap), y0, cw, ch)
            self.cards.append((c, r, self._sub_rects(r)))

        self.btn_go   = pygame.Rect(0, 0, 240, 56)
        self.btn_go.center   = (W // 2 + 140, 634)
        self.btn_back = pygame.Rect(0, 0, 150, 56)
        self.btn_back.center = (W // 2 - 160, 634)

        self.sel = 0
        self.hover_card = -1
        self.hover_btn = None

    @staticmethod
    def _sub_rects(r):
        """每张卡内部的分区，一次算好（别放进 draw 里）。

        排版顺序（自上而下）：
            头像占位 -> 名字 -> 称号 -> 血条 -> 数值两行
            -> 核心机制 -> 介绍两行 -> 被动（可折两行）
        """
        return {
            "portrait": pygame.Rect(r.x + 20, r.y + 16, r.w - 40, 114),
            "name":     pygame.Rect(r.x + 20, r.y + 140, r.w - 40, 30),
            "title":    pygame.Rect(r.x + 20, r.y + 170, r.w - 40, 22),
            "hpbar":    pygame.Rect(r.x + 20, r.y + 202, r.w - 40, 12),
            "stats":    pygame.Rect(r.x + 20, r.y + 220, r.w - 40, 40),
            "theme":    pygame.Rect(r.x + 20, r.y + 264, r.w - 40, 22),
            "desc":     pygame.Rect(r.x + 20, r.y + 290, r.w - 40, 62),
            # 被动框要给两行文字留高度，否则第二行会溢出框外
            "trait":    pygame.Rect(r.x + 16, r.bottom - 52, r.w - 32, 40),
        }

    # ---------- 输入 ----------
    def handle(self, event, mouse):
        if event.type == pygame.MOUSEMOTION:
            self.hover_card = self._card_at(mouse)
            self.hover_btn = self._btn_at(mouse)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            i = self._card_at(mouse)
            if i >= 0:
                # 第一次点选中，点已选中的那张才算「出发」
                if self.sel == i:
                    return ("pick", P.CHARACTERS[i])
                self.sel = i
                return None

            b = self._btn_at(mouse)
            if b == "go":
                return ("pick", P.CHARACTERS[self.sel])
            if b == "back":
                return "back"

        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_LEFT, pygame.K_a):
                self.sel = (self.sel - 1) % len(P.CHARACTERS)
            elif event.key in (pygame.K_RIGHT, pygame.K_d):
                self.sel = (self.sel + 1) % len(P.CHARACTERS)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                return ("pick", P.CHARACTERS[self.sel])
            elif event.key == pygame.K_ESCAPE:
                return "back"

        return None

    def _card_at(self, mouse):
        for i, (_c, r, _s) in enumerate(self.cards):
            if r.collidepoint(mouse):
                return i
        return -1

    def _btn_at(self, mouse):
        if self.btn_go.collidepoint(mouse):
            return "go"
        if self.btn_back.collidepoint(mouse):
            return "back"
        return None

    def update(self, dt):
        pass

    # ---------- 绘制 ----------
    def draw(self, surf, mouse=(0, 0), t_ms=0):
        surf.fill(BG)

        center_text(surf, "选择你的演算者", self.f_title, TEXT, W // 2, 62)
        center_text(surf, "三个角色只是开局不同，爬塔途中都能拿到同样的卡与遗物",
                    self.f_tiny, TEXT_FAINT, W // 2, 100)

        for i, (c, r, sub) in enumerate(self.cards):
            self._card(surf, c, r, sub, i == self.sel)

        # 底部按钮
        go_hot = self.hover_btn == "go"
        draw_box(surf, self.btn_go,
                 fill=(250, 249, 245) if go_hot else PANEL,
                 border=ACCENT, width=2)
        center_text(surf, "出发", self.f_btn, TEXT,
                    self.btn_go.centerx, self.btn_go.centery)

        bk_hot = self.hover_btn == "back"
        draw_box(surf, self.btn_back,
                 fill=(250, 249, 245) if bk_hot else PANEL,
                 border=LINE, width=2)
        center_text(surf, "返回", self.f_btn, TEXT_MUTE,
                    self.btn_back.centerx, self.btn_back.centery)

        center_text(surf, "← → 切换　回车 = 出发　ESC = 返回",
                    self.f_tiny, TEXT_FAINT, W // 2, H - 24)

    def _card(self, surf, c, r, sub, selected):
        col = tuple(c["color"])
        border = col if selected else PANEL_LINE
        draw_box(surf, r, fill=PANEL, border=border,
                 width=3 if selected else 2)

        # 选中时顶部加一条主题色
        if selected:
            pygame.draw.line(surf, col, (r.x + 12, r.y + 2),
                             (r.right - 12, r.y + 2), 5)

        # ---- 头像占位：大方框 + 大符号 + 「美术待补」 ----
        pr = sub["portrait"]
        draw_box(surf, pr, fill=(247, 246, 241), border=col,
                 width=2, shadow=False)
        # 用大符号本身当占位图，居中放
        big = _font(64)
        center_text(surf, c["icon"], big, col, pr.centerx, pr.centery + 6)
        # 角落一行小字，说明这里以后是立绘
        tag = self.f_tiny.render("头像占位", True, TEXT_FAINT)
        surf.blit(tag, (pr.right - tag.get_width() - 10, pr.y + 6))

        # ---- 名字 / 称号 ----
        center_text(surf, c["name"], self.f_name, TEXT,
                    sub["name"].centerx, sub["name"].centery)
        center_text(surf, c["title"], self.f_title2, col,
                    sub["title"].centerx, sub["title"].centery)

        # ---- 血条 + 数值 ----
        hb = sub["hpbar"]
        bar(surf, hb, 1.0, col)
        st = sub["stats"]
        center_text(surf, "生命上限 %d" % c["hp"], self.f_tiny, TEXT_MUTE,
                    st.centerx, st.y + 12)
        center_text(surf, "初始金币 %d" % c["gold"], self.f_tiny, GOLD,
                    st.centerx, st.y + 31)

        # ---- 核心机制 ----
        center_text(surf, c["theme"], self.f_body, TEXT,
                    sub["theme"].centerx, sub["theme"].centery)

        # ---- 介绍（折行）----
        self._wrap(surf, c["desc"], self.f_tiny, TEXT_MUTE,
                   sub["desc"], line_h=20)

        # ---- 被动（底部一条）----
        # 文案可能比框宽（比如「解方程者」那条），交给折行处理，
        # 所以框要留够两行的高度
        tr = sub["trait"]
        draw_box(surf, tr, fill=(250, 249, 245), border=col,
                 width=1, shadow=False, radius=7)
        tl = self.f_tiny.render(c["trait"], True, col)
        if tl.get_width() <= tr.w - 16:
            surf.blit(tl, tl.get_rect(center=tr.center))
        else:
            self._wrap(surf, c["trait"], self.f_tiny, col,
                       tr.inflate(-16, -8), line_h=17)

    @staticmethod
    def _wrap(surf, text, font, color, rect, line_h=20):
        """按像素宽度折行 —— 中文没有空格，不能用 split()。"""
        lines, cur = [], ""
        for ch in text:
            if font.size(cur + ch)[0] > rect.w:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        if cur:
            lines.append(cur)
        for i, ln in enumerate(lines):
            s = font.render(ln, True, color)
            surf.blit(s, (rect.x, rect.y + i * line_h))


# ==================== 界面三：开局过渡提示（可选）====================
class LoadingScene:
    """按「出发」之后、正式进地图之前的一小段过渡。

    存在的意义：地图生成 + 换场景有一瞬间的卡顿，
    直接闪过去会显得很生硬。这里画一行字顶一下。
    """

    name = "loading"

    def __init__(self, char, seconds=0.7):
        self.char = char
        self.left = seconds
        self.f_big = _font(34)
        self.f_mid = _font(18)
        self.t = 0.0

    def handle(self, event, mouse):
        # 按任意键跳过
        if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
            self.left = 0.0
        return None

    def update(self, dt):
        self.t += dt
        self.left -= dt
        if self.left <= 0:
            return "done"
        return None

    def draw(self, surf, mouse=(0, 0), t_ms=0):
        surf.fill(BG)
        col = tuple(self.char["color"])
        big = _font(96)
        center_text(surf, self.char["icon"], big, col, W // 2, 280)
        center_text(surf, "%s 踏入了公理塔" % self.char["name"],
                    self.f_big, TEXT, W // 2, 400)
        center_text(surf, "第 1 层 · 塔基 · 数之庭", self.f_mid, TEXT_MUTE,
                    W // 2, 442)
        # 呼吸点，表示在读盘
        n = int(self.t * 3) % 4
        center_text(surf, "正 在 生 成 地 图" + "·" * n,
                    self.f_mid, TEXT_FAINT, W // 2, 500)
