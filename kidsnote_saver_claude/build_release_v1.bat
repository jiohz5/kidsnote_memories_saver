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

REM 빌드 모드: 기본 onedir(폴더 배포).
REM  - onedir: 실행 시 임시폴더(MEIxxxx) 추출이 없어 시작이 빠르고,
REM    사내 PC에서 종료 시 "임시폴더 삭제 실패" 경고가 원천적으로 없음. (기본)
REM  - "build_release_v1.bat onefile"로 실행하면 기존 단일 exe 빌드.
set "BUILD_MODE=%~1"
if "%BUILD_MODE%"=="" set "BUILD_MODE=onedir"
if /I "%BUILD_MODE%"=="onefile" (
    set "MODE_FLAG=--onefile"
    set "RELEASE_DIR=Kidsnote_Release_V1.00_onefile"
) else (
    set "BUILD_MODE=onedir"
    set "MODE_FLAG=--onedir"
)

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

echo 2. Building %BUILD_MODE% exe with PyInstaller...
REM kidsnote_engine.py는 import로 자동 포함(바이트코드)되므로 --add-data로
REM 평문 소스를 동봉하지 않는다 (배포물에 .py 원문이 노출되는 것 방지)
"%BUILD_PY%" -m PyInstaller --noconfirm %MODE_FLAG% --windowed --hidden-import selenium --hidden-import requests --collect-all selenium --collect-all PIL --add-binary "%DRIVER_PATH%;." --add-data "%SCRIPT_DIR%kidsnote_icon.ico;." --name "%APP_NAME%" --icon "%SCRIPT_DIR%kidsnote_icon.ico" "%SCRIPT_DIR%kidsnote_saver.py"
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    exit /b 1
)
echo Done.
echo.

echo 3. Creating release folder...
mkdir "%RELEASE_DIR%"
if /I "%BUILD_MODE%"=="onefile" (
    copy /Y "dist\%APP_NAME%.exe" "%RELEASE_DIR%\"
) else (
    xcopy /E /I /Y "dist\%APP_NAME%" "%RELEASE_DIR%\%APP_NAME%" >nul
)
if errorlevel 1 (
    echo ERROR: Failed to copy build output into release folder.
    exit /b 1
)
echo Done.
echo.

echo 4. Creating release zip...
"%BUILD_PY%" -c "import shutil; shutil.make_archive(r'%RELEASE_DIR%', 'zip', r'%RELEASE_DIR%')"
if errorlevel 1 (
    echo ERROR: Failed to create zip.
    exit /b 1
)
echo Done.
echo.

echo ===================================================
echo Release ready: %SCRIPT_DIR%%RELEASE_DIR%.zip  (mode: %BUILD_MODE%)
echo ===================================================
endlocal
