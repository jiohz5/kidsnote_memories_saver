@echo off
chcp 65001 >nul
echo ===================================================
echo [Kidsnote Memories Saver V1.00] 릴리스 빌드 스크립트
echo ===================================================
echo.

echo 1. 기존 빌드 폴더 삭제 중...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "Kidsnote_Memories_Saver_V1.00.spec" del /q "Kidsnote_Memories_Saver_V1.00.spec"
echo 완료.
echo.

echo 2. 파이썬 가상환경(venv) 구성 중...
if not exist "venv_build" (
    python -m venv venv_build
)
call venv_build\Scripts\activate
echo 가상환경 진입 완료.
echo.

echo 3. 최소 필수 패키지 설치 중... 
python -m pip install --upgrade pip
pip install pyinstaller pyqt5 selenium pillow requests
echo 패키지 설치 완료.
echo.

echo 4. PyInstaller 단일 파일 컴파일 시작... (가상환경 내부)
pyinstaller --noconfirm --onefile --windowed --hidden-import selenium --hidden-import requests --collect-all selenium --add-binary "C:\edu\samsung-rpa-project-master/msedgedriver.exe;." --add-data "C:\edu\samsung-rpa-project-master/kidsnote_engine.py;." --name "Kidsnote_Memories_Saver_V1.00" --icon "NONE" "C:\edu\samsung-rpa-project-master/kidsnote_saver.py"
echo 컴파일 완료.
echo.

echo 5. 불필요한 파일 정리 및 Release 폴더 생성 중...
if exist "Kidsnote_Release_V1.00" rmdir /s /q "Kidsnote_Release_V1.00"
mkdir "Kidsnote_Release_V1.00"
echo 완료.
echo.

echo 6. 단일 실행 파일 복사 중...
copy /Y "dist\Kidsnote_Memories_Saver_V1.00.exe" "Kidsnote_Release_V1.00\"
echo 단일 실행 파일 복사 완료.
echo.

echo 7. 가상환경 해제...
call deactivate
echo.

echo 8. 배포용 ZIP 파일 자동 압축 중...
if exist "Kidsnote_Release_V1.00.zip" del /q "Kidsnote_Release_V1.00.zip"
python -c "import shutil; shutil.make_archive('Kidsnote_Release_V1.00', 'zip', 'Kidsnote_Release_V1.00')"
echo 압축 완료.
echo.

echo ===================================================
echo 배포 준비가 모두 완료되었습니다!
echo [Kidsnote_Release_V1.00.zip] 파일을 확인하세요.
echo ===================================================
