# 🧒 Kidsnote Memories Saver (키즈노트 추억 저장기)

> 키즈노트(kidsnote.com)에 올라온 우리 아이의 소중한 추억(알림장, 앨범)을 한 번에 내 컴퓨터로 다운로드할 수 있는 프로그램입니다.

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![PyQt5](https://img.shields.io/badge/GUI-PyQt5-green.svg)
![Selenium](https://img.shields.io/badge/Browser-Selenium%204-orange.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

---

## ✨ 주요 기능

- 🔐 **안전한 로그인** — 키즈노트 사이트에 직접 로그인 (ID/PW는 로컬에만 저장)
- 👶 **다자녀 지원** — 여러 아이가 등록되어 있어도 콤보박스로 전환 가능
- 📋 **알림장(보고서) 저장** — 선생님이 작성해주신 알림장을 PDF로 저장
- 📸 **앨범 사진 저장** — 사진 원본을 내 컴퓨터에 폴더별로 정리하여 다운로드
- 📅 **기간 선택** — 원하는 날짜 이후의 게시글만 선택적으로 수집
- 🖼️ **프로필 사진 표시** — 선택한 아이의 얼굴 사진이 프로그램에 실시간 표시
- 📂 **저장 폴더 열기** — 다운로드한 파일을 바로 탐색기에서 확인

---

## 🚀 사용 방법

### 방법 1: EXE 파일 실행 (추천 — 설치 불필요!)

1. [Releases](../../releases) 페이지에서 **`Kidsnote_Memories_Saver_v260226.exe`** 를 다운로드합니다
2. 다운로드한 `.exe` 파일을 더블클릭하여 실행합니다
3. **Chrome 브라우저가 컴퓨터에 설치되어 있어야 합니다** (별도의 ChromeDriver는 필요 없습니다!)

### 방법 2: Python으로 직접 실행

```bash
# 필수 패키지 설치
pip install PyQt5 selenium Pillow

# 실행
python kidsnote_memories_saver.py
```

---

## 📖 상세 사용법

### 1단계: 로그인
1. 프로그램을 실행하면 안내 팝업이 나타납니다 → **확인** 클릭
2. 키즈노트 **아이디(이메일)**와 **비밀번호**를 입력합니다
3. **"1. 키즈노트 로그인 열기"** 버튼 클릭
4. 로딩 화면이 나타나며, Chrome 브라우저가 자동으로 열리고 로그인됩니다
5. 아이 프로필 사진이 표시되면 로그인 성공!

### 2단계: 추억 목록 불러오기
1. **수집 범위**를 선택합니다 (알림장 / 사진앨범 / 둘 다)
2. 기간 제한이 필요하면 날짜를 설정합니다
3. **"2. 추억 목록 불러오기"** 버튼 클릭
4. 프로그램이 자동으로 키즈노트를 순회하며 목록을 수집합니다

### 3단계: 다운로드
1. 테이블에서 다운로드하고 싶은 항목을 **체크**합니다 (전체 선택 가능)
2. **저장 폴더**를 지정합니다
3. **"3. 선택한 항목 다운로드 시작"** 버튼 클릭
4. 완료되면 알림이 뜹니다!

---

## ⚠️ 주의사항

- **Chrome 브라우저**가 반드시 설치되어 있어야 합니다
- ChromeDriver는 **별도 설치 불필요** — Selenium 4가 자동으로 관리합니다
- 로그인 정보는 **내 컴퓨터 로컬**에만 저장되며 외부로 전송되지 않습니다
- 키즈노트 서버에 부담을 주지 않기 위해 적절한 대기 시간이 포함되어 있습니다
- 수집 중 프로그램을 강제 종료하면 일부 데이터가 누락될 수 있습니다

---

## 🛠️ 개발 환경에서 EXE 빌드하기

```bash
# PyInstaller 설치
pip install pyinstaller

# 빌드 실행
build_exe.bat
```

빌드가 완료되면 `dist/` 폴더에 `.exe` 파일이 생성됩니다.

---

## 📁 프로젝트 구조

```
├── kidsnote_memories_saver.py   # 메인 GUI 프로그램
├── kidsnote_save_manager.py     # 키즈노트 스크래핑 엔진
├── build_exe.bat                # EXE 빌드 스크립트
└── README.md                    # 이 파일
```

---

## 💡 FAQ

**Q: ChromeDriver를 따로 설치해야 하나요?**
> 아니요! Selenium 4에 내장된 Selenium Manager가 Chrome 버전에 맞는 드라이버를 자동으로 다운로드합니다. Chrome 브라우저만 설치되어 있으면 됩니다.

**Q: 다른 사람에게 줄 때 뭘 보내야 하나요?**
> `dist/` 폴더 안의 `.exe` 파일 하나만 보내면 됩니다. 받는 사람의 PC에 Chrome 브라우저만 설치되어 있으면 바로 사용 가능합니다.

**Q: 맥(Mac)에서도 사용할 수 있나요?**
> 현재는 Windows 전용입니다. Python이 설치되어 있다면 `python kidsnote_memories_saver.py`로 직접 실행은 가능할 수 있습니다.

**Q: 프로그램이 바이러스로 뜨는데요?**
> PyInstaller로 만든 `.exe`는 일부 백신에서 오탐(False Positive)할 수 있습니다. 소스 코드가 공개되어 있으니 안심하셔도 됩니다.

---

## 📜 라이선스

MIT License — 자유롭게 사용, 수정, 배포하실 수 있습니다.

---

*Made with ❤️ for parents who want to keep their children's precious memories.*
