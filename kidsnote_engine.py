import os
import time
import requests
import json
import base64
import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

def save_debug_snapshot(driver, step_name, log_func=print, mem=None):
    """
    현재 브라우저 창의 HTML 소스와 스크린샷을 지정된 폴더에 타임스탬프와 함께 저장합니다.
    디버깅용으로 오류 시점의 렌더링 상태를 확인하는 데 사용됩니다.
    """
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


def _scrape_list_pages(driver, item_type, memories, log, item_found_callback=None, check_stop_callback=None, limit_date_str=None, child_name=None):
    """
    Helper to scrape all pages of a list (Report or Album).
    Yields or callbacks items as they are found.
    """
    page_count = 1
    log(f"DEBUG: _scrape_list_pages 시작. 대상: {item_type}, 현재 URL: {driver.current_url}")
    while True:
        if check_stop_callback and check_stop_callback():
            log(f"DEBUG: {item_type} 수집 중지 요청 확인됨.")
            break

        try:
            # Wait for items to load
            log(f"DEBUG: {page_count}페이지 로딩 대기 중 (최대 15초)...")
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'exa4ze60') or contains(@class, 'css-220836')]"))
            )
        except TimeoutException:
            log(f"DEBUG: TimeoutException 발생. 현재 URL: {driver.current_url}")
            log(f"{item_type} {page_count}페이지 게시물을 찾을 수 없습니다.")
            save_debug_snapshot(driver, f"Timeout_{item_type}_Page{page_count}", log)
            break
        
        post_items = driver.find_elements(By.XPATH, "//div[contains(@class, 'exa4ze60') or contains(@class, 'css-220836')]")
        total_items = len(post_items)
        log(f"DEBUG: 게시물 항목을 {total_items}개 찾음.")

        # ── 첫 번째 항목의 부모 요소를 포함한 HTML 저장 (교사명 위치 파악용) ──
        if page_count == 1 and total_items > 0:
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
        time.sleep(2)
        
        if target_child:
            try:
                log_func(f"아이 전환 확인 중 (이름: {target_child})...")
                script = f"""
                    var spans = document.querySelectorAll("span[role='img']");
                    for(var i=0; i<spans.length; i++){{
                        var parent = spans[i].parentElement.parentElement;
                        if(parent && parent.innerText && parent.innerText.includes("{target_child}")) {{
                            spans[i].click();
                            return true;
                        }}
                    }}
                    return false;
                """
                driver.execute_script(script)
                time.sleep(2)
                driver.get("https://www.kidsnote.com/service")
                time.sleep(1.5)
            except Exception as e:
                log_func(f"아이 전환 중 예외 (무시): {e}")

        # 추억보기 1순위 클릭
        clicked = False
        try:
            mem_btn = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((By.XPATH, "//*[contains(@class,'e1q0zrbj0') and contains(.,'추억보기')]"))
            )
            driver.execute_script("arguments[0].click();", mem_btn)
            time.sleep(1.5)
            clicked = True
        except:
            pass
            
        # 추억보기 2순위 드롭다운 클릭
        if not clicked:
            try:
                toggle = driver.find_element(By.XPATH, "//*[@data-testid='center-sidebar-menu-select']")
                driver.execute_script("arguments[0].click();", toggle)
                time.sleep(0.8)
                mem_link = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[contains(@class,'e1efjxmz8') and contains(.,'추억보기')]"))
                )
                driver.execute_script("arguments[0].click();", mem_link)
                time.sleep(1.5)
            except Exception as e:
                log_func(f"추억보기 진입 모두 실패: {e}")

        # 전체보기 클릭
        try:
            view_all_btns = WebDriverWait(driver, 8).until(
                lambda d: d.find_elements(By.XPATH, "//*[contains(text(),'전체보기')]")
            )
            target_btn = None
            if item_type_label == "알림장":
                target_btn = view_all_btns[0] if view_all_btns else None
            else:
                target_btn = view_all_btns[1] if len(view_all_btns) >= 2 else (view_all_btns[0] if view_all_btns else None)
            
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
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//div[contains(@class,'exa4ze60') or contains(@class,'css-220836')]"))
            )
            return True
        except TimeoutException:
            log_func(f"{item_type_label} 목록 대기 시간 초과")
            return False
    except Exception as e:
        log_func(f"Memory view 진입 중 큰 예외 발생: {e}")
        return False
        


def fetch_memory_list(driver, status_callback=None, item_found_callback=None, check_stop_callback=None, scrape_reports=True, scrape_albums=True, profile_found_callback=None, limit_date_str=None, child_name=None):
    """
    Fetches the list of memories by navigating directly to /service/report and /service/album.
    If child_name is provided, navigate to /service first and click the child with that name.
    """
    def log(msg):
        print(msg) # 터미널에도 출력
        if status_callback and 'DEBUG' not in msg:
            status_callback(msg)

    memories = []

    # 0. 항상 /service 로 이동 후 아이 전환
    log("서비스 페이지로 이동 중...")
    driver.get("https://www.kidsnote.com/service")
    time.sleep(2) # 넉넉하게 대기

    if child_name is not None:
        try:
            log(f"아이 전환 중 (이름: {child_name})...")
            script = f"""
                var spans = document.querySelectorAll("span[role='img']");
                for(var i=0; i<spans.length; i++){{
                    var parent = spans[i].parentElement.parentElement;
                    if(parent && parent.innerText && parent.innerText.includes("{child_name}")) {{
                        spans[i].click();
                        return true;
                    }}
                }}
                return false;
            """
            driver.execute_script(script)
            time.sleep(2) # 클릭 후 정보 변경 대기
            
            # 아이 전환 직후에는 라우팅 꼬임을 방지하기 위해 홈으로 리프레시
            driver.get("https://www.kidsnote.com/service")
            time.sleep(1.5)
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
            time.sleep(1.2)

        log(f"DEBUG: 추억보기 클릭 후 URL: {driver.current_url}")

        # 사이드바 HTML 저장
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
            'var allStyleText = "";'
            'var styleTags = document.querySelectorAll("style");'
            'for(var t=0; t<styleTags.length; t++) { allStyleText += styleTags[t].textContent; }'
            'var activeSpan = document.querySelector("span[size=\'65\'][role=\'img\']");'
            'if(activeSpan) {'
            '  var container = activeSpan.parentElement;'
            '  var url = "";'
            '  var classList = activeSpan.className.split(" ");'
            '  for(var ci=0; ci<classList.length && !url; ci++) {'
            '    var cls = classList[ci].trim();'
            '    if(!cls) continue;'
            '    var searchKey = "." + cls;'
            '    var pos = allStyleText.indexOf(searchKey);'
            '    while(pos >= 0 && !url) {'
            '      var braceStart = allStyleText.indexOf("{", pos);'
            '      var braceEnd = allStyleText.indexOf("}", braceStart);'
            '      if(braceStart > 0 && braceEnd > braceStart) {'
            '        var block = allStyleText.substring(braceStart, braceEnd);'
            '        var bgIdx = block.indexOf("background-image:");'
            '        if(bgIdx >= 0) {'
            '          var urlIdx = block.indexOf("url(", bgIdx);'
            '          if(urlIdx >= 0) {'
            '            var endParen = block.indexOf(")", urlIdx + 4);'
            '            if(endParen > urlIdx + 4) {'
            '              url = block.substring(urlIdx + 4, endParen);'
            '              url = url.replace(/"/g, "").replace(/\x27/g, "");'
            '            }'
            '          }'
            '        }'
            '      }'
            '      pos = allStyleText.indexOf(searchKey, pos + 1);'
            '    }'
            '  }'
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
                    import urllib.request, base64
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=5) as response:
                        img_b64 = base64.b64encode(response.read()).decode('utf-8')
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
                _scrape_list_pages(driver, "알림장", memories, log, item_found_callback, check_stop_callback, limit_date_str, child_name)
        except Exception as e:
            log(f"알림장 조회 실패: {type(e).__name__} - {str(e)}")

    # 3. 앨범 수집 — 추억보기 → 전체보기 진입
    if scrape_albums:
        if check_stop_callback and check_stop_callback(): return memories
        log("앨범 추억 목록 조회 중...")
        try:
            if navigate_to_memory_view(driver, "앨범", log, target_child=None):
                log("앨범 전수 조사를 시작합니다...")
                _scrape_list_pages(driver, "앨범", memories, log, item_found_callback, check_stop_callback, limit_date_str, child_name)
        except Exception as e:
            log(f"앨범 조회 실패: {type(e).__name__} - {str(e)}")

    album_count = len([m for m in memories if m['type'] == '앨범'])
    report_count = len([m for m in memories if m['type'] == '알림장'])
    log(f"최종 조회 완료: 알림장 {report_count}개, 앨범 {album_count}개 수집.")

    return memories


def download_as_pdf(driver, post_info, target_path, status_callback=None):
    """
    Saves the currently open post detail page as a PDF using CDP.
    """
    def log(msg):
        if status_callback and 'DEBUG' not in msg:
            status_callback(msg)

    try:
        # 페이지 로딩 완료까지 충분히 대기 (댓글 포함)
        try:
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CLASS_NAME, "css-1469k6q.e8n018s0"))
            )
        except:
            pass  # 앨범의 경우 본문 텍스트 창이 없을 수 있으므로 무시
        time.sleep(2)  # 댓글 섹션 렌더링 추가 대기
            
        # 1. 페이지 전체 스크롤을 단계별로 내려서 레이지 로딩 타겟(댓글창, 이미지 등)을 모두 불러옴
        try:
            raw_height = driver.execute_script("return document.body.scrollHeight")
            total_height = int(raw_height if raw_height else 2000)
            for i in range(1, total_height + 1, 800):
                driver.execute_script(f"window.scrollTo(0, {i});")
                time.sleep(0.3)
        except Exception as scroll_e:
            pass
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5) # 마지막 하단 댓글/이미지 렌더링 넉넉히 대기
            
        # 2. 하단까지 스크롤되어 표시된 댓글 더보기 버튼 반복 클릭 (접힌 댓글 펼치기)
        try:
            max_attempts = 20
            for _ in range(max_attempts):
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
                            time.sleep(1.5)
                    except:
                        pass
                if not clicked:
                    break
        except Exception as comment_e:
            pass

        # 3. 댓글이 다 펼쳐지고 난 뒤 문서 전체 높이가 늘어났을 수 있으므로 다시 한번 맨 아래로 스크롤
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1) # 최종 화면 안정화 대기
        
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
            
        log("PDF 저장 완료.")
        return True
    except Exception as e:
        log(f"PDF 저장 오류: {e}")
        return False

def download_photos_only(driver, post_info, target_dir, status_callback=None):
    """
    Downloads only images from the currently open post detail page.
    """
    def log(msg):
        if status_callback and 'DEBUG' not in msg:
            status_callback(msg)

    try:
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CLASS_NAME, "css-1469k6q.e8n018s0"))
            )
        except:
            pass # 앨범은 본문 텍스트 영역이 없을 수 있으므로 에러 넘김
            
        # 스크롤을 단계별로 내려서 모든 Lazy-loading 이미지 호출
        try:
            raw_height = driver.execute_script("return document.body.scrollHeight")
            total_height = int(raw_height if raw_height else 2000)
            for i in range(1, total_height + 1, 800):
                driver.execute_script(f"window.scrollTo(0, {i});")
                time.sleep(0.3)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)  # 마지막 이미지 로딩 대기
        except Exception as scroll_e:
            pass
        
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
            
        # 카카오 CDN/키즈노트 인증을 위해 Selenium의 로그인 쿠키를 파이썬 리퀘스트 세션에 복사
        session = requests.Session()
        for cookie in driver.get_cookies():
            session.cookies.set(cookie['name'], cookie['value'])
            
        img_elements = driver.find_elements(By.TAG_NAME, "img")
        media_srcs = []
        for img in img_elements:
            src = img.get_attribute("src")
            if src and src.startswith("http"):
                if "profile" in src.lower() or "icon" in src.lower() or src.endswith(".svg"):
                    continue
                media_srcs.append(src)
                
        # 비디오 태그 탐색
        video_elements = driver.find_elements(By.TAG_NAME, "video")
        for vid in video_elements:
            v_src = vid.get_attribute("src")
            if not v_src:
                sources = vid.find_elements(By.TAG_NAME, "source")
                for s in sources:
                    s_url = s.get_attribute("src")
                    if s_url:
                        v_src = s_url
                        break
            if v_src and v_src.startswith("http"):
                media_srcs.append(v_src)

        count = 0
        for idx, src in enumerate(media_srcs):
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Referer": "https://www.kidsnote.com/"
                }
                response = session.get(src, headers=headers, timeout=20)
                if response.status_code == 200:
                    ext = src.split(".")[-1].split("?")[0]
                    if ext.lower() not in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4', 'webm', 'mov']:
                        ext = 'jpg' if 'img' in src or 'image' in src else 'mp4'
                    
                    import datetime, re
                    # Parse date string to YYMMDD
                    try:
                        date_str = post_info.get("date", "")
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
                        else:
                            date_prefix = "unknown"
                    except:
                        date_prefix = "unknown"
                        
                    post_index = post_info.get('post_index', 0)
                    item_type = post_info.get('type', '사진')
                    prefix_str = f"{date_prefix}_{item_type}" if post_index == 0 else f"{date_prefix}_{item_type}_{post_index}"
                    
                    file_path = os.path.join(target_dir, f"{prefix_str}_{count+1}.{ext}")
                    with open(file_path, "wb") as f:
                        f.write(response.content)
                    count += 1
                else:
                    pass
            except Exception as req_e:
                continue
                
        log(f"{post_info['title']}: {count}개의 파일(사진/동영상) 다운로드 완료.")
        if count == 0:
            log("다운로드할 사진/동영상을 찾지 못했습니다.")
        return True
    except Exception as e:
        log(f"사진/동영상 다운로드 오류: {e}")
        return False

def download_item(driver, mem, target_path_or_dir, is_pdf, status_callback=None, is_overwrite_allow=True):
    """
    Handles robust navigation to the detail page and downloads it.
    """
    def log(msg):
        if status_callback and 'DEBUG' not in msg: status_callback(msg)
        
    # 기존 파일이 있고 덮어쓰기가 허용되지 않으면 탐색 자체를 스킵
    if not is_overwrite_allow:
        if is_pdf:
            if os.path.exists(target_path_or_dir):
                log("이미 동일한 PDF 파일이 존재하여 다운로드를 건너뜁니다.")
                return True
        else:
            if os.path.exists(target_path_or_dir) and os.path.isdir(target_path_or_dir):
                # 디렉토리가 비어있지 않으면 이미 받은 것으로 간주
                if len(os.listdir(target_path_or_dir)) > 0:
                    log("이미 미디어 파일이 존재하여 다운로드를 건너뜁니다.")
                    return True

    if mem.get('url'):
        driver.get(mem['url'])
        time.sleep(2)  # 상세 페이지 완전 로딩 대기 (댓글 포함)
        if is_pdf:
            return download_as_pdf(driver, mem, target_path_or_dir, status_callback)
        else:
            return download_photos_only(driver, mem, target_path_or_dir, status_callback)
            
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
        found_post = _find_target()

        # 2. Check if it's on the next screen (for consecutive downloads crossing page boundaries)
        if not found_post:
            try:
                for _ in range(2):
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
            target_child = mem.get('child_name')
            success = navigate_to_memory_view(driver, mem['type'], log, target_child=target_child)
            if not success:
                log("추억보기 뷰 동기화 실패.")
                save_debug_snapshot(driver, f"Error_Navigating_MemView", status_callback, mem=mem)
                return False

            # Pagination
            target_page = mem.get('page', 1)
            for p in range(1, target_page):
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
            driver.execute_script("arguments[0].click();", found_post)
            time.sleep(2)  # 상세 페이지 완전 로딩 대기 (댓글 로드를 위해 2초로 연장)
            save_debug_snapshot(driver, f"Opened_{mem['type']}_Detail", status_callback, mem=mem)
            
            if is_pdf:
                res = download_as_pdf(driver, mem, target_path_or_dir, status_callback)
            else:
                res = download_photos_only(driver, mem, target_path_or_dir, status_callback)
            
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
