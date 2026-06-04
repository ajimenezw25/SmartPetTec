@echo off
cd /d "%~dp0"
echo.
echo  SmartPetHome -- starting...
echo.

if not exist ".env" (
    echo  [WARNING] .env not found.
    echo            Copy .env.example to .env and fill in your credentials.
    echo            Then double-click Start_SmartPetHome.bat again.
    pause
    exit /b 1
)

if not exist "app\SmartPetHome.exe" (
    echo  [ERROR] app\SmartPetHome.exe not found.
    echo          This file must be run from the SmartPetHome release folder.
    pause
    exit /b 1
)

app\SmartPetHome.exe

echo.
echo  SmartPetHome has stopped.
echo  If you see an error above, check app\crash.log for details.
pause
