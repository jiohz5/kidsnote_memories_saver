# -*- coding: utf-8 -*-
"""목록 진입(navigate_to_memory_view)이 실제로 어떻게 움직이는지 확인한다.

예전 tests/menu_entry_check.py 는 운영 코드에서 이미 지운 판단 함수를
테스트 안에 다시 구현해 그것을 검사하고 있었다. 통과는 하지만 아무것도
지켜 주지 않는 테스트였으므로 지우고, 이번에는 진짜 함수를 가짜 브라우저로 돌린다.

지키려는 것:
  - 아이를 바꿀 필요가 없으면 홈을 거치지 않고 목록 주소로 곧장 간다 (속도)
  - 알림장은 알림장 주소로, 앨범은 앨범 주소로 간다 (섞이면 조용한 오염)
  - 목록이 뜨면 성공, 키즈노트 오류 화면이나 시간 초과면 실패를 돌려준다
  - 로그인이 풀려 엉뚱한 곳에 떨어지면 진단 기록을 남긴다
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import kidsnote_engine as m  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want
    print("[%s] %s" % ("PASS" if ok else "FAIL", name), end="")
    print("" if ok else "\n        기대=%r\n        실제=%r" % (want, got))
    if not ok:
        fails.append(name)


class FakeDriver(object):
    """방문한 주소를 기록한다. redirect 가 있으면 그 주소로 떨어진 척한다."""

    def __init__(self, start="https://www.kidsnote.com/service/report", redirect=None):
        self.current_url = start
        self.visited = []
        self.redirect = redirect

    def get(self, url):
        self.visited.append(url)
        self.current_url = self.redirect or url

    def execute_script(self, *a, **k):
        return True

    def find_elements(self, *a, **k):
        return []


def run(label, outcome='items', redirect=None, target_child=None):
    logs = []
    saved = (m._wait_for_list_or_app_error, m.wait_css, m._is_on_service_home, m.time.sleep)
    m._wait_for_list_or_app_error = lambda d, timeout=30, poll=0.25: outcome
    m.wait_css = lambda *a, **k: True
    m._is_on_service_home = lambda d: "/service/" not in d.current_url
    m.time.sleep = lambda s: None
    try:
        driver = FakeDriver(redirect=redirect)
        ok = m.navigate_to_memory_view(driver, label, logs.append, target_child=target_child)
    finally:
        (m._wait_for_list_or_app_error, m.wait_css, m._is_on_service_home, m.time.sleep) = saved
    return ok, driver.visited, logs


print("\n== 목록 주소로 곧장 간다 ==")
ok, visited, _ = run("알림장")
check("알림장은 알림장 주소로", visited, [m.SECTION_URLS["알림장"]])
check("목록이 뜨면 성공", ok, True)

ok, visited, _ = run("앨범")
check("앨범은 앨범 주소로", visited, [m.SECTION_URLS["앨범"]])
check("홈(/service)을 거치지 않음", "https://www.kidsnote.com/service" in visited, False)

print("\n== 아이를 바꿔야 할 때만 홈을 거친다 ==")
ok, visited, _ = run("앨범", target_child="홍길동")
check("홈에 들렀다가", "https://www.kidsnote.com/service" in visited, True)
check("마지막에는 앨범 주소", visited[-1], m.SECTION_URLS["앨범"])

print("\n== 실패는 실패로 알린다 ==")
ok, _v, logs = run("앨범", outcome='error')
check("키즈노트 오류 화면이면 실패", ok, False)
check("오류 화면이라고 알림", any("오류 화면" in x for x in logs), True)

ok, _v, logs = run("알림장", outcome='timeout')
check("시간 초과면 실패", ok, False)

print("\n== 엉뚱한 곳에 떨어지면 기록한다 ==")
_ok, _v, logs = run("앨범", redirect="https://www.kidsnote.com/login")
check("로그인 화면으로 튕기면 진단 기록",
      any("[KN-DIAG]" in x and "목록이 아닌 곳" in x for x in logs), True)

_ok, _v, logs = run("앨범")
check("정상이면 그런 기록 없음", any("목록이 아닌 곳" in x for x in logs), False)

print()
if fails:
    print("RESULT: %d FAIL: %s" % (len(fails), fails))
    sys.exit(1)
print("RESULT: ALL PASSED")
