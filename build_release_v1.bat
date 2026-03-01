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

echo 2. PyInstaller 컴파일 시작...
python -m PyInstaller --noconfirm --onedir --windowed --add-data "C:\edu\samsung-rpa-project-master/kidsnote_engine.py;." --name "Kidsnote_Memories_Saver_V1.00" --icon "NONE" "C:\edu\samsung-rpa-project-master/kidsnote_saver.py"
echo 컴파일 완료.
echo.

echo 3. 불필요한 파일 정리 및 Release 폴더 생성 중...
if exist "Kidsnote_Release_V1.00" rmdir /s /q "Kidsnote_Release_V1.00"
mkdir "Kidsnote_Release_V1.00"
echo 완료.
echo.

echo 4. 실행 파일 런처 복사 중...
copy /Y "dist\Kidsnote_Memories_Saver_V1.00\Kidsnote_Memories_Saver_V1.00.exe" "Kidsnote_Release_V1.00\"
xcopy /E /I /Y "dist\Kidsnote_Memories_Saver_V1.00\_internal" "Kidsnote_Release_V1.00\_internal"
echo 런처 복사 완료.
echo.

echo ===================================================
echo 배포 준비가 모두 완료되었습니다!
echo [Kidsnote_Release_V1.00] 폴더를 통째로 압축해서 
echo 배포를 진행하시거나, 폴더 째로 공유하시면 됩니다.
echo ===================================================
pause
