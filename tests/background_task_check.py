# -*- coding: utf-8 -*-
"""백그라운드 작업이 추적되고, 창을 닫을 때 정리되는지 확인한다.

로그인·아이전환·업데이트확인은 원래 daemon 스레드라 창을 닫으면 그냥 버려졌다.
브라우저에 명령을 보내던 중이었다면 msedgedriver 프로세스가 남고, 그것이
PyInstaller 임시폴더를 붙들어 '삭제 실패' 경고를 냈다.
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PyQt6 import QtWidgets  # noqa: E402
import kidsnote_saver as ks  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("[%s] %s" % ("PASS" if cond else "FAIL", name), end="")
    print("" if cond else "  (%s)" % detail)
    if not cond:
        fails.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

# 창을 만들면 0.7초 뒤 안내 팝업이 뜨도록 예약된다. 그 팝업은 모달이라
# processEvents 를 도는 순간 열려서 사람이 누를 때까지 영영 돌아오지 않는다.
# 화면 없는 테스트에서는 뜨지 않게 막는다.
ks.KidsnoteApp.show_initial_popup = lambda self: None
ks.KidsnoteApp.show_post_login_popup = lambda self: None


def pump(seconds=1.0):
    """Qt 이벤트를 돌리며 기다린다 (스레드가 끝날 시간을 준다)."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)


print("\n== 작업이 실제로 실행되는가 ==")
w = ks.KidsnoteApp()
ran = []
task = w.run_in_background(lambda: ran.append(True))
task.wait(3000)
check("함수가 실행됨", ran == [True], ran)

print("\n== 인자가 전달되는가 ==")
got = []
task = w.run_in_background(lambda a, b: got.append((a, b)), 'x', 7)
task.wait(3000)
check("인자 그대로 전달", got == [('x', 7)], got)

print("\n== 참조를 들고 있는가 ==")
# 참조를 놓으면 파이썬이 회수해 돌던 작업이 끊기고, 종료할 때 기다릴 수도 없다
started = []
task = w.run_in_background(lambda: (started.append(1), time.sleep(0.5)))
check("실행 중인 작업이 목록에 있음", task in w._background_tasks)
task.wait(3000)

print("\n== 끝난 작업은 정리되는가 ==")
before = len(w._background_tasks)
for _ in range(5):
    w.run_in_background(lambda: None).wait(2000)
pump(0.3)
w.run_in_background(lambda: None).wait(2000)
check("끝난 것이 쌓이지 않음", len(w._background_tasks) <= before + 2,
      "%d개 남음" % len(w._background_tasks))

print("\n== 예외가 나도 앱이 죽지 않는가 ==")
# Qt는 run() 밖으로 새는 예외를 삼켜 버려 아무 흔적도 남지 않는다
def boom():
    raise RuntimeError("일부러 낸 오류")

task = w.run_in_background(boom)
task.wait(3000)
check("예외가 밖으로 새지 않음", not task.isRunning())

print("\n== 창을 닫을 때 기다리는가 ==")
w2 = ks.KidsnoteApp()
finished = []
w2.run_in_background(lambda: (time.sleep(0.4), finished.append(True)))
w2.close()          # closeEvent 가 백그라운드 작업을 기다려야 한다
check("닫은 뒤 남아 도는 작업 없음",
      all(not t.isRunning() for t in w2._background_tasks))
check("작업이 끝까지 실행됨", finished == [True], finished)

print()
if fails:
    print("RESULT: %d FAIL: %s" % (len(fails), fails))
    sys.exit(1)
print("RESULT: ALL PASSED")
