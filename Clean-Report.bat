@echo off
setlocal EnableExtensions
title StorageCleaner v9.1 [REPORT MODE]
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

echo ============================================================
echo  StorageCleaner v9.1 - Report Mode (scan only)
echo ============================================================
echo   Python : %PYEXE%
echo   Nothing is deleted in this mode.
echo ============================================================
echo.

"%PYEXE%" "%~dp0StorageCleaner.py" --deep --report
set "RC=%ERRORLEVEL%"

echo.
echo ============================================================
echo  Report complete - nothing deleted (exit code %RC%)
echo  To clean for real, run Clean-Deep.bat as Administrator.
echo ============================================================
goto :done

:nopython
echo.
echo  ERROR: Python was not found.
echo  Install Python 3 with "Add python.exe to PATH" enabled.
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
