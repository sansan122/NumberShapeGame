@echo off
cd /d "%~dp0"
echo ========================================
echo    Numbers and Forms  -  Quick Start
echo ========================================
echo.
if exist "%~dp0NumbersAndForms.exe" goto HAVE_EXE
echo   [1] Tower map          (main game)
echo   [2] Card battle        (fight demo)
echo   [3] Regenerate map     (fixed seed, same map)
echo   [4] Random map         (new map every time)
echo   [5] My first window    (my_test.py)
echo   [0] Quit
echo.
set /p CHOICE=Type a number then press ENTER: 
if "%CHOICE%"=="1" goto MAPGAME
if "%CHOICE%"=="2" goto CARD
if "%CHOICE%"=="3" goto GENMAP
if "%CHOICE%"=="4" goto RANDMAP
if "%CHOICE%"=="5" goto MYTEST
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
:RANDMAP
call "map_tools\3_gen_map_random.bat"
goto END
:MYTEST
call "4_run_my_test.bat"
goto END

:HAVE_EXE
echo   Found NumbersAndForms.exe - starting the game.
echo   (This file is standalone; nothing needs to be installed.)
echo.
start "" "%~dp0NumbersAndForms.exe"
goto END

:END
