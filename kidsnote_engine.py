import os
import time
import re
import requests
import json
import base64
import datetime
import html
from urllib.parse import urljoin, urlparse
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# 사내망 SSL 검사 프록시 등에서 인증서 검증이 불가능할 때만 예외적으로 비검증 모드로 전환.
# KIDSNOTE_TLS_NO_VERIFY=1 환경변수로 처음부터 강제할 수도 있음.
_TLS_INSECURE = os.environ.get("KIDSNOTE_TLS_NO_VERIFY", "") == "1"


def _debug_enabled():
    """디버그 산출물(HTML/스크린샷)에는 자녀 사진과 알림장 내용이 포함되므로 기본 비활성."""
    return os.environ.get("KIDSNOTE_DEBUG", "") == "1"


def _mark_tls_insecure():
    global _TLS_INSECURE
    if not _TLS_INSECURE:
        _TLS_INSECURE = True
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _session_get(session, url, **kwargs):
    """TLS 검증 실패(사내망 SSL 인스펙션) 시 1회 비검증으로 자동 재시도하는 GET."""
    try:
        return session.get(url, **kwargs)
    except requests.exceptions.SSLError:
        _mark_tls_insecure()
        session.verify = False
        return session.get(url, **kwargs)


def _sleep_with_stop(seconds, check_stop_callback=None, step=0.25):
    """중지 요청을 0.25초 간격으로 확인하며 대기. 중지 요청 시 True 반환."""
    end = time.time() + seconds
    while time.time() < end:
        if _stop_requested(check_stop_callback):
            return True
        time.sleep(min(step, max(0.01, end - time.time())))
    return _stop_requested(check_stop_callback)


def _dpapi_crypt(data, protect):
    """Windows DPAPI로 사용자 계정 단위 암복호화 (외부 의존성 없음)."""
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    buf = ctypes.create_string_buffer(data, len(data))
    in_blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    out_blob = DATA_BLOB()
    func = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not func(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def protect_secret(text):
    """비밀번호 등 민감 문자열을 DPAPI로 암호화해 저장용 문자열로 반환."""
    if not text:
        return ""
    try:
        return "dpapi:" + base64.b64encode(_dpapi_crypt(text.encode("utf-8"), True)).decode("ascii")
    except Exception:
        # DPAPI 실패 환경(비 Windows 등) 폴백 — 평문 저장은 하지 않음
        return "b64:" + base64.b64encode(text.encode("utf-8")).decode("ascii")


def unprotect_secret(stored):
    """protect_secret 저장값 또는 구버전(base64) 값을 복호화."""
    if not stored:
        return ""
    try:
        if stored.startswith("dpapi:"):
            return _dpapi_crypt(base64.b64decode(stored[len("dpapi:"):]), False).decode("utf-8")
        if stored.startswith("b64:"):
            stored = stored[len("b64:"):]
        return base64.b64decode(stored.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""


# 게시물 카드에서 '작성자 줄'을 식별하기 위한 호칭 키워드 (구조 추출 실패 시 폴백)
_WRITER_KEYWORDS = (
    '교사', '선생님', '원장', '엄마', '아빠', '어머니', '아버지', '어머님', '아버님',
    '할머니', '할아버지', '외할머니', '외할아버지', '이모', '고모', '삼촌', '보호자',
)

# 카드 안의 '작은 아바타(프로필 사진)' 주변 헤더 블록에서 작성자명을 구조적으로 추출.
# 키워드 방식과 달리 '최유찬 엄마', 교사 실명 등 표기 형태와 무관하게 잡아낸다.
# 날짜 줄("7월 14일 화요일", "2026.07.14")은 제외한다.
_WRITER_EXTRACT_JS = """
var card = arguments[0];
var datePat = /(\\d{1,2}\\s*\\uC6D4\\s*\\d{1,2}\\s*\\uC77C)|(\\d{4}\\s*[.\\-\\uB144]\\s*\\d{1,2})|\\uC694\\uC77C/;
function lines(el){ return (el.innerText || '').split('\\n').map(function(s){ return s.trim(); }).filter(Boolean); }
var avatars = card.querySelectorAll("img, span[role='img']");
for (var i = 0; i < avatars.length; i++) {
  var av = avatars[i];
  var w = av.offsetWidth || 0;
  if (w <= 0 || w > 80) continue;  /* 본문 사진(큰 이미지) 제외, 작은 아바타만 */
  var node = av;
  for (var up = 0; up < 4; up++) {
    node = node.parentElement;
    if (!node || node === card.parentElement) break;
    var ls = lines(node);
    if (ls.length > 4) break;  /* 본문까지 포함된 큰 컨테이너로 번지면 중단 */
    for (var j = 0; j < ls.length; j++) {
      if (ls[j].length >= 2 && ls[j].length <= 25 && !datePat.test(ls[j])) return ls[j];
    }
  }
}
return '';
"""


def _is_on_service_home(driver):
    """현재 /service 홈(하위 경로 없이)에 떠 있고 아바타가 렌더링된 상태인지 확인.

    반복 조회 시 불필요한 SPA 전체 리로드를 생략하기 위한 판별용.
    """
    try:
        current = (driver.current_url or "").split('?')[0].split('#')[0].rstrip('/')
        if not current.endswith('kidsnote.com/service'):
            return False
        return bool(driver.find_elements(By.CSS_SELECTOR, ANY_AVATAR_CSS))
    except Exception:
        return False


def wait_css(driver, selector, timeout=10, poll=0.2):
    """selector에 해당하는 엘리먼트가 나타나는 '즉시' 진행하는 대기.

    고정 time.sleep 대신 사용 — 페이지가 이미 떠 있으면 0.2초 만에 통과하므로
    불필요한 대기 체감을 없애고, 느린 환경에서는 timeout까지 기다려 준다.
    """
    try:
        WebDriverWait(driver, timeout, poll_frequency=poll).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, selector)
        )
        return True
    except Exception:
        return False


# 키즈노트 웹 자체가 정상 목록 대신 뜨우는 에러 화면 문구들.
# "아이쿠! 에러가 발생했습니다"(SPA 크래시 바운더리) 외에,
# 실사용 중 관측된 "오류가 발생하였습니다"(별도 오류 토스트/배너로 추정)도 함께 감지한다.
_KIDSNOTE_APP_ERROR_MARKERS = ("아이쿠", "오류가 발생하였습니다", "오류가 발생했습니다")


def _detect_kidsnote_app_error(driver):
    """키즈노트 웹 자체의 에러 화면(SPA 크래시 바운더리 등)인지 감지.

    사내망 등에서 조회 도중 SPA가 내부 예외로 크래시하면 목록 대신 이 화면이 뜨는데,
    겉보기엔 '목록이 안 뜬다'는 점에서 단순 네트워크 타임아웃과 구분이 안 돼 원인 파악이 어려웠다.
    """
    try:
        text = driver.execute_script("return document.body ? document.body.innerText : '';") or ""
        return any(marker in text for marker in _KIDSNOTE_APP_ERROR_MARKERS)
    except Exception:
        return False


# ── 키즈노트 화면 셀렉터 ────────────────────────────────────────────────
# exa4ze60 / css-220836 처럼 생긴 이름은 키즈노트가 프론트엔드를 새로 배포할 때마다
# 값이 바뀌는 자동 생성(CSS-in-JS) 클래스입니다. 어느 날 한꺼번에 깨질 수 있으므로
#   (1) 여기 한 곳에만 적어두고 (고칠 때 이 블록만 수정)
#   (2) 클래스로 못 찾으면 _find_post_cards()의 구조 기반 탐색이 대신 찾도록
# 이중으로 대비합니다.
# 각 목록의 고유 주소. 메뉴 클릭이 실패했을 때 여기로 직접 이동해 진입하고,
# 클릭 후 엉뚱한 목록으로 갔는지 확인하는 기준으로도 쓴다.
SECTION_URLS = {
    "알림장": "https://www.kidsnote.com/service/report",
    "앨범": "https://www.kidsnote.com/service/album",
}

POST_CARD_CLASSES = ("exa4ze60", "css-220836")      # 목록의 게시물 카드
CARD_DATE_XPATH = ".//div[contains(@class, 'exa4ze65')]/div"   # 카드 안 날짜
CARD_DATE_CLASS = "css-15xrcbi"                      # 날짜 폴백
CARD_BODY_XPATH = ".//div[contains(@class, 'e14iqn2g4')]"      # 카드 안 본문/제목
CARD_BODY_CLASS = "css-12g7lcb"                      # 본문 폴백
MEMORY_MENU_CLASS = "e1q0zrbj0"                      # 사이드바 '추억보기'
MEMORY_MENU_LINK_CLASS = "e1efjxmz8"                 # 드롭다운 '추억보기'
ALBUM_BODY_CLASS = "css-1469k6q"                     # 앨범 상세 본문 영역

# 여러 곳에서 쓰는 것들. 키즈노트가 화면을 바꾸면 여기부터 확인한다.
# (예전에는 같은 XPath가 세 군데에 흩어져 있어, 한 곳만 고치고 넘어가기 쉬웠다)
VIEW_ALL_XPATH = "//*[contains(text(),'전체보기')]"                    # 목록 '전체보기' 버튼
NEXT_PAGE_XPATH = "//button[.//span[starts-with(text(), '다음')]]"     # 다음 페이지 버튼
SIDEBAR_MENU_XPATH = "//*[@data-testid='center-sidebar-menu-select']"  # 사이드바 메뉴
ACTIVE_AVATAR_XPATH = "//*[@size='65' and @role='img']"                # 선택된 아이의 큰 아바타
ANY_AVATAR_CSS = "span[role='img']"                                    # 아바타 아무거나(화면 준비 확인용)
CHILD_AVATAR_CSS = "span[role='img'][size='36']"                       # 아이 목록의 작은 아바타(선택용)
ACTIVE_AVATAR_CSS = "span[role='img'][size='65']"                      # 선택된 아이의 큰 아바타


def post_card_xpath():
    """게시물 카드를 찾는 XPath (알려진 클래스 기준)."""
    conds = " or ".join("contains(@class, '%s')" % c for c in POST_CARD_CLASSES)
    return "//div[%s]" % conds


# 클래스명이 전부 바뀌었을 때 쓰는 구조 기반 탐색.
# '링크를 품고 있고 + 날짜 형태 텍스트를 포함하는 반복 요소'를 게시물 카드로 본다.
_FIND_CARDS_FALLBACK_JS = r"""
var datePat = /(\d{4}\s*[.\-년]\s*\d{1,2})|(\d{1,2}\s*월\s*\d{1,2}\s*일)/;
/* body/nav/footer 등은 카드가 될 수 없다 (페이지 전체를 카드 하나로 오인하는 것 방지) */
var SKIP = {BODY: 1, HTML: 1, NAV: 1, FOOTER: 1, HEADER: 1, MAIN: 1};
var groups = {};
var links = document.querySelectorAll('a[href]');
for (var i = 0; i < links.length; i++) {
  var node = links[i];
  for (var up = 0; up < 5 && node && node.parentElement; up++) {
    node = node.parentElement;
    if (SKIP[node.tagName]) break;
    var txt = node.innerText || '';
    if (txt.length > 600) break;              /* 너무 큰 컨테이너는 카드가 아님 */
    if (!datePat.test(txt)) continue;
    var sig = node.tagName + '|' + (node.className || '') + '|' + up;
    if (!groups[sig]) groups[sig] = [];
    if (groups[sig].indexOf(node) === -1) groups[sig].push(node);  /* 중복 제거 */
    break;
  }
}
var best = [];
for (var k in groups) {
  var g = groups[k];
  /* 서로를 포함하는 요소가 있으면 안쪽(개별 카드)만 남긴다 */
  g = g.filter(function (el) {
    return !g.some(function (other) { return other !== el && el.contains(other); });
  });
  if (g.length > best.length) best = g;
}
/* 2개 이상 반복되는 구조일 때만 신뢰한다 */
return best.length >= 2 ? best : [];
"""


def _find_post_cards(driver, log=None):
    """게시물 카드 목록을 반환. (요소목록, 폴백사용여부)

    1순위: 알려진 클래스명. 2순위: 구조 기반 탐색(클래스명이 전부 바뀐 경우).
    """
    try:
        cards = driver.find_elements(By.XPATH, post_card_xpath())
        if cards:
            return cards, False
    except Exception:
        pass

    try:
        cards = driver.execute_script(_FIND_CARDS_FALLBACK_JS) or []
        if cards:
            if log:
                log("[KN-DIAG] 카드 탐색: 클래스 실패 → 구조 기반 폴백으로 %d개 발견" % len(cards))
            return cards, True
    except Exception as e:
        if log:
            log("DEBUG: 구조 기반 카드 탐색 실패 - %s" % type(e).__name__)
    return [], False


_DATE_LIKE_RE = re.compile(r'(\d{4}\s*[.\-년]\s*\d{1,2}\s*[.\-월]?\s*\d{0,2})|(\d{1,2}\s*월\s*\d{1,2}\s*일)')


def _card_lines(card):
    """카드의 텍스트를 줄 단위로 반환 (실패 시 빈 리스트)."""
    try:
        return [ln.strip() for ln in (card.text or "").split("\n") if ln.strip()]
    except Exception:
        return []


def _first_date_like_line(card):
    """카드 텍스트에서 날짜 형태의 줄을 찾아 반환 (클래스명이 바뀌었을 때의 폴백)."""
    for line in _card_lines(card):
        if _DATE_LIKE_RE.search(line):
            return line
    return ""


def _longest_content_line(card):
    """카드 텍스트에서 날짜/작성자 줄을 제외한 가장 긴 줄을 본문으로 간주 (폴백)."""
    best = ""
    for line in _card_lines(card):
        if _DATE_LIKE_RE.search(line):
            continue
        if len(line) <= 25 and any(k in line for k in _WRITER_KEYWORDS):
            continue
        if len(line) > len(best):
            best = line
    return best[:35]


def _wait_for_list_or_app_error(driver, timeout=30, poll=0.25):
    """게시물 목록 요소가 뜨거나 키즈노트 자체 에러 화면이 뜨는 즉시(둘 중 먼저 오는 쪽) 반환.

    기존에는 목록 요소만 고정 타임아웃(최대 30초)으로 기다렸기 때문에, 목록 대신 에러 화면이
    떠 있어도 그 사실을 30초 내내 모르고 있다가 타임아웃이 지나서야 재시도로 넘어갔다
    ('감지 후 새로고침까지 너무 느리다' 피드백의 원인). 매 poll마다 에러 문구도 함께 확인해
    에러가 뜨면 타임아웃을 기다리지 않고 즉시 재시도로 넘어갈 수 있게 한다.
    반환: 'items' | 'error' | 'timeout'
    """
    items_xpath = post_card_xpath()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if driver.find_elements(By.XPATH, items_xpath):
                return 'items'
        except Exception:
            pass
        if _detect_kidsnote_app_error(driver):
            return 'error'
        time.sleep(poll)
    return 'timeout'


def normalize_media_url(driver, url):
    """Browser에서 보이는 이미지/동영상 URL을 requests가 받을 수 있는 절대 URL로 정리합니다."""
    if not url:
        return ""
    url = html.unescape(str(url).strip().strip('"').strip("'"))
    if not url or url in ("none", "null", "undefined"):
        return ""
    if url.startswith("data:") or url.startswith("blob:"):
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return urljoin(driver.current_url, url)
    if not url.startswith(("http://", "https://")):
        return urljoin(driver.current_url, url)
    return url


def _browser_user_agent(driver):
    try:
        return driver.execute_script("return navigator.userAgent") or "Mozilla/5.0"
    except Exception:
        return "Mozilla/5.0"


def create_browser_session(driver):
    """Selenium 로그인 쿠키/UA를 복사한 requests 세션을 만듭니다."""
    session = requests.Session()
    # 기본은 TLS 검증 활성. 사내망 SSL 인스펙션으로 실패하면 _session_get이 자동 폴백.
    session.verify = not _TLS_INSECURE
    if _TLS_INSECURE:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    # 재시도 횟수를 줄여 사내망 차단 환경에서 요청 1건이 수십 초씩 멈추는 현상 방지
    retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504, 429])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)

    for cookie in driver.get_cookies():
        try:
            kwargs = {"path": cookie.get("path", "/")}
            if cookie.get("domain"):
                kwargs["domain"] = cookie["domain"]
            session.cookies.set(cookie["name"], cookie["value"], **kwargs)
        except Exception:
            session.cookies.set(cookie.get("name"), cookie.get("value"))

    session.headers.update({
        "User-Agent": _browser_user_agent(driver),
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,video/*,*/*;q=0.8",
        "Referer": driver.current_url or "https://www.kidsnote.com/",
    })
    return session


def probe_direct_access(driver, timeout=5):
    """requests 세션이 브라우저 밖에서 키즈노트 서버에 직접 접근 가능한지 사전 점검.

    사내망 프록시/PAC 환경에서는 브라우저(Edge)는 정상이어도 파이썬 requests의
    직접 접근이 차단될 수 있고, 이 경우 사진/동영상 다운로드가 전부 실패한다.
    다운로드 시작 전에 이 함수로 확인해 사용자에게 미리 경고한다.
    """
    try:
        session = create_browser_session(driver)
        response = _session_get(session, "https://www.kidsnote.com/", timeout=(timeout, timeout), stream=True, allow_redirects=True)
        try:
            return response.status_code < 500
        finally:
            response.close()
    except Exception:
        return False


def _browser_fetch_media(driver, url, timeout=60):
    """브라우저(페이지 컨텍스트) 안에서 fetch로 미디어를 받아 bytes로 반환.

    파이썬 requests 직접 접근이 프록시/보안 정책으로 차단된 환경에서도
    브라우저 자체 네트워크는 뚫려 있으므로(페이지에 사진이 잘 보임),
    로그인 세션 그대로 fetch → blob → base64로 꺼내온다.
    반환: (bytes 또는 None, 상태 문자열)
    """
    def _do_fetch(with_credentials):
        js = """
            var url = arguments[0];
            var withCreds = arguments[1];
            var done = arguments[arguments.length - 1];
            try {
                var ctrl = new AbortController();
                setTimeout(function(){ ctrl.abort(); }, %d);
                fetch(url, {credentials: withCreds ? 'include' : 'omit', signal: ctrl.signal}).then(function(r){
                    if (!r.ok) { done('ERR:HTTP_' + r.status); return null; }
                    return r.blob();
                }).then(function(b){
                    if (!b) { return; }
                    var fr = new FileReader();
                    fr.onload = function(){
                        window.__kn_media_b64 = String(fr.result).split(',')[1] || '';
                        done('OK:' + window.__kn_media_b64.length);
                    };
                    fr.onerror = function(){ done('ERR:READ'); };
                    fr.readAsDataURL(b);
                }).catch(function(e){
                    var name = e && e.name ? e.name : 'FETCH';
                    var detail = e && e.message ? (':' + e.message).slice(0, 120) : '';
                    done('ERR:' + name + detail);
                });
            } catch (e) {
                done('ERR:' + e);
            }
        """ % max(int((timeout - 5) * 1000), 5000)
        try:
            driver.set_script_timeout(timeout)
            result = driver.execute_async_script(js, url, with_credentials)
            if not (isinstance(result, str) and result.startswith('OK:')):
                return None, str(result or 'ERR:UNKNOWN')
            total_len = int(result[3:])
            if total_len <= 0:
                return None, 'ERR:EMPTY'
            # 대용량 base64를 한 번에 반환하면 드라이버가 불안정해질 수 있어 4MB씩 분할 수신
            chunks = []
            chunk_size = 4 * 1024 * 1024
            for offset in range(0, total_len, chunk_size):
                part = driver.execute_script(
                    "return (window.__kn_media_b64 || '').substring(arguments[0], arguments[1]);",
                    offset, offset + chunk_size)
                chunks.append(part or '')
            driver.execute_script("window.__kn_media_b64 = null;")
            data = base64.b64decode(''.join(chunks))
            return (data, 'OK') if data else (None, 'ERR:DECODE')
        except Exception as e:
            return None, f'ERR:{type(e).__name__}'
        finally:
            try:
                driver.set_script_timeout(30)
            except Exception:
                pass

    data, status = _do_fetch(True)
    if data is None and status.startswith('ERR:TypeError'):
        # credentials:'include'로 크로스오리진(미디어 CDN) 요청 시, 서버가 자격증명 포함
        # CORS를 허용하지 않으면 브라우저가 네트워크 단계에서 응답을 차단해 TypeError만 남는다
        # (원인 메시지가 뭉개짐). 서명된 CDN URL은 보통 쿠키가 필요 없으므로 쿠키 없이 재시도한다.
        retry_data, retry_status = _do_fetch(False)
        if retry_data is not None:
            return retry_data, retry_status
        status = f"{status}|noauth:{retry_status}"
        if retry_status.startswith('ERR:TypeError'):
            # credentials 유무와 무관하게 둘 다 TypeError라면 CORS 자격증명 정책 문제가 아니라
            # CDN이 CORS 헤더 자체를 아예 내려주지 않는 경우일 가능성이 높다. no-cors 프로브로
            # '네트워크는 도달하지만 CORS만 없는 것'과 '네트워크 자체가 막힌 것'을 구분해 남긴다.
            status = f"{status}|probe:{_probe_no_cors_reachable(driver, url)}"
    return data, status


def _probe_no_cors_reachable(driver, url, timeout=15):
    """no-cors 모드 fetch로 CORS 헤더 부재와 순수 네트워크 차단을 구분하는 진단 프로브.

    no-cors 요청은 응답에 CORS 헤더가 없어도 브라우저가 막지 않는다(응답 '내용'을 못 읽을 뿐).
    이게 성공하면(opaque 응답 수신) 네트워크 자체는 뚫려 있고 CORS 헤더가 없어서 fetch로 못
    받는 것 → CDP 경유 우회가 유효한 케이스. 이마저 실패하면 사내망 차단/URL 만료 등
    네트워크 단계에서부터 막힌 것으로 봐야 한다.
    """
    js = """
        var url = arguments[0];
        var done = arguments[arguments.length - 1];
        var ctrl = new AbortController();
        setTimeout(function(){ ctrl.abort(); }, %d);
        fetch(url, {mode: 'no-cors', credentials: 'omit', signal: ctrl.signal}).then(function(r){
            done('reachable(type=' + r.type + ',status=' + r.status + ')');
        }).catch(function(e){
            var name = e && e.name ? e.name : 'FETCH';
            var detail = e && e.message ? (':' + e.message).slice(0, 80) : '';
            done('unreachable(' + name + detail + ')');
        });
    """ % max(int((timeout - 2) * 1000), 3000)
    try:
        driver.set_script_timeout(timeout)
        return driver.execute_async_script(js, url) or 'UNKNOWN'
    except Exception as e:
        return f'PROBE_ERR:{type(e).__name__}'
    finally:
        try:
            driver.set_script_timeout(30)
        except Exception:
            pass


def _cdp_fetch_media(driver, url):
    """CDP(DevTools Protocol)로 미디어를 CORS 제약 없이 원본 바이트로 받는다.

    fetch()/XHR은 브라우저의 동일-출처 정책을 반드시 지키므로, CDN이 CORS 헤더를 아예
    내려주지 않으면 credentials 유무와 무관하게 항상 'TypeError: Failed to fetch'로 막힌다
    (실제로 사내망 등에서 관측된 실패 패턴). Network.loadNetworkResource는 페이지 JS가 아니라
    디버깅 프로토콜로 브라우저 네트워크 스택에 직접 접근하므로 이 제약을 받지 않는다.
    Selenium의 Chromium 계열(Edge 포함) execute_cdp_cmd로 호출 가능.
    반환: (bytes 또는 None, 상태 문자열)
    """
    try:
        frame_tree = driver.execute_cdp_cmd('Page.getFrameTree', {})
        frame_id = frame_tree['frameTree']['frame']['id']
    except Exception as e:
        return None, f'ERR:CDP_FRAME_{type(e).__name__}'

    try:
        result = driver.execute_cdp_cmd('Network.loadNetworkResource', {
            'frameId': frame_id,
            'url': url,
            'options': {'disableCache': False, 'includeCredentials': True},
        })
    except Exception as e:
        # 구형 Edge/드라이버가 이 CDP 명령을 지원하지 않는 경우 (정상적인 폴백 대상)
        return None, f'ERR:CDP_UNSUPPORTED_{type(e).__name__}'

    resource = (result or {}).get('resource') or {}
    http_status = resource.get('httpStatusCode')
    if not resource.get('success'):
        net_err = resource.get('netErrorName') or resource.get('netError') or 'UNKNOWN'
        suffix = f'_HTTP{http_status}' if http_status else ''
        return None, f'ERR:CDP_{net_err}{suffix}'

    stream = resource.get('stream')
    if not stream:
        return None, 'ERR:CDP_NO_STREAM'

    chunks = []
    try:
        while True:
            chunk = driver.execute_cdp_cmd('IO.read', {'handle': stream, 'size': 4 * 1024 * 1024})
            piece = chunk.get('data', '') or ''
            chunks.append(base64.b64decode(piece) if chunk.get('base64Encoded') else piece.encode('utf-8', 'ignore'))
            if chunk.get('eof'):
                break
        driver.execute_cdp_cmd('IO.close', {'handle': stream})
    except Exception as e:
        return None, f'ERR:CDP_READ_{type(e).__name__}'

    body = b''.join(chunks)
    if http_status and int(http_status) >= 400:
        return None, f'ERR:CDP_HTTP_{http_status}'
    if not body:
        return None, 'ERR:CDP_EMPTY'
    return body, 'OK'


def fetch_bytes_with_browser_session(driver, url, session=None, referer=None, timeout=60):
    url = normalize_media_url(driver, url)
    if not url:
        raise ValueError("empty media url")
    session = session or create_browser_session(driver)
    headers = {}
    if referer:
        headers["Referer"] = referer
    response = _session_get(session, url, headers=headers, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "text/html" in content_type.lower():
        raise ValueError("media request returned an HTML page")
    sample = response.content[:120].lstrip().lower()
    if sample.startswith(b"<!doctype html") or sample.startswith(b"<html"):
        raise ValueError("media request returned an HTML page")
    return response.content, content_type


def _element_screenshot_b64(element, log=None):
    """WebElement를 브라우저에서 직접 캡처해 base64(PNG) 반환. 실패 시 ''.

    프록시가 이미지 CDN을 차단(직접 다운로드·브라우저 fetch 모두 불가)해도
    화면에 이미 렌더링된 요소는 캡처할 수 있다. 화질은 표시 해상도 수준.
    """
    if element is None:
        return ""
    try:
        b64 = element.screenshot_as_base64
        return b64 or ""
    except Exception as e:
        if log:
            log(f"DEBUG: 요소 캡처 실패 - {type(e).__name__}: {e}")
        return ""


def get_profile_image_b64(driver, url, log=None):
    """프로필(아이 얼굴) 이미지를 가장 견고한 방법으로 확보해 base64 반환.

    순서: ① 브라우저 fetch(원본 화질, 사내망에서도 브라우저 네트워크는 대개 열림)
         ② 파이썬 requests 세션
         ③ 화면의 활성 아바타 요소 캡처(무엇도 안 될 때 최후, 표시 해상도)
    모두 실패하면 [KN-DIAG] 태그로 세 방법의 사유를 한 줄에 남긴다(사용자 복사용).
    """
    def _log(msg):
        if log:
            log(msg)

    fetch_r = req_r = shot_r = "미시도"

    # ① 브라우저 컨텍스트 fetch
    if url:
        try:
            data, status = _browser_fetch_media(driver, url, timeout=15)
            if data:
                _log("[KN-DIAG] 프로필 성공(브라우저fetch)")
                return base64.b64encode(data).decode('utf-8')
            fetch_r = status
        except Exception as e:
            fetch_r = f"EXC:{type(e).__name__}"
    else:
        fetch_r = "URL없음"

    # ② 파이썬 requests 세션
    if url:
        try:
            data, _ct = fetch_bytes_with_browser_session(driver, url, timeout=5)
            if data:
                _log("[KN-DIAG] 프로필 성공(requests)")
                return base64.b64encode(data).decode('utf-8')
            req_r = "빈응답"
        except Exception as e:
            req_r = f"EXC:{type(e).__name__}"
    else:
        req_r = "URL없음"

    # ③ 활성 아바타 요소 캡처 (네트워크 불필요)
    try:
        avatar = driver.find_element(By.CSS_SELECTOR, ACTIVE_AVATAR_CSS)
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", avatar)
        except Exception:
            pass
        shot = _element_screenshot_b64(avatar, log)
        if shot:
            _log("[KN-DIAG] 프로필 성공(화면캡처/표시해상도)")
            return shot
        shot_r = "캡처빈값"
    except Exception as e:
        shot_r = f"요소없음:{type(e).__name__}"

    _log(f"[KN-DIAG] 프로필 실패 | fetch={fetch_r} | requests={req_r} | capture={shot_r}")
    return ""


def _best_url_from_srcset(srcset):
    if not srcset:
        return ""
    best_url = ""
    best_size = -1.0
    for part in [p.strip() for p in srcset.split(",") if p.strip()]:
        tokens = part.split()
        if not tokens:
            continue
        size = 1.0
        if len(tokens) > 1:
            try:
                size = float(tokens[1].rstrip("wx"))
            except Exception:
                pass
        if size > best_size:
            best_size = size
            best_url = tokens[0]
    return best_url


def _extension_from_response(src, content_type):
    path = urlparse(src).path
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4', 'webm', 'mov']:
        return ext
    content_type = (content_type or "").lower()
    if "png" in content_type:
        return "png"
    if "gif" in content_type:
        return "gif"
    if "webp" in content_type:
        return "webp"
    if "jpeg" in content_type or "jpg" in content_type:
        return "jpg"
    if "webm" in content_type:
        return "webm"
    if "quicktime" in content_type:
        return "mov"
    if "video" in content_type or "mp4" in content_type:
        return "mp4"
    return "jpg"


def _debug_output_dir():
    """디버그 산출물 저장 폴더.

    단일 exe(PyInstaller onefile)에서는 __file__이 종료 시 삭제되는 임시폴더를 가리켜
    저장해도 사라진다. 사용자가 실제로 찾아볼 수 있는 로그 폴더로 통일한다.
    """
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "KidsnoteMemoriesSaver", "logs")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return os.path.dirname(os.path.abspath(__file__))
    return path


def _stop_requested(check_stop_callback):
    try:
        return bool(check_stop_callback and check_stop_callback())
    except Exception:
        return False


def _media_prefix(post_info):
    """게시물 정보로부터 미디어 파일명 prefix(YYMMDD_종류[_순번])를 생성합니다."""
    import re
    date_prefix = "unknown"
    try:
        date_str = post_info.get("date", "") or ""
        match_dot = re.search(r'(\d{4})\.?\s*(\d{1,2})\.?\s*(\d{1,2})', date_str)
        match_kor = re.search(r'(?:(\d{4})\s*년)?\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', date_str)
        current_year = datetime.date.today().year
        if match_dot:
            y, m, d = match_dot.groups()
        elif match_kor:
            y = match_kor.group(1) or current_year
            m = match_kor.group(2)
            d = match_kor.group(3)
        else:
            y, m, d = None, None, None
        if y and m and d:
            date_prefix = f"{str(y)[-2:]}{int(m):02d}{int(d):02d}"
    except Exception:
        date_prefix = "unknown"

    post_index = post_info.get('post_index', 0)
    item_type = post_info.get('type', '사진')
    return f"{date_prefix}_{item_type}" if post_index == 0 else f"{date_prefix}_{item_type}_{post_index}"


def _post_timestamp(post_info):
    """게시물 날짜를 파일 타임스탬프(epoch)로 변환. 실패 시 None.

    저장된 사진/PDF의 파일 시간을 게시물 날짜로 맞춰
    갤러리/탐색기에서 실제 추억 순서대로 정렬되게 한다.
    """
    import re
    date_str = post_info.get("date", "") or ""
    match_dot = re.search(r'(\d{4})\.?\s*(\d{1,2})\.?\s*(\d{1,2})', date_str)
    match_kor = re.search(r'(?:(\d{4})\s*년)?\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', date_str)
    try:
        if match_dot:
            y, m, d = match_dot.groups()
        elif match_kor:
            y = match_kor.group(1) or datetime.date.today().year
            m = match_kor.group(2)
            d = match_kor.group(3)
        else:
            return None
        return datetime.datetime(int(y), int(m), int(d), 12, 0, 0).timestamp()
    except Exception:
        return None


def _apply_post_timestamp(path, post_info):
    ts = _post_timestamp(post_info)
    if ts:
        try:
            os.utime(path, (ts, ts))
        except OSError:
            pass

def save_debug_snapshot(driver, step_name, log_func=print, mem=None):
    """
    현재 브라우저 창의 HTML 소스와 스크린샷을 지정된 폴더에 타임스탬프와 함께 저장합니다.
    디버깅용으로 오류 시점의 렌더링 상태를 확인하는 데 사용됩니다.
    HTML/스크린샷에는 자녀 사진·알림장 본문이 포함되므로 KIDSNOTE_DEBUG=1일 때만 동작합니다.
    """
    if not _debug_enabled():
        return
    try:
        now = datetime.datetime.now()
        date_folder = now.strftime("%Y%m%d")
        time_prefix = now.strftime("%H%M%S")
        
        # 실행 위치(os.getcwd)는 단일 exe에서 임시폴더일 수 있으므로 로그 폴더 기준으로 저장
        debug_dir = os.path.join(_debug_output_dir(), "Kidsnote_Debug_Logs", date_folder)
        os.makedirs(debug_dir, exist_ok=True)
        
        safe_step = "".join(c for c in step_name if c not in r'\/:*?"<>|').strip()
        base_filename = os.path.join(debug_dir, f"{time_prefix}_{safe_step}")
        
        html_content = ""
        if mem:
            mem_info = f"<!-- TARGET MEM INFO: Date: {mem.get('date')}, Title: {mem.get('title')}, URL: {mem.get('url')} -->\n"
            html_content += mem_info
            # 로그 출력에도 mem.title 추가
            log_func(f"[DEBUG LOG] 스냅샷 저장됨: {time_prefix}_{safe_step} (Target: {mem.get('title')})")
        else:
            log_func(f"[DEBUG LOG] 스냅샷 저장됨: {time_prefix}_{safe_step}")
            
        html_content += driver.page_source
        
        with open(base_filename + ".html", "w", encoding="utf-8") as f:
            f.write(html_content)
            
        driver.save_screenshot(base_filename + ".png")
    except Exception as e:
        log_func(f"[DEBUG LOG] 스냅샷 저장 실패: {e}")


def _scrape_list_pages(driver, item_type, memories, log,
                       request=None, callbacks=None, result_info=None):
    """
    Helper to scrape all pages of a list (Report or Album).
    Yields or callbacks items as they are found.
    limit_date_str(시작일)보다 오래된 게시물에서 탐색을 중단하고,
    end_date_str(종료일)보다 최신인 게시물은 건너뛴다 (목록은 최신순).
    result_info(dict)에 조회 결과 진단 정보를 기록해 GUI가
    '기간 내 항목 없음'과 '네트워크 실패'를 구분해 안내할 수 있게 한다.
    """
    request = request or ScrapeRequest()
    callbacks = callbacks or ScrapeCallbacks()
    item_found_callback = callbacks.item_found
    check_stop_callback = callbacks.check_stop
    limit_date_str = request.start_date
    end_date_str = request.end_date
    child_name = request.child_name

    info = result_info if isinstance(result_info, dict) else {}
    page_count = 1
    log(f"DEBUG: _scrape_list_pages 시작. 대상: {item_type}, 현재 URL: {driver.current_url}")
    while True:
        if check_stop_callback and check_stop_callback():
            log(f"DEBUG: {item_type} 수집 중지 요청 확인됨.")
            break

        # Wait for items to load (에러 화면이 뜨면 타임아웃을 기다리지 않고 즉시 빠져나옴)
        log(f"DEBUG: {page_count}페이지 로딩 대기 중 (최대 30초)...")
        wait_outcome = _wait_for_list_or_app_error(driver, timeout=30)
        if wait_outcome == 'error':
            log(f"DEBUG: {item_type} {page_count}페이지에서 키즈노트 자체 오류 화면 감지됨 (대기 중단).")
            info['app_error'] = True
            info['timeout'] = True
            break
        if wait_outcome == 'timeout':
            log(f"DEBUG: TimeoutException 발생. 현재 URL: {driver.current_url}")
            log(f"{item_type} {page_count}페이지 게시물을 찾을 수 없습니다.")
            info['timeout'] = True
            save_debug_snapshot(driver, f"Timeout_{item_type}_Page{page_count}", log)
            break

        info['list_loaded'] = True

        # 스켈레톤/부분 렌더링 대응: 카드 개수가 안정될 때까지 짧게 폴링.
        # (첫 카드 하나만 뜬 순간 수집을 시작해 '1개 수집 완료(빈 행)'로 끝나는 증상 방지)
        post_items = []
        used_fallback = False
        try:
            prev_count = -1
            stable_deadline = time.time() + 6
            while time.time() < stable_deadline:
                post_items, used_fallback = _find_post_cards(driver, log)
                if len(post_items) == prev_count and prev_count > 0:
                    break
                prev_count = len(post_items)
                time.sleep(0.4)
        except Exception:
            post_items, used_fallback = _find_post_cards(driver, log)

        if used_fallback:
            info['selector_fallback'] = True

        total_items = len(post_items)

        # 화면에는 내용이 잔뜩 떠 있는데 게시물을 하나도 인식하지 못했다면,
        # '게시물이 없는 것'이 아니라 키즈노트 화면 구성이 바뀌어 우리가 못 알아보는
        # 상황일 가능성이 높다. 사용자에게 구분해 안내하기 위해 표시해 둔다.
        if total_items == 0:
            try:
                link_count = driver.execute_script("return document.querySelectorAll('a[href]').length;") or 0
                body_len = driver.execute_script("return (document.body.innerText || '').length;") or 0
                if link_count > 20 and body_len > 500:
                    info['selector_broken'] = True
                    log("[KN-DIAG] 게시물 0개인데 화면에는 내용 있음(links=%s, text=%s) → 화면 구성 변경 의심"
                        % (link_count, body_len))
            except Exception:
                pass

        info['items_seen'] = info.get('items_seen', 0) + total_items
        log(f"DEBUG: 게시물 항목을 {total_items}개 찾음.")

        # ── 첫 번째 항목의 부모 요소를 포함한 HTML 저장 (교사명 위치 파악용, 디버그 모드 전용) ──
        if _debug_enabled() and page_count == 1 and total_items > 0:
            try:
                # 부모 요소까지 포함하여 저장 (교사명이 카드 바깥에 있을 수 있음)
                parent_html = driver.execute_script(
                    "return arguments[0].parentElement ? arguments[0].parentElement.outerHTML : arguments[0].outerHTML;",
                    post_items[0]
                )
                debug_item_path = os.path.join(_debug_output_dir(), "debug_post_item.html")
                with open(debug_item_path, "w", encoding="utf-8") as f:
                    f.write(parent_html)
                log(f"DEBUG: 부모 요소 HTML → {debug_item_path}")
            except Exception as _de:
                log(f"DEBUG: 항목 HTML 저장 실패: {_de}")

        
        new_items_found = 0
        filtered_items_count = 0
        duplicate_items_count = 0
        
        for idx, post in enumerate(post_items):
            if check_stop_callback and check_stop_callback():
                log("알림장/앨범 수집이 사용자에 의해 중지되었습니다.")
                return
            try:
                # 작성자 추출 1순위: 아바타 인접 구조 기반 (호칭 표기와 무관하게 동작)
                writer = ""
                try:
                    writer = (driver.execute_script(_WRITER_EXTRACT_JS, post) or "").strip()
                except Exception:
                    writer = ""

                # 2순위 폴백: 호칭 키워드(교사/엄마/아빠 등)가 포함된 짧은 줄
                if not writer:
                    try:
                        card_text = post.text or ""
                        for line in card_text.split('\n'):
                            line = line.strip()
                            if not line or len(line) > 25:
                                continue
                            if any(k in line for k in _WRITER_KEYWORDS):
                                writer = line
                                break
                    except Exception:
                        pass

                if not writer:
                    writer = "알 수 없음"

                # 사진 유무 판별 (img 태그가 하나라도 있으면 O)
                has_photo = "O" if len(post.find_elements(By.TAG_NAME, "img")) > 0 else "X"

                # 날짜 추출
                try:
                    date_elem = post.find_element(By.XPATH, CARD_DATE_XPATH)
                    raw_date = date_elem.text.strip()
                except NoSuchElementException:
                    try:
                        date_elem = post.find_element(By.CLASS_NAME, CARD_DATE_CLASS).find_element(By.TAG_NAME, "span")
                        raw_date = date_elem.text.strip()
                    except Exception:
                        # 클래스가 바뀐 경우: 카드 텍스트에서 날짜 형태를 직접 찾는다
                        raw_date = _first_date_like_line(post) or "날짜 알 수 없음"
                date = raw_date
                if date != "날짜 알 수 없음" and date:
                    import re, datetime
                    match_dot = re.search(r'(\d{4})\.?\s*(\d{1,2})\.?\s*(\d{1,2})', date)
                    match_kor = re.search(r'(?:(\d{4})\s*년)?\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', date)
                    current_year = datetime.date.today().year
                    if match_dot:
                        y, m, d = match_dot.groups()
                        date = f"{y}.{int(m):02d}.{int(d):02d}"
                    elif match_kor:
                        y = match_kor.group(1) or current_year
                        m = match_kor.group(2)
                        d = match_kor.group(3)
                        date = f"{y}.{int(m):02d}.{int(d):02d}"
                
                # 제목/내용 추출
                try:
                    # 알림장의 경우 보통 본문이 제목 역할을 함
                    title_elem = post.find_element(By.XPATH, CARD_BODY_XPATH)
                    full_text = title_elem.text.strip()
                    title = full_text[:35].replace('\n', ' ') + "..." if len(full_text) > 35 else full_text.replace('\n', ' ')
                except NoSuchElementException:
                    try:
                        title_elem = post.find_element(By.CLASS_NAME, CARD_BODY_CLASS)
                        title = title_elem.text.strip()[:35]
                    except Exception:
                        # 클래스가 바뀐 경우: 카드 텍스트에서 날짜/작성자가 아닌 가장 긴 줄을 본문으로 본다
                        title = _longest_content_line(post) or "제목 알 수 없음"
                
                url = None
                try:
                    link_elem = post.find_element(By.TAG_NAME, "a")
                    url = link_elem.get_attribute("href")
                except Exception:
                    pass

                if end_date_str and date and date != "날짜 알 수 없음" and date > end_date_str:
                    # 종료일보다 최신 게시물은 건너뛰고 계속 탐색 (더 과거로 내려가면 범위에 들어옴)
                    filtered_items_count += 1
                    info['filtered_out'] = info.get('filtered_out', 0) + 1
                    continue

                if limit_date_str and date and date != "날짜 알 수 없음":
                    if date < limit_date_str:
                        log(f"DEBUG: 게시물 날짜({date})가 제한 날짜({limit_date_str})보다 이전이므로 이 페이지부터 탐색을 중단합니다.")
                        # 리스트는 최신순이므로 하나라도 더 과거라면 뒷페이지는 전부 스킵합니다.
                        filtered_items_count += 1
                        info['filtered_out'] = info.get('filtered_out', 0) + 1
                        return
                
                # 날짜도 제목도 없는 빈(스켈레톤) 카드는 수집하지 않는다
                if (not date or date == "날짜 알 수 없음") and (not title or title == "제목 알 수 없음"):
                    log(f"DEBUG: 항목 {idx}: 빈(스켈레톤) 카드로 판단되어 제외")
                    continue

                item_id = f"{item_type}_{date}_{title}_{url}"
                if not any(m.get('id') == item_id for m in memories):
                    new_mem = {
                        'id': item_id,
                        'date': date,
                        'title': title,
                        'type': item_type,
                        'writer': writer,
                        'has_photo': has_photo,
                        'url': url,
                        'page': page_count,
                        'index': idx,
                        'child_name': child_name,
                        'element': post
                    }
                    memories.append(new_mem)
                    new_items_found += 1
                    if item_found_callback:
                        item_found_callback(new_mem)
                else:
                    duplicate_items_count += 1
            except Exception as inner_e:
                log(f"DEBUG: 항목 {idx} 파싱 중 예외 발생: {type(inner_e).__name__}")
                continue
        
        log(f"{item_type} {page_count}페이지 완료 (수집: {new_items_found}개, 제외 등: {filtered_items_count}개, 중복: {duplicate_items_count}개) 총 {len(memories)}개 수집됨")
        
        if total_items > 0 and duplicate_items_count == total_items:
            # 발견된 항목이 모두 기존에 수집된(중복) 항목일 경우 무한루프로 간주하고 중단
            log(f"DEBUG: 새로운 항목이 없습니다 (모두 중복됨). 탐색 종료.")
            break
        elif total_items == 0:
            log(f"DEBUG: 게시물이 존재하지 않습니다. 탐색 종료.")
            break
            
        # Try to navigate to next page
        try:
            log(f"DEBUG: '다음' 버튼 찾는 중...")
            # '다음' 텍스트를 정확하게 포함하는 span을 가진 button만 찾음 (이전 버튼 제외)
            next_buttons = driver.find_elements(By.XPATH, NEXT_PAGE_XPATH)
            log(f"DEBUG: '다음' 버튼 요소 {len(next_buttons)}개 발견.")
            
            found_clickable_next = False
            for btn_idx, btn in enumerate(next_buttons):
                is_disabled = btn.get_attribute("disabled") or "disabled" in (btn.get_attribute("class") or "").lower()
                is_displayed = btn.is_displayed()
                log(f"DEBUG: 버튼 {btn_idx} - is_displayed: {is_displayed}, is_disabled: {is_disabled}, 태그: {btn.tag_name}")
                if not is_disabled and is_displayed:
                    log(f"DEBUG: 클릭 가능한 '다음' 버튼 클릭 시도 (인덱스 {btn_idx}).")
                    driver.execute_script("arguments[0].click();", btn)
                    found_clickable_next = True
                    break
            
            if not found_clickable_next:
                log(f"{item_type} 마지막 페이지에 도달했습니다.")
                break
                
            page_count += 1
            if post_items:
                try:
                    WebDriverWait(driver, 5).until(EC.staleness_of(post_items[0]))
                except Exception:
                    time.sleep(1) # Fallback
        except Exception as e:
            log(f"페이지 이동 중 오류: {e}")
            break


def navigate_to_memory_view(driver, item_type_label, log_func, target_child=None):
    """
    홈 화면에서부터 선택한 아이로 전환한 후 '추억보기' 메뉴를 통해 전체보기 화면으로 진입합니다.
    URL이 누락된 항목을 수집하거나 탐색할 때 SPA의 뷰 버퍼를 재동기화하는 강력한 방법입니다.
    """
    # 목록에 들어가기까지 어느 단계에서 시간이 가는지 남긴다.
    # '이미 화면에 다 떠 있는데도 한참 기다린다'는 체감을 확인하려면
    # 추측이 아니라 단계별 실제 소요를 봐야 한다. (진단정보 복사에 함께 담긴다)
    _t0 = time.time()

    def _mark(step):
        log_func("[KN-DIAG] 소요 %s: %s %.1f초" % (item_type_label, step, time.time() - _t0))

    try:
        # 이미 /service 홈에 떠 있으면(반복 조회 등) SPA 전체 리로드를 생략해 시간 절약
        if not _is_on_service_home(driver):
            driver.get("https://www.kidsnote.com/service")
            _mark("홈 재로드")
        # 프로필 아바타가 렌더링되는 즉시 진행 (고정 2초 대기 제거)
        wait_css(driver, ANY_AVATAR_CSS, timeout=10)
        _mark("아바타 렌더링까지")

        if target_child:
            try:
                log_func(f"아이 전환 확인 중 (이름: {target_child})...")
                script = """
                    var target = arguments[0];
                    var spans = document.querySelectorAll("span[role='img']");
                    for(var i=0; i<spans.length; i++){
                        var parent = spans[i].parentElement.parentElement;
                        if(parent && parent.innerText && parent.innerText.includes(target)) {
                            spans[i].click();
                            return true;
                        }
                    }
                    return false;
                """
                matched = driver.execute_script(script, target_child)
                if not matched:
                    log_func(f"[KN-DIAG] 아이 매칭 실패(이름: {target_child}) → 재진입 시도")
                time.sleep(0.5)
                driver.get("https://www.kidsnote.com/service")
                wait_css(driver, ANY_AVATAR_CSS, timeout=10)
            except Exception as e:
                log_func(f"아이 전환 중 예외 (무시): {e}")

        # 참고: 예전에는 '전체보기 버튼이 보이면 메뉴 클릭 생략' 지름길이 있었으나 제거했다.
        # SPA는 URL이 /service 그대로라 이전 아이의 잔상 화면을 '이미 추억보기'로 오판할 수 있어,
        # 아이 매칭 후에는 항상 추억보기 메뉴를 눌러 해당 아이의 목록으로 확실히 진입한다.
        clicked = False

        # 추억보기 1순위 클릭
        if not clicked:
            try:
                mem_btn = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[contains(@class,'" + MEMORY_MENU_CLASS + "') and contains(.,'추억보기')]"))
                )
                driver.execute_script("arguments[0].click();", mem_btn)
                _mark("추억보기 클릭까지")
                clicked = True
            except Exception:
                pass
            
        # 추억보기 2순위 드롭다운 클릭
        if not clicked:
            try:
                toggle = driver.find_element(By.XPATH, SIDEBAR_MENU_XPATH)
                driver.execute_script("arguments[0].click();", toggle)
                mem_link = WebDriverWait(driver, 15).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[contains(@class,'" + MEMORY_MENU_LINK_CLASS + "') and contains(.,'추억보기')]"))
                )
                driver.execute_script("arguments[0].click();", mem_link)
            except Exception as e:
                log_func(f"추억보기 진입 모두 실패: {e}")

        # 전체보기 클릭
        try:
            # 실제 대기는 아래 WebDriverWait(전체보기 버튼 감지)가 담당한다 → 뜨는 즉시 진행
            if item_type_label == "앨범":
                try:
                    target_btn = WebDriverWait(driver, 10).until(
                        lambda d: (lambda btns: btns[1] if len(btns) >= 2 else None)([b for b in d.find_elements(By.XPATH, VIEW_ALL_XPATH) if b.is_displayed()])
                    )
                except TimeoutException:
                    btns = [b for b in driver.find_elements(By.XPATH, VIEW_ALL_XPATH) if b.is_displayed()]
                    target_btn = btns[0] if btns else None
            else:
                target_btn = WebDriverWait(driver, 10).until(
                    lambda d: (lambda btns: btns[0] if btns else None)([b for b in d.find_elements(By.XPATH, VIEW_ALL_XPATH) if b.is_displayed()])
                )

            if target_btn:
                _mark("전체보기 버튼 찾기까지")
                driver.execute_script("arguments[0].click();", target_btn)
            else:
                # 버튼이 안 보인다고 바로 포기하지 않는다. 해당 목록은 고유 주소가 있으므로
                # 주소로 직접 이동해서라도 진입한다. (앨범 진입이 종종 실패하던 원인)
                log_func(f"{item_type_label} 전체보기 버튼이 보이지 않아 주소로 직접 이동합니다.")
                driver.get(SECTION_URLS[item_type_label])
        except Exception as e:
            log_func(f"전체보기 버튼 클릭 실패: {e} → 주소로 직접 이동합니다.")
            try:
                driver.get(SECTION_URLS[item_type_label])
            except Exception:
                return False

        # 엉뚱한 목록으로 갔는지 확인한다.
        # 앨범인데 '전체보기' 버튼이 하나뿐이면 알림장 버튼을 누르게 되어,
        # 알림장 글이 앨범으로 수집되는 조용한 오염이 생길 수 있다.
        try:
            expected = SECTION_URLS[item_type_label]
            marker = expected.rsplit("/", 1)[-1]          # 'report' 또는 'album'
            WebDriverWait(driver, 5).until(lambda d: marker in (d.current_url or ""))
        except Exception:
            log_func(f"{item_type_label} 화면이 아닌 곳으로 이동한 것 같아 주소로 다시 진입합니다. (현재: {driver.current_url})")
            try:
                driver.get(SECTION_URLS[item_type_label])
            except Exception:
                return False

        # 목록 항목 대기 (에러 화면이 뜨면 타임아웃을 기다리지 않고 즉시 빠져나옴)
        outcome = _wait_for_list_or_app_error(driver, timeout=30)
        if outcome == 'items':
            _mark("목록이 뜰 때까지(합계)")
            return True
        if outcome == 'error':
            log_func(f"{item_type_label} 목록 대신 키즈노트 자체 오류 화면이 감지되었습니다.")
            return False
        log_func(f"{item_type_label} 목록 대기 시간 초과")
        return False
    except Exception as e:
        log_func(f"Memory view 진입 중 큰 예외 발생: {e}")
        return False
        


class ScrapeRequest(object):
    """무엇을 조회할지. 조회 한 번에 대한 요청서다.

    인자 열한 개를 늘어놓던 것을 묶었다. 그중 다섯은 '무엇을 조회할지'(여기),
    넷은 '진행 상황을 어디로 알릴지'(ScrapeCallbacks), 하나는 결과 진단용이라
    성격이 서로 달랐다.

    start_date / end_date 는 'yyyy.mm.dd' 문자열이다. 둘 다 None 이면 기간을
    가리지 않고 전부 가져온다 (화면의 [전체]).
    """

    __slots__ = ('reports', 'albums', 'start_date', 'end_date', 'child_name')

    def __init__(self, reports=True, albums=True,
                 start_date=None, end_date=None, child_name=None):
        self.reports = reports          # 알림장을 가져올까
        self.albums = albums            # 앨범을 가져올까
        self.start_date = start_date    # 이 날짜보다 오래된 글은 건너뛴다
        self.end_date = end_date        # 이 날짜보다 최근 글은 건너뛴다
        self.child_name = child_name    # 이 아이로 전환한 뒤 조회한다

    @property
    def labels(self):
        """조회할 대상 이름들. 화면 표기와 같은 말을 쓴다."""
        names = []
        if self.reports:
            names.append("알림장")
        if self.albums:
            names.append("앨범")
        return names

    def __repr__(self):
        return "ScrapeRequest(reports=%r, albums=%r, %s~%s)" % (
            self.reports, self.albums, self.start_date, self.end_date)


class ScrapeCallbacks(object):
    """조회하면서 알려 줄 곳들. 모두 없어도 된다(그러면 조용히 진행한다).

    엔진이 GUI를 직접 만지지 않게 하려고 함수로 받는다. 무엇을 하는 함수인지는
    부르는 쪽이 정한다. GUI는 여기에 Qt 시그널을 꽂아 화면을 갱신한다.
    """

    __slots__ = ('status', 'item_found', 'profile_found', 'check_stop')

    def __init__(self, status=None, item_found=None,
                 profile_found=None, check_stop=None):
        self.status = status                # 진행 문구 한 줄
        self.item_found = item_found        # 게시물 하나를 찾을 때마다
        self.profile_found = profile_found  # 아이 프로필을 확보했을 때
        self.check_stop = check_stop        # 사용자가 중지를 눌렀는지 물어볼 함수

    def stopped(self):
        return bool(self.check_stop and self.check_stop())


def fetch_memory_list(driver, request=None, callbacks=None, result_info=None):
    """알림장과 앨범 목록을 훑어 게시물 정보를 모아 온다.

    request(ScrapeRequest)가 무엇을 가져올지, callbacks(ScrapeCallbacks)가
    진행 상황을 어디로 알릴지 정한다. 생략하면 기본값으로 전부 조회한다.

    아이 이름이 주어지면 먼저 그 아이로 전환한 뒤 조회한다.

    result_info(dict)를 넘기면 조회 결과 진단 정보를 기록한다
    (list_loaded / items_seen / filtered_out / timeout / nav_failed).
    '기간 안에 글이 없었다'와 '조회가 실패했다'는 둘 다 0건으로 끝나지만
    사용자에게는 전혀 다른 이야기라, GUI가 이 값을 보고 구분해서 안내한다.
    """
    request = request or ScrapeRequest()
    callbacks = callbacks or ScrapeCallbacks()

    status_callback = callbacks.status
    item_found_callback = callbacks.item_found
    check_stop_callback = callbacks.check_stop
    profile_found_callback = callbacks.profile_found
    scrape_reports = request.reports
    scrape_albums = request.albums
    limit_date_str = request.start_date
    end_date_str = request.end_date
    child_name = request.child_name

    def log(msg):
        print(msg) # 터미널에도 출력
        if status_callback and 'DEBUG' not in msg:
            status_callback(msg)

    info = result_info if isinstance(result_info, dict) else {}
    memories = []

    # 0. /service 홈으로 이동 후 아이 전환 (이미 홈이면 리로드 생략)
    log("서비스 페이지로 이동 중...")
    if not _is_on_service_home(driver):
        driver.get("https://www.kidsnote.com/service")
    # React Hydration 완료(아바타 렌더링)를 감지하는 즉시 진행 (고정 1초 대기 제거)
    wait_css(driver, ANY_AVATAR_CSS, timeout=10)

    if child_name is not None:
        try:
            log(f"아이 전환 확인 중 (이름: {child_name})...")
            # 대상 아이 아바타가 이미 활성(size=65) 상태면 'already'를 반환해
            # 클릭·리로드를 통째로 생략한다 → 같은 아이로 반복 조회 시 크게 빨라짐.
            script = """
                var target = arguments[0];
                var spans = document.querySelectorAll("span[role='img']");
                for(var i=0; i<spans.length; i++){
                    var parent = spans[i].parentElement.parentElement;
                    if(parent && parent.innerText && parent.innerText.includes(target)) {
                        if(spans[i].getAttribute('size') === '65') { return 'already'; }
                        spans[i].click();
                        return 'switched';
                    }
                }
                return 'notfound';
            """
            switch_result = driver.execute_script(script, child_name)
            if switch_result == 'already':
                log(f"DEBUG: '{child_name}' 이미 선택된 상태 → 전환/리로드 생략")
            else:
                time.sleep(0.5) # 클릭 후 정보 변경 대기
                # 아이 전환 직후에는 라우팅 꼬임을 방지하기 위해 홈으로 리프레시
                driver.get("https://www.kidsnote.com/service")
                wait_css(driver, ANY_AVATAR_CSS, timeout=10)
        except Exception as e:
            log(f"아이 전환 중 오류 (무시됨): {e}")

    # 주의: 예전에는 여기서 추억보기 메뉴를 미리 한 번 클릭했으나 제거했다.
    # SPA는 URL이 /service 그대로인 채 화면만 바뀌므로, 미리 클릭해 두면
    # navigate_to_memory_view가 '홈'으로 오판해 사라진 메뉴 버튼을 20초+15초씩
    # 기다리는 지연('알림장 추억 목록 조회 중' 멈춤 증상)의 원인이 됐다.
    # 프로필 추출(아래)은 홈 화면의 활성 아바타로 충분하다.
    if _debug_enabled():
        try:
            sidebar_html = driver.execute_script(
                "var s = document.querySelector('nav') || document.querySelector('[class*=\"sidebar\"]') || document.querySelector('aside');"
                "return s ? s.outerHTML : document.body.innerHTML.substring(0, 30000);"
            )
            debug_path = os.path.join(_debug_output_dir(), "debug_sidebar.html")
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(f"<!-- URL: {driver.current_url} -->\n" + (sidebar_html or ""))
            log(f"DEBUG: 사이드바 HTML → {debug_path}")
        except Exception as _se:
            log(f"DEBUG: 사이드바 저장 실패: {_se}")


    # 1.5 Extract Profile
    try:
        script = (
            'var activeSpan = document.querySelector("span[size=\'65\'][role=\'img\']");'
            'if(activeSpan) {'
            '  var container = activeSpan.parentElement;'
            '  var img = activeSpan.querySelector("img");'
            '  var imgUrl = img ? (img.currentSrc || img.src || "") : "";'
            '  var bg = window.getComputedStyle(activeSpan).backgroundImage || "";'
            '  var match = bg.match(/url\\(["\\\']?([^"\\\')]+)["\\\']?\\)/);'
            '  var url = imgUrl || (match ? match[1] : "");'
            '  var pTags = container.querySelectorAll("p");'
            '  var name = pTags.length > 0 ? pTags[0].textContent.trim() : container.textContent.trim();'
            '  var age = pTags.length > 1 ? pTags[1].textContent.trim() : "";'
            '  return [name, age, url];'
            '}'
            'return null;'
        )

        result = driver.execute_script(script)
        if result:
            name, age, url = result
            profile_text = f"{name} {age}".strip()
            log(f"프로필 획득: {profile_text}")
            
            # 브라우저 fetch → requests → 요소 캡처 순으로 가장 견고하게 확보
            img_b64 = get_profile_image_b64(driver, url, log) or None

            if profile_found_callback:
                profile_found_callback({"text": profile_text, "image": img_b64})
        else:
            log("활성화된 프로필 엘리먼트를 찾지 못했습니다 (무시됨)")
    except Exception as e:
        log(f"프로필 정보 획득 실패 (무시됨) - {e}")

    def _scrape_type_with_retry(label):
        """한 종류(알림장/앨범)를 조회하고, 비정상적으로 0건이면 강제 새로고침 후 재시도.

        SPA 상태가 꼬여 첫 조회가 조용히 실패하는 경우('조회 못 해놓고 완료' 증상)를
        사용자가 다시 누르지 않아도 자동으로 복구한다.
        키즈노트 웹 자체가 내부 예외로 죽어 "아이쿠! 에러가 발생했습니다" 화면이 뜨는 경우는
        일반 타임아웃보다 한 번 더 회복을 시도할 가치가 있어 최대 시도 횟수를 3회로 둔다.
        """
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            attempt_info = {}
            nav_ok = False
            before = len(memories)
            if navigate_to_memory_view(driver, label, log, target_child=None):
                nav_ok = True
                log(f"{label} 전수 조사를 시작합니다...")
                _scrape_list_pages(driver, label, memories, log,
                                   request=request, callbacks=callbacks,
                                   result_info=attempt_info)
            collected = len(memories) - before

            app_error = collected == 0 and (attempt_info.get('app_error') or _detect_kidsnote_app_error(driver))
            if app_error:
                log(f"[KN-DIAG] {label} 조회 중 키즈노트 웹 자체 오류 화면이 감지됨 (시도 {attempt}/{max_attempts})")

            # 비정상 0건 판단: 진입 실패 / 타임아웃 / 카드가 보였는데 전부 파싱 불가(스켈레톤)
            #   + 날짜 필터가 없는데 카드 자체가 0개(= SPA가 아직 안 뜬 것으로 의심)
            #   + 키즈노트 자체 에러 바운더리 화면
            parse_failed = (
                attempt_info.get('items_seen', 0) > 0
                and attempt_info.get('filtered_out', 0) == 0
            )
            no_items_unfiltered = (
                attempt_info.get('items_seen', 0) == 0
                and attempt_info.get('filtered_out', 0) == 0
            )
            abnormal_empty = collected == 0 and (
                not nav_ok or attempt_info.get('timeout') or parse_failed or no_items_unfiltered or app_error
            )
            stopped = bool(check_stop_callback and check_stop_callback())
            if attempt < max_attempts and abnormal_empty and not stopped:
                if app_error:
                    log(f"{label} 조회 중 키즈노트 웹사이트 자체 오류가 발생하여 화면을 새로 고친 뒤 다시 시도합니다...")
                else:
                    log(f"{label} 조회가 비정상 종료되어 화면을 새로 고친 뒤 한 번 더 시도합니다...")
                driver.get("https://www.kidsnote.com/service")
                wait_css(driver, ANY_AVATAR_CSS, timeout=10)
                continue

            # 마지막 시도의 진단 정보만 최종 info에 반영 (재시도 성공 시 첫 실패 흔적은 제거)
            if not nav_ok:
                info['nav_failed'] = True
            if app_error:
                info['app_error'] = True
            for key, value in attempt_info.items():
                if isinstance(value, bool):
                    info[key] = info.get(key) or value
                else:
                    info[key] = info.get(key, 0) + value
            return

    # 2. 알림장 수집 — 추억보기 → 전체보기 진입
    if scrape_reports:
        if check_stop_callback and check_stop_callback(): return memories
        log("알림장 추억 목록 조회 중...")
        try:
            _scrape_type_with_retry("알림장")
        except Exception as e:
            log(f"알림장 조회 실패: {type(e).__name__} - {str(e)}")

    # 3. 앨범 수집 — 추억보기 → 전체보기 진입
    if scrape_albums:
        if check_stop_callback and check_stop_callback(): return memories
        log("앨범 추억 목록 조회 중...")
        try:
            _scrape_type_with_retry("앨범")
        except Exception as e:
            log(f"앨범 조회 실패: {type(e).__name__} - {str(e)}")

    album_count = len([m for m in memories if m['type'] == '앨범'])
    report_count = len([m for m in memories if m['type'] == '알림장'])
    log(f"최종 조회 완료: 알림장 {report_count}개, 앨범 {album_count}개 수집.")

    return memories


def download_as_pdf(driver, post_info, target_path, status_callback=None, check_stop_callback=None):
    """
    Saves the currently open post detail page as a PDF using CDP.
    """
    def log(msg):
        if status_callback and 'DEBUG' not in msg:
            status_callback(msg)

    try:
        if _stop_requested(check_stop_callback):
            log("다운로드가 중지되었습니다.")
            return False
        # 페이지 로딩 완료까지 충분히 대기 (앨범의 경우 본문 텍스트가 없을 수 있어 이미지라도 뜨면 통과하도록 조건 변경)
        try:
            WebDriverWait(driver, 10).until(
                lambda d: d.find_elements(By.CLASS_NAME, ALBUM_BODY_CLASS) or d.find_elements(By.TAG_NAME, "img")
            )
        except Exception:
            pass
        if _sleep_with_stop(2, check_stop_callback):  # 댓글 섹션 렌더링 추가 대기
            log("다운로드가 중지되었습니다.")
            return False
            
        # 1. 페이지 전체 스크롤을 단계별로 내려서 레이지 로딩 타겟(댓글창, 이미지 등)을 모두 불러옴
        try:
            raw_height = driver.execute_script("return document.body.scrollHeight")
            total_height = int(raw_height if raw_height else 2000)
            for i in range(1, total_height + 1, 800):
                if _stop_requested(check_stop_callback):
                    log("다운로드가 중지되었습니다.")
                    return False
                driver.execute_script(f"window.scrollTo(0, {i});")
                time.sleep(0.5)
        except Exception as scroll_e:
            pass
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        if _sleep_with_stop(3, check_stop_callback):  # 마지막 하단 댓글/이미지 렌더링 넉넉히 대기
            log("다운로드가 중지되었습니다.")
            return False
            
        # 2. 하단까지 스크롤되어 표시된 댓글 더보기 버튼 반복 클릭 (접힌 댓글 펼치기)
        try:
            max_attempts = 20
            for _ in range(max_attempts):
                if _stop_requested(check_stop_callback):
                    log("다운로드가 중지되었습니다.")
                    return False
                # '전체보기', '더보기' 등 오탐 제외 — 댓글 전용 키워드만 사용
                btns = driver.find_elements(By.XPATH,
                    "//*["
                    "contains(text(),'이전 댓글') or "
                    "contains(text(),'댓글 더보기') or "
                    "contains(text(),'전체 댓글') or "
                    "contains(text(),'이전 댓글 보기') or "
                    "contains(text(),'답글 보기') or "
                    "contains(text(),'대댓글')"
                    "]"
                )
                clicked = False
                for btn in btns:
                    try:
                        if btn.is_displayed():
                            driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                            time.sleep(0.3)
                            driver.execute_script("arguments[0].click();", btn)
                            clicked = True
                            if _sleep_with_stop(1.5, check_stop_callback):
                                log("다운로드가 중지되었습니다.")
                                return False
                    except Exception:
                        pass
                if not clicked:
                    break
        except Exception as comment_e:
            pass

        # 3. 댓글이 다 펼쳐지고 난 뒤 문서 전체 높이가 늘어났을 수 있으므로 다시 한번 맨 아래로 스크롤
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1) # 최종 화면 안정화 대기
        if _stop_requested(check_stop_callback):
            log("다운로드가 중지되었습니다.")
            return False
        
        # PDF 출력 시 스크롤 박스에 갇힌 내용이 잘리는 것을 방지하기 위해 인쇄용 CSS(media print) 주입. 
        # 원본 레이아웃(Flex 등)을 파괴하지 않기 위해 height: auto는 최상단에만 적용.
        driver.execute_script("""
            var style = document.createElement('style');
            style.innerHTML = `
                @media print {
                    * {
                        contain: none !important;
                    }
                    html, body, #root, main, div, section, article {
                        height: auto !important;
                        max-height: none !important;
                        overflow: visible !important;
                        position: static !important;
                    }
                    /* 사이드바 메인메뉴 등 불필요한 고정 UI 숨김 */
                    nav, aside, header {
                        display: none !important;
                    }
                    /* 댓글 영역 등이 인쇄 방지 속성으로 숨겨지는 것 강제 해제 */
                    [data-is-printable="false"] {
                        display: block !important;
                    }
                }
            `;
            document.head.appendChild(style);
        """)
        
        log(f"PDF 저장 중: {os.path.basename(target_path)}")

        print_options = {
            'landscape': False,
            'displayHeaderFooter': False,
            'printBackground': True,
            'scale': 0.85,
            'marginTop': 0.5,
            'marginBottom': 0.5,
            'marginLeft': 0.5,
            'marginRight': 0.5,
        }
        
        result = driver.execute_cdp_cmd("Page.printToPDF", print_options)
        
        with open(target_path, "wb") as f:
            f.write(base64.b64decode(result['data']))
        _apply_post_timestamp(target_path, post_info)

        log("PDF 저장 완료.")
        return True
    except Exception as e:
        log(f"PDF 저장 오류: {e}")
        return False

def download_photos_only(driver, post_info, target_dir, status_callback=None, check_stop_callback=None, include_video=True, prefer_browser_fetch=False):
    """
    Downloads only images from the currently open post detail page.
    include_video=False면 동영상(video/source 태그, 동영상 확장자)은 건너뛴다.
    prefer_browser_fetch=True면 (사전 점검에서 직접 접근 차단이 확인된 경우)
    requests 시도를 생략하고 곧바로 브라우저 경유 다운로드를 사용한다.
    """
    def log(msg):
        if status_callback and 'DEBUG' not in msg:
            status_callback(msg)

    try:
        if _stop_requested(check_stop_callback):
            log("다운로드가 중지되었습니다.")
            return False
        try:
            # 앨범의 경우 본체 로딩 확인을 위해 넉넉한 대기 필요
            WebDriverWait(driver, 10).until(
                lambda d: len(d.find_elements(By.TAG_NAME, "img")) > 1 or d.find_elements(By.CLASS_NAME, ALBUM_BODY_CLASS)
            )
        except Exception:
            pass 
        if _sleep_with_stop(2.0, check_stop_callback):  # 레이지 로딩된 이미지 태그가 DOM에 붙는 시간을 충분히 기다림
            log("다운로드가 중지되었습니다.")
            return False
            
        # 스크롤 최적화 복구: 보폭이 너무 넓거나 대기시간이 짧으면(0.1초 등) 화면의 이미지들이 로드 요청을 쏘지 못함
        try:
            raw_height = driver.execute_script("return document.body.scrollHeight")
            total_height = int(raw_height if raw_height else 3000)
            for i in range(1, total_height + 1, 800):
                if _stop_requested(check_stop_callback):
                    log("다운로드가 중지되었습니다.")
                    return False
                driver.execute_script(f"window.scrollTo(0, {i});")
                time.sleep(0.4)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            if _sleep_with_stop(1.5, check_stop_callback):  # 마지막 이미지 로딩 대기
                log("다운로드가 중지되었습니다.")
                return False
        except Exception as scroll_e:
            pass
        
        if not os.path.exists(target_dir):
            os.makedirs(target_dir, exist_ok=True)
            
        # 카카오 CDN/키즈노트 인증을 위해 Selenium의 로그인 쿠키/UA를 파이썬 리퀘스트 세션에 복사
        session = create_browser_session(driver)

        raw_media = driver.execute_script("""
            const items = [];
            const add = (url, kind, w, h, dw, dh) => {
              if (url) items.push({url, kind, w: w || 0, h: h || 0, dw: dw || 0, dh: dh || 0});
            };
            document.querySelectorAll('img').forEach(img => {
              const dw = img.offsetWidth || 0, dh = img.offsetHeight || 0;
              [
                img.currentSrc,
                img.src,
                img.getAttribute('data-original-url'),
                img.getAttribute('data-original'),
                img.getAttribute('data-src'),
                img.getAttribute('data-big'),
                img.getAttribute('data-url')
              ].forEach(url => add(url, 'image', img.naturalWidth, img.naturalHeight, dw, dh));
              add(img.getAttribute('srcset'), 'srcset', img.naturalWidth, img.naturalHeight, dw, dh);
              const parentLink = img.closest('a');
              if (parentLink) add(parentLink.href, 'image-link', img.naturalWidth, img.naturalHeight, dw, dh);
            });
            document.querySelectorAll('video').forEach(video => {
              add(video.currentSrc || video.src, 'video', video.videoWidth, video.videoHeight, video.offsetWidth, video.offsetHeight);
              video.querySelectorAll('source').forEach(source => add(source.src || source.getAttribute('src'), 'video', 0, 0, video.offsetWidth, video.offsetHeight));
            });
            document.querySelectorAll('source').forEach(source => add(source.src || source.getAttribute('src'), 'source', 0, 0, 0, 0));
            document.querySelectorAll('*').forEach(el => {
              const bg = window.getComputedStyle(el).backgroundImage;
              if (bg && bg.includes('url(')) {
                const matches = bg.match(/url\\(["']?([^"')]+)["']?\\)/g) || [];
                matches.forEach(match => {
                  const url = match.replace(/^url\\(["']?/, '').replace(/["']?\\)$/, '');
                  add(url, 'background', el.offsetWidth, el.offsetHeight, el.offsetWidth, el.offsetHeight);
                });
              }
            });
            return items;
        """)

        media_srcs = []
        seen_srcs = set()
        for item in raw_media or []:
            raw_url = item.get("url", "")
            if item.get("kind") == "srcset":
                raw_url = _best_url_from_srcset(raw_url)
            src = normalize_media_url(driver, raw_url)
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
            # 프로필 아바타 제외: (1) 아바타 썸네일 URL 패턴(img_36x36/65x65/130x130/240x240) — 강한 신호,
            # (2) 화면에 아주 작게(<=90px, 앨범 썸네일 그리드는 보통 150px+이므로 안전) 표시되는 이미지
            is_small_display = 0 < disp <= 90
            is_avatar_thumb = bool(re.search(r'img_(36x36|65x65|130x130|240x240)\.', path_only))
            if (
                lower_src.endswith(".svg")
                or is_small_display
                or is_avatar_thumb
                or (looks_like_ui_asset and is_tiny_ui_asset)
                or (looks_like_ui_asset and width == 0 and height == 0)
            ):
                continue
            if src in seen_srcs:
                continue
            seen_srcs.add(src)
            media_srcs.append(src)

        # 화면에 렌더링된 '크게 표시되는' 이미지 요소 목록 (URL 다운로드가 전부 막히면 캡처 폴백)
        # 표시 크기(offsetWidth) 기준으로 걸러 프로필 아바타 같은 작은 이미지는 제외한다.
        large_img_elements = []
        try:
            for _img in driver.find_elements(By.TAG_NAME, "img"):
                try:
                    disp_w = int(_img.get_attribute("offsetWidth") or 0)
                    nat_w = int(_img.get_attribute("naturalWidth") or 0)
                    src_attr = (_img.get_attribute("src") or "").lower().split("?")[0]
                    if re.search(r'img_(36x36|65x65|130x130|240x240)\.', src_attr):
                        continue  # 아바타 썸네일 제외
                    if disp_w >= 200 and nat_w >= 200:
                        large_img_elements.append(_img)
                except Exception:
                    continue
        except Exception:
            pass

        count = 0
        failed_count = 0
        cdp_fallback_used = False
        browser_fallback_used = False
        capture_fallback_used = False
        fail_reasons = []  # [KN-DIAG] 요약용 실패 사유 모음
        prefix_str = _media_prefix(post_info)
        for idx, src in enumerate(media_srcs):
            if _stop_requested(check_stop_callback):
                log("다운로드가 중지되었습니다.")
                return False
            log(f"미디어 다운로드 중 ({idx+1}/{len(media_srcs)})...")
            saved = False
            fail_status = ""

            # 1차: 파이썬 직접 다운로드 (차단 확인된 환경이면 시도 자체를 생략해 시간 절약)
            if not prefer_browser_fetch:
                try:
                    headers = {"Referer": driver.current_url or "https://www.kidsnote.com/"}
                    response = _session_get(session, src, headers=headers, timeout=(10, 30), stream=True, allow_redirects=True)
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if "text/html" in content_type.lower():
                        raise ValueError("media request returned an HTML page")
                    ext = _extension_from_response(src, content_type)

                    file_path = os.path.join(target_dir, f"{prefix_str}_{count+1}.{ext}")
                    tmp_path = file_path + ".part"
                    wrote_any = False
                    with open(tmp_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=1024 * 256):
                            if _stop_requested(check_stop_callback):
                                raise InterruptedError("download stopped")
                            if chunk:
                                wrote_any = True
                                f.write(chunk)
                    if not wrote_any:
                        raise ValueError("empty media response")
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    os.replace(tmp_path, file_path)
                    _apply_post_timestamp(file_path, post_info)
                    count += 1
                    saved = True
                except Exception as req_e:
                    fail_status = f"direct:{type(req_e).__name__}"
                    try:
                        if 'tmp_path' in locals() and os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except Exception:
                        pass
                    if _stop_requested(check_stop_callback):
                        log("다운로드가 중지되었습니다.")
                        return False

            # 2차: CDP(DevTools Protocol) 경유 다운로드 — fetch()와 달리 CORS 제약을 받지 않아
            # CDN이 CORS 헤더를 아예 안 내려주는 경우(= 3차 browser fetch도 항상 실패하는 근본 원인)의
            # 진짜 대안이 된다.
            if not saved:
                media_bytes, status = _cdp_fetch_media(driver, src)
                if _stop_requested(check_stop_callback):
                    log("다운로드가 중지되었습니다.")
                    return False
                if media_bytes:
                    try:
                        ext = _extension_from_response(src, "")
                        file_path = os.path.join(target_dir, f"{prefix_str}_{count+1}.{ext}")
                        with open(file_path, "wb") as f:
                            f.write(media_bytes)
                        _apply_post_timestamp(file_path, post_info)
                        count += 1
                        saved = True
                        cdp_fallback_used = True
                    except Exception as write_e:
                        fail_status += f" cdp:write_{type(write_e).__name__}"
                else:
                    fail_status += f" cdp:{status}"

            # 3차: 브라우저 fetch() 경유 다운로드 — CDN이 CORS를 정상 지원하는 환경에서 유효
            if not saved:
                media_bytes, status = _browser_fetch_media(driver, src)
                if _stop_requested(check_stop_callback):
                    log("다운로드가 중지되었습니다.")
                    return False
                if media_bytes:
                    try:
                        ext = _extension_from_response(src, "")
                        file_path = os.path.join(target_dir, f"{prefix_str}_{count+1}.{ext}")
                        with open(file_path, "wb") as f:
                            f.write(media_bytes)
                        _apply_post_timestamp(file_path, post_info)
                        count += 1
                        saved = True
                        browser_fallback_used = True
                    except Exception as write_e:
                        fail_status += f" browser:write_{type(write_e).__name__}"
                else:
                    fail_status += f" browser:{status}"

            if not saved:
                failed_count += 1
                reason = fail_status.strip()
                if reason:
                    fail_reasons.append(reason)
                log(f"DEBUG: 미디어 다운로드 실패 ({reason})")

        # 4차(최후): 직접·CDP·브라우저 fetch가 모두 막힌 경우(프록시가 이미지 CDN 완전 차단 등)
        # 화면에 이미 보이는 이미지를 캡처해서라도 저장한다. 화질은 표시 해상도 수준.
        # media_srcs가 있을 때만(= 받을 사진이 있었는데 전부 실패) 캡처 — 텍스트 전용 글은 제외.
        if count == 0 and media_srcs and large_img_elements:
            log("직접·CDP·브라우저 다운로드가 모두 막혀 화면 캡처 방식으로 저장을 시도합니다...")
            # 실제 미디어 개수만큼만 캡처 (UI 이미지 과잉 저장 방지)
            for _img in large_img_elements[:len(media_srcs)]:
                if _stop_requested(check_stop_callback):
                    log("다운로드가 중지되었습니다.")
                    return False
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", _img)
                    time.sleep(0.15)
                except Exception:
                    pass
                shot = _element_screenshot_b64(_img, log)
                if not shot:
                    continue
                try:
                    file_path = os.path.join(target_dir, f"{prefix_str}_{count+1}.png")
                    with open(file_path, "wb") as f:
                        f.write(base64.b64decode(shot))
                    _apply_post_timestamp(file_path, post_info)
                    count += 1
                    capture_fallback_used = True
                except Exception:
                    continue

        if cdp_fallback_used:
            log("직접 접근이 차단되어 일부/전체 파일을 CDP(디버깅 프로토콜) 경유 방식으로 받았습니다.")
        if browser_fallback_used:
            log("직접 접근이 차단되어 일부/전체 파일을 브라우저 경유 방식으로 받았습니다.")
        if capture_fallback_used:
            log("네트워크가 막혀 화면 캡처본으로 저장했습니다. (원본보다 화질이 낮을 수 있어요)")

        # 진단 요약(사용자 복사용): 실패가 있었을 때만 대표 사유를 한 줄로 남긴다
        if failed_count or (count == 0 and media_srcs):
            reason_str = "; ".join(sorted(set(fail_reasons))[:4]) or "사유미상"
            method = "캡처" if capture_fallback_used else ("브라우저" if browser_fallback_used else ("CDP" if cdp_fallback_used else "직접"))
            log(f"[KN-DIAG] 미디어 실패 | 총{len(media_srcs)} 성공{count}({method}) 실패{failed_count} | 사유={reason_str}")

        log(f"{post_info['title']}: {count}개의 파일(사진/동영상) 다운로드 완료.")
        if count == 0:
            # 실제로 아무것도 저장하지 못했으면 성공으로 위장하지 않는다.
            # (사내망 프록시가 사진 서버를 차단하면 전부 여기로 떨어짐)
            if media_srcs:
                log(f"'{post_info.get('title', '')}': 미디어 {len(media_srcs)}개 다운로드 모두 실패 (네트워크 차단 가능성)")
                return False
            if str(post_info.get('has_photo', '')).upper() == 'O':
                log(f"'{post_info.get('title', '')}': 사진이 있는 게시물인데 미디어 주소를 찾지 못했습니다.")
                return False
            log("이 게시물에는 다운로드할 사진/동영상이 없습니다.")
        elif failed_count:
            log(f"일부 파일은 접근 권한/네트워크 문제로 건너뛰었습니다. (실패 {failed_count}개)")
        return True
    except Exception as e:
        log(f"사진/동영상 다운로드 오류: {e}")
        return False

def download_item(driver, mem, target_path_or_dir, is_pdf, status_callback=None, is_overwrite_allow=True, check_stop_callback=None, include_video=True, prefer_browser_fetch=False):
    """
    Handles robust navigation to the detail page and downloads it.
    """
    def log(msg):
        if status_callback and 'DEBUG' not in msg: status_callback(msg)

    if _stop_requested(check_stop_callback):
        log("다운로드가 중지되었습니다.")
        return False
        
    # 기존 파일이 있고 덮어쓰기가 허용되지 않으면 탐색 자체를 스킵
    if not is_overwrite_allow:
        if is_pdf:
            if os.path.exists(target_path_or_dir):
                log("이미 동일한 PDF 파일이 존재하여 다운로드를 건너뜁니다.")
                return True
        else:
            if os.path.isdir(target_path_or_dir):
                # 같은 폴더를 여러 게시물이 공유할 수 있으므로(한 곳에 모두 저장 옵션)
                # "폴더가 비어있지 않음"이 아니라 "이 게시물의 파일명 prefix와 일치하는 파일 존재"로 판정
                import re as _re
                prefix_str = _media_prefix(mem)
                pattern = _re.compile(_re.escape(prefix_str) + r"_\d+\.[A-Za-z0-9]+$")
                try:
                    existing = os.listdir(target_path_or_dir)
                except OSError:
                    existing = []
                if any(pattern.match(name) for name in existing):
                    log("이미 미디어 파일이 존재하여 다운로드를 건너뜁니다.")
                    return True

    if mem.get('url'):
        if _stop_requested(check_stop_callback):
            log("다운로드가 중지되었습니다.")
            return False
        driver.get(mem['url'])
        if _sleep_with_stop(2, check_stop_callback):  # 상세 페이지 완전 로딩 대기 (댓글 포함)
            log("다운로드가 중지되었습니다.")
            return False
        if is_pdf:
            return download_as_pdf(driver, mem, target_path_or_dir, status_callback, check_stop_callback)
        else:
            return download_photos_only(driver, mem, target_path_or_dir, status_callback, check_stop_callback, include_video, prefer_browser_fetch)
            
    # Need to navigate
    try:
        def _find_target():
            post_items = driver.find_elements(By.XPATH, post_card_xpath())
            for post in post_items:
                try:
                    raw_date = None
                    try: raw_date = post.find_element(By.XPATH, CARD_DATE_XPATH).text.strip()
                    except Exception: raw_date = post.find_element(By.CLASS_NAME, CARD_DATE_CLASS).find_element(By.TAG_NAME, "span").text.strip()
                    
                    d = raw_date
                    if d and d != "날짜 알 수 없음":
                        import datetime, re
                        match_dot = re.search(r'(\d{4})\.?\s*(\d{1,2})\.?\s*(\d{1,2})', d)
                        match_kor = re.search(r'(?:(\d{4})\s*년)?\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', d)
                        current_year = datetime.date.today().year
                        if match_dot:
                            y, m, day = match_dot.groups()
                            d = f"{y}.{int(m):02d}.{int(day):02d}"
                        elif match_kor:
                            y = match_kor.group(1) or current_year
                            m = match_kor.group(2)
                            day = match_kor.group(3)
                            d = f"{y}.{int(m):02d}.{int(day):02d}"
                    
                    try:
                        full_text = post.find_element(By.XPATH, CARD_BODY_XPATH).text.strip()
                        t = full_text[:35].replace('\n', ' ') + "..." if len(full_text) > 35 else full_text.replace('\n', ' ')
                    except Exception:
                        try:
                            t = post.find_element(By.CLASS_NAME, CARD_BODY_CLASS).text.strip()[:35]
                        except Exception:
                            t = ""

                    # 1순위: URL 매칭 (가장 정확함)
                    try:
                        post_url = post.find_element(By.TAG_NAME, "a").get_attribute("href")
                        if mem.get('url') and post_url == mem['url']:
                            return post
                    except Exception:
                        pass
                        
                    # 2순위: 텍스트 기반 매칭 (URL이 없는 경우 대비)
                    if d == mem['date'] and t == mem['title']:
                        return post
                except Exception as inner_e:
                    continue
            return None

        # 1. Check if it's already on the screen (e.g. from a previous driver.back())
        if _stop_requested(check_stop_callback):
            log("다운로드가 중지되었습니다.")
            return False
        found_post = _find_target()

        # 2. Check if it's on the next screen (for consecutive downloads crossing page boundaries)
        if not found_post:
            try:
                for _ in range(2):
                    if _stop_requested(check_stop_callback):
                        log("다운로드가 중지되었습니다.")
                        return False
                    next_buttons = driver.find_elements(By.XPATH, NEXT_PAGE_XPATH)
                    found_next = False
                    for btn in next_buttons:
                        is_disabled = btn.get_attribute("disabled") or "disabled" in (btn.get_attribute("class") or "").lower()
                        if not is_disabled and btn.is_displayed():
                            driver.execute_script("arguments[0].click();", btn)
                            time.sleep(1)
                            found_next = True
                            break
                    if found_next:
                        found_post = _find_target()
                        if found_post: break
                    else:
                        break
            except Exception:
                pass

        # 3. If STILL not found — fallback: go through '추억보기' to reset memory view mode
        if not found_post:
            log("순차 탐색 범위를 벗어나 목록 화면(추억보기 뷰)을 재동기화합니다...")
            if _stop_requested(check_stop_callback):
                log("다운로드가 중지되었습니다.")
                return False
            target_child = mem.get('child_name')
            success = navigate_to_memory_view(driver, mem['type'], log, target_child=target_child)
            if not success:
                log("추억보기 뷰 동기화 실패.")
                save_debug_snapshot(driver, f"Error_Navigating_MemView", status_callback, mem=mem)
                return False

            # Pagination
            target_page = mem.get('page', 1)
            for p in range(1, target_page):
                if _stop_requested(check_stop_callback):
                    log("다운로드가 중지되었습니다.")
                    return False
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, post_card_xpath()))
                    )
                except Exception: pass
                next_buttons = driver.find_elements(By.XPATH, NEXT_PAGE_XPATH)
                found_next = False
                for btn in next_buttons:
                    is_disabled = btn.get_attribute("disabled") or "disabled" in (btn.get_attribute("class") or "").lower()
                    if not is_disabled and btn.is_displayed():
                        driver.execute_script("arguments[0].click();", btn)
                        found_next = True
                        break
                if not found_next:
                    log(f"페이지 {target_page} 로 이동 실패 (다음 버튼 없음)")
                    return False
                time.sleep(0.5)

            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, post_card_xpath()))
                )
                time.sleep(1)
            except Exception:
                log("목록 항목을 로드하는 데 시간이 초과되었습니다.")

            found_post = _find_target()
        
        if found_post:
            if _stop_requested(check_stop_callback):
                log("다운로드가 중지되었습니다.")
                return False
            driver.execute_script("arguments[0].click();", found_post)
            if _sleep_with_stop(2, check_stop_callback):  # 상세 페이지 완전 로딩 대기 (댓글 로드를 위해 2초로 연장)
                log("다운로드가 중지되었습니다.")
                return False
            save_debug_snapshot(driver, f"Opened_{mem['type']}_Detail", status_callback, mem=mem)
            
            if is_pdf:
                res = download_as_pdf(driver, mem, target_path_or_dir, status_callback, check_stop_callback)
            else:
                res = download_photos_only(driver, mem, target_path_or_dir, status_callback, check_stop_callback, include_video, prefer_browser_fetch)
            
            # 다운로드 완료 후 뒤로가기를 호출하여 리스트 상태로 복귀!! (이것이 속도의 핵심)
            driver.back()
            time.sleep(1.5)
            return res
        else:
            log("해당 위치에 게시물이 존재하지 않습니다. (날짜/제목 불일치)")
            save_debug_snapshot(driver, f"NotFound_{mem['type']}_Detail", status_callback, mem=mem)
            return False
            
    except Exception as e:
        log(f"상세 페이지 이동 중 오류: {e}")
        save_debug_snapshot(driver, f"Error_Navigating_{mem['type']}", status_callback, mem=mem)
        return False


# ---------------------------------------------------------------------------
# 로그인과 아이 목록
#
# 원래 GUI(_init_driver) 안에서 직접 하던 일이다. 화면을 그리는 코드와 키즈노트
# 마크업을 읽는 코드가 한 함수에 섞여 있으면, 사이트가 바뀔 때 고칠 곳을 두 파일에서
# 찾아야 한다. 이 프로그램에서 가장 자주 일어나는 유지보수가 그것이라 웹을 읽는 일은
# 전부 이쪽으로 모은다.
# ---------------------------------------------------------------------------

# 작은 아바타 옆에서 이름과 나이를 읽어 온다.
_CHILD_NAMES_JS = """
var results = [];
var spans = document.querySelectorAll("span[role='img'][size='36']");
for (var i = 0; i < spans.length; i++) {
  var container = spans[i].parentElement.parentElement;
  var pTags = container.querySelectorAll("p");
  if (pTags.length >= 2) {
    results.push([pTags[0].textContent.trim(), pTags[1].textContent.trim()]);
  }
}
return results;
"""

# 활성 아바타에서 얼굴 사진 주소를 뽑는다.
# img 태그가 있으면 그쪽이 정확하고, 없으면 배경 이미지 CSS에서 긁는다.
_ACTIVE_AVATAR_URL_JS = """
var s = document.querySelector("span[role='img'][size='65']");
if (!s) { return ""; }
var img = s.querySelector("img");
if (img && (img.currentSrc || img.src)) { return img.currentSrc || img.src; }
var bg = window.getComputedStyle(s).backgroundImage || "";
var match = bg.match(/url\(["']?([^"')]+)["']?\)/);
return match ? match[1] : "";
"""

# 목록에 쓰이는 작은 썸네일 주소. 큰 것으로 바꿔야 화면에서 뭉개지지 않는다.
_THUMB_SIZES = ('img_36x36.jpg', 'img_65x65.jpg', 'img_130x130.jpg', 'img_240x240.jpg')


def login(driver, username, password, status_callback=None,
          field_timeout=90, verify_timeout=20):
    """키즈노트에 로그인하고, 실제로 성공했는지 확인해서 알려준다.

    성공 여부는 주소로 판단한다. 로그인 화면(/login)을 벗어났으면 성공이다.
    예전에는 아이디와 비밀번호를 넣기만 하고 무조건 '로그인 성공'이라고 표시해서,
    비밀번호가 틀려도 한참 진행하다 엉뚱한 화면에서 멈추는 바람에 원인을 알 수 없었다.

    돌려주는 값은 (결과, 사유) 두 개다.
        'ok'      로그인 성공
        'failed'  아이디나 비밀번호가 틀린 것으로 보임 (로그인 화면에 머물러 있음)
        'error'   로그인 화면 자체를 못 띄움 (네트워크 지연 등). 사유가 함께 온다.
    """
    def log(msg):
        if status_callback:
            status_callback(msg)

    try:
        driver.set_page_load_timeout(120)
        driver.get("https://www.kidsnote.com/login")
        user_field = WebDriverWait(driver, field_timeout).until(
            EC.presence_of_element_located((By.NAME, "username")))
    except Exception as e:
        return 'error', str(e)

    try:
        from selenium.webdriver.common.keys import Keys
        pass_field = driver.find_element(By.NAME, "password")
        user_field.send_keys(username)
        pass_field.send_keys(password)
        pass_field.send_keys(Keys.RETURN)
    except Exception as e:
        return 'error', str(e)

    log("로그인 확인 중...")
    try:
        WebDriverWait(driver, verify_timeout).until(
            lambda d: "/login" not in d.current_url)
    except Exception:
        return 'failed', ''
    return 'ok', ''


def upgrade_thumbnail_url(url, size=240):
    """작은 썸네일 주소를 더 큰 해상도 주소로 바꾼다. 해당 없으면 그대로 둔다."""
    if not url:
        return url
    for thumb in _THUMB_SIZES:
        url = url.replace(thumb, 'img_%dx%d.jpg' % (size, size))
    return url


def _profile_url_candidates(driver, primary_url, fallback_url):
    """얼굴 사진을 받아 볼 주소 후보를 큰 해상도부터 만든다.

    같은 사진이라도 해상도별로 주소가 따로 있는데 어느 것이 살아 있는지는 받아 봐야 안다.
    다만 너무 많이 시도하면 사내망처럼 막힌 환경에서 아이마다 수십 초씩 잡아먹으므로
    셋에서 끊는다.
    """
    candidates = []
    for base_url in (primary_url, fallback_url):
        if not base_url:
            continue
        normalized = normalize_media_url(driver, base_url)
        if normalized and normalized not in candidates:
            candidates.append(normalized)
        for size in (480, 360, 240):
            upgraded = upgrade_thumbnail_url(normalized, size)
            if upgraded and upgraded not in candidates:
                candidates.append(upgraded)
    return candidates[:3]


def _fetch_profile_bytes(driver, candidates, timeout=12):
    """후보 주소를 순서대로 시도해 얼굴 사진을 base64로 받아 온다.

    브라우저 fetch를 먼저 쓴다. 사내망 프록시도 브라우저 네트워크는 대개 열려 있고
    원본 화질을 그대로 받을 수 있기 때문이다. 안 되면 파이썬 requests 세션으로 넘어간다.
    """
    for url in candidates:
        try:
            data, _status = _browser_fetch_media(driver, url, timeout=timeout)
            if data:
                return base64.b64encode(data).decode('utf-8')
        except Exception:
            continue

    for url in candidates:
        try:
            data, _ct = fetch_bytes_with_browser_session(driver, url, timeout=3)
            if data:
                return base64.b64encode(data).decode('utf-8')
        except Exception:
            continue
    return ""


def fetch_children(driver, status_callback=None, progress_callback=None,
                   log_callback=None, max_image_failures=2):
    """로그인한 계정의 아이 목록을 얼굴 사진과 함께 읽어 온다.

    얼굴 사진은 레이지 로딩이라 그냥은 주소를 알 수 없다. 아이를 클릭해서 큰 아바타가
    활성화되어야 비로소 CSS에 주소가 들어간다. 그래서 아이마다 클릭 → 주소 추출 →
    내려받기 순서로 진행한다.

    내려받기가 연달아 실패하면(max_image_failures) 이후로는 시도하지 않는다.
    사내망에서 CDN이 막혀 있으면 아이마다 수십 초씩 기다리게 되는데, 얼굴 사진이 없어도
    프로그램을 쓰는 데는 지장이 없기 때문이다. 이때도 화면에 보이는 아바타를 캡처해
    두므로 대개 얼굴은 뜬다.

    progress_callback(이름, 현재번호, 전체수) 로 진행 상황을 알린다.

    돌려주는 값은 아이마다 다음을 담은 목록이다.
        text     화면에 보일 '이름 생년월일 (나이)'
        elem     이 아이를 고를 때 클릭할 요소
        img_b64  얼굴 사진 (없으면 None)
    """
    def log(msg):
        if status_callback:
            status_callback(msg)

    def debug(msg):
        if log_callback:
            log_callback(msg)

    # 아이 목록은 서비스 홈에만 있다. 다른 화면에 있으면 먼저 홈으로 돌아간다.
    if "kidsnote.com/service" not in (driver.current_url or ""):
        driver.get("https://www.kidsnote.com/service")
    wait_css(driver, ANY_AVATAR_CSS, timeout=10)

    # 큰 아바타가 뜰 때까지 기다린다. 이게 있어야 얼굴 사진 주소를 읽을 수 있다.
    try:
        WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.XPATH, ACTIVE_AVATAR_XPATH)))
        time.sleep(1)   # 이름과 나이 텍스트가 뒤따라 그려지는 시간
    except Exception:
        pass

    try:
        name_array = driver.execute_script(_CHILD_NAMES_JS) or []
        click_elems = driver.find_elements(By.CSS_SELECTOR, CHILD_AVATAR_CSS)
    except Exception as e:
        debug("Child list scrape failed: %s" % type(e).__name__)
        return []

    children = []
    seen = set()
    failure_streak = 0

    for idx, name_info in enumerate(name_array):
        try:
            name, age = name_info
        except (TypeError, ValueError):
            continue
        if not name or not age:
            continue

        text_val = "%s %s" % (name, age)
        if text_val in seen:
            continue
        seen.add(text_val)

        if progress_callback:
            progress_callback(name, idx + 1, len(name_array))

        # 이 아이를 클릭해 큰 아바타를 활성화시킨다 (그래야 사진 주소가 생긴다)
        if idx < len(click_elems):
            try:
                driver.execute_script("arguments[0].click();", click_elems[idx])
                time.sleep(1.0)     # CSS에 주소가 주입되는 시간
            except Exception:
                pass

        # 활성화된 아바타에서 사진 주소를 읽는다
        url = orig_url = ""
        try:
            raw = driver.execute_script(_ACTIVE_AVATAR_URL_JS) or ""
        except Exception:
            raw = ""
        if raw and raw != "none":
            if raw.startswith(("http", "//", "/")):
                url = normalize_media_url(driver, raw)
            elif "url(" in raw:
                start = raw.index("url(") + 4
                end = raw.index(")", start)
                url = normalize_media_url(driver, raw[start:end].strip('"').strip("'"))
            orig_url = url
            url = upgrade_thumbnail_url(url)

        # 네트워크가 막혀도 얼굴이 뜨도록 화면에 보이는 아바타를 캡처해 둔다
        shot_b64 = ""
        try:
            avatar = driver.find_element(By.CSS_SELECTOR, ACTIVE_AVATAR_CSS)
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", avatar)
                time.sleep(0.2)
            except Exception:
                pass
            shot_b64 = avatar.screenshot_as_base64 or ""
        except Exception as e:
            # 로그에 아이 이름을 남기지 않는다 (개인정보) - 순번으로만 기록
            debug("Profile avatar capture failed for child #%d: %s" % (idx + 1, type(e).__name__))

        img_b64 = None
        if url and failure_streak < max_image_failures:
            img_b64 = _fetch_profile_bytes(
                driver, _profile_url_candidates(driver, url, orig_url)) or None
            failure_streak = 0 if img_b64 else failure_streak + 1

        # 원본을 못 받았으면 화면 캡처본으로 대신한다
        if not img_b64 and shot_b64:
            img_b64 = shot_b64

        # 진단(복사용): 이 아이의 프로필 확보 결과를 한 줄로 남긴다
        source = "없음"
        if img_b64:
            source = "화면캡처" if img_b64 == shot_b64 else "네트워크"
        log("[KN-DIAG] 프로필(%s) %s | 방식=%s | URL=%s | 캡처=%s" % (
            name, "성공" if img_b64 else "실패", source,
            "있음" if url else "없음", "있음" if shot_b64 else "없음"))

        children.append({
            "text": text_val,
            "elem": click_elems[idx] if idx < len(click_elems) else None,
            "img_b64": img_b64,
        })

    return children


# 이름이 보이는 아바타를 찾아 클릭한다. 아이 전환은 React 상태 변경이라
# 주소를 바꾸는 것으로는 되지 않고 실제로 눌러야 한다.
_SELECT_CHILD_JS = """
var target = arguments[0];
var spans = document.querySelectorAll("span[role='img']");
for (var i = 0; i < spans.length; i++) {
  var parent = spans[i].parentElement.parentElement;
  if (parent && parent.innerText && parent.innerText.includes(target)) {
    spans[i].click();
    return true;
  }
}
return false;
"""


def select_child(driver, child_name, status_callback=None):
    """아이 목록에서 해당 아이를 눌러 활성 계정을 바꾼다.

    서비스 홈이 아닌 화면에서 누르면 상태가 꼬이므로 먼저 홈으로 되돌린다.
    누른 뒤에는 React가 화면을 다시 그릴 시간을 준다.

    찾아서 눌렀으면 True. 이름이 목록에 없으면 False.
    """
    def log(msg):
        if status_callback:
            status_callback(msg)

    if "kidsnote.com/service" not in (driver.current_url or ""):
        driver.get("https://www.kidsnote.com/service")
        time.sleep(1.5)

    clicked = bool(driver.execute_script(_SELECT_CHILD_JS, child_name))
    if not clicked:
        log("DEBUG: 아이 목록에서 해당 이름을 찾지 못했습니다.")
        return False

    time.sleep(2)   # React 상태 변경 후 렌더링 대기
    return True
