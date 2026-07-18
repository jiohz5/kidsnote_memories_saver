import sys
import threading
import os
import codecs
import datetime
import faulthandler
import traceback
import shutil
from PyQt5 import QtWidgets, QtCore, QtGui
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
import kidsnote_engine as manager

APP_VERSION = "1.03"
UPDATE_CHECK_REPO = "jiohz5/kidsnote_memories_saver"

_fault_log_file = None


def _app_log_dir():
    base_dir = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base_dir, "KidsnoteMemoriesSaver", "logs")


def write_app_log(message):
    try:
        os.makedirs(_app_log_dir(), exist_ok=True)
        log_path = os.path.join(_app_log_dir(), f"app_{datetime.datetime.now():%Y%m%d}.log")
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


def install_crash_logging():
    global _fault_log_file
    try:
        os.makedirs(_app_log_dir(), exist_ok=True)
        fault_path = os.path.join(_app_log_dir(), f"fault_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")
        _fault_log_file = open(fault_path, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=_fault_log_file, all_threads=True)
    except Exception:
        _fault_log_file = None

    old_hook = sys.excepthook

    def log_excepthook(exctype, value, tb):
        write_app_log("Uncaught exception:\n" + "".join(traceback.format_exception(exctype, value, tb)))
        if old_hook:
            old_hook(exctype, value, tb)

    sys.excepthook = log_excepthook

# 터미널(콘솔) 출력 환경에서 한글 깨짐을 방지하기 위한 강제 UTF-8 세팅
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Windows에서 파이썬 스크립트 실행 시 작업표시줄 아이콘이 표시되도록 설정 (AppUserModelID 강제 지정)
try:
    import ctypes
    myappid = 'kidsnote.memoriessaver.v1.03'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

class ScrapeThread(QtCore.QThread):
    item_found_signal = QtCore.pyqtSignal(dict)
    status_signal = QtCore.pyqtSignal(str)
    profile_signal = QtCore.pyqtSignal(dict)
    finished_signal = QtCore.pyqtSignal(list)

    def __init__(self, driver, scrape_reports=True, scrape_albums=True, limit_date_str=None, child_name=None, end_date_str=None):
        super().__init__()
        self.driver = driver
        self.scrape_reports = scrape_reports
        self.scrape_albums = scrape_albums
        self.limit_date_str = limit_date_str
        self.end_date_str = end_date_str
        self.child_name = child_name
        self.is_stopped = False
        # 조회 결과 진단 정보 — GUI가 '기간 내 항목 없음'과 '네트워크 실패'를 구분해 안내
        self.result_info = {}

    def run(self):
        try:
            memories = manager.fetch_memory_list(
                self.driver,
                status_callback=self.status_signal.emit,
                item_found_callback=self.item_found_signal.emit,
                check_stop_callback=self.check_stopped,
                scrape_reports=self.scrape_reports,
                scrape_albums=self.scrape_albums,
                profile_found_callback=self.profile_signal.emit,
                limit_date_str=self.limit_date_str,
                child_name=self.child_name,
                result_info=self.result_info,
                end_date_str=self.end_date_str
            )
            self.finished_signal.emit(memories)
        except Exception as e:
            self.status_signal.emit(f"목록 로드 중 오류: {e}")
            self.finished_signal.emit([])

    def check_stopped(self):
        return self.is_stopped
                                                            
    def stop(self):
        self.is_stopped = True


class CheckStateItem(QtWidgets.QTableWidgetItem):
    """체크 상태 기준으로 정렬되는 셀 아이템.

    '선택' 컬럼을 셀 위젯(QCheckBox) 대신 체크형 아이템으로 만들어
    헤더 클릭 정렬 시 체크 상태가 데이터 행과 함께 이동하도록 한다.
    """
    def __lt__(self, other):
        if isinstance(other, QtWidgets.QTableWidgetItem):
            try:
                return int(self.checkState()) < int(other.checkState())
            except Exception:
                pass
        return super().__lt__(other)


class DownloadThread(QtCore.QThread):
    status_signal = QtCore.pyqtSignal(str)
    progress_signal = QtCore.pyqtSignal(int)
    finished_signal = QtCore.pyqtSignal(str, int, int, bool)

    def __init__(self, driver, memories, indices, target_dir, is_pdf, is_single_folder, profile_name="알수없음", is_overwrite_allow=True, include_video=True):
        super().__init__()
        self.driver = driver
        self.memories = memories
        self.indices = indices
        self.target_dir = target_dir
        self.is_pdf = is_pdf
        self.is_single_folder = is_single_folder
        self.profile_name = profile_name
        self.is_overwrite_allow = is_overwrite_allow
        self.include_video = include_video
        self.is_stopped = False
        self._paused = False
        # 완료 후 GUI가 참조하는 결과 정보
        self.failed_indices = []    # 실패한 원본 인덱스 → '실패만 재시도'에 사용
        self.succeeded_ids = []     # 성공한 항목 id → 증분 백업 기록에 사용
        self.elapsed_sec = 0
        self.network_blocked = False  # 사전 점검에서 직접 접근 차단이 감지되면 True

    def stop(self):
        self.is_stopped = True

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def check_stopped(self):
        return bool(self.is_stopped)

    def run(self):
        import datetime
        import re
        import time

        success_cnt = 0
        fail_cnt = 0
        started_at = time.time()
        try:
            write_app_log(f"Download thread started. selected={len(self.indices)} pdf={self.is_pdf} single_folder={self.is_single_folder}")

            # 사진 모드는 requests 직접 접근이 필요하므로 시작 전에 접근 가능 여부를 점검.
            # (PDF 모드는 브라우저 CDP로 저장하므로 점검 불필요)
            if not self.is_pdf:
                self.status_signal.emit("네트워크 직접 접근 사전 점검 중...")
                if not manager.probe_direct_access(self.driver):
                    self.network_blocked = True
                    write_app_log("Direct network access probe failed -> switching to browser-fetch mode")
                    self.status_signal.emit("직접 접근이 차단된 환경 감지 → 브라우저 경유 다운로드로 자동 전환합니다.")

            date_type_counts = {}
            total = len(self.indices)
            self.progress_signal.emit(0)

            for count, idx in enumerate(self.indices):
                # 일시정지 — 항목 단위 경계에서 대기 (중지 요청 시 즉시 탈출)
                while self._paused and not self.is_stopped:
                    time.sleep(0.2)

                if self.is_stopped:
                    self.status_signal.emit("알림장/앨범 다운로드가 중지되었습니다.")
                    break

                try:
                    mem = dict(self.memories[idx])
                except Exception:
                    fail_cnt += 1
                    self.failed_indices.append(idx)
                    continue

                self.status_signal.emit(f"다운로드 중 ({count + 1}/{total}): {mem.get('title', '')}")

                try:
                    clean_date = re.sub(r'[\\/*?:"<>|]', "", mem.get('date', '')).strip().rstrip('.')
                    item_type = mem.get('type', '항목')

                    base_target_dir = os.path.join(self.target_dir, f"{self.profile_name}_{item_type}")
                    os.makedirs(base_target_dir, exist_ok=True)

                    if self.is_stopped:
                        self.status_signal.emit("알림장/앨범 다운로드가 중지되었습니다.")
                        break

                    dt_key = (clean_date, item_type)
                    post_index = date_type_counts.get(dt_key, 0)
                    date_type_counts[dt_key] = post_index + 1
                    mem['post_index'] = post_index

                    if self.is_pdf:
                        date_prefix = clean_date
                        dt_match_dot = re.search(r'(\d{4})\.?\s*(\d{1,2})\.?\s*(\d{1,2})', clean_date)
                        dt_match_kor = re.search(r'(?:(\d{4})\s*년)?\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', clean_date)
                        current_year = datetime.date.today().year
                        if dt_match_dot:
                            y, m, d = dt_match_dot.groups()
                        elif dt_match_kor:
                            y = dt_match_kor.group(1) or current_year
                            m = dt_match_kor.group(2)
                            d = dt_match_kor.group(3)
                        else:
                            y, m, d = None, None, None

                        if y and m and d:
                            date_prefix = f"{str(y)[-2:]}{int(m):02d}{int(d):02d}"

                        prefix_str = f"{date_prefix}_{item_type}" if post_index == 0 else f"{date_prefix}_{item_type}_{post_index}"

                        if self.is_single_folder:
                            filename = f"{prefix_str}_{mem.get('title', 'Unknown')}.pdf"
                            filename = re.sub(r'[\\/*?"<>|]', "", filename).strip()
                            path = os.path.join(base_target_dir, filename)
                        else:
                            filename = f"{prefix_str}.pdf"
                            filename = re.sub(r'[\\/*?"<>|]', "", filename).strip()
                            date_dir = os.path.join(base_target_dir, clean_date)
                            os.makedirs(date_dir, exist_ok=True)
                            path = os.path.join(date_dir, filename)

                        success = manager.download_item(
                            self.driver,
                            mem,
                            path,
                            self.is_pdf,
                            self.status_signal.emit,
                            self.is_overwrite_allow,
                            self.check_stopped,
                            self.include_video,
                            self.network_blocked,
                        )
                    else:
                        post_dir = base_target_dir if self.is_single_folder else os.path.join(base_target_dir, clean_date)
                        os.makedirs(post_dir, exist_ok=True)
                        success = manager.download_item(
                            self.driver,
                            mem,
                            post_dir,
                            self.is_pdf,
                            self.status_signal.emit,
                            self.is_overwrite_allow,
                            self.check_stopped,
                            self.include_video,
                            self.network_blocked,
                        )

                    if success:
                        success_cnt += 1
                        if mem.get('id'):
                            self.succeeded_ids.append(mem['id'])
                    else:
                        fail_cnt += 1
                        self.failed_indices.append(idx)
                except Exception:
                    write_app_log("Download item failed:\n" + traceback.format_exc())
                    fail_cnt += 1
                    self.failed_indices.append(idx)

                self.progress_signal.emit(int(((count + 1) / total) * 100))

            if not self.is_stopped:
                self.status_signal.emit(f"다운로드 완료 (성공: {success_cnt}, 실패/건너뜀: {fail_cnt})")
                self.progress_signal.emit(100)
        except Exception:
            write_app_log("Download thread failed:\n" + traceback.format_exc())
            self.status_signal.emit("다운로드 중 치명적 오류가 발생했습니다. 로그를 확인해 주세요.")
        finally:
            self.elapsed_sec = int(time.time() - started_at)
            write_app_log(f"Download thread finished. success={success_cnt} fail={fail_cnt} stopped={self.is_stopped} elapsed={self.elapsed_sec}s")
            self.finished_signal.emit(self.target_dir, success_cnt, fail_cnt, self.is_stopped)


class KidsnoteApp(QtWidgets.QWidget):
    ui_call_signal = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.ui_call_signal.connect(self._run_ui_call)
        self.driver = None
        self.memories = []
        self.scrape_thread = None                          
        self.stop_flag = False
        self.is_downloading = False
        self.is_loading_memories = False
        self.load_finished_received = False
        self.download_thread = None
        # 증분 백업: 이전에 성공적으로 받은 항목 id 목록 (로컬 저장)
        self.downloaded_ids = self._load_manifest()
        # 테이블 행 삽입 중 itemChanged 시그널로 인한 과도한 라벨 갱신 방지 플래그
        self._table_populating = False
        self.init_ui()
        # 새 버전 확인 (백그라운드, 실패해도 무시)
        threading.Thread(target=self._check_update_worker, daemon=True).start()

    # --- 증분 백업 기록(manifest) ---
    def _manifest_path(self):
        base_dir = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base_dir, "KidsnoteMemoriesSaver", "downloaded_items.json")

    def _load_manifest(self):
        try:
            import json
            with open(self._manifest_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data) if isinstance(data, list) else set()
        except Exception:
            return set()

    def _save_manifest(self, ids):
        try:
            import json
            os.makedirs(os.path.dirname(self._manifest_path()), exist_ok=True)
            with open(self._manifest_path(), "w", encoding="utf-8") as f:
                json.dump(sorted(ids), f, ensure_ascii=False)
        except Exception:
            write_app_log("Manifest save failed:\n" + traceback.format_exc())

    # --- 새 버전 확인 (GitHub Releases, 조용히 실패) ---
    def _check_update_worker(self):
        try:
            import json, re, urllib.request
            url = f"https://api.github.com/repos/{UPDATE_CHECK_REPO}/releases/latest"
            req = urllib.request.Request(url, headers={"User-Agent": "KidsnoteMemoriesSaver"})
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.load(response)
            tag = str(data.get("tag_name") or "").strip()

            def version_tuple(v):
                nums = re.findall(r"\d+", v)
                return tuple(int(n) for n in nums[:3]) if nums else (0,)

            if tag and version_tuple(tag) > version_tuple(APP_VERSION):
                self.run_on_ui_thread(lambda: self.tray_icon.showMessage(
                    "업데이트 안내",
                    f"새 버전 {tag} 이(가) 공개되었습니다. 블로그/GitHub에서 받아주세요.",
                    QtWidgets.QSystemTrayIcon.Information,
                    8000,
                ))
        except Exception:
            pass

    @QtCore.pyqtSlot(object)
    def _run_ui_call(self, callback):
        try:
            callback()
        except Exception:
            write_app_log("UI callback failed:\n" + traceback.format_exc())

    def run_on_ui_thread(self, callback):
        self.ui_call_signal.emit(callback)

    def init_ui(self):
        self.setWindowTitle('Kidsnote Memories Saver V1.03')
        
        # 사용자의 화면 해상도를 인식하여 기본 스케일 값 도출 (FHD, QHD 등 대응)
        screen = QtWidgets.QApplication.primaryScreen()
        screen_height = screen.availableGeometry().height() if screen else 1080
            
        # 4K 모니터(세로 해상도 약 2160) 기준에서 보던 비율을 다른 해상도에서도 동일하게 느끼도록 스케일 조정.
        # FHD(1080)의 경우 scale이 약 0.5가 되어 높이가 절반(800)으로 줄어듦
        scale = min(1.0, screen_height / 2160.0)
        
        # UI 마진이나 박스 크기를 위한 스케일링 (해상도 비율 그대로 줄임)
        def S(val):
            return max(1, int(val * scale))
            
        # 폰트 전용 스케일링 함수: 글씨가 너무 작아서 안 보이는 현상(FHD에서 너무 작음)을 방지하기 위해 최소 크기 방어선(하한선) 설정
        def FS(val):
            # FHD(scale 0.5)일 때 폰트가 절반으로 확 줄어들지 않고, 다소 완만하게 줄어들도록 보정(0.8 제곱) 및 하한선 제한
            return max(11, int(val * (scale ** 0.8)))
            
        # 화면의 60~70% 정도만 차지하도록 콤팩트하게 GUI 높이를 줄여서 시야 확보 (기준 1600 -> 1500 (레이아웃 잘림 방지용으로 살짝 여유 추가))
        target_height = FS(1500)
        target_width = int(980 * (scale ** 0.7))
        
        # 글씨나 입력칸이 아예 잘리지 않도록 안전 장치
        target_width = max(580, target_width)
        target_height = max(680, target_height)
            
        # 창을 화면의 적절한 위치(세로 가운데 쯤)에 배치
        y_pos = max(30, (screen_height - target_height) // 2)
        self.setGeometry(300, y_pos, target_width, target_height)
        
        # 창 크기를 고정하여 이동 시 윈도우 스냅으로 인해 강제로 크기가 변하는 현상 원천 차단
        self.setFixedSize(target_width, target_height)
            
        # --- 키즈노트 테마 글로벌 QSS 적용 (스케일 반영) ---
        self.setStyleSheet(f"""
            QWidget {{
                background-color: #F8F9FA;
                font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
                color: #2D3748;
                font-size: {FS(14)}px;  /* 전역 기본 폰트 가독성 확보 */
            }}
            QPushButton {{
                background-color: #03A9F4;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: {S(6)}px;
                padding: {S(8)}px {FS(15)}px;
            }}
            QPushButton:hover {{
                background-color: #0288D1;
            }}
            QPushButton:disabled {{
                background-color: #CBD5E0;
                color: #A0AEC0;
            }}
            QLineEdit, QComboBox {{
                border: {S(2)}px solid #E2E8F0;
                border-radius: {S(4)}px;
                padding: {S(5)}px;
                background-color: white;
            }}
            QLineEdit:focus, QComboBox:focus {{
                border: {S(2)}px solid #FFC300;
            }}
            QGroupBox {{
                border: {S(2)}px solid #E2E8F0;
                border-radius: {S(6)}px;
                margin-top: {FS(15)}px;
                padding-top: {FS(25)}px;
                padding-bottom: {FS(10)}px;
                font-weight: bold;
                background-color: white;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: {FS(10)}px;
                padding: 0 {S(5)}px;
                color: #FF5722;
            }}
            QTableWidget {{
                background-color: white;
                border: {S(1)}px solid #E2E8F0;
                border-radius: {S(4)}px;
                gridline-color: #EDF2F7;
            }}
            QHeaderView::section {{
                background-color: #F1F5F9;
                font-weight: bold;
                color: #4A5568;
                border: none;
                border-bottom: {S(2)}px solid #E2E8F0;
                padding: {S(4)}px;
            }}
            QCheckBox {{
                spacing: {S(8)}px;
                font-size: {FS(13)}px;
                font-weight: bold;
                color: #4A5568;
            }}
            QCheckBox::indicator {{
                width: {FS(18)}px;
                height: {FS(18)}px;
            }}
            QRadioButton {{
                font-weight: bold;
                color: #4A5568;
            }}
        """)
            
        # 첫 번째 가이드 팝업 실행
        QtCore.QTimer.singleShot(700, self.show_initial_popup)
        
        # 생성된 앱 전용 아이콘 적용
        def get_icon_path():
            import sys, os
            if hasattr(sys, '_MEIPASS'):
                return os.path.join(sys._MEIPASS, 'kidsnote_icon.ico')
            return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kidsnote_icon.ico')

        app_icon = QtGui.QIcon(get_icon_path())
        self.setWindowIcon(app_icon)

        # --- 레이아웃 설정 (메인 스크롤바를 없애기 위해 QScrollArea 제거하고 창 자체에 고정) ---
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(FS(10))

        # Config setup for Local ID/PW save
        import configparser, base64
        self.config = configparser.ConfigParser()
        self.config_path = os.path.join(os.path.expanduser("~"), "Kidsnote_Config.ini")
        self.config.read(self.config_path)
        
        saved_id = self.config.get('Login', 'id', fallback='')
        saved_pw_stored = self.config.get('Login', 'pw', fallback='')
        saved_remember = self.config.getboolean('Login', 'remember', fallback=False)
        # DPAPI 암호화 저장값(신규)과 base64 저장값(구버전) 모두 지원
        saved_pw = manager.unprotect_secret(saved_pw_stored)

        # Login Info Group
        login_group = QtWidgets.QGroupBox("로그인 정보")
        login_layout = QtWidgets.QHBoxLayout()
        login_layout.setSpacing(FS(15))
        
        # 1. 왼쪽: 아이디/비밀번호 수직 배치
        idpw_layout = QtWidgets.QVBoxLayout()
        idpw_layout.setSpacing(FS(5))
        
        id_layout = QtWidgets.QHBoxLayout()
        id_layout.addWidget(QtWidgets.QLabel("아이디:"))
        self.id_input = QtWidgets.QLineEdit(saved_id)
        self.id_input.setMinimumWidth(FS(140))
        self.id_input.setMaximumWidth(FS(180))
        id_layout.addWidget(self.id_input)
        idpw_layout.addLayout(id_layout)
        
        pw_layout = QtWidgets.QHBoxLayout()
        pw_layout.addWidget(QtWidgets.QLabel("비밀번호:"))
        self.pw_input = QtWidgets.QLineEdit(saved_pw)
        self.pw_input.setEchoMode(QtWidgets.QLineEdit.Password)
        self.pw_input.setMinimumWidth(FS(140))
        self.pw_input.setMaximumWidth(FS(180))
        pw_layout.addWidget(self.pw_input)
        idpw_layout.addLayout(pw_layout)
        
        login_layout.addLayout(idpw_layout)
        
        # 2. 가운데: 로그인 버튼
        self.login_btn = QtWidgets.QPushButton('🔐 키즈노트 로그인 열기')
        self.login_btn.clicked.connect(self.open_browser)
        self.login_btn.setMinimumWidth(FS(180))
        self.login_btn.setMinimumHeight(FS(60))
        self.login_btn.setStyleSheet(f"""
            QPushButton {{ background-color: #FFC300; color: #2D3748; font-weight: bold; border-radius: {S(6)}px; font-size: {FS(15)}px; }}
            QPushButton:hover {{ background-color: #E6B000; }}
            QPushButton:disabled {{ background-color: #FFDE59; color: #8A94A6; }}
        """)
        login_layout.addWidget(self.login_btn)
        
        # 3. 오른쪽: 저장 설정 및 보안 안내문
        chk_notice_layout = QtWidgets.QVBoxLayout()
        chk_notice_layout.setSpacing(FS(5))
        
        self.chk_remember = QtWidgets.QCheckBox("내 PC에 로그인 정보 자동저장")
        self.chk_remember.setChecked(saved_remember)
        self.chk_remember.setStyleSheet(f"color: #03A9F4; font-weight: bold; font-size: {FS(13)}px;")
        chk_notice_layout.addWidget(self.chk_remember)
        
        security_notice = QtWidgets.QLabel("※ 입력정보는 현재 이 PC에만 저장되며\n절대 외부 서버로 전송되지 않습니다.")
        security_notice.setStyleSheet(f"color: gray; font-size: {FS(11)}px;")
        chk_notice_layout.addWidget(security_notice)
        
        login_layout.addLayout(chk_notice_layout)
        login_layout.addStretch() # 오른쪽 끝 여백 채우기
        
        login_group.setLayout(login_layout)
        main_layout.addWidget(login_group)

        # Tray Icon for notifications
        self.tray_icon = QtWidgets.QSystemTrayIcon(self)
        self.tray_icon.setIcon(app_icon)
        self.tray_icon.show()

        # Status Label and Progress Bar 
        status_prog_layout = QtWidgets.QHBoxLayout()
        
        self.status_label = QtWidgets.QLabel('준비됨')
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        self.status_label.setStyleSheet(f"font-weight: bold; color: white; background-color: #03A9F4; font-size: {FS(16)}px; padding: {FS(8)}px; border-radius: {S(5)}px;")
        status_prog_layout.addWidget(self.status_label, stretch=1)
        
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: {S(2)}px solid #E2E8F0;
                border-radius: {S(5)}px;
                text-align: center;
                font-weight: bold;
                font-size: {FS(14)}px;
                color: #2D3748;
                background-color: white;
            }}
            QProgressBar::chunk {{
                background-color: #FFC300;
                border-radius: {S(3)}px;
            }}
        """)
        status_prog_layout.addWidget(self.progress_bar, stretch=2)
        main_layout.addLayout(status_prog_layout)

        # Collect Options Group (1단계: 아이 현황 및 수집 범위)
        collect_group = QtWidgets.QGroupBox("1단계: 아이 현황 및 수집 범위")
        collect_main_layout = QtWidgets.QHBoxLayout()

        # 왼쪽: 아이 현황 (프로필 이미지, 라벨, 콤보박스)
        left_layout = QtWidgets.QVBoxLayout()
        left_layout.setAlignment(QtCore.Qt.AlignCenter)
        left_layout.setSpacing(FS(5))
        
        # Profile Image Label
        self.profile_img_label = QtWidgets.QLabel()
        self.profile_img_label.setFixedSize(FS(96), FS(96))
        self.profile_img_label.setStyleSheet(f"border-radius: {FS(48)}px; background-color: #E2E8F0;")
        self.profile_img_label.setAlignment(QtCore.Qt.AlignCenter)
        self.profile_img_label.setText("사진")
        left_layout.addWidget(self.profile_img_label, alignment=QtCore.Qt.AlignCenter)

        
        # Child Combobox
        self.child_combo = QtWidgets.QComboBox()
        self.child_combo.addItem("1단계를 진행하세요")
        self.child_combo.setEnabled(False)
        self.child_combo.setMinimumHeight(FS(36))
        self.child_combo.setStyleSheet(f"font-weight: bold; font-size: {FS(13)}px; color: #2D3748; background-color: #F7FAFC; border: {S(2)}px solid #E2E8F0; border-radius: {S(5)}px;")
        self.child_combo.currentIndexChanged.connect(self.on_child_combo_changed)
        left_layout.addWidget(self.child_combo)

        # 오른쪽: 기존 1단계 내용 (배너, 알림장/앨범 선택, 조회 기간, 버튼)
        right_layout = QtWidgets.QVBoxLayout()

        # 수집 중 상태 안내 배너 (기본 숨김)
        self.loading_banner = QtWidgets.QLabel("⏳ 추억 목록을 불러오는 중입니다... 잠시 기다려 주세요.")
        self.loading_banner.setAlignment(QtCore.Qt.AlignCenter)
        self.loading_banner.setStyleSheet(f"""
            background-color: #FFF3CD; color: #856404; font-weight: bold; 
            font-size: {FS(13)}px; padding: {S(5)}px; border-radius: {S(5)}px; border: {S(1)}px solid #FCEEBB;
        """)
        self.loading_banner.setVisible(False)
        right_layout.addWidget(self.loading_banner)

        btn_layout = QtWidgets.QHBoxLayout()

        # 체크박스 (알림장/앨범)
        chk_layout = QtWidgets.QVBoxLayout()
        chk_layout.setAlignment(QtCore.Qt.AlignVCenter)
        chk_layout.setSpacing(FS(5))
        self.chk_report = QtWidgets.QCheckBox("알림장")
        self.chk_report.setChecked(True)
        self.chk_album = QtWidgets.QCheckBox("앨범")
        self.chk_album.setChecked(True)
        chk_layout.addWidget(self.chk_report)
        chk_layout.addWidget(self.chk_album)
        btn_layout.addLayout(chk_layout)

        # 조회 기간 — 날짜 범위 직접 지정 (기본값: 전체 기간에 해당하는 넓은 범위)
        period_layout = QtWidgets.QVBoxLayout()
        period_layout.addWidget(QtWidgets.QLabel("조회 기간 (달력 클릭으로 변경):"))
        date_range_layout = QtWidgets.QHBoxLayout()
        date_range_layout.setSpacing(FS(4))
        self.start_date_edit = QtWidgets.QDateEdit()
        self.start_date_edit.setDisplayFormat("yyyy.MM.dd")
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDate(QtCore.QDate(2000, 1, 1))  # 사실상 '전체'
        self.end_date_edit = QtWidgets.QDateEdit()
        self.end_date_edit.setDisplayFormat("yyyy.MM.dd")
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDate(QtCore.QDate.currentDate())
        date_range_layout.addWidget(self.start_date_edit)
        date_range_layout.addWidget(QtWidgets.QLabel("~"))
        date_range_layout.addWidget(self.end_date_edit)
        period_layout.addLayout(date_range_layout)
        btn_layout.addLayout(period_layout)

        # 추억 목록 불러오기 / 작업 중지 버튼 (세로 배치)
        action_btn_layout = QtWidgets.QVBoxLayout()
        action_btn_layout.setSpacing(FS(5))
        
        self.load_btn = QtWidgets.QPushButton('2. 추억 목록 불러오기')
        self.load_btn.clicked.connect(self.load_memories)
        self.load_btn.setEnabled(False)
        self.load_btn.setFixedHeight(FS(40))
        self.load_btn.setStyleSheet(f"""
            QPushButton {{ background-color: #FFC300; color: #2D3748; font-weight: bold; border-radius: {S(6)}px; font-size: {FS(14)}px; }}
            QPushButton:hover {{ background-color: #E6B000; }}
            QPushButton:disabled {{ background-color: #FFDE59; color: #8A94A6; }}
        """)
        action_btn_layout.addWidget(self.load_btn)

        self.stop_btn = QtWidgets.QPushButton('작업 중지')
        self.stop_btn.clicked.connect(self.stop_memories)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setFixedHeight(FS(40))
        self.stop_btn.setStyleSheet(f"""
            QPushButton {{ background-color: #E53E3E; color: white; font-weight: bold; border-radius: {S(6)}px; font-size: {FS(14)}px; }}
            QPushButton:hover {{ background-color: #C53030; }}
            QPushButton:disabled {{ background-color: #FC8181; }}
        """)
        action_btn_layout.addWidget(self.stop_btn)

        btn_layout.addLayout(action_btn_layout)

        right_layout.addLayout(btn_layout)

        # 좌우 레이아웃을 메인에 합치고 구분선 추가
        collect_main_layout.addLayout(left_layout, stretch=1)
        
        v_line = QtWidgets.QFrame()
        v_line.setFrameShape(QtWidgets.QFrame.VLine)
        v_line.setFrameShadow(QtWidgets.QFrame.Sunken)
        v_line.setStyleSheet("border: 1px solid #E2E8F0;")
        collect_main_layout.addWidget(v_line)
        
        collect_main_layout.addLayout(right_layout, stretch=3)

        collect_group.setLayout(collect_main_layout)
        main_layout.addWidget(collect_group)

        # Table View Group
        table_group = QtWidgets.QGroupBox("2단계: 수집된 추억 목록 확인 및 선택")
        table_layout = QtWidgets.QVBoxLayout()

        # Select/Deselect and Search
        target_layout = QtWidgets.QHBoxLayout()
        self.select_all_btn = QtWidgets.QPushButton("전체 선택")
        self.select_all_btn.clicked.connect(self.select_all)
        self.deselect_all_btn = QtWidgets.QPushButton("전체 해제")
        self.deselect_all_btn.clicked.connect(self.deselect_all)
        self.select_new_btn = QtWidgets.QPushButton("새 항목만 선택")
        self.select_new_btn.setToolTip("이 PC에서 아직 받은 적 없는 항목만 체크합니다 (증분 백업)")
        self.select_new_btn.clicked.connect(self.select_new_only)
        target_layout.addWidget(self.select_all_btn)
        target_layout.addWidget(self.deselect_all_btn)
        target_layout.addWidget(self.select_new_btn)
        
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("검색어 입력 (제목, 작성자 등)")
        self.search_input.textChanged.connect(self.filter_table)
        target_layout.addWidget(self.search_input)
        
        self.selection_label = QtWidgets.QLabel("선택됨: 0 / 전체: 0")
        self.selection_label.setStyleSheet(f"font-weight: bold; color: #E65100; font-size: {FS(14)}px; margin-left: {FS(10)}px;")
        target_layout.addWidget(self.selection_label)
        
        table_layout.addLayout(target_layout)

        # Table View
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(7)
        # 테이블의 기본 높이를 확 줄여서(250), 초기 빈 상태에선 앱 중앙 스크롤이 생기지 않도록 방지
        self.table.setMinimumHeight(FS(250))
        self.table.setHorizontalHeaderLabels(['선택', '날짜', '제목', '종류', '작성자', '사진', '백업'])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self.table.setColumnWidth(0, FS(40))
        self.table.setColumnWidth(1, FS(110))  # 날짜: "2026.01.26"
        self.table.setColumnWidth(3, FS(70))   # 종류: 알림장/앨범
        self.table.setColumnWidth(4, FS(180))  # 작성자: "2025 GREEN 교사" 등
        self.table.setColumnWidth(5, FS(45))   # 사진: O/X
        self.table.setColumnWidth(6, FS(50))   # 백업: 이전에 받은 항목 O 표시

        # 헤더 클릭 정렬: 화살표 표시 + 오름/내림 토글 (선택 컬럼은 체크 상태 기준)
        table_header = self.table.horizontalHeader()
        table_header.setSortIndicatorShown(True)
        # 정렬 후에는 행 위치가 바뀌므로, 위치 기준인 검색 필터 숨김 상태를 재적용
        table_header.sortIndicatorChanged.connect(
            lambda *_: QtCore.QTimer.singleShot(0, lambda: self.filter_table(self.search_input.text()))
        )
        # 체크박스(0번 컬럼) 상태 변경 시 선택 개수 라벨 갱신
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.setSortingEnabled(True)
        table_layout.addWidget(self.table)
        
        table_group.setLayout(table_layout)
        main_layout.addWidget(table_group)

        # Download Options Layout
        options_group = QtWidgets.QGroupBox("3단계: 최종 다운로드 설정")
        options_layout = QtWidgets.QVBoxLayout()

        # Directory Selection
        dir_layout = QtWidgets.QHBoxLayout()
        self.dir_input = QtWidgets.QLineEdit()
        self.dir_input.setPlaceholderText("저장할 디렉토리를 선택하세요")
        self.dir_input.setText(os.path.join(os.path.expanduser("~"), "Downloads", "Kidsnote_Memories"))
        dir_layout.addWidget(self.dir_input)
        
        self.dir_btn = QtWidgets.QPushButton("경로 선택")
        self.dir_btn.clicked.connect(self.select_directory)
        dir_layout.addWidget(self.dir_btn)

        self.open_dir_btn = QtWidgets.QPushButton("경로 열기")
        self.open_dir_btn.clicked.connect(self.open_directory)
        dir_layout.addWidget(self.open_dir_btn)

        options_layout.addLayout(dir_layout)

        # 3단계 옵션박스 전용 초밀착(Tight) 스타일 
        tight_group_style = f"""
            QGroupBox {{
                border: {S(1)}px solid #E2E8F0;
                border-radius: {S(4)}px;
                margin-top: {FS(8)}px;
                padding-top: {FS(12)}px;
                padding-bottom: {FS(0)}px;
                font-weight: bold;
                background-color: white;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: {FS(5)}px;
                padding: 0 {S(2)}px;
                color: #FF5722;
            }}
        """

        # Folder Options Group
        folder_group_box = QtWidgets.QGroupBox("저장 방식")
        folder_group_box.setStyleSheet(tight_group_style)
        self.folder_btn_group = QtWidgets.QButtonGroup()
        self.radio_layout_folder = QtWidgets.QHBoxLayout()
        self.radio_layout_folder.setContentsMargins(FS(5), 0, FS(5), 0)
        self.folder_individual_radio = QtWidgets.QRadioButton("개별 디렉토리에 저장 (날짜별)")
        self.folder_individual_radio.setChecked(True)
        self.folder_single_radio = QtWidgets.QRadioButton("한 곳에 모두 저장")
        self.folder_btn_group.addButton(self.folder_individual_radio)
        self.folder_btn_group.addButton(self.folder_single_radio)
        self.radio_layout_folder.addWidget(self.folder_individual_radio)
        self.radio_layout_folder.addWidget(self.folder_single_radio)
        folder_group_box.setLayout(self.radio_layout_folder)

        # File Type Option Group
        filetype_group_box = QtWidgets.QGroupBox("다운로드 항목 종류")
        filetype_group_box.setStyleSheet(tight_group_style)
        self.filetype_btn_group = QtWidgets.QButtonGroup()
        radio_layout = QtWidgets.QHBoxLayout()
        radio_layout.setContentsMargins(FS(5), 0, FS(5), 0)
        self.pdf_radio = QtWidgets.QRadioButton("전체 페이지 PDF 저장")
        self.pdf_radio.setChecked(True)
        self.photo_radio = QtWidgets.QRadioButton("사진+동영상만 받기")
        self.filetype_btn_group.addButton(self.pdf_radio)
        self.filetype_btn_group.addButton(self.photo_radio)
        radio_layout.addWidget(self.pdf_radio)
        radio_layout.addWidget(self.photo_radio)
        self.chk_exclude_video = QtWidgets.QCheckBox("동영상 제외")
        self.chk_exclude_video.setToolTip("체크하면 사진만 받고 동영상은 건너뜁니다 (용량 절약)")
        radio_layout.addWidget(self.chk_exclude_video)
        filetype_group_box.setLayout(radio_layout)

        # Overwrite Option Group
        overwrite_group_box = QtWidgets.QGroupBox("동일 항목 덮어쓰기")
        overwrite_group_box.setStyleSheet(tight_group_style)
        self.overwrite_btn_group = QtWidgets.QButtonGroup()
        radio_layout_overwrite = QtWidgets.QHBoxLayout()
        radio_layout_overwrite.setContentsMargins(FS(5), 0, FS(5), 0)
        self.overwrite_allow_radio = QtWidgets.QRadioButton("허용")
        self.overwrite_allow_radio.setChecked(True)
        self.overwrite_skip_radio = QtWidgets.QRadioButton("넘어가기")
        self.overwrite_btn_group.addButton(self.overwrite_allow_radio)
        self.overwrite_btn_group.addButton(self.overwrite_skip_radio)
        radio_layout_overwrite.addWidget(self.overwrite_allow_radio)
        radio_layout_overwrite.addWidget(self.overwrite_skip_radio)
        overwrite_group_box.setLayout(radio_layout_overwrite)

        options_grid = QtWidgets.QGridLayout()
        options_grid.setSpacing(FS(5))  # 그리드 사이 간격 축소
        options_grid.addWidget(overwrite_group_box, 0, 0)
        options_grid.addWidget(filetype_group_box, 0, 1)
        options_grid.addWidget(folder_group_box, 1, 0, 1, 2)
        
        options_layout.addLayout(options_grid)
        
        options_group.setLayout(options_layout)
        main_layout.addWidget(options_group)

        # Download Button + Pause Button
        download_row = QtWidgets.QHBoxLayout()
        self.download_btn = QtWidgets.QPushButton('3. 선택한 항목 다운로드 시작')
        self.download_btn.clicked.connect(self.start_download)
        self.download_btn.setEnabled(False)
        self.download_btn.setFixedHeight(FS(40))
        self.download_btn.setStyleSheet(f"""
            QPushButton {{ background-color: #FFC300; color: #2D3748; font-weight: bold; border-radius: {S(6)}px; }}
            QPushButton:hover {{ background-color: #E6B000; }}
            QPushButton:disabled {{ background-color: #FFDE59; color: #8A94A6; }}
        """)
        download_row.addWidget(self.download_btn, stretch=4)

        self.pause_btn = QtWidgets.QPushButton('일시정지')
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setFixedHeight(FS(40))
        self.pause_btn.setToolTip("현재 항목까지 마친 뒤 잠시 멈춥니다. 다시 누르면 이어서 진행합니다.")
        download_row.addWidget(self.pause_btn, stretch=1)
        main_layout.addLayout(download_row)

        # (QScrollArea 제거됨: 레이아웃이 self에 직접 연결되었으므로 추가 설정 불필요)

        # --- 로딩 오버레이 ---
        self._overlay = QtWidgets.QWidget(self)
        self._overlay.setStyleSheet("background-color: rgba(0, 0, 0, 160);")
        self._overlay_label = QtWidgets.QLabel("잠시만 기다려 주세요...", self._overlay)
        self._overlay_label.setAlignment(QtCore.Qt.AlignCenter)
        self._overlay_label.setStyleSheet(f"""
            color: white;
            font-size: {FS(18)}px;
            font-weight: bold;
            background: transparent;
            padding: {FS(20)}px;
        """)
        self._overlay_label.setWordWrap(True)
        overlay_layout = QtWidgets.QVBoxLayout(self._overlay)
        overlay_layout.addStretch()
        overlay_layout.addWidget(self._overlay_label)
        overlay_layout.addStretch()
        self._overlay.hide()

        # --- 1단계 잠금 오버레이 (로그인 전 메뉴 접근 방지) ---
        self.lock_overlay = QtWidgets.QWidget(self)
        self.lock_overlay.setStyleSheet("background-color: rgba(240, 240, 240, 200);")
        lock_label = QtWidgets.QLabel("위에서 '키즈노트 로그인 열기'를 먼저 완료해 주세요", self.lock_overlay)
        lock_label.setAlignment(QtCore.Qt.AlignCenter)
        lock_label.setStyleSheet(f"color: #2D3748; font-size: {FS(18)}px; font-weight: bold; background: transparent;")
        lock_layout = QtWidgets.QVBoxLayout(self.lock_overlay)
        lock_layout.addWidget(lock_label)
        self.lock_overlay.show()
        self.lock_overlay.raise_()

        # --- 2/3단계 잠금 오버레이 (추억 목록 불러오기 전 접근 방지) ---
        self.stage2_lock_overlay = QtWidgets.QWidget(self)
        self.stage2_lock_overlay.setStyleSheet("background-color: rgba(240, 240, 240, 210);")
        stage2_lock_label = QtWidgets.QLabel("먼저 1단계에서 [추억 목록 불러오기]를 진행해 주세요", self.stage2_lock_overlay)
        stage2_lock_label.setAlignment(QtCore.Qt.AlignCenter)
        stage2_lock_label.setStyleSheet(f"color: #2D3748; font-size: {FS(18)}px; font-weight: bold; background: transparent;")
        stage2_lock_layout = QtWidgets.QVBoxLayout(self.stage2_lock_overlay)
        stage2_lock_layout.addWidget(stage2_lock_label)
        self.stage2_lock_overlay.hide()  # 초기에는 1단계 오버레이가 가리고 있으므로 숨김 (1단계 열릴 때 같이 켬)

        # 위치 계산에 필요한 핵심 위젯 참조 저장
        self.table_group = table_group

    # --- 로딩 및 잠금 오버레이 제어 ---
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._overlay.setGeometry(self.rect())
        
        # 1단계 잠금 오버레이 (로그인 후 해제)
        if hasattr(self, 'lock_overlay') and hasattr(self, 'status_label'):
            y_offset = self.status_label.geometry().bottom()
            if y_offset > 0:
                new_geom = QtCore.QRect(0, y_offset, self.width(), self.height() - y_offset)
                if self.lock_overlay.geometry() != new_geom:
                    self.lock_overlay.setGeometry(new_geom)

        # 2/3단계 잠금 오버레이 (목록 불러오기 로드완료 후 해제)
        if hasattr(self, 'stage2_lock_overlay') and hasattr(self, 'table_group') and self.stage2_lock_overlay.isVisible():
            y_offset_stage2 = self.table_group.geometry().top()
            if y_offset_stage2 > 0:
                new_geom_stage2 = QtCore.QRect(0, y_offset_stage2, self.width(), self.height() - y_offset_stage2)
                if self.stage2_lock_overlay.geometry() != new_geom_stage2:
                    self.stage2_lock_overlay.setGeometry(new_geom_stage2)

    def _show_overlay(self, text='잠시만 기다려 주세요...'):
        self.run_on_ui_thread(lambda: self._do_show_overlay(text))

    def _hide_overlay(self):
        self.run_on_ui_thread(self._do_hide_overlay)

    def _update_overlay_text(self, text):
        self.run_on_ui_thread(lambda: self._do_update_overlay(text))

    @QtCore.pyqtSlot(str)
    def _do_show_overlay(self, text):
        self._overlay_label.setText(text)
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()
        self._overlay.show()

    @QtCore.pyqtSlot()
    def _do_hide_overlay(self):
        self._overlay.hide()

    @QtCore.pyqtSlot(str)
    def _do_update_overlay(self, text):
        self._overlay_label.setText(text)

    @QtCore.pyqtSlot()
    def _hide_lock_overlay(self):
        if hasattr(self, 'lock_overlay'):
            self.lock_overlay.hide()

    @QtCore.pyqtSlot()
    def _show_stage2_lock_overlay(self):
        if hasattr(self, 'stage2_lock_overlay'):
            self.stage2_lock_overlay.show()
            self.stage2_lock_overlay.raise_()
            self.resizeEvent(None)

    def select_directory(self):
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "저장 폴더 선택")
        if directory:
            self.dir_input.setText(directory)

    def open_directory(self):
        target_dir = self.dir_input.text()
        if os.path.exists(target_dir):
            os.startfile(target_dir)
        else:
            QtWidgets.QMessageBox.warning(self, "오류", "해당 경로가 아직 존재하지 않습니다.")

    def open_browser(self):
        username = self.id_input.text().strip()
        password = self.pw_input.text().strip()
        
        # Save credentials locally if checked
        if not self.config.has_section('Login'):
            self.config.add_section('Login')
        if self.chk_remember.isChecked():
            # 비밀번호는 Windows DPAPI(사용자 계정 단위 암호화)로 저장 — base64 평문 저장 금지
            self.config.set('Login', 'id', username)
            self.config.set('Login', 'pw', manager.protect_secret(password))
            self.config.set('Login', 'remember', 'True')
        else:
            self.config.set('Login', 'id', '')
            self.config.set('Login', 'pw', '')
            self.config.set('Login', 'remember', 'False')
            
        with open(self.config_path, 'w') as f:
            self.config.write(f)

        self.status_label.setText('브라우저 여는 중 및 로그인 입력 중...')
        self.login_btn.setEnabled(False)
        self._window_geo_for_driver = (self.x(), self.y(), self.width(), self.height())
        self._show_overlay('🔐 키즈노트 브라우저를 여는 중...')
        threading.Thread(target=self._init_driver, args=(username, password), daemon=True).start()

    def _get_installed_edge_version(self):
        edge_dirs = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application",
            r"C:\Program Files\Microsoft\Edge\Application",
        ]
        versions = []
        for edge_dir in edge_dirs:
            try:
                for name in os.listdir(edge_dir):
                    parts = name.split(".")
                    if len(parts) == 4 and all(part.isdigit() for part in parts):
                        versions.append(name)
            except Exception:
                pass
        if not versions:
            return ""

        def version_key(version):
            return tuple(int(part) for part in version.split("."))

        return sorted(versions, key=version_key)[-1]

    def _get_driver_version(self, driver_path):
        try:
            import subprocess
            result = subprocess.run(
                [driver_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=0x08000000,
            )
            import re
            match = re.search(r"(\d+\.\d+\.\d+\.\d+)", result.stdout or result.stderr or "")
            return match.group(1) if match else ""
        except Exception:
            return ""

    def _is_compatible_edge_driver(self, edge_version, driver_version):
        if not edge_version or not driver_version:
            return False
        return edge_version.split(".")[:3] == driver_version.split(".")[:3]

    def _driver_cache_root(self):
        return os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "KidsnoteMemoriesSaver",
            "drivers",
        )

    def _edge_driver_package_name(self):
        import platform
        machine = platform.machine().lower()
        if "arm64" in machine or "aarch64" in machine:
            return "edgedriver_arm64.zip"
        if machine in ("x86", "i386", "i686") or machine.endswith("32"):
            return "edgedriver_win32.zip"
        return "edgedriver_win64.zip"

    def _find_cached_edge_driver(self, edge_version):
        cache_root = self._driver_cache_root()
        try:
            for root, dirs, files in os.walk(cache_root):
                if "msedgedriver.exe" not in files:
                    continue
                driver_path = os.path.join(root, "msedgedriver.exe")
                if self._is_compatible_edge_driver(edge_version, self._get_driver_version(driver_path)):
                    return driver_path
        except Exception:
            pass
        return ""

    def _edge_driver_download_versions(self, edge_version):
        versions = [edge_version]
        build_version = ".".join(edge_version.split(".")[:3])
        latest_url = f"https://msedgedriver.microsoft.com/LATEST_RELEASE_{build_version}"
        try:
            import urllib.request
            req = urllib.request.Request(latest_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as response:
                latest = response.read().decode("utf-8", errors="ignore").strip()
            if latest and latest not in versions:
                versions.append(latest)
        except Exception:
            pass
        return versions

    def _cleanup_driver_cache(self, keep_driver_path):
        cache_root = self._driver_cache_root()
        try:
            keep_dir = os.path.dirname(os.path.abspath(keep_driver_path)) if keep_driver_path else ""
            version_dirs = []
            for name in os.listdir(cache_root):
                path = os.path.join(cache_root, name)
                if os.path.isdir(path) and path != keep_dir:
                    version_dirs.append((os.path.getmtime(path), path))
            for _, path in sorted(version_dirs, reverse=True)[5:]:
                import shutil
                shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass

    def _cache_driver_copy(self, source_path, cache_name):
        if not source_path or not os.path.exists(source_path):
            return ""
        try:
            driver_version = self._get_driver_version(source_path) or "unknown"
            cache_dir = os.path.join(self._driver_cache_root(), cache_name, driver_version)
            cached_path = os.path.join(cache_dir, "msedgedriver.exe")
            if not os.path.exists(cached_path):
                os.makedirs(cache_dir, exist_ok=True)
                shutil.copy2(source_path, cached_path)
            return cached_path
        except Exception:
            return source_path

    def _download_edge_driver(self, edge_version):
        if not edge_version:
            return ""

        cached_driver = self._find_cached_edge_driver(edge_version)
        if cached_driver:
            return cached_driver

        package_name = self._edge_driver_package_name()
        cache_dir = os.path.join(self._driver_cache_root(), edge_version)
        driver_path = os.path.join(cache_dir, "msedgedriver.exe")
        if self._is_compatible_edge_driver(edge_version, self._get_driver_version(driver_path)):
            return driver_path

        for download_version in self._edge_driver_download_versions(edge_version):
            try:
                import io
                import zipfile
                import urllib.request
                os.makedirs(cache_dir, exist_ok=True)
                url = f"https://msedgedriver.microsoft.com/{download_version}/{package_name}"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                self.update_status(f"Edge {edge_version}에 맞는 WebDriver를 자동 다운로드 중...")
                with urllib.request.urlopen(req, timeout=30) as response:
                    data = response.read()
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    exe_names = [name for name in zf.namelist() if os.path.basename(name).lower() == "msedgedriver.exe"]
                    if not exe_names:
                        continue
                    with open(driver_path, "wb") as f:
                        f.write(zf.read(exe_names[0]))
                if self._is_compatible_edge_driver(edge_version, self._get_driver_version(driver_path)):
                    self._cleanup_driver_cache(driver_path)
                    return driver_path
            except Exception:
                continue
        return ""

    def _start_edge_driver(self, options, bundled_driver_path):
        from selenium.webdriver.edge.service import Service
        from selenium.common.exceptions import SessionNotCreatedException, WebDriverException

        edge_version = self._get_installed_edge_version()
        candidates = []

        manual_driver_path = os.environ.get("KIDSNOTE_MSEDGEDRIVER", "")
        if not manual_driver_path:
            app_dir = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
            manual_driver_path = os.path.join(app_dir, "msedgedriver.exe")

        if manual_driver_path and os.path.exists(manual_driver_path):
            if self._is_compatible_edge_driver(edge_version, self._get_driver_version(manual_driver_path)):
                candidates.append(manual_driver_path)

        bundled_driver_cached = self._cache_driver_copy(bundled_driver_path, "bundled")
        bundled_version = self._get_driver_version(bundled_driver_cached)
        if self._is_compatible_edge_driver(edge_version, bundled_version):
            candidates.append(bundled_driver_cached)
        else:
            downloaded_driver = self._download_edge_driver(edge_version)
            if downloaded_driver:
                candidates.append(downloaded_driver)
            if bundled_driver_cached and os.path.exists(bundled_driver_cached):
                candidates.append(bundled_driver_cached)
            if manual_driver_path and os.path.exists(manual_driver_path):
                candidates.append(manual_driver_path)

        tried = set()
        last_error = None
        for driver_path in candidates:
            if not driver_path or driver_path in tried:
                continue
            tried.add(driver_path)
            try:
                return webdriver.Edge(service=Service(executable_path=driver_path), options=options)
            except SessionNotCreatedException as e:
                last_error = e
                continue
            except WebDriverException as e:
                last_error = e
                continue

        self.update_status("내장 WebDriver로 실행하지 못해 Selenium Manager로 재시도합니다...")
        try:
            return webdriver.Edge(options=options)
        except WebDriverException:
            if last_error:
                raise last_error
            raise

    def _init_driver(self, username, password):
        try:
            write_app_log("Login/profile initialization started")
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.keys import Keys
            
            options = webdriver.EdgeOptions()
            options.add_argument('--window-size=1100,900')
            # 윈도우 잔류 프로세스로 인한 PyInstaller 임시폴더(_MEI) 삭제 오류 방지를 위해 detach 해제
            # options.add_experimental_option("detach", True) 

            # 내장된 msedgedriver.exe 경로 탐색 (PyInstaller 빌드 환경 vs 일반 환경)
            if hasattr(sys, '_MEIPASS'):
                driver_path = os.path.join(sys._MEIPASS, 'msedgedriver.exe')
            else:
                driver_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'msedgedriver.exe')

            self.driver = self._start_edge_driver(options, driver_path)

            # GUI 창의 위치/크기를 읽어 Edge를 바로 오른쪽에 배치
            try:
                win_x, win_y, win_w, win_h = getattr(self, "_window_geo_for_driver", (300, 30, 980, 900))
                chrome_x = win_x + win_w + 8
                chrome_y = win_y
                self.driver.set_window_position(chrome_x, chrome_y)
                self.driver.set_window_size(1100, win_h)
            except Exception:
                pass

            try:
                self.driver.set_page_load_timeout(120)
                self.driver.get("https://www.kidsnote.com/login")
                
                # Wait for login fields and fill them
                wait = WebDriverWait(self.driver, 90)
                user_field = wait.until(EC.presence_of_element_located((By.NAME, "username")))
            except Exception as init_e:
                self.update_status(f"로그인 페이지 로딩 실패: 네트워크 지연 ({init_e})")
                self.run_on_ui_thread(lambda: self.login_btn.setText("로그인 및 시작"))
                self.enable_widget(self.login_btn, True)
                self._hide_overlay()
                if self.driver:
                    try: self.driver.quit()
                    except: pass
                    self.driver = None
                try:
                    import subprocess
                    subprocess.run(["taskkill", "/f", "/t", "/im", "msedgedriver.exe"], shell=False, creationflags=0x08000000)
                except: pass
                return

            pass_field = self.driver.find_element(By.NAME, "password")
            
            user_field.send_keys(username)
            pass_field.send_keys(password)
            pass_field.send_keys(Keys.RETURN) # Auto-submit
            
            self.update_status("안전하게 로그인 되었습니다! 아이 목록을 조회하는 중...")
            self._update_overlay_text("✅ 로그인 성공! 아이 정보를 확인 중입니다...")
            self.run_on_ui_thread(self._hide_lock_overlay)
            
            # 1단계가 열리면 2,3단계를 아직 못 만지게 stage2 잠금 활성화
            self.run_on_ui_thread(self._show_stage2_lock_overlay)

            self.run_on_ui_thread(lambda: self.login_btn.setText("✅ 로그인 완료"))
            # 로그인 처리(URL 전환)가 끝나는 즉시 진행 — 기존 고정 5초/4초 대기 제거
            import time
            try:
                WebDriverWait(self.driver, 12).until(lambda d: "/login" not in d.current_url)
            except Exception:
                pass
            if "kidsnote.com/service" not in self.driver.current_url:
                self.driver.get("https://www.kidsnote.com/service")
            # 프로필 아바타가 렌더링되는 즉시 진행 (최대 10초)
            manager.wait_css(self.driver, "span[role='img']", timeout=10)

            # Wait until profile section loads (Check for size 65 active avatar)
            try:
                WebDriverWait(self.driver, 60).until(EC.presence_of_element_located((By.XPATH, "//*[@size='65' and @role='img']")))
                time.sleep(1) # 부가 컴포넌트(이름/나이 텍스트) 렌더링 대기
            except:
                pass
                
            self.children_data = []
            try:
                # 자녀 이미지는 레이지 로딩 → 클릭하여 활성(size=65)되어야 비로소 CSS에 URL이 주입됨
                # 전략: 각 자녀를 클릭→활성화→size=65 span의 computedStyle에서 URL 추출
                
                # 1단계: 자녀 이름/나이 목록만 먼저 수집
                name_script = (
                    'var results = [];'
                    'var spans = document.querySelectorAll("span[role=\'img\'][size=\'36\']");'
                    'for(var i=0; i<spans.length; i++){'
                    '  var container = spans[i].parentElement.parentElement;'
                    '  var pTags = container.querySelectorAll("p");'
                    '  if(pTags.length >= 2) {'
                    '    results.push([pTags[0].textContent.trim(), pTags[1].textContent.trim()]);'
                    '  }'
                    '}'
                    'return results;'
                )
                name_array = self.driver.execute_script(name_script)
                
                from selenium.webdriver.common.by import By
                click_elems = self.driver.find_elements(By.CSS_SELECTOR, "span[role='img'][size='36']")
                
                # 2단계: 각 자녀를 클릭하여 활성화 후 size=65 아바타의 URL 추출
                import time as _time
                child_array = []
                for idx, name_info in enumerate(name_array):
                    name, age = name_info
                    if not name or not age:
                        continue
                    orig_url = ""
                    
                    # 해당 자녀 클릭하여 활성화
                    self._update_overlay_text(f'📷 {name}의 프로필 사진 가져오는 중...\n({idx+1}/{len(name_array)})')
                    if idx < len(click_elems):
                        try:
                            self.driver.execute_script("arguments[0].click();", click_elems[idx])
                            _time.sleep(1.0)  # CSS 주입 대기
                        except Exception as click_e:
                            pass
                    
                    # 활성화된 size=65 span의 computedStyle에서 URL 추출
                    url_script = (
                        'var s = document.querySelector("span[role=\'img\'][size=\'65\']");'
                        'if(!s) { return ""; }'
                        'var img = s.querySelector("img");'
                        'if(img && (img.currentSrc || img.src)) { return img.currentSrc || img.src; }'
                        'var bg = window.getComputedStyle(s).backgroundImage || "";'
                        'var match = bg.match(/url\\(["\\\']?([^"\\\')]+)["\\\']?\\)/);'
                        'return match ? match[1] : "";'
                    )
                    bg_value = self.driver.execute_script(url_script)
                    
                    url = ""
                    if bg_value and bg_value != "none":
                        if bg_value.startswith("http") or bg_value.startswith("//") or bg_value.startswith("/"):
                            url = manager.normalize_media_url(self.driver, bg_value)
                            orig_url = url
                        # url("https://...") 형태도 예전 코드와 호환
                        elif "url(" in bg_value:
                            start = bg_value.index("url(") + 4
                            end = bg_value.index(")", start)
                            url = manager.normalize_media_url(self.driver, bg_value[start:end].strip('"').strip("'"))
                            orig_url = url
                        # GUI 프로필 썸네일 해상도 개선 (원본 화질로 올림)
                        if url:
                            url = url.replace('img_36x36.jpg', 'img_240x240.jpg')
                            url = url.replace('img_65x65.jpg', 'img_240x240.jpg')
                            url = url.replace('img_130x130.jpg', 'img_240x240.jpg')

                    # 사내망 등에서 requests 직접 다운로드가 차단돼도 얼굴이 뜨도록,
                    # 지금 활성화된 아바타 요소를 브라우저에서 직접 캡처해 둔다 (네트워크 불필요)
                    shot_b64 = ""
                    try:
                        avatar_elem = self.driver.find_element(By.CSS_SELECTOR, "span[role='img'][size='65']")
                        shot_b64 = avatar_elem.screenshot_as_base64
                    except Exception:
                        pass

                    child_array.append([name, age, url, orig_url, shot_b64])
                
                
                
                seen_names = set()
                img_fetch_fail_streak = 0  # 사내망 CDN 차단 시 자녀마다 수십 초씩 지연되는 것을 방지
                for idx, item in enumerate(child_array):
                    name, age, url, orig_url, shot_b64 = item
                    if not name or not age:
                        continue

                    text_val = f"{name} {age}"

                    if text_val not in seen_names:
                        seen_names.add(text_val)
                        img_b64 = None
                        if url and img_fetch_fail_streak < 2:
                            def profile_url_candidates(primary_url, fallback_url):
                                candidates = []
                                for base_url in [primary_url, fallback_url]:
                                    if not base_url:
                                        continue
                                    normalized = manager.normalize_media_url(self.driver, base_url)
                                    if normalized and normalized not in candidates:
                                        candidates.append(normalized)
                                    for size in [480, 360, 240]:
                                        upgraded = normalized
                                        for old in ['img_36x36.jpg', 'img_65x65.jpg', 'img_130x130.jpg', 'img_240x240.jpg']:
                                            upgraded = upgraded.replace(old, f'img_{size}x{size}.jpg')
                                        if upgraded and upgraded not in candidates:
                                            candidates.append(upgraded)
                                return candidates[:3]

                            def fetch_img(req_url):
                                import base64
                                img_data, _ = manager.fetch_bytes_with_browser_session(self.driver, req_url, timeout=3)
                                try:
                                    from PIL import Image
                                    import io
                                    pil_img = Image.open(io.BytesIO(img_data))
                                    pil_img.thumbnail((512, 512), Image.LANCZOS)
                                    buf = io.BytesIO()
                                    pil_img.save(buf, format='PNG')
                                    img_data = buf.getvalue()
                                except:
                                    pass
                                return base64.b64encode(img_data).decode('utf-8')
                            for candidate_url in profile_url_candidates(url, orig_url):
                                try:
                                    img_b64 = fetch_img(candidate_url)
                                    if img_b64:
                                        break
                                except Exception:
                                    continue
                            if img_b64:
                                img_fetch_fail_streak = 0
                            else:
                                img_fetch_fail_streak += 1

                        # 원본 다운로드 실패(사내망 차단 등) 시 브라우저 캡처본으로 대체
                        if not img_b64 and shot_b64:
                            img_b64 = shot_b64

                        click_elem = click_elems[idx] if idx < len(click_elems) else None
                        self.children_data.append({
                            "text": text_val, 
                            "elem": click_elem,
                            "img_b64": img_b64
                        })
            except Exception as e:
                pass
                
            # Populate Combo Box
            write_app_log(f"Profile loading completed. children={len(getattr(self, 'children_data', []))}")
            self.run_on_ui_thread(self.populate_children_combo)
            
            self.enable_widget(self.load_btn, True)
            self._hide_overlay()
            # 로그인 성공 후 두 번째 팝업 띄우기 (GUI 스레드 안전 호출)
            self.run_on_ui_thread(self.show_post_login_popup)
        except Exception as e:
            write_app_log("Login/profile initialization failed:\n" + traceback.format_exc())
            error_text = str(e)
            if "session not created" in error_text.lower() or "driver" in error_text.lower():
                self.update_status(
                    "Edge WebDriver 자동 설정 실패: 회사망 다운로드 차단 또는 Edge 정책 제한을 확인해주세요."
                )
            else:
                self.update_status(f"브라우저 실행 또는 입력 오류: {e}")
            self.enable_widget(self.login_btn, True)
            self._hide_overlay()

    @QtCore.pyqtSlot()
    def populate_children_combo(self):
        if hasattr(self, 'lock_overlay'):
            self.lock_overlay.hide()
            
        if hasattr(self, 'children_data') and self.children_data:
            self.child_combo.blockSignals(True)
            self.child_combo.clear()
            for child in self.children_data:
                self.child_combo.addItem(child['text'])
            self.child_combo.setEnabled(True)
            self.child_combo.blockSignals(False)
            self.update_status(f"로그인 완료! 총 {len(self.children_data)}명의 자녀를 찾았습니다.")
            # 첫 번째 자녀를 기본으로 화면(우측 상단 프로필)에 즉각 반영
            if len(self.children_data) > 0:
                first_child = self.children_data[self.child_combo.currentIndex()]
                self.run_on_ui_thread(lambda: self.update_profile({"text": first_child["text"], "image": first_child.get("img_b64", None)}))
        else:
            self.update_status("로그인 완료! 아이 목록을 찾을 수 없으므로 브라우저에서 직접 선택해주세요.")

    def on_child_combo_changed(self, index):
        if not (hasattr(self, 'children_data') and 0 <= index < len(self.children_data)):
            return
        if not self.driver:
            return
        if self.is_downloading or self.is_loading_memories:
            # 작업 중 드라이버 동시 조작 방지 (사실상 콤보는 잠겨 있지만 이중 방어)
            self.update_status("작업이 진행 중이라 아이 전환을 할 수 없습니다. 작업 완료 후 다시 선택하세요.")
            return

        child_info = self.children_data[index]
        combo_text = self.child_combo.currentText()
        # 드라이버 명령(driver.get + sleep)을 GUI 스레드에서 실행하면 사내망 지연 시
        # 최대 페이지 로드 타임아웃(120초)까지 UI 전체가 얼어붙으므로 백그라운드로 이동
        self.child_combo.setEnabled(False)
        self.update_status(f"[{combo_text}] 계정으로 전환하는 중...")
        threading.Thread(target=self._switch_child_worker, args=(child_info, combo_text), daemon=True).start()

    def _switch_child_worker(self, child_info, combo_text):
        try:
            import time
            name = child_info['text'].split()[0]
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

            # 강제로 최상단 서비스 홈으로 돌린 상태에서 클릭해야 꼬이지 않음
            if "kidsnote.com/service" not in self.driver.current_url:
                self.driver.get("https://www.kidsnote.com/service")
                time.sleep(1.5)

            self.driver.execute_script(script, name)
            time.sleep(2)  # React 상태 변경 후 렌더링되도록 넉넉히 대기

            self.update_status(f"[{combo_text}] 계정으로 전환되었습니다. 이제 수집을 시작하세요.")
            self.run_on_ui_thread(
                lambda: self.update_profile({"text": child_info["text"], "image": child_info.get("img_b64", None)})
            )
        except Exception:
            write_app_log("Child switch failed:\n" + traceback.format_exc())
            self.update_status("아이 전환 중 오류가 발생했습니다. 잠시 후 다시 선택해 주세요.")
        finally:
            self.enable_widget(self.child_combo, True)

    @QtCore.pyqtSlot()
    def show_initial_popup(self):
        QtWidgets.QMessageBox.information(
            self, 
            "이용 안내", 
            "아이디와 비밀번호를 입력하신 후,\n\n'1. 키즈노트 로그인 열기' 버튼을 눌러주세요!\n(이미 입력되어 있다면 바로 누르시면 됩니다.)"
        )

    @QtCore.pyqtSlot()
    def show_post_login_popup(self):
        child_count = len(self.children_data) if hasattr(self, 'children_data') else 0
        if child_count > 1:
            msg = (
                f"🎉 로그인 성공! (자녀 {child_count}명)\n\n"
                "👧👦 아이를 선택하고\n"
                "⬇️ 1단계로 이동해서 '추억 목록 불러오기'를 클릭하세요!"
            )
        else:
            msg = "🎉 로그인 성공!\n\n⬇️ 바로 1단계에서 '추억 목록 불러오기'를 클릭하세요!"
            
        QtWidgets.QMessageBox.information(self, "다음 단계", msg)

    def update_progress(self, value):
        self.run_on_ui_thread(lambda: self.progress_bar.setValue(value))

    def _show_top_message(self, icon, title, text):
        box = QtWidgets.QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        box.setWindowModality(QtCore.Qt.ApplicationModal)
        box.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        box.show()
        box.raise_()
        box.activateWindow()
        return box.exec_()

    def _show_top_question(self, title, text, default_button=QtWidgets.QMessageBox.Yes):
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        box.setDefaultButton(default_button)
        box.setWindowModality(QtCore.Qt.ApplicationModal)
        box.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        box.show()
        box.raise_()
        box.activateWindow()
        return box.exec_()

    def _set_shared_controls_enabled(self, enabled):
        """수집/다운로드 중 동일 Edge 드라이버를 건드릴 수 있는 컨트롤을 일괄 잠금/해제.

        같은 WebDriver 세션을 두 스레드가 동시에 조작하면 명령이 꼬여
        '다운로드 준비 중...' 상태에서 멈추는 원인이 되므로 반드시 잠근다.
        """
        self.load_btn.setEnabled(enabled)
        self.chk_report.setEnabled(enabled)
        self.chk_album.setEnabled(enabled)
        self.start_date_edit.setEnabled(enabled)
        self.end_date_edit.setEnabled(enabled)
        self.child_combo.setEnabled(enabled and bool(getattr(self, 'children_data', None)))

    def _period_desc(self):
        """결과 안내 메시지에 쓸 조회 기간 설명 문자열."""
        return f"{self.start_date_edit.date().toString('yyyy.MM.dd')} ~ {self.end_date_edit.date().toString('yyyy.MM.dd')}"

    def load_memories(self):
        if not self.driver: return
        if self.is_downloading or self.is_loading_memories:
            QtWidgets.QMessageBox.warning(self, "안내", "이미 작업이 진행 중입니다. 완료 또는 중지 후 다시 시도하세요.")
            return
        if not self.chk_report.isChecked() and not self.chk_album.isChecked():
            QtWidgets.QMessageBox.warning(self, "경고", "수집할 대상을 최소 하나 이상 선택하세요.")
            return

        # 조회 기간 확정 (날짜칸이 단일 기준)
        start_qdate = self.start_date_edit.date()
        end_qdate = self.end_date_edit.date()
        if start_qdate > end_qdate:
            QtWidgets.QMessageBox.warning(self, "기간 오류", "시작 날짜가 종료 날짜보다 늦습니다.\n조회 기간을 다시 확인해 주세요.")
            return
        limit_date_str = start_qdate.toString("yyyy.MM.dd")
        end_date_str = end_qdate.toString("yyyy.MM.dd")

        self.status_label.setText('목록 불러오는 중...')
        self._set_shared_controls_enabled(False)
        self.stop_btn.setEnabled(True)
        self.download_btn.setEnabled(False)
        self.loading_banner.setVisible(True)
        self.update_progress(0)
        self.is_loading_memories = True
        self.load_finished_received = False
        
        self.memories = []
        self.table.setRowCount(0)

        child_name = None
        if hasattr(self, 'children_data') and self.children_data:
            idx = self.child_combo.currentIndex()
            if 0 <= idx < len(self.children_data):
                child_name = self.children_data[idx]['text'].split()[0]

        self.scrape_thread = ScrapeThread(
            driver=self.driver,
            scrape_reports=self.chk_report.isChecked(),
            scrape_albums=self.chk_album.isChecked(),
            limit_date_str=limit_date_str,
            child_name=child_name,
            end_date_str=end_date_str
        )
        self.scrape_thread.status_signal.connect(self.update_status)
        self.scrape_thread.profile_signal.connect(self.update_profile)
        self.scrape_thread.item_found_signal.connect(self.add_memory_to_table)
        self.scrape_thread.finished_signal.connect(self.on_load_finished)
        self.scrape_thread.finished.connect(self._ensure_load_finished)
        self.scrape_thread.start()

    def _set_all_checks(self, decide_checked):
        """표시 중인 모든 행의 체크 상태를 일괄 변경. decide_checked(row)가 True면 체크."""
        self.table.blockSignals(True)
        try:
            for i in range(self.table.rowCount()):
                if self.table.isRowHidden(i):
                    continue
                chk_item = self.table.item(i, 0)
                if chk_item:
                    chk_item.setCheckState(QtCore.Qt.Checked if decide_checked(i) else QtCore.Qt.Unchecked)
        finally:
            self.table.blockSignals(False)
        self.update_selection_label()

    def select_all(self):
        self._set_all_checks(lambda i: True)

    def deselect_all(self):
        self._set_all_checks(lambda i: False)

    def select_new_only(self):
        """증분 백업: 이 PC에서 아직 받은 적 없는 항목만 체크."""
        def is_new(i):
            title_item = self.table.item(i, 2)
            idx = title_item.data(QtCore.Qt.UserRole) if title_item else None
            if idx is not None and 0 <= idx < len(self.memories):
                return self.memories[idx].get('id') not in self.downloaded_ids
            return True
        self._set_all_checks(is_new)

    def _refresh_backup_marks(self):
        """다운로드 완료 후 테이블의 '백업' 컬럼 표시 갱신."""
        for i in range(self.table.rowCount()):
            title_item = self.table.item(i, 2)
            if not title_item:
                continue
            idx = title_item.data(QtCore.Qt.UserRole)
            if idx is None or not (0 <= idx < len(self.memories)):
                continue
            mark = "O" if self.memories[idx].get('id') in self.downloaded_ids else ""
            cell = self.table.item(i, 6)
            if cell:
                cell.setText(mark)
            else:
                self.table.setItem(i, 6, QtWidgets.QTableWidgetItem(mark))

    def toggle_pause(self):
        if not (self.is_downloading and self.download_thread):
            return
        if getattr(self.download_thread, '_paused', False):
            self.download_thread.resume()
            self.pause_btn.setText('일시정지')
            self.update_status("다운로드를 재개합니다...")
        else:
            self.download_thread.pause()
            self.pause_btn.setText('▶ 재개')
            self.update_status("현재 항목까지 마친 뒤 일시정지합니다...")

    def update_selection_label(self):
        total = 0
        selected = 0
        for i in range(self.table.rowCount()):
            if not self.table.isRowHidden(i):
                total += 1
                chk_item = self.table.item(i, 0)
                if chk_item and chk_item.checkState() == QtCore.Qt.Checked:
                    selected += 1
        self.selection_label.setText(f"선택됨: {selected} / 표시됨: {total}")

    def _on_table_item_changed(self, item):
        """0번(선택) 컬럼 체크 변경 시 선택 개수 라벨 갱신."""
        if item is not None and item.column() == 0 and not getattr(self, '_table_populating', False):
            self.update_selection_label()

    def stop_memories(self):
        self.stop_flag = True
        if self.scrape_thread and self.scrape_thread.isRunning():
            self.scrape_thread.stop()
            self.update_status("중지 요청됨... (현재 페이지 작업을 마친 뒤 종료됩니다)")
            self.stop_btn.setEnabled(False)
            QtWidgets.QMessageBox.information(self, "중지 수락", "목록 불러오기 작업이 중지 요청되었습니다. 진행 중인 페이지까지만 저장하고 멈춥니다.")
        elif self.is_downloading:
            if self.download_thread and hasattr(self.download_thread, "stop"):
                self.download_thread.stop()
            self.update_status("다운로드 중지 요청됨... 현재 파일을 정리한 뒤 멈춥니다.")
            self.stop_btn.setEnabled(False)

    @QtCore.pyqtSlot(dict)
    def add_memory_to_table(self, mem):
        self.table.setSortingEnabled(False) # 정렬 중에 행을 삽입하면 꼬일 수 있으므로 임시 비활성화
        self._table_populating = True

        self.memories.append(mem)
        i = self.table.rowCount()
        self.table.insertRow(i)

        # 체크박스: 셀 위젯 대신 체크형 아이템 — 헤더 정렬 시 체크 상태가 행과 함께 이동
        chk_item = CheckStateItem()
        chk_item.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
        chk_item.setCheckState(QtCore.Qt.Checked)
        chk_item.setTextAlignment(QtCore.Qt.AlignCenter)
        self.table.setItem(i, 0, chk_item)

        self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(mem['date']))
        
        title_item = QtWidgets.QTableWidgetItem(mem['title'])
        title_item.setData(QtCore.Qt.UserRole, len(self.memories) - 1)
        self.table.setItem(i, 2, title_item)
        
        self.table.setItem(i, 3, QtWidgets.QTableWidgetItem(mem['type']))
        self.table.setItem(i, 4, QtWidgets.QTableWidgetItem(mem.get('writer', '알 수 없음')))
        self.table.setItem(i, 5, QtWidgets.QTableWidgetItem(mem.get('has_photo', 'X')))
        backed_mark = "O" if mem.get('id') in self.downloaded_ids else ""
        self.table.setItem(i, 6, QtWidgets.QTableWidgetItem(backed_mark))

        self._table_populating = False
        self.table.setSortingEnabled(True) # 다시 활성화
        self.table.scrollToBottom()
        self.update_selection_label()

    def filter_table(self, text):
        text = text.lower()
        for i in range(self.table.rowCount()):
            match = False
            for j in range(1, self.table.columnCount()):
                item = self.table.item(i, j)
                if item and text in item.text().lower():
                    match = True
                    break
            self.table.setRowHidden(i, not match)
        self.update_selection_label()

    @QtCore.pyqtSlot(list)
    def on_load_finished(self, memories):
        self.load_finished_received = True
        self.is_loading_memories = False
        self._set_shared_controls_enabled(True)
        self.stop_btn.setEnabled(False)
        self.download_btn.setEnabled(True)
        self.loading_banner.setVisible(False)
        
        # 목록 조회가 끝났으므로 2,3단계 조작 가능하도록 오버레이 해제
        if hasattr(self, 'stage2_lock_overlay') and self.stage2_lock_overlay.isVisible():
             self.stage2_lock_overlay.hide()
             
        if len(self.memories) == 0:
            if self.scrape_thread.is_stopped:
                msg = "수집이 중지되었습니다. 가져온 항목이 없습니다."
                self.update_status(msg)
                self._show_top_message(QtWidgets.QMessageBox.Information, "중단됨", msg)
                return

            # 진단 정보로 '정상 조회했으나 0건'과 '조회 자체 실패'를 구분해 안내
            info = getattr(self.scrape_thread, 'result_info', None) or {}
            period_text = self._period_desc()

            if info.get('filtered_out', 0) > 0:
                # 목록은 정상적으로 열렸고 게시물도 있었지만, 전부 조회 기간 범위 밖
                msg = (
                    f"목록은 정상적으로 확인했습니다.\n\n"
                    f"다만 [{period_text}] 조회 기간 범위에 해당하는 게시물이 없어 결과가 0건입니다.\n"
                    f"조회 기간을 조정한 뒤 다시 시도해 보세요."
                )
                self.update_status(f"조회 완료: [{period_text}] 기간 내 게시물 0건")
                self._show_top_message(QtWidgets.QMessageBox.Information, "기간 내 게시물 없음", msg)
            elif info.get('list_loaded') and info.get('items_seen', 0) == 0:
                # 목록 화면은 열렸지만 게시물 자체가 하나도 없음 (신규 계정 등)
                msg = (
                    "목록 페이지는 정상적으로 열렸지만 게시물이 하나도 없습니다.\n\n"
                    "선택한 아이가 맞는지, 알림장/앨범 체크 항목이 맞는지 확인해 주세요."
                )
                self.update_status("조회 완료: 게시물 0건")
                self._show_top_message(QtWidgets.QMessageBox.Information, "게시물 없음", msg)
            else:
                # 목록 화면 진입 실패 또는 게시물 로딩 타임아웃 → 네트워크/일시 장애 안내
                msg = (
                    "목록 페이지를 여는 데 실패했거나 게시물 로딩이 시간 초과되었습니다.\n\n"
                    "사내망 등 네트워크 환경이 너무 느리거나 일시적인 장애일 수 있습니다.\n"
                    "잠시 후 다시 [목록 불러오기]를 시도해 주세요.\n"
                    "(캐시가 쌓여 두 세번째 시도 땐 더 빠릅니다!)"
                )
                self.update_status("수집 실패: 목록 페이지 로딩 시간 초과")
                self._show_top_message(QtWidgets.QMessageBox.Warning, "목록 가져오기 실패", msg)
            return

        if self.scrape_thread.is_stopped:
            msg = f"목록 로드 중지됨: {len(self.memories)}개 수집 완료"
            self.update_status(msg)
            self._show_top_message(QtWidgets.QMessageBox.Information, "불러오기 완료", msg)
        else:
            msg = f"목록 로드 완료: {len(self.memories)}개 수집 완료"
            self.update_status(msg)
            self.update_progress(100)
            self._show_top_message(QtWidgets.QMessageBox.Information, "불러오기 완료", msg)

    @QtCore.pyqtSlot()
    def _ensure_load_finished(self):
        if self.is_loading_memories and not self.load_finished_received:
            self.on_load_finished(self.memories)

    def start_download(self):
        write_app_log("Download button clicked")
        if not self.driver:
            QtWidgets.QMessageBox.warning(self, "오류", "브라우저 연결이 없습니다. 로그인부터 다시 진행해 주세요.")
            return
        if self.is_downloading or self.is_loading_memories:
            QtWidgets.QMessageBox.warning(self, "안내", "이미 작업이 진행 중입니다. 완료 또는 중지 후 다시 시도하세요.")
            return
        selected_indices = []
        for i in range(self.table.rowCount()):
            chk_item = self.table.item(i, 0)
            if not chk_item or chk_item.checkState() != QtCore.Qt.Checked:
                continue
            index_item = self.table.item(i, 2)
            if index_item:
                orig_idx = index_item.data(QtCore.Qt.UserRole)
                if orig_idx is not None:
                    selected_indices.append(orig_idx)
        
        if not selected_indices:
            QtWidgets.QMessageBox.warning(self, "경고", "다운로드할 항목을 선택해주세요.")
            return

        target_dir = self.dir_input.text()
        if not target_dir:
            QtWidgets.QMessageBox.warning(self, "경고", "저장 경로를 지정해주세요.")
            return

        self._launch_download_thread(selected_indices)

    def _launch_download_thread(self, selected_indices):
        """선택된 인덱스 목록으로 다운로드 스레드를 기동. '실패만 재시도'에서도 재사용."""
        target_dir = self.dir_input.text()
        self.stop_flag = False
        is_pdf = self.pdf_radio.isChecked()
        is_single_folder = self.folder_single_radio.isChecked()
        include_video = not self.chk_exclude_video.isChecked()

        # 아이 이름: 콤보박스 텍스트에서 첫 단어(이름)만 콕직으로 추출 및 특수문자 제거
        profile_name = "알수없음"
        try:
            combo_text = self.child_combo.currentText().strip()
            if combo_text:
                import re
                first_word = combo_text.split()[0]  # "최승아 23.7.14." → "최승아"
                profile_name = re.sub(r'[\\/*?:"<>|]', "", first_word)
        except:
            pass

        self.download_btn.setEnabled(False)
        # 다운로드 중 목록 재수집/아이 전환이 같은 드라이버를 건드리지 못하도록 잠금
        self._set_shared_controls_enabled(False)
        self.stop_btn.setEnabled(True)
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText('일시정지')
        self.is_downloading = True
        self.update_progress(0)
        self.update_status(f"다운로드 준비 중... 선택 {len(selected_indices)}개")

        is_overwrite_allow = self.overwrite_allow_radio.isChecked()

        write_app_log(
            f"Starting download thread. selected={len(selected_indices)} "
            f"pdf={is_pdf} single_folder={is_single_folder}"
        )
        self.download_thread = DownloadThread(
            self.driver,
            list(self.memories),
            selected_indices,
            target_dir,
            is_pdf,
            is_single_folder,
            profile_name,
            is_overwrite_allow,
            include_video,
        )
        self.download_thread.status_signal.connect(self.update_status)
        self.download_thread.progress_signal.connect(self.update_progress)
        self.download_thread.finished_signal.connect(self.on_download_finished)
        # finished_signal이 유실되는 비정상 종료에도 UI가 '준비 중'에 갇히지 않도록 이중 안전장치
        self.download_thread.finished.connect(self._ensure_download_finished)
        self.download_thread.start()

    @QtCore.pyqtSlot(str, int, int, bool)
    def on_download_finished(self, target_dir, success_cnt, fail_cnt, is_stopped):
        self.is_downloading = False
        self.download_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText('일시정지')
        self._set_shared_controls_enabled(True)

        finished_thread = self.download_thread

        # 증분 백업 기록: 성공 항목 id를 저장하고 테이블 '백업' 표시 갱신
        succeeded = [i for i in (getattr(finished_thread, 'succeeded_ids', None) or []) if i]
        if succeeded:
            self.downloaded_ids.update(succeeded)
            self._save_manifest(self.downloaded_ids)
            self._refresh_backup_marks()

        elapsed_sec = getattr(finished_thread, 'elapsed_sec', 0)
        self._show_download_complete(target_dir, success_cnt, fail_cnt, is_stopped, elapsed_sec)

        # 실패 항목만 재시도 제안 (사용자가 중지한 경우 제외)
        failed = list(getattr(finished_thread, 'failed_indices', None) or [])
        if failed and not is_stopped:
            reply = self._show_top_question(
                "실패 항목 재시도",
                f"다운로드에 실패한 {len(failed)}건이 있습니다.\n실패한 항목만 다시 시도할까요?"
            )
            if reply == QtWidgets.QMessageBox.Yes:
                self._launch_download_thread(failed)

    @QtCore.pyqtSlot()
    def _ensure_download_finished(self):
        if self.is_downloading:
            write_app_log("Download thread ended without finished_signal; recovering UI state")
            self.is_downloading = False
            self.download_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.pause_btn.setText('일시정지')
            self._set_shared_controls_enabled(True)
            self.update_status("다운로드가 비정상 종료되었습니다. 로그를 확인해 주세요.")

    def _show_download_complete(self, target_dir, success_cnt, fail_cnt, is_stopped, elapsed_sec=0):
        self.tray_icon.showMessage("키즈노트 다운로더", f"다운로드 완료 (성공: {success_cnt}, 실패/건너뜀: {fail_cnt})", QtWidgets.QSystemTrayIcon.Information, 5000)

        status_msg = f"총 {success_cnt+fail_cnt}개 중 성공: {success_cnt}건, 실패/건너뜀: {fail_cnt}건\n"
        if elapsed_sec:
            minutes, seconds = divmod(int(elapsed_sec), 60)
            status_msg += f"소요 시간: {minutes}분 {seconds}초\n" if minutes else f"소요 시간: {seconds}초\n"
        status_msg += f"저장 위치: {target_dir}\n"
        if is_stopped:
            status_msg += "\n(다운로드가 사용자에 의해 중도 중지되었습니다.)\n"

        network_blocked = bool(getattr(self.download_thread, 'network_blocked', False))
        if success_cnt == 0 and fail_cnt > 0 and not is_stopped:
            status_msg += (
                "\n⚠ 모든 항목이 실패했습니다.\n"
                "네트워크 보안 정책이 미디어 접근을 차단했을 가능성이 있습니다.\n"
                "PDF 저장 모드는 정상 동작할 수 있으니 함께 시도해 보세요.\n"
            )
        elif network_blocked and success_cnt > 0:
            status_msg += "\n(직접 접근 차단 환경이라 브라우저 경유 방식으로 받았습니다.)\n"

        reply = self._show_top_question("다운로드 완료", status_msg + "\n지금 폴더를 열어보시겠습니까?")
        
        if reply == QtWidgets.QMessageBox.Yes:
            import os
            if os.path.exists(target_dir):
                os.startfile(target_dir)

    @QtCore.pyqtSlot(dict)
    def update_profile(self, profile_info):
        text = profile_info.get('text', '알 수 없음')
        img_b64 = profile_info.get('image', None)
        
        if img_b64:
            import base64
            from PyQt5 import QtGui, QtCore
            
            raw_data = base64.b64decode(img_b64.encode('utf-8'))
            
            # PyQt5에 JPEG 플러그인이 없으므로 Pillow로 PNG 변환 후 로드
            try:
                from PIL import Image
                import io
                pil_img = Image.open(io.BytesIO(raw_data))
                buf = io.BytesIO()
                pil_img.save(buf, format='PNG')
                png_data = buf.getvalue()
            except Exception as pil_e:
                return
            
            pixmap = QtGui.QPixmap()
            success = pixmap.loadFromData(png_data)
            
            if not success or pixmap.isNull():
                return
                
            size = self.profile_img_label.size()
            dpr = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
            physical_size = QtCore.QSize(int(size.width() * dpr), int(size.height() * dpr))
            rounded = QtGui.QPixmap(physical_size)
            rounded.setDevicePixelRatio(dpr)
            rounded.fill(QtCore.Qt.transparent)
            
            painter = QtGui.QPainter(rounded)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            scaled_profile = pixmap.scaled(physical_size, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation)
            scaled_profile.setDevicePixelRatio(dpr)
            brush = QtGui.QBrush(scaled_profile)
            painter.setBrush(brush)
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawEllipse(0, 0, size.width(), size.height())
            painter.end()
            
            self.profile_img_label.setPixmap(rounded)
            self.profile_img_label.setText("")

    def update_status(self, msg):
        self.run_on_ui_thread(lambda: self.status_label.setText(msg))

    def enable_widget(self, widget, enabled):
        self.run_on_ui_thread(lambda: widget.setEnabled(enabled))

    def cleanup_browser_processes(self):
        def quit_driver():
            if hasattr(self, 'driver') and self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                finally:
                    self.driver = None

        import threading
        t = threading.Thread(target=quit_driver, daemon=True)
        t.start()
        t.join(timeout=5.0)

        try:
            import subprocess
            subprocess.run(["taskkill", "/f", "/t", "/im", "msedgedriver.exe"], shell=False, timeout=5, creationflags=0x08000000)
            # Selenium Manager 폴백으로 실행된 경우 selenium-manager.exe가 MEI 임시폴더 안에서
            # 돌고 있을 수 있음 → 살아있으면 PyInstaller 임시폴더 삭제 실패 경고의 원인이 됨
            subprocess.run(["taskkill", "/f", "/t", "/im", "selenium-manager.exe"], shell=False, timeout=5, creationflags=0x08000000)
        except Exception:
            pass

        # 프로세스 강제 종료 후 파일 잠금이 풀릴 시간을 잠깐 확보
        # (PyInstaller onefile의 임시폴더(MEIxxxx) 삭제 실패 경고 완화)
        try:
            import time as _time
            _time.sleep(0.3)
        except Exception:
            pass

    def closeEvent(self, event):
        self.hide() # 즉시 창 숨김 처리 (종료 시 딜레이 및 잔상 제거)

        # 실행 중인 QThread가 있으면 중지 요청 후 짧게 대기.
        # 스레드가 살아있는 채로 앱이 내려가면 종료 시점 크래시/경고의 원인이 됨.
        for worker in (self.scrape_thread, self.download_thread):
            try:
                if worker and worker.isRunning():
                    worker.stop()
            except Exception:
                pass
        for worker in (self.scrape_thread, self.download_thread):
            try:
                if worker and worker.isRunning():
                    worker.wait(2000)
            except Exception:
                pass

        # 드라이버를 먼저 종료하면 driver 명령에 블록된 스레드도 예외로 깨어나 종료됨
        self.cleanup_browser_processes()

        for worker in (self.scrape_thread, self.download_thread):
            try:
                if worker and worker.isRunning():
                    worker.wait(2000)
            except Exception:
                pass
        event.accept()

if __name__ == '__main__':
    install_crash_logging()
    # 4K 모니터 등 고해상도(High DPI) 디스플레이에서 GUI 텍스트와 UI가 극단적으로 작아지는 현상 방지
    if hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    if hasattr(QtCore.Qt, 'AA_UseHighDpiPixmaps'):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
        
    app = QtWidgets.QApplication(sys.argv)
    ex = KidsnoteApp()
    app.aboutToQuit.connect(ex.cleanup_browser_processes)
    ex.show()
    sys.exit(app.exec_())
