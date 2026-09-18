# -*- coding: utf-8 -*-
"""art_shapes.py —— 卡牌图案 + 敌人形象（纯代码几何绘制）。

为什么不用贴图：
    卡牌在战斗里只有 132×176、牌组面板里 104×142 —— 这么小的尺寸下
    插画细节全糊成一团，而**几何图标**在这个尺寸反而最清晰。而且卡名
    本身就是数学概念（加一 / 凑十 / 平方 / 三角盾 / 方阵 / 镜像 / 归零），
    画成对应图形比画插画更"说人话"，还和背景那层数学装饰同一套语言。
    代价：零。不用带图、不用预处理、体积一分不涨。

两个入口：
    draw_card_icon(screen, name, center, size, col)
        按卡名画图案。size 是「可用方形边长」，内部一切按比例算 ——
        所以同一张卡在战斗大卡（132 宽）和牌组小卡（104 宽）上
        形状完全一致，只是缩放不同。
    draw_enemy(screen, kind, center, r, t_ms)
        按敌人档次画形象（几何魔像 / 方程组·三元 / 不可解之影）。

三条硬规矩：

  1. **不认识的卡名不能画成空白** —— 以后加新卡而忘了补图案时，
     兜底画一个通用标记（问号圆盘），一眼能看出"这张卡还没配图案"，
     而不是静默留一片白。
  2. **只用 pygame.draw，不渲染生僻字符** —— 项目踩过 ⚔ ⌂ ◈ ▣ 在
     msyh.ttc 里渲染成豆腐块的亏。除了已经验证过安全的 χ（solver 的
     icon 一直在用），其余符号（+ ⊥ ∅ →）全部用线条画出来。
  3. **颜色只从一个主色派生** —— 调用方给数字卡的蓝或图形卡的绿，
     内部用 _shade() 派生深/浅两档。这样换主题色不用改这里。
"""

import math

import pygame

import game_env as E

# 字体缓存：卡面图案要用的字号各档只 load 一次
_fonts = {}


def _font(size):
    if size not in _fonts:
        _fonts[size] = E.load_font(size)
    return _fonts[size]


def _shade(col, f):
    """主色派生：f>0 往白里调（变浅），f<0 往黑里调（变深）。"""
    r, g, b = col[:3]
    if f >= 0:
        return (int(r + (255 - r) * f), int(g + (255 - g) * f),
                int(b + (255 - b) * f))
    f = -f
    return (int(r * (1 - f)), int(g * (1 - f)), int(b * (1 - f)))


def _line(screen, col, a, b, w):
    """带圆头的粗线：pygame 的 line 没有 round cap，两端补圆点。"""
    pygame.draw.line(screen, col, a, b, int(w))
    r = int(w) / 2.0
    pygame.draw.circle(screen, col, (int(a[0]), int(a[1])), int(max(1, r)))
    pygame.draw.circle(screen, col, (int(b[0]), int(b[1])), int(max(1, r)))


def _arrow_head(screen, col, tip, ang, size):
    """在 tip 处画一个指向 ang（弧度）的实心箭头。

    统一在这里画，是为了让「反例 / 最简形式 / 定义域扩张」三处的箭头
    长得一样 —— 各画各的三角形，三处的大小和张角立刻就不一致了
    （卡牌图案那批就是靠共用一个 _line 才保持一致的）。
    """
    half = size * 0.5
    back = ang + math.pi
    base = (tip[0] + math.cos(back) * size, tip[1] + math.sin(back) * size)
    left = (base[0] + math.cos(ang + math.pi / 2) * half,
            base[1] + math.sin(ang + math.pi / 2) * half)
    right = (base[0] + math.cos(ang - math.pi / 2) * half,
             base[1] + math.sin(ang - math.pi / 2) * half)
    pygame.draw.polygon(screen, col, [tip, left, right])


# ---------------------------------------------------------------------------
# 卡牌图案
# ---------------------------------------------------------------------------

def base_card_name(name):
    """剥掉强化后缀 —— 「三角盾+」的图案要用「三角盾」那一份。

    强化会把卡名加个加号，如果查表前不剥掉，玩家花掉一次强化机会之后
    卡面图案反而变成问号圆盘（图案"没了"）。所以查 _ICONS / CARD_SHAPE
    之前一律先过这里。
    """
    return name[:-1] if name.endswith("+") else name


def draw_card_icon(screen, name, center, size, col):
    """按卡名在 center 处画一个 size×size 的图案。

    size 取「可用区域」的短边，内部按比例绘制；col 是卡的主色。
    返回 True 表示画了专属图案，False 表示走了兜底（卡名没配图案）。
    """
    cx, cy = int(center[0]), int(center[1])
    s = float(size)
    drawer = _ICONS.get(base_card_name(name))
    if drawer is None:
        _icon_fallback(screen, cx, cy, s, col)
        return False
    drawer(screen, cx, cy, s, col)
    return True


def _icon_plus(screen, cx, cy, s, col):
    """加一 —— 一个粗加号，四角点四个小点（"再加一个"）。

    卡名就是加法，没有比「＋」更直接的表达。
    """
    arm = s * 0.36
    w = max(2, s * 0.13)
    _line(screen, col, (cx - arm, cy), (cx + arm, cy), w)
    _line(screen, col, (cx, cy - arm), (cx, cy + arm), w)
    dot = s * 0.055
    for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        pygame.draw.circle(
            screen, _shade(col, 0.45),
            (int(cx + dx * s * 0.42), int(cy + dy * s * 0.42)), int(max(2, dot)))


def _icon_ten(screen, cx, cy, s, col):
    """凑十 —— 10 个圆点排成三角阵（1+2+3+4 = 10，三角数）。

    比写个「10」有讲究：三角数本身就是"凑"出来的形状，
    一眼能看出"这些小点加起来是十"。
    """
    dot = max(3.0, s * 0.078)
    gap = s * 0.215
    rows = 4
    top = cy - gap * (rows - 1) / 2.0 - s * 0.02
    for row in range(rows):
        y = top + row * gap
        xs = [cx - (row * gap) / 2.0 + i * gap for i in range(row + 1)]
        for x in xs:
            c = col if row % 2 == 0 else _shade(col, 0.3)
            pygame.draw.circle(screen, c, (int(x), int(y)), int(dot))


def _icon_square(screen, cx, cy, s, col):
    """平方 —— 嵌套的两个正方形（x·x 就是"一个方乘一个方"）。"""
    outer = s * 0.38
    w = max(2, s * 0.075)
    pygame.draw.rect(screen, col,
                     pygame.Rect(int(cx - outer), int(cy - outer),
                                 int(outer * 2), int(outer * 2)),
                     int(w), border_radius=int(s * 0.05))
    inner = s * 0.17
    pygame.draw.rect(screen, _shade(col, 0.42),
                     pygame.Rect(int(cx - inner), int(cy - inner),
                                 int(inner * 2), int(inner * 2)),
                     border_radius=int(s * 0.04))


def _icon_unknown(screen, cx, cy, s, col):
    """未知数 —— 虚线圈 + χ（χ 是 solver 的 icon，msyh 里已验证有这个字）。"""
    r = s * 0.36
    _dashed_circle(screen, col, (cx, cy), r, s * 0.07)
    f = _font(max(10, int(s * 0.42)))
    t = f.render("χ", True, col)
    screen.blit(t, t.get_rect(center=(cx, cy)))


def _icon_triangle_shield(screen, cx, cy, s, col):
    """三角盾 —— 正三角 + 中脊竖线（盾的脊）。"""
    h = s * 0.40
    half = s * 0.42
    pts = [(cx, int(cy - h)), (int(cx - half), int(cy + h * 0.72)),
           (int(cx + half), int(cy + h * 0.72))]
    w = max(2, s * 0.085)
    pygame.draw.polygon(screen, col, pts, int(w))
    # 内部淡色填充，让"盾"有实心感
    pygame.draw.polygon(screen, _shade(col, 0.86), pts)
    pygame.draw.polygon(screen, col, pts, int(w))
    # 中脊
    _line(screen, _shade(col, 0.25), (cx, cy - h * 0.55),
          (cx, cy + h * 0.5), max(2, s * 0.045))


def _icon_grid(screen, cx, cy, s, col):
    """方阵 —— 2×2 四个方块（阵列的最小单位）。"""
    w = max(2, s * 0.07)
    b = s * 0.19          # 单个方块半边长
    gap = s * 0.035
    off = b + gap / 2.0
    for dx in (-1, 1):
        for dy in (-1, 1):
            r = pygame.Rect(0, 0, int(b * 2), int(b * 2))
            r.center = (int(cx + dx * off), int(cy + dy * off))
            pygame.draw.rect(screen, _shade(col, 0.8), r,
                             border_radius=int(s * 0.035))
            pygame.draw.rect(screen, col, r, int(w),
                             border_radius=int(s * 0.035))


def _icon_mirror(screen, cx, cy, s, col):
    """镜像 —— 左右两个对称三角，中间一条竖虚线当"镜面"。"""
    half = s * 0.20
    h = s * 0.36
    w = max(2, s * 0.08)
    # 左三角（朝右）
    pygame.draw.polygon(screen, col, [
        (int(cx - half * 1.8), int(cy - h)), (int(cx - half * 1.8), int(cy + h)),
        (int(cx - half * 0.35), cy)], int(w))
    # 右三角（朝左，镜像）
    pygame.draw.polygon(screen, _shade(col, 0.35), [
        (int(cx + half * 1.8), int(cy - h)), (int(cx + half * 1.8), int(cy + h)),
        (int(cx + half * 0.35), cy)], int(w))
    # 镜面虚线
    seg = s * 0.075
    y = cy - h
    while y < cy + h:
        pygame.draw.line(screen, _shade(col, 0.5),
                         (cx, int(y)), (cx, int(min(y + seg * 0.55, cy + h))),
                         max(1, int(s * 0.035)))
        y += seg


def _icon_zero(screen, cx, cy, s, col):
    """归零 —— 一个圆加一道斜杠（∅ 空集，"什么都没有了"）。"""
    r = s * 0.34
    w = max(2, s * 0.075)
    pygame.draw.circle(screen, col, (cx, cy), int(r), int(w))
    d = r * 0.92
    _line(screen, col, (int(cx - d), int(cy + d)), (int(cx + d), int(cy - d)),
          max(2, s * 0.085))


def _icon_contradiction(screen, cx, cy, s, col):
    """反证 —— ⊥ 记号（竖线立在横线上），逻辑里"矛盾/归谬"的符号。

    注意方向：横线必须在**下面**。画成横线在上就成了「T」，
    那是字母不是符号（第一版就画反了，一眼看出不对）。
    """
    w = max(2, s * 0.085)
    half = s * 0.40
    base_y = cy + s * 0.20          # 横线（底座）
    _line(screen, col, (cx - half, base_y), (cx + half, base_y), w)
    _line(screen, col, (cx, cy - s * 0.30), (cx, base_y), w)
    # 交点一个小圆点：两条命题撞上的那个"矛盾点"
    pygame.draw.circle(screen, _shade(col, 0.42), (cx, int(base_y)),
                       int(max(2, s * 0.055)))


def _icon_sqrt(screen, cx, cy, s, col):
    """开方 —— 一个根号（√），里面压着被开方的那条横线。

    商店卡池里有「开方」这张数字卡，之前没配图案，卡面一直是问号圆盘。
    """
    w = max(2, s * 0.08)
    pts = [(int(cx - s * 0.40), int(cy + s * 0.02)),
           (int(cx - s * 0.22), int(cy + s * 0.34)),
           (int(cx - s * 0.02), int(cy - s * 0.36)),
           (int(cx + s * 0.40), int(cy - s * 0.36))]
    pygame.draw.lines(screen, col, False, pts, int(w))
    # 根号内的被开方数（横线），让它读起来是「√ 一个数」
    _line(screen, _shade(col, 0.25),
          (int(cx + s * 0.04), int(cy - s * 0.12)),
          (int(cx + s * 0.36), int(cy - s * 0.12)), max(2, s * 0.06))


def _icon_substitute(screen, cx, cy, s, col):
    """换元 —— 方块「换成」圆：左方 + 箭头 + 右圆。"""
    w = max(2, s * 0.075)
    b = s * 0.125
    lx = int(cx - s * 0.305)
    rx = int(cx + s * 0.305)
    pygame.draw.rect(screen, _shade(col, 0.82),
                     pygame.Rect(lx - b, cy - b, int(b * 2), int(b * 2)),
                     border_radius=int(s * 0.03))
    pygame.draw.rect(screen, col,
                     pygame.Rect(lx - b, cy - b, int(b * 2), int(b * 2)),
                     int(w), border_radius=int(s * 0.03))
    pygame.draw.circle(screen, _shade(col, 0.82), (rx, cy), int(b))
    pygame.draw.circle(screen, col, (rx, cy), int(b), int(w))
    # 中间的替换箭头
    ay = cy
    _line(screen, _shade(col, 0.2), (int(cx - s * 0.13), ay),
          (int(cx + s * 0.13), ay), max(2, s * 0.05))
    ah = s * 0.075
    pygame.draw.polygon(screen, _shade(col, 0.2), [
        (int(cx + s * 0.13), int(ay - ah)), (int(cx + s * 0.13), int(ay + ah)),
        (int(cx + s * 0.22), ay)])


def _dashed_circle(screen, col, center, r, w):
    """虚线圈（未知数用）：按角度分小段画。"""
    cx, cy = center
    n = 12
    for i in range(n):
        a0 = (i / n) * math.tau
        a1 = a0 + (math.tau / n) * 0.6
        p0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
        p1 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
        pygame.draw.line(screen, col, p0, p1, max(1, int(w)))


def _icon_fallback(screen, cx, cy, s, col):
    """卡名没配图案时的兜底：问号圆盘，一眼看出"还没配图"。"""
    r = s * 0.34
    pygame.draw.circle(screen, _shade(col, 0.82), (cx, cy), int(r))
    pygame.draw.circle(screen, col, (cx, cy), int(r), max(2, int(s * 0.07)))
    f = _font(max(10, int(s * 0.44)))
    t = f.render("?", True, col)
    screen.blit(t, t.get_rect(center=(cx, cy)))


def _icon_digit(d):
    """数字牌 —— 圆盘里一个大数字（返回一个"画图函数"，见下面的注册处）。

    数字牌的图案就是这张牌的数字本身：牌面写的是它、打出的伤害是它、
    题目难度也是按它定的，不用再记一套「图标 ↔ 数值」的对应关系。
    圆盘 + 描边是为了在小卡上也能一眼看出是"一张牌上的数"，
    而不是屏幕上随便一个数字。
    """
    def draw(screen, cx, cy, s, col):
        r = s * 0.46
        pygame.draw.circle(screen, _shade(col, 0.84), (cx, cy), int(r))
        pygame.draw.circle(screen, col, (cx, cy), int(r), max(2, int(s * 0.055)))
        f = _font(max(10, int(s * 0.62)))
        t = f.render(d, True, _shade(col, -0.28))
        screen.blit(t, t.get_rect(center=(cx, cy + int(s * 0.01))))
    return draw


# 卡名 -> 图案。没配到的走 _icon_fallback（问号圆盘），
# 这样以后加新卡忘了补图案时能一眼看出来，而不是静默留白。
_ICONS = {
    "加一":   _icon_plus,
    "凑十":   _icon_ten,
    "平方":   _icon_square,
    "未知数": _icon_unknown,
    "开方":   _icon_sqrt,
    "三角盾": _icon_triangle_shield,
    "方阵":   _icon_grid,
    "镜像":   _icon_mirror,
    "归零":   _icon_zero,
    "反证":   _icon_contradiction,
    "换元":   _icon_substitute,
}

# 数字牌 0~9：图案就是那个数字。
# （上面的「加一 / 凑十 / 未知数 / 开方」是老牌面的图案，老存档里还有
#   这些卡，所以图案不能删；新牌面统一用 0~9。）
for _d in "0123456789":
    _ICONS[_d] = _icon_digit(_d)


# ---------------------------------------------------------------------------
# 遗物图案
# ---------------------------------------------------------------------------
# 十件遗物各配一个几何图案，和卡牌图案同一套路（同一套 _line / _shade /
# 兜底），理由也一样：遗物是**按名字结算**的（见 player.RELIC_POOL），
# 图鉴里十件一次全列出来，一行行读文字去找「我拿到的是哪件」太费劲；
# 给每件一个一眼能认的形，扫过去就找到了。
#
# 取名规矩是「名字本身就是这条效果的口诀」（player.RELIC_NAMING_RULE），
# 图案就照着同一条口诀画：
#     等比数列 -> 一块比一块高一倍的方块      反例   -> 箭头撞墙弹回
#     守恒律   -> 两端等重的天平              复利   -> 越涨越陡的曲线
#
# ⚠️ 加遗物时**必须同时在这里补一个图案**。漏了不会报错，只会画出
# 问号圆盘（不是留白，问号是故意的：一眼看得出"这件还没配图"）。
# tmp/verify_relic_find.py 有一条断言拿 RELIC_POOL 和这张表对账。

def draw_relic_icon(screen, name, center, size, col):
    """按遗物名在 center 画一个 size×size 的图案。

    size 是「可用方形边长」，内部一切按比例算 —— 所以同一个图案在
    图鉴小卡（44）和宝箱面板（56）上形状完全一致，只是缩放不同。
    返回 True 表示画了专属图案，False 表示走了兜底（问号圆盘）。
    """
    cx, cy = int(center[0]), int(center[1])
    s = float(size)
    drawer = RELIC_ICONS.get(name)
    if drawer is None:
        _icon_fallback(screen, cx, cy, s, col)
        return False
    drawer(screen, cx, cy, s, col)
    return True


def _ricon_gp(screen, cx, cy, s, col):
    """等比数列 —— 1 : 2 : 4 三块，底边对齐，一块比一块高一倍。

    「每答对一题伤害 +1」奖励的是接着答，而等比数列就是
    「每往后一项都乘同一个数」的那个序列。
    """
    w = max(2, s * 0.055)
    base = cy + s * 0.38
    x = cx - s * 0.49
    for i in range(3):
        b = s * 0.13 * (2 ** i)
        rr = pygame.Rect(int(x), int(base - b), int(b), int(b))
        pygame.draw.rect(screen, _shade(col, 0.80 - i * 0.25), rr,
                         border_radius=int(max(2, s * 0.03)))
        pygame.draw.rect(screen, col, rr, int(w),
                         border_radius=int(max(2, s * 0.03)))
        x += b + s * 0.04


def _ricon_counter(screen, cx, cy, s, col):
    """反例 —— 一支箭头撞上竖墙、原路弹回去（挨打时反弹伤害）。"""
    w = max(2, s * 0.07)
    wall = cx + s * 0.30
    _line(screen, col, (wall, cy - s * 0.40), (wall, cy + s * 0.40), w)
    # 去程（淡一点）：从左下斜上来撞墙
    _line(screen, _shade(col, 0.35),
          (cx - s * 0.44, cy + s * 0.28), (wall, cy), max(2, s * 0.065))
    # 回程：撞完往回走，箭头指着「回去」的方向
    back = (cx - s * 0.36, cy - s * 0.30)
    _line(screen, col, (wall, cy), back, max(2, s * 0.075))
    _arrow_head(screen, col, back,
                math.atan2(back[1] - cy, back[0] - wall), s * 0.20)


def _ricon_isoperimetric(screen, cx, cy, s, col):
    """等周不等式 —— 同样周长围一圈，圆包住的面积最大：
    圆里内接一个正方（"另一种围法"，看得到它比圆小）。

    对应效果：本回合出过数字卡后，图形卡额外 +4 格挡。
    """
    r = s * 0.44
    d = r / math.sqrt(2.0)
    rr = pygame.Rect(int(cx - d), int(cy - d), int(d * 2), int(d * 2))
    pygame.draw.rect(screen, _shade(col, 0.30), rr, max(2, int(s * 0.05)),
                     border_radius=int(max(2, s * 0.04)))
    pygame.draw.circle(screen, col, (cx, cy), int(r), max(2, int(s * 0.085)))


def _ricon_simplest(screen, cx, cy, s, col):
    """最简形式 —— 并排的两块经过化简只剩一块（能省的就省掉）。

    对应效果：战斗开始时，牌库里最弱的那张被舍去。
    """
    w = max(2, s * 0.06)
    b = s * 0.10
    for i in range(2):
        rr = pygame.Rect(0, 0, int(b * 2), int(b * 2))
        rr.center = (int(cx - s * 0.36 + i * (b * 2 + s * 0.04)), int(cy))
        pygame.draw.rect(screen, _shade(col, 0.74), rr,
                         border_radius=int(max(2, s * 0.03)))
        pygame.draw.rect(screen, _shade(col, 0.25), rr, int(w),
                         border_radius=int(max(2, s * 0.03)))
    # 化简的箭头
    _line(screen, col, (cx + s * 0.04, cy), (cx + s * 0.22, cy),
          max(2, s * 0.065))
    _arrow_head(screen, col, (cx + s * 0.28, cy), 0.0, s * 0.16)
    # 化简之后的那一块（实心、更醒目）
    rr = pygame.Rect(0, 0, int(b * 2.4), int(b * 2.4))
    rr.center = (int(cx + s * 0.36), int(cy))
    pygame.draw.rect(screen, _shade(col, 0.82), rr,
                     border_radius=int(max(2, s * 0.03)))
    pygame.draw.rect(screen, col, rr, int(w),
                     border_radius=int(max(2, s * 0.03)))


def _ricon_conservation(screen, cx, cy, s, col):
    """守恒律 —— 一架两端等重的天平（掉下去的会在另一头补回来）。

    对应效果：每场战斗开始时回 4 点生命。
    """
    w = max(2, s * 0.065)
    beam = cy - s * 0.26
    _line(screen, col, (cx - s * 0.44, beam), (cx + s * 0.44, beam),
          max(2, s * 0.07))
    # 立柱 + 底座
    _line(screen, col, (cx, beam), (cx, cy + s * 0.36), w)
    _line(screen, col, (cx - s * 0.20, cy + s * 0.36),
          (cx + s * 0.20, cy + s * 0.36), max(2, s * 0.07))
    # 两端的托盘（一样高 = 平衡）
    for sx in (-1, 1):
        hx = cx + sx * s * 0.36
        _line(screen, _shade(col, 0.35), (hx, beam), (hx, beam + s * 0.16),
              max(1, int(s * 0.035)))
        d = s * 0.13
        rr = pygame.Rect(int(hx - d), int(beam + s * 0.16),
                         int(d * 2), int(s * 0.11))
        pygame.draw.rect(screen, _shade(col, 0.80), rr,
                         border_radius=int(max(2, s * 0.03)))
        pygame.draw.rect(screen, col, rr, max(2, int(s * 0.045)),
                         border_radius=int(max(2, s * 0.03)))


def _ricon_permutation(screen, cx, cy, s, col):
    """排列组合 —— 3×3 的点阵，其中一条对角线被连起来
    （从"都摆在那儿"到"选出这一组"）。

    对应效果：每回合多抽 1 张牌（手里的可能性多一种）。
    """
    gap = s * 0.27
    dot = int(max(2, s * 0.062))
    # 先连线、后画点：接点才干净（点盖在线的端头上）
    _line(screen, col, (cx - gap, cy - gap), (cx + gap, cy + gap),
          max(2, s * 0.075))
    for i in range(-1, 2):
        for j in range(-1, 2):
            on = (i == j)
            c = col if on else _shade(col, 0.58)
            pygame.draw.circle(screen, c,
                               (int(cx + i * gap), int(cy + j * gap)),
                               dot + (1 if on else 0))


def _ricon_domain(screen, cx, cy, s, col):
    """定义域扩张 —— 实心的小圆（原来的定义域）外套一圈虚线大圆，
    四个斜角还探出小箭头（范围在往外长）。

    对应效果：最大生命 +12 —— 装得下的更多了。
    """
    r0, r1 = s * 0.21, s * 0.38
    pygame.draw.circle(screen, _shade(col, 0.78), (cx, cy), int(r0))
    pygame.draw.circle(screen, col, (cx, cy), int(r0), max(2, int(s * 0.065)))
    _dashed_circle(screen, _shade(col, 0.30), (cx, cy), r1, s * 0.07)
    for k in range(4):
        a = math.pi / 4 + k * math.pi / 2
        tip = (cx + math.cos(a) * (r1 + s * 0.12),
               cy + math.sin(a) * (r1 + s * 0.12))
        _arrow_head(screen, col, tip, a, s * 0.13)


def _ricon_tolerance(screen, cx, cy, s, col):
    """容错区间 —— 数轴上的一个区间，区间里那个点偏了一点也算数。

    对应效果：每回合第一次算错，卡牌不消耗。
    """
    w = max(2, s * 0.06)
    ay = cy + s * 0.24
    _line(screen, _shade(col, 0.40), (cx - s * 0.46, ay), (cx + s * 0.46, ay),
          max(1, int(s * 0.04)))
    lx, rx, top = cx - s * 0.24, cx + s * 0.24, cy - s * 0.22
    pygame.draw.lines(screen, col, False,
                      [(int(lx), int(ay)), (int(lx), int(top)),
                       (int(rx), int(top)), (int(rx), int(ay))], int(w))
    # 偏右的那个点：容错区间里的「差一点也算」
    pygame.draw.circle(screen, col, (int(cx + s * 0.12), int(ay)),
                       int(max(2, s * 0.075)))


def _ricon_reduce(screen, cx, cy, s, col):
    """约分 —— 分数线上下各两个小块，一条斜杠把公因子划掉。

    对应效果：商店删牌价格降低 30%（价格也被「约」掉了）。
    """
    w = max(2, s * 0.055)
    b = s * 0.085
    _line(screen, col, (cx - s * 0.30, cy), (cx + s * 0.30, cy),
          max(2, s * 0.07))
    for dy in (-1, 1):
        for dx in (-1, 1):
            rr = pygame.Rect(0, 0, int(b * 2), int(b * 2))
            rr.center = (int(cx + dx * s * 0.16), int(cy + dy * s * 0.24))
            pygame.draw.rect(screen, _shade(col, 0.72), rr,
                             border_radius=int(max(2, s * 0.025)))
            pygame.draw.rect(screen, _shade(col, 0.30), rr, int(w),
                             border_radius=int(max(2, s * 0.025)))
    # 划掉公因子的那一笔
    _line(screen, col, (cx - s * 0.36, cy + s * 0.40),
          (cx + s * 0.36, cy - s * 0.40), max(2, s * 0.075))


def _ricon_compound(screen, cx, cy, s, col):
    """复利 —— 一条越涨越陡的曲线，末端滚成一个大球（利滚利）。

    对应效果：战斗胜利的金币奖励 +50%。
    """
    n = 7
    x0, x1 = cx - s * 0.40, cx + s * 0.26
    y0, y1 = cy + s * 0.34, cy - s * 0.34
    pts = [(int(x0 + (x1 - x0) * (i / (n - 1.0))),
            int(y0 + (y1 - y0) * ((i / (n - 1.0)) ** 2.1))) for i in range(n)]
    pygame.draw.lines(screen, col, False, pts, max(2, int(s * 0.08)))
    pygame.draw.circle(screen, col, (int(x0), int(y0)), int(max(2, s * 0.055)))
    ball = (int(x1 + s * 0.06), int(y1))
    r = int(max(3, s * 0.15))
    pygame.draw.circle(screen, _shade(col, 0.80), ball, r)
    pygame.draw.circle(screen, col, ball, r, max(2, int(s * 0.055)))


# 遗物名 -> 图案。名字和 player.RELIC_POOL 一一对应，
# 漏配的会被 draw_relic_icon 画成问号圆盘（见上面那段注释）。
RELIC_ICONS = {
    "等比数列":   _ricon_gp,
    "反例":       _ricon_counter,
    "等周不等式": _ricon_isoperimetric,
    "最简形式":   _ricon_simplest,
    "守恒律":     _ricon_conservation,
    "排列组合":   _ricon_permutation,
    "定义域扩张": _ricon_domain,
    "容错区间":   _ricon_tolerance,
    "约分":       _ricon_reduce,
    "复利":       _ricon_compound,
}


def has_relic_icon(name):
    """这件遗物配了专属图案吗（给测试用：漏配一件就红）。"""
    return name in RELIC_ICONS


# ---------------------------------------------------------------------------
# 敌人形象
# ---------------------------------------------------------------------------

#: 敌人配色：每档一个主色（和背景的暖灰底搭得上，不刺眼）
ENEMY_STYLE = {
    "battle": {"main": (196, 96, 92), "dark": (150, 66, 64),
               "soft": (232, 208, 204), "stone": (186, 168, 162)},
    "elite":  {"main": (176, 108, 62), "dark": (132, 78, 44),
               "soft": (236, 216, 196), "stone": (190, 172, 158)},
    "boss":   {"main": (96, 80, 156), "dark": (58, 48, 104),
               "soft": (216, 212, 236), "stone": (168, 162, 186)},
    # 第一层层主「正方体·三阶」：用塔基那一层的主题蓝，
    # 和地图上这一层的配色对得上（玩家进战斗时不会觉得换了地方）
    "boss_square": {"main": (54, 116, 176), "dark": (32, 74, 122),
                    "soft": (214, 230, 246), "stone": (176, 198, 220)},
}


def enemy_style(kind):
    return ENEMY_STYLE.get(kind, ENEMY_STYLE["battle"])


def draw_enemy(screen, kind, center, r, t_ms=0):
    """按敌人档次画形象。r 是"体型半径"，一切按它比例缩放。

    四档各有各的视觉母题，和它们的名字对应：
        battle      几何魔像     —— 多边形一层层堆起来的石像
        elite       方程组·三元   —— 三个圆互相连线牵制，解一个才能动下一个
        boss        不可解之影    —— 一个收不拢的漩涡，中心是自己的矛盾
        boss_square 正方体·三阶   —— 三个正方形共用一条底边，边长 1:2:3
    """
    cx, cy = int(center[0]), int(center[1])
    r = float(r)
    st = enemy_style(kind)
    if kind == "elite":
        _enemy_elite(screen, cx, cy, r, st, t_ms)
    elif kind == "boss":
        _enemy_boss(screen, cx, cy, r, st, t_ms)
    elif kind == "boss_square":
        _enemy_square_boss(screen, cx, cy, r, st, t_ms)
    else:
        _enemy_golem(screen, cx, cy, r, st, t_ms)


def _enemy_golem(screen, cx, cy, r, st, t_ms):
    """几何魔像：底三角 + 中方 + 顶菱，从下往上"堆"出来。

    最基础的三种多边形摞成一个能站住的形象 —— 它就是"由最基础的多边形堆成"。
    身体随 t_ms 轻微呼吸（用 sin 直接算，无随机，可测试）。
    """
    breathe = 1.0 + 0.02 * math.sin(t_ms / 900.0) if t_ms else 1.0

    # 底座（大三角）。by = cy + r 让底边正好落在地面线（和原来红圆的底边一致，
    # 这样意图框/血条/影子这些已经调好的位置都不用动）
    base_h = r * 0.62 * breathe
    base_w = r * 0.86
    by = cy + r
    pygame.draw.polygon(screen, st["stone"], [
        (cx, int(by - base_h)), (int(cx - base_w), int(by)),
        (int(cx + base_w), int(by))])
    pygame.draw.polygon(screen, st["dark"], [
        (cx, int(by - base_h)), (int(cx - base_w), int(by)),
        (int(cx + base_w), int(by))], max(2, int(r * 0.055)))

    # 躯干（方块）
    bw = r * 0.56 * breathe
    bh = r * 0.60 * breathe
    body = pygame.Rect(0, 0, int(bw * 2), int(bh * 2))
    body.center = (cx, int(by - base_h - bh * 0.72))
    pygame.draw.rect(screen, st["stone"], body, border_radius=int(r * 0.08))
    pygame.draw.rect(screen, st["dark"], body, max(2, int(r * 0.055)),
                     border_radius=int(r * 0.08))

    # 头（菱形）
    hy = body.top - r * 0.24
    hw = r * 0.28
    hh = r * 0.28
    pygame.draw.polygon(screen, st["main"], [
        (cx, int(hy - hh)), (int(cx + hw), int(hy)),
        (cx, int(hy + hh)), (int(cx - hw), int(hy))])
    pygame.draw.polygon(screen, st["dark"], [
        (cx, int(hy - hh)), (int(cx + hw), int(hy)),
        (cx, int(hy + hh)), (int(cx - hw), int(hy))], max(2, int(r * 0.05)))

    # 两眼（躯干上的暗点，让它"活"）
    eye = max(2.0, r * 0.075)
    ey = body.top + bh * 0.45
    for dx in (-0.42, 0.42):
        pygame.draw.circle(screen, st["dark"],
                           (int(cx + bw * dx), int(ey)), int(eye))


def _enemy_elite(screen, cx, cy, r, st, t_ms):
    """方程组·三元：三个圆顶点互连成三角，中心一个"解"点。

    连线代表"互相牵制"，三条边缺一条就构不成方程组。
    """
    spin = t_ms / 4000.0 if t_ms else 0.0
    orb_r = r * 0.30          # 每个未知数圆盘的半径
    dist = r * 0.62           # 圆心到整体中心的距离
    pts = []
    for i in range(3):
        # +pi/2 让**第一个圆落在正下方**当底座 —— 三个圆摆成"倒品"字。
        # 若写成 -pi/2（第一个在上），形象重心偏上、底边离地面差一大截，
        # 看着像浮在半空（断言 [6] 会抓到：底边只到 0.73r）。
        a = spin + math.tau * i / 3.0 + math.pi / 2.0
        pts.append((cx + dist * math.cos(a), cy + dist * math.sin(a)))

    # 三条约束线（先画，压在圆下面）
    for i in range(3):
        a, b = pts[i], pts[(i + 1) % 3]
        pygame.draw.line(screen, st["dark"],
                         (int(a[0]), int(a[1])), (int(b[0]), int(b[1])),
                         max(2, int(r * 0.05)))

    # 三个未知数圆盘
    for i, (px, py) in enumerate(pts):
        pygame.draw.circle(screen, st["soft"], (int(px), int(py)), int(orb_r))
        pygame.draw.circle(screen, st["main"], (int(px), int(py)), int(orb_r),
                           max(2, int(r * 0.05)))
        f = _font(max(10, int(orb_r * 1.15)))
        t = f.render("χ", True, st["dark"])
        screen.blit(t, t.get_rect(center=(int(px), int(py))))

    # 中心：还没解出来的"解"（小实心点）
    pygame.draw.circle(screen, st["main"], (cx, cy), int(r * 0.10))
    pygame.draw.circle(screen, st["soft"], (cx, cy), int(r * 0.10),
                       max(1, int(r * 0.035)))


def _enemy_boss(screen, cx, cy, r, st, t_ms):
    """不可解之影：收不拢的螺旋 + 断口的环。

    螺旋是"越想解开、越绕进去"；外圈留个缺口表示这个方程没有解。
    """
    spin = t_ms / 2600.0 if t_ms else 0.0

    # 外环（留缺口）
    gap_a = spin
    rect = pygame.Rect(0, 0, int(r * 1.78), int(r * 1.78))
    rect.center = (cx, cy)
    pygame.draw.arc(screen, st["main"], rect,
                    gap_a + 0.28, gap_a + math.tau - 0.28,
                    max(3, int(r * 0.075)))

    # 内螺旋（2.4 圈，从外往内收）
    n = 72
    turns = 2.4
    winds = []
    for i in range(n + 1):
        t = i / n
        a = spin * 0.6 + t * math.tau * turns
        rad = r * (0.72 - 0.55 * t)
        winds.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    if len(winds) > 1:
        pygame.draw.lines(screen, st["dark"], False,
                          [(int(x), int(y)) for x, y in winds],
                          max(2, int(r * 0.055)))

    # 核（那个矛盾本身）
    pygame.draw.circle(screen, st["dark"], (cx, cy), int(r * 0.17))
    pygame.draw.circle(screen, st["main"], (cx, cy), int(r * 0.17),
                       max(2, int(r * 0.05)))
    pygame.draw.circle(screen, st["soft"], (cx, cy), int(r * 0.065))


def _enemy_square_boss(screen, cx, cy, r, st, t_ms):
    """正方体·三阶：三个正方形**共用同一条底边**，边长 1 : 2 : 3。

    形象就是它的攻击方式。三块方砖的边长是 1、2、3，面积正好是 1、4、9 ——
    「阶」这个字的两种意思（方砖的阶层 / 乘方的次数）在同一个图形里重合：
    它蓄一个数、打出那个数的平方（见 battle_scene.SQUARE_BOSS_CHARGE）。

    刻意**不画成立方体的立体投影**：斜投影在这么小的尺寸下会糊成一团，
    而「正方形一层层长大」既看得清，也正好是玩家要在这一层学会的那件事。
    """
    breathe = 1.0 + 0.02 * math.sin(t_ms / 900.0) if t_ms else 1.0
    foot = cy + r                      # 底边落在和别的敌人同一条地面线上

    # 从大到小叠：边长比例 1 : 2 : 3（= 面积 1 : 4 : 9）
    layers = ((3, 0.92, st["stone"]), (2, 0.62, st["soft"]), (1, 0.33, st["main"]))
    for order, frac, fill in layers:
        side = 2 * r * frac * breathe
        box = pygame.Rect(0, 0, int(side), int(side))
        box.centerx = cx
        box.bottom = int(foot)         # 三条底边对齐 —— 像一摞方砖立在地面上
        pygame.draw.rect(screen, fill, box, border_radius=int(r * 0.06))
        pygame.draw.rect(screen, st["dark"], box,
                         max(2, int(r * 0.05)), border_radius=int(r * 0.06))
        # 阶数用小方点标在左上角内缘，一眼看得出「这是第几阶」
        dot = max(2, int(r * 0.045))
        pygame.draw.circle(screen, st["dark"],
                           (box.left + dot * 3, box.top + dot * 3), dot)

    # 顶阶中心的一点高光：让最里面那块砖「亮起来」，视线有落点
    pygame.draw.circle(screen, st["soft"], (cx, int(foot - r * 0.33)),
                       max(3, int(r * 0.1)))


# ---------------------------------------------------------------------------
# 题目图形（组合出牌的「算面积」题 / 单出图形卡的「认图形名称」题）
# ---------------------------------------------------------------------------
#: 图形卡 -> 几何形状 id。
#  每张图形卡配一种**有面积公式**的基本图形，和卡名的数学含义对得上：
#    三角盾（盾）   -> 三角形
#    方阵（阵列）   -> 正方形
#    镜像（对称）   -> 长方形
#    反证（⊥ 直角） -> 平行四边形
#    换元（替换）   -> 梯形
#    归零（∅ 圆）   -> 圆
#  这里加了新卡却没配形状的话，shape_of_card() 返回 None，
#  调用方会退成「正方形」出题（不会崩，只是题目潦草一点）。
CARD_SHAPE = {
    "三角盾": "triangle",
    "方阵":   "square",
    "镜像":   "rectangle",
    "反证":   "parallelogram",
    "换元":   "trapezoid",
    "归零":   "circle",
}

#: 形状 id -> 中文名（认图形题的正确选项就是它）
SHAPE_CN = {
    "triangle":      "三角形",
    "square":        "正方形",
    "rectangle":     "长方形",
    "parallelogram": "平行四边形",
    "trapezoid":     "梯形",
    "circle":        "圆",
}

#: 形状 id -> 面积公式（写在题面上，玩家不用猜公式）
SHAPE_FORMULA = {
    "triangle":      "底 × 高 ÷ 2",
    "square":        "边长 × 边长",
    "rectangle":     "长 × 宽",
    "parallelogram": "底 × 高",
    "trapezoid":     "（上底 + 下底）× 高 ÷ 2",
    "circle":        "半径 × 半径 × 3（π 取 3）",
}

#: 认图形题的备选名（全部形状名，出题时从这里挑干扰项）
SHAPE_NAMES = list(SHAPE_CN.values())


def shape_of_card(name):
    """图形卡 -> 形状 id。没配到的卡返回 None（调用方兜底）。"""
    return CARD_SHAPE.get(base_card_name(name))


def shape_cn(shape):
    return SHAPE_CN.get(shape, "图形")


def shape_formula(shape):
    return SHAPE_FORMULA.get(shape, "")


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def _dashed_line(screen, col, a, b, w, seg=9):
    """虚线：画「高」这类辅助线用，和实线的边区分开，一眼知道不是边。"""
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    length = math.hypot(bx - ax, by - ay)
    if length <= 0.5:
        return
    ux, uy = (bx - ax) / length, (by - ay) / length
    t = 0.0
    while t < length:
        t2 = min(t + seg, length)
        pygame.draw.line(screen, col,
                         (int(ax + ux * t), int(ay + uy * t)),
                         (int(ax + ux * t2), int(ay + uy * t2)), max(1, int(w)))
        t += seg * 1.9


def _dim_label(screen, text, pos, col, fs):
    """尺寸标注：白底小牌 + 深色数字 —— 压在图形线上也读得清。"""
    f = _font(max(12, int(fs)))
    t = f.render(text, True, _shade(col, -0.25))
    r = t.get_rect(center=(int(pos[0]), int(pos[1])))
    pygame.draw.rect(screen, (255, 255, 255), r.inflate(9, 3), border_radius=4)
    screen.blit(t, r)


def _num(v):
    """标注用的数字：4.0 -> "4"，3.5 -> "3.5"。"""
    return "%g" % v


def draw_shape_figure(screen, shape, center, size, col, dims=None, labels=True):
    """画出「题目里的那个图形」。

    参数：
      shape   形状 id（见 SHAPE_CN）
      center  图形中心点
      size    可用方形边长（和 draw_card_icon 同一套约定，内部按比例算）
      col     线色（图形卡用绿，数字卡用蓝）
      dims    尺寸字典，例如 {"base": 6, "height": 4}。给了尺寸就**按真实
              比例**画（底 6 高 4 看着确实是扁的），而不是画个"示意图形" ——
              面积题里图形比例不对，玩家一眼就觉得题目糊弄。
      labels  是否标注尺寸数字（认图形名称的题不需要标，标了反而像送答案）
    返回 True 表示画了专属图形，False 表示走了兜底。
    """
    cx, cy = int(center[0]), int(center[1])
    s = float(size)
    col = tuple(col[:3])
    fill = _shade(col, 0.88)
    w = max(2, s * 0.055)
    fs = max(13, s * 0.105)
    dims = dims or {}
    show = bool(labels and dims)
    fn = _FIGURES.get(shape)
    if fn is None:
        _icon_fallback(screen, cx, cy, s, col)
        return False
    fn(screen, cx, cy, s, col, fill, w, dims, show, fs)
    return True


def _fig_triangle(screen, cx, cy, s, col, fill, w, dims, show, fs):
    """三角形：底边在下、顶点在上；高是虚线的垂线。"""
    base = float(dims.get("base", 6)) or 6.0
    height = float(dims.get("height", 4)) or 4.0
    bw = s * 0.84
    bh = _clamp(bw * height / base, s * 0.30, s * 0.78)
    top = (cx, cy - bh / 2.0)
    bl = (cx - bw / 2.0, cy + bh / 2.0)
    br = (cx + bw / 2.0, cy + bh / 2.0)
    pts = [(int(top[0]), int(top[1])), (int(bl[0]), int(bl[1])),
           (int(br[0]), int(br[1]))]
    pygame.draw.polygon(screen, fill, pts)
    pygame.draw.polygon(screen, col, pts, int(w))
    if show:
        _dashed_line(screen, _shade(col, 0.2), top, (cx, bl[1]), max(1, w * 0.6))
        _dim_label(screen, _num(height), (cx + s * 0.10, cy + bh * 0.14), col, fs)
        _dim_label(screen, _num(base), (cx + bw * 0.26, bl[1] + fs * 1.05), col, fs)


def _fig_square(screen, cx, cy, s, col, fill, w, dims, show, fs):
    """正方形。"""
    side = float(dims.get("side", 5)) or 5.0
    half = s * 0.34
    r = pygame.Rect(int(cx - half), int(cy - half), int(half * 2), int(half * 2))
    pygame.draw.rect(screen, fill, r)
    pygame.draw.rect(screen, col, r, int(w))
    if show:
        _dim_label(screen, _num(side), (cx, r.bottom + fs * 1.1), col, fs)


def _fig_rectangle(screen, cx, cy, s, col, fill, w, dims, show, fs):
    """长方形：长边在下（标长），右竖边外侧标宽。"""
    lw = float(dims.get("w", 6)) or 6.0
    lh = float(dims.get("h", 4)) or 4.0
    bw = s * 0.86
    bh = _clamp(bw * lh / lw, s * 0.26, s * 0.72)
    r = pygame.Rect(0, 0, int(bw), int(bh))
    r.center = (cx, cy)
    pygame.draw.rect(screen, fill, r)
    pygame.draw.rect(screen, col, r, int(w))
    if show:
        _dim_label(screen, _num(lw), (cx, r.bottom + fs * 1.1), col, fs)
        _dim_label(screen, _num(lh), (r.right + fs * 1.4, cy), col, fs)


def _fig_parallelogram(screen, cx, cy, s, col, fill, w, dims, show, fs):
    """平行四边形：斜一格；高仍是从上底顶点到下底的垂线。"""
    base = float(dims.get("base", 6)) or 6.0
    height = float(dims.get("height", 4)) or 4.0
    bw = s * 0.78
    bh = _clamp(bw * height / base, s * 0.28, s * 0.72)
    skew = bw * 0.26
    tl = (cx - bw / 2.0, cy - bh / 2.0)
    tr = (cx + bw / 2.0, cy - bh / 2.0)
    br = (cx + bw / 2.0 + skew, cy + bh / 2.0)
    bl = (cx - bw / 2.0 + skew, cy + bh / 2.0)
    pts = [(int(p[0]), int(p[1])) for p in (tl, tr, br, bl)]
    pygame.draw.polygon(screen, fill, pts)
    pygame.draw.polygon(screen, col, pts, int(w))
    if show:
        foot = (bl[0], bl[1])
        _dashed_line(screen, _shade(col, 0.2), tl, foot, max(1, w * 0.6))
        _dim_label(screen, _num(height),
                   ((tl[0] + foot[0]) / 2.0 + fs * 1.0, cy + bh * 0.10),
                   col, fs)
        _dim_label(screen, _num(base), (bl[0] + bw / 2.0, bl[1] + fs * 1.05),
                   col, fs)


def _fig_trapezoid(screen, cx, cy, s, col, fill, w, dims, show, fs):
    """梯形：上底短、下底长；高同样是虚线。"""
    top_a = float(dims.get("top", 4)) or 4.0
    bot_b = float(dims.get("bottom", 6)) or 6.0
    height = float(dims.get("height", 4)) or 4.0
    bw = s * 0.86
    tw = _clamp(bw * top_a / bot_b, bw * 0.24, bw * 0.92)
    bh = _clamp(bw * height / bot_b, s * 0.26, s * 0.70)
    tl = (cx - tw / 2.0, cy - bh / 2.0)
    tr = (cx + tw / 2.0, cy - bh / 2.0)
    br = (cx + bw / 2.0, cy + bh / 2.0)
    bl = (cx - bw / 2.0, cy + bh / 2.0)
    pts = [(int(p[0]), int(p[1])) for p in (tl, tr, br, bl)]
    pygame.draw.polygon(screen, fill, pts)
    pygame.draw.polygon(screen, col, pts, int(w))
    if show:
        _dashed_line(screen, _shade(col, 0.2), tl, (tl[0], bl[1]),
                     max(1, w * 0.6))
        _dim_label(screen, _num(height), (tl[0] + fs * 0.9, cy + bh * 0.10),
                   col, fs)
        _dim_label(screen, _num(top_a), (cx, tl[1] - fs * 1.05), col, fs)
        _dim_label(screen, _num(bot_b), (cx, bl[1] + fs * 1.05), col, fs)


def _fig_circle(screen, cx, cy, s, col, fill, w, dims, show, fs):
    """圆：画一条半径线并标出半径（面积题里圆只给半径，π 取 3）。"""
    rad = float(dims.get("r", 4)) or 4.0
    rp = s * 0.34
    pygame.draw.circle(screen, fill, (cx, cy), int(rp))
    pygame.draw.circle(screen, col, (cx, cy), int(rp), int(w))
    ang = math.radians(-38)
    end = (cx + rp * math.cos(ang), cy + rp * math.sin(ang))
    _line(screen, _shade(col, 0.1), (cx, cy), (int(end[0]), int(end[1])),
          max(1, w * 0.7))
    pygame.draw.circle(screen, _shade(col, 0.1), (cx, cy), max(2, int(w * 0.9)))
    if show:
        _dim_label(screen, "r = " + _num(rad),
                   ((cx + end[0]) / 2.0 + fs * 0.4,
                    (cy + end[1]) / 2.0 - fs * 1.15), col, fs)


_FIGURES = {
    "triangle":      _fig_triangle,
    "square":        _fig_square,
    "rectangle":     _fig_rectangle,
    "parallelogram": _fig_parallelogram,
    "trapezoid":     _fig_trapezoid,
    "circle":        _fig_circle,
}
