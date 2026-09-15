@echo off
cd /d "%~dp0"
echo ========================================
echo   Numbers and Forms - Main
echo ========================================
echo.
echo   Tower map. Climb from the bottom to the boss.
echo   Mouse wheel / UP / DOWN : scroll view
echo   Click a highlighted node : move there
echo   Click a far node         : preview path
echo   R : restart floor        ESC : quit
echo.
"C:\Users\sanji\.workbuddy\binaries\python\envs\naf\Scripts\python.exe" "main.py"
echo.
pause >nul
