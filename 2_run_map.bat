@echo off
cd /d "%~dp0"
echo ========================================
echo   Tower Map  (standalone)
echo ========================================
echo.
echo   Start at the bottom, climb up.
echo   Highlighted nodes = reachable. Click one to move.
echo   Click a far node to preview the path instead.
echo   Mouse wheel or UP/DOWN to scroll. ESC to quit.
echo.
"C:\Users\sanji\.workbuddy\binaries\python\envs\naf\Scripts\python.exe" "map_scene.py"
echo.
pause >nul
