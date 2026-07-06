@echo off
chcp 65001 >nul
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=C:\edu\samsung-rpa-project-master"
set "BUILD_PY=%PROJECT_ROOT%\venv_build\Scripts\python.exe"
set "DRIVER_PATH=%SCRIPT_DIR%msedgedriver.exe"
if not exist "%DRIVER_PATH%" set "DRIVER_PATH=%PROJECT_ROOT%\msedgedriver.exe"
set "APP_NAME=Kidsnote_Memories_Saver_V1.00"
set "RELEASE_DIR=Kidsnote_Release_V1.00"

echo ===================================================
echo [Kidsnote Memories Saver V1.00] Release Build
echo ===================================================
echo.

if not exist "%BUILD_PY%" (
    echo ERROR: Build Python not found: %BUILD_PY%
    echo Please prepare the build venv first.
    exit /b 1
)

if not exist "%DRIVER_PATH%" (
    echo ERROR: Edge WebDriver not found: %DRIVER_PATH%
    exit /b 1
)

echo 1. Cleaning old build outputs...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "%APP_NAME%.spec" del /q "%APP_NAME%.spec"
if exist "%RELEASE_DIR%" rmdir /s /q "%RELEASE_DIR%"
if exist "%RELEASE_DIR%.zip" del /q "%RELEASE_DIR%.zip"
echo Done.
echo.

echo 2. Building one-file exe with PyInstaller...
"%BUILD_PY%" -m PyInstaller --noconfirm --onefile --windowed --hidden-import selenium --hidden-import requests --collect-all selenium --collect-all PIL --add-binary "%DRIVER_PATH%;." --add-data "%SCRIPT_DIR%kidsnote_engine.py;." --add-data "%SCRIPT_DIR%kidsnote_icon.ico;." --name "%APP_NAME%" --icon "%SCRIPT_DIR%kidsnote_icon.ico" "%SCRIPT_DIR%kidsnote_saver.py"
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    exit /b 1
)
echo Done.
echo.

echo 3. Creating release folder...
mkdir "%RELEASE_DIR%"
copy /Y "dist\%APP_NAME%.exe" "%RELEASE_DIR%\"
if errorlevel 1 (
    echo ERROR: Failed to copy exe into release folder.
    exit /b 1
)
echo Done.
echo.

echo 4. Creating release zip...
"%BUILD_PY%" -c "import shutil; shutil.make_archive('Kidsnote_Release_V1.00', 'zip', 'Kidsnote_Release_V1.00')"
if errorlevel 1 (
    echo ERROR: Failed to create zip.
    exit /b 1
)
echo Done.
echo.

echo ===================================================
echo Release ready: %SCRIPT_DIR%%RELEASE_DIR%.zip
echo ===================================================
endlocal
