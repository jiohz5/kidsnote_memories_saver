# 🚀 릴리스 체크리스트

새 버전을 배포하기 전에 이 순서대로 확인합니다.

---

## 1. Edge WebDriver가 최신인지 확인 ⚠️ 가장 중요

배포본 안에는 `msedgedriver.exe` 가 함께 들어갑니다.
이 드라이버는 **사용자 PC의 Edge와 메이저 버전이 같을 때만** 그대로 쓰입니다.

버전이 뒤처지면 → 실행할 때마다 드라이버를 새로 내려받는 경로로 빠짐
→ **사내망처럼 다운로드가 막힌 환경에서는 프로그램이 아예 실행되지 않습니다.**

```bash
python check_driver.py msedgedriver.exe
```

| 결과 | 의미 |
|---|---|
| `-> OK: 메이저 버전이 최신과 같습니다` | 그대로 배포 가능 |
| `*** 경고: 동봉 드라이버가 148, 최신은 151` | **아래 절차로 교체 후 배포** |

### 드라이버 교체 방법

1. 경고 메시지에 표시된 주소로 접속해 zip을 받습니다
   `https://msedgedriver.microsoft.com/<최신버전>/edgedriver_win64.zip`
   (또는 [공식 다운로드 페이지](https://developer.microsoft.com/microsoft-edge/tools/webdriver/))
2. 압축을 풀고 `msedgedriver.exe` 를 이 폴더의 것과 **교체**합니다
3. `python check_driver.py msedgedriver.exe` 로 OK가 나오는지 다시 확인합니다

> 빌드 스크립트도 시작할 때 이 검사를 자동으로 수행하며,
> 버전이 뒤처지면 계속할지 물어봅니다.

---

## 2. 버전 번호 올리기

아래 세 곳의 버전을 새 버전으로 맞춥니다.

| 파일 | 위치 |
|---|---|
| `kidsnote_saver.py` | `APP_VERSION`, `myappid`, `setWindowTitle` |
| `build_release_v1.bat` | `APP_NAME`, `ONEDIR_RELEASE` |
| `README.md` | 버전을 직접 적은 곳이 있다면 (현재는 `Vx.xx` 표기라 보통 불필요) |

---

## 3. 빌드

```bash
build_release_v1.bat
```

- 기본값(`both`)으로 **단일 exe + 폴더 zip** 두 가지가 모두 생성됩니다
- 결과물: `Kidsnote_Memories_Saver_Vx.xx.exe`, `Kidsnote_Release_Vx.xx.zip`

---

## 4. 배포 전 실물 점검

빌드된 exe를 직접 실행해 아래를 확인합니다.

- [ ] 프로그램이 정상적으로 뜨는가 (콘솔 창이 뜨지 않아야 정상)
- [ ] 로그인 → 아이 목록에 **얼굴 사진**이 표시되는가
- [ ] 목록 불러오기 → **작성자·날짜·제목**이 제대로 나오는가
- [ ] 몇 건 다운로드 → 폴더/파일 이름이 의도대로인가
      (`20260714/260714_알림장_제목.pdf`)
- [ ] 종료 시 오류 창이 뜨지 않는가

---

## 5. 릴리스 발행

```bash
git tag -a Vx.xx -m "..."
git push origin Vx.xx
gh release create Vx.xx "Kidsnote_Memories_Saver_Vx.xx.exe" "Kidsnote_Release_Vx.xx.zip" \
  --title "..." --notes-file <릴리스노트> --latest
```

**두 파일을 모두 첨부**합니다.
- `...exe` — 기본 (압축 해제 없이 바로 실행)
- `...zip` — 임시폴더 경고가 뜨는 환경용 폴더판

---

## 6. 발행 후 확인

- [ ] 릴리스 페이지에 **자산 2개**가 모두 올라갔는가
- [ ] **Latest** 로 표시되는가
- [ ] 이전 버전 사용자에게 업데이트 알림이 가는가
      (앱이 시작할 때 GitHub 최신 태그와 `APP_VERSION` 을 비교합니다)
