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


# ---------------------------------------------------------------------------
# 卡牌图案
# ---------------------------------------------------------------------------

def draw_card_icon(screen, name, center, size, col):
    """按卡名在 center 处画一个 size×size 的图案。

    size 取「可用区域」的短边，内部按比例绘制；col 是卡的主色。
    返回 True 表示画了专属图案，False 表示走了兜底（卡名没配图案）。
    """
    cx, cy = int(center[0]), int(center[1])
    s = float(size)
    drawer = _ICONS.get(name)
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


# 卡名 -> 图案。没配到的走 _icon_fallback（问号圆盘），
# 这样以后加新卡忘了补图案时能一眼看出来，而不是静默留白。
_ICONS = {
    "加一":   _icon_plus,
    "凑十":   _icon_ten,
    "平方":   _icon_square,
    "未知数": _icon_unknown,
    "三角盾": _icon_triangle_shield,
    "方阵":   _icon_grid,
    "镜像":   _icon_mirror,
    "归零":   _icon_zero,
    "反证":   _icon_contradiction,
    "换元":   _icon_substitute,
}


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
}


def enemy_style(kind):
    return ENEMY_STYLE.get(kind, ENEMY_STYLE["battle"])


def draw_enemy(screen, kind, center, r, t_ms=0):
    """按敌人档次画形象。r 是"体型半径"，一切按它比例缩放。

    三档各有各的视觉母题，和它们的名字对应：
        battle 几何魔像   —— 多边形一层层堆起来的石像
        elite  方程组·三元 —— 三个圆互相连线牵制，解一个才能动下一个
        boss   不可解之影  —— 一个收不拢的漩涡，中心是自己的矛盾
    """
    cx, cy = int(center[0]), int(center[1])
    r = float(r)
    st = enemy_style(kind)
    if kind == "elite":
        _enemy_elite(screen, cx, cy, r, st, t_ms)
    elif kind == "boss":
        _enemy_boss(screen, cx, cy, r, st, t_ms)
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
