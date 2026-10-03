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


def run(cards, mem, url=FakeDriver.current_url, both=False, renav=None, overwrite=True,
        existing_pdf=False):
    """가짜 목록 화면에서 글 하나를 받아 본다.

    both 가 참이면 download_post 로 PDF·사진을 한 번에, 아니면 download_item 으로 사진만.
    renav 를 주면 '목록으로 다시 들어가기'가 그 카드들이 있는 화면을 띄운 것으로 친다.
    돌려주는 것: (결과, 누른 카드, 로그, 저장한 순서, 다시 들어간 횟수)
    """
    logs = []
    order = []
    renav_calls = []
    saved = {k: getattr(m, k) for k in ("download_photos_only", "download_as_pdf",
                                        "_sleep_with_stop", "save_debug_snapshot",
                                        "navigate_to_memory_view", "_watch_during_wait")}
    saved_sleep = m.time.sleep
    driver = FakeDriver(cards)
    driver.current_url = url

    def fake_renav(*a, **k):
        renav_calls.append(1)
        if renav is None:
            return False                 # 다시 들어가기 실패
        driver.cards = renav
        driver.current_url = m.SECTION_URLS[mem["type"]]
        return True

    m.download_photos_only = lambda *a, **k: order.append("사진") or True
    m.download_as_pdf = lambda *a, **k: order.append("PDF") or True
    m._sleep_with_stop = lambda s, cb=None, step=0.25: False
    m.save_debug_snapshot = lambda *a, **k: None
    m.navigate_to_memory_view = fake_renav
    m._watch_during_wait = lambda seconds, checks, cb: False   # 실제 시간을 기다리지 않는다
    m.time.sleep = lambda s: None
    try:
        if both:
            pdf = "C:/tmp/x.pdf"
            ok = m.download_post(driver, mem, pdf_path=pdf, media_dir="C:/tmp/x",
                                 status_callback=logs.append, is_overwrite_allow=overwrite)
        else:
            ok = m.download_item(driver, mem, "C:/tmp/x", False, status_callback=logs.append)
    finally:
        for k, v in saved.items():
            setattr(m, k, v)
        m.time.sleep = saved_sleep
    return ok, driver.clicked, logs, order, len(renav_calls)


LONG = "오늘은 친구들과 물놀이를 했어요. 다들 신나게 놀았답니다.\n다음 주에도 또 해요!"

print("\n== 목록에서 모은 글을 다시 찾아내는가 ==")
target = FakeCard("2026.7.14", LONG)
other = FakeCard("2026.7.14", "같은 날 다른 글")
ok, clicked, _l, _o, _r = run([other, target], mem_as_listed("2026.7.14", LONG))
check("찾아서 성공", ok, True)
check("날짜가 같아도 제목으로 맞는 글을 고름", clicked, [target])

print("\n== 키즈노트가 화면을 바꿔 예비 셀렉터로 읽어도 찾는가 ==")
# 예전에는 예비 셀렉터 쪽만 제목을 '...' 없이 잘라서, 이 상황에서 글을 못 찾았다
fallback_card = FakeCard("2026.7.14", LONG, primary_selector=False)
ok, clicked, _l, _o, _r = run([fallback_card], mem_as_listed("2026.7.14", LONG))
check("예비 셀렉터로도 찾음", clicked, [fallback_card])

print("\n== 날짜 표기가 달라도 같은 날이면 찾는가 ==")
card = FakeCard("2026년 7월 14일", "한글 날짜 글")
ok, clicked, _l, _o, _r = run([card], mem_as_listed("2026.07.14", "한글 날짜 글"))
check("'2026년 7월 14일' 카드 = '2026.07.14' 글", clicked, [card])

print("\n== 없는 글은 누르지 않는다 ==")
ok, clicked, logs, _o, _r = run([other], mem_as_listed("2026.7.14", LONG))
check("실패", ok, False)
check("아무것도 누르지 않음", clicked, [])

print("\n== 단계별 소요 측정 ==")
m.begin_download_stats()
for _ in range(4):
    _ok, _c, logs, _o, _r = run([target], mem_as_listed("2026.7.14", LONG))
detail = [x for x in logs if "[KN-DIAG] 소요 다운로드 #" in x]
summary = m.end_download_stats()
check("4건째에는 한 줄씩 기록하지 않음 (처음 3건만)", detail, [])
check("요약에 건수가 들어감", "| 4건 |" in summary, True)
check("요약에 '바로 찾음' 횟수가 들어감", "바로 4" in summary, True)

m.begin_download_stats()
_ok, _c, logs, _o, _r = run([target], mem_as_listed("2026.7.14", LONG))
check("첫 건은 한 줄로 기록", any("[KN-DIAG] 소요 다운로드 #1" in x for x in logs), True)
check("다시 시작하면 측정을 비움", "| 1건 |" in m.end_download_stats(), True)

m.begin_download_stats()
check("받은 것이 없으면 요약도 없음", m.end_download_stats(), "")

print("\n== [PDF+사진] 은 한 번 열어 함께 저장 ==")
ok, clicked, _l, order, _r = run([target], mem_as_listed("2026.7.14", LONG), both=True)
check("둘 다 성공", ok, (True, True))
check("글은 한 번만 누름", clicked, [target])
# PDF 저장이 댓글을 펼쳐 화면을 바꾸므로 사진을 먼저 고른다
check("사진 먼저, PDF 나중", order, ["사진", "PDF"])

print("\n== 이미 있는 것은 건너뛴다 (덮어쓰기 안 함) ==")
import tempfile
_tmp = tempfile.mkdtemp(prefix="kn_dlitem_")
_pdf = os.path.join(_tmp, "x.pdf")
open(_pdf, "wb").close()
_saved = m.download_photos_only, m.download_as_pdf
_order = []
m.download_photos_only = lambda *a, **k: _order.append("사진") or True
m.download_as_pdf = lambda *a, **k: _order.append("PDF") or True
try:
    _drv = FakeDriver([target])
    _old_sleep = m.time.sleep
    m.time.sleep = lambda s: None
    _old_watch = m._watch_during_wait
    m._watch_during_wait = lambda s, c, cb: False
    _old_sws = m._sleep_with_stop
    m._sleep_with_stop = lambda s, cb=None, step=0.25: False
    try:
        res = m.download_post(_drv, mem_as_listed("2026.7.14", LONG), pdf_path=_pdf,
                              media_dir=_tmp, is_overwrite_allow=False)
    finally:
        m.time.sleep, m._watch_during_wait, m._sleep_with_stop = _old_sleep, _old_watch, _old_sws
finally:
    m.download_photos_only, m.download_as_pdf = _saved
check("있는 PDF 는 건너뛰고 사진만 받음", _order, ["사진"])
check("결과는 둘 다 성공", res, (True, True))

open(os.path.join(_tmp, m._media_prefix(mem_as_listed("2026.7.14", LONG)) + "_1.jpg"), "wb").close()
_drv = FakeDriver([target])
res = m.download_post(_drv, mem_as_listed("2026.7.14", LONG), pdf_path=_pdf,
                      media_dir=_tmp, is_overwrite_allow=False)
check("둘 다 이미 있으면 글을 열지도 않음", _drv.clicked, [])
check("  -> 성공으로 처리", res, (True, True))

print("\n== 다른 종류 목록에서 헛되이 찾지 않는다 ==")
# 앨범 목록이 떠 있는데 알림장 글을 찾는 상황. 예전에는 이 화면과 다음 두 페이지를
# 뒤진 뒤에야 다시 들어갔다 (실측 6.9초).
report_mem = dict(mem_as_listed("2026.7.14", LONG), type="알림장")
ok, clicked, _l, _o, renav = run([target], report_mem,
                                 url=m.SECTION_URLS["앨범"], renav=[target])
check("곧장 알림장 목록으로 다시 들어감", renav, 1)
check("다시 들어간 화면에서 찾아 누름", clicked, [target])

ok, clicked, _l, _o, renav = run([target], mem_as_listed("2026.7.14", LONG),
                                 url=m.SECTION_URLS["앨범"])
check("같은 종류 목록이면 다시 들어가지 않음", renav, 0)

ok, clicked, _l, _o, renav = run([target], report_mem, url="https://www.kidsnote.com/service",
                                 renav=[target])
check("어느 목록인지 모르는 화면이면 예전처럼 먼저 찾아봄", clicked, [target])
check("  -> 찾았으니 다시 들어가지 않음", renav, 0)

print("\n== 고정 대기의 효과 기록 ==")
m.begin_download_stats()
m._note_wait("시험 대기", (100, 2000, 5, 2), (100, 2000, 5, 2))   # 아무것도 안 바뀜
m._note_wait("시험 대기", (100, 2000, 5, 2), (100, 2000, 5, 0))   # 이미지가 다 받아짐
m._note_wait("시험 대기", (100, 2000, 5, 0), (180, 2600, 5, 0))   # 글이 늘어남
m._note_moment("시험 전환", 0.3)
m._note_moment("시험 전환", 0.5)
m._note_count("시험 횟수", 3)
m._record_download_timing("바로", 0.1, 2.0, 4.0, 1.5, lambda x: None)
lines = m.end_download_stats().split("\n")
check("요약이 여러 줄이고 줄마다 진단 표시", all(l.startswith("[KN-DIAG]") for l in lines), True)
check("대기 효과: 3번 중 2번 변화", any("시험 대기: 3번 중 2번 변화" in l for l in lines), True)
check("전환 시점: 평균 0.4초 최대 0.5초", any("시험 전환 평균 0.4초 최대 0.5초 (2번)" in l for l in lines), True)
check("횟수 기록", any("시험 횟수 3" in l for l in lines), True)

print("\n== 고정 대기 중 전환 시점 재기 ==")
m.begin_download_stats()
_start = m.time.time()
_flag = {"n": 0}
def _becomes_true():
    _flag["n"] += 1
    return _flag["n"] >= 3
stopped = m._watch_during_wait(0.5, {"곧 일어남": _becomes_true, "안 일어남": lambda: False}, None)
_took = m.time.time() - _start
check("기다리는 시간은 그대로 (0.5초)", 0.45 <= _took < 1.0, True)
check("중지 아님", stopped, False)
_lines = m.end_download_stats()   # 다운로드 건수가 0이라 요약 문자열은 비지만 기록은 남았다
check("일어난 시점 기록", len(m._dl_stats["moments"].get("곧 일어남", [])), 1)
check("끝내 안 일어난 것도 셈", m._dl_stats["counts"].get("안 일어남 안 일어남"), 1)
stopped = m._watch_during_wait(5, {}, lambda: True)
check("중지 요청이 오면 바로 멈춤", stopped, True)

print()
if fails:
    print("RESULT: %d FAIL: %s" % (len(fails), fails))
    sys.exit(1)
print("RESULT: ALL PASSED")
