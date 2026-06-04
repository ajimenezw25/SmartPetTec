@echo off
setlocal enabledelayedexpansion
:: ============================================================
::  SmartPetHome — Run from source (Windows)
::  Double-click, or run from Command Prompt.
:: ============================================================

cd /d "%~dp0"

echo.
echo  SmartPetHome — starting...
echo.

:: ── Check .env ────────────────────────────────────────────────
if not exist ".env" (
    if exist ".env.example" (
        echo  [INFO] .env not found — copying .env.example to .env
        copy ".env.example" ".env" >nul
        echo  [ACTION REQUIRED] Open .env and fill in your credentials, then re-run this file.
        pause
        exit /b 1
    ) else (
        echo  [ERROR] .env not found and .env.example is missing.
        echo          Create a .env file with your credentials before running.
        pause
        exit /b 1
    )
)

:: ── Create .venv if missing ───────────────────────────────────
if not exist ".venv\Scripts\activate.bat" (
    echo  [INFO] Virtual environment not found — creating .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo  [ERROR] Could not create virtual environment.
        echo          Make sure Python 3.11+ is installed and on PATH.
        pause
        exit /b 1
    )
    echo  [OK] .venv created.
)

:: ── Activate .venv ────────────────────────────────────────────
call ".venv\Scripts\activate.bat"

:: ── Install / update dependencies ────────────────────────────
echo  [INFO] Installing requirements...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo  [ERROR] pip install failed.
    pause
    exit /b 1
)

:: ── Launch ────────────────────────────────────────────────────
echo  [INFO] Launching SmartPetHome...
echo.
python launcher.py

if errorlevel 1 (
    echo.
    echo  [ERROR] SmartPetHome exited with an error. See output above.
    pause
)
endlocal
