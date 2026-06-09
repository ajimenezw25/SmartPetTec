@echo off
cd /d "%~dp0"

echo.
echo  SmartPetHome - starting...
echo.

:: Check .env
if not exist ".env" (
    if exist ".env.example" (
        echo  [INFO] .env not found - copying .env.example to .env
        copy ".env.example" ".env" >nul
        echo  [ACTION REQUIRED] Open .env and fill in your credentials, then re-run this file.
        pause
        exit /b 1
    ) else (
        echo  [ERROR] .env not found and .env.example is missing.
        pause
        exit /b 1
    )
)

:: Use a venv on C: so Windows Store Python can create it
set VENV=C:\Temp\sph-venv
set PYTHON=%VENV%\Scripts\python.exe

if not exist "%PYTHON%" (
    echo  [INFO] Creating virtual environment at %VENV% ...
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo  [ERROR] Could not create virtual environment.
        echo          Make sure Python 3.11+ is installed and on PATH.
        pause
        exit /b 1
    )
    echo  [OK] Virtual environment created.
)

:: Install / update dependencies
echo  [INFO] Installing requirements...
"%PYTHON%" -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo  [ERROR] pip install failed.
    pause
    exit /b 1
)

:: Launch
echo  [INFO] Launching SmartPetHome...
echo.
"%PYTHON%" launcher.py

if errorlevel 1 (
    echo.
    echo  [ERROR] SmartPetHome exited with an error. See output above.
    pause
)
