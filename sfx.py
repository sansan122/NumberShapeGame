# -*- coding: utf-8 -*-
"""sfx.py —— 全程代码合成的音效 + 背景音乐（不依赖任何音频文件）。

=============================================================================
为什么是「合成」而不是「放 wav」
=============================================================================
这个项目的定位是**免安装单 exe**（见 打包.py 与 game_env.py 的注释），
美术也全是代码画的几何图形。音效如果改成外部资源会引入三个麻烦：

  1. 打包时要额外带一个 assets/sfx/ 目录，少一个文件就少一种声音；
  2. 音频文件的体积按秒算，几十个音效轻松几 MB，白白撑大安装包；
  3. 拿到别人的素材有版权问题，而这个游戏是要发给小朋友玩的。

所以这里**一个字节的音频文件都不用**：所有声音都由下面这几个振荡器 /
噪声发生器在启动时算出来，直接塞给 pygame.mixer.Sound。

刻意**没有引入 numpy**（虽然 numpy 合成更省事）：多一个第三方依赖就多一份
「别人电脑上装不上 / 打包漏了隐藏 import」的风险，而实测纯 Python 合成
34 种音效（含变体共 41 段）约 1.3 秒 —— 主线程一行都不等（见下面的「后台
合成」一节），代价完全可以接受。
采样率选 22050Hz：儿童游戏的音效不需要 44.1k，减半 = 生成时间减半。

=============================================================================
音色设计：怎么做出「打击感」
=============================================================================
一个有力的打击音 = **三层叠加**，少一层都会软：

    瞬态（attack）  1~40ms 的高频噪声爆破 —— 那是「啪」的一声，负责锐利
    厚度（body）    几百 Hz 下滑到几十 Hz 的三角/锯齿 —— 负责「实」
    重量（sub）     60~110Hz 的正弦快速下坠 —— 那是「咚」，负责沉

再按伤害量分四档（轻/中/重/巨），档次越高：噪声越长、下坠越深、
尾巴越久、饱和（distortion）越强。玩家打出 81 点平方伤害时听到的
一定是「巨」档，和挠 2 点血完全不是一个动静 —— 这就是打击感的来源。

=============================================================================
音色设计：怎么让小朋友不讨厌
=============================================================================
  · 答对 = 上行大调琶音 + 钟铃音色（明亮、有奖励感）
  · 答错 = 柔和的下行小三度，**不加刺耳蜂鸣**，音量也压低
    （小孩子对失败音很敏感，被声音吓到就不想玩了）
  · 失败/战败 = 缓慢下行，像「叹气」而不是「爆炸」
  · 每一次点击都有回馈（按钮、选卡、抽牌、打字都有各自的短音）
  · 重复触发的声音（点卡、打击）会做**限流**，避免「哒哒哒」叠成噪音

=============================================================================
对外接口（其它模块只用这几个）
=============================================================================
    sfx.init()                 建混音器 + 合成全部音效（幂等，失败返回 False）
    sfx.play("hit_heavy")      播一个音效（未初始化时是安全的空操作）
    sfx.play_bgm("bgm_battle") 切背景音乐（自动淡出淡入）
    sfx.update(dt)             每帧调一次，推进 BGM 淡入淡出
    sfx.toggle_sfx() / toggle_bgm()   开关（F1 / F2）
    sfx.count()                累计播放次数，供主循环判断「这次点击有没有出过声」
"""

import array
import json
import math
import queue
import random
import threading

import pygame

import game_env as E

# ---------------------------------------------------------------------------
# 一、基础常量与波形
# ---------------------------------------------------------------------------

#: 采样率。22050 比 44100 省一半生成时间，儿童音效听不出差别
SR = 22050
#: 16 位有符号
CHANNELS = 2
#: 缓冲区 512 帧 ≈ 23ms 延迟 —— 足够跟手，又不容易爆音
BUFFER = 512

_TWO_PI = 6.283185307179586


def _osc_sine(ph):
    return math.sin(_TWO_PI * ph)


def _osc_triangle(ph):
    # 用 asin(sin) 生成三角波：比锯齿波柔和，又比正弦有泛音（更「实体」）
    return 0.63661977 * math.asin(math.sin(_TWO_PI * ph))


def _osc_square(ph):
    return 1.0 if ph < 0.5 else -1.0


def _osc_pulse(ph):
    # 占空比 25% 的方波：比 50% 方波更「薄」更复古
    return 1.0 if ph < 0.25 else -1.0


def _osc_saw(ph):
    return 2.0 * ph - 1.0


#: 波形名 -> 取一个样本的函数。相位 ph 是**归一化**的 0..1（不是弧度），
#: 这样每次累加只要 += f/SR，省掉一次 2π 乘法。
_OSC = {
    "sine": _osc_sine,
    "triangle": _osc_triangle,
    "square": _osc_square,
    "pulse": _osc_pulse,
    "saw": _osc_saw,
}


def note(name):
    """音名 -> 频率。例：note("C5") = 523.25，note("A4") = 440.0。

    支持 `#`（升）和 `b`（降）：note("F#3")、note("Bb4")。
    写音名比写频率可读得多 —— 看代码就知道这是个大三度还是纯五度。
    """
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    letter = name[0].upper()
    semi = base[letter]
    rest = name[1:]
    if rest and rest[0] in "#b":
        semi += 1 if rest[0] == "#" else -1
        rest = rest[1:]
    midi = (int(rest) + 1) * 12 + semi          # MIDI 编号，C4 = 60
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


# ---------------------------------------------------------------------------
# 二、缓冲：往一条浮点轨道上叠声音，最后归一化成 Sound
# ---------------------------------------------------------------------------


class _Buf:
    """一条单声道浮点轨道。

    所有声音都是「往同一条轨道上叠若干个 tone / noise」造出来的 ——
    和真实录音棚的加法合成一个思路。最后 to_sound() 统一归一化 + 转 16 位。
    """

    __slots__ = ("n", "b")

    def __init__(self, seconds):
        self.n = max(2, int(SR * seconds))
        self.b = [0.0] * self.n

    # ---------------- 振荡器 ----------------
    def tone(self, t0, dur, f0, f1=None, amp=0.4, wave="sine",
             attack=0.004, release=0.05, decay=2.5, env="perc"):
        """叠一个振荡器音。

        t0/dur  起始秒数 / 时长
        f0/f1   起始频率 / 结束频率（None = 不滑音）。滑音是打击感的灵魂：
                频率往下掉 = 能量在释放，听起来就「砸」得下去
        amp     音量
        wave    波形（见 _OSC）
        attack  起音时间（秒）。**别设 0**：从 0 瞬间跳到满音量会「啪」一声
                直流爆音，那是杂音不是打击感
        decay   衰减指数，越大衰减越快（perc 包络用）
        env     "perc" = 打击包络（起音后一路衰减）
                "pad"  = 持续包络（起音 → 保持 → 余弦收尾，给和弦垫用）
        """
        i0 = int(t0 * SR)
        if i0 >= self.n:
            return
        nn = int(dur * SR)
        if nn < 2:
            return
        if i0 + nn > self.n:
            nn = self.n - i0               # 超出轨道就截断，别越界
        f1 = f0 if f1 is None else f1
        osc = _OSC.get(wave, _osc_sine)

        na = max(1, int(attack * SR))
        nr = max(1, int(release * SR))
        if na + nr > nn:
            na = max(1, nn // 4)
            nr = max(1, nn // 4)
        body = nn - na - nr
        inv_sr = 1.0 / SR
        step = (f1 - f0) / nn
        ph = 0.0
        f = float(f0)
        buf = self.b

        if env == "pad":
            for k in range(nn):
                ph += f * inv_sr
                if ph >= 1.0:
                    ph -= int(ph)
                if k < na:
                    e = k / na
                elif k < na + body:
                    e = 1.0
                else:
                    r = (k - na - body) / nr
                    e = 0.5 + 0.5 * math.cos(math.pi * r)   # 余弦收尾，无爆音
                buf[i0 + k] += osc(ph) * amp * e
                f += step
        else:
            span = nn - na
            for k in range(nn):
                ph += f * inv_sr
                if ph >= 1.0:
                    ph -= int(ph)
                if k < na:
                    e = k / na
                else:
                    e = (1.0 - (k - na) / span) ** decay
                buf[i0 + k] += osc(ph) * amp * e
                f += step

    # ---------------- 噪声 ----------------
    def noise(self, t0, dur, amp=0.3, decay=2.5, lp=0.35, hp=0.0,
              attack=0.001, sweep=0.0, rng=None):
        """叠一段滤波白噪声。

        噪声是打击感和「风声/摩擦声」的来源 —— 纯振荡器做不出那种质感。

        lp     低通强度 0..1：越大越亮，越小越闷（0.05 = 远处隆隆声）
        hp     高通量 0..1：>0 会削掉低频，做出「啪」的锐利感
        sweep  滤波器随时间的变化量：负值 = 由闷变亮（像「咻」的一声）
        """
        rng = rng or random
        i0 = int(t0 * SR)
        if i0 >= self.n:
            return
        nn = int(dur * SR)
        if nn < 2:
            return
        if i0 + nn > self.n:
            nn = self.n - i0
        na = max(1, int(attack * SR))
        span = nn - na
        buf = self.b
        y = 0.0
        inv = 1.0 / nn
        for k in range(nn):
            x = rng.uniform(-1.0, 1.0)
            a = lp + sweep * (k * inv)
            if a < 0.005:
                a = 0.005
            elif a > 0.99:
                a = 0.99
            y += a * (x - y)
            v = x - hp * y                 # 减掉低频部分 ≈ 高通
            e = k / na if k < na else (1.0 - (k - na) / span) ** decay
            buf[i0 + k] += v * amp * e

    # ---------------- 混音 ----------------
    def drive(self, amount):
        """整体过一遍软饱和。重打击用它把波形「压扁」，听起来更凶更有侵略性。

        用三次软削波而不是直接截断：直接截断会产生大量奇次谐波，
        听起来是「破音」；三次曲线是平滑滚上去的，是「变厚」。
        """
        if amount <= 1.0:
            return
        for i, v in enumerate(self.b):
            v *= amount
            if v > 1.0:
                v = 1.0
            elif v < -1.0:
                v = -1.0
            self.b[i] = 1.5 * v - 0.5 * v * v * v

    def to_pcm(self, peak=0.8):
        """归一化到指定峰值，转成 mixer 要的「16 位立体声交错」原始字节。

        归一化是**必须**的：不归一化的话，「巨」档因为叠了三层会天然比
        「轻」档响好几倍，音量差失控。归一化之后「轻/重」的区别是靠
        音色层次和低频量做出来的，不是靠音量硬砸 —— 那才是专业的做法。

        注意这个方法**不碰 pygame**：它只做纯计算，所以可以丢到后台线程里跑
        （见 _worker）。建 Sound 那一步必须在主线程做，因为要碰混音器。
        """
        mx = 0.0
        for v in self.b:
            a = -v if v < 0.0 else v
            if a > mx:
                mx = a
        g = peak / mx if mx > 1e-9 else 0.0

        # 归一化后 |v*g| <= peak <= 1.0，所以 int(...) 必然落在 [-32767, 32767]，
        # **不需要逐个样本钳位** —— 省掉每样本两次比较，这是最热的一段循环。
        mono = array.array("h", [int(v * g * 32767.0) for v in self.b])

        # 单声道复制成 L/R：mixer 是按立体声开的，缓冲必须交错双声道。
        # 用 array 的扩展切片一次性展开，比 Python 循环快一个数量级。
        stereo = array.array("h", bytes(4 * self.n))
        stereo[0::2] = mono
        stereo[1::2] = mono
        return stereo.tobytes()

    def to_sound(self, peak=0.8):
        """直接拿到 pygame.Sound（只能在主线程调）。"""
        return make_sound(self.to_pcm(peak))


# ---------------------------------------------------------------------------
# 三、音效目录
# ---------------------------------------------------------------------------
#: name -> {"sec","peak","variants","build"}。用装饰器注册，配方写起来像
#: 一段「菜谱」：往 0 秒放一个噪声、0.02 秒放一层下滑音……

_SPECS = {}
#: name -> [Sound, ...]（变体）。init() 之后才填。
_SND = {}


def sound(name, seconds, peak=0.8, variants=1):
    """把一个生成函数注册成音效。

    variants > 1 时会生成多个随机抖动版本，播放时随机挑一个 ——
    连打同样的牌不会每次都听出「同一段录音」的机械感。
    """
    def deco(fn):
        _SPECS[name] = {"sec": seconds, "peak": peak,
                        "variants": variants, "build": fn}
        return fn
    return deco


# ========================= 打击类（打击感的核心） =========================

@sound("hit_light", 0.20, peak=0.78, variants=3)
def _(b, rng):
    """轻打击（1~6 点伤害）：一声清脆的「嗒」。

    高频噪声很短很亮 —— 这一下负责「锐」；身体层下滑到 140Hz，
    给一点「实心」的感觉就收住，不拖尾。
    """
    b.noise(0.0, 0.035, amp=0.75, decay=3.4, lp=0.85, hp=0.9)
    b.tone(0.0, 0.16, rng.uniform(400, 460), 150, amp=0.55,
           wave="triangle", decay=2.6)
    b.tone(0.0, 0.13, 130, 62, amp=0.40, wave="sine", decay=1.9)


@sound("hit_mid", 0.26, peak=0.84, variants=3)
def _(b, rng):
    """中打击（7~14 点伤害）：加了方波「啪」和更深的低频下坠。"""
    b.noise(0.0, 0.05, amp=0.85, decay=3.0, lp=0.8, hp=0.85)
    b.tone(0.0, 0.05, rng.uniform(700, 800), 300, amp=0.22, wave="square",
           decay=2.0)
    b.tone(0.0, 0.22, rng.uniform(330, 370), 110, amp=0.60,
           wave="triangle", decay=2.4)
    b.tone(0.0, 0.20, 105, 48, amp=0.42, wave="sine", decay=1.8)


@sound("hit_heavy", 0.36, peak=0.90, variants=3)
def _(b, rng):
    """重打击（15~29 点伤害）：四层叠加 + 软饱和。

    尾巴特意留长（0.34s 的隆隆声），让这一下「有余震」。
    """
    b.noise(0.0, 0.07, amp=0.95, decay=2.6, lp=0.75, hp=0.8)
    b.tone(0.0, 0.07, rng.uniform(760, 880), 320, amp=0.26, wave="square",
           decay=1.8)
    b.tone(0.0, 0.30, rng.uniform(280, 320), 85, amp=0.65,
           wave="triangle", decay=2.2)
    b.tone(0.0, 0.28, 175, 36, amp=0.60, wave="sine", decay=1.6)
    b.noise(0.03, 0.32, amp=0.30, decay=1.4, lp=0.10, hp=0.0)
    b.drive(1.5)


@sound("hit_massive", 0.62, peak=1.0)
def _(b, rng):
    """巨大打击（30 点以上，比如 9² = 81 的平方组合）：全档最狠的一发。

    多了一段「蓄力扫频」（起手 80ms 由闷变亮的噪声）+ 金属余韵，
    听起来像一发重炮砸下来。这是玩家打出平方组合时最该爽到的一刻。
    """
    # 蓄力：由暗到亮的扫频，制造「来了」的预感
    b.noise(0.0, 0.09, amp=0.45, decay=1.2, lp=0.06, sweep=0.9, hp=0.2)
    # 主爆音
    b.noise(0.07, 0.10, amp=1.0, decay=2.2, lp=0.8, hp=0.75)
    b.tone(0.07, 0.10, 900, 340, amp=0.30, wave="square", decay=1.6)
    # 身体：锯齿波下滑，带一点脏
    b.tone(0.07, 0.40, 260, 55, amp=0.45, wave="saw", decay=2.0)
    # 重量
    b.tone(0.07, 0.46, 130, 30, amp=0.85, wave="sine", decay=1.4)
    # 金属余韵
    b.tone(0.09, 0.30, 1180, 1050, amp=0.16, wave="sine", decay=3.2)
    b.tone(0.09, 0.26, 1770, 1600, amp=0.10, wave="sine", decay=3.6)
    # 余震
    b.noise(0.14, 0.44, amp=0.34, decay=1.2, lp=0.07)
    b.drive(1.85)


@sound("hit_block", 0.30, peak=0.80)
def _(b, rng):
    """格挡（伤害被挡下）：一声金属「铛」。

    两个高频正弦 + 快起音 = 金属敲击；底下垫一个低频 thump，
    表示「挡住了，但还是有分量」。
    """
    b.noise(0.0, 0.03, amp=0.6, decay=3.5, lp=0.9, hp=0.95)
    b.tone(0.0, 0.26, 1420, 1380, amp=0.34, wave="sine", decay=3.4)
    b.tone(0.0, 0.22, 2130, 2060, amp=0.20, wave="sine", decay=3.8)
    b.tone(0.0, 0.14, 190, 95, amp=0.42, wave="triangle", decay=2.4)


@sound("hurt", 0.34, peak=0.76, variants=2)
def _(b, rng):
    """玩家挨打：闷响 + 下行两音。

    故意做得**不刺耳**（峰值 0.76，比打击音低一档）：小朋友被打不该
    被声音吓到，只要让他「知道掉血了」就够。
    """
    b.tone(0.0, 0.20, 150, 60, amp=0.70, wave="sine", decay=1.8)
    b.noise(0.0, 0.06, amp=0.45, decay=2.8, lp=0.5, hp=0.5)
    b.tone(0.06, 0.16, note("A4"), note("E4"), amp=0.22,
           wave="triangle", decay=2.2)


@sound("enemy_die", 0.70, peak=0.85)
def _(b, rng):
    """敌人倒下：下行扫频 + 噪声散开 + 一点余晖。

    「散开」的感觉来自最后那段由亮变闷的噪声 —— 像沙子落地。
    """
    b.tone(0.0, 0.34, 620, 70, amp=0.45, wave="saw", decay=1.5)
    b.tone(0.0, 0.40, 300, 40, amp=0.55, wave="sine", decay=1.4)
    b.noise(0.0, 0.42, amp=0.55, decay=1.6, lp=0.5, sweep=-0.45, hp=0.3)
    b.tone(0.30, 0.34, note("C5"), note("C5"), amp=0.16, wave="sine",
           decay=3.0)


# ========================= 答题类（奖励反馈） =========================

@sound("answer_ok", 0.80, peak=0.82)
def _(b, rng):
    """答对！上行大调琶音 C5-E5-G5-C6，钟铃音色 + 高音闪烁。

    这是全游戏播放次数最多的「奖励音」，所以做得格外讲究：
      · 上行音阶 = 心理上的「上升、成功」，这是有共识的
      · 每个音都加了个 2 倍频泛音（钟铃感），比纯正弦「贵」
      · 尾巴撒了一点极短的高频噪声，像闪光
    """
    seq = ("C5", "E5", "G5", "C6")
    for i, nm in enumerate(seq):
        t = i * 0.075
        f = note(nm)
        b.tone(t, 0.42 - i * 0.05, f, amp=0.40, wave="sine", decay=2.8)
        b.tone(t, 0.26 - i * 0.03, f * 2.0, amp=0.15, wave="sine", decay=3.4)
    for i, t in enumerate((0.06, 0.14, 0.22, 0.30)):
        b.noise(t, 0.05, amp=0.16, decay=3.0, lp=0.95, hp=0.95)


@sound("answer_no", 0.50, peak=0.62)
def _(b, rng):
    """答错：柔和下行两音（E4→C4），音量压低。

    **刻意不用蜂鸣器/警报音**。小孩子卡在一道题上本来就沮丧，
    再来一记刺耳的错误音，下次他就不敢点提交了 —— 那会直接
    毁掉「做题 = 打怪」的正反馈。这里要传达的是「哦，再试试」。
    """
    b.tone(0.0, 0.30, note("E4"), note("E4"), amp=0.34,
           wave="triangle", decay=2.6)
    b.tone(0.13, 0.34, note("C4"), note("C4"), amp=0.32, wave="sine",
           decay=2.4)
    b.noise(0.0, 0.07, amp=0.18, decay=3.0, lp=0.25, hp=0.0)


@sound("combo_ok", 1.10, peak=0.88)
def _(b, rng):
    """组合成功：比 answer_ok 更长更华丽的琶音 + 收尾和弦。

    组合要花两张卡、答一道更难的题，所以反馈必须**明显比单卡更响** ——
    不然玩家会觉得「组合没什么好处」。最后那个三和弦就是「盖章」。
    """
    seq = ("C5", "E5", "G5", "C6", "E6", "G6")
    for i, nm in enumerate(seq):
        t = i * 0.065
        f = note(nm)
        b.tone(t, 0.50 - i * 0.045, f, amp=0.34, wave="sine", decay=2.6)
        b.tone(t, 0.30 - i * 0.03, f * 2.0, amp=0.12, wave="sine", decay=3.2)
    # 上行扫频垫在底下，把整段「托」起来
    b.tone(0.0, 0.45, 520, 1560, amp=0.10, wave="triangle", decay=1.2)
    # 收尾和弦
    for nm in ("C5", "E5", "G5", "C6"):
        b.tone(0.42, 0.60, note(nm), amp=0.20, wave="sine", decay=2.2)
    for t in (0.05, 0.13, 0.21, 0.29, 0.37, 0.45):
        b.noise(t, 0.05, amp=0.14, decay=3.0, lp=0.95, hp=0.95)


# ========================= 卡牌 / 界面类 =========================

@sound("card_select", 0.13, peak=0.58)
def _(b, rng):
    """选中一张牌：短促上行 blip（G5→C6）。"""
    b.tone(0.0, 0.10, note("G5"), note("C6"), amp=0.42,
           wave="triangle", decay=2.6)
    b.noise(0.0, 0.02, amp=0.25, decay=4.0, lp=0.95, hp=0.9)


@sound("card_deselect", 0.11, peak=0.45)
def _(b, rng):
    """取消选中：下行 blip（C6→G5），比选中音轻。"""
    b.tone(0.0, 0.09, note("C6"), note("G5"), amp=0.34,
           wave="triangle", decay=2.8)


@sound("card_draw", 0.30, peak=0.52)
def _(b, rng):
    """抽牌：纸牌划过空气的「唰」。

    做法是噪声 + 低通由闷变亮再变闷 —— 单独一段噪声是「沙沙」，
    让滤波器走一个来回才有「划过去」的方向感。
    """
    b.noise(0.0, 0.14, amp=0.60, decay=1.6, lp=0.08, sweep=0.85, hp=0.4)
    b.noise(0.12, 0.16, amp=0.40, decay=2.2, lp=0.75, sweep=-0.6, hp=0.5)


@sound("card_play", 0.32, peak=0.68)
def _(b, rng):
    """出牌：一阵下坠的风声 + 落地的「嗒」。"""
    b.noise(0.0, 0.20, amp=0.55, decay=1.8, lp=0.7, sweep=-0.5, hp=0.5)
    b.tone(0.0, 0.16, note("E5"), note("A4"), amp=0.26, wave="triangle",
           decay=2.4)
    b.tone(0.12, 0.18, 320, 120, amp=0.34, wave="triangle", decay=2.6)


@sound("combo_charge", 0.46, peak=0.70)
def _(b, rng):
    """组合起手：上行蓄力扫频，提示「两道算式正在合并」。

    和 hit_massive 的蓄力段是同一个动机，但更长更亮 —— 玩家会下意识
    把「这个声音」和「接下来那一下很疼」联系起来。
    """
    b.noise(0.0, 0.34, amp=0.50, decay=1.1, lp=0.05, sweep=1.0, hp=0.2)
    b.tone(0.0, 0.36, 420, 1240, amp=0.22, wave="triangle", decay=1.4)


@sound("quiz_open", 0.34, peak=0.58)
def _(b, rng):
    """题目弹出：两音「问句」动机（G4→C5，上行小二度结尾 = 疑问感）。"""
    b.tone(0.0, 0.16, note("G4"), amp=0.34, wave="triangle", decay=3.0)
    b.tone(0.10, 0.22, note("C5"), amp=0.34, wave="sine", decay=2.8)


@sound("key_tap", 0.05, peak=0.34)
def _(b, rng):
    """答题时敲键盘：极短极轻的点击，不能抢戏（一秒可能响好几下）。"""
    b.noise(0.0, 0.025, amp=0.5, decay=4.0, lp=0.9, hp=0.85)
    b.tone(0.0, 0.03, 1400, 1100, amp=0.20, wave="sine", decay=3.5)


@sound("ui_hover", 0.06, peak=0.30)
def _(b, rng):
    """鼠标划过按钮：一声很轻的高音 tick（存在感刚好，不吵）。"""
    b.tone(0.0, 0.04, 1750, 1700, amp=0.34, wave="triangle", decay=3.4)
    b.noise(0.0, 0.015, amp=0.20, decay=4.0, lp=0.95, hp=0.9)


@sound("ui_click", 0.10, peak=0.62)
def _(b, rng):
    """通用按钮点击：明亮的方波短音 + 一颗噪声「颗粒」。"""
    b.tone(0.0, 0.06, 880, 1250, amp=0.34, wave="square", decay=3.0)
    b.tone(0.0, 0.09, 440, 620, amp=0.26, wave="triangle", decay=2.6)
    b.noise(0.0, 0.02, amp=0.34, decay=4.0, lp=0.9, hp=0.85)


@sound("ui_back", 0.20, peak=0.55)
def _(b, rng):
    """返回 / 取消：下行两音。"""
    b.tone(0.0, 0.08, note("E5"), amp=0.32, wave="triangle", decay=3.0)
    b.tone(0.07, 0.12, note("A4"), amp=0.32, wave="sine", decay=2.8)


@sound("ui_deny", 0.26, peak=0.60)
def _(b, rng):
    """操作不可用（能量不够 / 走不到那个节点）：短促低鸣。

    用「低 + 闷」而不是「尖 + 响」来表达拒绝 —— 尖的否定音会让人烦躁，
    闷的听起来像「暂时不行」，更适合小朋友。
    """
    b.tone(0.0, 0.20, 230, 190, amp=0.40, wave="pulse", decay=2.0)
    b.tone(0.0, 0.16, 115, 92, amp=0.34, wave="sine", decay=2.2)


@sound("shield", 0.34, peak=0.66)
def _(b, rng):
    """获得格挡：柔和的金属上行闪光。

    刻意**不用** hit_block 那种「铛」——那是被挡下敌人攻击时用的。
    自己上盾和被敲一下是两件事，声音也该是两个。
    """
    b.tone(0.0, 0.22, note("E5"), note("B5"), amp=0.30, wave="triangle",
           decay=2.6)
    b.tone(0.04, 0.20, note("B5"), note("E6"), amp=0.18, wave="sine",
           decay=3.0)
    b.noise(0.0, 0.05, amp=0.20, decay=3.2, lp=0.92, hp=0.9)


@sound("turn_start", 0.42, peak=0.60)
def _(b, rng):
    """新回合开始：一声轻快的「叮」+ 一点风声。

    回合制游戏里这是节奏点。有了它，玩家能听出「又轮到我出牌了」，
    不用一直盯着屏幕上的回合数。
    """
    b.tone(0.0, 0.30, note("G5"), amp=0.30, wave="sine", decay=2.6)
    b.tone(0.02, 0.24, note("D6"), amp=0.16, wave="sine", decay=3.0)
    b.noise(0.0, 0.16, amp=0.22, decay=2.4, lp=0.45, sweep=0.5, hp=0.45)


@sound("node_move", 0.30, peak=0.62)
def _(b, rng):
    """地图上前进一步：轻快的两音上行 + 一点点脚步声。"""
    b.tone(0.0, 0.13, note("D5"), amp=0.32, wave="triangle", decay=2.8)
    b.tone(0.09, 0.18, note("A5"), amp=0.30, wave="sine", decay=2.6)
    b.noise(0.0, 0.06, amp=0.24, decay=3.0, lp=0.6, hp=0.6)


@sound("battle_start", 0.85, peak=0.84)
def _(b, rng):
    """遭遇敌人：两声低沉的鼓 + 上行紧绷感。

    这是「要打架了」的信号。两下鼓点之间留半拍，像心跳 ——
    小朋友一听就知道「要认真了」。
    """
    for t, amp in ((0.0, 0.80), (0.30, 0.70)):
        b.tone(t, 0.26, 130, 46, amp=amp, wave="sine", decay=2.0)
        b.noise(t, 0.09, amp=0.40, decay=2.6, lp=0.4, hp=0.35)
    b.tone(0.52, 0.32, note("A3"), note("A4"), amp=0.24, wave="triangle",
           decay=1.8)


# ========================= 流程 / 奖励类 =========================

@sound("coin", 0.30, peak=0.66)
def _(b, rng):
    """金币：经典的两声「叮」（B5→E6）。

    电子游戏里最普及的奖励音，小朋友就算没玩过游戏也有「拿到东西了」
    的条件反射。直接照这个共识做，比自创一个音高效得多。
    """
    b.tone(0.0, 0.09, note("B5"), amp=0.40, wave="square", decay=3.2)
    b.tone(0.07, 0.22, note("E6"), amp=0.40, wave="square", decay=2.8)
    b.tone(0.07, 0.20, note("E6") * 2, amp=0.10, wave="sine", decay=3.4)


@sound("relic", 1.25, peak=0.80)
def _(b, rng):
    """获得遗物：钟琴上行 + 高音闪烁，比答对更「贵重」。"""
    seq = ("G4", "C5", "E5", "G5", "C6")
    for i, nm in enumerate(seq):
        t = i * 0.085
        f = note(nm)
        b.tone(t, 0.70 - i * 0.06, f, amp=0.30, wave="sine", decay=2.2)
        b.tone(t, 0.45, f * 2.76, amp=0.09, wave="sine", decay=3.0)
    for t in (0.10, 0.20, 0.30, 0.42, 0.55, 0.70, 0.85):
        b.noise(t, 0.07, amp=0.13, decay=2.8, lp=0.95, hp=0.95)
    for nm in ("C5", "E5", "G5"):
        b.tone(0.46, 0.75, note(nm), amp=0.16, wave="sine", decay=1.9)


@sound("heal", 0.75, peak=0.62)
def _(b, rng):
    """回血：温暖的三音上行，慢起音（像暖流而不是开关）。"""
    for i, nm in enumerate(("C4", "E4", "G4", "C5")):
        b.tone(i * 0.09, 0.55, note(nm), amp=0.24, wave="sine",
               attack=0.03, decay=2.0)
    b.tone(0.0, 0.55, note("C4") / 2, amp=0.18, wave="sine",
           attack=0.05, decay=1.8)


@sound("upgrade", 0.95, peak=0.74)
def _(b, rng):
    """卡牌强化：金属打磨感上行 + 一声定音。

    用方波 + 快衰减做出「齿轮转动」的机械感，最后落到高音表示完成。
    """
    for i, stepf in enumerate((1.0, 1.19, 1.41, 1.68)):
        b.tone(i * 0.09, 0.11, note("A4") * stepf, amp=0.24, wave="square",
               decay=2.6)
    b.tone(0.30, 0.55, note("A5"), amp=0.30, wave="sine", decay=2.2)
    b.tone(0.30, 0.40, note("E6"), amp=0.14, wave="sine", decay=2.8)
    b.noise(0.30, 0.10, amp=0.16, decay=3.0, lp=0.9, hp=0.9)


@sound("floor_clear", 1.15, peak=0.80)
def _(b, rng):
    """通过一层：一阵风 + 上行纯五度 + 高音尾音。"""
    b.noise(0.0, 0.55, amp=0.40, decay=1.3, lp=0.10, sweep=0.7, hp=0.25)
    b.tone(0.0, 0.30, note("C5"), note("G5"), amp=0.26, wave="triangle",
           decay=1.8)
    b.tone(0.26, 0.60, note("C6"), amp=0.30, wave="sine", decay=2.0)
    b.tone(0.26, 0.45, note("G5"), amp=0.18, wave="sine", decay=2.4)
    for t in (0.30, 0.42, 0.55, 0.70):
        b.noise(t, 0.06, amp=0.12, decay=3.0, lp=0.95, hp=0.95)


@sound("win", 1.85, peak=0.92)
def _(b, rng):
    """战斗胜利：小号角式上行 + 收尾长和弦。

    速度上刻意用「附点节奏」（长-短），这是号角最典型的韵律，
    一听就「赢了」。
    """
    # 号角：C5 - G5（附点） - C6
    b.tone(0.00, 0.22, note("C5"), amp=0.36, wave="square", decay=2.2)
    b.tone(0.18, 0.24, note("G5"), amp=0.36, wave="square", decay=2.2)
    b.tone(0.42, 0.30, note("C6"), amp=0.38, wave="square", decay=2.0)
    # 上行跑动
    for i, nm in enumerate(("E5", "G5", "C6", "E6")):
        b.tone(0.62 + i * 0.055, 0.20, note(nm), amp=0.26,
               wave="triangle", decay=2.6)
    # 收尾和弦（长）
    for nm in ("C5", "E5", "G5", "C6"):
        b.tone(0.80, 1.00, note(nm), amp=0.22, wave="sine", decay=1.5)
    b.tone(0.80, 1.00, note("C4"), amp=0.20, wave="sine", decay=1.5)
    b.noise(0.80, 0.20, amp=0.14, decay=2.6, lp=0.95, hp=0.9)


@sound("lose", 1.60, peak=0.66)
def _(b, rng):
    """战败：缓慢下行，像一声叹息。

    **刻意做得柔和**（峰值 0.66，全档最低之一）：输掉一局本来就难受，
    音效再沉重会让孩子直接关掉游戏。让它听起来是「可惜了」而不是
    「你完蛋了」。
    """
    for i, nm in enumerate(("A4", "F4", "D4", "A3")):
        b.tone(i * 0.24, 0.90, note(nm), amp=0.26, wave="sine",
               attack=0.04, decay=1.6)
    b.tone(0.0, 1.30, note("D3"), amp=0.22, wave="sine",
           attack=0.06, decay=1.3)


# ========================= 背景音乐 =========================
# BGM 也是合成出来的：五声音阶 + 简单和弦进行。选五声音阶是因为它
# **没有半音冲突**（任意两个音同时响都不会难听），这样"代码随机生成
# 也永远不会踩到难听的和声"—— 这是让程序生成音乐能听的保险丝。

@sound("bgm_explore", 12.0, peak=0.70)
def _(b, rng):
    """探索 / 菜单 / 商店 / 休整：C 大调五声音阶，慢速和弦垫 + 稀疏钟琴。

    速度 80BPM，一个和弦 3 秒，四个和弦一轮（C - Am - F - G）。
    全部音符都在 11.9 秒前衰减干净，这样循环回开头时不会有咔哒声。
    """
    bars = (
        ("C3", ("C4", "E4", "G4")),
        ("A2", ("A3", "C4", "E4")),
        ("F2", ("F3", "A3", "C4")),
        ("G2", ("G3", "B3", "D4")),
    )
    for i, (bass, chord) in enumerate(bars):
        t = i * 3.0
        b.tone(t, 2.95, note(bass), amp=0.30, wave="sine",
               attack=0.5, release=1.3, env="pad")
        b.tone(t, 2.95, note(bass) * 2, amp=0.10, wave="triangle",
               attack=0.6, release=1.3, env="pad")
        for nm in chord:
            b.tone(t, 2.95, note(nm), amp=0.13, wave="sine",
                   attack=0.7, release=1.4, env="pad")
    # 稀疏的钟琴旋律（C 大调五声音阶：C D E G A）
    melody = ((0.90, "E5"), (2.10, "G5"), (3.90, "A5"), (5.10, "G5"),
              (6.20, "E5"), (7.50, "D5"), (8.70, "E5"), (10.00, "D5"),
              (10.90, "C5"))
    for t, nm in melody:
        f = note(nm)
        b.tone(t, 0.85, f, amp=0.24, wave="sine", decay=2.4)
        b.tone(t, 0.55, f * 2.0, amp=0.07, wave="sine", decay=3.0)


@sound("bgm_battle", 12.0, peak=0.70)
def _(b, rng):
    """战斗：A 小调五声音阶，脉冲低音 + 极轻的节拍，比探索曲紧一点。

    刻意**不加旋律**：战斗中玩家在算题，脑子里已经有一个声音了，
    再来一条旋律会抢注意力。这里只给节奏和和声「托底」。
    """
    beat = 0.5                        # 120BPM
    bars = (
        ("A2", ("A3", "C4", "E4")),
        ("F2", ("F3", "A3", "C4")),
        ("C3", ("C4", "E4", "G4")),
        ("G2", ("G3", "B3", "D4")),
    )
    for i, (bass, chord) in enumerate(bars):
        t = i * 3.0
        # 和弦垫（每小节一个，缓慢）
        for nm in chord:
            b.tone(t, 2.90, note(nm), amp=0.11, wave="sine",
                   attack=0.45, release=1.1, env="pad")
        # 脉冲低音：每拍一下，第 1 拍重、第 4 拍补一个八度
        for k in range(6):
            bt = t + k * beat
            if k % 3 == 2:
                continue              # 留白，避免机械
            f = note(bass)
            b.tone(bt, 0.32, f, amp=0.34 if k == 0 else 0.24,
                   wave="triangle", decay=2.2)
        # 极轻的鼓点：每小节两次低频「咚」 + 细碎的高频沙锤
        for bt in (t, t + 1.5):
            b.tone(bt, 0.16, 96, 44, amp=0.30, wave="sine", decay=2.6)
        for k in range(6):
            b.noise(t + k * beat + 0.25, 0.03, amp=0.09, decay=4.0,
                    lp=0.95, hp=0.95)
    # 收尾把尾巴接回开头（最后一个和弦延到 11.9 秒）
    b.tone(10.5, 1.35, note("E4"), amp=0.10, wave="sine",
           attack=0.4, release=0.7, env="pad")


# ---------------------------------------------------------------------------
# 四、播放引擎
# ---------------------------------------------------------------------------

_ok = False             # 混音器 + 音效是否就绪。没就绪时所有接口都是安全空操作
_sfx_on = True
_bgm_on = True
_sfx_vol = 0.85         # 音效总音量
_bgm_vol_set = 0.50     # 背景音乐总音量（刻意比音效低，别抢）

_count = 0              # 累计播放次数（主循环用它判断「这次点击出没出声」）
_gate = {}              # 限流用：key -> 上次播放的时刻(ms)
_later = []             # 延时播放队列：[剩余秒数, 名字, 音量, key, 限流间隔]

_ch_bgm = None          # 0 号声道，专供背景音乐
_bgm_cur = None         # 正在播的曲名
_bgm_pending = None     # 排队等着播的曲名（等淡出结束）
_bgm_mode = "idle"      # idle / in / out / play
_bgm_vol = 0.0
_bgm_fade = 0.8

#: 合成交给后台线程做 —— 全部音效算完要 1.4 秒，同步做会让启动明显卡住。
#: 线程只算 PCM 字节；建 pygame.Sound 必须回主线程（要碰混音器）。
_jobs = queue.Queue()
_thread = None
#: 已建好的 Sound 必须**持有它那份 PCM 字节的引用**。
#: pygame 从 buffer 建 Sound 时是「包一层」而不是复制（Mix_QuickLoad_RAW），
#: 字节对象一旦被回收，声音就变成随机噪声甚至崩掉 —— 这条真踩过类似的坑，
#: 所以这里显式留着不放。总共才几 MB，不值得省。
_PCM_KEEP = []

#: 合成顺序：玩家最先听到的排最前，BGM 放最后。
#: BGM 要 1 秒才合成好，但主循环每帧都会重试起播，晚一秒进音乐**完全无感**；
#: 反过来如果把 BGM 排前面，开局点头几下都是哑的 —— 那才是问题。
_BUILD_ORDER = (
    "ui_hover", "ui_click", "ui_back", "ui_deny",
    "card_select", "card_deselect", "card_draw", "card_play",
    "key_tap", "quiz_open", "answer_ok", "answer_no",
    "combo_charge", "combo_ok",
    "hit_light", "hit_mid", "hit_heavy", "hit_block", "hit_massive",
    "shield", "hurt", "enemy_die", "turn_start", "battle_start",
    "node_move", "coin", "relic", "heal", "upgrade", "floor_clear",
    "win", "lose",
    "bgm_battle", "bgm_explore",
)

#: 设置文件（和存档放一起）。读写失败一律静默 —— 记不住音量不是崩溃理由
_SETTINGS_NAME = "audio.json"


def make_sound(raw, keep=True):
    """把 PCM 字节包成 pygame.Sound（**只能在主线程调**）。

    keep=True 会把字节留在 _PCM_KEEP 里。这个参数不是可选项 ——
    不 keep 的话 Sound 引用的内存随时可能被回收，声音会变成爆音。
    """
    if keep:
        _PCM_KEEP.append(raw)
    return pygame.mixer.Sound(buffer=raw)


def _build_one(name, spec, variant):
    """算出一条音效的 PCM 字节。纯计算，不碰 pygame，所以能在线程里跑。"""
    buf = _Buf(spec["sec"])
    spec["build"](buf, random.Random(hash(name) * 31 + variant))
    return buf.to_pcm(spec["peak"])


def _worker(order):
    """后台合成线程：逐个算，算好一个就往队列里放一个。

    线程与主线程之间**只通过一个 queue 传递不可变数据**（名字 + bytes），
    共享状态为零 —— 不用锁，也不会出现「合成到一半被读」的问题。
    """
    for name in order:
        spec = _SPECS.get(name)
        if not spec:
            continue
        pcms = []
        for v in range(spec["variants"]):
            try:
                pcms.append(_build_one(name, spec, v))
            except (ValueError, IndexError, OverflowError, MemoryError):
                break                   # 这条炸了就丢它一个，不影响别人
        if pcms:
            _jobs.put((name, pcms))


def _drain():
    """把线程已经算好的音效取出来建成 Sound（主线程，每帧调一次）。"""
    while True:
        try:
            name, pcms = _jobs.get_nowait()
        except queue.Empty:
            return
        try:
            _SND[name] = [make_sound(b) for b in pcms]
        except pygame.error:
            pass


def pre_init():
    """在 pygame.init() **之前**调用，把混音器参数提前定好。

    好处是省掉「pygame 先按 44100 开一遍、我们再关掉重开」这一步。
    不调也行 —— init() 里会自己纠正。
    """
    try:
        pygame.mixer.pre_init(SR, -16, CHANNELS, BUFFER)
    except (pygame.error, AttributeError):
        pass


def init(force=False):
    """建混音器 + 合成全部音效。幂等；任何失败都只是「没声音」，不抛异常。

    返回 True = 有声音可用。
    """
    global _ok, _ch_bgm, _sfx_on, _bgm_on
    if _ok and not force:
        return True

    want = (SR, -16, CHANNELS)
    try:
        cur = pygame.mixer.get_init()
        if cur != want:
            if cur:
                pygame.mixer.quit()       # 参数不对就重开（比如被 pygame.init 按 44100 开了）
            pygame.mixer.init(frequency=SR, size=-16, channels=CHANNELS,
                              buffer=BUFFER)
        # 24 个声道足够几十种音效重叠；0 号留给 BGM（set_reserved 之后
        # Sound.play() 不会再自动占用它，BGM 不会被音效挤掉）
        pygame.mixer.set_num_channels(24)
        pygame.mixer.set_reserved(1)
        _ch_bgm = pygame.mixer.Channel(0)
    except (pygame.error, OSError):
        _ok = False
        return False

    # 合成交给后台线程。这一步**立刻返回**，所以启动不会被 1.4 秒的
    # 合成卡住；音效算好一个就能用一个（_drain 每帧来取）。
    global _thread
    _SND.clear()
    _PCM_KEEP.clear()
    while not _jobs.empty():             # force 重建时清掉上一轮的残留
        try:
            _jobs.get_nowait()
        except queue.Empty:
            break
    order = [n for n in _BUILD_ORDER if n in _SPECS]
    order += [n for n in _SPECS if n not in _BUILD_ORDER]   # 新加的音效兜底也排进去
    _thread = threading.Thread(target=_worker, args=(order,),
                               name="sfx-build", daemon=True)
    _thread.start()

    _ok = True
    _load_settings()
    return True


def shutdown():
    """退出时收尾（关 BGM、关混音器）。"""
    global _ok, _bgm_cur, _bgm_pending, _bgm_mode
    if _ok:
        try:
            _ch_bgm.stop()
        except pygame.error:
            pass
    _bgm_cur = None
    _bgm_pending = None
    _bgm_mode = "idle"
    _later.clear()
    _ok = False


def _pick(snds):
    return snds[random.randrange(len(snds))]


def play(name, vol=1.0, key=None, gap_ms=70):
    """播一个音效。

    vol      额外音量系数（0~1）
    key      限流用的身份，默认就是音效名。同名音效在 gap_ms 内只会响一次 ——
             没有这个，一秒内连点五张牌会叠成「哒哒哒哒哒」的噪音
    gap_ms   限流间隔，0 = 不限流（关键反馈应该设 0，保证每次都听得见）
    """
    global _count
    if not _ok or not _sfx_on or vol <= 0.0:
        return
    snds = _SND.get(name)
    if not snds:
        return

    if gap_ms > 0:
        now = pygame.time.get_ticks()
        k = key or name
        if now - _gate.get(k, -100000) < gap_ms:
            return
        _gate[k] = now

    try:
        ch = _pick(snds).play()
    except pygame.error:
        return
    if ch is not None:
        # 所有声道都被占满时 play() 返回 None —— 这是天然的并发上限，
        # 直接放弃这一次，不要抢别人的声道
        try:
            ch.set_volume(max(0.0, min(1.0, vol * _sfx_vol)))
        except pygame.error:
            pass
    _count += 1


def play_after(name, delay, vol=1.0, key=None, gap_ms=0):
    """过 `delay` 秒（**游戏时间**）再播。

    为什么需要「延时播放」：一串反馈是有顺序的 ——
    「敌人倒地」→（0.5 秒）→「胜利号角」，同时播就糊成一坨。
    游戏里到处都在按这个套路排反馈，所以把这件事做进引擎，
    而不是让每个调用方自己记计时器。

    计时用主循环喂进来的 dt 累减，**不是**用墙钟（perf_counter）——
    这样它和 BGM 淡入淡出、角色动画走的是同一条时间轴：
    游戏卡一下、或者被暂停住，延时队列也跟着一起停，
    不会出现「画面还停着，声音已经抢跑了」。
    """
    if not _ok or not _sfx_on:
        return
    _later.append([max(0.0, delay), name, vol, key, gap_ms])


def _run_later(dt):
    """推进延时队列（dt = 这一帧过去多少游戏秒）。"""
    i = 0
    while i < len(_later):
        it = _later[i]
        it[0] -= dt
        if it[0] <= 0.0:
            _later.pop(i)
            play(it[1], vol=it[2], key=it[3], gap_ms=it[4])
        else:
            i += 1


def count():
    """累计播放次数。主循环用它判断「这次点击场景自己出过声没有」。"""
    return _count


# ---------------- 背景音乐 ----------------

def play_bgm(name, fade=0.8):
    """切背景音乐。

    没有做真正的交叉淡入（两条轨互相叠加）—— 那是 4 个声道的复杂度，
    收益只是省掉 0.4 秒的间隙。这里用「先淡出旧的、再淡入新的」，
    状态机简单得多，听感上只是换场时顿一下，完全可接受。
    """
    global _bgm_pending, _bgm_fade, _bgm_mode
    if not _ok or not _bgm_on:
        return
    if name == _bgm_cur or name == _bgm_pending:
        return
    _bgm_pending = name
    _bgm_fade = max(0.15, fade)
    if _bgm_cur is not None:
        _bgm_mode = "out"


def stop_bgm(fade=0.5):
    """淡出并停止背景音乐。"""
    global _bgm_pending, _bgm_fade, _bgm_mode
    _bgm_pending = None
    _bgm_fade = max(0.15, fade)
    if _bgm_cur is not None:
        _bgm_mode = "out"


def update(dt):
    """每帧调一次：收取后台合成好的音效 + 推进 BGM 淡入淡出。"""
    global _bgm_cur, _bgm_pending, _bgm_mode, _bgm_vol
    if not _ok or _ch_bgm is None:
        return

    _drain()                            # 后台线程算好的音效在这里入库
    _run_later(dt)                      # 延时队列里到点的音效在这里播

    if _bgm_mode == "out":
        _bgm_vol -= dt / _bgm_fade
        if _bgm_vol <= 0.0:
            _bgm_vol = 0.0
            try:
                _ch_bgm.stop()
            except pygame.error:
                pass
            _bgm_mode = "idle"
            if _bgm_pending is None:
                _bgm_cur = None            # 彻底停了，之后还能重新点同一首
        else:
            _set_bgm_channel_vol()

    if _bgm_mode == "idle" and _bgm_pending and _bgm_on:
        snds = _SND.get(_bgm_pending)
        if not snds:
            # BGM 要 1 秒左右才合成完。**不能**在这里把 pending 丢掉 ——
            # 丢掉的话这一刻想播的曲子就永远播不出来了（会静音一整局）。
            # 保持排队，下一帧再来问，合成好自然就起播了。
            return
        _bgm_cur = _bgm_pending
        _bgm_pending = None
        try:
            _ch_bgm.play(_pick(snds), loops=-1)
        except pygame.error:
            _bgm_cur = None
            return
        _bgm_vol = 0.0
        _set_bgm_channel_vol()
        _bgm_mode = "in"

    elif _bgm_mode == "in":
        _bgm_vol += dt / _bgm_fade
        if _bgm_vol >= 1.0:
            _bgm_vol = 1.0
            _bgm_mode = "play"
        _set_bgm_channel_vol()


def _set_bgm_channel_vol():
    try:
        _ch_bgm.set_volume(_bgm_vol * _bgm_vol_set)
    except pygame.error:
        pass


# ---------------- 开关（F1 / F2） ----------------

def sfx_enabled():
    return _sfx_on


def bgm_enabled():
    return _bgm_on


def set_sfx(on):
    global _sfx_on
    _sfx_on = bool(on)
    _save_settings()
    return _sfx_on


def set_bgm(on):
    """开关背景音乐。

    这里**直接硬停**，不做「保留当前曲目、打开时接着放」那套记忆 ——
    主循环每帧都会问一次「这一屏该放哪首」，所以下一帧自然会重新淡入，
    状态机因此少一个分支（少一个分支就少一处会写错的地方）。
    """
    global _bgm_on, _bgm_cur, _bgm_pending, _bgm_mode, _bgm_vol
    _bgm_on = bool(on)
    _bgm_pending = None
    _bgm_cur = None
    _bgm_vol = 0.0
    if _ch_bgm is not None:
        try:
            _ch_bgm.stop()
        except pygame.error:
            pass
    _bgm_mode = "idle"
    _save_settings()
    return _bgm_on


def toggle_sfx():
    return set_sfx(not _sfx_on)


def toggle_bgm():
    return set_bgm(not _bgm_on)


def status():
    """一句话说明当前音频状态（给屏幕上的提示条用）。"""
    if not _ok:
        return "音频不可用"
    return "音效 %s　音乐 %s" % ("开" if _sfx_on else "关",
                                 "开" if _bgm_on else "关")


def key_hint():
    """底部提示条上追加的一小段说明。"""
    if not _ok:
        return ""
    return "　·　F1 音效%s　F2 音乐%s" % ("开" if _sfx_on else "关",
                                        "开" if _bgm_on else "关")


# ---------------- 设置持久化 ----------------

def _settings_path():
    try:
        return E.user_data_path(_SETTINGS_NAME)
    except Exception:                    # noqa: BLE001
        return None


def _save_settings():
    p = _settings_path()
    if p is None:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(str(p), "w", encoding="utf-8") as f:
            json.dump({"sfx": _sfx_on, "bgm": _bgm_on}, f)
    except (OSError, ValueError):
        pass                             # 存不下就算了，不值得为它报错


def _load_settings():
    global _sfx_on, _bgm_on
    p = _settings_path()
    if p is None or not p.is_file():
        return
    try:
        with open(str(p), "r", encoding="utf-8") as f:
            d = json.load(f)
        _sfx_on = bool(d.get("sfx", True))
        _bgm_on = bool(d.get("bgm", True))
    except (OSError, ValueError, TypeError):
        pass


def describe():
    """启动日志用的一行说明。"""
    if not _ok:
        return "音频：不可用（没有声卡 / 驱动打不开），游戏照常运行"
    # 合成是后台跑的：还在算的时候要让日志看得出「不是少了音效，是还没算完」
    done, total = built()
    stage = "音效 %d 种" % total if done >= total else "音效合成中 %d/%d" % (done, total)
    return "音频：%dHz %d声道　%s　音效%s　音乐%s" % (
        SR, CHANNELS, stage,
        "开" if _sfx_on else "关", "开" if _bgm_on else "关")


def ready():
    """音频是否可用（没有声卡时是 False —— 游戏照常能玩，只是没声音）。"""
    return _ok


def built():
    """后台合成进行到哪了：(已就绪条数, 总条数)。测试脚本用它等合成结束。"""
    return len(_SND), len(_SPECS)


def wait_ready(timeout=8.0):
    """等后台合成全部结束（只给测试/打包校验用，不要在主循环里调）。

    返回 True = 全部就绪。
    """
    import time as _t
    end = _t.perf_counter() + timeout
    while _t.perf_counter() < end:
        _drain()
        if len(_SND) >= len(_SPECS):
            return True
        _t.sleep(0.01)
    return False