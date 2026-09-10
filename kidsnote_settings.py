# -*- coding: utf-8 -*-
"""사용자 설정 파일(Kidsnote_Config.ini) 읽고 쓰기.

설정을 손대는 곳이 세 군데(초기 로딩, 로그인 정보 저장, 다운로드 옵션 저장)에
흩어져 있었고, 각각 파일을 직접 열고 configparser를 다뤘다. 파일이 깨졌을 때의
방어 코드는 그중 한 곳에만 있어서, 나머지 두 곳은 같은 상황에서 예외로 죽었다.

여기 한곳으로 모아 두면 인코딩 처리도, 저장 실패 처리도 한 번만 하면 된다.

저장 위치는 사용자 홈 폴더다. 프로그램 폴더에 두면 배포본을 다른 곳에 옮겨
받을 때마다 설정이 사라진다.
"""
import configparser
import os


CONFIG_NAME = "Kidsnote_Config.ini"


def default_path():
    return os.path.join(os.path.expanduser("~"), CONFIG_NAME)


class Settings(object):
    """설정 파일 하나를 감싼다. 읽기는 항상 성공하고, 쓰기는 실패해도 죽지 않는다."""

    def __init__(self, path=None, log=None):
        self.path = path or default_path()
        self._log = log
        self._parser = configparser.ConfigParser()
        self._load()

    # ------------------------------------------------------------------ 내부
    def _say(self, msg):
        if self._log:
            self._log(msg)

    def _load(self):
        """설정을 읽어 들인다. 파일이 깨져 있어도 예외를 내지 않는다.

        configparser.read()는 기본 로케일 인코딩으로 파일을 연다. 그래서 BOM이
        하나만 붙어 있어도 예외로 죽는데, 예전 버전이 BOM 붙은 파일을 쓴 적이 있어
        실제로 프로그램이 안 뜨는 일이 있었다. 인코딩을 차례로 바꿔 가며 시도하고,
        그래도 안 되면 빈 설정으로 시작한다. 설정을 잃는 것이 못 뜨는 것보다 낫다.
        """
        for encoding in ("utf-8-sig", "utf-8", None):
            try:
                self._parser.read(self.path, encoding=encoding)
                return
            except UnicodeDecodeError:
                continue
            except Exception:
                self._say("Config read failed; starting with defaults")
                break
        self._parser = configparser.ConfigParser()

    # ------------------------------------------------------------------ 읽기
    def get(self, section, key, fallback=""):
        return self._parser.get(section, key, fallback=fallback)

    def get_bool(self, section, key, fallback=False):
        try:
            return self._parser.getboolean(section, key, fallback=fallback)
        except ValueError:
            # 사용자가 파일을 직접 고쳐 'yes'도 'true'도 아닌 값이 들어간 경우
            return fallback

    # ------------------------------------------------------------------ 쓰기
    def set_many(self, section, values):
        """한 구획에 여러 값을 넣는다. 값은 모두 문자열로 저장된다."""
        if not self._parser.has_section(section):
            self._parser.add_section(section)
        for key, value in values.items():
            self._parser.set(section, key, str(value))

    def save(self):
        """파일에 쓴다. 실패해도 예외를 밖으로 내지 않고 False를 돌려준다.

        저장 실패는 다음 실행 때 설정이 없는 정도의 문제라, 지금 하던 일
        (로그인이나 다운로드)을 멈출 이유가 되지 않는다.
        """
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                self._parser.write(f)
            return True
        except Exception:
            self._say("Config save failed: %s" % self.path)
            return False
