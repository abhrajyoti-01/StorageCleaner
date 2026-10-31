@echo off
setlocal EnableExtensions
title StorageCleaner v9.1 [AGGRESSIVE MODE]
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
if errorlevel 1 goto :needadmin

echo ============================================================
echo  StorageCleaner v9.1 - AGGRESSIVE Mode
echo ============================================================
echo   Brain  : v9 (AI-trained, safety-vetoed, live scoring)
echo   Python : %PYEXE%
echo ============================================================
echo.
echo  This cleans everything DEEP does, PLUS things that need
echo  reinstalling afterwards:
echo    - VS Code extension data
echo    - Python user site-packages
echo    - npm global packages
echo    - Android AVD caches, installer Package Cache
echo.
echo  After it finishes you may need to:
echo    1. Reload VS Code so extensions restore
echo    2. pip install your Python packages again
echo    3. npm install -g your global CLIs again
echo.
echo  Press Ctrl+C now to cancel, or
pause

"%PYEXE%" "%~dp0StorageCleaner.py" --aggressive
set "RC=%ERRORLEVEL%"

echo.
echo ============================================================
echo  Finished (exit code %RC%)
echo ============================================================
goto :done

:needadmin
echo.
echo  AGGRESSIVE mode needs Administrator rights.
echo  Right-click this file and pick "Run as administrator".
echo.
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
