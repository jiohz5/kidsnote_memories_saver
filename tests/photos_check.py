# -*- coding: utf-8 -*-
"""사진/동영상 저장(download_photos_only)을 가짜 브라우저로 검증한다.

두 가지를 본다.

1. 무엇을 '이 글의 사진'으로 고르는가 (select_media_urls)
   예전 인라인 코드를 아래에 그대로 옮겨 두고, 많은 후보 조합에서 결과를 비교한다.
   여기가 틀리면 사진이 빠지거나 아이 얼굴 썸네일·아이콘이 사진처럼 섞여 저장된다.

2. 막혔을 때 다음 방법으로 넘어가는가
   직접 받기 → CDP → 브라우저 fetch → 화면 캡처. 사내망에서 실제로 이 순서대로 막힌다.
   네트워크는 쓰지 않는다. 각 방법을 가짜로 바꿔 '성공/실패'를 정해 준다.
"""
import itertools
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import kidsnote_engine as m  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want
    print("[%s] %s" % ("PASS" if ok else "FAIL", name), end="")
    print("" if ok else "\n        기대=%r\n        실제=%r" % (want, got))
    if not ok:
        fails.append(name)


class FakeDriver(object):
    current_url = "https://www.kidsnote.com/service/album/123"

    def __init__(self, raw_media=None, imgs=None):
        self._raw = raw_media or []
        self._imgs = imgs or []

    def execute_script(self, script, *args):
        if "scrollHeight" in script and "return" in script:
            return 900
        if "const items" in script:
            return self._raw
        return None

    def find_elements(self, by=None, value=None):
        if value == "img":
            return self._imgs
        return []


# ===================================================== 1. 무엇을 고르는가
def old_select(driver, raw_media, include_video):
    """예전 download_photos_only 안의 거르기 코드 그대로 (수정 금지)."""
    media_srcs = []
    seen_srcs = set()
    for item in raw_media or []:
        raw_url = item.get("url", "")
        if item.get("kind") == "srcset":
            raw_url = m._best_url_from_srcset(raw_url)
        src = m.normalize_media_url(driver, raw_url)
        if not src:
            continue
        lower_src = src.lower()
        if not include_video:
            if item.get("kind") in ("video", "source"):
                continue
            path_part = lower_src.split("?")[0]
            if any(path_part.endswith("." + ext) for ext in ("mp4", "webm", "mov", "m4v", "avi", "m3u8")):
                continue
        width = int(item.get("w") or 0)
        height = int(item.get("h") or 0)
        disp = max(int(item.get("dw") or 0), int(item.get("dh") or 0))
        path_only = lower_src.split("?")[0]
        is_tiny_ui_asset = 0 < max(width, height) <= 96
        looks_like_ui_asset = any(token in lower_src for token in ["profile", "avatar", "icon", "logo", "sprite"])
        is_small_display = 0 < disp <= 90
        is_avatar_thumb = bool(re.search(r'img_(36x36|65x65|130x130|240x240)\.', path_only))
        if (lower_src.endswith(".svg") or is_small_display or is_avatar_thumb
                or (looks_like_ui_asset and is_tiny_ui_asset)
                or (looks_like_ui_asset and width == 0 and height == 0)):
            continue
        if src in seen_srcs:
            continue
        seen_srcs.add(src)
        media_srcs.append(src)
    return media_srcs


URLS = [
    "https://cdn.kidsnote.com/photo/a.jpg",
    "https://cdn.kidsnote.com/photo/a.jpg?x=1",
    "//cdn.kidsnote.com/photo/b.png",
    "/relative/c.jpeg",
    "https://cdn.kidsnote.com/u/img_65x65.jpg",
    "https://cdn.kidsnote.com/u/img_240x240.jpg",
    "https://cdn.kidsnote.com/profile/me.jpg",
    "https://cdn.kidsnote.com/ui/icon.svg",
    "https://cdn.kidsnote.com/video/v.mp4",
    "https://cdn.kidsnote.com/video/v.m3u8?t=1",
    "data:image/png;base64,AAAA",
    "", "none",
    "https://cdn.kidsnote.com/photo/s1.jpg 1x, https://cdn.kidsnote.com/photo/s2.jpg 2x",
]
KINDS = ["image", "srcset", "image-link", "video", "source", "background"]
SIZES = [(0, 0, 0, 0), (40, 40, 40, 40), (1200, 900, 300, 200),
         (90, 90, 90, 90), (96, 96, 150, 150), (1200, 900, 80, 60)]

print("\n== 사진 고르기: 예전 코드와 같은가 ==")
items = [{"url": u, "kind": k, "w": w, "h": h, "dw": dw, "dh": dh}
         for u, k, (w, h, dw, dh) in itertools.product(URLS, KINDS, SIZES)]
drv = FakeDriver()
mismatch = []
for include_video in (True, False):
    # 하나씩 넣어 보고, 섞어서도 넣어 본다 (중복 제거와 순서까지 같은지)
    for it in items:
        if old_select(drv, [it], include_video) != m.select_media_urls(drv, [it], include_video):
            mismatch.append((it, include_video))
    if old_select(drv, items, include_video) != m.select_media_urls(drv, items, include_video):
        mismatch.append(("전체 목록", include_video))
check("후보 %d종 x 동영상 포함/제외 모두 동일" % len(items), mismatch[:3], [])

print("\n== 사진 고르기: 지켜야 할 규칙 ==")
def pick(url, kind="image", w=1200, h=900, dw=300, dh=200, video=True):
    return m.select_media_urls(drv, [{"url": url, "kind": kind, "w": w, "h": h, "dw": dw, "dh": dh}], video)

check("평범한 사진은 고름", pick("https://cdn.kidsnote.com/photo/a.jpg"),
      ["https://cdn.kidsnote.com/photo/a.jpg"])
check("아이 얼굴 썸네일(img_65x65)은 뺌", pick("https://cdn.kidsnote.com/u/img_65x65.jpg"), [])
check("화면에 작게(90px 이하) 보이는 것은 뺌", pick("https://cdn.kidsnote.com/photo/a.jpg", dw=80, dh=60), [])
check("아이콘(.svg)은 뺌", pick("https://cdn.kidsnote.com/ui/icon.svg"), [])
check("동영상 제외 설정이면 동영상은 뺌", pick("https://cdn.kidsnote.com/video/v.mp4", kind="video", video=False), [])
check("동영상 포함 설정이면 동영상도 고름", pick("https://cdn.kidsnote.com/video/v.mp4", kind="video"),
      ["https://cdn.kidsnote.com/video/v.mp4"])
check("srcset 은 가장 큰 것", pick("https://x/s1.jpg 1x, https://x/s2.jpg 2x", kind="srcset"),
      ["https://x/s2.jpg"])
check("같은 주소는 한 번만",
      m.select_media_urls(drv, [{"url": "https://x/a.jpg", "kind": "image", "dw": 300}] * 3, True),
      ["https://x/a.jpg"])


# ===================================================== 2. 막혔을 때 넘어가는가
RAW = [{"url": "https://cdn.kidsnote.com/photo/%d.jpg" % i, "kind": "image",
        "w": 1200, "h": 900, "dw": 300, "dh": 200} for i in (1, 2)]
POST = {"date": "2026.07.14", "type": "앨범", "title": "물놀이", "post_index": 0}


class FakeResponse(object):
    def __init__(self, ok):
        self.ok = ok
        self.headers = {"content-type": "image/jpeg"}

    def raise_for_status(self):
        if not self.ok:
            raise IOError("403")

    def iter_content(self, chunk_size=0):
        yield b"JPEGDATA"


class FakeImg(object):
    def get_attribute(self, name):
        return {"offsetWidth": "300", "naturalWidth": "1200", "src": "https://x/p.jpg"}.get(name, "")


def run(direct=True, cdp=False, browser=False, capture=False, raw=RAW, stop_after=None,
        has_photo="O", prefer_browser=False):
    """가짜 환경에서 download_photos_only 를 돌려 (결과, 저장된 파일, 로그) 를 돌려준다."""
    target = tempfile.mkdtemp(prefix="kn_photo_")
    logs = []
    calls = {"n": 0}

    def stop_cb():
        calls["n"] += 1
        return stop_after is not None and calls["n"] > stop_after

    patches = {
        "_sleep_with_stop": lambda s, cb=None, step=0.25: m._stop_requested(cb),
        "create_browser_session": lambda d: object(),
        "_session_get": lambda s, url, **k: FakeResponse(direct),
        "_cdp_fetch_media": lambda d, url: ((b"CDP", "200") if cdp else (None, "blocked")),
        "_browser_fetch_media": lambda d, url, timeout=60: ((b"BRW", "200") if browser else (None, "cors")),
        "_element_screenshot_b64": lambda el, log=None: ("UE5HREFUQQ==" if capture else ""),
        "WebDriverWait": lambda d, t: type("W", (), {"until": lambda self, f: True})(),
    }
    saved = {k: getattr(m, k) for k in patches}
    saved_sleep = m.time.sleep
    for k, v in patches.items():
        setattr(m, k, v)
    m.time.sleep = lambda s: None
    try:
        info = dict(POST, has_photo=has_photo)
        ok = m.download_photos_only(FakeDriver(raw, imgs=[FakeImg(), FakeImg()]), info, target,
                                    status_callback=logs.append, check_stop_callback=stop_cb,
                                    prefer_browser_fetch=prefer_browser)
        files = sorted(os.listdir(target))
        contents = [open(os.path.join(target, f), "rb").read() for f in files]
    finally:
        for k, v in saved.items():
            setattr(m, k, v)
        m.time.sleep = saved_sleep
        shutil.rmtree(target, ignore_errors=True)
    return ok, files, contents, logs


print("\n== 직접 받기가 되면 ==")
ok, files, contents, _ = run(direct=True)
check("성공", ok, True)
check("글 날짜로 이름을 붙여 번호대로 저장", files, ["260714_앨범_1.jpg", "260714_앨범_2.jpg"])

print("\n== 직접 받기가 막히면 CDP 로 ==")
ok, files, contents, logs = run(direct=False, cdp=True)
check("성공", ok, True)
check("CDP 로 받은 내용이 저장됨", contents, [b"CDP", b"CDP"])
check("CDP 를 썼다고 알림", any("CDP" in x for x in logs), True)

print("\n== CDP 도 막히면 브라우저 fetch 로 ==")
ok, files, contents, logs = run(direct=False, cdp=False, browser=True)
check("성공", ok, True)
check("브라우저로 받은 내용이 저장됨", contents, [b"BRW", b"BRW"])

print("\n== 직접 받기를 건너뛰는 설정(사내망 차단 확인됨) ==")
ok, files, contents, _ = run(direct=True, cdp=True, prefer_browser=True)
check("직접 받기를 시도하지 않고 CDP 로", contents, [b"CDP", b"CDP"])

print("\n== 전부 막히면 화면 캡처로 ==")
ok, files, contents, logs = run(direct=False, capture=True)
check("성공", ok, True)
check("캡처본은 png 로 저장", files, ["260714_앨범_1.png", "260714_앨범_2.png"])
check("화질이 낮을 수 있다고 알림", any("화면 캡처" in x for x in logs), True)

print("\n== 캡처까지 안 되면 실패로 알린다 (성공으로 위장하지 않음) ==")
ok, files, _c, logs = run(direct=False)
check("실패", ok, False)
check("아무것도 저장되지 않음", files, [])
check("진단 줄이 남음", any("[KN-DIAG] 미디어 실패" in x for x in logs), True)

print("\n== 사진이 있다던 글인데 주소를 못 찾으면 실패 ==")
ok, files, _c, _l = run(raw=[], has_photo="O")
check("실패", ok, False)

print("\n== 사진이 없는 글은 성공 ==")
ok, files, _c, _l = run(raw=[], has_photo="")
check("성공", ok, True)
check("저장된 것 없음", files, [])

print("\n== 중간에 중지하면 ==")
ok, files, _c, logs = run(direct=True, stop_after=6)
check("실패로 끝남", ok, False)
check("중지되었다고 알림", any("중지" in x for x in logs), True)

print()
if fails:
    print("RESULT: %d FAIL: %s" % (len(fails), fails))
    sys.exit(1)
print("RESULT: ALL PASSED")
