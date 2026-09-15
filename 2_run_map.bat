@echo off
cd /d "%~dp0"
echo ========================================
echo   Numbers and Forms - Map Only
echo ========================================
echo.
set "PYEXE="
rem --- 1) project-local virtualenv ---
if exist "%~dp0.venv\Scripts\python.exe" set "PYEXE=%~dp0.venv\Scripts\python.exe"
if defined PYEXE goto RUN

rem --- 2) python on PATH ---
for %%I in (python.exe) do if not defined PYEXE if exist "%%~$PATH:I" set "PYEXE=%%~$PATH:I"
if defined PYEXE goto RUN

rem --- 3) the py launcher ---
where py >nul 2>nul
if %errorlevel%==0 set "PYEXE=py"
if defined PYEXE goto RUN

rem --- 4) common install locations ---
for %%D in (
  "%LOCALAPPDATA%\Programs\Python"
  "%ProgramFiles%"
  "C:\Python313"
  "C:\Python312"
  "C:\Python311"
) do if not defined PYEXE (
  for /d %%P in ("%%~D\Python3*") do (
    if exist "%%~P\python.exe" set "PYEXE=%%~P\python.exe"
  )
  if exist "%%~D\python.exe" set "PYEXE=%%~D\python.exe"
)
if defined PYEXE goto RUN

echo.
echo [ERROR] Python was not found on this computer.
echo.
echo   This launcher needs Python 3.8 or newer, with pygame installed.
echo   Option A: install Python from https://www.python.org/downloads/
echo             (check "Add python.exe to PATH" during setup)
echo   Option B: use the packaged "NumbersAndForms.exe" instead -
echo             it is standalone and needs nothing installed.
echo.
pause
exit /b 1

:RUN
echo   Just the tower map, no battles.
echo.
"%PYEXE%" "map_scene.py"
echo.
pause >nul
