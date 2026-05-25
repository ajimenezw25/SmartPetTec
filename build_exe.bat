@echo off
:: ============================================================
::  SmartPetHome - Build Windows .exe
::  Run this on YOUR development machine (not the user's).
::  Requires: setup.bat already run, PyInstaller installed.
:: ============================================================

echo.
echo  Building SmartPetHome executable...
echo.

call venv\Scripts\activate.bat

pyinstaller smartpethome.spec --clean --noconfirm

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Check output above.
    pause
    exit /b 1
)

echo.
echo  ==========================================
echo   Build successful!
echo   Output: dist\SmartPetHome\
echo  ==========================================
echo.
echo  BEFORE DISTRIBUTING:
echo  1. Copy your .env file into dist\SmartPetHome\
echo  2. Zip the entire dist\SmartPetHome\ folder
echo  3. Share the zip — users run SmartPetHome.exe
echo.
pause
