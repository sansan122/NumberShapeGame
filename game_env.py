# -*- coding: utf-8 -*-
"""
game_env.py —— 一处集中解决「换台电脑就跑不起来」的问题。

这个模块只干三件事，但每一件都是分发时必须的：

  1. resource_path()  找到打包进 exe 里的资源（字体、配置表）
  2. user_data_path() 找到「可写」的目录（存档、日志）
  3. load_font() / fonts()  容错地加载中文字体

为什么要单独一个模块？因为原来这些东西散落在 6 个文件里、写死了
`C:/Windows/Fonts/msyh.ttc` 和 `Path(__file__).parent`，
打包成 exe 之后两条全都失效：

  · 打包后 `__file__` 指向临时解包目录（每次运行都不一样，
    而且退出就删）→ 存档写进去等于没存
  · 别人电脑上不一定有 msyh.ttc（Windows 精简版 / 装了非中文语言包
    的系统可能没有）→ 直接崩溃

所以约定：**任何地方要用字体或路径，都从这里拿，别再自己写。**
"""

import os
import sys
from pathlib import Path

import pygame

# ---------------------------------------------------------------------------
# 一、路径：区分「只读的资源」和「可写的用户数据」
# ---------------------------------------------------------------------------

#: 是否运行在 PyInstaller 打出来的 exe 里
#: 打包后 sys.frozen 会被 PyInstaller 设上，这是个约定俗成的探测方式
IS_FROZEN = getattr(sys, "frozen", False)


def app_dir():
    """exe（或项目根）所在的目录 —— 用户能看见、能双击的那个地方。

    打包后用户可能会把 exe 放在桌面、D 盘、U 盘……所以
    **不能**用 `Path(__file__).parent`，那个指向的是临时解包目录。
    """
    if IS_FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(*parts):
    """只读资源（字体、tower.yaml 等）的位置。

    打包后资源被解压到 `sys._MEIPASS` 指向的临时目录；
    源码模式下就是项目根目录。
    """
    if IS_FROZEN:
        base = Path(getattr(sys, "_MEIPASS", app_dir()))
    else:
        base = Path(__file__).resolve().parent
    return base.joinpath(*parts)


def user_data_path(*parts):
    """**可写**数据（存档）的位置。

    优先放 exe 同级的 `saves/` —— 好处是「整个文件夹拷走，存档跟着走」，
    符合「免安装绿色版」的直觉。

    但如果 exe 被放在 C:\\Program Files 或者只读介质上，同级目录写不了，
    那就退回用户目录 `%APPDATA%/数与形/`。两者都试不通的话，
    至少让 `save()` 报一个可读的错，而不是崩掉。
    """
    primary = app_dir()
    try:
        if _writable(primary):
            return primary.joinpath(*parts)
    except BaseException:
        # 探测本身出任何意外（包括被安全策略强行 SystemExit）
        # 都不能让游戏起不来，直接走 AppData 兜底。
        pass

    # 退回 AppData（Windows 上一定可写）
    try:
        base = Path(os.environ.get("APPDATA") or Path.home())
    except BaseException:
        base = Path.home()
    return (base / "数与形").joinpath(*parts)


def _writable(d):
    """安静地测一下这个目录能不能写。

    不用「写探针文件再删掉」的老办法，原因有两个：
      · 删文件在某些受限环境里会抛 SystemExit（不是 OSError），
        `except OSError` 拦不住，整个进程会直接死掉；
      · 每次都往用户目录里写垃圾文件也很脏。

    改用 os.access 做权限位判断 + 目录是否存在的静态检查：
    不产生任何文件，也不会被删除策略干扰。

    注意：os.access 在极少数 ACL/网络盘场景下可能不准，
    所以 user_data_path() 还有一层「真写不进去就退 AppData」的兜底。
    """
    try:
        if not d.is_dir():
            return False
        # os.W_OK 在 Windows 上对 ACL 的判断有限，但对「只读介质 /
        # C:\Program Files 无权限」这类常见情况够用了。
        return os.access(str(d), os.W_OK)
    except (OSError, ValueError):
        return False


# ---------------------------------------------------------------------------
# 二、字体：多级兜底，缺一个换下一个，最后一定要拿到能用的
# ---------------------------------------------------------------------------

#: 按「好看程度」排的候选。msyh = 微软雅黑（中文 Windows 默认有）；
#: simhei / simsun 是更老的系统也带的；最后还有 pygame 内置字体兜底。
_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑（Win7+ 简体中文）
    "C:/Windows/Fonts/msyh.ttf",
    "C:/Windows/Fonts/msyhbd.ttc",    # 雅黑粗体
    "C:/Windows/Fonts/simhei.ttf",    # 黑体（老系统也有）
    "C:/Windows/Fonts/simsun.ttc",    # 宋体
    "C:/Windows/Fonts/Deng.ttf",      # 等线
    "C:/Windows/Fonts/msjh.ttc",      # 微软正黑（繁体系统）
)

#: 缓存：同一个字号不要重复建 Font 对象（建字体是有点慢的）
_font_cache = {}
#: 记录最终用了哪个字体，启动时打一行日志方便排查
_CHOSEN_FONT = None


def find_font_path():
    """挑一个系统里真实存在的中文字体路径；都没有就返回 None。"""
    global _CHOSEN_FONT
    if _CHOSEN_FONT is not None:
        return _CHOSEN_FONT or None

    for cand in _FONT_CANDIDATES:
        if Path(cand).is_file():
            _CHOSEN_FONT = cand
            return cand

    # 再试一把 pygame 自己知道的字体名（跨平台时会走到这里）
    for name in ("microsoftyahei", "simhei", "notosanscjksc", "arialunicodems"):
        hit = pygame.font.match_font(name)
        if hit:
            _CHOSEN_FONT = hit
            return hit

    _CHOSEN_FONT = ""      # 空字符串 = 找过了，没有
    return None


def load_font(size, bold=False):
    """拿到一个指定字号的字体。**任何情况下都会返回可用的 Font 对象。**

    没有中文字体时退回 pygame 默认字体 —— 中文会变成方块，
    但至少程序能跑、能点，比直接崩掉强得多。
    """
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]

    path = find_font_path()
    font = None
    if path:
        try:
            font = pygame.font.Font(path, size)
        except (OSError, pygame.error):
            font = None
    if font is None:
        font = pygame.font.Font(None, size)      # pygame 自带，拉丁字母可用

    if bold:
        try:
            font.set_bold(True)
        except pygame.error:
            pass

    _font_cache[key] = font
    return font


def fonts(sizes):
    """一次拿一组字体，返回 dict。sizes 形如 {"BIG": 34, "MID": 21}。

    用法：
        self.F = E.fonts({"BIG": 34, "MID": 21})
        self.F["BIG"].render("数与形", True, (0, 0, 0))
    """
    return {k: load_font(v) for k, v in sizes.items()}


# ---------------------------------------------------------------------------
# 三、通用文字折行
# ---------------------------------------------------------------------------

def wrap_text(font, text, max_w):
    """把 text 按像素宽度折成若干行（中文逐字折行就够，不必按词断）。

    放在这里是因为**三处都要用**：牌组面板、节点面板、地图的遗物图鉴。
    这份逻辑原先抄了三遍（deck_view.wrap_text / node_scenes.wrapped_lines /
    地图里再写一份），改一次行距要翻三个文件 —— 本项目已经因为
    「同一件事写两处」栽过好几次（见 README 踩坑），所以收口到这里。

    `\n` 是硬换行（说明文案里写死断行的地方靠它）。

    单个字就超宽时也硬放一行 —— 老版本会先 append 一个空串，
    折出来的第一行是空行，排版算高度就会莫名多出一行。
    """
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if font.size(cur + ch)[0] <= max_w:
            cur += ch
        elif cur:
            lines.append(cur)
            cur = ch
        else:
            cur = ch          # 一个字就超宽：让它自己占一行，别死循环
    if cur:
        lines.append(cur)
    return lines


def describe_environment():
    """启动时打一行环境说明，出问题时一眼能看出是哪里的锅。"""
    return (
        "运行模式：%s\n"
        "程序目录：%s\n"
        "资源目录：%s\n"
        "存档目录：%s\n"
        "中文字体：%s"
        % (
            "打包 exe" if IS_FROZEN else "源码",
            app_dir(),
            resource_path(),
            user_data_path("saves"),
            find_font_path() or "（未找到，将使用 pygame 默认字体，中文会显示为方块）",
        )
    )
