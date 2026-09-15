"""
《数与形》主程序
================================================
目前含两个场景：
  1. 地图场景（map_scene.MapScene）—— 爬塔选路线
  2. 战斗场景（test_card.py）—— 待接入

现在按 M 键可以在地图 / 战斗之间切换，方便分别看效果。
后续会把两者接起来：在地图上点战斗节点 -> 进入战斗 -> 打完回地图。

运行：双击 3_run_game.bat
"""

import sys
from pathlib import Path

import pygame

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import map_scene as M          # noqa: E402

WIDTH, HEIGHT = 1280, 720


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("数与形 · 公理塔")
    clock = pygame.time.Clock()

    try:
        data = M.load_map()
    except FileNotFoundError as e:
        print(e)
        print("\n请先运行 2_gen_map.bat 生成地图。")
        input("按回车退出...")
        return

    scene = M.MapScene(data)
    scene.cam_y = scene.camera_for(scene.nodes[scene.current])
    scene.cam_target = scene.cam_y

    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        mouse = pygame.mouse.get_pos()
        t_ms = pygame.time.get_ticks()

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False

            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    running = False
                elif ev.key in (pygame.K_UP, pygame.K_w):
                    scene.scroll(70)
                elif ev.key in (pygame.K_DOWN, pygame.K_s):
                    scene.scroll(-70)
                elif ev.key == pygame.K_r:
                    # 重开本层
                    scene.load_floor(scene.floor_index)
                    scene.cam_y = scene.camera_for(scene.nodes[scene.current])
                    scene.cam_target = scene.cam_y

            elif ev.type == pygame.MOUSEWHEEL:
                scene.scroll(ev.y * 55)

            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                nd = scene.hovered_node(mouse)
                if nd is not None:
                    if scene.can_move_to(nd["id"]):
                        scene.move_to(nd["id"])
                    else:
                        p = scene.find_path(nd["id"])
                        if p:
                            scene.target = nd["id"]
                            scene.path_hint = p
                            scene.push_log("查看路径：%d 步" % len(p))
                        else:
                            scene.push_log("从当前位置无法到达")

        scene.update(dt)

        # ---- 提示条（临时，等战斗接入后删）----
        scene.draw(screen, mouse, t_ms)
        tip = scene.F_TINY.render(
            "R 重开本层　·　ESC 退出", True, M.TEXT_FAINT)
        screen.blit(tip, (M.WIDTH - tip.get_width() - 24, M.HEIGHT - 28))

        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
