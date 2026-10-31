@echo off
setlocal EnableExtensions
title StorageCleaner v9.1 [DEEP MODE]
cd /d "%~dp0"

set "PYEXE="
for %%P in (python.exe) do if not defined PYEXE set "PYEXE=%%~$PATH:P"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PYEXE if exist "C:\Program Files\Python313\python.exe" set "PYEXE=C:\Program Files\Python313\python.exe"
if not defined PYEXE if exist "C:\Program Files\Python312\python.exe" set "PYEXE=C:\Program Files\Python312\python.exe"
if not defined PYEXE if exist "C:\Program Files\Python311\python.exe" set "PYEXE=C:\Program Files\Python311\python.exe"
if not defined PYEXE for %%P in (py.exe) do if not defined PYEXE set "PYEXE=%%~$PATH:P"

if not defined PYEXE goto :nopython
if not exist "%~dp0StorageCleaner.py" goto :noscript

net session >nul 2>&1
if errorlevel 1 set "ADMIN=no"
if not defined ADMIN set "ADMIN=yes"

echo ============================================================
echo  StorageCleaner v9.1 - DEEP Mode
echo ============================================================
echo   Brain     : v9 (retrained, safety-vetoed)
echo   Python    : %PYEXE%
echo   Elevated  : %ADMIN%
echo ============================================================
echo.
echo  Cleans: editor/browser caches, dev package caches,
echo          system caches, temp, crash dumps, old sessions,
echo          OLD WINDOWS FILES (Windows.old, setup leftovers,
echo          Windows update logs older than 30 days).
echo  Keeps : Downloads, Documents, Pictures, Videos, Desktop,
echo          OneDrive, .ssh, .aws, AI tool sessions.
echo.
echo  Slow boot on battery? Run Clean-Performance.bat -
echo  that is power throttling, not junk (the report explains).
echo.
if "%ADMIN%"=="no" echo  NOTE: not elevated - Windows.old, memory dump and other
if "%ADMIN%"=="no" echo        system targets are listed but SKIPPED. Right-click
if "%ADMIN%"=="no" echo        this file, "Run as administrator", to clean them.
if "%ADMIN%"=="no" echo.

"%PYEXE%" "%~dp0StorageCleaner.py" --deep
set "RC=%ERRORLEVEL%"

echo.
echo ============================================================
echo  Finished (exit code %RC%)
echo ============================================================
goto :done

:nopython
echo.
echo  ERROR: Python was not found.
echo  Install Python 3 and tick "Add python.exe to PATH",
echo  or edit this file and set PYEXE to your python.exe path.
echo.
goto :done

:noscript
echo.
echo  ERROR: StorageCleaner.py not found next to this launcher.
echo  Expected: %~dp0StorageCleaner.py
echo.
goto :done

:done
echo.
pause
endlocal
