# -*- coding: utf-8 -*-
"""내려받을 글 찾기(download_item)와 단계별 소요 측정을 가짜 브라우저로 확인한다.

지금까지 수집된 글은 전부 주소가 없다(기록 1625건 모두 'None'). 그래서 내려받을 때
목록으로 돌아가 '날짜+제목이 같은 카드'를 찾아 누른다. 목록에서 글을 모을 때 만든
날짜·제목과 여기서 카드를 읽어 만든 날짜·제목이 한 글자라도 다르면 글을 못 찾는다.

예전에는 두 곳이 각자 날짜와 제목을 만들었고, 예비 셀렉터 쪽 제목 규칙이 서로
어긋나 있었다. 이 테스트는 두 곳이 같은 함수를 거치는지를 실제 흐름으로 확인한다.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import kidsnote_engine as m  # noqa: E402
import kidsnote_paths as p  # noqa: E402
from selenium.common.exceptions import NoSuchElementException  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want
    print("[%s] %s" % ("PASS" if ok else "FAIL", name), end="")
    print("" if ok else "\n        기대=%r\n        실제=%r" % (want, got))
    if not ok:
        fails.append(name)


class Text(object):
    def __init__(self, text):
        self.text = text


class FakeCard(object):
    """목록의 게시물 카드. 주소 링크는 없다 (실제로도 없었다)."""

    def __init__(self, raw_date, body, primary_selector=True):
        self.raw_date = raw_date
        self.body = body
        self.primary = primary_selector

    def find_element(self, by, value):
        if value == m.CARD_DATE_XPATH:
            return Text(self.raw_date)
        if value == m.CARD_BODY_XPATH:
            if not self.primary:
                raise NoSuchElementException("키즈노트가 화면을 바꾼 상황")
            return Text(self.body)
        if value == m.CARD_BODY_CLASS:
            return Text(self.body)
        raise NoSuchElementException(value)


class FakeDriver(object):
    current_url = "https://www.kidsnote.com/service/album"

    def __init__(self, cards):
        self.cards = cards
        self.clicked = []

    def find_elements(self, by=None, value=None):
        return list(self.cards) if value == m.post_card_xpath() else []

    def execute_script(self, script, *args):
        if "click" in script and args:
            self.clicked.append(args[0])
        return None

    def back(self):
        pass


def mem_as_listed(raw_date, body):
    """목록 수집 쪽이 이 카드로 만들었을 글 정보 (같은 함수를 거친다)."""
    return {"date": p.normalize_list_date(raw_date), "title": m.format_list_title(body),
            "type": "앨범", "url": None, "page": 1, "child_name": "홍길동"}


def run(cards, mem):
    logs = []
    saved = {k: getattr(m, k) for k in ("download_photos_only", "_sleep_with_stop",
                                        "save_debug_snapshot", "navigate_to_memory_view")}
    saved_sleep = m.time.sleep
    m.download_photos_only = lambda *a, **k: True
    m._sleep_with_stop = lambda s, cb=None, step=0.25: False
    m.save_debug_snapshot = lambda *a, **k: None
    m.navigate_to_memory_view = lambda *a, **k: False   # 재진입은 실패한 것으로
    m.time.sleep = lambda s: None
    try:
        driver = FakeDriver(cards)
        ok = m.download_item(driver, mem, "C:/tmp/x", False, status_callback=logs.append)
    finally:
        for k, v in saved.items():
            setattr(m, k, v)
        m.time.sleep = saved_sleep
    return ok, driver.clicked, logs


LONG = "오늘은 친구들과 물놀이를 했어요. 다들 신나게 놀았답니다.\n다음 주에도 또 해요!"

print("\n== 목록에서 모은 글을 다시 찾아내는가 ==")
target = FakeCard("2026.7.14", LONG)
other = FakeCard("2026.7.14", "같은 날 다른 글")
ok, clicked, _ = run([other, target], mem_as_listed("2026.7.14", LONG))
check("찾아서 성공", ok, True)
check("날짜가 같아도 제목으로 맞는 글을 고름", clicked, [target])

print("\n== 키즈노트가 화면을 바꿔 예비 셀렉터로 읽어도 찾는가 ==")
# 예전에는 예비 셀렉터 쪽만 제목을 '...' 없이 잘라서, 이 상황에서 글을 못 찾았다
fallback_card = FakeCard("2026.7.14", LONG, primary_selector=False)
ok, clicked, _ = run([fallback_card], mem_as_listed("2026.7.14", LONG))
check("예비 셀렉터로도 찾음", clicked, [fallback_card])

print("\n== 날짜 표기가 달라도 같은 날이면 찾는가 ==")
card = FakeCard("2026년 7월 14일", "한글 날짜 글")
ok, clicked, _ = run([card], mem_as_listed("2026.07.14", "한글 날짜 글"))
check("'2026년 7월 14일' 카드 = '2026.07.14' 글", clicked, [card])

print("\n== 없는 글은 누르지 않는다 ==")
ok, clicked, logs = run([other], mem_as_listed("2026.7.14", LONG))
check("실패", ok, False)
check("아무것도 누르지 않음", clicked, [])

print("\n== 단계별 소요 측정 ==")
m.begin_download_stats()
for _ in range(4):
    _ok, _c, logs = run([target], mem_as_listed("2026.7.14", LONG))
detail = [x for x in logs if "[KN-DIAG] 소요 다운로드 #" in x]
summary = m.end_download_stats()
check("4건째에는 한 줄씩 기록하지 않음 (처음 3건만)", detail, [])
check("요약에 건수가 들어감", "| 4건 |" in summary, True)
check("요약에 '바로 찾음' 횟수가 들어감", "바로 4" in summary, True)

m.begin_download_stats()
_ok, _c, logs = run([target], mem_as_listed("2026.7.14", LONG))
check("첫 건은 한 줄로 기록", any("[KN-DIAG] 소요 다운로드 #1" in x for x in logs), True)
check("다시 시작하면 측정을 비움", "| 1건 |" in m.end_download_stats(), True)

m.begin_download_stats()
check("받은 것이 없으면 요약도 없음", m.end_download_stats(), "")

print()
if fails:
    print("RESULT: %d FAIL: %s" % (len(fails), fails))
    sys.exit(1)
print("RESULT: ALL PASSED")
