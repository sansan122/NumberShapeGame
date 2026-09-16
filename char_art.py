# -*- coding: utf-8 -*-
"""char_art.py —— 角色立绘与动作动画的加载 / 播放。

素材来源：人物(1)/ 目录（角色001=演算者、角色002=构形师、
角色003=解方程者），经 tmp/prepare_char_art.py 预处理成
assets/chars/{id}/ 下的 PNG 帧序列：

    full.png        静态立绘（选角卡片等不动的场合）
    idle_NN.png     待机循环（8 帧 × 100ms）
    attack_NN.png   攻击（12~16 帧 × 100ms，播完自动回待机）
    hit_NN.png      受击（8 帧 × 100ms，播完自动回待机）

三条硬规矩（都吃过亏）：

  1. **素材缺失绝不崩** —— 角色图是后来一张一张补的（现在三个都齐，
     但打包时 assets 目录仍可能漏带）。加载失败时 `has_art=False`，
     调用方退回原来的「符号 + 颜色」占位画法。
  2. **资源路径一律走 game_env.resource_path** —— 打包后资源
     在 sys._MEIPASS 临时目录，`Path(__file__).parent` 会找错地方。
  3. **缩放结果要缓存，但键必须带帧身份** —— smoothscale 不便宜，
     同一帧重复缩放会让战斗掉帧；可所有帧尺寸相同（联合 bbox 裁剪），
     按 (高度, 宽度) 记键会让第一帧结果被全部帧共用、动画冻在第一帧，
     必须用 (高度, id(帧)) 记键。两条都真踩过。
"""

from pathlib import Path

import pygame

import game_env as E

#: 帧时长（毫秒），素材导出时就是 100ms/帧
FRAME_MS = 100

#: 预处理输出的统一高度（见 prepare_char_art.py 的 TARGET_H）
SOURCE_H = 320

#: 动作名 -> 是否循环播放
_ACTIONS = (("idle", True), ("attack", False), ("hit", False))

#: 角色素材在 assets/chars 下的目录名
_DIRS = {
    "calculator": "calculator",
    "geometer": "geometer",
    "solver": "solver",
}

# ---------------------------------------------------------------------------
# 加载（惰性 + 缓存）
# ---------------------------------------------------------------------------

#: char_id -> CharArt，全局唯一（Surface 内存别重复占）
_cache = {}


class CharArt:
    """一个角色的全部美术帧 + 动画播放状态。

    就算没有素材也可以创建（has_art=False），draw 直接什么都不画，
    由调用方画符号占位 —— 这样上游代码不用写两套分支。
    """

    def __init__(self, char_id):
        self.char_id = char_id
        self.has_art = False
        self.full = None          # 静态立绘 Surface（高 SOURCE_H）
        self.frames = {}          # action -> [Surface, ...]
        self._load(char_id)

        # ---- 播放状态 ----
        self.action = "idle"
        self.looping = True
        self.frame_i = 0
        self.ms_in_frame = 0
        # 缩放缓存：key=(高度, 宽度) -> Surface
        self._scaled = {}
        self._scaled_full = {}

    def _load(self, char_id):
        """读 assets/chars/{id}/ 下的帧。任何一步失败就保持 has_art=False。"""
        d = _DIRS.get(char_id)
        if not d:
            return
        base = Path(E.resource_path("assets", "chars", d))
        if not base.is_dir():
            return
        try:
            for act, _loop in _ACTIONS:
                frames = []
                i = 0
                while True:
                    p = base / ("%s_%02d.png" % (act, i))
                    if not p.is_file():
                        break
                    frames.append(pygame.image.load(str(p)).convert_alpha())
                    i += 1
                if frames:
                    self.frames[act] = frames
            full_p = base / "full.png"
            if full_p.is_file():
                self.full = pygame.image.load(str(full_p)).convert_alpha()
        except (pygame.error, OSError):
            # 坏图 / 半个文件：退回占位，别让游戏起不来
            self.frames = {}
            self.full = None
            return
        self.has_art = bool(self.frames.get("idle")) and self.full is not None

    # ---------------- 播放控制 ----------------
    def play(self, action):
        """切到某个动作。attack/hit 是一次性（播完自动回 idle）。"""
        if not self.has_art or action not in self.frames:
            return
        if action == self.action and action in ("attack", "hit"):
            return  # 动作还在播，别打断重头（连续受击时更自然）
        self.action = action
        self.looping = (action == "idle")
        self.frame_i = 0
        self.ms_in_frame = 0

    def tick(self, dt_ms):
        """推进帧。dt_ms 用主循环的毫秒 delta。"""
        if not self.has_art:
            return
        frames = self.frames.get(self.action)
        if not frames:
            return
        self.ms_in_frame += dt_ms
        while self.ms_in_frame >= FRAME_MS:
            self.ms_in_frame -= FRAME_MS
            self.frame_i += 1
            if self.frame_i >= len(frames):
                if self.looping:
                    self.frame_i = 0
                else:
                    # 一次性动作（攻击/受击）播完 -> 自动回待机
                    self.action = "idle"
                    self.looping = True
                    self.frame_i = 0
                    self.ms_in_frame = 0
                    break

    def current(self):
        """当前应该显示的帧 Surface；没有素材返回 None。"""
        if not self.has_art:
            return None
        frames = self.frames.get(self.action) or self.frames.get("idle")
        if not frames:
            return None
        return frames[min(self.frame_i, len(frames) - 1)]

    # ---------------- 绘制 ----------------
    def _scaled_frame(self, surf, height, cache):
        """按目标高度缩放（宽等比），结果缓存。

        缓存键必须带上「是哪一帧」(用 id(surf))：预处理把所有帧裁成
        同一个联合 bbox，尺寸全部相同，只按 (高度, 宽度) 记键的话
        第一帧的缩放结果会被所有帧共用 —— 动画就永远停在第一帧。
        （真踩过的坑：立绘显示正常但一动不动，就是它。）
        """
        key = (height, id(surf))
        if key not in cache:
            ratio = height / surf.get_height()
            w = max(1, round(surf.get_width() * ratio))
            cache[key] = pygame.transform.smoothscale(
                surf, (w, height))
        return cache[key]

    def draw(self, screen, anchor, height):
        """画当前帧。anchor=(cx, bottom_y)：角色底部中心锚点，像「站」在那里。

        立绘带透明通道，直接 blit 即可。
        返回 True = 画了立绘；False = 没有素材（调用方该画符号占位）。
        """
        if not self.has_art:
            return False
        frame = self.current()
        if frame is None:
            return False
        img = self._scaled_frame(frame, height, self._scaled)
        cx, by = anchor
        screen.blit(img, img.get_rect(midbottom=(cx, by)))
        return True

    def draw_static(self, screen, rect):
        """画静态立绘，等比缩放塞进 rect（居中，不放大超过源尺寸太多）。

        用于选角卡片这类固定框位。素材缺失时返回 False，调用方画占位。
        """
        if not self.has_art:
            return False
        rw, rh = rect.w, rect.h
        ratio = min(rw / self.full.get_width(), rh / self.full.get_height())
        w = max(1, round(self.full.get_width() * ratio))
        h = max(1, round(self.full.get_height() * ratio))
        key = (h, w)
        if key not in self._scaled_full:
            self._scaled_full[key] = pygame.transform.smoothscale(
                self.full, (w, h))
        screen.blit(self._scaled_full[key],
                    self._scaled_full[key].get_rect(center=rect.center))
        return True


def get_char_art(char_id):
    """拿一个角色的 CharArt（全局缓存，缺失素材也返回可用对象）。"""
    if char_id not in _cache:
        _cache[char_id] = CharArt(char_id)
    return _cache[char_id]


def has_art(char_id):
    """轻量查询：这个角色有没有立绘素材。"""
    return get_char_art(char_id).has_art


def draw_idle(screen, char_id, anchor, height, t_ms):
    """无状态的待机动画绘制：按 t_ms 直接算当前帧。

    给地图这类「只要循环待机、不想维护播放状态」的场合用。
    返回 True = 画了；False = 没素材（调用方画占位）。
    """
    art = get_char_art(char_id)
    if not art.has_art:
        return False
    frames = art.frames.get("idle")
    if not frames:
        return False
    f = frames[int(t_ms / FRAME_MS) % len(frames)]
    img = art._scaled_frame(f, height, art._scaled)
    cx, by = anchor
    screen.blit(img, img.get_rect(midbottom=(cx, by)))
    return True
