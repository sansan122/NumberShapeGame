@echo off
cd /d "%~dp0"
echo ========================================
echo   Numbers and Forms  -  Quick Start
echo ========================================
echo.
echo   [1] Tower map          (main game)
echo   [2] Card battle        (fight demo)
echo   [3] Regenerate map     (rebuild + preview)
echo   [4] My first window    (my_test.py)
echo   [0] Quit
echo.
set /p CHOICE=Type a number then press ENTER: 
if "%CHOICE%"=="1" goto MAPGAME
if "%CHOICE%"=="2" goto CARD
if "%CHOICE%"=="3" goto GENMAP
if "%CHOICE%"=="4" goto MYTEST
if "%CHOICE%"=="0" goto END
echo Invalid choice.
pause >nul
goto END
:MAPGAME
call "3_run_game.bat"
goto END
:CARD
call "1_run_card.bat"
goto END
:GENMAP
call "map_tools\2_gen_map.bat"
goto END
:MYTEST
call "4_run_my_test.bat"
goto END
:END
