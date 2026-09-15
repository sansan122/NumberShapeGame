# -*- coding: utf-8 -*-
"""
gen_bat.py —— 生成「换台电脑也能跑」的启动器。

为什么要有这个脚本？（而不是手写 .bat）
  1. .bat 必须存成 GBK 编码、内容纯 ASCII（否则 cmd.exe 报
     "Code language not supported or defined"，老坑见 README 避坑第 1 条）
  2. 原来 .bat 里写死了本机 Python 路径，别人电脑上必然报错
  3. 用 Python 生成能保证编码/换行/非 ASCII 检查都做对

生成策略：
  打包成 exe 之后根本用不到 .bat（双击 exe 即可）。
  但源码模式下（发给懂技术的人、或自己调试）需要 .bat 兜底，
  所以 .bat 里做「按顺序探测 Python」：
     1) 项目自带的 .venv\\Scripts\\python.exe（如果一起发过去了）
     2) 环境变量里能找到的 python
     3) py 启动器（windows 官方推荐的写法）
     4) 常见安装路径
  全都找不到 -> 给一句人能看懂的中文提示（用 GBK 写进 .bat 里的
  中文提示不行，所以这里只用 ASCII 提示 + 让 Python 脚本自己报错）
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent.parent      # 项目根

# ---------------------------------------------------------------------------
# 探测 Python 的公共片段。抽出来让 5 个 .bat 共用，避免改一处漏四处。
# ---------------------------------------------------------------------------
FIND_PY = r"""
set "PYEXE="
rem --- 1) project-local virtualenv ---
if exist "%~dp0.venv\Scripts\python.exe" set "PYEXE=%~dp0.venv\Scripts\python.exe"
if defined PYEXE goto RUN

rem --- 2) python on PATH ---
for %%I in (python.exe) do if not defined PYEXE if exist "%%~$PATH:I" set "PYEXE=%%~$PATH:I"
if defined PYEXE goto RUN

rem --- 3) the py launcher ---
where py >nul 2>nul
if %errorlevel%==0 set "PYEXE=py"
if defined PYEXE goto RUN

rem --- 4) common install locations ---
for %%D in (
  "%LOCALAPPDATA%\Programs\Python"
  "%ProgramFiles%"
  "C:\Python313"
  "C:\Python312"
  "C:\Python311"
) do if not defined PYEXE (
  for /d %%P in ("%%~D\Python3*") do (
    if exist "%%~P\python.exe" set "PYEXE=%%~P\python.exe"
  )
  if exist "%%~D\python.exe" set "PYEXE=%%~D\python.exe"
)
if defined PYEXE goto RUN

echo.
echo [ERROR] Python was not found on this computer.
echo.
echo   This launcher needs Python 3.8 or newer, with pygame installed.
echo   Option A: install Python from https://www.python.org/downloads/
echo             (check "Add python.exe to PATH" during setup)
echo   Option B: use the packaged "NumbersAndForms.exe" instead -
echo             it is standalone and needs nothing installed.
echo.
pause
exit /b 1

:RUN
"""


def launcher(body_lines, header_lines):
    """拼一个完整的 .bat：头 + 探测 Python + 跑到指定脚本 + 暂停。"""
    lines = [
        "@echo off",
        'cd /d "%~dp0"',
        "echo ========================================",
    ]
    lines += ["echo   " + h for h in header_lines]
    lines.append("echo ========================================")
    lines.append("echo.")
    lines += FIND_PY.strip("\n").split("\n")
    lines += body_lines
    lines.append("echo.")
    lines.append("pause >nul")
    return lines


def write_bat(path, lines):
    """写 GBK 编码 + CRLF 换行的 .bat。lines 必须全 ASCII。"""
    for ln in lines:
        try:
            ln.encode("ascii")
        except UnicodeEncodeError:
            raise SystemExit("!! .bat 里出现了非 ASCII 字符：%r" % ln)
    content = "\r\n".join(lines) + "\r\n"
    Path(path).write_bytes(content.encode("gbk"))
    return len(lines)


# ---------------------------------------------------------------------------
# 要生成的启动器
# ---------------------------------------------------------------------------
JOBS = [
    ("3_run_game.bat", ["Numbers and Forms - Main Game"], [
        "echo   Tower map. Climb from the bottom to the boss.",
        "echo   Mouse wheel / UP / DOWN : scroll view",
        "echo   Click a highlighted node : move there",
        "echo   Click a far node         : preview path",
        "echo   S save   L load   R restart floor   M menu   ESC quit",
        "echo.",
        '"%PYEXE%" "main.py"',
    ]),
    ("1_run_card.bat", ["Numbers and Forms - Card Battle"], [
        "echo   Solve a math question to play a card.",
        "echo.",
        '"%PYEXE%" "test_card.py"',
    ]),
    ("2_run_map.bat", ["Numbers and Forms - Map Only"], [
        "echo   Just the tower map, no battles.",
        "echo.",
        '"%PYEXE%" "map_scene.py"',
    ]),
    ("4_run_my_test.bat", ["My First Window"], [
        "echo   The very first red-square window.",
        "echo.",
        '"%PYEXE%" "my_test.py"',
    ]),
]


def main():
    made = []

    for name, header, body in JOBS:
        n = write_bat(HERE / name, launcher(body, header))
        made.append((name, n))

    # 地图工具那两个在 map_tools/ 下，工作目录要指过去
    for name, script, header in [
        ("map_tools/2_gen_map.bat", "build_map.py", "Regenerate Map (fixed seed)"),
        ("map_tools/3_gen_map_random.bat", "build_map.py --random",
         "Regenerate Map (random seed)"),
    ]:
        lines = [
            "@echo off",
            'cd /d "%~dp0"',
            "echo ========================================",
            "echo   " + header,
            "echo ========================================",
            "echo.",
        ]
        lines += FIND_PY.strip("\n").split("\n")
        lines += [
            'cd /d "%~dp0tools"',
            '"%PYEXE%" ' + script,
            "echo.",
            "pause >nul",
        ]
        n = write_bat(HERE / name, lines)
        made.append((name, n))

    for name, n in made:
        print("  %-32s %3d 行" % (name, n))
    print("\n共生成 %d 个启动器。" % len(made))


if __name__ == "__main__":
    main()
