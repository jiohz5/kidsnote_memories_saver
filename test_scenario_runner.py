import os
import sys
import time
import datetime
import configparser
import base64
from selenium import webdriver

# Windows 콘솔에서 이모지 출력 시 cp949 인코딩 에러 방지
sys.stdout.reconfigure(encoding='utf-8')

# Engine import
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import kidsnote_engine

def get_credentials():
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.expanduser("~"), "Kidsnote_Config.ini")
    config.read(config_path)
    if not config.has_section('Login'):
        return None, None
    id_str = config.get('Login', 'id', fallback='')
    pw_b64 = config.get('Login', 'pw', fallback='')
    if id_str and pw_b64:
        pw_str = base64.b64decode(pw_b64.encode('utf-8')).decode('utf-8')
        return id_str, pw_str
    return None, None

def login(driver, username, password):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys

    print("\n[Login] Navigating to Kidsnote...")
    driver.get("https://www.kidsnote.com/login")
    wait = WebDriverWait(driver, 15)
    user_field = wait.until(EC.presence_of_element_located((By.NAME, "username")))
    pass_field = driver.find_element(By.NAME, "password")
    
    user_field.send_keys(username)
    pass_field.send_keys(password)
    pass_field.send_keys(Keys.RETURN)
    print("[Login] Logged in. Checking service page...")
    time.sleep(3)
    if "kidsnote.com/service" not in driver.current_url:
        driver.get("https://www.kidsnote.com/service")
        time.sleep(2)

def status_callback(msg):
    print(f"[STATUS] {msg}")

def run_scenarios(is_full_check=False):
    """
    is_full_check=False: 3개월 기간 제한 설정 (Simple Check)
    is_full_check=True: 제한 기간 없음 (Full Check)
    """
    username, password = get_credentials()
    if not username:
        print("No saved credentials found. Please run GUI first to log in and save credentials.")
        return

    options = webdriver.ChromeOptions()
    driver = webdriver.Chrome(options=options)
    
    try:
        login(driver, username, password)
        
        print("\n=== [준비] 등록된 자녀 목록 확인 ===")
        script = """
            var results = [];
            var spans = document.querySelectorAll("span[role='img'][size='36']");
            for(var i=0; i<spans.length; i++){
              var container = spans[i].parentElement.parentElement;
              var pTags = container.querySelectorAll("p");
              if(pTags.length >= 2) {
                var cname = pTags[0].textContent.trim();
                if (!results.includes(cname)) {
                    results.push(cname);
                }
              }
            }
            return results;
        """
        children_names = driver.execute_script(script)
        if not children_names:
            print("No children found. Test aborted.")
            return

        print(f"발견된 자녀 목록: {children_names}")
        child1 = children_names[0]
        child2 = children_names[1] if len(children_names) > 1 else None

        # ---------------------------------------------------------
        # 시나리오 수행 함수
        def run_case(case_name, target_child, scrape_reports, scrape_albums, single_dir, overwrite):
            print(f"\n=================================================================")
            print(f"▶ '{case_name}' 시작 - 자녀: {target_child}")
            print(f"▶ 옵션: 알림장({scrape_reports}), 앨범({scrape_albums}), 한곳저장({single_dir}), 덮어쓰기({overwrite})")
            print(f"=================================================================")

            limit_date = None
            if not is_full_check:
                limit_date = (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y.%m.%d")
                print(f"   * 제한 일자 설정 (Simple): 최근 3개월 ({limit_date})")

            # 1. 수집
            start_t = time.time()
            memories = kidsnote_engine.fetch_memory_list(
                driver,
                status_callback=status_callback,
                item_found_callback=None,
                check_stop_callback=lambda: False,
                scrape_reports=scrape_reports,
                scrape_albums=scrape_albums,
                profile_found_callback=None,
                limit_date_str=limit_date,
                child_name=target_child
            )
            print(f"\n   -> 수집 완료: 총 {len(memories)}개 항목 (소요 시간: {int(time.time() - start_t)}초)")

            if not memories:
                print("   -> 수집된 데이터가 없어 다운로드를 건너뜁니다.")
                return

            # 전체선택 / 해제 테스트 (시뮬레이션: 파이썬 배열 슬라이싱 및 정렬)
            print(f"   -> (검증) 전체 선택 기능: 메모리 목록 길이 = {len(memories)}")
            # 최신순(날짜, 인덱스) 정렬
            memories.sort(key=lambda x: (x.get('date', ''), -x.get('index', 0)), reverse=True)
            
            # 상위 10개만 선택
            top_10 = memories[:10]
            print(f"   -> 다운로드 대상 필터링 완료: 상위(최신) 10개 항목만 진행합니다.")

            target_base_dir = os.path.join(os.getcwd(), "E2E_Test_Results", target_child)
            os.makedirs(target_base_dir, exist_ok=True)

            print("\n   [다운로드 진행]")
            for mem in top_10:
                is_pdf = (mem['type'] == '알림장') 
                
                # 경로 설정
                if single_dir:
                    save_path_or_dir = target_base_dir
                else:
                    date_folder = mem['date'].replace('.', '')
                    save_path_or_dir = os.path.join(target_base_dir, date_folder)
                    os.makedirs(save_path_or_dir, exist_ok=True)

                if is_pdf:
                    # PDF 파일명 생성
                    safe_title = "".join(c for c in mem['title'][:15] if c.isalnum() or c in (' ', '_', '-')).strip()
                    writer_prefix = ""
                    if mem.get('writer'):
                        writer_prefix = f"[{mem['writer']}]_"
                    file_name = f"{mem['date']}_{mem['type']}_{writer_prefix}{safe_title}.pdf"
                    save_path_or_dir = os.path.join(save_path_or_dir, file_name)

                print(f"      - 다운로드 시도: [{mem['type']}] {mem['date']} - {mem['title'][:15]}...")
                
                res = kidsnote_engine.download_item(
                    driver, 
                    mem, 
                    save_path_or_dir, 
                    is_pdf=is_pdf, 
                    status_callback=lambda msg: print(f"        └ {msg}"), 
                    is_overwrite_allow=overwrite
                )
                print(f"      - 결과: {res}")
            print(f"   -> '{case_name}' 완료.")

        # =========================================================
        # 시나리오 실행 목록
        # =========================================================
        # 시나리오 1: 아이 1 - 알림장만 - 단일폴더 - 덮어쓰기 허용
        run_case("Sc.1 알림장 단일폴더(덮어쓰기O)", child1, scrape_reports=True, scrape_albums=False, single_dir=True, overwrite=True)

        # 시나리오 2: 아이 1 - 앨범만 - 날짜폴더 - 덮어쓰기 넘어가기
        run_case("Sc.2 앨범 날짜폴더(덮어쓰기X)", child1, scrape_reports=False, scrape_albums=True, single_dir=False, overwrite=False)

        # 시나리오 3: 아이 1 - 둘 다 - 혼합폴더(날짜옵션) - 덮어쓰기 허용
        run_case("Sc.3 알림장/앨범 날짜폴더(덮어쓰기O)", child1, scrape_reports=True, scrape_albums=True, single_dir=False, overwrite=True)

        # 시나리오 4: 아이 2 - 둘 다 - 단일폴더 - 덮어쓰기 넘어가기
        if child2:
            run_case("Sc.4 자녀2 전환(둘 다)", child2, scrape_reports=True, scrape_albums=True, single_dir=True, overwrite=False)
            
            # 시나리오 5: 아이 1 재전환
            print("\n=== 자녀 1 정상 재전환 검증 ===")
            kidsnote_engine.navigate_to_memory_view(driver, "알림장", status_callback, target_child=child1)
            print("자녀 1 전환 명령 실행됨.")

        # 시나리오 6: 강제 작업 중지(Stop) 시뮬레이션
        print("\n=================================================================")
        print(f"▶ 'Sc.6 강제 작업 중지 (Stop Flag)' 시뮬레이션 시작")
        print(f"=================================================================")
        class StopHelper:
            def __init__(self):
                self.count = 0
            def check_stop(self):
                self.count += 1
                if self.count > 5: # 페이지를 몇 번 넘기다 중지 신호 발생
                    print("     [StopHelper] 강제 중지 신호 (True) 발생!")
                    return True
                return False
                
        helper = StopHelper()
        part_memories = kidsnote_engine.fetch_memory_list(
            driver,
            status_callback=status_callback,
            item_found_callback=None,
            check_stop_callback=helper.check_stop,
            scrape_reports=True,
            scrape_albums=True,
            limit_date_str=None,
            child_name=child1
        )
        print(f"   -> 강제 중지 후 수집된 개수: {len(part_memories)}")
        print("모든 E2E 테스트가 종료되었습니다.")
        
    except Exception as e:
         import traceback
         traceback.print_exc()
    finally:
         driver.quit()
