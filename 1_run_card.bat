@echo off
cd /d "%~dp0"
echo ========================================
echo   Numbers and Forms - Card Battle
echo ========================================
echo.
echo   Left click a card, then an empty area to play it.
echo   A math quiz pops up - answer it correctly for the effect.
echo   Type digits, ENTER to confirm, BACKSPACE to fix.
echo   Close the window to quit.
echo.
echo   [NOTICE] Answer WRONG and the card is wasted to discard.
echo.
"C:\Users\sanji\.workbuddy\binaries\python\envs\naf\Scripts\python.exe" "test_card.py"
echo.
echo Program exited. Press any key to close...
pause >nul
