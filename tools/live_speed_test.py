# -*- coding: utf-8 -*-
"""실제 키즈노트로 목록·다운로드 속도를 재는 실행기. 사람은 로그인 버튼만 누른다.

로그인은 계정 비밀번호로 키즈노트에 접속하는 일이라 자동으로 하지 않는다.
로그인이 끝나면 나머지는 순서대로 저절로 진행된다.

    1. 조회 기간을 PERIOD 로 맞추고 목록 불러오기 (알림장·앨범 모두)
    2. 가장 최근 글을 종류별로 PER_TYPE 개씩 고름
    3. [PDF+사진] 으로, 테스트 전용 폴더에 다운로드
    4. 이번 실행의 [KN-DIAG] 줄과 받은 파일 상태를 보고서로 남기고 창을 닫음

사용자의 실제 상태는 건드리지 않는다.
    - 실제 백업 폴더가 아니라 테스트 폴더에 받는다 (새 코드에 문제가 있어도 기존 백업을 덮어쓰지 않게)
    - 증분 백업 기록(downloaded_items.json)에 남기지 않는다 (테스트로 받은 글이 '이미 받음'이 되지 않게)
    - 저장 폴더 설정을 바꾸지 않는다
    - 중간에 뜨는 안내·질문 창은 열지 않고 '아니오'로 넘긴다 (실패 항목 자동 재시도도 하지 않음)

보고서에는 글 제목을 적지 않는다.

사용법:
    python tools/live_speed_test.py <테스트 폴더> <보고서 경로>
"""
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PyQt6 import QtWidgets, QtCore  # noqa: E402
import kidsnote_saver as ks  # noqa: E402

PERIOD = "최근 3개월"
PER_TYPE = 10
# 로그인을 기다리는 최대 시간(초). 사람이 자리를 비울 수 있어 넉넉하게 둔다.
LOGIN_TIMEOUT = int(os.environ.get("LIVE_LOGIN_TIMEOUT", 12 * 60 * 60))
# 로그인한 뒤 목록·다운로드에 쓸 수 있는 최대 시간(초).
# 시작 시각부터 세면 로그인을 오래 기다린 만큼 측정 시간이 줄어 다운로드 도중에 끊긴다.
RUN_TIMEOUT = int(os.environ.get("LIVE_RUN_TIMEOUT", 60 * 60))

OUT_DIR = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, "_live_test")
REPORT = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.join(OUT_DIR, "report.json")
PROGRESS = REPORT + ".progress.txt"
os.makedirs(OUT_DIR, exist_ok=True)

STARTED = time.time()
STARTED_STAMP = time.strftime("%Y-%m-%d %H:%M:%S")
events = []


def note(msg):
    line = "%s %s" % (time.strftime("%H:%M:%S"), msg)
    events.append(line)
    try:
        with open(PROGRESS, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- 사용자 상태 보호
Box = QtWidgets.QMessageBox
ks.KidsnoteApp._save_prefs = lambda self: note("저장 폴더 설정 저장은 건너뜀")
ks.KidsnoteApp._save_manifest = lambda self, ids: note("증분 백업 기록 저장은 건너뜀")
ks.KidsnoteApp.show_initial_popup = lambda self: None
ks.KidsnoteApp.show_post_login_popup = lambda self: None
ks.KidsnoteApp._show_top_message = lambda self, icon, title, text: note("[안내창 생략] " + str(title))


def _no_question(self, title, text, default_button=None):
    note("[질문창 -> 아니오] " + str(title))
    return Box.StandardButton.No


ks.KidsnoteApp._show_top_question = _no_question
for _name in ("warning", "information", "critical"):
    setattr(Box, _name, staticmethod(
        lambda *a, **k: (note("[경고창 생략] " + str(a[1] if len(a) > 1 else "")), Box.StandardButton.Ok)[1]))
Box.question = staticmethod(lambda *a, **k: (note("[질문창 -> 아니오]"), Box.StandardButton.No)[1])


# ---------------------------------------------------------------- 보고서
def collect_report(stage, extra=None):
    report = {"stage": stage, "started": STARTED_STAMP, "elapsed_sec": int(time.time() - STARTED),
              "events": events, "out_dir": OUT_DIR}
    report.update(extra or {})

    # 이번 실행 동안 로그에 남은 [KN-DIAG] 줄
    log_dir = ks._app_log_dir()
    diag = []
    for name in sorted(os.listdir(log_dir)):
        if not name.startswith("app_"):
            continue
        try:
            for line in open(os.path.join(log_dir, name), encoding="utf-8", errors="replace"):
                m = re.match(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]", line)
                if "[KN-DIAG]" in line and m and m.group(1) >= STARTED_STAMP:
                    diag.append(line.rstrip())
        except OSError:
            continue
    report["diag"] = diag

    # 받은 파일 상태 (제목은 적지 않는다)
    files = []
    for root, _d, names in os.walk(OUT_DIR):
        for n in names:
            if n.endswith((".json", ".txt")) and root == OUT_DIR:
                continue
            files.append(os.path.join(root, n))
    by_ext = {}
    small = 0
    parts = 0
    total_bytes = 0
    try:
        from PIL import Image
    except ImportError:
        Image = None
    for p in files:
        ext = os.path.splitext(p)[1].lower()
        by_ext[ext] = by_ext.get(ext, 0) + 1
        total_bytes += os.path.getsize(p)
        if p.endswith(".part"):
            parts += 1
        if Image and ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            try:
                with Image.open(p) as im:
                    if max(im.size) <= 260:
                        small += 1
            except Exception:
                pass
    report["files"] = {"count": len(files), "by_ext": by_ext, "small_images": small,
                       "part_files": parts, "megabytes": round(total_bytes / 1024 / 1024, 1)}
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- 진행
app = QtWidgets.QApplication(sys.argv)
ks.install_crash_logging()
w = ks.KidsnoteApp()
app.aboutToQuit.connect(w.cleanup_browser_processes)
w.setWindowTitle(w.windowTitle() + "  -  속도 측정: 로그인만 눌러 주세요")
w.show()
w.raise_()
w.activateWindow()
w.update_status("속도 측정 모드입니다. [로그인] 버튼만 눌러 주세요. 나머지는 자동으로 진행됩니다.")
note("시작. 로그인을 기다립니다")

state = {"step": "login", "since": time.time(), "picked": {}, "scraped": 0}


def finish(stage, extra=None):
    note("끝: " + stage)
    collect_report(stage, extra)
    QtCore.QTimer.singleShot(1500, w.close)
    QtCore.QTimer.singleShot(8000, app.quit)
    timer.stop()


def tick():
    try:
        _tick()
    except Exception as e:
        import traceback
        note("실행기 오류: %s" % traceback.format_exc())
        finish("실행기 오류")


def _tick():
    now = time.time()
    if state.get("login_at") and now - state["login_at"] > RUN_TIMEOUT:
        finish("로그인 뒤 시간 초과", {"last_step": state["step"]})
        return

    step = state["step"]
    if step == "login":
        if now - state["since"] > LOGIN_TIMEOUT:
            finish("로그인 대기 시간 초과")
            return
        ready = (getattr(w, "driver", None) is not None and getattr(w, "children_data", None)
                 and w.load_btn.isEnabled() and w.child_combo.isEnabled())
        if ready:
            note("로그인 완료. 아이 %d명" % len(w.children_data))
            state.update(step="settle", since=now, login_at=now)
        return

    if step == "settle":
        if now - state["since"] < 3:
            return
        w.chk_report.setChecked(True)
        w.chk_album.setChecked(True)
        w.period_combo.setCurrentText(PERIOD)
        note("목록 불러오기 시작 (%s)" % PERIOD)
        state.update(step="scrape", since=now)
        w.load_memories()
        return

    if step == "scrape":
        if w.load_finished_received and not w.is_loading_memories:
            state["scraped"] = len(w.memories)
            state["scrape_sec"] = round(now - state["since"], 1)
            note("목록 %d건, %.1f초" % (len(w.memories), now - state["since"]))
            if not w.memories:
                finish("목록 0건")
                return
            state.update(step="select", since=now)
        return

    if step == "select":
        w.deselect_all()
        rows = []
        for row in range(w.table.rowCount()):
            item = w.table.item(row, 2)
            idx = item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None
            if idx is None or not (0 <= idx < len(w.memories)):
                continue
            rows.append((row, w.memories[idx].get("type")))
        picked = {}
        chosen = []
        for row, typ in rows:                      # 종류별로 PER_TYPE 개씩
            if picked.get(typ, 0) < PER_TYPE:
                picked[typ] = picked.get(typ, 0) + 1
                chosen.append(row)
        for row, typ in rows:                      # 한쪽이 모자라면 다른 쪽으로 채움
            if len(chosen) >= PER_TYPE * 2:
                break
            if row not in chosen:
                picked[typ] = picked.get(typ, 0) + 1
                chosen.append(row)
        for row in chosen:
            w.table.item(row, 0).setCheckState(QtCore.Qt.CheckState.Checked)
        state["picked"] = picked
        note("선택: %s" % picked)
        w.both_radio.setChecked(True)
        w.dir_input.setText(OUT_DIR)
        note("다운로드 시작 (PDF+사진) -> 테스트 폴더")
        state.update(step="download", since=now)
        w.start_download()
        return

    if step == "download":
        th = getattr(w, "download_thread", None)
        if th is not None and th.isFinished() and not w.is_downloading:
            state["download_sec"] = round(now - state["since"], 1)
            note("다운로드 끝, %.1f초" % (now - state["since"]))
            finish("완료", {"scraped": state["scraped"], "scrape_sec": state.get("scrape_sec"),
                           "picked": state["picked"], "download_sec": state["download_sec"],
                           "success": len(getattr(th, "succeeded_ids", []) or []),
                           "failed": len(getattr(th, "failed_indices", []) or [])})
        return


timer = QtCore.QTimer()
timer.timeout.connect(tick)
timer.start(1000)
sys.exit(app.exec())
