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

print()
if fails:
    print("RESULT: %d FAIL: %s" % (len(fails), fails))
    sys.exit(1)
print("RESULT: ALL PASSED")
