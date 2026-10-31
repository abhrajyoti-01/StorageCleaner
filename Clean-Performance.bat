@echo off
setlocal EnableExtensions
title StorageCleaner v9.1 [PERFORMANCE REPORT]
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
echo  StorageCleaner v9.1 - Performance Report
echo ============================================================
echo  Shows why the PC is slow, especially on battery:
echo  power scheme, battery CPU boost, fast startup,
echo  startup programs, disk space. Deletes nothing.
echo.
echo  To apply the battery fix afterwards, run:
echo    python StorageCleaner.py --fix-power
echo ============================================================
echo.

"%PYEXE%" "%~dp0StorageCleaner.py" --performance
set "RC=%ERRORLEVEL%"

echo.
echo ============================================================
echo  Finished (exit code %RC%)
echo  Fix battery slowdown:  python StorageCleaner.py --fix-power
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
