# -*- coding: utf-8 -*-
"""동봉할 Edge WebDriver가 최신인지 확인하고, 뒤처졌으면 자동으로 교체한다.

배포본 안의 드라이버는 사용자의 Edge와 '메이저 버전'이 같을 때만 그대로 쓰인다.
버전이 뒤처지면 실행할 때마다 드라이버를 새로 내려받는 경로로 빠지는데,
이는 사내망처럼 다운로드가 막힌 환경에서 실행 자체가 실패하는 원인이 된다.
그래서 릴리스 빌드 전에 이 검사를 자동으로 수행한다.

사용법:
    python check_driver.py <드라이버경로>            # 확인만
    python check_driver.py <드라이버경로> --update   # 뒤처졌으면 자동 교체

종료 코드: 0 = 최신이거나 교체 성공, 1 = 갱신 필요(교체 안 함) 또는 교체 실패
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

LATEST_URL = "https://msedgedriver.microsoft.com/LATEST_STABLE"
DOWNLOAD_URL = "https://msedgedriver.microsoft.com/{version}/edgedriver_win64.zip"


def driver_version(driver_path):
    """드라이버 실행 파일에서 버전 문자열을 읽는다."""
    driver_path = os.path.abspath(driver_path)
    if not os.path.exists(driver_path):
        raise RuntimeError(f"파일이 없습니다: {driver_path}")
    out = subprocess.run([driver_path, "--version"], capture_output=True, text=True, timeout=20)
    text = (out.stdout or out.stderr or "").strip()
    for token in text.split():
        if token[:1].isdigit() and token.count(".") >= 2:
            return token
    raise RuntimeError(f"버전을 읽지 못했습니다: {text!r}")


def latest_version():
    """마이크로소프트가 배포 중인 최신 안정 버전."""
    with urllib.request.urlopen(LATEST_URL, timeout=15) as resp:
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


def update_driver(driver_path, version):
    """최신 드라이버를 받아 검증한 뒤 기존 파일을 교체한다.

    받은 파일이 실제로 실행되고 기대한 버전을 보고할 때만 교체하므로,
    다운로드가 깨졌더라도 멀쩡한 기존 드라이버를 잃지 않는다.
    """
    url = DOWNLOAD_URL.format(version=version)
    print(f"   내려받는 중: {url}")
    with urllib.request.urlopen(url, timeout=180) as resp:
        payload = resp.read()
    print(f"   내려받음: {len(payload) / 1024 / 1024:.1f} MB")

    with tempfile.TemporaryDirectory(prefix="edgedriver_") as tmp:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            names = [n for n in zf.namelist() if os.path.basename(n).lower() == "msedgedriver.exe"]
            if not names:
                raise RuntimeError("zip 안에 msedgedriver.exe가 없습니다")
            extracted = os.path.join(tmp, "msedgedriver.exe")
            with zf.open(names[0]) as src, open(extracted, "wb") as dst:
                shutil.copyfileobj(src, dst)

        # 교체 전에 새 파일이 정상 동작하는지 확인
        got = driver_version(extracted)
        if got.split(".")[0] != version.split(".")[0]:
            raise RuntimeError(f"받은 드라이버 버전이 예상과 다릅니다: {got} (기대 {version})")
        print(f"   검증 완료: {got}")

        driver_path = os.path.abspath(driver_path)
        backup = driver_path + ".old"
        try:
            if os.path.exists(driver_path):
                shutil.copy2(driver_path, backup)   # 되돌릴 수 있게 백업
            shutil.copy2(extracted, driver_path)
        except PermissionError:
            raise RuntimeError("드라이버 파일이 사용 중입니다. 실행 중인 프로그램을 닫고 다시 시도하세요.")

    print(f"   교체 완료: {driver_path}")
    if os.path.exists(driver_path + ".old"):
        print(f"   (이전 버전 백업: {os.path.basename(driver_path)}.old)")
    return True


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_update = "--update" in sys.argv
    driver_path = args[0] if args else "msedgedriver.exe"

    try:
        bundled = driver_version(driver_path)
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

    print(f"   -> 뒤처짐: {bundled.split('.')[0]} < {latest.split('.')[0]}")
    if not do_update:
        print("      (--update 를 주면 자동으로 교체합니다)")
        return 1

    try:
        update_driver(driver_path, latest)
    except Exception as e:
        print(f"   *** 자동 교체 실패: {e}")
        print("       기존 드라이버는 그대로 두었습니다. RELEASE_CHECKLIST.md의 수동 절차를 참고하세요.")
        return 1

    print("   -> OK: 최신 드라이버로 교체했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
