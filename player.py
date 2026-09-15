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


class Player:
    """跨场景共享的玩家状态。"""

    def __init__(self, max_hp=80, gold=60):
        self.max_hp = max_hp
        self.hp = max_hp
        self.gold = gold
        self.relics = []
        self.deck = [Card(*c) for c in STARTER_DECK]
        self.log_lines = []

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
        p = cls.__new__(cls)
        p.max_hp = d["max_hp"]
        p.hp = d["hp"]
        p.gold = d["gold"]
        p.relics = list(d["relics"])
        p.deck = [Card(c["name"], c["ctype"], c["value"], c["desc"],
                       c["cost"], c["effect"]) for c in d["deck"]]
        p.log_lines = []
        return p
