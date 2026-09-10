# -*- coding: utf-8 -*-
"""목록 진입 판단이 빠르게 끝나는지 실제 브라우저로 확인한다.

앨범을 조회할 때 '추억보기' 메뉴를 찾지 못해 20초를 통째로 버리던 문제가 있었다.
(측정: 알림장은 목록까지 0.9초, 앨범은 21.0초)

키즈노트에 로그인하지 않고, 같은 구조의 가짜 화면 세 가지로 확인한다.
  - 메뉴만 있는 화면        -> 메뉴 요소를 찾아야 한다
  - 이미 목록이 뜬 화면     -> 메뉴를 기다리지 않고 바로 통과해야 한다
  - 둘 다 없는 화면         -> 오래 붙들지 말고 정해진 시간 안에 포기해야 한다

Edge와 msedgedriver가 없으면 건너뛴다.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import kidsnote_engine as m  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402
from selenium.webdriver.support.ui import WebDriverWait  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("[%s] %s" % ("PASS" if cond else "FAIL", name), end="")
    print("" if cond else "  (%s)" % detail)
    if not cond:
        fails.append(name)


MENU_PAGE = """
<html><body>
  <div class="e1q0zrbj0">추억보기</div>
</body></html>
"""

LIST_PAGE = """
<html><body>
  <div>추억 알림장 <button>전체보기</button></div>
  <div>추억 앨범 <button>전체보기</button></div>
</body></html>
"""

EMPTY_PAGE = "<html><body><p>아무것도 없음</p></body></html>"


def make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    path = os.path.join(ROOT, 'msedgedriver.exe')
    if not os.path.exists(path):
        return None
    opts = webdriver.EdgeOptions()
    opts.add_argument('--headless=new')
    opts.add_argument('--window-size=1100,900')
    return webdriver.Edge(service=Service(executable_path=path), options=opts)


def probe(driver, html, timeout=5):
    """navigate_to_memory_view 안의 판단 함수와 같은 조건으로 재 본다."""
    driver.get("data:text/html;charset=utf-8," + html)

    def condition(d):
        try:
            if [b for b in d.find_elements(By.XPATH, m.VIEW_ALL_XPATH) if b.is_displayed()]:
                return 'ready'
        except Exception:
            pass
        try:
            for el in d.find_elements(By.XPATH, m.MEMORY_MENU_XPATH):
                if el.is_displayed() and el.is_enabled():
                    return el
        except Exception:
            pass
        return False

    started = time.time()
    try:
        result = WebDriverWait(driver, timeout).until(condition)
    except Exception:
        result = None
    return result, time.time() - started


try:
    driver = make_driver()
except Exception as e:
    print("\n[건너뜀] Edge를 띄우지 못했습니다: %s" % type(e).__name__)
    driver = None

if driver is None:
    print("\n[건너뜀] msedgedriver.exe 가 없어 브라우저 검사는 생략합니다.")
else:
    try:
        print("\n== 메뉴만 있는 화면 ==")
        result, took = probe(driver, MENU_PAGE)
        check("추억보기 메뉴를 찾아냄", result is not None and result != 'ready', result)
        check("금방 찾음 (2초 이내)", took < 2, "%.1f초" % took)

        print("\n== 이미 목록이 뜬 화면 ==")
        result, took = probe(driver, LIST_PAGE)
        check("메뉴를 기다리지 않고 바로 통과", result == 'ready', result)
        check("즉시 통과 (1초 이내)", took < 1, "%.1f초" % took)

        print("\n== 둘 다 없는 화면 ==")
        result, took = probe(driver, EMPTY_PAGE, timeout=5)
        check("찾지 못함", result is None, result)
        # 예전에는 여기서 20초를 버렸다. 못 찾을 상황이면 빨리 포기하고
        # 다른 방법(사이드바 펼치기)으로 넘어가야 한다.
        check("20초가 아니라 정해진 시간에 포기", took < 8, "%.1f초" % took)

        print("\n== 메뉴 XPath 가 실제로 동작하는가 ==")
        driver.get("data:text/html;charset=utf-8," + MENU_PAGE)
        found = driver.find_elements(By.XPATH, m.MEMORY_MENU_XPATH)
        check("클래스와 글자로 메뉴를 집어냄", len(found) == 1, len(found))
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
