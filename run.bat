@echo off
REM ============================================================================
REM  Video2Agent launcher — the ONE way to start this project.
REM  Do not add start.bat / dev.bat / build.bat. New capabilities go here as
REM  subcommands.
REM
REM  Usage:  run.bat <video> [options] -> process a video
REM          run.bat test       -> run the test suite (offline, deterministic)
REM          run.bat safety     -> secret / .env hygiene audit
REM          run.bat deps       -> reinstall dependencies into .venv
REM
REM  THIS FILE MUST KEEP CRLF LINE ENDINGS. cmd.exe mis-parses LF-only batch
REM  files: comments and parenthesised blocks merge, producing errors like
REM  "'M' is not recognized as an internal or external command". .gitattributes
REM  enforces it; any tool that rewrites this file must convert afterwards.
REM ============================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

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

REM --- Resolve an interpreter, preferring Python 3.9 --------------------
set "BOOT_PY="
where py >nul 2>nul
if not errorlevel 1 (
    py -3.9 -c "pass" >nul 2>nul
    if not errorlevel 1 set "BOOT_PY=py -3.9"
)
if not defined BOOT_PY (
    where py >nul 2>nul && set "BOOT_PY=py -3"
)
if not defined BOOT_PY (
    where python >nul 2>nul && set "BOOT_PY=python"
)
if not defined BOOT_PY (
    echo [ERROR] No Python interpreter found on PATH. Install Python 3.9 and retry.
    echo         https://www.python.org/downloads/
    pause
    exit /b 1
)

REM --- Provision a project-local venv ----------------------------------------
REM Dependencies install once, when the venv is first created. Use `run.bat deps`
REM to refresh them after changing requirements.
set "FRESH_VENV="
if not exist ".venv\Scripts\python.exe" (
    echo [setup] Creating project venv with: %BOOT_PY%
    %BOOT_PY% -m venv .venv
    if errorlevel 1 (
        echo [WARN] Could not create .venv - continuing with %BOOT_PY% directly.
    ) else (
        set "FRESH_VENV=1"
    )
)

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=%BOOT_PY%"
)

for /f "delims=" %%V in ('%PY% -c "import sys;print(sys.version.split()[0])" 2^>nul') do set "PYVER=%%V"
echo [info] Using Python !PYVER! ^(!PY!^)

REM --- Make src/ importable without an install step ---------------------------
set "PYTHONPATH=%~dp0src"

if defined FRESH_VENV goto :install_deps
if /i "%~1"=="deps" goto :install_deps
goto :after_deps

:install_deps
echo [setup] Installing dependencies...
if exist "requirements.txt" (
    !PY! -m pip install --quiet --disable-pip-version-check -r requirements.txt
) else (
    if exist "pyproject.toml" !PY! -m pip install --quiet --disable-pip-version-check -e .
)
if errorlevel 1 (
    echo [ERROR] Dependency install failed.
    goto :end_fail
)
if /i "%~1"=="deps" (
    echo Dependencies up to date.
    goto :end
)

:after_deps

REM --- Subcommands ------------------------------------------------------------
if /i "%~1"=="test" (
    REM The suite runs OFFLINE and deterministic: no live API call, no quota
    REM spent, no dependency on the network. Clear real credentials here so a
    REM populated .env can never leak into a test run.
    set "VIDEO2AGENT_ENV=test"
    REM set "SOME_API_KEY="
    !PY! -c "import pytest" >nul 2>nul || !PY! -m pip install --quiet --disable-pip-version-check pytest
    !PY! -m pytest -q
    if errorlevel 1 goto :end_fail
    goto :end
)

if /i "%~1"=="safety" (
    REM Run this BEFORE putting any real credential in .env.
    !PY! tools\safety_check.py
    if errorlevel 1 goto :end_fail
    goto :end
)

REM --- Default: run the app ---------------------------------------------------
!PY! -m video2agent %*
if errorlevel 1 goto :end_fail
goto :end

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
REM terminal or run by a scheduler — pausing there would hang an unattended task
REM forever waiting for a keypress that never comes.
if "%~1"=="" pause
endlocal
