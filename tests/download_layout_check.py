# -*- coding: utf-8 -*-
"""다운로드 스레드가 실제로 만드는 폴더·파일 배치를 검증한다.

네트워크와 브라우저 없이 돌린다. 엔진의 download_item 을 가짜로 바꿔
'저장했다고 치고' 빈 파일만 만들게 한 뒤, 디스크에 남은 결과를 확인한다.

경로 계산은 tests/paths_check.py 가 따로 검증하지만, 계산한 경로를 스레드가
제대로 쓰는지는 별개 문제라서 여기서 본다. 옛 이름 넘겨받기와 빈 폴더 정리처럼
실제 파일이 있어야만 드러나는 동작도 함께 확인한다.
"""
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt6 import QtWidgets  # noqa: E402
import kidsnote_saver as ks  # noqa: E402
import kidsnote_engine as manager  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want
    print("[%s] %s" % ("PASS" if ok else "FAIL", name), end="")
    print("" if ok else "\n        기대=%r\n        실제=%r" % (want, got))
    if not ok:
        fails.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def fake_download_item(driver, mem, target_path_or_dir, is_pdf, status_cb=None,
                       overwrite=True, check_stop=None, include_video=True,
                       network_blocked=False):
    """실제 저장 대신 빈 파일만 만든다. 사진 모드면 폴더에 파일 두 개."""
    if is_pdf:
        os.makedirs(os.path.dirname(target_path_or_dir), exist_ok=True)
        open(target_path_or_dir, 'wb').close()
    else:
        os.makedirs(target_path_or_dir, exist_ok=True)
        prefix = "%s_%s" % (mem.get('_prefix', 'x'), mem.get('post_index', 0))
        for i in (1, 2):
            open(os.path.join(target_path_or_dir, "%s_%d.jpg" % (prefix, i)), 'wb').close()
    return True


def run_download(memories, single_folder=False, is_pdf=True, is_both=False,
                 pre_create=None):
    """가짜 다운로드를 한 번 돌리고, 저장 폴더의 파일 목록을 상대경로로 돌려준다."""
    target = tempfile.mkdtemp(prefix="kn_layout_")
    if pre_create:
        for rel in pre_create:
            full = os.path.join(target, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            open(full, 'wb').close()

    original = manager.download_item
    manager.download_item = fake_download_item
    try:
        th = ks.DownloadThread(
            driver=None, memories=memories, indices=list(range(len(memories))),
            target_dir=target, is_pdf=is_pdf, is_single_folder=single_folder,
            profile_name="홍길동", is_overwrite_allow=True, include_video=True,
            is_both=is_both,
        )
        th.run()   # 스레드를 띄우지 않고 본문만 그대로 실행
    finally:
        manager.download_item = original

    found = []
    for root, _dirs, files in os.walk(target):
        for f in files:
            found.append(os.path.relpath(os.path.join(root, f), target).replace(os.sep, '/'))
    dirs = []
    for root, ds, _f in os.walk(target):
        for d in ds:
            dirs.append(os.path.relpath(os.path.join(root, d), target).replace(os.sep, '/'))
    shutil.rmtree(target, ignore_errors=True)
    return sorted(found), sorted(dirs)


MEM = lambda date, title, typ='알림장', mid='1': {  # noqa: E731
    'date': date, 'title': title, 'type': typ, 'id': mid,
    'url': 'https://example.invalid/%s' % mid,
}

print("\n== 날짜별 폴더 배치 ==")
files, _ = run_download([MEM('2026.07.14', '물놀이')])
check("PDF가 날짜 폴더에 제목까지 붙어 저장",
      files, ['홍길동_알림장/20260714/260714_알림장_물놀이.pdf'])

files, _ = run_download([MEM('2026.7.4', '봄소풍')])
check("한 자리 월/일도 올바른 폴더로",
      files, ['홍길동_알림장/20260704/260704_알림장_봄소풍.pdf'])

print("\n== 같은 날 여러 글 ==")
files, _ = run_download([MEM('2026.07.14', '오전', mid='1'),
                         MEM('2026.07.14', '오후', mid='2')])
check("같은 날 두 글이 서로 덮어쓰지 않음", len(files), 2)
check("둘째 글에 순번이 붙음",
      files, ['홍길동_알림장/20260714/260714_알림장_1_오후.pdf',
              '홍길동_알림장/20260714/260714_알림장_오전.pdf'])

print("\n== 한 폴더에 모으기 ==")
files, dirs = run_download([MEM('2026.07.14', '물놀이')], single_folder=True)
check("날짜 폴더 없이 유형 폴더에 저장",
      files, ['홍길동_알림장/260714_알림장_물놀이.pdf'])
check("날짜 폴더가 만들어지지 않음", dirs, ['홍길동_알림장'])

print("\n== 알림장과 앨범은 서로 다른 폴더 ==")
files, _ = run_download([MEM('2026.07.14', '글', '알림장', '1'),
                         MEM('2026.07.14', '사진', '앨범', '2')])
check("유형별로 폴더가 갈림",
      files, ['홍길동_알림장/20260714/260714_알림장_글.pdf',
              '홍길동_앨범/20260714/260714_앨범_사진.pdf'])

print("\n== 옛 이름 넘겨받기 ==")
# 예전 버전이 만든 점 있는 폴더 + 제목 없는 PDF
files, dirs = run_download(
    [MEM('2026.07.14', '물놀이')],
    pre_create=['홍길동_알림장/2026.07.14/260714_알림장.pdf'],
)
check("점 있는 옛 폴더가 새 이름으로 넘어옴",
      dirs, ['홍길동_알림장', '홍길동_알림장/20260714'])
check("제목 없던 옛 PDF가 제목 붙은 이름으로 넘어옴 (두 벌로 쌓이지 않음)",
      files, ['홍길동_알림장/20260714/260714_알림장_물놀이.pdf'])

print("\n== 사진 저장 ==")
files, _ = run_download([MEM('2026.07.14', '물놀이', '앨범')], is_pdf=False)
check("사진은 날짜 폴더에 들어감", len(files), 2)
check("사진 폴더 경로",
      sorted({os.path.dirname(f) for f in files}), ['홍길동_앨범/20260714'])

print("\n== PDF와 사진 동시 저장 ==")
files, _ = run_download([MEM('2026.07.14', '물놀이', '앨범')], is_pdf=True, is_both=True)
check("PDF 1개 + 사진 2개가 같은 날짜 폴더에", len(files), 3)
check("모두 같은 폴더", len({os.path.dirname(f) for f in files}), 1)

print("\n== 저장에 실패하면 빈 폴더를 남기지 않는다 ==")
original = manager.download_item
target = tempfile.mkdtemp(prefix="kn_layout_fail_")
manager.download_item = lambda *a, **k: False   # 항상 실패
try:
    th = ks.DownloadThread(driver=None, memories=[MEM('2026.07.14', '물놀이')],
                           indices=[0], target_dir=target, is_pdf=True,
                           is_single_folder=False, profile_name="홍길동")
    th.run()
finally:
    manager.download_item = original
leftover = [d for d in os.listdir(target)] if os.path.isdir(target) else []
shutil.rmtree(target, ignore_errors=True)
check("빈 날짜 폴더도 빈 유형 폴더도 남지 않음", leftover, [])

print()
if fails:
    print("RESULT: %d FAIL: %s" % (len(fails), fails))
    sys.exit(1)
print("RESULT: ALL PASSED")
