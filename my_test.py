import pygame
import sys

# 1. 初始化
pygame.init()
screen = pygame.display.set_mode((800, 600))
pygame.display.set_caption("我的第一个游戏窗口")

# 2. 游戏主循环
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:  # 点击右上角X关闭
            running = False

    # 3. 填充背景颜色 (R, G, B) 这里是浅蓝色
    screen.fill((173, 216, 230))
    
    # 4. 画一个红色方块 (x, y, 宽, 高)
    pygame.draw.rect(screen, (255, 0, 0), (300, 200, 200, 200))
    
    # 5. 刷新屏幕
    pygame.display.flip()

# 6. 退出
pygame.quit()
sys.exit()