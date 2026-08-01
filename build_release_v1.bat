@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=C:\edu\samsung-rpa-project-master"
set "BUILD_PY=%PROJECT_ROOT%\venv_build\Scripts\python.exe"
set "DRIVER_PATH=%SCRIPT_DIR%msedgedriver.exe"
if not exist "%DRIVER_PATH%" set "DRIVER_PATH=%PROJECT_ROOT%\msedgedriver.exe"
set "APP_NAME=Kidsnote_Memories_Saver_V1.06"
set "ONEDIR_RELEASE=Kidsnote_Release_V1.06"

REM Build mode (default: both)
REM   both    = single exe + folder zip
REM   onefile = single exe only (run right after download, no unzip)
REM   onedir  = folder zip only (faster start, no temp-folder warning)
set "BUILD_MODE=%~1"
if "%BUILD_MODE%"=="" set "BUILD_MODE=both"

echo ===================================================
echo  Kidsnote Memories Saver - Release Build
echo  mode: %BUILD_MODE%
echo ===================================================
echo.

if not exist "%BUILD_PY%" (
    echo ERROR: Build Python not found: %BUILD_PY%
    exit /b 1
)
if not exist "%DRIVER_PATH%" (
    echo ERROR: Edge WebDriver not found: %DRIVER_PATH%
    exit /b 1
)

if /I "%BUILD_MODE%"=="both" goto build_both

call :build_one %BUILD_MODE%
if errorlevel 1 exit /b 1
goto finish

:build_both
call :build_one onefile
if errorlevel 1 exit /b 1
call :build_one onedir
if errorlevel 1 exit /b 1

:finish
echo ===================================================
echo  Build complete.
if exist "%SCRIPT_DIR%%APP_NAME%.exe" echo   single exe : %APP_NAME%.exe
if exist "%SCRIPT_DIR%%ONEDIR_RELEASE%.zip" echo   folder zip : %ONEDIR_RELEASE%.zip
echo ===================================================
endlocal
exit /b 0


:build_one
REM ---- build one mode (arg: onefile | onedir) ----
set "MODE=%~1"
if /I "%MODE%"=="onefile" (set "MODE_FLAG=--onefile") else (set "MODE_FLAG=--onedir")

echo [%MODE%] 1. Cleaning intermediate outputs...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "%APP_NAME%.spec" del /q "%APP_NAME%.spec"

echo [%MODE%] 2. Building with PyInstaller...
REM kidsnote_engine.py is bundled as bytecode via import, so the plain
REM .py source is intentionally NOT shipped with --add-data.
"%BUILD_PY%" -m PyInstaller --noconfirm %MODE_FLAG% --windowed --hidden-import selenium --hidden-import requests --collect-all selenium --collect-all PIL --add-binary "%DRIVER_PATH%;." --add-data "%SCRIPT_DIR%kidsnote_icon.ico;." --name "%APP_NAME%" --icon "%SCRIPT_DIR%kidsnote_icon.ico" "%SCRIPT_DIR%kidsnote_saver.py"
if errorlevel 1 (
    echo ERROR: PyInstaller build failed [%MODE%]
    exit /b 1
)

echo [%MODE%] 3. Collecting release artifact...
if /I "%MODE%"=="onefile" goto collect_onefile

if exist "%ONEDIR_RELEASE%" rmdir /s /q "%ONEDIR_RELEASE%"
if exist "%ONEDIR_RELEASE%.zip" del /q "%ONEDIR_RELEASE%.zip"
mkdir "%ONEDIR_RELEASE%"
xcopy /E /I /Y "dist\%APP_NAME%" "%ONEDIR_RELEASE%\%APP_NAME%" >nul
if errorlevel 1 (
    echo ERROR: Failed to copy onedir output.
    exit /b 1
)
"%BUILD_PY%" -c "import shutil; shutil.make_archive(r'%ONEDIR_RELEASE%', 'zip', r'%ONEDIR_RELEASE%')"
if errorlevel 1 (
    echo ERROR: Failed to create zip.
    exit /b 1
)
echo [%MODE%] Done.
echo.
exit /b 0

:collect_onefile
REM Ship the exe as-is (no zip) so users can run it right after download
copy /Y "dist\%APP_NAME%.exe" "%SCRIPT_DIR%%APP_NAME%.exe" >nul
if errorlevel 1 (
    echo ERROR: Failed to copy single exe.
    exit /b 1
)
echo [%MODE%] Done.
echo.
exit /b 0
