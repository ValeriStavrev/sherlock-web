@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYEXE="

cls
echo.
echo ==============================================
echo        SHERLOCK WEB - WINDOWS STARTER
echo ==============================================
echo.

echo [1/5] Looking for Python...

REM Modern Python Install Manager / launcher: use any installed Python 3.x.
py -3 --version >nul 2>&1
if not errorlevel 1 set "PYEXE=py -3"

REM Fallback for a normal python.exe installation on PATH.
if not defined PYEXE (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYEXE=python"
)

if not defined PYEXE (
    echo.
    echo ERROR: No Python 3 installation was found.
    echo.
    echo Install Python 3.12 or newer from:
    echo https://www.python.org/downloads/windows/
    echo.
    echo Then run this file again.
    echo.
    pause
    exit /b 1
)

echo Using: %PYEXE%
%PYEXE% --version
if errorlevel 1 goto :error

echo.
echo [2/5] Creating virtual environment...
if not exist ".venv\Scripts\python.exe" (
    %PYEXE% -m venv .venv
    if errorlevel 1 goto :error
)

set "VENV_PY=%CD%\.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo ERROR: The virtual environment was not created.
    goto :error
)

echo.
echo [3/5] Upgrading pip...
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 goto :error

echo.
echo [4/5] Installing web app and Sherlock...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :error
"%VENV_PY%" -m pip install --upgrade sherlock-project
if errorlevel 1 goto :error

"%VENV_PY%" -c "import sherlock_project; print('Sherlock package: OK')"
if errorlevel 1 goto :error

if not exist ".env" (
    copy /Y ".env.example" ".env" >nul
    echo.
    echo Created .env from .env.example
)

echo.
echo [5/5] Starting web app...
echo.
echo Open this in your browser:
echo http://127.0.0.1:5000
echo.
echo Keep this window open while using the website.
echo Press CTRL+C to stop the server.
echo.
"%VENV_PY%" run_local.py
set "EXITCODE=%ERRORLEVEL%"

echo.
if not "%EXITCODE%"=="0" (
    echo The web app stopped with exit code %EXITCODE%.
    echo Read the error message above.
) else (
    echo The web app has stopped.
)
echo.
pause
exit /b %EXITCODE%

:error
echo.
echo ==============================================
echo ERROR: Setup failed.
echo ==============================================
echo.
echo Read the error shown above.
echo This window will stay open so you can copy it.
echo.
pause
exit /b 1
