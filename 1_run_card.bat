@echo off
cd /d "%~dp0"
echo ========================================
echo   Card Battle Prototype
echo ========================================
echo.
echo   Click a card, then click empty space to play it.
echo   Solve the math problem that pops up to make it work.
echo   On the underline: type digits, ENTER to submit, BACKSPACE to fix.
echo   Close the window to quit.
echo.
echo   [NOTICE] A wrong answer wastes the card.
echo.
"C:\Users\sanji\.workbuddy\binaries\python\envs\naf\Scripts\python.exe" "test_card.py"
echo.
pause >nul
