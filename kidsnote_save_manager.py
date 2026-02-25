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

def _scrape_list_pages(driver, item_type, memories, log, item_found_callback=None, check_stop_callback=None, limit_date_str=None):
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
            # 페이지 구조 파악을 위한 디버깅용 태그 검색
            try:
                spans = len(driver.find_elements(By.TAG_NAME, "span"))
                divs = len(driver.find_elements(By.TAG_NAME, "div"))
                log(f"DEBUG: 페이지 구조 정보 - SPAN 갯수: {spans}, DIV 갯수: {divs}")
                
                # HTML 구조를 파일로 저장하여 분석
                import os
                html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"debug_{item_type}.html")
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                log(f"DEBUG: 해당 페이지의 HTML 소스를 {html_path} 에 저장했습니다.")
            except Exception as e:
                log(f"DEBUG: HTML 저장 중 오류: {e}")
            break
        
        post_items = driver.find_elements(By.XPATH, "//div[contains(@class, 'exa4ze60') or contains(@class, 'css-220836')]")
        total_items = len(post_items)
        log(f"DEBUG: 게시물 항목을 {total_items}개 찾음.")
        
        new_items_found = 0
        filtered_items_count = 0
        duplicate_items_count = 0
        
        for idx, post in enumerate(post_items):
            if check_stop_callback and check_stop_callback():
                log("알림장/앨범 수집이 사용자에 의해 중지되었습니다.")
                return
            try:
                writer = "알 수 없음"
                try:
                    writer_elem = post.find_element(By.XPATH, ".//strong")
                    writer_text = writer_elem.text.strip()
                    if "가정에서 원으로" in writer_text: # 제외 조건
                        filtered_items_count += 1
                        continue
                    writer = writer_text
                except NoSuchElementException:
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
                    title = full_text[:20].replace('\n', ' ') + "..." if len(full_text) > 20 else full_text
                except NoSuchElementException:
                    try:
                        title_elem = post.find_element(By.CLASS_NAME, "css-12g7lcb")
                        title = title_elem.text.strip()
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

def fetch_memory_list(driver, status_callback=None, item_found_callback=None, check_stop_callback=None, scrape_reports=True, scrape_albums=True, profile_found_callback=None, limit_date_str=None):
    """
    Fetches the list of memories by navigating into "View All" for both Reports and Albums.
    """
    def log(msg):
        print(msg) # 터미널에도 출력
        if status_callback and 'DEBUG' not in msg:
            status_callback(msg)

    memories = []
    
    # 1. Ensure we are on the service page
    if "kidsnote.com/service" not in driver.current_url:
        driver.get("https://www.kidsnote.com/service")
        time.sleep(1)

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

    # 2. Main Memory View
    log("'추억보기' 메뉴 접근 중...")
    try:
        memory_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//*[@id=\"app\"]/div[2]/div/div[1]/div[1]/button"))
        )
        memory_btn.click()
        time.sleep(1)
        log(f"DEBUG: 추억보기 진입 후 현재 URL: {driver.current_url}")
    except TimeoutException:
         log("'추억보기' 버튼을 찾을 수 없으나 계속 진행합니다.")

    # 3. Scrape Reports (알림장)
    if scrape_reports:
        if check_stop_callback and check_stop_callback(): return memories
        log("알림장 '전체보기' 탐색 중...")
        try:
            wait = WebDriverWait(driver, 10)
            view_all_elements = driver.find_elements(By.XPATH, "//*[contains(text(), '전체보기')]")
            
            log(f"'전체보기' 관련 요소를 {len(view_all_elements)}개 찾았습니다.")
            
            if len(view_all_elements) >= 1:
                log("첫 번째 '전체보기' (알림장) 클릭 시도...")
                driver.execute_script("arguments[0].click();", view_all_elements[0])
                time.sleep(1)
                log("알림장 전수 조사를 시작합니다...")
                _scrape_list_pages(driver, "알림장", memories, log, item_found_callback, check_stop_callback, limit_date_str)
            else:
                log("알림장 '전체보기' 버튼을 찾을 수 없습니다. (텍스트 매칭 실패)")
        except Exception as e:
            log(f"알림장 조회 실패: {type(e).__name__} - {str(e)}")

    # 4. Return to Memory View for Albums
    log("다시 '추억보기' 메인으로 이동 중...")
    driver.get("https://www.kidsnote.com/service")
    time.sleep(1)
    try:
        memory_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//*[@id=\"app\"]/div[2]/div/div[1]/div[1]/button"))
        )
        memory_btn.click()
        time.sleep(1)
    except:
        log("'추억보기' 메인 복귀 중 오류 또는 이미 메인입니다.")

    # 5. Scrape Albums (앨범)
    if scrape_albums:
        if check_stop_callback and check_stop_callback(): return memories
        log("앨범 '전체보기' 탐색 중...")
        try:
            view_all_elements = driver.find_elements(By.XPATH, "//*[contains(text(), '전체보기')]")
            log(f"다시 찾은 '전체보기' 관련 요소: {len(view_all_elements)}개")
            
            if len(view_all_elements) >= 2:
                log("두 번째 '전체보기' (앨범) 클릭 시도...")
                driver.execute_script("arguments[0].click();", view_all_elements[1])
                time.sleep(1)
                log("앨범 전수 조사를 시작합니다...")
                _scrape_list_pages(driver, "앨범", memories, log, item_found_callback, check_stop_callback, limit_date_str)
            elif len(view_all_elements) == 1:
                log("하나의 '전체보기'만 발견됨. 클릭 시도...")
                driver.execute_script("arguments[0].click();", view_all_elements[0])
                time.sleep(3)
                _scrape_list_pages(driver, "앨범", memories, log, item_found_callback, check_stop_callback, limit_date_str)
            else:
                 log("앨범 '전체보기' 버튼을 찾을 수 없습니다.")
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
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CLASS_NAME, "css-1469k6q.e8n018s0"))
            )
        except:
            pass # 앨범의 경우 본문 텍스트 창이 없을 수 있으므로 무시
            
        # 댓글 창이 접혀있다면 끝까지 펴기 시도
        try:
            # 여러 번 눌러야 할 수 있으므로 반복 확인
            prev_height = driver.execute_script("return document.body.scrollHeight")
            max_attempts = 10 # 무한루프 방지를 위해 최대 10번까지만 시도
            for _ in range(max_attempts):
                btns = driver.find_elements(By.XPATH, "//*[contains(text(), '이전 댓글') or contains(text(), '댓글 더보기') or contains(text(), '전체 댓글')]")
                clicked = False
                for btn in btns:
                    try:
                        if btn.is_displayed():
                            driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                            time.sleep(0.5)
                            driver.execute_script("arguments[0].click();", btn)
                            clicked = True
                            time.sleep(1.5) # 댓글이 로딩될 시간을 충분히 줌
                    except:
                        pass
                if not clicked:
                    break # 더 이상 클릭할 버튼이 없으면 종료
        except Exception as comment_e:
            pass
            
        # 페이지 전체 스크롤을 단계별로 내려서 레이지 로딩된 이미지를 모두 불러옴
        try:
            raw_height = driver.execute_script("return document.body.scrollHeight")
            total_height = int(raw_height if raw_height else 2000)
            for i in range(1, total_height + 1, 800):
                driver.execute_script(f"window.scrollTo(0, {i});")
                time.sleep(0.3)
        except Exception as scroll_e:
            pass
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1) # 마지막까지 렌더링될 여유 부여
        
        # PDF 출력 시 스크롤 박스에 갇힌 댓글이 잘리는 것을 방지하기 위해 CSS 강제 덮어쓰기
        driver.execute_script("""
            var style = document.createElement('style');
            style.innerHTML = '* { overflow: visible !important; height: auto !important; max-height: none !important; }';
            document.head.appendChild(style);
        """)
        
        log(f"PDF 저장 중: {os.path.basename(target_path)}")
        
        print_options = {
            'landscape': False,
            'displayHeaderFooter': False,
            'printBackground': True,
            'preferCSSPageSize': False # False로 해야 내용물 전체 길이에 맞게 짤리지 않음
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

def download_item(driver, mem, target_path_or_dir, is_pdf, status_callback=None):
    """
    Handles robust navigation to the detail page and downloads it.
    """
    def log(msg):
        if status_callback and 'DEBUG' not in msg: status_callback(msg)
        
    if mem.get('url'):
        driver.get(mem['url'])
        time.sleep(0.5)
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
                        t = full_text[:20].replace('\n', ' ') + "..." if len(full_text) > 20 else full_text
                    except:
                        t = post.find_element(By.CLASS_NAME, "css-12g7lcb").text.strip()

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

        # 3. If STILL not found, meaning we are out of context, fallback to full detour
        if not found_post:
            log("순차 탐색 범위를 벗어나 목록 화면을 다시 동기화합니다... (최대 수 초 소요)")
            driver.get("https://www.kidsnote.com/service")
            time.sleep(1)
            
            # Click memory view
            try:
                memory_btn = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//*[@id=\"app\"]/div[2]/div/div[1]/div[1]/button"))
                )
                driver.execute_script("arguments[0].click();", memory_btn)
                time.sleep(0.5)
            except TimeoutException:
                log("'추억보기' 버튼을 찾는 데 시간이 초과되었습니다. 우회 클릭을 시도합니다.")
                btns = driver.find_elements(By.XPATH, "//*[contains(text(), '추억보기')]")
                if btns:
                    driver.execute_script("arguments[0].click();", btns[0])
                    time.sleep(0.5)
            
            # View All for specific type
            view_all_elements = driver.find_elements(By.XPATH, "//*[contains(text(), '전체보기')]")
            if len(view_all_elements) == 0:
                log("전체보기 버튼을 찾을 수 없습니다.")
                return False
                
            if mem['type'] == '알림장':
                driver.execute_script("arguments[0].click();", view_all_elements[0])
            else:
                driver.execute_script("arguments[0].click();", view_all_elements[1] if len(view_all_elements) > 1 else view_all_elements[0])
            time.sleep(0.5)
            
            # Pagination
            target_page = mem.get('page', 1)
            for p in range(1, target_page):
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'exa4ze60') or contains(@class, 'css-220836')]"))
                )
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
                
            # Wait for items to visibly load
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'exa4ze60') or contains(@class, 'css-220836')]"))
                )
                time.sleep(1) # 마지막 렌더링 대기
            except:
                log("목록 항목을 로드하는 데 시간이 초과되었습니다.")
                
            found_post = _find_target()
        
        if found_post:
            driver.execute_script("arguments[0].click();", found_post)
            time.sleep(1) # 상세 페이지로 진입할 수 있도록 대기 연장
            
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
            return False
            
    except Exception as e:
        log(f"상세 페이지 이동 중 오류: {e}")
        return False
