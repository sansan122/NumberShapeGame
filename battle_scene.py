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
import art_shapes
import sfx
from player import (Card, DIFF_DESC, card_color, card_soft, difficulty_name,
                    difficulty_tier, type_label)

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
# 深一点的中浅色调，营造「塔内神秘感」；仍是浅底深字，不抢前景可读性
BG_TOP      = (196, 206, 224)   # 背景渐变：顶部偏冷蓝（原 240,244,250 加深）
BG_BOT      = (218, 210, 198)   # 底部偏暖米（原 248,244,238 加深）
FLOOR       = (186, 194, 208)   # 地面 / 地平线（原 226,232,240 加深）
DECO_SYMBOL = (178, 188, 206)   # 漂浮数学符号（随背景一起加深，仍淡）
DECO_LINE   = (196, 204, 218)   # 背景网格（比符号更淡，隐隐一层）
DECO_GRAPH  = (170, 180, 200)   # 几何图形描边（略深，动起来时可见）
DECO_FORMULA= (160, 170, 192)   # 公式文字（最清晰的一层装饰）
# ---- 坐标系（背景里的函数要「画在坐标轴上」）----
AXIS_COL    = (172, 182, 204)   # 坐标轴 / 刻度 / x·y·O 标注
PLANE_GRID  = (205, 212, 226)   # 坐标系内部的单位网格（最淡的一层）
CURVE_COL   = (145, 157, 187)   # 函数曲线（坐标系里最醒目的元素，仍淡于前景）
DECO_LABEL  = (158, 169, 194)   # 坐标系角落的函数名

#: 背景里的两个坐标系：左 = y=sin x（曲线横向流动），右 = y=x²（开口呼吸）
#  矩形是「图纸」范围，曲线超出部分会被裁掉，所以不会有线头飞到坐标系外面。
#  左右边界是量出来的，不是拍的：
#    左 ≥ 448 —— 三个角色所有动作帧的立绘像素最右到 x=444（实测 union），
#                再往左摆就会被角色压住；
#    右 ≤ 886 —— Boss 体型半径 100、E_X=1000，最左到 x=900；
#    中间让开 x=640 的「对决区」中线（占 639~641）。
SIN_PLANE  = pygame.Rect(450, 126, 186, 148)
SIN_ORIGIN = (480, 200)         # 正弦的原点（轴的中点，波绕着它上下摆）
SIN_UNIT   = 19                 # 正弦：1 个数学单位 19px，横向约 1.55 个周期
PAR_PLANE  = pygame.Rect(662, 126, 224, 148)
PAR_ORIGIN = (774, 250)         # 抛物线的原点放在底部中央，开口朝上
PAR_UNIT   = 21                 # 抛物线：1 个单位 21px，呼吸到最陡也留在框内

#: 漂浮符号：(字符, 屏幕x, 屏幕y)。刻意避开两个坐标系占的中间带
#  （x450~886 / y126~274），所以全挤在「顶栏之下、图纸之上」那条 74px 窄带、
#  左右边缘、以及图纸下方的空档里。字号 52 正好塞进那条窄带。
DECO_SYMBOLS = [
    ("∑", 110, 84), ("π", 250, 84), ("√", 330, 92), ("∞", 960, 90),
    ("∫", 1150, 84), ("θ", 1230, 118),
    ("△", 62, 300), ("α", 170, 440),
    ("λ", 368, 444), ("φ", 596, 322),
]
DECO_SYMBOL_SIZE = 52


# ==================== 打击感（视觉侧） ====================
# 「打击感」一半靠音效，另一半靠画面。这一节是视觉侧的三件套：
# 屏幕震动、受击闪白、飘出的伤害数字。
#
# 三者**共用同一张伤害分档表**（DMG_TIERS）：打 4 点和打 81 点，听到的
# 声音、抖的幅度必须是同一档 —— 否则会出现「听到轻击、画面却大地震」
# 这种对不上的情况，玩家立刻就觉得假。

#: 屏幕震动：持续时长（秒）与幅度上限（像素）
SHAKE_LIFE = 0.30
SHAKE_MAX = 15.0
#: 受击闪白 / 玩家挨打时整屏泛红的持续时长
FLASH_LIFE = 0.14
HURT_LIFE = 0.34
#: 飘字存活时长 / 上升像素
POP_LIFE = 0.85
POP_RISE = 52.0

#: 伤害分档：(伤害上限, 音效名, 震动幅度)。上限 None = 不封顶那一档。
#:
#: 幅度差做得很明显 —— 1~6 点几乎不振（1.5px，只是「有反馈」），
#: 81 点的平方组合振满 15px。差了 10 倍，玩家不看数字也知道这一下有多重。
DMG_TIERS = (
    (6, "hit_light", 1.5),
    (14, "hit_mid", 4.0),
    (29, "hit_heavy", 8.5),
    (None, "hit_massive", SHAKE_MAX),
)


def impact_tier(dmg):
    """按伤害量选「音效 + 震动幅度」，返回 (音效名, 像素)。

    音效和震动**从这里一起取**，就是为了保证两者永远同档 ——
    分成两处各判一次，早晚有人改了一处忘了另一处。
    """
    for cap, name, mag in DMG_TIERS:
        if cap is None or dmg <= cap:
            return name, mag
    return DMG_TIERS[-1][1], DMG_TIERS[-1][2]


def deco_symbol_offset(i, t_ms):
    """第 i 个漂浮符号在 t_ms 时的纵向漂移量（像素）。

    每个符号相位不同、幅度 6~12px 不等，看着才像各自漂浮。
    提成模块函数是为了让测试脚本能用同一份公式复算符号的活动范围，
    免得「代码改了公式、测试还在按旧范围检查」。
    """
    return int((6 + (i % 3) * 3) * math.sin(t_ms / 1400.0 + i * 0.7))


#: 符号漂移的最大幅度（上界，测试用来框出活动范围）
DECO_SYMBOL_MAX_DRIFT = 12

#: 公式小字：(文本, 屏幕x, 屏幕y)，同样避开图纸
DECO_FORMULAS = [
    ("E = mc²", 398, 62), ("a² + b² = c²", 838, 62),
    ("πr²", 566, 100), ("√2", 700, 90),
    ("y = f(x)", 600, 398), ("d/dx", 468, 448),
    ("Σ", 830, 428), ("lim", 700, 458),
]
DECO_FORMULA_SIZE = 22

#: 几何「形」装饰：(锚点x, 锚点y, 半宽, 半高)。半宽/半高取运动到极值时的外接框，
#  用来保证它们不会转着转着扫进坐标系里。
DECO_SHAPES = {
    "circle":   (478, 90, 31, 31),     # 半径呼吸的圆
    "rings":    (398, 358, 30, 30),    # 同心圆 + 绕圈卫星点
    "square":   (528, 350, 28, 28),    # 自转的正方形（转 45° 时外接半径最大）
    "triangle": (884, 348, 22, 34),    # 上下浮动的三角形
}
GLOW_ALLY   = (168, 196, 226)   # 玩家头像外圈光晕
GLOW_FOE    = (224, 186, 186)   # 敌人头像外圈光晕
BATTLE_LINE = (188, 194, 208)   # 中央对决区底衬

WIDTH, HEIGHT = 1280, 720
CARD_W, CARD_H = 132, 176


# ==================== 敌人配置 ====================
# relic / upgrade：打完这一档敌人之后，战利品面板发几件遗物、送几次强化。
# 精英那行是兑现 tower.yaml 里写的「阶段化敌人，掉落遗物」——
# 以前这里只有 gold，遗物和强化一句都没落地，玩家打完精英两手空空。
ENEMY_KINDS = {
    "battle": {
        "name": "几何魔像",
        "hp": 50,
        "desc": "由最基础的多边形堆成",
        "gold": 28,
        "relic": 0,
        "upgrade": 0,
    },
    "elite": {
        "name": "方程组·三元",
        "hp": 78,
        "desc": "三个未知数互相牵制，解开一个才能动下一个",
        "gold": 55,
        "relic": 1,
        "upgrade": 1,
    },
    "boss": {
        "name": "不可解之影",
        "hp": 120,
        "desc": "它本身就是那个矛盾",
        "gold": 120,
        "relic": 1,
        "upgrade": 2,
    },
}


def sieved_card(deck):
    """遗物「质数筛」：从牌库里挑出最弱的一张（只读，不改 deck）。

    强弱只看固定收益量：伤害 + 格挡。抽牌 / 清格挡这类功能卡没有数值，
    权重记 0 —— 它们本来就在「弱」那一档，被筛掉不冤。
    牌库为空返回 None。
    """
    if not deck:
        return None
    return min(deck, key=lambda c: c.effect.get("dmg", 0)
                                    + c.effect.get("block", 0))


# ==================== 题目（四种题型）====================
def _darken(col, f=0.78):
    """按钮 hover / 按下时的暗调色（从主色派生，不写死颜色）。"""
    return tuple(int(c * f) for c in col[:3])


# 想打出一张卡就得先答题，这是本作的核心。题型和出牌方式一一对应：
#   数字卡单独打出        -> 算术题（难度由卡上的数字决定，见下面）
#   图形卡单独打出        -> 认图形名称（图形卡上没有数字，出算术题无从下手）
#   数字卡 + 图形卡组合   -> 算图形面积（数字卡上的数就是图形上的边）
#   数字卡 + 平方组合     -> 算这个数的平方（伤害＝平方）
#
# π 取 3：圆面积要能整除，不然「算对」变成一道小数题，小学生直接卡住。
PI_APPROX = 3

#: 面积题的数值上限：数字卡的值不会超过它（输入框最多 4 位，面积必须装得下）
MAX_SHAPE_SIDE = 12

#: 组合成功打出省下的能量（两张卡费用之和 − 这个数）。
#  组合要花两张卡、答一道更难的题，还只占一次出牌机会 —— 不打折没人用。
COMBO_DISCOUNT = 1


def combo_cost(a, b):
    """一次组合的能量费用：两张卡费用之和 − COMBO_DISCOUNT。

    最低 1 点：组合再便宜也不能变成 0 费白嫖（0 费意味着「反正不要钱，
    每回合先点一下试试」，出牌的取舍就没了）。
    """
    return max(1, a.cost + b.cost - COMBO_DISCOUNT)


# ---------- 算术题：难度跟着数字卡的数字走 ----------
# 数字越大，式子越长、用到的运算越多，9 号牌甚至要带括号。难度阶梯的定义
# 在 player.DIFF_TIER（卡面标签、题目标题、测试都从那一份读）。

#: 运算优先级 —— 渲染括号时用（"÷" 和 "×" 同级）
_PREC = {"+": 1, "-": 1, "×": 2, "÷": 2}


def _add_pair(rng, lo, hi):
    """两个正整数相加，和落在 [lo, hi]。"""
    total = rng.randint(max(2, lo), hi)
    a = rng.randint(1, total - 1)
    return a, total - a


def _sub_pair(rng, a_lo, a_hi):
    """a - b，差 ≥ 1：不出负数，也不出 0 这种"算了等于没算"的答案。"""
    a = rng.randint(max(2, a_lo), a_hi)
    return a, rng.randint(1, a - 1)


def _div_pair(rng, q_lo, q_hi, b_lo=2, b_hi=9):
    """按「商 × 除数」倒着造被除数 —— 这样除法永远除得尽，答案一定是整数。"""
    q = rng.randint(q_lo, q_hi)
    b = rng.randint(b_lo, b_hi)
    return b * q, b


def _build_expr(tier, rng=random):
    """按难度档造一棵表达式树：(运算符, 左, 右)，叶子是整数。

    为什么造树、不拼字符串：答案用同一棵树递归算（_eval_expr），题面也用
    同一棵树渲染（_expr_text），**题面和答案不可能对不上**；括号由渲染函数
    按优先级自动补，不用手写、也不会多算少算。

    所有式子都是「构造保证」的：答案是非负整数、除法整除、不会出现小数和
    负数。所以这里没有「算完发现不合规就重掷」的兜底 —— 那种兜底在参数
    极端时会死循环，而这里靠的是取数时就卡住范围。
    """
    if tier <= 0:                                  # 最简：一位数加法，和 ≤ 5
        a, b = _add_pair(rng, 2, 5)
        return ("+", a, b)

    if tier == 1:                                  # 10 以内加减
        if rng.random() < 0.6:
            a, b = _add_pair(rng, 3, 10)
            return ("+", a, b)
        a, b = _sub_pair(rng, 4, 10)
        return ("-", a, b)

    if tier == 2:                                  # 20 以内加减 + 一位数乘法
        r = rng.random()
        if r < 0.4:
            a, b = _add_pair(rng, 8, 20)
            return ("+", a, b)
        if r < 0.7:
            a, b = _sub_pair(rng, 9, 20)
            return ("-", a, b)
        return ("×", rng.randint(2, 9), rng.randint(2, 9))

    if tier == 3:                                  # 四则：两位数加减 / 乘 / 整除
        r = rng.random()
        if r < 0.3:
            a, b = _add_pair(rng, 20, 60)
            return ("+", a, b)
        if r < 0.55:
            a, b = _sub_pair(rng, 25, 60)
            return ("-", a, b)
        if r < 0.8:
            return ("×", rng.randint(3, 12), rng.randint(3, 9))
        a, b = _div_pair(rng, 2, 9)
        return ("÷", a, b)

    if tier == 4:                                  # 两步四则：先乘除后加减
        r = rng.random()
        a, b = rng.randint(3, 9), rng.randint(3, 9)
        if r < 0.35:
            return ("+", ("×", a, b), rng.randint(2, 20))
        if r < 0.6:
            return ("-", ("×", a, b), rng.randint(2, a * b - 1))
        d, e = _div_pair(rng, 3, 9, 3, 9)
        if r < 0.8:
            return ("+", ("÷", d, e), rng.randint(2, 20))
        return ("-", ("÷", d, e), rng.randint(1, d // e - 1))

    # tier 5：带括号的两三步式（最难的一档，配 9 号牌）
    r = rng.random()
    if r < 0.3:                                    # (a + b) × c
        a, b = _add_pair(rng, 5, 15)
        return ("×", ("+", a, b), rng.randint(2, 6))
    if r < 0.55:                                   # a × (b − c)
        b = rng.randint(6, 15)
        return ("×", rng.randint(2, 6), ("-", b, rng.randint(2, b - 2)))
    if r < 0.8:                                    # (a + b) ÷ c，保证整除
        c = rng.randint(2, 6)
        s = c * rng.randint(3, 9)
        a = rng.randint(1, s - 1)
        return ("÷", ("+", a, s - a), c)
    a, b = rng.randint(3, 9), rng.randint(3, 9)    # a × b − (c + d)
    c, d = _add_pair(rng, 3, max(4, a * b - 2))
    return ("-", ("×", a, b), ("+", c, d))


def _expr_text(node, parent_prec=0, tight=False):
    """把表达式树渲染成题面文字，按优先级自动补括号。

    parent_prec 是父式子的优先级；tight 表示「这个子式子落在父算子的右边，
    而父算子是 - 或 ÷」—— 这时同优先级也必须补括号：
    8 - (2 + 3) 和 8 - 2 + 3 不是一回事。
    """
    if isinstance(node, int):
        return str(node)
    op, left, right = node
    prec = _PREC[op]
    ls = _expr_text(left, prec, False)
    rs = _expr_text(right, prec, op in ("-", "÷"))
    text = "%s %s %s" % (ls, op, rs)
    if prec < parent_prec or (tight and prec == parent_prec):
        return "(" + text + ")"
    return text


def _eval_expr(node):
    """算这棵树的值（题面怎么写的，就算成什么 —— 答案的唯一来源）。"""
    if isinstance(node, int):
        return node
    op, left, right = node
    a, b = _eval_expr(left), _eval_expr(right)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "×":
        return a * b
    return a // b                     # 构造保证整除，不会丢小数


def make_arith(tier, rng=random):
    """出一道算术题，返回 (题面文字, 答案)。测试脚本也用它。"""
    node = _build_expr(tier, rng)
    return _expr_text(node), _eval_expr(node)


def combo_kind(a, b):
    """两张卡能不能组合、组合出哪一类题 —— 组合机制的唯一判据。

    返回：
      "area"   数字 + 图形 -> 算图形面积
      "square" 数字 + 平方 -> 算这个数的平方
      None     不能组合（两张同类卡；或者平方配图形 —— 凑不出一对新题面）
    """
    types = {a.ctype, b.ctype}
    if types == {"number", "shape"}:
        return "area"
    if types == {"number", "op"}:
        return "square"
    return None


def is_combo_types(a, b):
    """老名字（早期只有面积题那一类组合时留下的）：能不能组合。"""
    return combo_kind(a, b) is not None


def roll_shape_dims(shape, v, rng=random):
    """给面积题掷一组尺寸，返回 (dims, 面积)。

    硬约束（都有测试盯着）：
      · 尺寸全是正整数；
      · **面积一定是整数** —— 三角形/梯形的高取偶数，÷2 才除得干净；
      · 面积 ≤ 9999（输入框只收 4 位数字）。
    v 是数字卡上的那个数，作为图形的「主尺寸」（底 / 边长 / 长 / 半径）。
    """
    v = max(2, min(int(v), MAX_SHAPE_SIDE))
    if shape == "triangle":
        h = 2 * rng.randint(1, 5)                  # 偶数高 -> 面积整除
        return {"base": v, "height": h}, v * h // 2
    if shape == "square":
        return {"side": v}, v * v
    if shape == "rectangle":
        h = rng.randint(2, 9)
        while h == v:                              # 长宽一样就不是长方形了
            h = rng.randint(2, 9)
        return {"w": v, "h": h}, v * h
    if shape == "parallelogram":
        h = rng.randint(2, 9)
        return {"base": v, "height": h}, v * h
    if shape == "trapezoid":
        top = rng.randint(2, 5)
        bottom = v if v > top else top + rng.randint(1, 4)
        h = 2 * rng.randint(1, 4)                  # 偶数高 -> 面积整除
        return {"top": top, "bottom": bottom, "height": h}, (top + bottom) * h // 2
    # circle（shape 不认识时也走这里：兜底成圆，题目潦草但不会崩）
    return {"r": v}, PI_APPROX * v * v


def shape_dims_text(shape, dims):
    """面积题题面上那行尺寸描述。"""
    if shape in ("triangle", "parallelogram"):
        return "底 %g，高 %g" % (dims["base"], dims["height"])
    if shape == "square":
        return "边长 %g" % dims["side"]
    if shape == "rectangle":
        return "长 %g，宽 %g" % (dims["w"], dims["h"])
    if shape == "trapezoid":
        return "上底 %g，下底 %g，高 %g" % (dims["top"], dims["bottom"],
                                          dims["height"])
    if shape == "circle":
        return "半径 %g，π 取 %d" % (dims["r"], PI_APPROX)
    return ""


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

        # ---- 角色被动（trait，文案在 player.CHARACTERS，效果在这里结算）----
        # 三个被动都按 char_id 判断，不额外加存档字段，老存档一样跑得动。
        self.char_id = player.char_id
        # 演算者【直感】：本回合那张「首张数字卡」用掉了没有
        self.first_number_used = False
        # 构形师【承形】：玩家点结束回合那一刻还剩多少格挡
        self.carry_block = 0
        # 解方程者【代入】：每回合抽牌阶段多抽 1 张
        self.draw_bonus = 1 if player.char_id == "solver" else 0

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
        # 遗物「质数筛」：战斗开始时从牌库筛掉 1 张最弱的卡。
        # 必须赶在洗牌抽牌之前做，否则筛掉的可能是已经上手的那张。
        self.sieved = None
        if player.has_relic("质数筛"):
            self.sieved = sieved_card(self.deck)
            if self.sieved is not None:
                self.deck.remove(self.sieved)
        random.shuffle(self.deck)
        self.hand = []
        self.discard = []
        # 发牌不出声（见 draw_cards 里的 _quiet_draw）
        self._quiet_draw = True
        self.draw_cards(5 + self.draw_bonus)
        self._quiet_draw = False

        # ---- 交互 ----
        self.sel_card = None
        self.pending_number = None
        self.log = ["遭遇 %s！算对才能出牌。" % self.e_name]
        if self.sieved is not None:
            self.log.insert(0, "「质数筛」生效：筛掉了「%s」" % self.sieved.name)
        self.quiz = None
        self.combo_hint = ""

        self.done = False
        self.result = None

        # ---- 打击感：震动 / 闪白 / 飘字（见模块顶部那一节）----
        self.shake_t = 0.0            # 震动剩余时长（秒）
        self.shake_mag = 0.0          # 这次震动多大
        self.e_flash = 0.0            # 敌人闪白剩余时长
        self.hurt_flash = 0.0         # 玩家挨打时整屏泛红剩余时长
        self.pops = []                # 飘字（dict 列表，见 pop()）
        self._canvas = None           # 震动用的离屏画布（惰性创建，见 draw）

        # ---- 遗物效果 ----
        self.extra_block_first = 0
        if player.has_relic("勾股定理"):
            self.extra_block_first = 3
        # 「公理石」的最大生命加成在 Player.add_relic 里结算（拿到就生效），
        # 战斗这边不用管；「质数筛」见上面牌组那一段。

        # ---- 字体 ----
        self.F_BIG = E.load_font(34)
        self.F_MID = E.load_font(22)
        self.F_SML = E.load_font(17)
        self.F_TINY = E.load_font(14)

        # ---- 布局 ----
        self.BTN_END = pygame.Rect(1112, 545, 160, 56)
        self.BTN_SUBMIT = pygame.Rect(560, 492, 160, 46)
        self.QUIZ_BOX = pygame.Rect(380, 300, 520, 290)
        # 图形题（算面积 / 认图形名称）要用更大的框：一题里既要摆得下图形，
        # 又要摆得下选项按钮。算术题那个 520×290 的框塞不下。
        self.QUIZ_BOX_FIG = pygame.Rect(330, 140, 620, 448)

        # ---- 舞台锚点（杀戮尖塔式：角色立于场地左右，血条画在脚边）----
        self.P_X, self.P_FOOT = 250, 486      # 玩家：站位 / 脚底
        self.P_SYM_CY = 360                   # 无立绘时占位圆的圆心
        self.E_X = 1000                       # 敌人站位
        # 敌人体型随档次变大。E_CY 让形象**底边正好踩在 y=486 的地面线上**
        # （和玩家脚底 P_FOOT 同一条线，脚下影子都是 492）。
        # 注意这里曾是 435 - E_R —— 那会让敌人整体浮在地面线上方 57px，
        # 看着像挂在半空（换成几何形象后特别明显）。别改回 435。
        self.E_R = {"battle": 78, "elite": 88, "boss": 100}.get(self.kind, 84)
        self.E_CY = 486 - self.E_R

        self.layout_hand()  # 先算一次手牌位置，保证第一帧点得到

    # ==================== 牌库 ====================
    def draw_cards(self, n):
        """抽 n 张牌。
        注意：这个方法原来叫 draw()，会和「画一帧」的 draw(screen, mouse, t_ms)
        撞名，导致后者被覆盖 —— 所以改名成 draw_cards。"""
        before = len(self.hand)
        for _ in range(n):
            if not self.deck:
                self.deck = self.discard[:]
                self.discard.clear()
                random.shuffle(self.deck)
            if self.deck and len(self.hand) < 8:
                self.hand.append(self.deck.pop())
        # 真抽到牌才出声（牌库和弃牌堆都空的时候硬抽是无声的，别骗玩家）。
        # 开局那一手是「发牌」，不算玩家的操作，所以静音 —— 不然进战斗
        # 先听见一阵唰唰的抽牌声，像玩家自己点了七下。
        if (len(self.hand) > before
                and not getattr(self, "_quiet_draw", False)):
            sfx.play("card_draw", gap_ms=120)

    # ==================== 打击感 ====================
    def shake(self, mag):
        """请求一次屏幕震动。

        取**最大值**而不是累加：连击时如果每一下都往上叠幅度，
        画面会抖到看不清手牌 —— 反馈过度反而妨碍玩家操作。
        """
        if mag > self.shake_mag:
            self.shake_mag = mag
        self.shake_t = SHAKE_LIFE

    def pop(self, text, x, y, col, size=26):
        """在 (x, y) 冒一行会往上飘、会淡出的字。

        文字在**创建时**就渲染好存起来，不是每帧现渲 ——
        飘字带白色描边（要渲两遍），每帧重渲会白白吃掉几毫秒。

        存成 dict 而不是「(图, 边, x, y, t)」这种元组：元组要靠下标读，
        以后加一个字段（比如「跟谁一起飘」）就得把所有下标数一遍，
        改漏一处就是画错位置。名字长一点，但不会错。
        """
        font = E.load_font(size, bold=True)
        self.pops.append({
            "text": text,
            "surf": font.render(text, True, col),
            "edge": font.render(text, True, (255, 255, 255)),
            "x": float(x),
            "y": float(y),
            "t": 0.0,
        })

    def update_fx(self, dt):
        """推进震动 / 闪白 / 飘字的生命周期。"""
        if self.shake_t > 0.0:
            self.shake_t = max(0.0, self.shake_t - dt)
            if self.shake_t == 0.0:
                self.shake_mag = 0.0
        if self.e_flash > 0.0:
            self.e_flash = max(0.0, self.e_flash - dt)
        if self.hurt_flash > 0.0:
            self.hurt_flash = max(0.0, self.hurt_flash - dt)
        if self.pops:
            alive = []
            for p in self.pops:
                p["t"] += dt
                if p["t"] < POP_LIFE:
                    alive.append(p)
            self.pops = alive

    def draw_pops(self, screen):
        """画飘字：先快后慢地上升，后 45% 淡出。"""
        for p in self.pops:
            k = p["t"] / POP_LIFE
            yy = int(p["y"] - POP_RISE * (1.0 - (1.0 - k) ** 2))
            surf, edge = p["surf"], p["edge"]
            if k > 0.55:
                # 淡出用 set_alpha（临时改一下，画完恢复），不复制 Surface
                surf.set_alpha(max(0, int(255 * (1.0 - (k - 0.55) / 0.45))))
            r = surf.get_rect(center=(p["x"], yy))
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                screen.blit(edge, r.move(dx, dy))
            screen.blit(surf, r)
            surf.set_alpha(255)

    def draw_overlays(self, screen):
        """受击闪白（敌人）/ 挨打泛红（整屏）。画在最上层。"""
        if self.e_flash > 0.0:
            a = 200.0 * (self.e_flash / FLASH_LIFE)
            r0 = self.E_R + 26
            # 三层同心圆叠出「由内向外衰减」的柔边。
            # 直接画一个实心白圆会露出一圈生硬的白边，看着像在敌人身上
            # 贴了张白纸；打击感要的是「闪一下」，不是「糊一块白的」。
            veil = pygame.Surface((r0 * 2, r0 * 2), pygame.SRCALPHA)
            for k, f in ((1.00, 0.30), (0.80, 0.30), (0.58, 0.35)):
                pygame.draw.circle(veil, (255, 255, 255, int(a * f)),
                                   (r0, r0), int(r0 * k))
            screen.blit(veil, (self.E_X - r0, self.E_CY - r0))
        if self.hurt_flash > 0.0:
            a = int(78 * (self.hurt_flash / HURT_LIFE))
            if a > 0:
                v = self._red_veil()
                v.set_alpha(a)
                screen.blit(v, (0, 0))

    def _red_veil(self):
        """整屏泛红用的纯色层（建一次就够，逐帧只改 alpha）。"""
        if getattr(self, "_veil", None) is None:
            self._veil = pygame.Surface((WIDTH, HEIGHT))
            self._veil.fill((188, 44, 44))
        return self._veil

    def _canvas_surface(self):
        """震动用的离屏画布（惰性创建：不抖的战斗一帧都不会多花这块内存）。"""
        if self._canvas is None:
            self._canvas = pygame.Surface((WIDTH, HEIGHT))
        return self._canvas

    def _shake_offset(self, t_ms):
        """当前帧的屏幕偏移量。

        偏移量用两个不同频率的正弦合成，**不要用 random**：
        随机数每帧乱跳看着像花屏/掉帧，正弦是连续来回，
        才像「被砸得晃了一下」。
        """
        if self.shake_t <= 0.0:
            return 0, 0
        k = self.shake_t / SHAKE_LIFE            # 1 -> 0
        m = self.shake_mag * k * k               # 二次衰减：起手猛，很快收住
        return (int(m * math.sin(t_ms * 0.085)),
                int(m * math.cos(t_ms * 0.117)))

    def hit_feedback(self, dmg, actual, x=None, y=None):
        """一次伤害的全部反馈：音效 + 震动 + 闪白 + 飘字。**只走这一条路**。

        三个调用方（单卡 / 面积组合 / 平方组合）都收敛到这里，
        所以「81 点打得比 4 点狠」这件事只有一份实现。

        dmg    本次基础伤害（含加成，用来分档）
        actual 真正打掉的血（被格挡减过，可能是 0）
        """
        if x is None:
            x = self.E_X
        if y is None:
            y = self.E_CY - self.E_R - 12

        if actual <= 0:
            # 全被格挡挡下了：金属「铛」+ 不震屏（没打穿，不该有分量感）
            sfx.play("hit_block", gap_ms=0)
            self.pop("格挡", x, y - 16, ACCENT, 24)
            self.e_flash = FLASH_LIFE * 0.5
            return

        name, mag = impact_tier(dmg)
        sfx.play(name, gap_ms=0)
        self.shake(mag)
        self.e_flash = FLASH_LIFE
        # 飘字字号跟着伤害长：打 4 点是 24 号，打 81 点是 46 号
        size = int(min(46, 23 + actual * 0.55))
        self.pop("−%d" % actual, x, y, RED, size)
        if dmg >= 30:
            # 巨额伤害再补一行「暴击式」的赞美，强化「这一下很大」的感觉
            self.pop("厉害！", x, y + 40, AMBER, 26)

    # ==================== 出题 ====================
    #: 平方题的示例用哪几个数（示例必须避开本题要算的那个数 —— 否则
    #  直接把答案摆在例题里了）
    SQUARE_DEMO_POOL = (2, 3, 4, 5)

    def make_quiz(self, card):
        """算术题 —— 单独打出一张数字卡时的题型。

        题目难度由**卡上的数字**决定：0 号牌是一位数加法，9 号牌要算带
        括号的四则式（台阶见 player.DIFF_TIER）。数字越大打得越疼，
        题目也越费脑子 —— 手牌里选哪张打，就是在选「做多难的题」。

        （保留这个名字：它一直是「单卡出牌」的入口，测试脚本也在调它。）
        """
        tier = difficulty_tier(card.value)
        expr, ans = make_arith(tier)
        return {"kind": "arith", "expr": expr, "ans": ans, "tier": tier,
                "input": "", "card": card, "cards": [card],
                "submit_rect": self.BTN_SUBMIT}

    def make_area_quiz(self, number_card, shape_card):
        """组合出牌（数字卡 + 图形卡）的题：**算这个图形的面积**。

        数字卡上的那个数就是图形上的「主尺寸」（底 / 边长 / 长 / 半径），
        另一维随机 —— 这就是「数形结合」四个字的字面意思：数变成形，形算回数。
        面积公式写在题面上，玩家不用背公式，要算的是数。
        """
        shape = art_shapes.shape_of_card(shape_card.name) or "square"
        dims, ans = roll_shape_dims(shape, number_card.value)
        return {"kind": "area", "shape": shape, "dims": dims, "ans": ans,
                "input": "", "card": number_card,
                "cards": [number_card, shape_card],
                "submit_rect": self._area_submit_rect()}

    def make_square_quiz(self, number_card, square_card):
        """「平方」+ 数字卡的题：先看两个例子，再算这个数的平方。

        例子（2² = 2 × 2 = 4 …）把「平方＝自己乘自己」这条规则讲完，
        本题要算的就是**数字卡上那个数**的平方。所以这张牌的强弱完全跟着
        数字卡走：配 9 号牌是 9 × 9 = 81，配 0 号牌还是 0 —— 越小越白给，
        越大越赚，而题面长度始终只有「乘法」这一档。
        """
        n = int(number_card.value)
        demos = [d for d in self.SQUARE_DEMO_POOL if d != n][:2]
        return {"kind": "square", "n": n, "ans": n * n, "demos": demos,
                "input": "", "card": number_card,
                "cards": [number_card, square_card],
                "submit_rect": self._square_submit_rect()}

    def make_name_quiz(self, shape_card):
        """图形卡单独打出时的题：**认出这是什么图形**（四选一）。

        图形卡上没有数字（value 恒为 0），出算术题无从下手；出认图形
        既贴「形」这条线，又不用玩家在 720p 窗口里手打中文。
        """
        shape = art_shapes.shape_of_card(shape_card.name) or "square"
        right = art_shapes.shape_cn(shape)
        pool = [n for n in art_shapes.SHAPE_NAMES if n != right]
        options = [right] + random.sample(pool, min(3, len(pool)))
        random.shuffle(options)
        return {"kind": "name", "shape": shape, "options": options,
                "ans_idx": options.index(right), "pick": None,
                "input": "", "card": shape_card, "cards": [shape_card],
                "option_rects": self._name_option_rects(len(options)),
                "submit_rect": self._fig_submit_rect("name")}

    def _fig_submit_rect(self, kind):
        """认图形题的提交按钮位置（面积题的按钮跟着填空线走，见下）。"""
        box = self.QUIZ_BOX_FIG
        return pygame.Rect(box.centerx - 70, box.y + 372, 140, 40)

    def _area_submit_rect(self):
        """面积题的提交按钮：跟在填空线右侧，输入和提交挤在同一行，
        省下的纵向空间留给图形本身。"""
        box = self.QUIZ_BOX_FIG
        row_y = box.y + 358
        lw = self.F_MID.size("S =")[0]
        total = lw + 10 + 130 + 26 + 130
        x0 = box.centerx - total // 2
        return pygame.Rect(x0 + lw + 10 + 130 + 26, row_y, 130, 40)

    def _square_submit_rect(self):
        """平方题的提交按钮：在例题框和填空行下面居中。"""
        box = self.QUIZ_BOX_FIG
        return pygame.Rect(box.centerx - 78, box.y + 330, 156, 46)

    def _name_option_rects(self, n):
        """认图形题的选项按钮：两列网格，居中排。"""
        box = self.QUIZ_BOX_FIG
        w, h, gap = 250, 52, 18
        out = []
        for i in range(n):
            row, col = i // 2, i % 2
            cnt = min(2, n - row * 2)          # 奇数个时最后一行居中
            total = cnt * w + (cnt - 1) * gap
            x0 = box.centerx - total // 2
            out.append(pygame.Rect(x0 + col * (w + gap),
                                   box.y + 240 + row * (h + gap), w, h))
        return out

    def _quiz_pop_y(self, q):
        """答题反馈的飘字该出现在哪个高度：正好压在题目框上方。

        算术题用小的 QUIZ_BOX（y=300），其它三种用大的 QUIZ_BOX_FIG（y=140），
        所以高度必须按题型算 —— 写死一个值必然有一种题型被框压住。
        """
        box = (self.QUIZ_BOX if q.get("kind", "arith") == "arith"
               else self.QUIZ_BOX_FIG)
        return box.top - 30

    def submit_quiz(self):
        """交卷判题。四种题型的对错判定不一样，答对之后的结算也不一样：
        算术题 / 认图形 -> 单卡结算；面积题 / 平方题 -> 两张卡一起结算。"""
        q = self.quiz
        if q is None:
            return
        kind = q.get("kind", "arith")

        if kind == "name":
            correct = q.get("pick") == q["ans_idx"]
        else:
            try:
                got = int(q["input"]) if q["input"] else None
            except ValueError:
                got = None
            correct = got == q["ans"]

        if correct:
            # 组合题（面积 / 平方）用更华丽的 combo_ok：组合要花两张卡、
            # 答一道更难的题，反馈必须明显比单卡更强，玩家才觉得划算。
            # 它紧接着还会叠一发 hit_massive，两段自然连成
            # 「组合成立 → 重锤落下」，这是全游戏最爽的一拍。
            sfx.play("combo_ok" if kind in ("area", "square") else "answer_ok",
                     gap_ms=0)
            self.pop("答对了！", WIDTH // 2, self._quiz_pop_y(q), GREEN, 30)
            if kind == "arith":
                self.log.insert(0, "✓ %s = %d　算对了！" % (q["expr"], q["ans"]))
                self.resolve_card(q["card"])
            elif kind == "area":
                self.log.insert(0, "✓ 面积 %d　数形结合成立！" % q["ans"])
                self.resolve_combo(q["cards"][0], q["cards"][1])
            elif kind == "square":
                self.log.insert(0, "✓ %d² = %d × %d = %d　平方成立！"
                                % (q["n"], q["n"], q["n"], q["ans"]))
                self.resolve_square(q["cards"][0], q["cards"][1])
            else:
                self.log.insert(0, "✓ 这是%s　认对了！"
                                % q["options"][q["ans_idx"]])
                self.resolve_card(q["card"])
        else:
            # 答错音刻意做得柔和（见 sfx.answer_no）：卡牌失效的惩罚已经
            # 够重了，再来一记刺耳蜂鸣，下次孩子就不敢点提交了。
            sfx.play("answer_no", gap_ms=0)
            self.pop("再想想～", WIDTH // 2, self._quiz_pop_y(q), RED, 26)
            if kind == "arith":
                self.log.insert(0, "✗ %s = %d　算错了，卡牌失效"
                                % (q["expr"], q["ans"]))
            elif kind == "area":
                self.log.insert(0, "✗ 面积算错了（正解 %d）　两张卡一起失效"
                                % q["ans"])
            elif kind == "square":
                self.log.insert(0, "✗ %d 的平方是 %d × %d = %d　两张卡一起失效"
                                % (q["n"], q["n"], q["n"], q["ans"]))
            else:
                self.log.insert(0, "✗ 这不是%s　卡牌失效"
                                % q["options"][q["ans_idx"]])
            # 遗物「换元法」：每回合第一次算错不消耗卡牌
            if (self.player.has_relic("换元法") and
                    not getattr(self, "_eq_used", False)):
                self._eq_used = True
                n_cards = len(q.get("cards", [q["card"]]))
                self.log.insert(0, "「换元法」生效：这%s被留下了"
                                % ("两张卡都" if n_cards > 1 else "张卡"))
                for c in q.get("cards", [q["card"]]):
                    c.selected = False
            else:
                for c in q.get("cards", [q["card"]]):
                    if c in self.hand:
                        self.hand.remove(c)
                    self.discard.append(c)
        self.quiz = None
        self.check_end()

    # ==================== 出牌结算 ====================
    def _settle_card(self, card, dmg_override=None):
        """结算一张卡的效果（伤害 / 格挡 / 抽牌 / 清格挡）。

        单卡出牌、面积组合、平方组合**都走这里** —— 遗物加成
        （约等号 / 勾股定理）和角色被动（直感）只有这一份实现，
        三条路不会算出三套数值。

        dmg_override：把这张卡的基础伤害换成别的数。平方组合用它把
        「数字卡自己的 9 点」换成「9² = 81」；传 None 就按卡面结算。
        这个方法只管效果，不管弃牌、不管胜负（那是调用方的事）。
        """
        eff = card.effect
        # 这张牌这次实际能打出的基础伤害：平方组合会把它换成 n²。
        base = eff.get("dmg", 0) if dmg_override is None else dmg_override
        # 伤害为 0 的牌**不吃任何伤害加成**（约等号 / 直感）：
        # 「0² = 0」就该是 0，给一张没有伤害的牌 +1，玩家只会觉得账算不清。
        has_dmg = base > 0
        bonus = 0
        if self.player.has_relic("约等号") and has_dmg:
            bonus = 1
        # 演算者【直感】：每回合打出的第一张数字卡伤害 +1。
        # 判定放在这里而不是 submit_quiz —— 算对才叫「打出」，
        # 不然算错一次就把直感白嫖掉了。
        if (self.char_id == "calculator" and card.ctype == "number"
                and has_dmg and not self.first_number_used):
            bonus += 1
            self.first_number_used = True
            self.log.insert(0, "「直感」生效：本回合首张数字卡 +1 伤害")

        if has_dmg:
            dmg = base + bonus
            actual = max(0, dmg - self.e_block)
            self.e_block = max(0, self.e_block - dmg)
            self.e_hp -= actual
            self.p_anim.play("attack")     # 打出伤害 -> 播攻击动作
            self.log.insert(0, "造成 %d 点伤害" % actual)
            # 打击反馈的**唯一出口**：音效分档 + 震屏 + 闪白 + 飘字。
            # 单卡 / 面积组合 / 平方组合三条路都汇到这一句，所以
            # 「81 点比 4 点打得狠」这件事只有一份实现，不可能走偏。
            self.hit_feedback(dmg, actual)

        if "block" in eff:
            gain = eff["block"]
            # 遗物「勾股定理」：本回合首次图形卡额外格挡
            if card.ctype == "shape" and self.extra_block_first > 0:
                gain += self.extra_block_first
                self.extra_block_first = 0
                self.log.insert(0, "「勾股定理」生效：+3 格挡")
            self.p_block += gain
            self.log.insert(0, "获得 %d 点格挡" % gain)
            # 上盾和被敲是两件事，用两个不同的音（shield ≠ hit_block）
            sfx.play("shield", gap_ms=0)
            self.pop("+%d 格挡" % gain, self.P_X + 96, self.P_SYM_CY - 30,
                     ACCENT, 22)

        if "draw" in eff:
            self.draw_cards(eff["draw"])
            self.log.insert(0, "抽了 %d 张牌" % eff["draw"])

        if eff.get("strip"):
            self.e_block = 0
            self.log.insert(0, "清空了敌人的格挡")
            sfx.play("hit_block", vol=0.7, gap_ms=0)

    def resolve_card(self, card):
        """单卡生效（算术题 / 认图形题答对之后）。"""
        self._settle_card(card)
        if card in self.hand:
            self.hand.remove(card)
        self.discard.append(card)

        # 打完就要立刻结算胜负：不然把敌人打死之后
        # 战斗不会结束，还得等到「结束回合」才判胜。
        self.check_end()

    def resolve_combo(self, number_card, shape_card):
        """「数形结合」生效：数字卡 + 图形卡一起算对面积之后走这里。

        两张卡的效果**同时生效**，另外多抽 1 张牌 —— 一次组合要花两张卡、
        两份能量、还只占一次出牌机会，不补一张手牌的话，
        组合永远不如拆成两回合打，那这个机制就是个摆设。
        """
        self._settle_card(number_card)
        self._settle_card(shape_card)
        self.draw_cards(1)
        self.log.insert(0, "「数形结合」奖励：额外抽 1 张牌")
        for c in (number_card, shape_card):
            if c in self.hand:
                self.hand.remove(c)
            self.discard.append(c)
        self.check_end()

    def resolve_square(self, number_card, square_card):
        """「平方」组合生效：数字卡打出的伤害换成**它自己的平方**。

        9 号牌 + 平方 = 81 点伤害（而不是 9 点）——「打出的伤害就是数字牌的
        平方」说的就是这一句。平方卡自己没有伤害（effect 是空的），所以这里
        结算出来的那一份伤害只可能来自数字卡，靠 dmg_override 换过去。

        平方组合**不补牌**（面积组合补 1 张）：它的补偿就是那个平方本身 ——
        9² 顶得上好几张牌，再白送一张手牌就没人愿意老实打数字卡了。
        """
        n = int(number_card.value)
        self._settle_card(number_card, dmg_override=n * n)
        # 平方卡目前没有自己的效果；照常走一遍结算，是为了以后给它加
        # 效果（比如「抽 1 张」「额外 +5」）时不用再改这条路径。
        self._settle_card(square_card)
        for c in (number_card, square_card):
            if c in self.hand:
                self.hand.remove(c)
            self.discard.append(c)
        self.check_end()

    def check_end(self):
        if self.e_hp <= 0:
            self.e_hp = 0
            first = not self.done           # check_end 会被调很多次，只演一次
            self.phase = "win"
            self.result = "win"
            self.done = True
            self.player.gold += self.reward_gold
            self.player.hp = max(0, self.p_hp)
            self.player.log("战斗胜利，+%d 金币" % self.reward_gold)
            if first:
                # 结算演出：敌人倒地 →（0.5s）号角 →（1.05s）金币入袋。
                # 三个音**必须错开**：同时播只会糊成一坨噪音，
                # 而「先后顺序」本身就是一段小小的胜利演出。
                sfx.play("enemy_die", gap_ms=0)
                sfx.play_after("win", 0.5)
                sfx.play_after("coin", 1.05)
        elif self.p_hp <= 0:
            self.p_hp = 0
            first = not self.done
            self.phase = "lose"
            self.result = "lose"
            self.done = True
            self.player.hp = 0
            self.player.log("倒在了 %s 面前" % self.e_name)
            if first:
                # 战败音刻意柔和（见 sfx.lose）：孩子输一局本来就难受，
                # 再来一段沉重的音乐，下次就不想打开了
                sfx.play("lose", gap_ms=0)

    # ==================== 回合 ====================
    def end_turn(self):
        """结束玩家回合 —— 这里**坚决不清格挡**。

        清早了敌人这一下就整打在血上，格挡就变成「只显示、不生效」
        （曾经就是这么错的，玩家进游戏一眼就发现了）。
        格挡要活到 enemy_act() 结算完，新回合开始时才归零。
        构形师【承形】看的正是这一刻还剩多少格挡。
        """
        self.discard.extend(self.hand)
        self.hand.clear()
        self.carry_block = self.p_block if self.char_id == "geometer" else 0
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
                # 挨打反馈：闷响（比打击音柔和一档）+ 整屏泛红 + 飘字。
                # 刻意不震屏 —— 屏幕震动是「我打中了」的爽感，被揍也震
                # 会把这个信号搞混。
                sfx.play("hurt", gap_ms=0)
                self.hurt_flash = HURT_LIFE
                self.pop("−%d" % actual, self.P_X, 248, RED, 26)
            else:
                self.log.insert(0, "敌人攻击，被格挡挡下了")
                sfx.play("hit_block", gap_ms=0)
                self.pop("挡下了", self.P_X, 248, ACCENT, 24)
        elif self.e_intent == "block":
            self.e_block += 8
            self.log.insert(0, "敌人获得 8 点格挡")
            sfx.play("shield", gap_ms=0)
            self.pop("+8 格挡", self.E_X + 96, self.E_CY - self.E_R - 60,
                     ACCENT, 22)
        elif self.e_intent == "buff":
            self.e_intent_val += 3
            self.log.insert(0, "敌人强化，下次攻击 +3")
            sfx.play("upgrade", vol=0.8, gap_ms=0)
            self.pop("强化 +3", self.E_X + 96, self.E_CY - self.E_R - 60,
                     PURPLE, 22)

        self.check_end()
        if self.phase == "enemy":
            self.turn += 1
            self.p_energy = self.p_max_energy
            # 新回合才开始清格挡（上回合留下的格挡不跨回合保留）
            self.p_block = 0
            # 构形师【承形】：上回合结束时有余留格挡 -> 这回合起步先给 2 点
            if self.carry_block > 0:
                self.p_block = 2
                self.log.insert(0, "「承形」生效：+2 格挡")
            self.carry_block = 0
            self.first_number_used = False          # 新回合，直感重置
            self._eq_used = False
            n = 5 + self.draw_bonus + (1 if self.player.has_relic("对数尺") else 0)
            # 回合开始的「叮」比抽牌声早一点，两者才不会糊在一起
            sfx.play("turn_start", gap_ms=0)
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

    # ==================== 选牌 / 组合 ====================
    def clear_selection(self):
        """把手牌上的选中状态全部清掉（取消选择、出牌之后都走这里）。"""
        self.sel_card = None
        self.pending_number = None
        self.combo_hint = ""
        for c in self.hand:
            c.selected = False

    def hint_for(self, card):
        """选中一张卡时的提示语：告诉他下一步能干什么 ——
        这是「组合」这条机制唯一的入口提示，不能省。"""
        if card.ctype == "number":
            return ("已选数字 %d —— 再点图形卡＝算面积，点「平方」＝算 %d²"
                    % (card.value, card.value))
        if card.ctype == "op":
            return "已选「%s」—— 再点数字卡＝算它的平方" % card.name
        return "已选「%s」—— 再点数字卡＝组合（算面积题）" % card.name

    def start_combo(self, card_a, card_b):
        """把选中的两张卡合成一次出牌 —— 组合机制**唯一**的入口。

        先问 combo_kind()：数字 + 图形是「数形结合」（算面积），
        数字 + 平方是「乘方」（算这个数的平方）。费用是两张卡之和
        **减去 1 点**（组合优惠，见 COMBO_DISCOUNT）—— 组合要花两张卡、
        答一道更难的题、还只占一次出牌机会，不打折没人肯用。

        能量不够就把这次组合挡下来，并且**不改变**已选状态 ——
        玩家可以少选一张，或者结束回合。
        """
        kind = combo_kind(card_a, card_b)
        if kind is None:
            return False
        num = card_a if card_a.ctype == "number" else card_b
        other = card_b if card_a.ctype == "number" else card_a
        cost = combo_cost(num, other)
        if self.p_energy < cost:
            self.log.insert(0, "能量不足！组合需要 %d 点能量" % cost)
            sfx.play("ui_deny", gap_ms=0)
            return False
        self.p_energy -= cost
        self.log.insert(0, "组合费用 %d 点能量（%d + %d − %d 优惠）"
                        % (cost, num.cost, other.cost, COMBO_DISCOUNT))
        # 起手先来一段上行蓄力音，把「接下来这一下会很疼」预告出去
        sfx.play("combo_charge", gap_ms=0)
        self.quiz = (self.make_area_quiz(num, other) if kind == "area"
                     else self.make_square_quiz(num, other))
        self.clear_selection()
        return True

    def _quiz_key(self, event):
        """答题时的键盘输入：数字题敲数字，认图形题按 1-4。"""
        q = self.quiz
        if q.get("kind") == "name":
            if event.key == pygame.K_RETURN:
                self.submit_quiz()
            elif event.key == pygame.K_BACKSPACE:
                q["pick"] = None
                sfx.play("key_tap", vol=0.6, gap_ms=40)
            elif event.unicode in ("1", "2", "3", "4"):
                i = int(event.unicode) - 1
                if i < len(q["options"]):
                    q["pick"] = i
                    sfx.play("card_select", vol=0.8, gap_ms=0)
            return
        if event.key == pygame.K_BACKSPACE:
            q["input"] = q["input"][:-1]
            sfx.play("key_tap", vol=0.6, gap_ms=40)
        elif event.key == pygame.K_RETURN:
            self.submit_quiz()
        elif event.unicode.isdigit() and len(q["input"]) < 4:
            q["input"] += event.unicode
            # 每次敲键都出声，但限流 40ms：一秒敲五下听着像机关枪，
            # 那一串「哒哒哒」会盖住答题该有的专注感
            sfx.play("key_tap", vol=0.85, gap_ms=40)

    def _quiz_click(self, mouse):
        """答题弹窗里的点击：认图形题的选项按钮 + 提交按钮。"""
        q = self.quiz
        for i, r in enumerate(q.get("option_rects", [])):
            if r.collidepoint(mouse):
                q["pick"] = i
                sfx.play("card_select", gap_ms=0)
                return
        if q.get("submit_rect", self.BTN_SUBMIT).collidepoint(mouse):
            self.submit_quiz()

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
                self._quiz_key(event)
            elif event.key == pygame.K_ESCAPE:
                self.clear_selection()
            return None

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        # 答题弹窗优先
        if self.quiz is not None:
            self._quiz_click(mouse)
            return None

        if self.phase == "player" and self.BTN_END.collidepoint(mouse):
            sfx.play("ui_click", gap_ms=0)
            self.end_turn()
            return None

        # 手牌点击
        if self.phase == "player":
            for c in self.hand:
                if c.rect and c.rect.collidepoint(mouse):
                    if c.selected:
                        sfx.play("card_deselect", gap_ms=0)
                        self.clear_selection()
                        return None
                    # 已经选了一张，再点**能配对的另一类**卡 -> 组合，
                    # 这一步就是「组合」本身的入口（数字+图形 / 数字+平方）
                    if (self.sel_card is not None and self.sel_card is not c
                            and is_combo_types(self.sel_card, c)):
                        self.start_combo(self.sel_card, c)
                        return None
                    # 选中的时候**不查能量** —— 单张贵不代表组合贵（组合是
                    # 两张之和再减 1）。真花不起的时候，出牌那一步自然会挡。
                    for x in self.hand:
                        x.selected = False
                    c.selected = True
                    self.sel_card = c
                    self.pending_number = c if c.ctype == "number" else None
                    self.combo_hint = self.hint_for(c)
                    # 选卡是最高频的操作，限流 55ms：连点几张时不会叠成噪音
                    sfx.play("card_select", gap_ms=55)
                    return None

            # 点空白 = 打出选中的卡
            if self.sel_card:
                card = self.sel_card
                # 「平方」这类运算卡不能单独打出：它自己不带任何数值，
                # 单独出就是把它白白丢掉（玩家一眼看不出为什么没伤害）。
                if card.ctype == "op":
                    self.log.insert(0, "「%s」不能单出 —— 要配一张数字卡"
                                    % card.name)
                    sfx.play("ui_deny", gap_ms=0)
                    self.pop("不能单出！", self.P_X, self.P_SYM_CY - 120,
                             AMBER, 26)
                    self.clear_selection()
                    return None
                if self.p_energy < card.cost:
                    self.log.insert(0, "能量不足！")
                    sfx.play("ui_deny", gap_ms=0)
                    self.pop("能量不足", self.P_X, self.P_SYM_CY - 120,
                             AMBER, 26)
                    return None
                self.p_energy -= card.cost
                # 图形卡上没有数字，单独打出考「认图形名称」；
                # 数字卡单独打出考算术题（难度看卡上的数字）。
                if card.ctype == "shape":
                    self.quiz = self.make_name_quiz(card)
                else:
                    self.quiz = self.make_quiz(card)
                sfx.play("card_play", gap_ms=0)
                sfx.play_after("quiz_open", 0.12)   # 出牌音之后题目再弹出来
                self.clear_selection()
        return None

    def update(self, dt):
        # 推进打击感特效（震动 / 闪白 / 飘字）
        self.update_fx(dt)
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

        # 2) 地面：底部一条地平线，把手牌区「托」起来
        pygame.draw.rect(screen, FLOOR, (0, HEIGHT - CARD_H - 52, WIDTH, CARD_H + 52))
        pygame.draw.line(screen, (170, 180, 200),
                         (0, HEIGHT - CARD_H - 52), (WIDTH, HEIGHT - CARD_H - 52), 2)

        # 3) 数学装饰：坐标网格 / 函数曲线 / 几何图形 / 公式（都在前景之下）
        self.draw_math_decor(screen, t_ms)

        # 4) 漂浮的数学符号（半透明，慢速上下漂移，呼应「数与形」主题）
        big = E.load_font(DECO_SYMBOL_SIZE)
        for i, (sym, sx, sy) in enumerate(DECO_SYMBOLS):
            dy = deco_symbol_offset(i, t_ms)
            # 半透明：画到一张带 alpha 的临时表面再 blit
            s = big.render(sym, True, DECO_SYMBOL)
            s.set_alpha(90)
            screen.blit(s, s.get_rect(center=(sx, sy + dy)))

    def _coord_plane(self, screen, box, origin, unit, t_ms, kind):
        """画一个「带坐标轴」的函数图，并让曲线在轴内运动。

        参数：
          box    坐标系占的矩形（图纸范围）。整个绘制都套在这一层裁剪里，
                 所以曲线跑到框外会被切掉，不会有一条线头飞出去。
          origin 原点在屏幕上的位置。
          unit   1 个数学单位 = 多少像素。
          kind   "sin"  —— y = 1.55·sin(x − phase)，相位随时间推进，
                          整条波像水波一样横向流动；另有一颗「珠子」固定在
                          x = 6.2 处，随波上下起伏。
                 "parabola" —— y = a·x²，顶点钉在原点，开口随 a 呼吸；
                          一颗「珠子」沿曲线左右滑动，像有参数在扫描。

        绘制顺序：单位网格 → 坐标轴 + 箭头 + 刻度 → 曲线 → 动点 → 文字标注。
        """
        ox, oy = origin
        old_clip = screen.get_clip()
        screen.set_clip(box)

        # ---- 1) 单位网格：最淡的一层，像坐标纸 ----
        gx = ox + unit
        while gx <= box.right:
            pygame.draw.line(screen, PLANE_GRID, (gx, box.top), (gx, box.bottom), 1)
            gx += unit
        gx = ox - unit
        while gx >= box.left:
            pygame.draw.line(screen, PLANE_GRID, (gx, box.top), (gx, box.bottom), 1)
            gx -= unit
        gy = oy - unit
        while gy >= box.top:
            pygame.draw.line(screen, PLANE_GRID, (box.left, gy), (box.right, gy), 1)
            gy -= unit
        gy = oy + unit
        while gy <= box.bottom:
            pygame.draw.line(screen, PLANE_GRID, (box.left, gy), (box.right, gy), 1)
            gy += unit

        # ---- 2) 坐标轴：横轴 x、纵轴 y，末端带箭头 ----
        pygame.draw.line(screen, AXIS_COL, (box.left, oy), (box.right, oy), 2)
        pygame.draw.line(screen, AXIS_COL, (ox, box.bottom), (ox, box.top), 2)
        pygame.draw.polygon(screen, AXIS_COL, [
            (box.right, oy), (box.right - 11, oy - 5), (box.right - 11, oy + 5)])
        pygame.draw.polygon(screen, AXIS_COL, [
            (ox, box.top), (ox - 5, box.top + 11), (ox + 5, box.top + 11)])

        # ---- 3) 刻度：每 1 个单位一个小短划 ----
        gx = ox + unit
        while gx <= box.right - 16:
            pygame.draw.line(screen, AXIS_COL, (gx, oy - 4), (gx, oy + 4), 2)
            gx += unit
        gx = ox - unit
        while gx >= box.left + 4:
            pygame.draw.line(screen, AXIS_COL, (gx, oy - 4), (gx, oy + 4), 2)
            gx -= unit
        gy = oy - unit
        while gy >= box.top + 16:
            pygame.draw.line(screen, AXIS_COL, (ox - 4, gy), (ox + 4, gy), 2)
            gy -= unit
        gy = oy + unit
        while gy <= box.bottom - 4:
            pygame.draw.line(screen, AXIS_COL, (ox - 4, gy), (ox + 4, gy), 2)
            gy += unit

        # ---- 4) 函数曲线（fy 返回「数学单位」的高度，画前换算成像素）----
        if kind == "sin":
            phase = t_ms / 620.0

            def fy(xm):
                return 1.8 * math.sin(xm - phase)
        else:
            # 开口系数 a 随呼吸在 0.075~0.175 之间起伏：a 小则口大开得缓、
            # a 大则口窄立得陡，看上去就是这条抛物线在「一呼一吸」。
            # 上限压在 0.175，是为了呼吸到最陡时两臂也刚好留在图纸范围内，
            # 不会从框顶穿出去。
            a = 0.125 + 0.05 * math.sin(t_ms / 900.0)

            def fy(xm):
                return a * xm * xm

        pts = []
        x = box.left
        while x <= box.right:
            pts.append((x, int(round(oy - fy((x - ox) / float(unit)) * unit))))
            x += 2
        if len(pts) > 1:
            pygame.draw.lines(screen, CURVE_COL, False, pts, 2)

        # ---- 5) 曲线上的动点：让「在动」这件事一眼可见 ----
        if kind == "sin":
            dm = 6.2                       # 固定在某个 x 上的珠子，随波起伏
        else:
            dm = 2.9 * math.sin(t_ms / 1300.0)   # 沿曲线左右扫描
        pygame.draw.circle(screen, CURVE_COL,
                           (int(ox + dm * unit),
                            int(oy - fy(dm) * unit)), 3)

        # ---- 6) 标注：轴名 x / y、原点 O、角落的函数名 ----
        for txt, pos in (("x", (box.right - 16, oy - 13)),
                         ("y", (ox + 9, box.top + 8)),
                         ("O", (ox - 11, oy + 12))):
            s = self.F_TINY.render(txt, True, AXIS_COL)
            screen.blit(s, s.get_rect(center=pos))

        screen.set_clip(old_clip)

        # 函数名写在图的下方（像课本里的图注）。放在框内会压在网格线/刻度上，
        # 放到框外反而干净，也不受裁剪影响。
        lab = self.F_TINY.render("y = sin x" if kind == "sin" else "y = x²",
                                 True, DECO_LABEL)
        screen.blit(lab, (box.left + 2, box.bottom + 2))

    def draw_math_decor(self, screen, t_ms):
        """在渐变背景上铺一层数学元素：背景里的两个坐标系（各带一条函数
        曲线）、几何图形、公式。

        全部用极淡的颜色，画在角色之下，只做氛围、不抢前景。
        函数不再是「悬空漂着的裸曲线」，而是画在各自带刻度的坐标系里：
        左图的 y = sin x 横向流动、右图的 y = x² 开口呼吸，各自还有一颗
        动点在曲线上跑。运动都由 t_ms 驱动的平滑周期函数决定（不引入随机
        抖动），所以画面稳定、截图可复现、也好写断言。

        布局约束（必须避开前景，边界都是实测出来的）：
          玩家立绘所有动作帧的像素并集 = x56~444 / y206~486（P_X=250、高 280）；
          敌人最宽是 Boss 半径 100、E_X=1000 → 最左 x900；
          顶栏 y0~52；手牌从 y518 起；「对决区」中线在 x=640。
          于是中间那条能摆图纸的空档只有 x448~886，两个坐标系就卡在这里。
        """
        # ---- 3.1 两个坐标系（函数画在坐标轴上）----
        self._coord_plane(screen, SIN_PLANE, SIN_ORIGIN, SIN_UNIT, t_ms, "sin")
        self._coord_plane(screen, PAR_PLANE, PAR_ORIGIN, PAR_UNIT, t_ms, "parabola")

        # ---- 3.2 几何图形（描边，随 t_ms 旋转 / 浮动，呼应「形」）----
        # 锚点统一取自 DECO_SHAPES，测试脚本按同一份数据检查「不撞图纸」
        c_cx, c_cy = DECO_SHAPES["circle"][:2]
        g_cx, g_cy = DECO_SHAPES["rings"][:2]
        s_cx, s_cy = DECO_SHAPES["square"][:2]
        t_cx, t_cy = DECO_SHAPES["triangle"][:2]

        # 圆（顶部横带）：半径随 t_ms 缓慢「呼吸」，像有生命
        cr = 25 + int(6 * math.sin(t_ms / 700.0))
        pygame.draw.circle(screen, DECO_GRAPH, (c_cx, c_cy), cr, 2)
        # 同心圆（下段左）：围一圈卫星点绕外圈转，暗示旋转
        pygame.draw.circle(screen, DECO_GRAPH, (g_cx, g_cy), 26, 2)
        pygame.draw.circle(screen, DECO_GRAPH, (g_cx, g_cy), 15, 1)
        sat_ang = t_ms / 700.0
        pygame.draw.circle(screen, DECO_GRAPH,
                           (g_cx + int(26 * math.cos(sat_ang)),
                            g_cy + int(26 * math.sin(sat_ang))), 3)
        # 正方形（下段中）：绕中心缓慢旋转
        sq_half = 19
        sq_ang = t_ms / 3000.0
        sq_pts = []
        for k in range(4):
            a = sq_ang + math.pi / 4 + k * math.pi / 2
            sq_pts.append((s_cx + sq_half * 1.414 * math.cos(a),
                           s_cy + sq_half * 1.414 * math.sin(a)))
        pygame.draw.polygon(screen, DECO_GRAPH, sq_pts, 2)
        # 三角形（下段右）：上下浮动
        tri_dy = int(8 * math.sin(t_ms / 650.0 + 1.0))
        pygame.draw.polygon(screen, DECO_GRAPH,
                            [(t_cx - 20, t_cy + tri_dy), (t_cx + 20, t_cy + tri_dy),
                             (t_cx, t_cy - 32 + tri_dy)], 2)

        # ---- 3.3 公式（小字，最淡可读层，保持静态不抢戏）----
        f = E.load_font(DECO_FORMULA_SIZE)
        for txt, fx, fy in DECO_FORMULAS:
            s = f.render(txt, True, DECO_FORMULA)
            s.set_alpha(120)
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
        pygame.draw.circle(screen, (176, 186, 204), (cx, my), 14 + pulse, 2)
        pygame.draw.circle(screen, (150, 162, 184), (cx, my), 4)

    # ==================== 舞台（杀戮尖塔式布局） ====================
    def draw_stage(self, screen, t_ms):
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
        # 敌人形象：三档各有各的几何母题（几何魔像 / 方程组·三元 / 不可解之影），
        # 不再用「红圆 + 名字前两字」占位。体型半径沿用原来的 E_R，
        # 底边正好落在 y=435 的地面线上，意图框/血条/影子的位置都不用动。
        art_shapes.draw_enemy(screen, self.kind, (self.E_X, self.E_CY),
                              self.E_R, t_ms)

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
        # ---- 屏幕震动：先画到离屏画布，最后整体偏移贴到屏幕上 ----
        # 用了个小技巧：把参数 screen 换成画布，下面**整段绘制代码一个字都不用改**
        # ——它们照旧用 screen 这个名字画，只是此刻 screen 指向画布。
        # 要动的地方越少，漏改的风险越小（这段绘制代码有 70 行，全改一遍
        # 很容易漏一处，而漏掉的那一处就会在震动时「不跟着抖」，特别显眼）。
        real = screen
        ox, oy = self._shake_offset(t_ms)
        if ox or oy:
            screen = self._canvas_surface()

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
        self.draw_stage(screen, t_ms)

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
            screen.blit(ht, (WIDTH // 2 - ht.get_width() // 2,
                             HEIGHT - CARD_H - 116))
            sub = self.F_TINY.render(
                "再点配得上的卡 ＝ 组合（省 1 点能量）；点空白处 ＝ 单独打出",
                True, TEXT_MUTE)
            screen.blit(sub, (WIDTH // 2 - sub.get_width() // 2,
                              HEIGHT - CARD_H - 90))
        elif self.phase == "player" and not self.done:
            ht = self.F_TINY.render(
                "数字卡单出＝算术题；数字＋图形＝算面积；数字＋平方＝算平方；"
                "图形卡单出＝认图形", True, TEXT_MUTE)
            screen.blit(ht, (WIDTH // 2 - ht.get_width() // 2,
                             HEIGHT - CARD_H - 92))

        # ---------- 打击感：飘字 + 闪白（压在场景之上、弹窗之下） ----------
        self.draw_pops(screen)
        self.draw_overlays(screen)

        # ---------- 答题弹窗 ----------
        if self.quiz is not None:
            self.draw_quiz(screen, mouse, t_ms)

        # ---------- 结算画面 ----------
        if self.done:
            self.draw_result(screen)

        # 震动：把画布整体偏移贴回真正的屏幕上。
        # 先铺一层背景色 —— 画布偏移后边缘会露出上一帧的旧像素，
        # 不盖掉的话会看到一条抖动的残影边。
        if ox or oy:
            real.fill(BG)
            real.blit(screen, (ox, oy))

    def draw_card(self, screen, card, mouse):
        r = card.rect
        lift = 18 if card.selected else 0
        r = r.move(0, -lift)
        col = card_color(card.ctype)        # 数字 / 图形 / 运算 三色
        soft = card_soft(card.ctype)
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

        # 图案区：卡面中部的几何图案（形状按卡名，颜色随卡类型）。
        # 数字牌的图案就是那个数字本身（art_shapes._icon_digit），
        # 图形 / 运算卡各有各的图形。
        icon_cy = r.y + 71
        art_shapes.draw_card_icon(screen, card.name,
                                  (r.centerx, icon_cy), r.w * 0.46, col)

        # 类型标签：数字卡后面再挂一个难度名（最简 / 加减 / … / 括号），
        # 玩家扫一眼卡面就知道「打这张要做多难的题」。
        tag = type_label(card.ctype)
        if card.ctype == "number":
            tag = "%s・%s" % (tag, difficulty_name(card.value))
        tg = self.F_TINY.render(tag, True, col)
        screen.blit(tg, tg.get_rect(center=(r.centerx, r.y + 108)))

        # 描述
        cy = r.y + 122
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

        q = self.quiz
        kind = q.get("kind", "arith")
        if kind == "arith":
            self._draw_arith_quiz(screen, mouse, t_ms, q)
        elif kind == "square":
            self._draw_square_quiz(screen, mouse, t_ms, q)
        else:
            self._draw_figure_quiz(screen, mouse, t_ms, q, kind)

    def _fit_font(self, text, max_w):
        """挑一个能把 text 塞进 max_w 的最大字号。

        算术题的式子长短跟着难度走：0 号牌是「3 + 4」，9 号牌是
        「9 × 4 − (3 + 5)」—— 固定用大字号的话，难题会顶出答题框。
        """
        for size in (34, 28, 22):
            f = E.load_font(size)
            if f.size(text)[0] <= max_w:
                return f
        return E.load_font(22)

    def _draw_typed(self, screen, typed, line_x0, line_x1, line_y, col, t_ms):
        """填空线 + 已输入的内容 + 闪烁光标（数字题和面积题共用）。"""
        cx_mid = (line_x0 + line_x1) // 2
        if typed:
            tt = self.F_BIG.render(typed, True, TEXT)
            screen.blit(tt, tt.get_rect(midbottom=(cx_mid, line_y - 4)))
            if (t_ms // 500) % 2 == 0:
                cur_x = cx_mid + tt.get_width() // 2 + 8
                pygame.draw.line(screen, col, (cur_x, line_y - 40),
                                 (cur_x, line_y - 4), 3)
        elif (t_ms // 500) % 2 == 0:
            pygame.draw.line(screen, col, (cx_mid, line_y - 40),
                             (cx_mid, line_y - 4), 3)

    def _draw_submit(self, screen, mouse, q, col):
        """提交按钮。位置按题型存在 quiz["submit_rect"] 里 ——
        面积题的按钮跟着填空线走，其他题用固定的那个。"""
        r = q.get("submit_rect", self.BTN_SUBMIT)
        hover = r.collidepoint(mouse)
        pygame.draw.rect(screen, _darken(col) if hover else col, r,
                         border_radius=10)
        sb = self.F_MID.render("提交", True, (255, 255, 255))
        screen.blit(sb, sb.get_rect(center=r.center))

    def _draw_arith_quiz(self, screen, mouse, t_ms, q):
        """算术题（单出数字卡）：大等式 + 填空线。

        标题下面挂一行小字写明「这是数字几的题、属于哪一档」——
        难度是跟着数字卡走的，得让玩家看得见，不然他会以为题目是乱出的。
        """
        box = self.QUIZ_BOX
        pygame.draw.rect(screen, PANEL, box, border_radius=16)
        pygame.draw.rect(screen, ACCENT, box, 3, border_radius=16)

        title = self.F_MID.render("解出这道题，卡牌才会生效", True, TEXT)
        screen.blit(title, title.get_rect(center=(box.centerx, box.y + 38)))

        sub_txt = "数字 %s 的题 · %s" % (q["card"].name,
                                        DIFF_DESC.get(q.get("tier", 0), ""))
        sub = self.F_TINY.render(sub_txt, True, TEXT_MUTE)
        screen.blit(sub, sub.get_rect(center=(box.centerx, box.y + 66)))

        expr_y = box.y + 122
        BLANK_W, GAP = 130, 18
        expr_txt = q["expr"] + " ="
        f = self._fit_font(expr_txt, box.w - 60 - BLANK_W - GAP)
        expr = f.render(expr_txt, True, ACCENT)
        total_w = expr.get_width() + GAP + BLANK_W
        start_x = box.centerx - total_w // 2
        screen.blit(expr, (start_x, expr_y - expr.get_height() // 2))

        line_x0 = start_x + expr.get_width() + GAP
        line_x1 = line_x0 + BLANK_W
        line_y = expr_y + 34
        pygame.draw.line(screen, ACCENT, (line_x0, line_y), (line_x1, line_y), 3)
        self._draw_typed(screen, q["input"], line_x0, line_x1, line_y,
                         ACCENT, t_ms)

        self._draw_submit(screen, mouse, q, ACCENT)
        hint = self.F_TINY.render("直接敲数字键输入，回车提交，退格删除",
                                  True, TEXT_MUTE)
        screen.blit(hint, hint.get_rect(center=(box.centerx, box.bottom - 22)))

    def _draw_square_quiz(self, screen, mouse, t_ms, q):
        """平方题（数字卡 + 平方卡）：先是「例题框」，再是本题。

        例题必须**完整算出来**（2² = 2 × 2 = 4）：只写「2² = 2 × 2」
        等于把最后一步也留给玩家猜，那就不叫例题了。本题那一行同样把
        「n² = n × n =」铺开，玩家要做的只是把乘法算完 —— 这正是
        「先给示例、再出一道算平方的题」的意思。
        """
        box = self.QUIZ_BOX_FIG
        col = card_color("op")
        soft = card_soft("op")
        pygame.draw.rect(screen, PANEL, box, border_radius=16)
        pygame.draw.rect(screen, col, box, 3, border_radius=16)

        title = self.F_MID.render("平方，就是自己乘自己", True, TEXT)
        screen.blit(title, title.get_rect(center=(box.centerx, box.y + 36)))

        # 例题框
        ex = pygame.Rect(box.centerx - 220, box.y + 66, 440, 104)
        pygame.draw.rect(screen, soft, ex, border_radius=12)
        pygame.draw.rect(screen, col, ex, 1, border_radius=12)
        lab = self.F_TINY.render("例", True, col)
        screen.blit(lab, (ex.x + 16, ex.y + 12))
        ey = ex.y + 32
        for d in q["demos"]:
            line = "%d² = %d × %d = %d" % (d, d, d, d * d)
            t = self.F_MID.render(line, True, TEXT)
            screen.blit(t, (ex.x + 52, ey))
            ey += 32

        # 本题：n² = n × n = ____
        n = q["n"]
        n_txt = self.F_BIG.render("%d²  =  %d × %d  =" % (n, n, n), True, col)
        qw = self.F_BIG.render(str(n * n), True, TEXT).get_width()
        BLANK_W = max(130, qw + 24)
        total = n_txt.get_width() + 16 + BLANK_W
        x0 = box.centerx - total // 2
        row_y = box.y + 226
        screen.blit(n_txt, (x0, row_y - n_txt.get_height() // 2))

        line_x0 = x0 + n_txt.get_width() + 16
        line_x1 = line_x0 + BLANK_W
        line_y = row_y + 30
        pygame.draw.line(screen, col, (line_x0, line_y), (line_x1, line_y), 3)
        self._draw_typed(screen, q["input"], line_x0, line_x1, line_y, col, t_ms)

        self._draw_submit(screen, mouse, q, col)
        hint = self.F_TINY.render("敲数字键输入结果，回车提交，退格删除",
                                  True, TEXT_MUTE)
        screen.blit(hint, hint.get_rect(center=(box.centerx, box.bottom - 20)))

    def _draw_figure_quiz(self, screen, mouse, t_ms, q, kind):
        """图形题（组合出的面积题 / 单出图形卡的认图形题）。

        两种题的排版共用一个大框：**上面是图形，下面是题面**。
        图形就画在框里，玩家不用在脑子里拼图 —— 这是本题型存在的意义。
        """
        box = self.QUIZ_BOX_FIG
        col = GREEN                      # 图形卡的主色
        pygame.draw.rect(screen, PANEL, box, border_radius=16)
        pygame.draw.rect(screen, col, box, 3, border_radius=16)

        title_txt = ("算对这个面积，两张卡一起生效" if kind == "area"
                     else "认出这个图形，卡牌才会生效")
        title = self.F_MID.render(title_txt, True, TEXT)
        screen.blit(title, title.get_rect(center=(box.centerx, box.y + 36)))

        if kind == "area":
            art_shapes.draw_shape_figure(screen, q["shape"],
                                         (box.centerx, box.y + 176), 170, col,
                                         q["dims"])
            l1 = self.F_SML.render("求这个%s的面积" % art_shapes.shape_cn(q["shape"]),
                                   True, TEXT)
            screen.blit(l1, l1.get_rect(center=(box.centerx, box.y + 280)))
            l2 = self.F_SML.render(
                "%s　　面积 = %s" % (shape_dims_text(q["shape"], q["dims"]),
                                    art_shapes.shape_formula(q["shape"])),
                True, TEXT_MUTE)
            screen.blit(l2, l2.get_rect(center=(box.centerx, box.y + 308)))

            # 输入行：S = ____  ＋ 提交（挤在同一行，纵向空间留给图形）
            btn = q.get("submit_rect", self.BTN_SUBMIT)
            line_x1 = btn.x - 26
            line_x0 = line_x1 - 130
            lab = self.F_MID.render("S =", True, col)
            screen.blit(lab, lab.get_rect(midright=(line_x0 - 10, btn.centery)))
            line_y = btn.centery + 18
            pygame.draw.line(screen, col, (line_x0, line_y), (line_x1, line_y), 3)
            self._draw_typed(screen, q["input"], line_x0, line_x1, line_y,
                             col, t_ms)
            self._draw_submit(screen, mouse, q, col)
            hint = self.F_TINY.render("敲数字键输入面积，回车提交，退格删除",
                                      True, TEXT_MUTE)
        else:
            art_shapes.draw_shape_figure(screen, q["shape"],
                                         (box.centerx, box.y + 160), 140, col,
                                         None, False)
            for i, r in enumerate(q["option_rects"]):
                picked = (q.get("pick") == i)
                hover = r.collidepoint(mouse)
                bg = col if picked else (GREEN_SOFT if hover else CARD_FACE)
                pygame.draw.rect(screen, bg, r, border_radius=12)
                pygame.draw.rect(screen, col, r, 3 if picked else 2,
                                 border_radius=12)
                txt = self.F_MID.render("%d. %s" % (i + 1, q["options"][i]),
                                        True, (255, 255, 255) if picked else TEXT)
                screen.blit(txt, txt.get_rect(center=r.center))
            self._draw_submit(screen, mouse, q, col)
            hint = self.F_TINY.render("点选项或按 1-4 选择，回车提交",
                                      True, TEXT_MUTE)
        screen.blit(hint, hint.get_rect(center=(box.centerx, box.bottom - 20)))

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
