# -*- coding: utf-8 -*-
"""엔진의 로그인·아이목록 함수를 실제 브라우저로 검증한다.

키즈노트에 로그인하지 않는다. 같은 구조의 가짜 페이지를 띄워 놓고,
엔진이 거기서 이름·나이·얼굴사진 주소를 제대로 읽어 내는지 본다.

자바스크립트는 파이썬이 문법을 봐 주지 않으므로 한 번은 실제로 실행해 봐야 한다.
셀렉터를 손볼 때 이 테스트가 먼저 깨지면, 사용자가 겪기 전에 알 수 있다.

Edge와 msedgedriver가 필요하다. 없으면 건너뛴다(성공으로 처리).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import kidsnote_engine as m  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want
    print("[%s] %s" % ("PASS" if ok else "FAIL", name), end="")
    print("" if ok else "\n        기대=%r\n        실제=%r" % (want, got))
    if not ok:
        fails.append(name)


# 키즈노트 아이 목록과 같은 구조. 작은 아바타 옆에 이름/나이가 p 태그로 있고,
# 선택된 아이의 큰 아바타에 얼굴 사진이 배경으로 깔린다.
FAKE_PAGE = """
<html><body>
  <div>
    <div><span role="img" size="36"></span></div>
    <div><p>홍길동</p><p>21.3.15. (5년 5개월)</p></div>
  </div>
  <div>
    <div><span role="img" size="36"></span></div>
    <div><p>홍길순</p><p>23.7.1. (3년 2개월)</p></div>
  </div>
  <span role="img" size="65"
        style="background-image:url('https://example.invalid/a/img_65x65.jpg');
               width:65px;height:65px;display:inline-block"></span>
</body></html>
"""

EMPTY_PAGE = "<html><body><p>아이 없음</p></body></html>"


def make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    driver_path = os.path.join(ROOT, 'msedgedriver.exe')
    if not os.path.exists(driver_path):
        return None
    opts = webdriver.EdgeOptions()
    opts.add_argument('--headless=new')
    opts.add_argument('--window-size=1100,900')
    return webdriver.Edge(service=Service(executable_path=driver_path), options=opts)


# ------------------------------------------------- 브라우저 없이 되는 검사
print("\n== 썸네일 주소 확대 ==")
check("작은 썸네일은 큰 것으로",
      m.upgrade_thumbnail_url('http://x/img_65x65.jpg'), 'http://x/img_240x240.jpg')
check("36 크기도 마찬가지",
      m.upgrade_thumbnail_url('http://x/img_36x36.jpg'), 'http://x/img_240x240.jpg')
check("크기를 지정할 수 있음",
      m.upgrade_thumbnail_url('http://x/img_65x65.jpg', 480), 'http://x/img_480x480.jpg')
check("해당 없는 주소는 그대로",
      m.upgrade_thumbnail_url('http://x/photo.jpg'), 'http://x/photo.jpg')
check("빈 주소도 예외 없이", m.upgrade_thumbnail_url(''), '')
check("None도 예외 없이", m.upgrade_thumbnail_url(None), None)

# ------------------------------------------------- 실제 브라우저가 필요한 검사
try:
    driver = make_driver()
except Exception as e:
    print("\n[건너뜀] Edge를 띄우지 못해 브라우저 검사는 생략합니다: %s" % type(e).__name__)
    driver = None

if driver is None:
    print("\n[건너뜀] msedgedriver.exe 가 없어 브라우저 검사는 생략합니다.")
else:
    try:
        print("\n== 아이 목록 읽기 (가짜 페이지) ==")
        driver.get("data:text/html;charset=utf-8," + FAKE_PAGE)

        names = driver.execute_script(m._CHILD_NAMES_JS)
        check("이름과 나이를 짝지어 읽음", names,
              [['홍길동', '21.3.15. (5년 5개월)'], ['홍길순', '23.7.1. (3년 2개월)']])

        url = driver.execute_script(m._ACTIVE_AVATAR_URL_JS)
        check("선택된 아이의 얼굴 사진 주소를 읽음",
              url, 'https://example.invalid/a/img_65x65.jpg')
        check("그 주소를 큰 해상도로 바꿈",
              m.upgrade_thumbnail_url(url), 'https://example.invalid/a/img_240x240.jpg')

        print("\n== 아이가 없는 화면에서도 죽지 않는가 ==")
        driver.get("data:text/html;charset=utf-8," + EMPTY_PAGE)
        check("이름 목록은 빈 목록", driver.execute_script(m._CHILD_NAMES_JS), [])
        check("얼굴 사진 주소는 빈 문자열", driver.execute_script(m._ACTIVE_AVATAR_URL_JS), "")

        print("\n== 아이 전환 ==")
        driver.get("data:text/html;charset=utf-8," + FAKE_PAGE)
        # 클릭되었는지 표시가 남도록 심어 둔다
        driver.execute_script("""
            window.__clicked = null;
            document.querySelectorAll("span[role='img'][size='36']").forEach(function (s, i) {
              s.addEventListener('click', function () { window.__clicked = i; });
            });
        """)
        found = driver.execute_script(m._SELECT_CHILD_JS, '홍길순')
        check("두 번째 아이를 찾아 누름", bool(found), True)
        check("실제로 눌린 것은 두 번째", driver.execute_script("return window.__clicked;"), 1)

        found = driver.execute_script(m._SELECT_CHILD_JS, '없는아이')
        check("목록에 없는 이름은 False", bool(found), False)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

print()
if fails:
    print("RESULT: %d FAIL: %s" % (len(fails), fails))
    sys.exit(1)
print("RESULT: ALL PASSED")
