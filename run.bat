@echo off
:: ============================================================
::  SmartPetHome - Run Script
::  Double-click this to start the app after setup.
:: ============================================================

echo.
echo  Starting SmartPetHome...
echo.

:: Check .env exists
if not exist .env (
    echo [ERROR] .env file not found.
    echo Please run setup.bat first.
    pause
    exit /b 1
)

:: Check venv exists
if not exist venv\Scripts\activate.bat (
    echo [ERROR] Virtual environment not found.
    echo Please run setup.bat first.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

echo  Opening http://localhost:5000 in your browser...
:: Small delay so Flask starts before the browser opens
start /b cmd /c "timeout /t 2 >nul && start http://localhost:5000"

echo  Press Ctrl+C to stop the server.
echo.
python app.py

pause
