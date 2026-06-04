@echo off
:: ============================================================
::  SmartPetHome - Build Windows .exe
::  Output: release\SmartPetHome\
::
::  Final structure:
::    release\SmartPetHome\
::      SmartPetHome.exe
::      _internal\
::      .env.example
::      README_RUN.txt
::      docs\              (if present)
:: ============================================================

cd /d "%~dp0"

echo.
echo  SmartPetHome -- building executable...
echo.

if not exist ".venv\Scripts\activate.bat" (
    echo  [ERROR] .venv not found. Run run_app.bat first to create it.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"

pip show pyinstaller | findstr /i "6.20" >nul
if errorlevel 1 (
    echo  [INFO] Installing pyinstaller==6.20.0 ...
    pip install pyinstaller==6.20.0 --quiet
)

echo  [INFO] Cleaning build\, dist\, release\ ...
if exist build   rmdir /s /q build
if exist dist    rmdir /s /q dist
if exist release rmdir /s /q release

echo  [INFO] Running PyInstaller ...
pyinstaller smartpethome.spec --clean --noconfirm

if errorlevel 1 (
    echo.
    echo  [ERROR] PyInstaller build failed. See output above.
    pause
    exit /b 1
)

if not exist "dist\SmartPetHome\SmartPetHome.exe" (
    echo  [ERROR] dist\SmartPetHome\SmartPetHome.exe not found after build.
    pause
    exit /b 1
)

:: ── Copy dist directly into release\SmartPetHome\ ────────────
echo  [INFO] Assembling release\SmartPetHome\ ...
mkdir "release\SmartPetHome"
xcopy /e /i /q "dist\SmartPetHome" "release\SmartPetHome"

:: Remove PyInstaller build artefacts that occasionally land in dist\
del /q "release\SmartPetHome\*.toc"        2>nul
del /q "release\SmartPetHome\*.pyz"        2>nul
del /q "release\SmartPetHome\xref-*.html"  2>nul
del /q "release\SmartPetHome\warn-*.txt"   2>nul
if exist "release\SmartPetHome\localpycs" rmdir /s /q "release\SmartPetHome\localpycs"

:: Never ship real .env
if exist "release\SmartPetHome\.env" (
    del /q "release\SmartPetHome\.env"
    echo  [INFO] Removed .env from release.
)

:: ── Support files ─────────────────────────────────────────────
copy ".env.example"   "release\SmartPetHome\.env.example"  >nul
copy "README_RUN.txt" "release\SmartPetHome\README_RUN.txt" >nul

if exist "docs" xcopy /e /i /q "docs" "release\SmartPetHome\docs"

:: ── Show result ───────────────────────────────────────────────
echo.
echo  ============================================
echo   Build complete!  Output: release\SmartPetHome\
echo  ============================================
echo.
dir /b "release\SmartPetHome"
echo.
pause
