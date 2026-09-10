# -*- coding: utf-8 -*-
"""Edge WebDriver를 찾고, 버전을 맞추고, 필요하면 내려받는 일.

앱과 빌드 스크립트가 함께 쓴다. 원래는 같은 일을 두 벌로 갖고 있었다.
    앱(kidsnote_saver.py)   실행할 때 사용자 Edge에 맞는 드라이버를 확보
    빌드(check_driver.py)   배포본에 넣을 드라이버를 최신으로 교체
버전을 읽는 방식도, 최신 버전을 물어보는 주소도 서로 달라서, 한쪽을 고쳐도
다른 쪽은 그대로 남았다. 여기 한곳에 모아 둔다.

용어:
    메이저.마이너.빌드  앞 세 자리. 이게 같아야 Edge와 드라이버가 함께 동작한다.
    LATEST_STABLE       지금 배포 중인 최신 안정 버전 (빌드할 때 쓴다)
    LATEST_RELEASE_<빌드>  특정 빌드에 맞는 드라이버 버전 (사용자 PC에서 쓴다)
"""
import io
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

BASE_URL = "https://msedgedriver.microsoft.com"
LATEST_STABLE_URL = BASE_URL + "/LATEST_STABLE"

DRIVER_EXE = "msedgedriver.exe"

# 콘솔 창이 깜빡이지 않게 한다 (윈도우 전용 플래그)
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+\.\d+)")

_EDGE_DIRS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application",
    r"C:\Program Files\Microsoft\Edge\Application",
)


def driver_version(driver_path, timeout=10):
    """드라이버 실행 파일이 스스로 밝히는 버전. 못 읽으면 빈 문자열.

    처음 실행하는 파일은 바이러스 검사 때문에 몇 초씩 걸리기도 한다.
    여기서 시간이 모자라 빈 값이 나오면 '호환되지 않는다'고 판단해서
    쓸데없이 새로 내려받게 되므로, 너무 짧게 잡지 않는다.
    """
    if not driver_path:
        return ""
    # 상대 경로를 그대로 넘기면 윈도우가 현재 폴더가 아니라 PATH에서 찾는다.
    # 'msedgedriver.exe' 처럼 파일 이름만 준 경우 엉뚱하게 실패하므로 먼저 펼친다.
    driver_path = os.path.abspath(driver_path)
    if not os.path.exists(driver_path):
        return ""
    try:
        result = subprocess.run(
            [driver_path, "--version"],
            capture_output=True, text=True, timeout=timeout,
            creationflags=_NO_WINDOW,
        )
    except Exception:
        return ""
    match = _VERSION_RE.search(result.stdout or result.stderr or "")
    return match.group(1) if match else ""


def installed_edge_version():
    """이 PC에 깔린 Edge 중 가장 높은 버전. 못 찾으면 빈 문자열.

    Edge는 버전 이름의 폴더를 만들어 두므로 그 이름을 읽는다.
    업데이트 직후에는 옛 버전 폴더가 남아 있어서 가장 높은 것을 고른다.
    """
    versions = []
    for edge_dir in _EDGE_DIRS:
        try:
            for name in os.listdir(edge_dir):
                parts = name.split(".")
                if len(parts) == 4 and all(part.isdigit() for part in parts):
                    versions.append(name)
        except Exception:
            continue
    if not versions:
        return ""
    return sorted(versions, key=lambda v: tuple(int(p) for p in v.split(".")))[-1]


def is_compatible(edge_version, drv_version):
    """Edge와 드라이버가 함께 쓸 수 있는 짝인가.

    앞 세 자리(메이저.마이너.빌드)가 같아야 한다. 넷째 자리는 달라도 된다.
    """
    if not edge_version or not drv_version:
        return False
    return edge_version.split(".")[:3] == drv_version.split(".")[:3]


def major_of(version):
    """'152.0.4191.66' -> '152'. 못 읽으면 빈 문자열."""
    return version.split(".")[0] if version else ""


def package_name():
    """이 PC에 맞는 드라이버 zip 이름."""
    machine = platform.machine().lower()
    if "arm64" in machine or "aarch64" in machine:
        return "edgedriver_arm64.zip"
    if machine in ("x86", "i386", "i686") or machine.endswith("32"):
        return "edgedriver_win32.zip"
    return "edgedriver_win64.zip"


def _read_url(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def _decode_version_text(raw):
    """버전 파일을 문자열로 바꾼다.

    마이크로소프트는 이 파일을 BOM 붙은 UTF-16으로 내려준다.
    그냥 UTF-8로 읽으면 글자 사이에 널 문자가 끼어 버전이 깨진다.
    """
    for encoding in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            text = raw.decode(encoding).strip()
        except (UnicodeDecodeError, UnicodeError):
            continue
        cleaned = "".join(ch for ch in text if ch.isdigit() or ch == ".")
        if cleaned:
            return cleaned
    return ""


def latest_stable_version(timeout=15):
    """지금 배포 중인 최신 안정 버전. 빌드할 때 쓴다."""
    text = _decode_version_text(_read_url(LATEST_STABLE_URL, timeout))
    if not text:
        raise RuntimeError("최신 버전 문자열을 해석하지 못했습니다")
    return text


def download_versions_for(edge_version, timeout=8):
    """이 Edge에 맞는 드라이버로 시도해 볼 버전 목록.

    Edge와 완전히 같은 버전의 드라이버가 늘 있는 것은 아니다.
    그래서 같은 빌드에 대해 마이크로소프트가 알려 주는 버전도 함께 시도한다.
    조회에 실패해도(사내망 차단 등) 최소한 Edge 버전 하나는 시도해 본다.
    """
    versions = [edge_version]
    build = ".".join(edge_version.split(".")[:3])
    try:
        latest = _read_url("%s/LATEST_RELEASE_%s" % (BASE_URL, build), timeout)
        text = _decode_version_text(latest)
        if text and text not in versions:
            versions.append(text)
    except Exception:
        pass
    return versions


def download_driver(version, dest_dir, timeout=180, progress=None):
    """드라이버를 내려받아 dest_dir 에 풀어 놓고 그 경로를 돌려준다.

    zip 안에 msedgedriver.exe 가 없으면 예외를 낸다. 받은 파일이 실제로
    쓸 수 있는지(버전을 밝히는지)는 부르는 쪽이 확인한다.
    """
    url = "%s/%s/%s" % (BASE_URL, version, package_name())
    if progress:
        progress("내려받는 중: %s" % url)
    payload = _read_url(url, timeout)
    if progress:
        progress("내려받음: %.1f MB" % (len(payload) / 1024 / 1024))

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = [n for n in zf.namelist()
                 if os.path.basename(n).lower() == DRIVER_EXE]
        if not names:
            raise RuntimeError("zip 안에 %s가 없습니다" % DRIVER_EXE)
        os.makedirs(dest_dir, exist_ok=True)
        target = os.path.join(dest_dir, DRIVER_EXE)
        with zf.open(names[0]) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return target


# ---------------------------------------------------------------------------
# 사용자 PC에서 쓰는 드라이버 보관함
#
# 배포본에 넣어 둔 드라이버가 사용자 Edge와 맞지 않으면 맞는 것을 내려받는데,
# 매번 받으면 느리므로 받아 둔 것을 여기에 쌓아 두고 다시 쓴다.
# ---------------------------------------------------------------------------

def cache_root():
    return os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "KidsnoteMemoriesSaver", "drivers",
    )


def find_cached(edge_version):
    """보관함에서 이 Edge에 맞는 드라이버를 찾는다. 없으면 빈 문자열."""
    try:
        for root, _dirs, files in os.walk(cache_root()):
            if DRIVER_EXE not in files:
                continue
            path = os.path.join(root, DRIVER_EXE)
            if is_compatible(edge_version, driver_version(path)):
                return path
    except Exception:
        pass
    return ""


def cache_copy(source_path, cache_name):
    """배포본 안의 드라이버를 보관함에 복사해 두고 그 경로를 돌려준다.

    배포본이 onefile 로 만들어지면 실행할 때마다 임시폴더에 풀렸다가 사라진다.
    그 경로를 그대로 쓰면 다음 실행 때 없으므로, 남는 자리에 한 번 복사해 둔다.
    복사에 실패하면 원래 경로를 그대로 돌려준다 (없는 것보다는 낫다).
    """
    if not source_path or not os.path.exists(source_path):
        return ""
    try:
        version = driver_version(source_path) or "unknown"
        cache_dir = os.path.join(cache_root(), cache_name, version)
        cached = os.path.join(cache_dir, DRIVER_EXE)
        if not os.path.exists(cached):
            os.makedirs(cache_dir, exist_ok=True)
            shutil.copy2(source_path, cached)
        return cached
    except Exception:
        return source_path


def prune_cache(keep_driver_path, keep_count=5):
    """보관함이 계속 불어나지 않게 오래된 것부터 지운다."""
    try:
        keep_dir = (os.path.dirname(os.path.abspath(keep_driver_path))
                    if keep_driver_path else "")
        dirs = []
        for name in os.listdir(cache_root()):
            path = os.path.join(cache_root(), name)
            if os.path.isdir(path) and path != keep_dir:
                dirs.append((os.path.getmtime(path), path))
        for _mtime, path in sorted(dirs, reverse=True)[keep_count:]:
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def ensure_driver_for_edge(edge_version, status_callback=None):
    """이 Edge에 맞는 드라이버를 확보한다. 보관함을 먼저 뒤지고, 없으면 받는다.

    확보하지 못하면 빈 문자열. 부르는 쪽은 다른 후보로 넘어가면 된다.
    """
    if not edge_version:
        return ""

    cached = find_cached(edge_version)
    if cached:
        return cached

    dest_dir = os.path.join(cache_root(), edge_version)
    existing = os.path.join(dest_dir, DRIVER_EXE)
    if is_compatible(edge_version, driver_version(existing)):
        return existing

    if status_callback:
        status_callback("Edge %s에 맞는 WebDriver를 자동 다운로드 중..." % edge_version)

    for version in download_versions_for(edge_version):
        try:
            path = download_driver(version, dest_dir, timeout=30)
            if is_compatible(edge_version, driver_version(path)):
                prune_cache(path)
                return path
        except Exception:
            continue
    return ""


def driver_candidates(bundled_driver_path, status_callback=None):
    """드라이버를 실행해 볼 순서를 정한다.

    Edge와 맞는 것을 앞에 둔다. 맞는 게 없으면 그래도 있는 것들을 뒤에 붙인다.
    버전이 어긋나도 되는 경우가 가끔 있어서, 시도조차 안 하는 것보다 낫다.

    KIDSNOTE_MSEDGEDRIVER 환경변수로 직접 지정한 드라이버가 있으면 그것도 후보다.
    (사내망처럼 다운로드가 막힌 곳에서 관리자가 미리 넣어 둘 수 있게 한 장치)
    """
    edge_version = installed_edge_version()
    candidates = []

    manual = os.environ.get("KIDSNOTE_MSEDGEDRIVER", "")
    if not manual:
        app_dir = os.path.dirname(
            sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
        manual = os.path.join(app_dir, DRIVER_EXE)

    if manual and os.path.exists(manual):
        if is_compatible(edge_version, driver_version(manual)):
            candidates.append(manual)

    bundled_cached = cache_copy(bundled_driver_path, "bundled")
    if is_compatible(edge_version, driver_version(bundled_cached)):
        candidates.append(bundled_cached)
    else:
        downloaded = ensure_driver_for_edge(edge_version, status_callback)
        if downloaded:
            candidates.append(downloaded)
        if bundled_cached and os.path.exists(bundled_cached):
            candidates.append(bundled_cached)
        if manual and os.path.exists(manual):
            candidates.append(manual)

    # 순서를 지키면서 중복만 없앤다
    seen = set()
    ordered = []
    for path in candidates:
        if path and path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


# ---------------------------------------------------------------------------
# 빌드할 때 쓰는 부분
# ---------------------------------------------------------------------------

def replace_driver(driver_path, version, progress=None):
    """배포본에 넣을 드라이버를 최신 것으로 바꾼다.

    받은 파일이 실제로 실행되고 기대한 버전을 밝힐 때만 교체한다.
    그래서 다운로드가 깨졌더라도 멀쩡한 기존 드라이버를 잃지 않는다.
    바꾸기 전 것은 .old 로 남겨 되돌릴 수 있게 한다.
    """
    def say(msg):
        if progress:
            progress(msg)

    import tempfile
    with tempfile.TemporaryDirectory(prefix="edgedriver_") as tmp:
        extracted = download_driver(version, tmp, progress=progress)

        got = driver_version(extracted, timeout=20)
        if major_of(got) != major_of(version):
            raise RuntimeError("받은 드라이버 버전이 예상과 다릅니다: %s (기대 %s)" % (got, version))
        say("   검증 완료: %s" % got)

        driver_path = os.path.abspath(driver_path)
        try:
            if os.path.exists(driver_path):
                shutil.copy2(driver_path, driver_path + ".old")   # 되돌릴 수 있게
            shutil.copy2(extracted, driver_path)
        except PermissionError:
            raise RuntimeError("드라이버 파일이 사용 중입니다. 실행 중인 프로그램을 닫고 다시 시도하세요.")

    say("   교체 완료: %s" % driver_path)
    if os.path.exists(driver_path + ".old"):
        say("   (이전 버전 백업: %s.old)" % os.path.basename(driver_path))
    return True


def python_dll_dir():
    """이 파이썬이 의존하는 DLL 폴더 (anaconda 의 Library/bin).

    PyInstaller 가 _ssl / _lzma / _ctypes 의 의존 DLL을 못 찾으면 빌드는 성공해도
    실행할 때 DLL 로드 실패로 죽는다. 빌드 스크립트가 이 경로를 PATH에 넣는다.
    """
    return os.path.join(sys.base_prefix, "Library", "bin")
