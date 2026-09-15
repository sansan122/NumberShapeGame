@echo off
cd /d "%~dp0"
echo ========================================
echo   Numbers and Forms  -  Quick Start
echo ========================================
echo.
echo   [1] Card battle prototype   (main demo)
echo   [2] My first window         (my_test.py)
echo   [3] Generate tower map preview
echo   [0] Quit
echo.
set /p CHOICE=Type 1, 2, 3 or 0 then press ENTER: 
if "%CHOICE%"=="1" goto CARD
if "%CHOICE%"=="2" goto MYTEST
if "%CHOICE%"=="3" goto MAP
if "%CHOICE%"=="0" goto END
echo Invalid choice.
pause >nul
goto END
:CARD
call "1_run_card.bat"
goto END
:MYTEST
call "1_run_my_test.bat"
goto END
:MAP
call "map_tools\2_gen_map.bat"
goto END
:END
