import os
import time
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
        
        debug_dir = os.path.join(os.getcwd(), "Kidsnote_Debug_Logs", date_folder)
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


def _scrape_list_pages(driver, item_type, memories, log, item_found_callback=None, check_stop_callback=None, limit_date_str=None, child_name=None, result_info=None):
    """
    Helper to scrape all pages of a list (Report or Album).
    Yields or callbacks items as they are found.
    result_info(dict)에 조회 결과 진단 정보를 기록해 GUI가
    '기간 내 항목 없음'과 '네트워크 실패'를 구분해 안내할 수 있게 한다.
    """
    info = result_info if isinstance(result_info, dict) else {}
    page_count = 1
    log(f"DEBUG: _scrape_list_pages 시작. 대상: {item_type}, 현재 URL: {driver.current_url}")
    while True:
        if check_stop_callback and check_stop_callback():
            log(f"DEBUG: {item_type} 수집 중지 요청 확인됨.")
            break

        try:
            # Wait for items to load
            log(f"DEBUG: {page_count}페이지 로딩 대기 중 (최대 15초)...")
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'exa4ze60') or contains(@class, 'css-220836')]"))
            )
        except TimeoutException:
            log(f"DEBUG: TimeoutException 발생. 현재 URL: {driver.current_url}")
            log(f"{item_type} {page_count}페이지 게시물을 찾을 수 없습니다.")
            info['timeout'] = True
            save_debug_snapshot(driver, f"Timeout_{item_type}_Page{page_count}", log)
            break

        info['list_loaded'] = True
        post_items = driver.find_elements(By.XPATH, "//div[contains(@class, 'exa4ze60') or contains(@class, 'css-220836')]")
        total_items = len(post_items)
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
                debug_item_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_post_item.html")
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
                # 알림장: 카드에 교사명 별도 표시 없음 → "선생님" 고정
                # 앨범: 카드 텍스트에 "2025 GREEN 교사" 같은 줄이 있음 → 추출
                writer = "선생님"
                if item_type == "앨범":
                    writer = "알 수 없음"
                    try:
                        card_text = post.text or ""
                        for line in card_text.split('\n'):
                            line = line.strip()
                            if line and '교사' in line:
                                writer = line
                                break
                    except Exception:
                        pass

                # 사진 유무 판별 (img 태그가 하나라도 있으면 O)
                has_photo = "O" if len(post.find_elements(By.TAG_NAME, "img")) > 0 else "X"

                # 날짜 추출
                try:
                    date_elem = post.find_element(By.XPATH, ".//div[contains(@class, 'exa4ze65')]/div")
                    raw_date = date_elem.text.strip()
                except NoSuchElementException:
                    try:
                        date_elem = post.find_element(By.CLASS_NAME, "css-15xrcbi").find_element(By.TAG_NAME, "span")
                        raw_date = date_elem.text.strip()
                    except:
                        raw_date = "날짜 알 수 없음"
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
                    title_elem = post.find_element(By.XPATH, ".//div[contains(@class, 'e14iqn2g4')]")
                    full_text = title_elem.text.strip()
                    title = full_text[:35].replace('\n', ' ') + "..." if len(full_text) > 35 else full_text.replace('\n', ' ')
                except NoSuchElementException:
                    try:
                        title_elem = post.find_element(By.CLASS_NAME, "css-12g7lcb")
                        title = title_elem.text.strip()[:35]
                    except:
                        title = "제목 알 수 없음"
                
                url = None
                try:
                    link_elem = post.find_element(By.TAG_NAME, "a")
                    url = link_elem.get_attribute("href")
                except:
                    pass

                if limit_date_str and date and date != "날짜 알 수 없음":
                    if date < limit_date_str:
                        log(f"DEBUG: 게시물 날짜({date})가 제한 날짜({limit_date_str})보다 이전이므로 이 페이지부터 탐색을 중단합니다.")
                        # 리스트는 최신순이므로 하나라도 더 과거라면 뒷페이지는 전부 스킵합니다.
                        filtered_items_count += 1
                        info['filtered_out'] = info.get('filtered_out', 0) + 1
                        return
                
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
            next_buttons = driver.find_elements(By.XPATH, "//button[.//span[starts-with(text(), '다음')]]")
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
                except:
                    time.sleep(1) # Fallback
        except Exception as e:
            log(f"페이지 이동 중 오류: {e}")
            break


def navigate_to_memory_view(driver, item_type_label, log_func, target_child=None):
    """
    홈 화면에서부터 선택한 아이로 전환한 후 '추억보기' 메뉴를 통해 전체보기 화면으로 진입합니다.
    URL이 누락된 항목을 수집하거나 탐색할 때 SPA의 뷰 버퍼를 재동기화하는 강력한 방법입니다.
    """
    try:
        driver.get("https://www.kidsnote.com/service")
        # 프로필 아바타가 렌더링되는 즉시 진행 (고정 2초 대기 제거)
        wait_css(driver, "span[role='img']", timeout=10)

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
                driver.execute_script(script, target_child)
                time.sleep(0.5)
                driver.get("https://www.kidsnote.com/service")
                wait_css(driver, "span[role='img']", timeout=10)
            except Exception as e:
                log_func(f"아이 전환 중 예외 (무시): {e}")

        # 추억보기 1순위 클릭
        clicked = False
        try:
            mem_btn = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, "//*[contains(@class,'e1q0zrbj0') and contains(.,'추억보기')]"))
            )
            driver.execute_script("arguments[0].click();", mem_btn)
            time.sleep(0.5)
            clicked = True
        except:
            pass
            
        # 추억보기 2순위 드롭다운 클릭
        if not clicked:
            try:
                toggle = driver.find_element(By.XPATH, "//*[@data-testid='center-sidebar-menu-select']")
                driver.execute_script("arguments[0].click();", toggle)
                time.sleep(0.5)
                mem_link = WebDriverWait(driver, 15).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[contains(@class,'e1efjxmz8') and contains(.,'추억보기')]"))
                )
                driver.execute_script("arguments[0].click();", mem_link)
                time.sleep(0.5)
            except Exception as e:
                log_func(f"추억보기 진입 모두 실패: {e}")

        # 전체보기 클릭
        try:
            # /service를 새로 로드한 직후라 이전 화면 잔상이 없으므로 최소 안정화만 두고
            # 실제 대기는 아래 WebDriverWait(전체보기 버튼 감지)가 담당 → 뜨는 즉시 진행
            time.sleep(0.3)

            if item_type_label == "앨범":
                try:
                    target_btn = WebDriverWait(driver, 10).until(
                        lambda d: (lambda btns: btns[1] if len(btns) >= 2 else None)([b for b in d.find_elements(By.XPATH, "//*[contains(text(),'전체보기')]") if b.is_displayed()])
                    )
                except TimeoutException:
                    btns = [b for b in driver.find_elements(By.XPATH, "//*[contains(text(),'전체보기')]") if b.is_displayed()]
                    target_btn = btns[0] if btns else None
            else:
                target_btn = WebDriverWait(driver, 10).until(
                    lambda d: (lambda btns: btns[0] if btns else None)([b for b in d.find_elements(By.XPATH, "//*[contains(text(),'전체보기')]") if b.is_displayed()])
                )

            if target_btn:
                driver.execute_script("arguments[0].click();", target_btn)
            else:
                log_func(f"{item_type_label} 전체보기 버튼을 찾지 못했습니다.")
                return False
        except Exception as e:
            log_func(f"전체보기 버튼 클릭 실패: {e}")
            return False

        # 목록 항목 대기
        try:
            # 아래 WebDriverWait가 게시물 감지 즉시 통과하므로 고정 안정화는 최소화
            time.sleep(0.3)
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.XPATH, "//div[contains(@class,'exa4ze60') or contains(@class,'css-220836')]"))
            )
            return True
        except TimeoutException:
            log_func(f"{item_type_label} 목록 대기 시간 초과")
            return False
    except Exception as e:
        log_func(f"Memory view 진입 중 큰 예외 발생: {e}")
        return False
        


def fetch_memory_list(driver, status_callback=None, item_found_callback=None, check_stop_callback=None, scrape_reports=True, scrape_albums=True, profile_found_callback=None, limit_date_str=None, child_name=None, result_info=None):
    """
    Fetches the list of memories by navigating directly to /service/report and /service/album.
    If child_name is provided, navigate to /service first and click the child with that name.
    result_info(dict)를 넘기면 조회 결과 진단 정보(list_loaded/items_seen/filtered_out/timeout/nav_failed)를 기록한다.
    """
    def log(msg):
        print(msg) # 터미널에도 출력
        if status_callback and 'DEBUG' not in msg:
            status_callback(msg)

    info = result_info if isinstance(result_info, dict) else {}
    memories = []

    # 0. 항상 /service 로 이동 후 아이 전환
    log("서비스 페이지로 이동 중...")
    driver.get("https://www.kidsnote.com/service")
    # React Hydration 완료(아바타 렌더링)를 감지하는 즉시 진행 (고정 1초 대기 제거)
    wait_css(driver, "span[role='img']", timeout=10)

    if child_name is not None:
        try:
            log(f"아이 전환 중 (이름: {child_name})...")
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
            driver.execute_script(script, child_name)
            time.sleep(0.5) # 클릭 후 정보 변경 대기

            # 아이 전환 직후에는 라우팅 꼬임을 방지하기 위해 홈으로 리프레시
            driver.get("https://www.kidsnote.com/service")
            wait_css(driver, "span[role='img']", timeout=10)
        except Exception as e:
            log(f"아이 전환 중 오류 (무시됨): {e}")

    # ── 추억보기 진입 시도 및 사이드바 구조 디버그 저장 ──
    try:
        # 추억보기 버튼 탐색 (data-testid 또는 텍스트)
        mem_btn = None
        try:
            mem_btn = driver.find_element(By.XPATH,
                "//*[@data-testid='center-sidebar-menu-select']"
            )
        except Exception:
            pass
        if not mem_btn:
            candidates = driver.find_elements(By.XPATH, "//*[contains(text(),'추억보기')]")
            if candidates:
                mem_btn = candidates[0]

        if mem_btn:
            driver.execute_script("arguments[0].click();", mem_btn)
            time.sleep(0.5)

        log(f"DEBUG: 추억보기 클릭 후 URL: {driver.current_url}")

        # 사이드바 HTML 저장 (디버그 모드 전용 — 개인정보 포함 가능)
        if _debug_enabled():
            sidebar_html = driver.execute_script(
                "var s = document.querySelector('nav') || document.querySelector('[class*=\"sidebar\"]') || document.querySelector('aside');"
                "return s ? s.outerHTML : document.body.innerHTML.substring(0, 30000);"
            )
            debug_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_sidebar.html")
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
            
            img_b64 = None
            if url:
                try:
                    img_data, _ = fetch_bytes_with_browser_session(driver, url, timeout=3)
                    img_b64 = base64.b64encode(img_data).decode('utf-8')
                except Exception as e:
                    log(f"프로필 사진 획득 실패 (무시됨) - {e}")

            if profile_found_callback:
                profile_found_callback({"text": profile_text, "image": img_b64})
        else:
            log("활성화된 프로필 엘리먼트를 찾지 못했습니다 (무시됨)")
    except Exception as e:
        log(f"프로필 정보 획득 실패 (무시됨) - {e}")

    # 2. 알림장 수집 — 추억보기 → 전체보기 진입
    if scrape_reports:
        if check_stop_callback and check_stop_callback(): return memories
        log("알림장 추억 목록 조회 중...")
        try:
            if navigate_to_memory_view(driver, "알림장", log, target_child=None):
                log("알림장 전수 조사를 시작합니다...")
                _scrape_list_pages(driver, "알림장", memories, log, item_found_callback, check_stop_callback, limit_date_str, child_name, result_info=info)
            else:
                info['nav_failed'] = True
        except Exception as e:
            log(f"알림장 조회 실패: {type(e).__name__} - {str(e)}")

    # 3. 앨범 수집 — 추억보기 → 전체보기 진입
    if scrape_albums:
        if check_stop_callback and check_stop_callback(): return memories
        log("앨범 추억 목록 조회 중...")
        try:
            if navigate_to_memory_view(driver, "앨범", log, target_child=None):
                log("앨범 전수 조사를 시작합니다...")
                _scrape_list_pages(driver, "앨범", memories, log, item_found_callback, check_stop_callback, limit_date_str, child_name, result_info=info)
            else:
                info['nav_failed'] = True
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
                lambda d: d.find_elements(By.CLASS_NAME, "css-1469k6q") or d.find_elements(By.TAG_NAME, "img")
            )
        except:
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
                    except:
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

def download_photos_only(driver, post_info, target_dir, status_callback=None, check_stop_callback=None, include_video=True):
    """
    Downloads only images from the currently open post detail page.
    include_video=False면 동영상(video/source 태그, 동영상 확장자)은 건너뛴다.
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
                lambda d: len(d.find_elements(By.TAG_NAME, "img")) > 1 or d.find_elements(By.CLASS_NAME, "css-1469k6q")
            )
        except:
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
            const add = (url, kind, w, h) => {
              if (url) items.push({url, kind, w: w || 0, h: h || 0});
            };
            document.querySelectorAll('img').forEach(img => {
              [
                img.currentSrc,
                img.src,
                img.getAttribute('data-original-url'),
                img.getAttribute('data-original'),
                img.getAttribute('data-src'),
                img.getAttribute('data-big'),
                img.getAttribute('data-url')
              ].forEach(url => add(url, 'image', img.naturalWidth, img.naturalHeight));
              add(img.getAttribute('srcset'), 'srcset', img.naturalWidth, img.naturalHeight);
              const parentLink = img.closest('a');
              if (parentLink) add(parentLink.href, 'image-link', img.naturalWidth, img.naturalHeight);
            });
            document.querySelectorAll('video').forEach(video => {
              add(video.currentSrc || video.src, 'video', video.videoWidth, video.videoHeight);
              video.querySelectorAll('source').forEach(source => add(source.src || source.getAttribute('src'), 'video', 0, 0));
            });
            document.querySelectorAll('source').forEach(source => add(source.src || source.getAttribute('src'), 'source', 0, 0));
            document.querySelectorAll('*').forEach(el => {
              const bg = window.getComputedStyle(el).backgroundImage;
              if (bg && bg.includes('url(')) {
                const matches = bg.match(/url\\(["']?([^"')]+)["']?\\)/g) || [];
                matches.forEach(match => {
                  const url = match.replace(/^url\\(["']?/, '').replace(/["']?\\)$/, '');
                  add(url, 'background', el.offsetWidth, el.offsetHeight);
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
            is_tiny_ui_asset = 0 < max(width, height) <= 96
            looks_like_ui_asset = any(token in lower_src for token in ["profile", "avatar", "icon", "logo", "sprite"])
            if lower_src.endswith(".svg") or (looks_like_ui_asset and is_tiny_ui_asset) or (looks_like_ui_asset and width == 0 and height == 0):
                continue
            if src in seen_srcs:
                continue
            seen_srcs.add(src)
            media_srcs.append(src)

        count = 0
        failed_count = 0
        prefix_str = _media_prefix(post_info)
        for idx, src in enumerate(media_srcs):
            if _stop_requested(check_stop_callback):
                log("다운로드가 중지되었습니다.")
                return False
            try:
                log(f"미디어 다운로드 중 ({idx+1}/{len(media_srcs)})...")
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
            except Exception as req_e:
                try:
                    if 'tmp_path' in locals() and os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass
                if _stop_requested(check_stop_callback):
                    log("다운로드가 중지되었습니다.")
                    return False
                failed_count += 1
                continue
                
        log(f"{post_info['title']}: {count}개의 파일(사진/동영상) 다운로드 완료.")
        if count == 0:
            log("다운로드할 사진/동영상을 찾지 못했습니다.")
        elif failed_count:
            log(f"일부 파일은 접근 권한/네트워크 문제로 건너뛰었습니다. (실패 {failed_count}개)")
        return True
    except Exception as e:
        log(f"사진/동영상 다운로드 오류: {e}")
        return False

def download_item(driver, mem, target_path_or_dir, is_pdf, status_callback=None, is_overwrite_allow=True, check_stop_callback=None, include_video=True):
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
            return download_photos_only(driver, mem, target_path_or_dir, status_callback, check_stop_callback, include_video)
            
    # Need to navigate
    try:
        def _find_target():
            post_items = driver.find_elements(By.XPATH, "//div[contains(@class, 'exa4ze60') or contains(@class, 'css-220836')]")
            for post in post_items:
                try:
                    raw_date = None
                    try: raw_date = post.find_element(By.XPATH, ".//div[contains(@class, 'exa4ze65')]/div").text.strip()
                    except: raw_date = post.find_element(By.CLASS_NAME, "css-15xrcbi").find_element(By.TAG_NAME, "span").text.strip()
                    
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
                        full_text = post.find_element(By.XPATH, ".//div[contains(@class, 'e14iqn2g4')]").text.strip()
                        t = full_text[:35].replace('\n', ' ') + "..." if len(full_text) > 35 else full_text.replace('\n', ' ')
                    except:
                        try:
                            t = post.find_element(By.CLASS_NAME, "css-12g7lcb").text.strip()[:35]
                        except:
                            t = ""

                    # 1순위: URL 매칭 (가장 정확함)
                    try:
                        post_url = post.find_element(By.TAG_NAME, "a").get_attribute("href")
                        if mem.get('url') and post_url == mem['url']:
                            return post
                    except:
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
                    next_buttons = driver.find_elements(By.XPATH, "//button[.//span[starts-with(text(), '다음')]]")
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
            except:
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
                        EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'exa4ze60') or contains(@class, 'css-220836')]"))
                    )
                except: pass
                next_buttons = driver.find_elements(By.XPATH, "//button[.//span[starts-with(text(), '다음')]]")
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
                    EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'exa4ze60') or contains(@class, 'css-220836')]"))
                )
                time.sleep(1)
            except:
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
                res = download_photos_only(driver, mem, target_path_or_dir, status_callback, check_stop_callback, include_video)
            
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
