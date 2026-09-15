"""
《数与形》玩家状态
================================================
整个爬塔过程中共享的玩家数据：生命、金币、遗物、牌库。

地图、战斗、各种节点面板都从这里读写，保证状态一致。
"""

import random

# ==================== 卡牌定义 ====================
class Card:
    """一张卡。ctype 有 number（数字卡）/ shape（图形卡）两种。"""

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


# 初始牌组（每项会被 clone 成独立实例）
STARTER_DECK = [
    ("加一",   "number", 3, "造成 3 点伤害", 1, {"dmg": 3}),
    ("加一",   "number", 3, "造成 3 点伤害", 1, {"dmg": 3}),
    ("凑十",   "number", 7, "造成 7 点伤害", 1, {"dmg": 7}),
    ("凑十",   "number", 7, "造成 7 点伤害", 1, {"dmg": 7}),
    ("平方",   "number", 4, "造成 4 点伤害", 1, {"dmg": 4}),
    ("三角盾", "shape",  0, "获得 6 点格挡", 1, {"block": 6}),
    ("三角盾", "shape",  0, "获得 6 点格挡", 1, {"block": 6}),
    ("方阵",   "shape",  0, "获得 9 点格挡", 2, {"block": 9}),
    ("镜像",   "shape",  0, "抽 2 张牌",     1, {"draw": 2}),
    ("归零",   "shape",  0, "清空敌人格挡",  1, {"strip": True}),
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
#   trait     被动（先记录设计，实装留到后面）
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
        "desc": "以数字为刃的基础职。数字卡比旁人多一张，"
                "前期清怪最稳，但缺防线，被压血时容易翻车。",
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
        "deck": [
            ("加一",   "number", 3, "造成 3 点伤害", 1, {"dmg": 3}),
            ("凑十",   "number", 6, "造成 6 点伤害", 1, {"dmg": 6}),
            ("三角盾", "shape",  0, "获得 7 点格挡", 1, {"block": 7}),
            ("三角盾", "shape",  0, "获得 7 点格挡", 1, {"block": 7}),
            ("三角盾", "shape",  0, "获得 7 点格挡", 1, {"block": 7}),
            ("方阵",   "shape",  0, "获得 11 点格挡", 2, {"block": 11}),
            ("方阵",   "shape",  0, "获得 11 点格挡", 2, {"block": 11}),
            ("镜像",   "shape",  0, "抽 2 张牌",     1, {"draw": 2}),
            ("归零",   "shape",  0, "清空敌人格挡",  1, {"strip": True}),
            ("反证",   "shape",  0, "获得 5 点格挡并造成 4 点伤害", 1,
             {"block": 5, "dmg": 4}),
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
        "deck": [
            ("加一",   "number", 3, "造成 3 点伤害", 1, {"dmg": 3}),
            ("凑十",   "number", 5, "造成 5 点伤害", 1, {"dmg": 5}),
            ("平方",   "number", 5, "造成 5 点伤害", 1, {"dmg": 5}),
            ("三角盾", "shape",  0, "获得 5 点格挡", 1, {"block": 5}),
            ("三角盾", "shape",  0, "获得 5 点格挡", 1, {"block": 5}),
            ("镜像",   "shape",  0, "抽 2 张牌",     1, {"draw": 2}),
            ("镜像",   "shape",  0, "抽 2 张牌",     1, {"draw": 2}),
            ("换元",   "shape",  0, "抽 1 张牌并造成 4 点伤害", 1,
             {"draw": 1, "dmg": 4}),
            ("归零",   "shape",  0, "清空敌人格挡",  1, {"strip": True}),
            ("未知数", "number", 6, "造成 6 点伤害", 1, {"dmg": 6}),
        ],
        "trait": "【代入】每回合抽牌阶段多抽 1 张，但手牌上限仍是 5",
    },
]


def character_by_id(cid):
    """按 id 找角色；找不到返回第一个（别让老存档读崩）。"""
    for c in CHARACTERS:
        if c["id"] == cid:
            return c
    return CHARACTERS[0]


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

    # ---------- 遗物 ----------
    def add_relic(self, name):
        self.relics.append(name)

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
        p.deck = []
        for c in d.get("deck", []):
            try:
                p.deck.append(Card(c["name"], c["ctype"], c["value"],
                                   c["desc"], c["cost"], c.get("effect")))
            except (KeyError, TypeError):
                # 单张卡坏了就跳过，不要为一张卡丢掉整局
                continue
        p.log_lines = []
        return p
