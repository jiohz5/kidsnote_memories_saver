# -*- coding: utf-8 -*-
"""동봉할 Edge WebDriver가 최신인지 릴리스 전에 확인한다.

배포본 안의 드라이버는 사용자의 Edge와 '메이저 버전'이 같을 때만 그대로 쓰인다.
버전이 뒤처지면 실행할 때마다 드라이버를 새로 내려받는 경로로 빠지는데,
이는 사내망처럼 다운로드가 막힌 환경에서 실행 자체가 실패하는 원인이 된다.

종료 코드: 0 = 최신(그대로 배포 가능), 1 = 갱신 권장
"""
import os
import subprocess
import sys
import urllib.request

LATEST_URL = "https://msedgedriver.microsoft.com/LATEST_STABLE"


def bundled_version(driver_path):
    driver_path = os.path.abspath(driver_path)   # 상대 경로로도 안전하게 실행
    if not os.path.exists(driver_path):
        raise RuntimeError(f"파일이 없습니다: {driver_path}")
    out = subprocess.run([driver_path, "--version"], capture_output=True, text=True, timeout=15)
    text = (out.stdout or out.stderr or "").strip()
    for token in text.split():
        if token[:1].isdigit() and token.count(".") >= 2:
            return token
    raise RuntimeError(f"버전을 읽지 못했습니다: {text!r}")


def latest_version():
    with urllib.request.urlopen(LATEST_URL, timeout=10) as resp:
        raw = resp.read()
    # 이 파일은 BOM이 붙은 UTF-16으로 내려온다
    for enc in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            text = raw.decode(enc).strip()
        except (UnicodeDecodeError, UnicodeError):
            continue
        text = "".join(ch for ch in text if ch.isdigit() or ch == ".")
        if text:
            return text
    raise RuntimeError("최신 버전 문자열을 해석하지 못했습니다")


def main():
    driver_path = sys.argv[1] if len(sys.argv) > 1 else "msedgedriver.exe"

    try:
        bundled = bundled_version(driver_path)
    except Exception as e:
        print(f"   [건너뜀] 동봉 드라이버 버전 확인 실패: {e}")
        return 0   # 확인 자체가 안 되면 빌드를 막지는 않는다

    print(f"   동봉 드라이버 : {bundled}")

    try:
        latest = latest_version()
    except Exception as e:
        print(f"   [건너뜀] 최신 버전 조회 실패(네트워크?): {e}")
        return 0   # 오프라인 빌드를 막지 않는다

    print(f"   최신 배포본   : {latest}")

    if bundled.split(".")[0] == latest.split(".")[0]:
        print("   -> OK: 메이저 버전이 최신과 같습니다.")
        return 0

    print()
    print(f"   *** 경고: 동봉 드라이버가 {bundled.split('.')[0]}, 최신은 {latest.split('.')[0]} 입니다.")
    print("   이대로 배포하면 사용자의 Edge와 맞지 않아 실행할 때마다")
    print("   드라이버를 새로 내려받게 되고, 사내망에서는 실행이 실패할 수 있습니다.")
    print(f"   갱신: https://msedgedriver.microsoft.com/{latest}/edgedriver_win64.zip")
    return 1


if __name__ == "__main__":
    sys.exit(main())
