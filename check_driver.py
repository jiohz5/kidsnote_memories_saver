# -*- coding: utf-8 -*-
"""동봉할 Edge WebDriver가 최신인지 확인하고, 뒤처졌으면 자동으로 교체한다.

배포본 안의 드라이버는 사용자의 Edge와 '메이저 버전'이 같을 때만 그대로 쓰인다.
버전이 뒤처지면 실행할 때마다 드라이버를 새로 내려받는 경로로 빠지는데,
이는 사내망처럼 다운로드가 막힌 환경에서 실행 자체가 실패하는 원인이 된다.
그래서 릴리스 빌드 전에 이 검사를 자동으로 수행한다.

버전을 읽고 내려받는 실제 작업은 edge_driver 모듈에 있다. 앱도 같은 모듈을 쓴다.
예전에는 앱과 이 스크립트가 같은 일을 따로 구현하고 있어서, 한쪽을 고쳐도
다른 쪽은 그대로 남았다.

사용법:
    python check_driver.py <드라이버경로>            # 확인만
    python check_driver.py <드라이버경로> --update   # 뒤처졌으면 자동 교체

종료 코드: 0 = 최신이거나 교체 성공, 1 = 갱신 필요(교체 안 함) 또는 교체 실패
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edge_driver   # noqa: E402


def main():
    if "--print-dll-dir" in sys.argv:
        print(edge_driver.python_dll_dir())
        return 0

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_update = "--update" in sys.argv
    driver_path = args[0] if args else edge_driver.DRIVER_EXE

    # 처음 실행하는 exe는 바이러스 검사 때문에 느릴 수 있어 넉넉히 기다린다
    bundled = edge_driver.driver_version(driver_path, timeout=20)
    if not bundled:
        print("   [건너뜀] 동봉 드라이버 버전 확인 실패: %s" % driver_path)
        return 0   # 확인 자체가 안 되면 빌드를 막지는 않는다

    print("   동봉 드라이버 : %s" % bundled)

    try:
        latest = edge_driver.latest_stable_version()
    except Exception as e:
        print("   [건너뜀] 최신 버전 조회 실패(네트워크?): %s" % e)
        return 0   # 오프라인 빌드를 막지 않는다

    print("   최신 배포본   : %s" % latest)

    if edge_driver.major_of(bundled) == edge_driver.major_of(latest):
        print("   -> OK: 메이저 버전이 최신과 같습니다.")
        return 0

    print("   -> 뒤처짐: %s < %s" % (edge_driver.major_of(bundled),
                                     edge_driver.major_of(latest)))
    if not do_update:
        print("      (--update 를 주면 자동으로 교체합니다)")
        return 1

    try:
        edge_driver.replace_driver(driver_path, latest, progress=print)
    except Exception as e:
        print("   *** 자동 교체 실패: %s" % e)
        print("       기존 드라이버는 그대로 두었습니다. RELEASE_CHECKLIST.md의 수동 절차를 참고하세요.")
        return 1

    print("   -> OK: 최신 드라이버로 교체했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
