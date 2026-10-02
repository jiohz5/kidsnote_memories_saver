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
# 브라우저를 못 띄우면 건너뛰되, 결과 줄에 반드시 드러나게 한다.
# 예전에는 건너뛰고도 'ALL PASSED' 를 찍어서, Edge가 업데이트되어 드라이버와
# 버전이 어긋난 동안 이 검사가 아무것도 안 했는데도 통과로 보였다.
skipped_reason = None
try:
    driver = make_driver()
    if driver is None:
        skipped_reason = "msedgedriver.exe 없음"
except Exception as e:
    skipped_reason = "Edge를 띄우지 못함(%s) - Edge와 드라이버 버전을 확인하세요" % type(e).__name__
    driver = None

if driver is None:
    print("\n[건너뜀] 브라우저 검사: %s" % skipped_reason)
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

        # 어느 아바타가 눌렸는지 기록이 남도록 심어 둔다 (문서 순서 번호)
        MARK_CLICKS = """
            window.__clicked = null;
            document.querySelectorAll("span[role='img']").forEach(function (s, i) {
              s.addEventListener('click', function () { window.__clicked = i; });
            });
        """

        print("\n== 아이 전환 ==")
        driver.get("data:text/html;charset=utf-8," + FAKE_PAGE)
        driver.execute_script(MARK_CLICKS)
        check("두 번째 아이를 찾아 누름", m.click_child(driver, '홍길순'), 'switched')
        check("실제로 눌린 것은 두 번째", driver.execute_script("return window.__clicked;"), 1)
        check("목록에 없는 이름은 notfound", m.click_child(driver, '없는아이'), 'notfound')

        print("\n== '이미 선택된 아이' 판정 ==")
        # 첫째 아이가 이미 선택되어(큰 아바타, size=65) 있는 화면
        ACTIVE_PAGE = """
        <html><body>
          <div><div><span role="img" size="65"></span></div>
               <div><p>홍길동</p><p>21.3.15.</p></div></div>
          <div><div><span role="img" size="36"></span></div>
               <div><p>홍길순</p><p>23.7.1.</p></div></div>
        </body></html>
        """
        driver.get("data:text/html;charset=utf-8," + ACTIVE_PAGE)
        driver.execute_script(MARK_CLICKS)
        check("반복 조회용: 이미 선택된 아이는 누르지 않음",
              m.click_child(driver, '홍길동', skip_if_active=True), 'already')
        check("  -> 실제로 아무것도 눌리지 않음",
              driver.execute_script("return window.__clicked;"), None)

        # 사용자가 직접 아이를 바꾸는 곳은 판정을 믿지 않고 항상 누른다.
        # 판정이 틀리면 다른 아이의 기록을 이 아이 이름으로 저장하게 되기 때문이다.
        check("직접 전환용: 이미 선택돼 있어도 누름",
              m.click_child(driver, '홍길동'), 'switched')
        check("  -> 실제로 눌림", driver.execute_script("return window.__clicked;"), 0)

        check("선택 안 된 아이는 반복 조회용이어도 누름",
              m.click_child(driver, '홍길순', skip_if_active=True), 'switched')
    finally:
        try:
            driver.quit()
        except Exception:
            pass

print()
if fails:
    print("RESULT: %d FAIL: %s" % (len(fails), fails))
    sys.exit(1)
if skipped_reason:
    print("RESULT: SKIPPED - 브라우저 검사를 하지 못함 (%s)" % skipped_reason)
    sys.exit(2)
print("RESULT: ALL PASSED")
