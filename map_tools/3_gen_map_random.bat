@echo off
cd /d "%~dp0"
echo ========================================
echo   Numbers and Forms - Random Map
echo ========================================
echo.
echo   Generating a brand new random map...
echo.
"C:\Users\sanji\.workbuddy\binaries\python\envs\naf\Scripts\python.exe" tools\build_map.py --random
echo.
"C:\Users\sanji\.workbuddy\binaries\python\envs\naf\Scripts\python.exe" tools\render_map.py
echo.
echo Done. Opening preview page...
start "" "out\map.html"
pause >nul
