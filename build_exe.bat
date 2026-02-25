@echo off
chcp 65001
echo ============================================
echo [빌드 시작] Kidsnote Memories Saver v260226
echo ============================================

rem Conda 환경의 Qt DLL 경로
set PATH=%PATH%;C:\Users\jioh5\anaconda3\Library\bin;C:\Users\jioh5\anaconda3\Library\plugins

rem 기존 잔여물 삭제
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul

rem PyInstaller 실행 - 불필요한 모듈 제외하여 용량 대폭 절감
C:\Users\jioh5\anaconda3\Scripts\pyinstaller.exe ^
    --name "Kidsnote_Memories_Saver_v260226" ^
    --onefile ^
    --windowed ^
    --noconfirm ^
    --paths "C:\Users\jioh5\anaconda3\Library\bin" ^
    --hidden-import "selenium.webdriver.common.service" ^
    --hidden-import "selenium.webdriver.chrome.service" ^
    --hidden-import "PIL" ^
    --exclude-module numpy ^
    --exclude-module pandas ^
    --exclude-module matplotlib ^
    --exclude-module scipy ^
    --exclude-module sklearn ^
    --exclude-module notebook ^
    --exclude-module jupyter ^
    --exclude-module IPython ^
    --exclude-module tornado ^
    --exclude-module zmq ^
    --exclude-module jedi ^
    --exclude-module docutils ^
    --exclude-module sphinx ^
    --exclude-module pytest ^
    --exclude-module setuptools ^
    --exclude-module pip ^
    --exclude-module tkinter ^
    --exclude-module unittest ^
    --exclude-module xml ^
    --exclude-module xmlrpc ^
    --exclude-module pydoc ^
    --exclude-module lib2to3 ^
    --exclude-module curses ^
    --exclude-module lxml ^
    --exclude-module babel ^
    --exclude-module cryptography ^
    --exclude-module nacl ^
    --exclude-module cv2 ^
    --exclude-module tensorflow ^
    --exclude-module torch ^
    --exclude-module h5py ^
    --exclude-module boto ^
    --exclude-module botocore ^
    --exclude-module psutil ^
    kidsnote_memories_saver.py

echo.
echo ============================================
echo [빌드 완료] dist 폴더를 확인해주세요.
echo ============================================

rem 파일 크기 표시
for %%F in (dist\Kidsnote_Memories_Saver_v260226.exe) do echo 파일 크기: %%~zF bytes
explorer.exe dist
