"""
《数与形》玩家状态
================================================
整个爬塔过程中共享的玩家数据：生命、金币、遗物、牌库。

地图、战斗、各种节点面板都从这里读写，保证状态一致。
"""

import random

# ==================== 卡牌定义 ====================
class Card:
    """一张卡。ctype 有 number（数字卡）/ shape（图形卡）/ op（运算卡）三种。

    op 是「平方」这类**不能单独打出**的牌：它自己不带伤害，只负责把
    配在一起的那张数字卡变强（平方 = 数字的自身相乘，见 battle_scene）。
    """

    def __init__(self, name, ctype, value, desc, cost=1, effect=None):
        self.name = name
        self.ctype = ctype
        self.value = value
        self.desc = desc
        self.cost = cost
        self.effect = dict(effect) if effect else {}
        self.selected = False
        self.rect = None
        self.hover = False

    def clone(self):
        c = Card(self.name, self.ctype, self.value, self.desc,
                 self.cost, self.effect)
        return c

    def __repr__(self):
        return "<Card %s %s>" % (self.name, self.ctype)


# ==================== 卡牌类型 ====================
#: ctype -> (主色, 浅色底, 卡面标签)。
#  数字卡 / 图形卡各自一色；运算卡（平方）单独一色 —— 它不是数字、
#  也不是形状，是「把数字变成它的平方」的一件工具，混进任何一边都会
#  让玩家以为它可以单独打出去。
CARD_TYPE_STYLE = {
    "number": ((24, 95, 165), (230, 241, 251), "数字"),
    "shape":  ((59, 109, 17), (234, 243, 222), "图形"),
    "op":     ((150, 60, 150), (245, 233, 245), "运算"),
}
CARD_TYPE_FALLBACK = ((110, 108, 102), (240, 240, 238), "卡牌")


def type_style(ctype):
    """一种卡类型的三件套（主色 / 浅底 / 标签）；认不出的类型走兜底。"""
    return CARD_TYPE_STYLE.get(ctype, CARD_TYPE_FALLBACK)


def card_color(ctype):
    return type_style(ctype)[0]


def card_soft(ctype):
    return type_style(ctype)[1]


def type_label(ctype):
    return type_style(ctype)[2]


# ==================== 数字牌 0~9 ====================
#: 数字卡的难度阶梯 —— 牌面上的数字越大，题目越长、用到的运算越多。
#: 出题实现在 battle_scene._build_expr，这张表是**唯一**的档位定义，
#: 卡面标签、题目标题、测试断言都从这里读，免得改了一处漏一处。
#:   tier 0  一位数加法（和 ≤ 5）       tier 3  两位数加减 / 乘除
#:   tier 1  10 以内加减               tier 4  两步四则（先乘除后加减）
#:   tier 2  20 以内加减 / 乘法         tier 5  带括号的四则
DIFF_TIER = {0: 0, 1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3, 7: 4, 8: 4, 9: 5}
DIFF_NAME = {0: "最简", 1: "加减", 2: "含乘", 3: "四则", 4: "两步", 5: "括号"}
DIFF_DESC = {
    0: "一位数加法",
    1: "10 以内加减",
    2: "20 以内加减与乘法",
    3: "两位数加减与乘除",
    4: "两步四则（先乘除后加减）",
    5: "带括号的四则",
}
#: 认不出的数字一律按最难处理 —— 宁可把简单题出难了，也不能把难题
#: 当简单题出（那样高数字的牌就白嫖了伤害）
DIFF_MAX = max(DIFF_NAME)


def difficulty_tier(value):
    """数字 -> 难度档（0~5）。"""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return DIFF_MAX
    return DIFF_TIER.get(v, DIFF_MAX)


def difficulty_name(value):
    return DIFF_NAME[difficulty_tier(value)]


def _number_specs():
    """数字牌 0~9 的牌面定义 —— 牌上的数字就是这张牌本身。

    伤害＝数字本身，题目难度也＝数字（DIFF_TIER）：**越难算的牌打得越疼**，
    这是这套牌最基本的张力。手牌里有几张数字牌，就代表「我这一回合肯做
    几道多难的题」，取舍全在这儿。

    0 号牌是唯一的例外：0 既没有伤害、平方也还是 0，按原样它是一张纯死牌
    （玩家一定会来报这个 bug）。所以给它「抽 1 张牌」—— 白给一道最简题，
    换一张手牌，正好是 0 在加法里的角色（加它等于没加）。
    """
    out = []
    for v in range(10):
        if v == 0:
            out.append(("0", "number", 0, "无伤害，抽 1 张", 1, {"draw": 1}))
        else:
            out.append((str(v), "number", v, "造成 %d 点伤害" % v, 1,
                        {"dmg": v}))
    return out


NUMBER_SPECS = _number_specs()

#: 乘方卡：**不能单独打出**，必须配一张数字卡。
#: 出题时先给两个示例（2² = 2 × 2 = 4 …），再问「这个数的平方是几」；
#: 打出的伤害就是那个平方（n²）。这是唯一一张「自己没伤害」的牌 ——
#: 它是一台乘方器，不是子弹。
#:
#: **不在初始牌组里**：它是打穿第一层层主（正方体·三阶）之后才拿到的
#: 战利品。第一层没有它，玩家只能用 0~9 的加法慢慢磨；拿到它之后，
#: 9 号牌一发 81 点 —— 这一前一后就是第一层与后两层难度曲线的分水岭。
#: 所以「什么时候解锁平方」直接决定了整局的节奏，别随手改回去。
SQUARE_SPEC = ("平方", "op", 0, "配数字卡：伤害＝数字²", 2, {})

#: 平方卡的解锁条件：第几层（0 基）的层主被击败后发放。
SQUARE_UNLOCK_FLOOR = 0


# 初始牌组 = 数字牌 0~9（十张）+ 各角色自己的形卡。
# 每项会被 clone 成独立实例。
# 注意这里**没有平方** —— 它要靠打掉第一层层主换来（见 SQUARE_SPEC）。
STARTER_DECK = NUMBER_SPECS + [
    ("三角盾", "shape", 0, "获得 6 点格挡", 1, {"block": 6}),
    ("三角盾", "shape", 0, "获得 6 点格挡", 1, {"block": 6}),
    ("方阵",   "shape", 0, "获得 9 点格挡", 2, {"block": 9}),
    ("镜像",   "shape", 0, "抽 2 张牌",     1, {"draw": 2}),
    ("归零",   "shape", 0, "清空敌人格挡",  1, {"strip": True}),
]


# ==================== 三名可选角色 ====================
# 美术资源后面再加，现在先用「文字 + 方框 + 数学符号」把界面和数值跑通。
#
# 字段说明：
#   id        存档用的稳定标识，**不要改**（改了老存档会读不回来）
#   name/title 显示名与称号
#   icon      角色头像占位用的符号 —— 必须是 msyh.ttc 里存在的字符
#             （⚔ ⌂ ◈ ▣ 会渲染成豆腐块，别用）
#   color     主题色，用来画方框、血条、卡牌描边
#   hp/gold   初始生命与金币
#   theme     核心机制一句话，用来做「新手提示」
#   desc      面板里的详细介绍
#   deck      初始牌组（覆盖 STARTER_DECK）；None 表示用默认
#   trait     被动 —— 文案显示在选角界面，效果在 battle_scene 里按 char_id 结算
CHARACTERS = [
    {
        "id": "calculator",
        "name": "演算者",
        "title": "数之刃",
        "icon": "∑",
        "color": (24, 95, 165),
        "hp": 80,
        "gold": 60,
        "theme": "数字卡强化 —— 伤害直接、节奏快",
        "desc": "以数字为刃的基础职。起手牌组最精简，清怪最稳，"
                "前期靠「直感」每回合白赚 1 点伤害；但缺防线，"
                "被压血时容易翻车。拿到「平方」后爆发最猛。",
        "deck": None,
        "trait": "【直感】每回合打出的第一张数字卡伤害 +1",
    },
    {
        "id": "geometer",
        "name": "构形师",
        "title": "形之壁",
        "icon": "△",
        "color": (59, 109, 17),
        "hp": 92,
        "gold": 50,
        "theme": "格挡与反伤 —— 挨打也能赢",
        "desc": "以图形为盾的守备职。生命最高、格挡最厚，"
                "适合慢慢磨；代价是伤害偏低，打得久一点。",
        "deck": NUMBER_SPECS + [
            ("三角盾", "shape", 0, "获得 7 点格挡", 1, {"block": 7}),
            ("三角盾", "shape", 0, "获得 7 点格挡", 1, {"block": 7}),
            ("三角盾", "shape", 0, "获得 7 点格挡", 1, {"block": 7}),
            ("方阵",   "shape", 0, "获得 11 点格挡", 2, {"block": 11}),
            ("方阵",   "shape", 0, "获得 11 点格挡", 2, {"block": 11}),
            ("反证",   "shape", 0, "获得 5 点格挡并造成 4 点伤害", 1,
             {"block": 5, "dmg": 4}),
            ("归零",   "shape", 0, "清空敌人格挡",  1, {"strip": True}),
        ],
        "trait": "【承形】回合结束时若还有未用完的格挡，下回合 +2 格挡",
    },
    {
        "id": "solver",
        "name": "解方程者",
        "title": "未知之追",
        "icon": "χ",
        "color": (150, 60, 150),
        "hp": 72,
        "gold": 75,
        "theme": "抽牌与连击 —— 手牌越多越强",
        "desc": "以未知数为引的爆发职。生命最低、初始金币最多，"
                "靠抽牌找关键卡；手顺时能一回合秒掉精英。",
        "deck": NUMBER_SPECS + [
            ("三角盾", "shape", 0, "获得 5 点格挡", 1, {"block": 5}),
            ("镜像",   "shape",  0, "抽 2 张牌",     1, {"draw": 2}),
            ("镜像",   "shape",  0, "抽 2 张牌",     1, {"draw": 2}),
            ("换元",   "shape",  0, "抽 1 张牌并造成 4 点伤害", 1,
             {"draw": 1, "dmg": 4}),
            ("归零",   "shape", 0, "清空敌人格挡",  1, {"strip": True}),
        ],
        "trait": "【代入】每回合抽牌阶段多抽 1 张",
    },
]


def character_by_id(cid):
    """按 id 找角色；找不到返回第一个（别让老存档读崩）。"""
    for c in CHARACTERS:
        if c["id"] == cid:
            return c
    return CHARACTERS[0]


#: 遗物取名的规矩。写成字符串常量（而不是只写在注释里）有两个原因：
#:   1. 它是一条**设计约束**，得有个正式的家，不能藏在注释里；
#:   2. 注释不进字节码，只有字符串常量能被 打包.py 的指纹表盯住 ——
#:      这条规矩被后来的人悄悄删掉时，打包自检会当场变红。
RELIC_NAMING_RULE = "名字本身就是这条效果的口诀：念一遍猜不出效果，就重取。"

#: 遗物「定义域扩张」加的上限生命。写成常量是为了让卡面文案
#: （RELIC_POOL 里那句「最大生命 +12」）和实现读同一个数 ——
#: tmp/verify_relics.py 有一条断言专门拿这两个对账，
#: 改了数值却忘了改文案会当场变红。
RELIC_DOMAIN_HP = 12


# ==================== 遗物池 ====================
#: (名字, 描述)。效果按名字结算，散在用到的地方：
#:   等比数列 / 容错区间 / 排列组合 / 等周不等式 / 最简形式 /
#:   守恒律 / 反例 / 复利                          -> battle_scene
#:   定义域扩张                                    -> Player.add_relic
#:   约分                                          -> Player.removal_price
#:
#: **取名的规矩：名字本身就是这条效果的口诀。**
#:   这是本作的核心卖点 —— 惩罚与道具同时当记忆强化用（路线代价
#:   「取近似 / 开区间 / 未完待证」也是照这条来的）。所以：
#:     · 名字必须是真数学概念，不许生造（「等比数列」而不是「连击环」）
#:     · 效果必须是这个名字**最直白**的那层意思，别拐两个弯 ——
#:       玩家看到「约分」能猜到和「化简掉一张牌」有关，
#:       看到「反例」能猜到和「反驳回去」有关
#:     · 同一件遗物只准有一条效果，不许「+1 伤害并且再抽一张」
#:   检查办法很土但有效：把名字念一遍，猜不出效果就重取。
#:
#: 十件的分布是**刻意配平**的（重做时按这个比例挑的）：
#:   战斗内 6 件：进攻 2（等比数列 / 反例）、防守 2（等周不等式 / 最简形式）、
#:              续航 1（守恒律）、手牌 1（排列组合）
#:   战斗外 3 件：上限 1（定义域扩张）、经济 2（约分 / 复利）
#:   容错 1 件：容错区间 —— 唯一一件直接改「算错」这条规则的，
#:              它撑住了整个「敢做题」的体验，别删
RELIC_POOL = [
    # ---- 战斗内：进攻 ----
    ("等比数列", "本回合每答对一题，伤害 +1（最多 +3）"),
    ("反例",     "被敌人攻击命中时，反弹 3 点伤害"),
    # ---- 战斗内：防守 ----
    ("等周不等式", "本回合打出过数字卡后，图形卡额外 +4 格挡"),
    ("最简形式",   "战斗开始时，牌库里最弱的一张被舍去"),
    # ---- 战斗内：续航与手牌 ----
    ("守恒律",   "每场战斗开始时，恢复 4 点生命"),
    ("排列组合", "每回合抽牌阶段多抽 1 张牌"),
    # ---- 战斗外：上限与容错 ----
    ("定义域扩张", "最大生命 +12，并回复等量生命"),
    ("容错区间",   "每回合第一次算错，卡牌不消耗"),
    # ---- 战斗外：经济 ----
    ("约分", "商店删牌价格降低 30%"),
    ("复利", "战斗胜利的金币奖励 +50%"),
]


def roll_unowned_relic(player, rng=random):
    """抽一件玩家还没有的遗物；全拿完了返回 None（由调用方折现成金币）。

    必须去重 —— 否则「遗物 3 件」里可能躺着两件等比数列，
    效果却只按名字算一份，玩家会觉得白白亏了一件。
    """
    owned = set(player.relics)
    pool = [r for r in RELIC_POOL if r[0] not in owned]
    if not pool:
        return None
    return rng.choice(pool)


# ==================== 商店删牌的定价 ====================
# 删牌是牌组质量唯一可靠的提升手段（卡越少，关键牌上手率越高），
# 所以它**必须越来越贵**，否则金币全部倒进删牌，牌组会缩到只剩几张神卡。
#
# 两条规则一起构成约束：
#   1. 一次商店只能删一张 —— 删完这家店就没了（ShopPanel.removed_here）
#   2. 每删掉一张，下一次的价钱就涨一档（Player.removals_done 累加）
#
# 价格写成「基价 + 档位 × 步长」，方便调；60 / 90 / 120 / 150 …
# 一局能进的商店本来就不多，涨太快会直接劝退，涨太慢又拦不住堆删牌。
REMOVAL_BASE = 60
REMOVAL_STEP = 30

#: 遗物「约分」的折扣率 —— 删牌价按它打折。
#: 取 0.7 是刻意的「差一点就跨档」：60 -> 42、90 -> 63、120 -> 84，
#: 每一档都压在整十以下，观感上就是「便宜了一档」。
#: 注意折扣只作用在**价格**上，removals_done 的计数照旧 ——
#: 不然拿一件约分就能永远按第一档的价钱删牌，删牌这套约束直接失效。
REMOVAL_DISCOUNT = 0.7


class Player:
    """跨场景共享的玩家状态。"""

    def __init__(self, max_hp=80, gold=60, char=None):
        """char 传 CHARACTERS 里的一项就会按角色初始化
        （生命/金币/牌组全部覆盖）；不传就是老样子。"""
        self.char_id = char["id"] if char else "calculator"
        if char:
            max_hp = char["hp"]
            gold = char["gold"]
            deck_src = char.get("deck") or STARTER_DECK
        else:
            deck_src = STARTER_DECK

        self.max_hp = max_hp
        self.hp = max_hp
        self.gold = gold
        self.relics = []
        # 挂起的强化次数：路线代价「开区间」承诺「战后额外获得 1 次强化」，
        # 先记在这里，等下一场战斗打赢了由战利品面板兑现。
        self.pending_upgrades = 0
        # 历史上删过几张牌 —— 商店拿它定下一次的删牌价（见 REMOVAL_BASE）。
        # 只记「删过几次」，不记「花了多少钱」：价格是推导出来的，
        # 记钱的话改一次定价就会和存档里存的钱对不上。
        self.removals_done = 0
        # 平方卡解锁了没有：打穿第一层层主那一刻置 True。
        # 商店卡池靠它决定要不要摆出「平方」——不然第一层的商店
        # 就能买到它，「打完层主才拿到」这条线就白设了。
        self.square_unlocked = False
        self.deck = [Card(*c) for c in deck_src]
        self.log_lines = []

    @property
    def char(self):
        """取当前角色的定义（美术 + 被动都从这里读）。"""
        return character_by_id(self.char_id)

    # ---------- 牌库 ----------
    def deck_cards(self):
        """返回牌库里所有卡（用于强化 / 移除）。"""
        return list(self.deck)

    def add_card_to_deck(self, name, ctype, value, desc, cost, effect):
        self.deck.append(Card(name, ctype, value, desc, cost, effect))

    def add_card_obj(self, card):
        self.deck.append(card)

    def remove_card(self, card):
        if card in self.deck:
            self.deck.remove(card)
            return True
        return False

    # ---------- 商店：删牌 ----------
    def removal_price(self):
        """下一次删牌要多少钱。

        由「已删掉几张」推出来，不是存档里的独立字段 —— 这样调定价
        （REMOVAL_BASE / REMOVAL_STEP）对老存档也立刻生效，不用迁移数据。

        遗物「约分」在这里打折：价格是**算出来的**，折扣也必须在同一处算 ——
        商店面板上写的价、余额够不够的判断、真正扣钱的那一下，全都问
        这个方法要数，因此不可能出现「显示 63、扣了 90」。
        """
        price = REMOVAL_BASE + REMOVAL_STEP * self.removals_done
        if self.has_relic("约分"):
            price = max(1, int(round(price * REMOVAL_DISCOUNT)))
        return price

    def buy_removal(self, card):
        """付钱删掉一张牌。成功返回实付价格，失败（钱不够 / 卡不在牌库）返回 None。

        扣钱、删卡、计数三件事必须**绑在一起**：拆开写过一次，
        结果漏了计数，删牌价永远停在第一档。
        """
        if card not in self.deck:
            return None
        price = self.removal_price()
        if self.gold < price:
            return None
        self.gold -= price
        self.deck.remove(card)
        self.removals_done += 1
        return price

    # ---------- 平方卡解锁 ----------
    def has_square(self):
        """牌库里（或已解锁）有没有平方。老存档可能自带一张，两种情况都算有。"""
        return self.square_unlocked or any(c.name == "平方" for c in self.deck)

    def unlock_square(self):
        """打穿第一层层主后发平方牌。返回 True 表示这次真的新发了一张。

        已经有一张就不再塞第二张 —— 效果按卡算，两张平方只是纯粹的重复。
        但**解锁标记照样置 True**，否则商店永远不卖平方。
        """
        fresh = not any(c.name == "平方" for c in self.deck)
        if fresh:
            self.add_card_to_deck(*SQUARE_SPEC)
        self.square_unlocked = True
        return fresh

    # ---------- 遗物 ----------
    def add_relic(self, name):
        """收下一件遗物。有些遗物是「拿到就生效」的，在这里一次结算掉 ——
        以前这里只是 append，导致写进遗物池的「+12 生命」那件完全没用。
        返回一句话说明，供上层写日志。

        只有「拿到的那一刻一次性生效」的遗物才在这里结算；
        每场战斗都要重新算的（等比数列 / 等周不等式 …）归 battle_scene。
        """
        self.relics.append(name)
        if name == "定义域扩张":
            # 上限和当前生命一起加（不然白得多出来的上限血量）
            self.max_hp += RELIC_DOMAIN_HP
            self.hp = min(self.max_hp, self.hp + RELIC_DOMAIN_HP)
            return "最大生命 +%d" % RELIC_DOMAIN_HP
        return ""

    def has_relic(self, name):
        return name in self.relics

    # ---------- 日志 ----------
    def log(self, text):
        self.log_lines.insert(0, text)
        self.log_lines = self.log_lines[:20]

    # ---------- 生命 ----------
    def heal(self, amount):
        before = self.hp
        self.hp = min(self.max_hp, self.hp + amount)
        return self.hp - before

    def damage(self, amount):
        self.hp = max(0, self.hp - amount)
        return amount

    @property
    def alive(self):
        return self.hp > 0

    # ---------- 存档（简单 dict）----------
    def to_dict(self):
        return {
            "char_id": self.char_id,
            "max_hp": self.max_hp,
            "hp": self.hp,
            "gold": self.gold,
            "relics": list(self.relics),
            "pending_upgrades": self.pending_upgrades,
            "removals_done": self.removals_done,
            "square_unlocked": self.square_unlocked,
            "deck": [{"name": c.name, "ctype": c.ctype, "value": c.value,
                      "desc": c.desc, "cost": c.cost, "effect": dict(c.effect)}
                     for c in self.deck],
        }

    @classmethod
    def from_dict(cls, d):
        """从存档字典还原。
        这里故意用 .get() 带默认值，不直接下标取 —— 万一存档里
        某些字段（比如以后新加的）没有，也不会整个读档崩掉。"""
        p = cls.__new__(cls)
        # 老存档没有 char_id，兜个默认角色即可，不影响读档
        p.char_id = d.get("char_id") or "calculator"
        p.max_hp = int(d.get("max_hp", 80))
        p.gold = int(d.get("gold", 60))
        # 生命要夹在 0..max_hp 之间，防止手改过的存档出现负血 / 超血
        p.hp = max(0, min(int(d.get("hp", p.max_hp)), p.max_hp))
        p.relics = list(d.get("relics", []))
        # 挂起的强化次数以前**只写不读** —— 「开区间」承诺的那 1 次强化
        # 在存读档之后就凭空消失了。写进 to_dict 的字段这里必须全部还原。
        p.pending_upgrades = int(d.get("pending_upgrades", 0))
        p.removals_done = int(d.get("removals_done", 0))
        p.square_unlocked = bool(d.get("square_unlocked", False))
        p.deck = []
        for c in d.get("deck", []):
            try:
                p.deck.append(Card(c["name"], c["ctype"], c["value"],
                                   c["desc"], c["cost"], c.get("effect")))
            except (KeyError, TypeError):
                # 单张卡坏了就跳过，不要为一张卡丢掉整局
                continue
        # 老存档（平方还在初始牌组那会儿）如果自带一张平方，补上解锁标记，
        # 否则读档后商店永远不卖平方 —— 玩家会以为是 bug。
        if p.has_square():
            p.square_unlocked = True
        p.log_lines = []
        return p
