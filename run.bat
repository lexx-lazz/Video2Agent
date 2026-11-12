@echo off
REM ============================================================================
REM  Video2Agent launcher, the ONE way to start this project.
REM  Do not add start.bat / dev.bat / build.bat. New capabilities go here as
REM  subcommands.
REM
REM  Usage:  run.bat                     -> interactive menu with a file picker
REM          run.bat <video> [options]   -> process one video directly
REM          run.bat <videos or folder>  -> process several, one after another
REM          run.bat --queue --at 23:30  -> run the saved queue at a set time
REM          run.bat test                -> run the test suite (offline)
REM          run.bat safety              -> secret / .env hygiene audit
REM          run.bat deps                -> reinstall the Python packages
REM
REM  Nothing needs installing first. The first run downloads uv (a small tool from
REM  astral.sh), and uv downloads its own copy of Python. Both live in .runtime\
REM  inside this folder, so the PC's own Python, if it has one, never matters.
REM  FFmpeg comes with the Python packages. Delete this folder and it's all gone.
REM
REM  THIS FILE MUST KEEP CRLF LINE ENDINGS. cmd.exe mis-parses LF-only batch
REM  files: comments and parenthesised blocks merge, producing errors like
REM  "'M' is not recognized as an internal or external command". .gitattributes
REM  enforces it; any tool that rewrites this file must convert afterwards.
REM ============================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM The Python version every install uses, and the uv release that fetches it.
REM UV_SHA256 is the official checksum of that release, so a damaged or swapped
REM download is refused instead of run.
set "PYTHON_VERSION=3.12"
set "UV_VERSION=0.13.5"
set "UV_SHA256=a38b8d1902b7cfbc76b423ba1bb456f623f42064cdc72628b6075b89afd1019a"

set "RUNTIME=%~dp0.runtime"
set "UV=%RUNTIME%\uv\uv.exe"
set "UV_PYTHON_INSTALL_DIR=%RUNTIME%\python"
set "UV_CACHE_DIR=%RUNTIME%\cache"
REM The Whisper speech model, downloaded on the first video, goes here too
if not defined HF_HOME set "HF_HOME=%RUNTIME%\models"
set "PY=.venv\Scripts\python.exe"

REM --- UTF-8 console so non-ASCII output renders correctly --------------------
chcp 65001 >nul 2>nul
set "PYTHONIOENCODING=utf-8"

REM --- Load .env into THIS shell, safely --------------------------------------
REM Only ever calls the `set` builtin on parsed KEY/VALUE pairs, so a stray line
REM in .env can never be executed as a command. Comment lines are skipped via
REM eol=#; blank lines are skipped by for /f. An already-exported variable is
REM never overwritten, so an explicitly-set key always wins.
if exist ".env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%K in (".env") do (
        if not "%%K"=="" if not defined %%K set "%%K=%%L"
    )
)

REM --- Get uv, on the first run only -----------------------------------------
if not exist "%UV%" (
    call :download_uv
    if errorlevel 1 goto :end_fail
)

REM --- Check the project's Python environment, and rebuild it if it's wrong ---
REM A .venv made by an older version of this launcher, with another Python, or
REM left broken when a folder was moved, gets thrown away and made again.
if exist "%PY%" (
    "%PY%" -c "import sys; sys.exit(not sys.version.startswith('%PYTHON_VERSION%.'))" >nul 2>nul
    if errorlevel 1 (
        echo [setup] The .venv folder is from a different setup. Making a fresh one...
        rmdir /s /q .venv
    )
)

if not exist "%PY%" (
    echo [setup] First run: getting Python %PYTHON_VERSION% for this project. This takes a minute or two...
    "%UV%" venv --quiet --managed-python --python %PYTHON_VERSION% .venv
    if errorlevel 1 (
        echo [ERROR] Could not set up Python. Check the internet connection and run again.
        goto :end_fail
    )
)

REM --- Install the packages when they're missing or the list has changed ------
REM A copy of requirements.txt is kept in .venv after every install that worked.
REM If it's missing, the last install never finished, so it runs again.
set "NEED_INSTALL="
if /i "%~1"=="deps" set "NEED_INSTALL=1"
if not exist ".venv\installed-requirements.txt" set "NEED_INSTALL=1"
if not defined NEED_INSTALL (
    fc /b requirements.txt ".venv\installed-requirements.txt" >nul 2>nul
    if errorlevel 1 set "NEED_INSTALL=1"
)
if defined NEED_INSTALL (
    echo [setup] Installing the Python packages. The first time this downloads about 300 MB...
    "%UV%" pip install --quiet --python "%PY%" -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] The packages did not install. Check the internet connection and run again.
        goto :end_fail
    )
    copy /y requirements.txt ".venv\installed-requirements.txt" >nul
    REM The downloaded package files aren't needed once installed, so free the space
    "%UV%" cache clean --quiet >nul 2>nul
    echo [setup] Ready.
)

if /i "%~1"=="deps" (
    echo Dependencies up to date.
    goto :end
)

for /f "delims=" %%V in ('%PY% -c "import sys;print(sys.version.split()[0])" 2^>nul') do set "PYVER=%%V"
echo [info] Using Python !PYVER! ^(!PY!^)

REM --- Make src/ importable without an install step ---------------------------
set "PYTHONPATH=%~dp0src"

REM --- Subcommands ------------------------------------------------------------
if /i "%~1"=="test" (
    REM The suite runs OFFLINE and deterministic: no live API call, no quota
    REM spent, no dependency on the network. Clear real credentials here so a
    REM populated .env can never leak into a test run.
    set "VIDEO2AGENT_ENV=test"
    "%PY%" -c "import pytest" >nul 2>nul || "%UV%" pip install --quiet --python "%PY%" pytest
    "%PY%" -m pytest -q
    if errorlevel 1 goto :end_fail
    goto :end
)

if /i "%~1"=="safety" (
    REM Run this BEFORE putting any real credential in .env.
    "%PY%" tools\safety_check.py
    if errorlevel 1 goto :end_fail
    goto :end
)

REM --- Default: run the app ---------------------------------------------------
"%PY%" -m video2agent %*
if errorlevel 1 goto :end_fail
goto :end


:download_uv
REM curl and tar come with Windows 10 (1803 and later) and Windows 11.
echo [setup] First run: downloading uv %UV_VERSION%, about 15 MB...
if not exist "%RUNTIME%\uv" mkdir "%RUNTIME%\uv"
set "UV_ZIP=%RUNTIME%\uv.zip"
curl -fsSL -o "%UV_ZIP%" "https://github.com/astral-sh/uv/releases/download/%UV_VERSION%/uv-x86_64-pc-windows-msvc.zip"
if errorlevel 1 (
    echo [ERROR] Could not download uv. Check the internet connection and run again.
    exit /b 1
)

REM Refuse the file unless it's exactly the release we expect
set "GOT_SHA256="
for /f "delims=" %%H in ('certutil -hashfile "%UV_ZIP%" SHA256 ^| findstr /v ":"') do set "GOT_SHA256=%%H"
set "GOT_SHA256=!GOT_SHA256: =!"
if /i not "!GOT_SHA256!"=="%UV_SHA256%" (
    echo [ERROR] The uv download did not match its checksum, so it was not used.
    del "%UV_ZIP%" >nul 2>nul
    exit /b 1
)

tar -xf "%UV_ZIP%" -C "%RUNTIME%\uv"
del "%UV_ZIP%" >nul 2>nul
if not exist "%UV%" (
    echo [ERROR] Could not unpack uv.
    exit /b 1
)
exit /b 0


:end_fail
REM Non-zero exit so a scheduler or CI can actually detect a failed run.
echo.
if "%~1"=="" pause
endlocal
exit /b 1

:end
echo.
REM Only pause for the bare, double-clicked invocation, where the window would
REM otherwise vanish instantly. Every subcommand is typed into an existing
REM terminal or run by a scheduler. Pausing there would hang an unattended task
REM forever waiting for a keypress that never comes.
if "%~1"=="" pause
endlocal
