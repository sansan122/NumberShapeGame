@echo off
cd /d "%~dp0"
echo ========================================
echo   Numbers and Forms - Generate Map
echo ========================================
echo.
"C:\Users\sanji\.workbuddy\binaries\python\envs\naf\Scripts\python.exe" tools\build_map.py
echo.
"C:\Users\sanji\.workbuddy\binaries\python\envs\naf\Scripts\python.exe" tools\render_map.py
echo.
echo Done. Opening preview page...
start "" "out\map.html"
pause >nul
