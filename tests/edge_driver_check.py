# -*- coding: utf-8 -*-
"""Edge WebDriver 관리 모듈 검증.

앱과 빌드 스크립트가 같이 쓰는 코드다. 여기가 틀리면 두 곳이 동시에 틀린다.
네트워크가 필요한 검사는 따로 표시하고, 안 되면 건너뛴다.
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import edge_driver as ed  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want
    print("[%s] %s" % ("PASS" if ok else "FAIL", name), end="")
    print("" if ok else "\n        기대=%r\n        실제=%r" % (want, got))
    if not ok:
        fails.append(name)


print("\n== 버전 호환 판정 ==")
# 앞 세 자리가 같아야 한다. 넷째 자리는 달라도 된다.
check("앞 세 자리가 같으면 호환", ed.is_compatible("152.0.4191.66", "152.0.4191.30"), True)
check("빌드 번호가 다르면 비호환", ed.is_compatible("152.0.4191.66", "152.0.4190.10"), False)
check("메이저가 다르면 비호환", ed.is_compatible("152.0.4191.66", "151.0.4129.72"), False)
check("한쪽이 비면 비호환", ed.is_compatible("", "152.0.4191.66"), False)
check("양쪽이 비면 비호환", ed.is_compatible("", ""), False)
check("None도 예외 없이", ed.is_compatible(None, None), False)

print("\n== 메이저 버전 추출 ==")
check("정상 버전", ed.major_of("152.0.4191.66"), "152")
check("빈 문자열", ed.major_of(""), "")
check("None", ed.major_of(None), "")

print("\n== 버전 파일 해석 ==")
# 마이크로소프트는 BOM 붙은 UTF-16으로 내려준다. 그냥 읽으면 널 문자가 낀다.
check("UTF-16 BOM", ed._decode_version_text("152.0.4191.66".encode("utf-16")), "152.0.4191.66")
check("UTF-8 BOM", ed._decode_version_text("152.0.4191.66".encode("utf-8-sig")), "152.0.4191.66")
check("맨 UTF-8", ed._decode_version_text(b"152.0.4191.66"), "152.0.4191.66")
check("앞뒤 공백/줄바꿈 제거", ed._decode_version_text(b"  152.0.4191.66 \r\n"), "152.0.4191.66")
check("숫자가 없으면 빈 문자열", ed._decode_version_text(b"not a version"), "")

print("\n== 받을 버전 목록 ==")
# 네트워크가 막혀도 최소한 Edge 버전 하나는 시도해야 한다
saved = ed._read_url
ed._read_url = lambda url, timeout: (_ for _ in ()).throw(OSError("차단됨"))
try:
    check("조회 실패해도 Edge 버전은 시도", ed.download_versions_for("152.0.4191.66"),
          ["152.0.4191.66"])
finally:
    ed._read_url = saved

# 조회에 성공하면 그 버전도 함께 시도한다
ed._read_url = lambda url, timeout: "152.0.4191.80".encode("utf-16")
try:
    check("조회 성공하면 둘 다 시도", ed.download_versions_for("152.0.4191.66"),
          ["152.0.4191.66", "152.0.4191.80"])
    # 같은 값이면 중복으로 넣지 않는다
    ed._read_url = lambda url, timeout: "152.0.4191.66".encode("utf-16")
    check("같은 값이면 하나만", ed.download_versions_for("152.0.4191.66"),
          ["152.0.4191.66"])
finally:
    ed._read_url = saved

print("\n== 패키지 이름 ==")
name = ed.package_name()
check("이 PC용 zip 이름이 나옴",
      name in ("edgedriver_win64.zip", "edgedriver_win32.zip", "edgedriver_arm64.zip"), True)

print("\n== 없는 파일도 예외 없이 ==")
check("없는 경로의 버전은 빈 문자열", ed.driver_version(r"C:\없는폴더\없는파일.exe"), "")
check("빈 경로도 빈 문자열", ed.driver_version(""), "")
check("None 경로도 빈 문자열", ed.driver_version(None), "")

print("\n== 보관함 ==")
tmp = tempfile.mkdtemp(prefix="kn_drv_")
saved_root = ed.cache_root
ed.cache_root = lambda: tmp
try:
    check("빈 보관함에서는 못 찾음", ed.find_cached("152.0.4191.66"), "")
    # 오래된 폴더 정리: 5개만 남긴다
    for i in range(8):
        os.makedirs(os.path.join(tmp, "ver%d" % i), exist_ok=True)
    ed.prune_cache("", keep_count=5)
    check("보관함은 5개까지만", len(os.listdir(tmp)), 5)
    # 복사 대상이 없으면 빈 문자열
    check("없는 파일은 보관하지 않음", ed.cache_copy(r"C:\없는파일.exe", "bundled"), "")
finally:
    ed.cache_root = saved_root
    shutil.rmtree(tmp, ignore_errors=True)

print("\n== 실제 드라이버 파일 (있으면) ==")
real = os.path.join(ROOT, "msedgedriver.exe")
if os.path.exists(real):
    version = ed.driver_version(real, timeout=20)
    print("   동봉 드라이버 버전: %s" % version)
    check("네 자리 버전을 읽어 냄", len(version.split(".")) == 4, True)

    # 파일 이름만 준 경우. 윈도우는 상대 경로를 현재 폴더가 아니라 PATH에서 찾으므로
    # 안에서 절대 경로로 펼치지 않으면 빌드 스크립트가 조용히 실패한다 (실제로 겪음).
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        check("파일 이름만 줘도 읽어 냄", ed.driver_version("msedgedriver.exe", timeout=20),
              version)
    finally:
        os.chdir(cwd)

    edge = ed.installed_edge_version()
    print("   설치된 Edge 버전  : %s" % (edge or "(못 찾음)"))
    if edge:
        print("   호환 여부         : %s" % ed.is_compatible(edge, version))
else:
    print("   [건너뜀] msedgedriver.exe 가 없습니다")

print("\n== 이 프로그램이 띄운 드라이버만 정리 ==")
# 같은 PC에서 다른 자동화 프로그램의 msedgedriver 가 함께 돌 수 있다 (실제로 겪음).
# 창을 닫을 때 이름으로 전부 죽이면 그 프로그램의 브라우저까지 끊긴다.
# 여기서는 내 자식 드라이버 하나와, 다른 프로그램이 띄운 셈인 드라이버 하나를 띄워 본다.
# 남의 드라이버는 이 검사가 직접 띄운 것만 쓰고, 끝나면 그 번호로만 정리한다.
if os.name == "nt" and os.path.exists(real):
    import ctypes
    import subprocess

    def alive(pid):
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            k32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259   # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)

    def is_my_child(pid, parent=None):
        return any(p == pid for p, _n in ed._child_processes(parent or os.getpid()))

    mine = subprocess.Popen([real, "--port=0"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=0x08000000)
    # 다른 프로그램 흉내: 따로 띄운 파이썬이 드라이버를 띄우고 계속 살아 있다
    other = subprocess.Popen(
        [sys.executable, "-c",
         "import subprocess, sys, time\n"
         "p = subprocess.Popen([sys.argv[1], '--port=0'], stdout=subprocess.DEVNULL,"
         " stderr=subprocess.DEVNULL, creationflags=0x08000000)\n"
         "print(p.pid, flush=True)\n"
         "time.sleep(60)\n", real],
        stdout=subprocess.PIPE, text=True, creationflags=0x08000000)
    try:
        foreign_pid = int(other.stdout.readline().strip())
        check("내 드라이버는 내 자식으로 보임", is_my_child(mine.pid), True)
        check("남의 드라이버는 내 자식이 아님", is_my_child(foreign_pid), False)

        killed = ed.kill_own_driver_processes()
        check("내 드라이버를 정리 대상에 넣음", mine.pid in killed, True)
        check("남의 드라이버는 정리 대상에 없음", foreign_pid in killed, False)
        try:
            mine.wait(timeout=5)
            mine_gone = True
        except subprocess.TimeoutExpired:
            mine_gone = False
        check("내 드라이버는 꺼짐", mine_gone, True)
        check("남의 드라이버는 살아 있음", alive(foreign_pid), True)
    finally:
        if mine.poll() is None:
            mine.kill()
        # 이 검사가 띄운 파이썬과 그 아래 드라이버만, 번호로 정리한다
        subprocess.run(["taskkill", "/f", "/t", "/pid", str(other.pid)], capture_output=True,
                       creationflags=0x08000000)
        other.wait(timeout=10)

    # 부모 번호는 부모가 끝나도 남는다. 예전에 같은 번호를 쓰던 프로그램의 고아 프로세스를
    # 내 자식으로 착각하지 않도록, 나보다 먼저 생긴 것은 빼야 한다.
    probe = subprocess.Popen([real, "--port=0"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=0x08000000)
    saved_birth = ed._process_birth
    try:
        me = os.getpid()
        check("생긴 시각: 자식이 나보다 뒤", ed._process_birth(probe.pid) >= ed._process_birth(me),
              True)
        check("  -> 그래서 자식으로 보임", is_my_child(probe.pid), True)
        ed._process_birth = lambda pid: 200 if pid == me else 100   # 자식이 더 먼저 생긴 척
        check("  -> 나보다 먼저 생긴 것은 자식으로 치지 않음", is_my_child(probe.pid), False)
        check("  -> 정리 대상에도 없음", probe.pid in ed.kill_own_driver_processes(), False)
    finally:
        ed._process_birth = saved_birth
        probe.kill()
        probe.wait(timeout=5)
else:
    print("   [건너뜀] 윈도우가 아니거나 msedgedriver.exe 가 없습니다")

print()
if fails:
    print("RESULT: %d FAIL: %s" % (len(fails), fails))
    sys.exit(1)
print("RESULT: ALL PASSED")
