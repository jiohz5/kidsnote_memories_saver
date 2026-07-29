# Claude Code Review Prompt

아래 프로젝트를 코드 리뷰하고, 필요한 경우 안정성 중심으로 수정해줘.

## 프로젝트 개요

프로젝트명: Kidsnote Memories Saver

키즈노트(kidsnote.com)에 로그인한 뒤 자녀 프로필을 선택하고, 알림장과 앨범 사진/동영상을 로컬 PC에 백업하는 Windows 데스크톱 앱이야.

## 기술 스택

- Python
- PyQt5 GUI
- QThread 기반 백그라운드 작업
- Selenium + Microsoft Edge WebDriver
- PyInstaller one-file exe 배포
- Windows bat 빌드 스크립트

## 핵심 파일

- `kidsnote_saver.py`
  - 메인 PyQt5 GUI
  - 로그인 입력/상태 표시
  - 자녀 프로필 표시
  - 목록 불러오기/다운로드 버튼 처리
  - `ScrapeThread`, `DownloadThread` 등 스레드 제어

- `kidsnote_engine.py`
  - Selenium 기반 Kidsnote 웹 자동화
  - 로그인 후 자녀 선택
  - 알림장/앨범 목록 수집
  - PDF 저장
  - 사진/동영상 다운로드

- `build_release_v1.bat`
  - PyInstaller 빌드 스크립트
  - `msedgedriver.exe`, `kidsnote_engine.py`, `kidsnote_icon.ico` 포함

- `test_*.py`
  - 기존 E2E/시나리오 테스트 초안

## 최근 겪은 문제

다음 이슈들을 중심으로 검토해줘.

1. 다운로드 버튼 클릭 후 UI가 `다운로드 준비 중...`에서 멈추거나 Edge가 움직이지 않는 문제
2. PyQt UI 프리징 또는 갑작스러운 종료
3. QThread와 GUI 스레드 간 안전하지 않은 호출
4. 다운로드 중지 버튼이 즉시 반응하지 않는 문제
5. Edge WebDriver 버전 불일치 및 자동 다운로드/캐시 구조 안정성
6. PyInstaller one-file exe 종료 시 `_MEI...` 임시폴더 삭제 실패 경고
7. 회사 PC/사내망에서 프로필 이미지 로딩 또는 다운로드가 멈추는 문제
8. 로그에 개인정보나 민감 데이터가 남지 않는지

## 리뷰 목표

우선순위는 다음과 같아.

1. 실제 사용자 PC에서 멈추지 않고 안정적으로 동작
2. 다운로드 시작/진행/중지/완료 흐름이 명확하게 동작
3. QThread 사용이 PyQt 관점에서 안전함
4. Selenium/EdgeDriver 실패 시 사용자에게 복구 가능한 메시지를 보여줌
5. PyInstaller 배포판에서 누락 모듈이나 DLL 문제가 나지 않음
6. 테스트 가능성이 올라가도록 구조 개선

## 요청 방식

먼저 전체 구조를 빠르게 파악한 뒤, 아래 형식으로 답해줘.

1. 치명적 버그 또는 높은 위험도 문제
2. 중간 위험도 문제
3. 낮은 위험도/개선 제안
4. 추천 수정 방향
5. 실제 코드 수정이 필요한 파일 목록

가능하면 직접 코드를 수정해줘. 단, 대규모 리팩터링보다는 현재 구조를 살리면서 안정성을 올리는 방향을 선호해.

## 주의사항

- 테스트 산출물, 다운로드 결과물, 실제 사용자 데이터는 이 폴더에 포함하지 않았어.
- `msedgedriver.exe`, `dist/`, `build/`, `venv_build/`, `Kidsnote_Release*.zip` 등은 리뷰 패키지에서 제외했어.
- 리뷰 중 개인정보/로그/자격증명 저장 방식도 같이 봐줘.
