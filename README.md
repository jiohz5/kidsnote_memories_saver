# 🧒 Kidsnote Memories Saver (키즈노트 추억 저장기) V1.00

> 키즈노트(kidsnote.com)에 올라온 우리 아이의 소중한 추억(알림장, 앨범)을 한 번에 내 컴퓨터로 다운로드할 수 있는 윈도우용 프로그램입니다.

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![PyQt5](https://img.shields.io/badge/GUI-PyQt5-green.svg)
![Edge](https://img.shields.io/badge/Browser-Microsoft%20Edge-informational.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

---

## ✨ 주요 기능 (V1.00 안정화 버전)

- 🚀 **완벽한 오프라인 구동 (New!)** — 사내망/방화벽 환경에서도 차단 없이 무조건 실행되도록 Edge WebDriver를 프로그램 내부에 완전히 내장했습니다.
- 🖥️ **4K 고해상도 완벽 지원 (New!)** — High DPI 자동 스케일링을 지원하여 4K 모니터에서도 UI와 글씨가 작아지지 않고 선명하게 보입니다.
- 🔐 **안전한 로그인** — 키즈노트 사이트에 직접 로그인 (ID/PW는 로컬 컴퓨터에만 암호화되어 저장)
- 👶 **다자녀 지원** — 여러 아이가 등록되어 있어도 콤보박스로 즉시 전환
- 📋 **알림장(보고서) 저장** — 선생님이 작성해주신 알림장을 PDF 형식으로 보존
- 📸 **앨범 사진/동영상 저장** — 원본 화질을 그대로 폴더별로 일괄 다운로드
- 🖼️ **실시간 가이드 오버레이** — 사용자가 순서대로 진행할 수 있도록 화면을 잠그고 안내하는 UI 오버레이 제공

---

## 🚀 다운로드 및 실행 방법

### 방법 1: 배포용 EXE 파일 바로 실행 (추천 — 100% 무설치!)

1. GitHub의 [Releases](../../releases) 페이지에서 최신 **`Kidsnote_Release_V1.00.zip`** 파일을 다운로드합니다.
2. 압축을 풀고 안에 있는 **`Kidsnote_Memories_Saver_V1.00.exe`** 를 더블클릭하여 실행합니다.
3. **Microsoft Edge 브라우저**만 사용자의 윈도우 PC에 설치되어 있으면 끝입니다! (별도의 프로그램이나 드라이버 설치가 절대 필요 없습니다.)

> [!TIP]
> **Windows SmartScreen 경고가 뜰 경우 해결법**
> 개인이 만든 무료 프로그램이라 인증서가 없어 발생합니다. [추가 정보] -> [실행] 버튼을 누르시면 됩니다. 코드는 이 저장소에 전면 공개되어 있습니다.

### 방법 2: Python 개발 환경에서 직접 실행

```bash
# 파이썬 패키지 설치
pip install PyQt5 selenium Pillow requests

# msedgedriver.exe (Edge WebDriver)를 현재 폴더에 미리 준비해야 합니다.

# 직접 실행
python kidsnote_saver.py
```

---

## 🛠️ GitHub 저장소 업로드 가이드 (개발자용)

저장소를 외부에 공개하거나 배포할 때, **소스 코드(Source Code)**와 **릴리스 배포판(Release)**을 명확히 구분하여 업로드해야 합니다.

### 1. 일반 레포지토리(저장소)에 업로드할 파일들:
저장소의 `main` 브랜치에는 순수 소스 코드와 문서만 올라가야 합니다. `.gitignore`가 설정되어 있으므로 `git push`를 하면 아래 파일들만 안전하게 업로드됩니다.
- `kidsnote_saver.py` (메인 GUI)
- `kidsnote_engine.py` (코어 스크래핑 엔진)
- `build_release_v1.bat` (빌드 스크립트)
- `README.md` (설명서)
- `test_*.py` (테스트 스크립트 모음)
- `.gitignore`
- *(주의: `msedgedriver.exe` 및 `.zip` 파일은 용량이 크므로 일반 커밋에 포함시키지 않습니다.)*

### 2. GitHub Releases 메뉴에 업로드할 파일 (배포용):
GitHub 저장소 우측의 **"Releases" -> "Draft a new release"** 메뉴를 통해 버전을 발행하실 때, 아래 1개의 바이너리 파일만 첨부(Upload) 하시면 됩니다.
- 🎯 **`Kidsnote_Release_V1.00.zip`** (빌드 스크립트가 자동으로 만들어준 100% 무설치 완성본입니다.)

---

## 💡 자주 묻는 질문 (FAQ)

**Q: 크롬(Chrome)을 쓰는데 작동하나요?**
> 사용자 PC의 기본 브라우저가 크롬이더라도 상관없습니다! 프로그램은 윈도우에 기본 내장된 **Microsoft Edge**를 몰래 열어서 작업을 대행합니다. 

**Q: 사내망이라서 보안 차단 프로그램이 빡빡한데, 인터넷에서 뭘 몰래 다운받다가 막히지 않나요?**
> 막히지 않습니다! 가장 흔한 웹 드라이버 에러를 방지하기 위해 프로그램 `exe` 내부에 Edge 통신용 엔진을 직접 쑤셔 넣어서(Bundling) 빌드했습니다. 폐쇄망에서도 Edge 브라우저만 창이 뜰 수 있다면 100% 구동됩니다.

**Q: 화면 글씨가 너무 큽니다 / 작습니다.**
> V1.00부터 4K High DPI 최적화와 해상도별 동적 스케일링(`FS()`)이 완벽히 적용되었습니다. 사용하시는 윈도우의 '디스플레이 배율' 설정에 따라 똑똑하게 사이즈를 맞춥니다.

---

## 📜 라이선스

MIT License — 자유롭게 사용, 수정, 배포하실 수 있습니다. *(단, 상업적 대량 자동화 용도의 무단 남용은 권장하지 않습니다.)*
