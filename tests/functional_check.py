# -*- coding: utf-8 -*-
"""Qt 버전과 무관하게 통과해야 하는 핵심 동작 검증.

Qt5 -> Qt6 전환 전후로 같은 결과가 나오는지 확인하는 용도.
로그인/네트워크 없이 오프스크린으로 실행된다.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PyQt6 import QtWidgets, QtCore, QtGui   # noqa
import kidsnote_saver as ks

fails = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        fails.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
w = ks.KidsnoteApp()
w.show()
app.processEvents()

# ── 1. 기간 프리셋 ────────────────────────────────────────────
today = QtCore.QDate.currentDate()
w.period_combo.setCurrentText("최근 1주일")
check("기간 프리셋: 시작일 = 오늘-7", w.start_date_edit.date() == today.addDays(-7))
check("기간 프리셋에서도 날짜칸은 선택 가능", w.start_date_edit.isEnabled())

# 이번 학년도: 어린이집·유치원의 한 해는 3월에 시작한다.
# 1~2월에 올해 3월을 쓰면 아직 오지 않은 날짜가 되어 조회가 0건이 된다.
w.period_combo.setCurrentText("이번 학년도 (3월~)")
app.processEvents()
check("학년도 프리셋: 3월 1일부터",
      w.start_date_edit.date() == ks.KidsnoteApp._academic_year_start(today),
      w.start_date_edit.date().toString("yyyy.MM.dd"))
for probe, want_year in ((QtCore.QDate(2026, 9, 10), 2026),
                         (QtCore.QDate(2026, 3, 1), 2026),
                         (QtCore.QDate(2026, 2, 28), 2025),
                         (QtCore.QDate(2026, 1, 5), 2025)):
    got = ks.KidsnoteApp._academic_year_start(probe)
    check("학년도 시작 %s -> %d.03.01" % (probe.toString("yyyy.MM.dd"), want_year),
          got == QtCore.QDate(want_year, 3, 1), got.toString("yyyy.MM.dd"))
w.period_combo.setCurrentText("직접 지정")
check("직접 지정: 날짜칸 활성", w.start_date_edit.isEnabled())

# 달력에서 날짜를 직접 고르면 기간이 '직접 지정'으로 전환되고 그 날짜가 유지되어야 한다
w.period_combo.setCurrentText("최근 1주일")
app.processEvents()
w.start_date_edit.setDate(QtCore.QDate(2025, 5, 5))
app.processEvents()
check("날짜 직접 선택 시 '직접 지정'으로 전환", w.period_combo.currentText().startswith("직접"),
      w.period_combo.currentText())
check("직접 고른 날짜가 유지됨", w.start_date_edit.date() == QtCore.QDate(2025, 5, 5),
      w.start_date_edit.date().toString("yyyy.MM.dd"))
w.period_combo.setCurrentText("최근 1개월")
app.processEvents()
check("프리셋 재선택 시 다시 계산됨", w.start_date_edit.date() == today.addDays(-30))
w.period_combo.setCurrentText("전체")
check("전체: _period_desc", w._period_desc() == "전체", w._period_desc())

# ── 2. 표: 삽입 / 체크 / 정렬 ─────────────────────────────────
mems = [
    {"id": "a", "date": "2026.03.01", "title": "최신글", "type": "알림장", "writer": "엄마", "has_photo": "O", "url": None, "child_name": "아이1"},
    {"id": "b", "date": "2026.01.15", "title": "오래된글", "type": "앨범", "writer": "교사", "has_photo": "X", "url": None, "child_name": "아이1"},
    {"id": "c", "date": "2026.02.10", "title": "중간글", "type": "알림장", "writer": "아빠", "has_photo": "O", "url": None, "child_name": "아이1"},
]
for m in mems:
    w.add_memory_to_table(dict(m))
check("표: 3행 삽입", w.table.rowCount() == 3)


def row_of(title):
    for r in range(w.table.rowCount()):
        it = w.table.item(r, 2)
        if it and it.text() == title:
            return r
    return -1


checked_state = QtCore.Qt.CheckState.Checked
unchecked_state = QtCore.Qt.CheckState.Unchecked

w.table.item(row_of("오래된글"), 0).setCheckState(unchecked_state)
w.table.sortItems(1, QtCore.Qt.SortOrder.AscendingOrder)
order = [w.table.item(r, 1).text() for r in range(3)]
check("정렬: 날짜 오름차순", order == ["2026.01.15", "2026.02.10", "2026.03.01"], str(order))
check("정렬: 체크 해제가 행을 따라감",
      w.table.item(row_of("오래된글"), 0).checkState() == unchecked_state)

# 선택 컬럼 정렬 (PyQt6에서 int() 불가로 깨지기 쉬운 지점)
w.table.sortItems(0, QtCore.Qt.SortOrder.AscendingOrder)
states = [w.table.item(r, 0).checkState() for r in range(3)]
check("정렬: 선택 컬럼 기준 정렬 동작", states[0] == unchecked_state and states[-1] == checked_state,
      str([s.name if hasattr(s, 'name') else s for s in states]))

# ── 3. 선택 조작 ──────────────────────────────────────────────
w.select_all()
check("전체 선택", all(w.table.item(r, 0).checkState() == checked_state for r in range(3)))
w.deselect_all()
check("전체 해제", all(w.table.item(r, 0).checkState() == unchecked_state for r in range(3)))
w.downloaded_ids.add("a")
w.select_new_only()
check("새 항목만 선택: 받은 항목 제외", w.table.item(row_of("최신글"), 0).checkState() == unchecked_state)
check("새 항목만 선택: 새 항목 체크", w.table.item(row_of("오래된글"), 0).checkState() == checked_state)
w.downloaded_ids.discard("a")

# ── 4. 검색 필터 ──────────────────────────────────────────────
w.select_all()
w.search_input.setText("앨범")
app.processEvents()
hidden = {w.table.item(r, 2).text() for r in range(3) if w.table.isRowHidden(r)}
check("검색 필터", hidden == {"최신글", "중간글"}, str(hidden))
w.search_input.setText("")
app.processEvents()

# ── 5. 상태 문구 말줄임 ───────────────────────────────────────
long_msg = "다운로드 중 (50/681) · 약 6분 40초 남음: " + ("긴제목" * 30)
w._set_status_text(long_msg)
app.processEvents()
fm = QtGui.QFontMetrics(w.status_label.font())
check("상태 문구가 라벨 폭을 넘지 않음",
      fm.horizontalAdvance(w.status_label.text()) <= w.status_label.width())
check("긴 문구는 말줄임 처리", w.status_label.text() != long_msg)

# ── 6. 파일명 정제 ────────────────────────────────────────────
f = ks._safe_title_fragment
check("파일명: 금지문자 제거", not any(c in f('현장학습: 동물원/수족관 "특별"') for c in '\/:*?"<>|'))
check("파일명: 길이 제한", len(f("가" * 100)) <= 30)
check("파일명: 알 수 없는 제목은 빈값", f("제목 알 수 없음") == "")

# ── 7. 옵션 문구 잘림 ─────────────────────────────────────────
clipped = [n for n, o in {
    "PDF": w.pdf_radio, "사진": w.photo_radio, "모두": w.both_radio,
    "동영상제외": w.chk_exclude_video, "개별": w.folder_individual_radio,
    "한곳": w.folder_single_radio, "허용": w.overwrite_allow_radio, "넘어가기": w.overwrite_skip_radio,
    # 아래 4개는 고배율에서 실제로 잘렸던 곳이라 반드시 포함한다
    "알림장": w.chk_report, "앨범": w.chk_album,
    "시작일": w.start_date_edit, "종료일": w.end_date_edit,
    "기간콤보": w.period_combo,
}.items() if o.width() < o.sizeHint().width()]
# 오프스크린 가상 화면은 실제 모니터보다 훨씬 좁아, 창이 레이아웃 요구폭까지
# 넓어지지 못한다. 여기서 보려는 것은 '레이아웃이 충분한 폭에서 올바른가'이므로
# 요구폭을 준 뒤 판정한다. (실제 화면에서는 _fit_window_to_contents가 넓혀준다)
w.setFixedSize(max(w.sizeHint().width() + 20, w.width()), w.height())
app.processEvents()
clipped = [n for n, o in {
    "PDF": w.pdf_radio, "사진": w.photo_radio, "모두": w.both_radio,
    "동영상제외": w.chk_exclude_video, "개별": w.folder_individual_radio,
    "한곳": w.folder_single_radio, "허용": w.overwrite_allow_radio, "넘어가기": w.overwrite_skip_radio,
    "알림장": w.chk_report, "앨범": w.chk_album,
    "시작일": w.start_date_edit, "종료일": w.end_date_edit, "기간콤보": w.period_combo,
}.items() if o.width() < o.sizeHint().width()]
check("옵션·기간 문구 잘림 없음 (DPI %s)" % os.environ.get("QT_FONT_DPI", "96"), not clipped, str(clipped))

# 날짜 텍스트가 실제로 들어가는지 (sizeHint 통과해도 글자가 넘칠 수 있어 별도 확인)
_fm = QtGui.QFontMetrics(w.start_date_edit.font())
check("날짜 텍스트가 칸 안에 들어감",
      _fm.horizontalAdvance(w.start_date_edit.text()) + 20 <= w.start_date_edit.width(),
      f"텍스트={_fm.horizontalAdvance(w.start_date_edit.text())} 칸={w.start_date_edit.width()}")

print()
print("RESULT:", "ALL PASSED" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)
