import sys
import threading
import os
import codecs
from PyQt5 import QtWidgets, QtCore, QtGui
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
import kidsnote_engine as manager

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

    def __init__(self, driver, scrape_reports=True, scrape_albums=True, limit_date_str=None, child_name=None):
        super().__init__()
        self.driver = driver
        self.scrape_reports = scrape_reports
        self.scrape_albums = scrape_albums
        self.limit_date_str = limit_date_str
        self.child_name = child_name
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
                limit_date_str=self.limit_date_str,
                child_name=self.child_name
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
        self.setWindowTitle('Kidsnote Memories Saver V1.00')
        
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
        
        # IDE 등에서 기본 파이썬 실행시 표시될 귀여운 아이콘(폴더나 집 모양 스탠다드 아이콘 활용)
        self.setWindowIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DirHomeIcon))

        # --- 레이아웃 설정 (메인 스크롤바를 없애기 위해 QScrollArea 제거하고 창 자체에 고정) ---
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(FS(10))

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
        self.tray_icon.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DirHomeIcon))
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
        self.profile_img_label.setFixedSize(FS(80), FS(80))
        self.profile_img_label.setStyleSheet(f"border-radius: {FS(40)}px; background-color: #E2E8F0;")
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

        # 조회 기간
        period_layout = QtWidgets.QVBoxLayout()
        period_layout.addWidget(QtWidgets.QLabel("조회 기간:"))
        self.period_combo = QtWidgets.QComboBox()
        self.period_combo.addItems(["전체 수집 (시간이 오래 걸릴 수 있습니다)", "최근 3개월", "최근 6개월", "최근 1년", "최근 2년"])
        self.period_combo.setCurrentIndex(0)
        period_layout.addWidget(self.period_combo)
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
        target_layout.addWidget(self.select_all_btn)
        target_layout.addWidget(self.deselect_all_btn)
        
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
        self.table.setColumnCount(6)
        # 테이블의 기본 높이를 확 줄여서(250), 초기 빈 상태에선 앱 중앙 스크롤이 생기지 않도록 방지
        self.table.setMinimumHeight(FS(250))
        self.table.setHorizontalHeaderLabels(['선택', '날짜', '제목', '종류', '작성자', '사진'])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self.table.setColumnWidth(0, FS(40))
        self.table.setColumnWidth(1, FS(110))  # 날짜: "2026.01.26"
        self.table.setColumnWidth(3, FS(70))   # 종류: 알림장/앨범
        self.table.setColumnWidth(4, FS(180))  # 작성자: "2025 GREEN 교사" 등
        self.table.setColumnWidth(5, FS(45))   # 사진: O/X
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

        # Download Button
        self.download_btn = QtWidgets.QPushButton('3. 선택한 항목 다운로드 시작')
        self.download_btn.clicked.connect(self.start_download)
        self.download_btn.setEnabled(False)
        self.download_btn.setFixedHeight(FS(40))
        self.download_btn.setStyleSheet(f"""
            QPushButton {{ background-color: #FFC300; color: #2D3748; font-weight: bold; border-radius: {S(6)}px; }}
            QPushButton:hover {{ background-color: #E6B000; }}
            QPushButton:disabled {{ background-color: #FFDE59; color: #8A94A6; }}
        """)
        main_layout.addWidget(self.download_btn)

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

            from selenium.webdriver.edge.service import Service
            
            options = webdriver.EdgeOptions()
            options.add_argument('--window-size=1100,900')
            options.add_experimental_option("detach", True) 

            # 내장된 msedgedriver.exe 경로 탐색 (PyInstaller 빌드 환경 vs 일반 환경)
            if hasattr(sys, '_MEIPASS'):
                driver_path = os.path.join(sys._MEIPASS, 'msedgedriver.exe')
            else:
                driver_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'msedgedriver.exe')
                
            service = Service(executable_path=driver_path)
            self.driver = webdriver.Edge(service=service, options=options)

            # GUI 창의 위치/크기를 읽어 Edge를 바로 오른쪽에 배치
            try:
                geo = self.geometry()
                chrome_x = geo.x() + geo.width() + 8
                chrome_y = geo.y()
                self.driver.set_window_position(chrome_x, chrome_y)
                self.driver.set_window_size(1100, geo.height())
            except Exception:
                pass

            self.driver.get("https://www.kidsnote.com/login")
            
            # Wait for login fields and fill them
            wait = WebDriverWait(self.driver, 15)
            user_field = wait.until(EC.presence_of_element_located((By.NAME, "username")))
            pass_field = self.driver.find_element(By.NAME, "password")
            
            user_field.send_keys(username)
            pass_field.send_keys(password)
            pass_field.send_keys(Keys.RETURN) # Auto-submit
            
            self.update_status("안전하게 로그인 되었습니다! 아이 목록을 조회하는 중...")
            self._update_overlay_text("✅ 로그인 성공! 아이 정보를 확인 중입니다...")
            self.lock_overlay.hide()
            
            # 1단계가 열리면 2,3단계를 아직 못 만지게 stage2 잠금 활성화
            if hasattr(self, 'stage2_lock_overlay'):
                self.stage2_lock_overlay.show()
                self.stage2_lock_overlay.raise_()
                self.resizeEvent(None)  # 강제 레이아웃 실시간 갱신

            self.login_btn.setText("✅ 로그인 완료")
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
                QtCore.QMetaObject.invokeMethod(self, "update_profile", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(dict, {"text": first_child["text"], "image": first_child.get("img_b64", None)}))
        else:
            self.update_status("로그인 완료! 아이 목록을 찾을 수 없으므로 브라우저에서 직접 선택해주세요.")

    def on_child_combo_changed(self, index):
        if hasattr(self, 'children_data') and 0 <= index < len(self.children_data):
            try:
                child_info = self.children_data[index]
                name = child_info['text'].split()[0]
                script = f"""
                    var spans = document.querySelectorAll("span[role='img']");
                    for(var i=0; i<spans.length; i++){{
                        var parent = spans[i].parentElement.parentElement;
                        if(parent && parent.innerText && parent.innerText.includes("{name}")) {{
                            spans[i].click();
                            return true;
                        }}
                    }}
                    return false;
                """
                
                # 강제로 최상단 서비스 홈으로 돌린 상태에서 클릭해야 꼬이지 않음
                if "kidsnote.com/service" not in self.driver.current_url:
                    self.driver.get("https://www.kidsnote.com/service")
                    import time
                    time.sleep(1.5)
                    
                res = self.driver.execute_script(script)
                import time
                time.sleep(2) # React 상태 변경 후 렌더링되도록 넉넉히 대기
                
                self.update_status(f"[{self.child_combo.currentText()}] 계정으로 전환되었습니다. 이제 수집을 시작하세요.")
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
        self.chk_report.setEnabled(False)
        self.chk_album.setEnabled(False)
        self.period_combo.setEnabled(False)
        self.loading_banner.setVisible(True)
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
            child_name=child_name
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
        self.chk_report.setEnabled(True)
        self.chk_album.setEnabled(True)
        self.period_combo.setEnabled(True)
        self.loading_banner.setVisible(False)
        
        # 목록 조회가 끝났으므로 2,3단계 조작 가능하도록 오버레이 해제
        if hasattr(self, 'stage2_lock_overlay') and self.stage2_lock_overlay.isVisible():
             self.stage2_lock_overlay.hide()
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

        # 아이 이름: 콤보박스 텍스트에서 첫 단어(이름)만 콕직으로 추출
        profile_name = "알수없음"
        try:
            combo_text = self.child_combo.currentText().strip()
            if combo_text:
                profile_name = combo_text.split()[0]  # "최승아 23.7.14." → "최승아"
        except:
            pass

        self.download_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        
        is_overwrite_allow = self.overwrite_allow_radio.isChecked()
        
        threading.Thread(target=self._run_download, args=(selected_indices, target_dir, is_pdf, is_single_folder, profile_name, is_overwrite_allow), daemon=True).start()

    def _run_download(self, indices, target_dir, is_pdf, is_single_folder, profile_name="알수없음", is_overwrite_allow=True):
        # 윈도우 절전 모드 방지 설정 (ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        except Exception as win_e:
            pass

        try:
                    
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
                        
                        if is_single_folder:
                            filename = f"{prefix_str}_{mem.get('title', 'Unknown')}.pdf"
                            filename = re.sub(r'[\\/*?"<>|]', "", filename).strip()
                            path = os.path.join(base_target_dir, filename)
                        else:
                            filename = f"{prefix_str}.pdf"
                            filename = re.sub(r'[\\/*?"<>|]', "", filename).strip()
                            date_dir = os.path.join(base_target_dir, clean_date)
                            if not os.path.exists(date_dir):
                                os.makedirs(date_dir, exist_ok=True)
                            path = os.path.join(date_dir, filename)
                        
                        success = manager.download_item(self.driver, mem, path, is_pdf, self.update_status, is_overwrite_allow)
                    else:
                        if is_single_folder:
                            post_dir = base_target_dir
                        else:
                            post_dir = os.path.join(base_target_dir, clean_date)
                            if not os.path.exists(post_dir):
                                os.makedirs(post_dir, exist_ok=True)
                        success = manager.download_item(self.driver, mem, post_dir, is_pdf, self.update_status, is_overwrite_allow)
                except Exception as item_e:
                    pass

                # Update progress bar
                progress_percentage = int(((count + 1) / total) * 100)
                self.update_progress(progress_percentage)
            
            if not self.stop_flag:
                self.update_status("선택한 모든 항목 다운로드가 완료되었습니다!")
                self.update_progress(100)
            # Use invokeMethod to show QMessageBox safely from a background thread
            QtCore.QMetaObject.invokeMethod(self, "_show_download_complete", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, target_dir))
        except Exception as e:
            self.update_status(f"다운로드 중 치명적 오류 발생: {e}")
        finally:
            self.enable_widget(self.download_btn, True)
            try:
                # 작업 종료 후 절전 모드 방지 해제 (기본값 복귀)
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            except:
                pass

    @QtCore.pyqtSlot(str)
    def _show_download_complete(self, target_dir):
        self.tray_icon.showMessage("키즈노트 다운로더", "선택한 모든 항목의 다운로드가 성공적으로 완료되었습니다.", QtWidgets.QSystemTrayIcon.Information, 5000)
        
        reply = QtWidgets.QMessageBox.question(
            self, 
            "다운로드 완료", 
            "선택한 모든 항목의 다운로드가 완료되었습니다.\n지금 폴더를 열어보시겠습니까?", 
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, 
            QtWidgets.QMessageBox.Yes
        )
        
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
    # 4K 모니터 등 고해상도(High DPI) 디스플레이에서 GUI 텍스트와 UI가 극단적으로 작아지는 현상 방지
    if hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    if hasattr(QtCore.Qt, 'AA_UseHighDpiPixmaps'):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
        
    app = QtWidgets.QApplication(sys.argv)
    ex = KidsnoteApp()
    ex.show()
    sys.exit(app.exec_())
