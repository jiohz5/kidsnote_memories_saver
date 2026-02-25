import sys
import threading
import os
import codecs
from PyQt5 import QtWidgets, QtCore, QtGui
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
import kidsnote_save_manager as manager

# 터미널(콘솔) 출력 환경에서 한글 깨짐을 방지하기 위한 강제 UTF-8 세팅
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

class ScrapeThread(QtCore.QThread):
    item_found_signal = QtCore.pyqtSignal(dict)
    status_signal = QtCore.pyqtSignal(str)
    profile_signal = QtCore.pyqtSignal(dict)
    finished_signal = QtCore.pyqtSignal(list)

    def __init__(self, driver, scrape_reports=True, scrape_albums=True, limit_date_str=None):
        super().__init__()
        self.driver = driver
        self.scrape_reports = scrape_reports
        self.scrape_albums = scrape_albums
        self.limit_date_str = limit_date_str
        self.is_stopped = False

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
                limit_date_str=self.limit_date_str
            )
            self.finished_signal.emit(memories)
        except Exception as e:
            self.status_signal.emit(f"목록 로드 중 오류: {e}")
            self.finished_signal.emit([])

    def check_stopped(self):
        return self.is_stopped
                                                            
    def stop(self):
        self.is_stopped = True


class KidsnoteApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.driver = None
        self.memories = []
        self.scrape_thread = None                          
        self.stop_flag = False
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle('Kidsnote Memories Saver v260226')
        
        # --- 키즈노트 테마 글로벌 QSS 적용 ---
        self.setStyleSheet("""
            QWidget {
                background-color: #F8F9FA;
                font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
                color: #2D3748;
            }
            QPushButton {
                background-color: #03A9F4;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 8px 15px;
            }
            QPushButton:hover {
                background-color: #0288D1;
            }
            QPushButton:disabled {
                background-color: #CBD5E0;
                color: #A0AEC0;
            }
            QLineEdit, QComboBox {
                border: 2px solid #E2E8F0;
                border-radius: 4px;
                padding: 5px;
                background-color: white;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 2px solid #FFC300;
            }
            QGroupBox {
                border: 2px solid #E2E8F0;
                border-radius: 6px;
                margin-top: 15px;
                font-weight: bold;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 5px;
                color: #FF5722;
            }
            QTableWidget {
                background-color: white;
                border: 1px solid #E2E8F0;
                border-radius: 4px;
                gridline-color: #EDF2F7;
            }
            QHeaderView::section {
                background-color: #F1F5F9;
                font-weight: bold;
                color: #4A5568;
                border: none;
                border-bottom: 2px solid #E2E8F0;
                padding: 4px;
            }
            QCheckBox {
                spacing: 8px;
                font-size: 13px;
                font-weight: bold;
                color: #4A5568;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QRadioButton {
                font-weight: bold;
                color: #4A5568;
            }
        """)
        
        # 이전 기본 사이즈에서 세로 길이(Height)만 조금 더 길고 시원하게 늘림
        self.setGeometry(300, 100, 1000, 1100)
        self.setMinimumSize(800, 800)
        
        # 첫 번째 가이드 팝업 실행
        QtCore.QTimer.singleShot(700, self.show_initial_popup)
        
        # IDE 등에서 기본 파이썬 실행시 표시될 귀여운 아이콘(폴더나 집 모양 스탠다드 아이콘 활용)
        self.setWindowIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DirHomeIcon))

        main_layout = QtWidgets.QVBoxLayout()

        # Config setup for Local ID/PW save
        import configparser, base64
        self.config = configparser.ConfigParser()
        self.config_path = os.path.join(os.path.expanduser("~"), "Kidsnote_Config.ini")
        self.config.read(self.config_path)
        
        saved_id = self.config.get('Login', 'id', fallback='')
        saved_pw_b64 = self.config.get('Login', 'pw', fallback='')
        saved_remember = self.config.getboolean('Login', 'remember', fallback=False)
        try:
            saved_pw = base64.b64decode(saved_pw_b64.encode('utf-8')).decode('utf-8') if saved_pw_b64 else ''
        except:
            saved_pw = ''

        # Login Info Group
        login_group = QtWidgets.QGroupBox("로그인 정보")
        login_layout = QtWidgets.QGridLayout()
        
        login_layout.addWidget(QtWidgets.QLabel("아이디:"), 0, 0)
        self.id_input = QtWidgets.QLineEdit(saved_id)
        login_layout.addWidget(self.id_input, 0, 1)
        
        login_layout.addWidget(QtWidgets.QLabel("비밀번호:"), 1, 0)
        self.pw_input = QtWidgets.QLineEdit(saved_pw)
        self.pw_input.setEchoMode(QtWidgets.QLineEdit.Password)
        login_layout.addWidget(self.pw_input, 1, 1)
        
        self.chk_remember = QtWidgets.QCheckBox("로그인 정보 내 PC에 저장하기 (암호화되어 안전하게 보관됩니다)")
        self.chk_remember.setChecked(saved_remember)
        self.chk_remember.setStyleSheet("color: #03A9F4; font-weight: bold;")
        login_layout.addWidget(self.chk_remember, 2, 0, 1, 2)
        
        security_notice = QtWidgets.QLabel("※ 입력하신 정보는 이 PC에서 자동 로그인에만 사용되며, 절대로 인터넷을 통해 외부 서버로 전송되지 않습니다.")
        security_notice.setStyleSheet("color: gray; font-size: 11px; margin-top: 5px;")
        security_notice.setWordWrap(True)
        login_layout.addWidget(security_notice, 3, 0, 1, 2)
        
        login_group.setLayout(login_layout)
        main_layout.addWidget(login_group)

        # Tray Icon for notifications
        self.tray_icon = QtWidgets.QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DirHomeIcon))
        self.tray_icon.show()

        # Status Label
        self.status_label = QtWidgets.QLabel('준비됨')
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        self.status_label.setStyleSheet("font-weight: bold; color: white; background-color: #03A9F4; font-size: 18px; padding: 10px; border-radius: 5px;")
        main_layout.addWidget(self.status_label)
        
        # Progress Bar
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #E2E8F0;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
                font-size: 14px;
                color: #2D3748;
                background-color: white;
            }
            QProgressBar::chunk {
                background-color: #FFC300;
                border-radius: 3px;
            }
        """)
        main_layout.addWidget(self.progress_bar)

        # Profile Layout
        self.profile_widget = QtWidgets.QWidget()
        self.profile_layout = QtWidgets.QHBoxLayout(self.profile_widget)
        self.profile_layout.setContentsMargins(15, 10, 15, 10)
        
        # 대상 자녀 콤보박스를 프로필 위젯 최좌측에 배치
        self.child_combo = QtWidgets.QComboBox()
        self.child_combo.addItem("1단계를 진행하세요")
        self.child_combo.setEnabled(False)
        self.child_combo.setMinimumWidth(150)
        self.child_combo.setMinimumHeight(40)
        self.child_combo.setStyleSheet("font-weight: bold; font-size: 14px; color: #2D3748; background-color: #F7FAFC; border: 2px solid #E2E8F0; border-radius: 5px;")
        self.child_combo.currentIndexChanged.connect(self.on_child_combo_changed)
        
        self.profile_img_label = QtWidgets.QLabel()
        self.profile_img_label.setFixedSize(60, 60)
        self.profile_img_label.setStyleSheet("border-radius: 30px; background-color: #E2E8F0;")
        self.profile_img_label.setAlignment(QtCore.Qt.AlignCenter)
        self.profile_img_label.setText("사진")
        
        self.profile_label = QtWidgets.QLabel('아이 정보: (아직 불러오지 않음)')
        self.profile_label.setStyleSheet("font-weight: bold; color: #03A9F4; font-size: 17px;")
        
        self.profile_layout.addWidget(self.child_combo)
        self.profile_layout.addSpacing(15)
        self.profile_layout.addWidget(self.profile_img_label)
        self.profile_layout.addWidget(self.profile_label)
        self.profile_layout.addStretch()
        
        self.profile_widget.setStyleSheet("background-color: white; border-radius: 8px; border: 2px solid #E2E8F0;")
        main_layout.addWidget(self.profile_widget)

        # Collect Options Group
        collect_group = QtWidgets.QGroupBox("1단계: 데이터 연동 및 수집 범위")
        btn_layout = QtWidgets.QHBoxLayout()
        self.login_btn = QtWidgets.QPushButton('1. 키즈노트 로그인 열기')
        self.login_btn.clicked.connect(self.open_browser)
        self.login_btn.setFixedHeight(40)
        self.login_btn.setStyleSheet("""
            QPushButton { background-color: #FFC300; color: #2D3748; font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #E6B000; }
            QPushButton:disabled { background-color: #FFDE59; color: #8A94A6; }
        """)
        btn_layout.addWidget(self.login_btn)

        # 2번 버튼과 체크박스를 가깝게 묶기 위한 그룹 레이아웃
        middle_layout = QtWidgets.QHBoxLayout()
        middle_layout.setSpacing(10) # 간격 좁힘
        
        chk_layout = QtWidgets.QVBoxLayout()
        self.chk_report = QtWidgets.QCheckBox("알림장")
        self.chk_report.setChecked(True)
        self.chk_album = QtWidgets.QCheckBox("앨범")
        self.chk_album.setChecked(True)
        chk_layout.addWidget(self.chk_report)
        chk_layout.addWidget(self.chk_album)
        
        # Period Filter Combo
        self.period_combo = QtWidgets.QComboBox()
        self.period_combo.addItems(["전체 수집 (시간이 오래 걸릴 수 있습니다)", "최근 3개월", "최근 6개월", "최근 1년", "최근 2년"])
        self.period_combo.setCurrentIndex(0) # 기본 전체 수집
        period_layout = QtWidgets.QVBoxLayout()
        period_layout.addWidget(QtWidgets.QLabel("조회 기간:"))
        period_layout.addWidget(self.period_combo)
        
        middle_layout.addLayout(chk_layout)
        middle_layout.addLayout(period_layout)

        self.load_btn = QtWidgets.QPushButton('2. 추억 목록 불러오기')
        self.load_btn.clicked.connect(self.load_memories)
        self.load_btn.setEnabled(False)
        self.load_btn.setFixedHeight(40)
        self.load_btn.setStyleSheet("""
            QPushButton { background-color: #FFC300; color: #2D3748; font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #E6B000; }
            QPushButton:disabled { background-color: #FFDE59; color: #8A94A6; }
        """)
        middle_layout.addWidget(self.load_btn)
        
        btn_layout.addLayout(middle_layout)
        
        self.stop_btn = QtWidgets.QPushButton('작업 중지')
        self.stop_btn.clicked.connect(self.stop_memories)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setFixedHeight(40)
        self.stop_btn.setStyleSheet("""
            QPushButton { background-color: #E53E3E; color: white; }
            QPushButton:hover { background-color: #C53030; }
            QPushButton:disabled { background-color: #FC8181; }
        """)
        btn_layout.addWidget(self.stop_btn)
        
        collect_group.setLayout(btn_layout)
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
        target_layout.addWidget(self.select_all_btn)
        target_layout.addWidget(self.deselect_all_btn)
        
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("검색어 입력 (제목, 작성자 등)")
        self.search_input.textChanged.connect(self.filter_table)
        target_layout.addWidget(self.search_input)
        
        self.selection_label = QtWidgets.QLabel("선택됨: 0 / 전체: 0")
        self.selection_label.setStyleSheet("font-weight: bold; color: #E65100; font-size: 14px; margin-left: 10px;")
        target_layout.addWidget(self.selection_label)
        
        table_layout.addLayout(target_layout)

        # Table View
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(6)
        self.table.setMinimumHeight(450) # 화면에 최소 10칸 이상 더 보이도록 높이 대폭 강제 할당
        self.table.setHorizontalHeaderLabels(['선택', '날짜', '제목', '종류', '작성자', '사진 유무'])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(1, 230) # 날짜 컬럼 너비 더 넓게 확장
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(4, 120)
        self.table.setColumnWidth(5, 80)
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

        # Folder Options Group
        folder_group_box = QtWidgets.QGroupBox("저장 방식")
        self.folder_btn_group = QtWidgets.QButtonGroup()
        self.radio_layout_folder = QtWidgets.QHBoxLayout()
        self.folder_individual_radio = QtWidgets.QRadioButton("개별 디렉토리에 저장 (날짜별)")
        self.folder_individual_radio.setChecked(True)
        self.folder_single_radio = QtWidgets.QRadioButton("한 곳에 모두 저장")
        self.folder_btn_group.addButton(self.folder_individual_radio)
        self.folder_btn_group.addButton(self.folder_single_radio)
        self.radio_layout_folder.addWidget(self.folder_individual_radio)
        self.radio_layout_folder.addWidget(self.folder_single_radio)
        folder_group_box.setLayout(self.radio_layout_folder)
        options_layout.addWidget(folder_group_box)

        # File Type Option Group
        filetype_group_box = QtWidgets.QGroupBox("다운로드 항목 종류")
        self.filetype_btn_group = QtWidgets.QButtonGroup()
        radio_layout = QtWidgets.QHBoxLayout()
        self.pdf_radio = QtWidgets.QRadioButton("전체 페이지 PDF 저장")
        self.pdf_radio.setChecked(True)
        self.photo_radio = QtWidgets.QRadioButton("사진+동영상만 받기")
        self.filetype_btn_group.addButton(self.pdf_radio)
        self.filetype_btn_group.addButton(self.photo_radio)
        radio_layout.addWidget(self.pdf_radio)
        radio_layout.addWidget(self.photo_radio)
        filetype_group_box.setLayout(radio_layout)
        options_layout.addWidget(filetype_group_box)
        
        options_group.setLayout(options_layout)
        main_layout.addWidget(options_group)

        # Download Button
        self.download_btn = QtWidgets.QPushButton('3. 선택한 항목 다운로드 시작')
        self.download_btn.clicked.connect(self.start_download)
        self.download_btn.setEnabled(False)
        self.download_btn.setFixedHeight(40)
        self.download_btn.setStyleSheet("""
            QPushButton { background-color: #FFC300; color: #2D3748; font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #E6B000; }
            QPushButton:disabled { background-color: #FFDE59; color: #8A94A6; }
        """)
        main_layout.addWidget(self.download_btn)

        self.setLayout(main_layout)

        # --- 로딩 오버레이 ---
        self._overlay = QtWidgets.QWidget(self)
        self._overlay.setStyleSheet("background-color: rgba(0, 0, 0, 160);")
        self._overlay_label = QtWidgets.QLabel("잠시만 기다려 주세요...", self._overlay)
        self._overlay_label.setAlignment(QtCore.Qt.AlignCenter)
        self._overlay_label.setStyleSheet("""
            color: white;
            font-size: 18px;
            font-weight: bold;
            background: transparent;
            padding: 20px;
        """)
        self._overlay_label.setWordWrap(True)
        overlay_layout = QtWidgets.QVBoxLayout(self._overlay)
        overlay_layout.addStretch()
        overlay_layout.addWidget(self._overlay_label)
        overlay_layout.addStretch()
        self._overlay.hide()

    # --- 로딩 오버레이 제어 ---
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._overlay.setGeometry(self.rect())

    def _show_overlay(self, text='잠시만 기다려 주세요...'):
        QtCore.QMetaObject.invokeMethod(self, "_do_show_overlay", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, text))

    def _hide_overlay(self):
        QtCore.QMetaObject.invokeMethod(self, "_do_hide_overlay", QtCore.Qt.QueuedConnection)

    def _update_overlay_text(self, text):
        QtCore.QMetaObject.invokeMethod(self, "_do_update_overlay", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, text))

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
        import configparser, base64
        if not self.config.has_section('Login'):
            self.config.add_section('Login')
        if self.chk_remember.isChecked():
            pw_b64 = base64.b64encode(password.encode('utf-8')).decode('utf-8')
            self.config.set('Login', 'id', username)
            self.config.set('Login', 'pw', pw_b64)
            self.config.set('Login', 'remember', 'True')
        else:
            self.config.set('Login', 'id', '')
            self.config.set('Login', 'pw', '')
            self.config.set('Login', 'remember', 'False')
            
        with open(self.config_path, 'w') as f:
            self.config.write(f)

        self.status_label.setText('브라우저 여는 중 및 로그인 입력 중...')
        self.login_btn.setEnabled(False)
        self._show_overlay('🔐 키즈노트 브라우저를 여는 중...')
        threading.Thread(target=self._init_driver, args=(username, password), daemon=True).start()

    def _init_driver(self, username, password):
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.keys import Keys

            options = webdriver.ChromeOptions()
            options.add_argument('--window-size=1200,1000')
            options.add_experimental_option("detach", True) 
            self.driver = webdriver.Chrome(options=options)
            self.driver.get("https://www.kidsnote.com/login")
            
            # Wait for login fields and fill them
            wait = WebDriverWait(self.driver, 15)
            user_field = wait.until(EC.presence_of_element_located((By.NAME, "username")))
            pass_field = self.driver.find_element(By.NAME, "password")
            
            user_field.send_keys(username)
            pass_field.send_keys(password)
            pass_field.send_keys(Keys.RETURN) # Auto-submit
            
            self.update_status("안전하게 로그인 되었습니다! 아이 목록을 조회하는 중...")
            self._update_overlay_text('✅ 로그인 성공!\n아이 정보를 가져오는 중...')
            
            # 로그인 직후 메뉴 페이지로 완벽하게 넘어갈 때까지 여유있게 대기 후 명시적 주소 이동
            import time
            time.sleep(3)
            if "kidsnote.com/service" not in self.driver.current_url:
                self.driver.get("https://www.kidsnote.com/service")
                time.sleep(2)
            
            # Wait until profile section loads (Check for size 65 active avatar)
            try:
                WebDriverWait(self.driver, 15).until(EC.presence_of_element_located((By.XPATH, "//*[@size='65' and @role='img']")))
                time.sleep(1) # 부가 컴포넌트 렌더링 대기
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
                    
                    # 해당 자녀 클릭하여 활성화
                    self._update_overlay_text(f'📷 {name}의 프로필 사진 가져오는 중...\n({idx+1}/{len(name_array)})')
                    if idx < len(click_elems):
                        try:
                            self.driver.execute_script("arguments[0].click();", click_elems[idx])
                            _time.sleep(1.5)  # CSS 주입 대기
                        except Exception as click_e:
                            pass
                    
                    # 활성화된 size=65 span의 computedStyle에서 URL 추출
                    url_script = (
                        'var s = document.querySelector("span[role=\'img\'][size=\'65\']");'
                        'if(s) { return window.getComputedStyle(s).backgroundImage; }'
                        'return "none";'
                    )
                    bg_value = self.driver.execute_script(url_script)
                    
                    url = ""
                    if bg_value and bg_value != "none":
                        # url("https://...") 에서 URL만 추출
                        if "url(" in bg_value:
                            start = bg_value.index("url(") + 4
                            end = bg_value.index(")", start)
                            url = bg_value[start:end].strip('"').strip("'")
                    
                    child_array.append([name, age, url])
                
                
                
                seen_names = set()
                for idx, item in enumerate(child_array):
                    name, age, url = item
                    if not name or not age: 
                        continue
                        
                    text_val = f"{name} {age}"
                    
                    if text_val not in seen_names:
                        seen_names.add(text_val)
                        img_b64 = None
                        if url:
                            try:
                                import urllib.request, base64
                                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                                with urllib.request.urlopen(req, timeout=5) as response:
                                    img_data = response.read()
                                    content_type = response.headers.get('Content-Type', 'unknown')
                                    
                                    # PyQt5에 JPEG 플러그인이 없으므로 모든 이미지를 Pillow로 PNG 변환
                                    try:
                                        from PIL import Image
                                        import io
                                        pil_img = Image.open(io.BytesIO(img_data))
                                        buf = io.BytesIO()
                                        pil_img.save(buf, format='PNG')
                                        img_data = buf.getvalue()
                                    except ImportError:
                                        pass
                                    except Exception as conv_e:
                                        pass
                                    
                                    img_b64 = base64.b64encode(img_data).decode('utf-8')
                            except Exception as img_e:
                                pass
                        else:
                            pass
                        
                        click_elem = click_elems[idx] if idx < len(click_elems) else None
                        self.children_data.append({
                            "text": text_val, 
                            "elem": click_elem,
                            "img_b64": img_b64
                        })
            except Exception as e:
                pass
                
            # Populate Combo Box
            QtCore.QMetaObject.invokeMethod(self, "populate_children_combo", QtCore.Qt.QueuedConnection)
            
            self.enable_widget(self.load_btn, True)
            self._hide_overlay()
            # 로그인 성공 후 두 번째 팝업 띄우기 (GUI 스레드 안전 호출)
            QtCore.QMetaObject.invokeMethod(self, "show_post_login_popup", QtCore.Qt.QueuedConnection)
        except Exception as e:
            self.update_status(f"브라우저 실행 또는 입력 오류: {e}")
            self.enable_widget(self.login_btn, True)
            self._hide_overlay()

    @QtCore.pyqtSlot()
    def populate_children_combo(self):
        if hasattr(self, 'children_data') and self.children_data:
            self.child_combo.blockSignals(True)
            self.child_combo.clear()
            for child in self.children_data:
                self.child_combo.addItem(child['text'])
            self.child_combo.setEnabled(True)
            self.child_combo.blockSignals(False)
            self.update_status(f"로그인 완료! 총 {len(self.children_data)}개의 자녀 정보를 찾았습니다.")
            # 첫 번째 자녀를 기본으로 화면(우측 상단 프로필)에 즉각 반영
            if len(self.children_data) > 0:
                first_child = self.children_data[self.child_combo.currentIndex()]
                QtCore.QMetaObject.invokeMethod(self, "update_profile", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(dict, {"text": first_child["text"], "image": first_child.get("img_b64", None)}))
        else:
            self.update_status("로그인 완료! 아이 목록을 찾을 수 없으므로 브라우저에서 직접 선택해주세요.")

    def on_child_combo_changed(self, index):
        if hasattr(self, 'children_data') and 0 <= index < len(self.children_data):
            try:
                child_info = self.children_data[index]
                elem = child_info['elem']
                # 자바스크립트로 클릭 트리거
                self.driver.execute_script("arguments[0].click();", elem)
                import time
                time.sleep(1) # 화면 갱신 대기
                self.update_status(f"[{self.child_combo.currentText()}] 계정으로 전환되었습니다. 이제 수집을 시작하세요.")
                # 즉각적으로 프로필 카드 업데이트
                self.update_profile({"text": child_info["text"], "image": child_info.get("img_b64", None)})
            except Exception as e:
                pass

    @QtCore.pyqtSlot()
    def show_initial_popup(self):
        QtWidgets.QMessageBox.information(
            self, 
            "이용 안내", 
            "아이디와 비밀번호를 입력하신 후,\n\n'1. 키즈노트 로그인 열기' 버튼을 눌러주세요!\n(이미 입력되어 있다면 바로 누르시면 됩니다.)"
        )

    @QtCore.pyqtSlot()
    def show_post_login_popup(self):
        QtWidgets.QMessageBox.information(
            self, 
            "다음 단계", 
            "정상적으로 로그인 되었습니다!\n\n별도의 추가 조작 없이 바로 '2. 추억 목록 불러오기' 버튼을 클릭하여 수집을 시작하시면 됩니다.\n(추후 자녀가 여러 명일 경우 프로필을 직접 선택할 수 있는 기능을 추가할 예정입니다.)"
        )

    def update_progress(self, value):
        QtCore.QMetaObject.invokeMethod(self.progress_bar, "setValue", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(int, value))

    def load_memories(self):
        if not self.driver: return
        if not self.chk_report.isChecked() and not self.chk_album.isChecked():
            QtWidgets.QMessageBox.warning(self, "경고", "수집할 대상을 최소 하나 이상 선택하세요.")
            return

        self.status_label.setText('목록 불러오는 중...')
        self.load_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.download_btn.setEnabled(False)
        self.update_progress(0)
        
        self.memories = []
        self.table.setRowCount(0)

        import datetime
        today = datetime.date.today()
        limit_date_str = None
        period_text = self.period_combo.currentText()
        if "3개월" in period_text:
            limit_date = today - datetime.timedelta(days=90)
            limit_date_str = limit_date.strftime("%Y.%m.%d")
        elif "6개월" in period_text:
            limit_date = today - datetime.timedelta(days=180)
            limit_date_str = limit_date.strftime("%Y.%m.%d")
        elif "1년" in period_text:
            limit_date = today - datetime.timedelta(days=365)
            limit_date_str = limit_date.strftime("%Y.%m.%d")
        elif "2년" in period_text:
            limit_date = today - datetime.timedelta(days=730)
            limit_date_str = limit_date.strftime("%Y.%m.%d")

        self.scrape_thread = ScrapeThread(
            driver=self.driver, 
            scrape_reports=self.chk_report.isChecked(), 
            scrape_albums=self.chk_album.isChecked(),
            limit_date_str=limit_date_str
        )
        self.scrape_thread.status_signal.connect(self.update_status)
        self.scrape_thread.profile_signal.connect(self.update_profile)
        self.scrape_thread.item_found_signal.connect(self.add_memory_to_table)
        self.scrape_thread.finished_signal.connect(self.on_load_finished)
        self.scrape_thread.start()

    def select_all(self):
        for i in range(self.table.rowCount()):
            if not self.table.isRowHidden(i):
                chk_widget = self.table.cellWidget(i, 0)
                checkbox = chk_widget.findChild(QtWidgets.QCheckBox)
                if checkbox:
                    checkbox.blockSignals(True)
                    checkbox.setChecked(True)
                    checkbox.blockSignals(False)
        self.update_selection_label()

    def deselect_all(self):
        for i in range(self.table.rowCount()):
            if not self.table.isRowHidden(i):
                chk_widget = self.table.cellWidget(i, 0)
                checkbox = chk_widget.findChild(QtWidgets.QCheckBox)
                if checkbox:
                    checkbox.blockSignals(True)
                    checkbox.setChecked(False)
                    checkbox.blockSignals(False)
        self.update_selection_label()

    def update_selection_label(self):
        total = 0
        selected = 0
        for i in range(self.table.rowCount()):
            if not self.table.isRowHidden(i):
                total += 1
                chk_widget = self.table.cellWidget(i, 0)
                checkbox = chk_widget.findChild(QtWidgets.QCheckBox)
                if checkbox and checkbox.isChecked():
                    selected += 1
        QtCore.QMetaObject.invokeMethod(self.selection_label, "setText", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, f"선택됨: {selected} / 표시됨: {total}"))

    def stop_memories(self):
        self.stop_flag = True
        if self.scrape_thread and self.scrape_thread.isRunning():
            self.scrape_thread.stop()
            self.update_status("중지 요청됨... (현재 페이지 작업을 마친 뒤 종료됩니다)")
            self.stop_btn.setEnabled(False)
            QtWidgets.QMessageBox.information(self, "중지 수락", "목록 불러오기 작업이 중지 요청되었습니다. 진행 중인 페이지까지만 저장하고 멈춥니다.")

    @QtCore.pyqtSlot(dict)
    def add_memory_to_table(self, mem):
        self.table.setSortingEnabled(False) # 정렬 중에 행을 삽입하면 꼬일 수 있으므로 임시 비활성화
        
        self.memories.append(mem)
        i = self.table.rowCount()
        self.table.insertRow(i)
        
        # Checkbox
        chk_widget = QtWidgets.QWidget()
        chk_layout = QtWidgets.QHBoxLayout(chk_widget)
        checkbox = QtWidgets.QCheckBox()
        checkbox.setChecked(True)
        checkbox.stateChanged.connect(lambda state: self.update_selection_label())
        chk_layout.addWidget(checkbox)
        chk_layout.setAlignment(QtCore.Qt.AlignCenter)
        chk_layout.setContentsMargins(0, 0, 0, 0)
        self.table.setCellWidget(i, 0, chk_widget)
        
        self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(mem['date']))
        self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(mem['title']))
        self.table.setItem(i, 3, QtWidgets.QTableWidgetItem(mem['type']))
        self.table.setItem(i, 4, QtWidgets.QTableWidgetItem(mem.get('writer', '알 수 없음')))
        self.table.setItem(i, 5, QtWidgets.QTableWidgetItem(mem.get('has_photo', 'X')))
        
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
        self.load_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.download_btn.setEnabled(True)
        if self.scrape_thread.is_stopped:
            msg = f"목록 로드 중지됨: {len(self.memories)}개 수집 완료"
            self.update_status(msg)
            QtWidgets.QMessageBox.information(self, "불러오기 완료", msg)
        else:
            msg = f"목록 로드 완료: {len(self.memories)}개 수집 완료"
            self.update_status(msg)
            self.update_progress(100)
            QtWidgets.QMessageBox.information(self, "불러오기 완료", msg)

    def start_download(self):
        selected_indices = []
        for i in range(self.table.rowCount()):
            chk_widget = self.table.cellWidget(i, 0)
            checkbox = chk_widget.findChild(QtWidgets.QCheckBox)
            if checkbox.isChecked():
                selected_indices.append(i)
        
        if not selected_indices:
            QtWidgets.QMessageBox.warning(self, "경고", "다운로드할 항목을 선택해주세요.")
            return

        target_dir = self.dir_input.text()
        if not target_dir:
            QtWidgets.QMessageBox.warning(self, "경고", "저장 경로를 지정해주세요.")
            return

        self.stop_flag = False
        is_pdf = self.pdf_radio.isChecked()
        is_single_folder = self.folder_single_radio.isChecked()
        self.download_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        threading.Thread(target=self._run_download, args=(selected_indices, target_dir, is_pdf, is_single_folder), daemon=True).start()

    def _run_download(self, indices, target_dir, is_pdf, is_single_folder):
        # 윈도우 절전 모드 방지 설정 (ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        except Exception as win_e:
            pass
            
        try:
            profile_name = "알수없음"
            label_text = self.profile_label.text()
            if "아이 정보: " in label_text:
                raw = label_text.split("아이 정보: ")[1].strip()
                if raw and raw != "(아직 불러오지 않음)":
                    profile_name = raw.split()[0]
                    
            date_type_counts = {}
            total = len(indices)
            self.update_progress(0)
            for count, idx in enumerate(indices):
                if self.stop_flag:
                    self.update_status("알림장/앨범 다운로드가 중지되었습니다.")
                    break
                    
                mem = self.memories[idx]
                self.update_status(f"다운로드 중 ({count+1}/{total}): {mem['title']}")
                
                try:
                    import re
                    clean_date = re.sub(r'[\\/*?:"<>|]', "", mem['date']).strip().rstrip('.')
                    item_type = mem['type']
                    
                    base_target_dir = os.path.join(target_dir, f"{profile_name}_{item_type}")
                    if not os.path.exists(base_target_dir):
                        os.makedirs(base_target_dir)

                    dt_key = (clean_date, item_type)
                    post_index = date_type_counts.get(dt_key, 0)
                    date_type_counts[dt_key] = post_index + 1
                    mem['post_index'] = post_index
                    
                    if is_pdf:
                        # Extract YYMMDD for PDF name prefix
                        date_prefix = clean_date 
                        dt_match_dot = re.search(r'(\d{4})\.?\s*(\d{1,2})\.?\s*(\d{1,2})', clean_date)
                        dt_match_kor = re.search(r'(?:(\d{4})\s*년)?\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', clean_date)
                        import datetime
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
                        
                        filename = f"{prefix_str}_{mem.get('title', 'Unknown')}.pdf" if is_single_folder else f"{prefix_str}.pdf"
                        filename = re.sub(r'[\\/*?:"<>|]', "", filename).strip()
                        path = os.path.join(base_target_dir, filename) if is_single_folder else os.path.join(base_target_dir, clean_date, filename)
                        
                        success = manager.download_item(self.driver, mem, path, is_pdf, self.update_status)
                    else:
                        post_dir = base_target_dir if is_single_folder else os.path.join(base_target_dir, clean_date)
                        success = manager.download_item(self.driver, mem, post_dir, is_pdf, self.update_status)
                except Exception as item_e:
                    pass

                # Update progress bar
                progress_percentage = int(((count + 1) / total) * 100)
                self.update_progress(progress_percentage)
            
            if not self.stop_flag:
                self.update_status("선택한 모든 항목 다운로드가 완료되었습니다!")
                self.update_progress(100)
            # Use invokeMethod to show QMessageBox safely from a background thread
            QtCore.QMetaObject.invokeMethod(self, "_show_download_complete", QtCore.Qt.QueuedConnection)
        except Exception as e:
            self.update_status(f"다운로드 중 치명적 오류 발생: {e}")
        finally:
            self.enable_widget(self.download_btn, True)
            try:
                # 작업 종료 후 절전 모드 방지 해제 (기본값 복귀)
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            except:
                pass

    @QtCore.pyqtSlot()
    def _show_download_complete(self):
        self.tray_icon.showMessage("키즈노트 다운로더", "선택한 모든 항목의 다운로드가 성공적으로 완료되었습니다.", QtWidgets.QSystemTrayIcon.Information, 5000)
        QtWidgets.QMessageBox.information(self, "완료", "선택한 모든 항목의 다운로드가 완료되었습니다.")

    @QtCore.pyqtSlot(dict)
    def update_profile(self, profile_info):
        text = profile_info.get('text', '알 수 없음')
        img_b64 = profile_info.get('image', None)
        
        self.profile_label.setText(text)
        
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
            rounded = QtGui.QPixmap(size)
            rounded.fill(QtCore.Qt.transparent)
            
            painter = QtGui.QPainter(rounded)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            brush = QtGui.QBrush(pixmap.scaled(size, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation))
            painter.setBrush(brush)
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawEllipse(0, 0, size.width(), size.height())
            painter.end()
            
            self.profile_img_label.setPixmap(rounded)
            self.profile_img_label.setText("")

    def update_status(self, msg):
        QtCore.QMetaObject.invokeMethod(self.status_label, "setText", QtCore.Q_ARG(str, msg))

    def enable_widget(self, widget, enabled):
        QtCore.QMetaObject.invokeMethod(widget, "setEnabled", QtCore.Q_ARG(bool, enabled))

    def closeEvent(self, event):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
        event.accept()

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    ex = KidsnoteApp()
    ex.show()
    sys.exit(app.exec_())
