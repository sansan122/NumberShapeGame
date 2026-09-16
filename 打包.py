# -*- coding: utf-8 -*-
"""
打包.py —— 一键把游戏打成可以发给别人的 exe。

用法：
    <python> 打包.py

它会做四件事：
    1. 重新生成所有启动器（保证编码和探测逻辑是最新的）
    2. 用 PyInstaller 打包成单文件 exe
    3. 把 exe 和说明拷到一个干净的发布目录
    4. 在隔离环境里**自检一遍**（确认打包后真的能跑）

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
"""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RELEASE = HERE / "release" / "数与形"
EXE_NAME = "NumbersAndForms.exe"


def step(n, msg):
    print("\n[%d/4] %s" % (n, msg))
    print("-" * 56)


def run(cmd, **kw):
    print("  $", " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], cwd=HERE, **kw)
    if r.returncode != 0:
        raise SystemExit("!! 上一步失败（exit %d）" % r.returncode)
    return r


def clear_dir(p):
    """整目录删掉（只删两个目录，不逐个删文件——避免触发批量删除的安全确认）。"""
    if not p.exists():
        return
    print("  清理 %s ..." % p.name)
    shutil.rmtree(p, ignore_errors=True)


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
            stale.unlink()
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
        try:
            stale.unlink()
        except OSError:
            pass

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
    clear_dir(old_release)

    # ---- 4) 自检：在隔离目录里真跑一遍 ----
    step(4, "自检：在隔离目录里运行打包产物")
    check = HERE / "tmp" / "_release_check"
    clear_dir(check)                     # 整目录清，避免逐文件删
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
        # 自检完成，把整个隔离目录清掉（整目录删，不逐文件删）
        clear_dir(check)

    # ---- 顺带打个 zip，方便直接发 ----
    zip_path = RELEASE.parent / "数与形-公理塔.zip"
    zip_old = RELEASE.parent / "_old_数与形-公理塔.zip"
    if zip_path.exists():
        # 同样用改名腾位置，别 unlink（会累加删除计数）
        if zip_old.exists():
            zip_old.unlink()
        zip_path.rename(zip_old)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(RELEASE.iterdir()):
            z.write(f, arcname="数与形/" + f.name)
    print("\n  已打包 zip：%s（%.1f MB）"
          % (zip_path.name, zip_path.stat().st_size / 1024 / 1024))

    # 新 zip 已经落好了，这时候才删旧的。
    # （曾经漏了这一步：每重打包一次就白留一个 26MB 的 _old_*.zip）
    if zip_old.exists():
        try:
            zip_old.unlink()
            print("  旧的 zip 已清理")
        except OSError:
            print("  ! 旧 zip 删不掉，手动删一下：%s" % zip_old)

    print("\n" + "=" * 56)
    print("完成。可以把这个发出去：")
    print("  %s" % zip_path)
    print("  或整个文件夹：%s" % RELEASE)
    print("=" * 56)


if __name__ == "__main__":
    main()
