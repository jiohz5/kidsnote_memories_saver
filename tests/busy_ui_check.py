# -*- coding: utf-8 -*-
"""작업 중인지가 화면에 드러나고, 받는 동안 건드리면 안 되는 곳이 잠기는지 확인한다.

    - 목록을 불러오거나 받는 중에는 상태줄이 주황으로 바뀐다
    - 받는 중에는 2·3단계(목록 선택, 저장 설정)가 잠기고 그 위에 이유가 적힌다
      ([일시정지]·[작업 중지]는 그대로 누를 수 있어야 한다)
    - 잠긴 곳을 누르면 상태줄이 깜박인다
    - 작업 중에 창을 닫으려 하면 먼저 묻는다

브라우저 없이, 수집·다운로드 스레드를 가짜로 바꿔 실제 화면 흐름(불러오기 -> 받기 -> 끝)을 탄다.
사용자의 설정·증분 백업 기록·로그는 건드리지 않는다.
"""
import os
import sys
import tempfile
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp(prefix="kn_busy_")
os.environ.setdefault("KIDSNOTE_LOG_DIR", os.path.join(_TMP, "logs"))
os.makedirs(os.environ["KIDSNOTE_LOG_DIR"], exist_ok=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PyQt6 import QtWidgets, QtCore, QtTest  # noqa: E402
import kidsnote_saver as ks  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("[%s] %s" % ("PASS" if cond else "FAIL", name), end="")
    print("" if cond else "  (%s)" % (detail,))
    if not cond:
        fails.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def pump(seconds=0.2):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def wait_until(cond, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


# ---------------------------------------------------------------- 사용자 상태 보호
Box = QtWidgets.QMessageBox
asked = []          # 물어본 창 제목
answers = {}        # 제목에 들어간 말 -> 대답 (없으면 '아니오')
shown = []
opened = []

ks.KidsnoteApp.show_initial_popup = lambda self: None
ks.KidsnoteApp.show_post_login_popup = lambda self: None
ks.KidsnoteApp._save_prefs = lambda self: None
ks.KidsnoteApp._save_manifest = lambda self, ids: None
ks.KidsnoteApp._show_top_message = lambda self, icon, title, text: shown.append(title)


def _question(self, title, text, default_button=None):
    asked.append(title)
    for key, answer in answers.items():
        if key in title:
            return answer
    return Box.StandardButton.No


ks.KidsnoteApp._show_top_question = _question
for _name in ("warning", "information", "critical"):
    setattr(Box, _name, staticmethod(lambda *a, **k: (shown.append(a[1] if len(a) > 1 else ""),
                                                       Box.StandardButton.Ok)[1]))
_real_startfile = getattr(os, "startfile", None)
os.startfile = lambda path: opened.append(path)    # 탐색기 창을 실제로 열지 않는다


# ---------------------------------------------------------------- 가짜 스레드
class FakeScrape(QtCore.QThread):
    item_found_signal = QtCore.pyqtSignal(dict)
    status_signal = QtCore.pyqtSignal(str)
    profile_signal = QtCore.pyqtSignal(dict)
    finished_signal = QtCore.pyqtSignal(list)
    release = threading.Event()

    def __init__(self, **kwargs):
        super().__init__()
        self.is_stopped = False
        self.result_info = {}

    def stop(self):
        self.is_stopped = True
        FakeScrape.release.set()

    def run(self):
        found = []
        for i, title in enumerate(("가", "나")):
            mem = {"id": "m%d" % i, "date": "2026.09.0%d" % (i + 1), "title": title, "type": "알림장",
                   "writer": "교사", "has_photo": "O", "url": None, "child_name": "아이1"}
            found.append(mem)
            self.item_found_signal.emit(mem)
        FakeScrape.release.wait(10)
        self.finished_signal.emit(found)


class FakeDownload(QtCore.QThread):
    status_signal = QtCore.pyqtSignal(str)
    progress_signal = QtCore.pyqtSignal(int)
    finished_signal = QtCore.pyqtSignal(str, int, int, bool)
    release = threading.Event()

    def __init__(self, driver, memories, indices, target_dir, *rest):
        super().__init__()
        self.target_dir = target_dir
        self.indices = indices
        self.is_stopped = False
        self._paused = False
        self.succeeded_ids = []
        self.failed_indices = []
        self.elapsed_sec = 1
        self.network_blocked = False

    def stop(self):
        self.is_stopped = True
        FakeDownload.release.set()

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def run(self):
        self.progress_signal.emit(50)
        FakeDownload.release.wait(10)
        self.finished_signal.emit(self.target_dir, len(self.indices), 0, self.is_stopped)


ks.ScrapeThread = FakeScrape
ks.DownloadThread = FakeDownload


class FakeDriver(object):
    window_handles = ["main"]

    def quit(self):
        pass


w = ks.KidsnoteApp()
w.show()
pump(0.3)
w.driver = FakeDriver()
w.children_data = [{"text": "아이1 21.3.15.", "img_b64": "x"}]
w.lock_overlay.hide()
w.dir_input.setText(os.path.join(_TMP, "save"))
os.makedirs(os.path.join(_TMP, "save"), exist_ok=True)
w.load_btn.setEnabled(True)

IDLE, BUSY, ALERT = "#03A9F4", "#EF6C00", "#D32F2F"


def status_color():
    css = w.status_label.styleSheet()
    for color in (IDLE, BUSY, ALERT):
        if color in css:
            return color
    return css


print("\n== 평소 ==")
check("상태줄은 하늘색", status_color() == IDLE, status_color())
check("잠금막은 숨어 있음", not w.busy_overlay.isVisible())
check("2단계 표는 쓸 수 있음", w.table_group.isEnabled())
_h_idle = w.status_label.sizeHint().height()

print("\n== 목록을 불러오는 중 ==")
w.load_memories()
check("불러오는 중으로 바뀜", w.is_loading_memories, w.is_loading_memories)
check("상태줄이 주황", status_color() == BUSY, status_color())
check("  -> 색이 바뀌어도 줄 높이는 그대로", w.status_label.sizeHint().height() == _h_idle,
      "%d -> %d" % (_h_idle, w.status_label.sizeHint().height()))
check("불러오는 중에는 2단계를 잠그지 않음 (고른 체크가 다운로드에 그대로 쓰임)",
      w.table_group.isEnabled() and not w.busy_overlay.isVisible())

asked.clear()
check("닫으려 하면 묻고, '아니오'면 닫지 않음", w.close() is False and w.isVisible(), asked)
check("  -> 무엇이 진행 중인지 제목에 적음", any("목록" in t for t in asked), asked)

FakeScrape.release.set()
check("불러오기가 끝남", wait_until(lambda: not w.is_loading_memories), w.is_loading_memories)
check("상태줄이 다시 하늘색", status_color() == IDLE, status_color())
check("두 줄이 표에 들어옴", w.table.rowCount() == 2, w.table.rowCount())

print("\n== 받는 중 ==")
w.start_download()
check("받는 중으로 바뀜", w.is_downloading, w.is_downloading)
pump(0.1)
check("상태줄이 주황", status_color() == BUSY, status_color())
check("잠금막이 보임", w.busy_overlay.isVisible())
check("2단계(목록 선택)를 잠금", not w.table_group.isEnabled())
check("3단계(저장 설정)를 잠금", not w.options_group.isEnabled())
check("  -> 표의 체크칸도 키보드로 못 바꿈", not w.table.isEnabled())

veil = w.busy_overlay.geometry()
check("잠금막이 2단계 위쪽부터 덮음", veil.top() <= w.table_group.geometry().top(),
      (veil.top(), w.table_group.geometry().top()))
check("잠금막이 3단계 아래쪽까지 덮음", veil.bottom() >= w.options_group.geometry().bottom(),
      (veil.bottom(), w.options_group.geometry().bottom()))
check("[일시정지]는 덮지 않음", not veil.intersects(w.pause_btn.geometry()),
      (veil, w.pause_btn.geometry()))
check("[일시정지]·[작업 중지]는 누를 수 있음", w.pause_btn.isEnabled() and w.stop_btn.isEnabled())
check("1단계 [목록 불러오기]는 잠김", not w.load_btn.isEnabled())

print("\n== 잠긴 곳을 누르면 ==")
QtTest.QTest.mouseClick(w.busy_overlay, QtCore.Qt.MouseButton.LeftButton,
                        QtCore.Qt.KeyboardModifier.NoModifier, QtCore.QPoint(5, 5))
check("상태줄이 빨갛게 깜박임", status_color() == ALERT, status_color())
pump(1.2)
check("  -> 잠시 뒤 주황으로 돌아옴", status_color() == BUSY, status_color())

opened.clear()
w.busy_open_dir_btn.click()
check("[받은 파일 보기]는 저장 폴더를 엶", opened == [os.path.join(_TMP, "save")], opened)
check("  -> 다운로드는 그대로", w.is_downloading)

print("\n== 받는 중에 창을 닫으려 하면 ==")
asked.clear()
check("묻고, '아니오'면 닫지 않음", w.close() is False and w.isVisible(), asked)
check("  -> 다운로드라고 적음", any("다운로드" in t for t in asked), asked)
check("  -> 다운로드는 그대로", w.is_downloading)

print("\n== 받기가 끝나면 ==")
FakeDownload.release.set()
check("받기가 끝남", wait_until(lambda: not w.is_downloading), w.is_downloading)
pump(0.1)
check("상태줄이 다시 하늘색", status_color() == IDLE, status_color())
check("잠금막이 사라짐", not w.busy_overlay.isVisible())
check("2·3단계를 다시 쓸 수 있음", w.table_group.isEnabled() and w.options_group.isEnabled())
check("표도 다시 쓸 수 있음", w.table.isEnabled())

print("\n== 쉬는 중에는 묻지 않고 닫힘 ==")
asked.clear()
check("바로 닫힘", w.close() is True, asked)
check("  -> 묻지 않음", asked == [], asked)

if _real_startfile:
    os.startfile = _real_startfile

print()
if fails:
    print("RESULT: %d FAIL: %s" % (len(fails), fails))
    sys.exit(1)
print("RESULT: ALL PASSED")
