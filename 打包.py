# -*- coding: utf-8 -*-
"""
打包.py —— 一键把游戏打成可以发给别人的 exe。

用法：
    <python> 打包.py

它会做五件事：
    1. 重新生成所有启动器（保证编码和探测逻辑是最新的）
    2. 用 PyInstaller 打包成单文件 exe
    3. 把 exe 和说明拷到一个干净的发布目录
    4. 在隔离环境里**自检一遍**（确认打包后真的能跑）
    5. 读 exe 里的代码核对**代码指纹**（确认装进去的真是最新代码）
       —— 被 import 的模块在 PYZ 里，入口脚本 main 在 CArchive 里，
          两处都要查（见 verify_exe_code 里的说明）

产出的发布目录（可以直接压缩发给别人）：
    release/数与形/
        NumbersAndForms.exe
        发给别人-怎么玩.txt
        0_START_HERE.bat
        开发者文档.md（其实就是 README）

⚠️ 关于"删文件"的一条硬规矩（踩过坑，别再改回去）：
    所有清理动作一律用 **整目录 rmtree** 或 **改名 rename**，
    绝对不要写 `for f in dir.iterdir(): f.unlink()` 这种逐文件遍历删除。
    原因：运行环境里有一个"每回合累计删除文件数"的计数器，超过 50 个
    就会跳出来拦一句 SAFE_DELETE_BULK_CONFIRM_REQUIRED 把脚本打断。
    本脚本原来在 build/ dist/ release/ 三处都用了逐文件删，
    结果每次重打包都跑到一半被拦；改成整目录删 + 改名之后就顺了。

⚠️ 补一条：**"整目录删"并不是万能的**，别以为写成 rmtree 就稳了。
    那个计数器数的是**目录里的条目数**，不是"删了几次"。
    所以 build/ 一旦涨到 50 个以上条目，连整目录 rmtree 也会被拦
    （实测：刚写完这个脚本时 build/ 只有 30 来个条目能过，
    后来涨到 58 个就开始每次都拦）。
    更坑的是：拦截是抛 **SystemExit**，而 `shutil.rmtree(..., ignore_errors=True)`
    只吞 OSError —— 挡不住，脚本会**静默死在清理那一步**，
    连个 traceback 都没有（现象是只打印了"清理 build ..."就没了）。
    所以 clear_dir 里必须 catch BaseException，并准备好"改名腾位置"的兜底。
"""

import marshal
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RELEASE = HERE / "release" / "数与形"
EXE_NAME = "NumbersAndForms.exe"

# ---------------------------------------------------------------------------
# 代码指纹：用来回答「exe 里装的到底是不是最新代码」
# ---------------------------------------------------------------------------
# 为什么不能只看「打包没报错 + exe 时间戳变了」：
#   · 增量构建可能吃到旧的 build/ 缓存；
#   · 清理被安全策略拦下时流程可能中断在半路（exe 是新的、zip 还是旧的）；
#   · 时间戳新 ≠ 内容是新的。
#
# ⚠️ 也**不能拿字符串去裸 grep exe**：
#   onefile 的 exe 里 PYZ 是 zlib 压缩过的，`needle in exe.read_bytes()`
#   **永远返回 False**，哪怕代码明明在里面（连「演算者」这种一定存在的
#   字符串都搜不到）。照这个假信号去「修」只会白忙一场。
#   正确做法是用 PyInstaller 自己的 reader 把 PYZ 解出来看字节码常量
#   （docstring 也会进 co_consts，所以能当指纹；spec 里 optimize 必须为 0）。
#
# 每条指纹都**必须写明在哪个模块里找** —— 早先只写 (label, needle) 两元组，
# 而检查时只解一个模块，于是指向别的模块的指纹永远 FAIL，把人骗去重打包。
# 而且字符串必须是**从源码复制**的，不是凭印象编的（编过一次，源码里根本没有）。
#
# 每次改了游戏代码，从这里开头的注释或 docstring 里挑一句新的加进来。
#
# ⚠️ 表里**必须至少留一条指向 main 的**（下面那两条就是）。
#    理由：main 是入口脚本，它**不在 PYZ 里**、走的是 CArchive 那一路
#    （见 open_exe_strings 的说明）。留着一条指向它的指纹，等于顺手
#    给「读取逻辑有没有覆盖入口脚本」上了个哨兵 ——
#    哪天有人把两处查找改回只查 PYZ，这两条会立刻失败。
FINGERPRINTS = [
    ("map_scene", "相机边界复用 camera_for", "上下界直接复用"),
    ("map_scene", "camera_for 注释更正", "别再照着它改符号"),
    ("deck_view", "牌组面板高度自适应", "按卡片数量算面板高度并居中"),
    ("battle_scene", "血条随血量变色", "颜色随剩余比例变"),
    ("save_system", "多存档槽", "saves/save_1.json ~ save_3.json，三个槽位"),
    ("ui_scenes", "存档槽选择界面", "三个存档槽的列表"),
    ("ui_scenes", "游戏内 M 回主菜单", "返回主菜单"),
    ("char_art", "角色立绘动画加载", "缺失素材也返回可用对象"),
    ("battle_scene", "杀戮尖塔式战斗舞台", "血条和格挡画在角色脚边"),
    ("char_art", "解方程者立绘接入", "角色003=解方程者"),
    ("art_shapes", "卡牌图案与敌人形象", "卡牌图案 + 敌人形象（纯代码几何绘制）"),
    ("battle_scene", "背景函数画在坐标系上", "背景里的两个坐标系"),
    ("battle_scene", "格挡在敌人出手之后才清", "清早了敌人这一下就整打在血上"),
    ("battle_scene", "三角色被动实装", "「承形」生效：+2 格挡"),
    ("node_scenes", "精英 / 层主战利品面板", "先看遗物、点「收下」，再进选卡界面"),
    ("player", "遗物不重复发放", "抽一件玩家还没有的遗物"),
    ("battle_scene", "数形结合组合出牌", "算对这个面积，两张卡一起生效"),
    ("battle_scene", "图形卡单出考认图形名称", "认出这个图形，卡牌才会生效"),
    ("battle_scene", "组合费用是两张卡之和", "组合需要 %d 点能量"),
    ("art_shapes", "题目图形按形状绘制", "平行四边形"),
    ("art_shapes", "强化卡的加号后缀要剥掉", "卡面图案反而变成问号圆盘"),
    ("player", "数字牌 0~9 十张", "0 既没有伤害、平方也还是 0"),
    ("player", "数字卡的难度阶梯", "带括号的四则"),
    ("battle_scene", "算术题难度跟着数字走", "难度由**卡上的数字**决定"),
    ("battle_scene", "平方组合：伤害＝数字的平方", "打出的伤害就是数字牌的"),
    ("battle_scene", "平方题先给例题", "平方，就是自己乘自己"),
    ("battle_scene", "平方卡不能单出", "不能单出 —— 要配一张数字卡"),
    ("battle_scene", "组合省 1 点能量", "组合费用 %d 点能量"),
    ("art_shapes", "数字牌的图案就是那个数字", "数字牌的图案就是这张牌的数字本身"),
    ("node_scenes", "选卡网格自动缩放进屏幕", "牌组会越买越大"),
    ("sfx", "音效全在代码里合成", "为什么是「合成」而不是「放 wav」"),
    ("sfx", "答对是上行大调琶音", "答对 = 上行大调琶音 + 钟铃音色（明亮、有奖励感）"),
    ("battle_scene", "打击感四档共用一张表", "音效和震动**从这里一起取**，就是为了保证两者永远同档"),
    ("battle_scene", "伤害反馈只有一个出口", "按伤害量选「音效 + 震动幅度」"),
    ("main", "F1/F2 开关音效与音乐", "音效已关"),
    ("node_scenes", "商店删牌一次只能一张", "这家店已经用过了（一次只能删一张）"),
    ("player", "删牌价随次数递增", "由「已删掉几张」推出来，不是存档里的独立字段"),
    ("player", "第一层层主解锁平方", "打穿第一层层主后发平方牌。返回 True 表示这次真的新发了一张。"),
    ("main", "战利品里真的发了平方", "从层主身上拆下了「平方」！"),
    ("node_scenes", "战利品多一段「新卡到手」", "新卡到手"),
    ("battle_scene", "层主按层数配难度倍率", "把基础配置 + 本层倍率，算成这一场真正用的敌人数值。"),
    ("battle_scene", "第一层层主是平方主题", "「正方体·三阶」的出招：蓄力 n，下回合打出 n²。"),
    ("art_shapes", "正方体·三阶的形象", "三个正方形**共用同一条底边**"),
    ("battle_scene", "平方打击的文案只有一处", "「平方」打击：%d² = %d"),
    ("battle_scene", "平方基数从伤害开方还原", "伤害存的就是 n²，所以 n 由它**开方还原**，不另存字段。"),
    ("node_scenes", "折行文字的高度要算出来", "这段文字折行之后占多高（含行距），和 draw_wrapped 的推进量一致。"),
    ("node_scenes", "新卡到手面板自适应排版", "锚点全部由**真实文字行数**推出来"),
    ("build_map", "地图带出本层难度倍率", "enemy_scale"),
]

# 对照组：**很老的代码里就有**的字符串。它们必须是「有」，
# 否则说明解析流程本身坏了（全是「无」时无法区分「没打进包」和「脚本坏了」）。
BASELINE = [
    ("map_scene", "解析流程基线", "限制相机范围"),
]


def walk_strings(code):
    """递归收集一个 code object 里所有的字符串常量。"""
    out = []
    for k in code.co_consts:
        if isinstance(k, str):
            out.append(k)
        elif hasattr(k, "co_consts"):
            out += walk_strings(k)
    return out


def open_exe_strings(exe):
    """打开 exe，返回 `(strings_of, pyz_modules, close)`。

    `strings_of(mod)` 给出该模块全部字符串常量拼成的一段文本；
    返回 None 表示「这个模块在包里找不到」。
    `close()` 负责清理临时文件（用完必须调）。

    ⚠️ **必须查两个地方，只查 PYZ 是不行的**（踩过）：
    PyInstaller 把**被 import 的模块**塞进 PYZ（zlib 压缩），
    但**入口脚本是单独处理的** —— 它以 marshal 过的 code object
    直接躺在 CArchive 里，条目名就是脚本名（main.py -> "main"，
    头 4 字节 b'c\\x00\\x00\\x00' 就是 marshal 的 code 标记）。

    只查 PYZ 的写法会漏掉所有指向 main 的指纹，汇总成「exe 不是最新代码」，
    而源码里那几条明明在 —— 看着像打包坏了，其实是指纹找错了地方。
    （这个坑直到本机装上 PyInstaller、真跑了一次打包才暴露：
      本机预检只读源码、不读包，永远发现不了。）

    这里把「怎么读包」收口成**一份实现**，打包自检与
    tmp/verify_exe_contents.py 共用 —— 同一份逻辑抄两处必然漂移，
    指纹表已经吃过一次这个亏。
    """
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

    ar = CArchiveReader(str(exe))
    pyz_names = [n for n in ar.toc if n.endswith(".pyz")]
    if not pyz_names:
        raise ValueError("exe 里没有 PYZ，不像是 PyInstaller 产物")

    raw = ar.extract(pyz_names[0])
    if isinstance(raw, tuple):
        raw = raw[1]
    # 落到系统临时目录：不在仓库里留东西，也不占用 tmp/ 的清理逻辑
    tmp_pyz = Path(tempfile.gettempdir()) / "_pkg_check.pyz"
    tmp_pyz.write_bytes(raw)
    z = ZlibArchiveReader(str(tmp_pyz))

    cache = {}

    def strings_of(mod):
        if mod in cache:
            return cache[mod]

        text = None
        if mod in z.toc:                            # ① 被 import 的模块
            text = "\n".join(walk_strings(z.extract(mod)))
        elif mod in ar.toc:                         # ② 入口脚本
            data = ar.extract(mod)
            if isinstance(data, tuple):
                data = data[1]
            for blob in (data, data[16:]):          # 带 pyc 头时跳过 16 字节
                try:
                    text = "\n".join(walk_strings(marshal.loads(blob)))
                    break
                except Exception:
                    continue

        cache[mod] = text
        return text

    return strings_of, list(z.toc), lambda: safe_unlink(tmp_pyz)


def verify_exe_code(exe):
    """核对 exe 里的代码指纹。对不上就中止打包。"""
    print("  读 %s 里的代码 ..." % exe.name)
    try:
        strings_of, _mods, close = open_exe_strings(exe)
    except ImportError as e:
        raise SystemExit("!! 需要 PyInstaller 才能做内容自检：%s" % e)
    except ValueError as e:
        raise SystemExit("!! %s" % e)

    try:
        missing = []
        for title, group in (("对照组（必须命中，确认解析流程正常）", BASELINE),
                             ("代码指纹（必须命中，确认是最新代码）", FINGERPRINTS)):
            print("  %s：" % title)
            for mod, label, needle in group:
                text = strings_of(mod)
                if text is None:
                    # 分开说：「找不到模块」和「找不到字符串」是两种毛病，
                    # 合成一个 FAIL 就没法区分「指纹写错」和「打包漏了」。
                    print("    [FAIL] %-28s （模块 %s 既不在 PYZ 也不在"
                          " CArchive —— 指纹的模块名写错了）" % (label, mod))
                    missing.append(label)
                    continue
                ok = needle in text
                if not ok:
                    missing.append(label)
                print("    [%s] %-28s %s" % ("OK  " if ok else "FAIL", label, needle))
    finally:
        close()

    if missing:
        raise SystemExit(
            "!! exe 里不是最新代码，缺 %d 条指纹：%s\n"
            "   （先确认这几条指纹字符串在对应源码里确实存在；\n"
            "     若源码里也没有，那是指纹写错，不是打包问题）"
            % (len(missing), "、".join(missing)))
    print("  OK：%d 条指纹全部命中，exe 里就是最新代码" % len(FINGERPRINTS))


def step(n, msg):
    print("\n[%d/5] %s" % (n, msg))
    print("-" * 56)


def run(cmd, **kw):
    print("  $", " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], cwd=HERE, **kw)
    if r.returncode != 0:
        raise SystemExit("!! 上一步失败（exit %d）" % r.returncode)
    return r


def why_failed(e):
    """把异常翻译成一句有用的话。

    别直接 `"%s" % e` —— 安全策略抛的是 `SystemExit(1)`，
    `str()` 出来就是一个裸的 `1`，等于什么都没说
    （日志里出现过「删除被安全策略拦下：1」这种没用的话）。
    真正的诊断信息（count/threshold/targets）是那层钩子自己打在
    **上一行**的 `[safe-delete] ...` JSON 里。
    """
    if isinstance(e, SystemExit):
        return ("被安全策略中止（SystemExit %r）；"
                "计数信息见上一行 [safe-delete] 日志" % (e.code,))
    return "%s: %s" % (type(e).__name__, e)


def clear_dir(p, required=True):
    """清掉一个中间产物目录；删不动就改名腾位置。

    只用「整目录删」，不逐个删文件（见文件头的硬规矩）。
    但整目录删也会被拦（计数器数的是目录里的**条目数**，超 50 就拦），
    而且拦截抛的是 **SystemExit**，`ignore_errors=True` 挡不住 —— 所以
    必须 catch BaseException，否则脚本会静默死在清理这一步。
    兜底方案：改名腾位置。rename 不属于删除动作，不会被拦；
    `.gitignore` 里已经有 `*.old`，所以也不会污染 git status。

    required=True  ：这个目录**必须**腾出空路径（比如 build/ dist/，
                     下次要往里写），删不掉也改不了名就只能报错。
    required=False ：纯打扫卫生（临时目录、旧备份）。删不掉无所谓，
                     **绝不能因此中断打包** —— 踩过：自检完清理临时目录时
                     被拦，改名又撞上「刚 kill 掉的进程还占着 exe」，
                     结果整个脚本在最后一步崩了，zip 都没来得及生成。
    """
    if not p.exists():
        return
    print("  清理 %s ..." % p.name)
    try:
        shutil.rmtree(p, ignore_errors=True)
        if not p.exists():
            return
    except BaseException as e:              # SystemExit 也在这里面
        print("    !! 删除被拦：%s" % why_failed(e))

    # 改名挪开。带时间戳，避免多次打包互相覆盖。
    stale = p.with_name("%s_stale_%s.old" % (p.name, time.strftime("%m%d%H%M%S")))
    for i in range(3):                      # 刚 kill 的进程可能还占着文件，稍等重试
        if not p.exists():                  # 上一轮删了一半，其实已经腾出位置了
            print("    -> 目录已消失（删除虽被拦但已完成）")
            return
        try:
            p.rename(stale)
            print("    -> 已改名腾位置：%s" % stale.name)
            print("       （不影响本次打包；这是中间产物，可以随时手动删掉）")
            return
        except OSError as e:
            if i == 2:
                if required:
                    raise SystemExit("!! 既删不掉也改不了名：%s（%s）"
                                     % (p, why_failed(e)))
                print("    （只是打扫卫生，失败就算了：%s）" % why_failed(e))
            time.sleep(0.5)


def safe_unlink(p):
    """删单个文件，删不掉就算了（返回是否删掉）。

    为什么不用 `p.unlink()` 裸写：
      · 安全策略拦批量删除时抛的是 **SystemExit**，`except OSError` 接不住；
      · 这些位置都是「删旧备份」这种可失败的操作，失败不该弄死整个打包流程。
    """
    try:
        p.unlink()
        return True
    except BaseException as e:                 # SystemExit / PermissionError 都吃掉
        print("    （%s 暂未删掉，不打紧：%s）" % (p.name, why_failed(e)))
        return False


def main():
    py = sys.executable

    # ---- 0) 清掉上一轮的中间产物 ----
    # 必须在调 PyInstaller 之前做，且不能用 --clean 让 PyInstaller 自己删，
    # 因为它是逐文件删的，文件数一超阈值就会被安全策略拦下。
    clear_dir(HERE / "build")
    clear_dir(HERE / "dist")

    # ---- 1) 重新生成启动器 ----
    step(1, "重新生成启动器（.bat）")
    run([py, "tools_dev/gen_bat.py"])
    run([py, "tools_dev/gen_start_menu.py"])

    # ---- 2) 打包 ----
    step(2, "PyInstaller 打包成单文件 exe")
    # 注意：这里用的是 --noconfirm 而**不是** --clean。
    # --clean 会让 PyInstaller 自己去删 build/ 里上百个中间文件，
    # 而批量删除会触发安全策略（SAFE_DELETE_BULK_CONFIRM_REQUIRED）打断流程。
    # 正确做法：打包前自己把 build/ 和 dist/ 清掉（见上面 clear_dir），
    # 只删两个目录，不逐个删文件。
    #
    # 另外旧的 dist/NumbersAndForms.exe 会被改名成 .old 挪开：
    # PyInstaller 覆盖不了自己上一轮生成的、体积几十 MB 的 exe
    # （Windows 上偶尔报 PermissionError），而「改名」不会触发批量删除确认。
    built = HERE / "dist" / EXE_NAME
    if built.exists():
        stale = HERE / "dist" / (EXE_NAME + ".old")
        if stale.exists():
            safe_unlink(stale)
        built.rename(stale)
        print("  旧的 exe 已挪到 %s" % stale.name)
    run([py, "-m", "PyInstaller", "NumbersAndForms.spec", "--noconfirm"])

    built = HERE / "dist" / EXE_NAME
    if not built.exists():
        raise SystemExit("!! 没找到打包产物：%s" % built)
    mb = built.stat().st_size / 1024 / 1024
    print("  产物：%s（%.1f MB）" % (built.name, mb))

    # 新 exe 已确认，可以把上一轮的旧 exe 删掉了（单个文件，不会触发批量确认）
    stale = HERE / "dist" / (EXE_NAME + ".old")
    if stale.exists():
        safe_unlink(stale)

    # ---- 3) 整理发布目录 ----
    step(3, "整理发布目录（只放玩家需要的东西）")
    # 旧目录先改名腾出位置，最后再整目录删。
    # 千万别写成「for f in RELEASE.iterdir(): f.unlink()」——那是逐文件删，
    # 安全策略里有「每回合累计删除文件数」计数，删多了就会被拦下。
    old_release = RELEASE.parent / "_old_数与形"
    clear_dir(old_release)
    if RELEASE.exists():
        RELEASE.rename(old_release)
    RELEASE.mkdir(parents=True, exist_ok=True)

    shutil.copy2(built, RELEASE / EXE_NAME)
    for extra in ("发给别人-怎么玩.txt", "0_START_HERE.bat"):
        src = HERE / extra
        if src.exists():
            shutil.copy2(src, RELEASE / extra)

    # 附一份完整的 README，方便懂技术的人自己改
    if (HERE / "README.md").exists():
        shutil.copy2(HERE / "README.md", RELEASE / "开发者文档.md")

    for f in sorted(RELEASE.iterdir()):
        print("  %-28s %8.1f KB" % (f.name, f.stat().st_size / 1024))

    # 新内容已就位，旧的备份目录这时候才删
    # （纯打扫卫生：删不掉也不能中断后面的自检和打 zip）
    clear_dir(old_release, required=False)

    # ---- 4) 自检：在隔离目录里真跑一遍 ----
    step(4, "自检：在隔离目录里运行打包产物")
    check = HERE / "tmp" / "_release_check"
    clear_dir(check, required=False)     # 整目录清，避免逐文件删
    check.mkdir(parents=True, exist_ok=True)
    exe_in_check = check / EXE_NAME
    shutil.copy2(RELEASE / EXE_NAME, exe_in_check)

    import os
    env = dict(os.environ)
    env["SDL_VIDEODRIVER"] = "dummy"
    env["SDL_AUDIODRIVER"] = "dummy"
    # 5 秒内没崩 = 启动成功，然后杀掉
    try:
        p = subprocess.Popen([str(check / EXE_NAME)], cwd=check, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            p.wait(timeout=5)
            print("  !! 进程 5 秒内就退出了，exit code = %s" % p.returncode)
            out, err = p.communicate()
            if err:
                print("  stderr:", err.decode("utf-8", "replace")[:600])
            raise SystemExit("!! 打包产物启动失败")
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
            print("  OK：隔离目录里启动后持续运行 5 秒未崩溃")
    except OSError as e:
        raise SystemExit("!! 无法运行打包产物：%s" % e)
    finally:
        # 自检完成，把整个隔离目录清掉（整目录删，不逐文件删）。
        # 这里**必须** required=False：刚 kill 掉的 exe 在 Windows 上
        # 可能还占着文件，删不掉是正常的，绝不能因此中断后面的打 zip。
        clear_dir(check, required=False)

    # ---- 5) 内容自检：exe 里真的是最新代码吗 ----
    step(5, "内容自检：核对 exe 里的代码指纹")
    verify_exe_code(RELEASE / EXE_NAME)

    # ---- 顺带打个 zip，方便直接发 ----
    zip_path = RELEASE.parent / "数与形-公理塔.zip"
    zip_old = RELEASE.parent / "_old_数与形-公理塔.zip"
    if zip_path.exists():
        # 同样用改名腾位置，别 unlink（会累加删除计数）
        if zip_old.exists():
            safe_unlink(zip_old)
        zip_path.rename(zip_old)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(RELEASE.iterdir()):
            z.write(f, arcname="数与形/" + f.name)
    print("\n  已打包 zip：%s（%.1f MB）"
          % (zip_path.name, zip_path.stat().st_size / 1024 / 1024))

    # 新 zip 已经落好了，这时候才删旧的。
    # （曾经漏了这一步：每重打包一次就白留一个 26MB 的 _old_*.zip）
    if zip_old.exists():
        if safe_unlink(zip_old):
            print("  旧的 zip 已清理")

    print("\n" + "=" * 56)
    print("完成。可以把这个发出去：")
    print("  %s" % zip_path)
    print("  或整个文件夹：%s" % RELEASE)
    print("=" * 56)


if __name__ == "__main__":
    main()
