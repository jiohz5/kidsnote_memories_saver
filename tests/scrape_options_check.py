# -*- coding: utf-8 -*-
"""조회 요청/콜백 묶음과 조회 재시도 동작 검증.

브라우저 없이 가짜 드라이버로 돌린다. 확인하려는 것은 두 가지다.
  - 요청서(ScrapeRequest)에 적은 대로 알림장/앨범을 고르는가
  - 목록에 못 들어갔을 때 조용히 0건으로 끝내지 않고 다시 시도하는가

두 번째가 중요하다. 실제로 앨범 진입에 실패해 0건으로 끝난 적이 있는데,
사용자에게는 '앨범이 없다'와 구분되지 않았다.
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
    """아무것도 없는 화면인 척한다."""
    current_url = "https://www.kidsnote.com/service"

    def get(self, url):
        self.current_url = url

    def execute_script(self, *a, **k):
        return None

    def find_elements(self, *a, **k):
        return []

    def find_element(self, *a, **k):
        raise Exception("없음")

    def set_page_load_timeout(self, *a):
        pass


def run_fetch(request, nav_ok=False, found=0):
    """엔진의 목록 조회를 가짜 환경에서 돌리고, 로그와 진입 시도 기록을 돌려준다.

    found 는 목록에서 찾은 것으로 칠 게시물 수다. 0이면 '한 건도 못 봤다'는 뜻이라
    엔진이 조회 실패로 의심해 다시 시도한다.
    """
    logs = []
    attempts = []

    def fake_nav(driver, label, log_func, target_child=None):
        attempts.append(label)
        if not nav_ok:
            log_func("%s 전체보기 버튼을 찾지 못했습니다." % label)
        return nav_ok

    def fake_scrape(driver, item_type, memories, log, request=None,
                    callbacks=None, result_info=None):
        for i in range(found):
            memories.append({'type': item_type, 'title': '글%d' % i,
                             'date': '2026.09.01', 'id': '%s-%d' % (item_type, i)})
        if isinstance(result_info, dict):
            result_info['items_seen'] = found
            result_info['list_loaded'] = True

    saved = (m.navigate_to_memory_view, m._detect_kidsnote_app_error,
             m.wait_css, m._is_on_service_home, m._scrape_list_pages)
    m.navigate_to_memory_view = fake_nav
    m._detect_kidsnote_app_error = lambda d: False
    m.wait_css = lambda *a, **k: True
    m._is_on_service_home = lambda d: True
    m._scrape_list_pages = fake_scrape
    try:
        memories = m.fetch_memory_list(
            FakeDriver(), request=request,
            callbacks=m.ScrapeCallbacks(status=logs.append))
    finally:
        (m.navigate_to_memory_view, m._detect_kidsnote_app_error,
         m.wait_css, m._is_on_service_home, m._scrape_list_pages) = saved
    return logs, attempts, memories


print("\n== 요청서 ==")
check("기본은 둘 다 조회", m.ScrapeRequest().labels, ["알림장", "앨범"])
check("알림장만", m.ScrapeRequest(albums=False).labels, ["알림장"])
check("앨범만", m.ScrapeRequest(reports=False).labels, ["앨범"])
check("아무것도 안 고르면 빈 목록",
      m.ScrapeRequest(reports=False, albums=False).labels, [])

r = m.ScrapeRequest(start_date="2026.03.01", end_date="2026.09.10")
check("기간이 그대로 담김", (r.start_date, r.end_date), ("2026.03.01", "2026.09.10"))
check("기간을 안 주면 전체", (m.ScrapeRequest().start_date, m.ScrapeRequest().end_date),
      (None, None))

print("\n== 콜백 묶음 ==")
cb = m.ScrapeCallbacks()
check("아무것도 안 주면 중지 아님", cb.stopped(), False)
check("중지 함수가 True면 중지", m.ScrapeCallbacks(check_stop=lambda: True).stopped(), True)
check("중지 함수가 False면 진행", m.ScrapeCallbacks(check_stop=lambda: False).stopped(), False)

print("\n== 요청서대로 대상을 고르는가 ==")
_l, attempts, _m = run_fetch(m.ScrapeRequest(albums=False), nav_ok=True, found=2)
check("알림장만 요청하면 앨범은 건드리지 않음", set(attempts), {"알림장"})

_l, attempts, _m = run_fetch(m.ScrapeRequest(reports=False), nav_ok=True, found=2)
check("앨범만 요청하면 알림장은 건드리지 않음", set(attempts), {"앨범"})

_l, attempts, mems = run_fetch(m.ScrapeRequest(), nav_ok=True, found=2)
check("둘 다 요청하면 둘 다 시도", set(attempts), {"알림장", "앨범"})
check("찾은 것이 모두 모여 나옴", len(mems), 4)
check("유형이 섞이지 않음", sorted({x['type'] for x in mems}), ["알림장", "앨범"])

print("\n== 조용히 0건으로 끝내지 않는가 ==")
# 실제로 앨범 진입에 실패해 0건으로 끝난 적이 있다. 사용자에게 그것은
# '앨범이 없다'와 구분되지 않으므로, 의심스러우면 다시 시도해야 한다.
_l, attempts, _m = run_fetch(m.ScrapeRequest(reports=False), nav_ok=False)
check("진입 실패 시 여러 번 시도", len(attempts) >= 2, True)
check("모두 앨범에 대한 시도", set(attempts), {"앨범"})

_l, attempts, _m = run_fetch(m.ScrapeRequest(reports=False), nav_ok=True, found=0)
check("들어갔는데 한 건도 못 보면 다시 시도", len(attempts) >= 2, True)

_l, attempts, _m = run_fetch(m.ScrapeRequest(reports=False), nav_ok=True, found=3)
check("제대로 가져오면 한 번만", len(attempts), 1)

print()
if fails:
    print("RESULT: %d FAIL: %s" % (len(fails), fails))
    sys.exit(1)
print("RESULT: ALL PASSED")
