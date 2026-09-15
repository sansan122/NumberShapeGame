# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置 —— 打成**单文件、免安装**的 NumbersAndForms.exe。

用法（在项目根目录）：
    <python> -m PyInstaller NumbersAndForms.spec --noconfirm

产物：
    dist/NumbersAndForms.exe     约 30~45 MB，双击即玩

几个关键决定，都有原因：

  · console=False
      游戏不需要黑框。但注意：关掉控制台后 print 的输出就看不见了，
      所以出问题时排查会变难 —— 见下面的「调试版」说明。

  · onefile（EXE(...) 里不写 COLLECT）
      好处是只有**一个文件**，对方不用解压、不会漏文件。
      代价是每次启动都要把内容解压到临时目录（首次启动慢 1~2 秒）。
      对「只会双击的人」来说，一个文件比启动快更重要。

  · 打包 tower.yaml 和字体
      tower.yaml 是地图配置，必须进包（build_map 会读它）。
      字体也一起打进去：别人电脑上就算没有微软雅黑也能正常显示中文。

调试版打包（出问题想看到报错）：
    把下面 console=False 改成 console=True，重新打包，
    运行时会弹一个黑框，Python 的报错会显示在那里。
"""

from pathlib import Path

ROOT = Path(SPECPATH)          # PyInstaller 会注入 SPECPATH = spec 所在目录

# ---------------------------------------------------------------------------
# 要一起打包的数据文件
# ---------------------------------------------------------------------------
datas = [
    # 地图配置（build_map.py 会读）
    (str(ROOT / "map_tools" / "data" / "tower.yaml"), "map_tools/data"),
]

# 字体：挑一个存在的就打进去（用户机器上有没有都无所谓，有兜底链）
for font in ("msyh.ttc", "msyh.ttf", "simhei.ttf", "simsun.ttc"):
    p = Path("C:/Windows/Fonts") / font
    if p.is_file():
        datas.append((str(p), "fonts"))
        break

# 开发/测试脚本不需要进包，明确排除掉能显著减小体积
excludes = [
    "tkinter", "unittest", "pydoc", "doctest", "test",
    "numpy", "PIL", "matplotlib", "scipy", "pandas",
    "setuptools", "pip", "email", "http", "xml", "pdb",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT), str(ROOT / "map_tools" / "tools")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # 这几个是运行时动态 import 的，静态分析扫不到，必须显式列出来
        "build_map",
        "map_scene",
        "node_scenes",
        "battle_scene",
        "player",
        "save_system",
        "ui_scenes",
        "game_env",
        "yaml",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NumbersAndForms",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX 容易触发杀软误报，关掉
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,             # ← 改成 True 就是「能看到报错的调试版」
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                 # 图标由代码 set_icon 绘制，见 main.make_window_icon()
)
