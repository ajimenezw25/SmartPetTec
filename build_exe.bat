@echo off
cd /d "%~dp0"

echo.
echo  SmartPetHome - building EXE...
echo.

:: Build venv on C: so Windows Store Python can write it
set BUILD_VENV=C:\Temp\sph-build-venv
set PYTHON=%BUILD_VENV%\Scripts\python.exe

if not exist "%BUILD_VENV%" (
    echo  [INFO] Creating build venv at %BUILD_VENV% ...
    python -m venv "%BUILD_VENV%"
    if errorlevel 1 ( echo [ERROR] venv creation failed & pause & exit /b 1 )
)

echo  [INFO] Installing dependencies...
"%PYTHON%" -m pip install -r requirements.txt --quiet
"%PYTHON%" -m pip install pyinstaller==6.20.0 Pillow --quiet

echo  [INFO] Generating icon...
"%PYTHON%" make_icon.py

echo  [INFO] Cleaning old build...
if exist build   rmdir /s /q build
if exist dist    rmdir /s /q dist
if exist release rmdir /s /q release

echo  [INFO] Running PyInstaller...
"%PYTHON%" -m PyInstaller smartpethome.spec --clean --noconfirm

if not exist "dist\SmartPetHome\SmartPetHome.exe" (
    echo  [ERROR] Build failed - EXE not found.
    pause & exit /b 1
)

echo  [INFO] Assembling release folder...
mkdir "release\SmartPetHome"
xcopy /e /i /q "dist\SmartPetHome" "release\SmartPetHome"
if exist ".env.example" copy ".env.example" "release\SmartPetHome\.env.example" >nul
if exist "README_RUN.txt" copy "README_RUN.txt" "release\SmartPetHome\README_RUN.txt" >nul
if exist "release\SmartPetHome\.env" del /q "release\SmartPetHome\.env"

echo.
echo  ============================================================
echo   Done!  release\SmartPetHome\SmartPetHome.exe is ready.
echo  ============================================================
echo.
pause
