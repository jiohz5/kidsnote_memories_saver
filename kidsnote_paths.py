# -*- coding: utf-8 -*-
"""저장 위치와 파일 이름을 정하는 규칙.

여기 있는 함수는 전부 순수 함수다. 파일을 만들지도, 지우지도, 옮기지도 않고
경로 문자열만 계산해서 돌려준다. 실제 디스크 작업은 부르는 쪽(DownloadThread)이 한다.

이렇게 떼어 놓은 이유:
사용자가 받은 추억이 어느 폴더에 어떤 이름으로 들어가는지는 이 프로그램에서
가장 눈에 띄는 결과물인데, 규칙이 조금만 어긋나도 같은 날짜가 두 폴더로 갈라지거나
같은 글이 두 벌로 쌓인다. 그런 사고는 조용히 일어나서 한참 뒤에야 발견된다.
규칙이 스레드 안에 섞여 있으면 실제로 로그인해서 받아 보기 전에는 검증할 수 없으므로,
계산만 따로 꺼내어 표로 놓고 확인할 수 있게 했다.

날짜 표기는 두 가지를 쓴다.
    폴더 = YYYYMMDD (20260714)   — 정렬이 자연스럽고 탐색기에서 한눈에 들어온다
    파일 = YYMMDD   (260714)     — 이름이 길어지지 않게 두 자리 연도를 쓴다
"""
import datetime
import os
import re

# 윈도우 파일 이름에 쓸 수 없는 문자
_FORBIDDEN = r'[\\/*?:"<>|]'

# '2026.07.14', '2026. 7. 4', '20260714' 처럼 숫자 위주로 적힌 날짜
_DATE_NUMERIC = re.compile(r'(\d{4})\.?\s*(\d{1,2})\.?\s*(\d{1,2})')
# '2026년 7월 14일', '7월 4일' 처럼 한글로 적힌 날짜 (연도는 없을 수 있음)
_DATE_KOREAN = re.compile(r'(?:(\d{4})\s*년)?\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일')


class PostDate(object):
    """게시물 날짜 하나를 폴더용·파일용 표기로 함께 들고 있는 값.

    parsed 가 False 면 날짜를 해석하지 못한 것이다. 이때는 원문에서 점만 지운
    문자열을 그대로 쓰는데, 최소한 폴더 이름으로 쓸 수는 있어야 하기 때문이다.
    """

    __slots__ = ('raw', 'folder', 'prefix', 'parsed')

    def __init__(self, raw, folder, prefix, parsed):
        self.raw = raw          # 금지문자만 지운 원본 (예: '2026.07.14')
        self.folder = folder    # 폴더 이름       (예: '20260714')
        self.prefix = prefix    # 파일 이름 앞부분 (예: '260714')
        self.parsed = parsed    # 날짜로 해석되었는가

    @property
    def needs_legacy_rename(self):
        """예전 버전이 만든 점 있는 폴더(2026.07.14)를 넘겨받아야 하는 경우."""
        return self.raw != self.folder

    def __repr__(self):
        return "PostDate(raw=%r, folder=%r, prefix=%r, parsed=%r)" % (
            self.raw, self.folder, self.prefix, self.parsed)

    def __eq__(self, other):
        if not isinstance(other, PostDate):
            return NotImplemented
        return (self.raw, self.folder, self.prefix, self.parsed) == (
            other.raw, other.folder, other.prefix, other.parsed)


def parse_post_date(raw_date, today=None):
    """게시물에 적힌 날짜 문자열을 폴더용·파일용 표기로 바꾼다.

    날짜 해석은 반드시 구분자가 살아 있는 원문으로 한다.
    점을 먼저 지우고 파싱하면 '2026.7.4' 가 '202674' 가 되어 자릿수 경계가 사라진다.

    연도가 없는 한글 표기('7월 14일')는 올해로 본다. 키즈노트 목록은 올해 글에서
    연도를 생략하기 때문이다.
    """
    raw_clean = re.sub(_FORBIDDEN, "", raw_date or "").strip().rstrip('.')

    numeric = _DATE_NUMERIC.search(raw_clean)
    korean = _DATE_KOREAN.search(raw_clean)
    if numeric:
        year, month, day = numeric.groups()
    elif korean:
        year = korean.group(1) or (today or datetime.date.today()).year
        month, day = korean.group(2), korean.group(3)
    else:
        # 해석 실패: 점만 지운 원문을 폴더 이름으로 그대로 쓴다
        fallback = raw_clean.replace('.', '') or raw_clean
        return PostDate(raw_clean, fallback, fallback, False)

    year, month, day = int(year), int(month), int(day)
    return PostDate(
        raw_clean,
        "%04d%02d%02d" % (year, month, day),
        "%02d%02d%02d" % (year % 100, month, day),
        True,
    )


def safe_title_fragment(title, limit=30):
    """게시물 제목을 파일명에 쓸 수 있는 짧은 조각으로 바꾼다.

    윈도우 파일명 금지문자와 줄바꿈을 공백으로 바꾸고, 길이를 제한한 뒤
    끝의 공백·마침표를 없앤다. 윈도우는 마침표로 끝나는 이름을 조용히 잘라내서,
    남겨 두면 파일 이름이 의도와 달라진다.

    쓸 만한 글자가 없으면 빈 문자열을 돌려준다. 이 경우 부르는 쪽은 제목 없이 저장한다.
    """
    text = (title or "").strip()
    if not text or text.startswith("제목 알 수 없음"):
        return ""
    text = text.replace("...", " ")
    text = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text[:limit].strip()
    return text.rstrip(". ")


def pdf_filename(date_prefix, item_type, post_index, title):
    """PDF 파일 이름을 만든다.

    같은 날짜·같은 유형에 글이 여럿이면 두 번째부터 순번을 붙여 서로 덮어쓰지 않게 한다.
    제목은 열어보지 않아도 내용을 알 수 있도록 붙이는 것이라, 쓸 만한 글자가 없으면 생략한다.
    """
    stem = "%s_%s" % (date_prefix, item_type)
    if post_index:
        stem = "%s_%d" % (stem, post_index)
    fragment = safe_title_fragment(title)
    return ("%s_%s.pdf" % (stem, fragment)) if fragment else ("%s.pdf" % stem)


class SavePlan(object):
    """추억 하나를 저장할 위치 묶음.

    legacy_* 는 '예전 버전이 만들어 둔 이름'이다. 그 경로에 파일이나 폴더가 실제로
    있으면 새 이름으로 넘겨받아, 같은 글이 두 벌로 쌓이거나 같은 날짜가 두 폴더로
    갈라지는 것을 막는다. 없으면 아무 일도 하지 않는다.
    """

    __slots__ = ('type_dir', 'date_dir', 'media_dir', 'pdf_path',
                 'legacy_date_dir', 'legacy_pdf_path')

    def __init__(self, type_dir, date_dir, media_dir, pdf_path,
                 legacy_date_dir=None, legacy_pdf_path=None):
        self.type_dir = type_dir                # <저장폴더>/<아이이름>_<유형>
        self.date_dir = date_dir                # 날짜 폴더 (한 폴더에 모으기면 None)
        self.media_dir = media_dir              # 사진·동영상을 넣을 폴더
        self.pdf_path = pdf_path                # PDF 전체 경로 (PDF를 안 받으면 None)
        self.legacy_date_dir = legacy_date_dir  # 점 있는 옛 날짜 폴더
        self.legacy_pdf_path = legacy_pdf_path  # 제목 없던 옛 PDF 경로

    def __repr__(self):
        return "SavePlan(type_dir=%r, date_dir=%r, pdf_path=%r)" % (
            self.type_dir, self.date_dir, self.pdf_path)


def plan_save_paths(target_dir, profile_name, item_type, post_date,
                    post_index=0, title="", single_folder=False, want_pdf=True):
    """추억 하나를 어디에 어떤 이름으로 저장할지 계산한다. 디스크는 건드리지 않는다.

    single_folder 가 True 면 날짜별로 나누지 않고 유형 폴더 하나에 전부 모은다.
    이 경우 날짜 폴더가 없으므로 옛 폴더를 넘겨받는 일도 하지 않는다.
    """
    type_dir = os.path.join(target_dir, "%s_%s" % (profile_name, item_type))

    if single_folder:
        date_dir = None
        media_dir = type_dir
        legacy_date_dir = None
    else:
        date_dir = os.path.join(type_dir, post_date.folder)
        media_dir = date_dir
        legacy_date_dir = (os.path.join(type_dir, post_date.raw)
                           if post_date.needs_legacy_rename else None)

    pdf_path = None
    legacy_pdf_path = None
    if want_pdf:
        filename = pdf_filename(post_date.prefix, item_type, post_index, title)
        parent = type_dir if single_folder else date_dir
        pdf_path = os.path.join(parent, filename)
        # 제목을 붙이기 전 버전이 쓰던 이름. 제목이 붙은 경우에만 넘겨받을 대상이 있다.
        #
        # 날짜별로 나눌 때만 넘겨받는다. 한 폴더에 모으기 모드에서는 예전 버전도
        # 넘겨받기를 하지 않았고, 여기서 임의로 바꾸면 리팩토링이 조용히 동작을
        # 바꾸는 셈이 된다. (모으기 모드에도 같은 중복이 생길 수 있다는 점은
        # 별개 문제로 남겨 둔다.)
        untitled = pdf_filename(post_date.prefix, item_type, post_index, "")
        if untitled != filename and not single_folder:
            legacy_pdf_path = os.path.join(parent, untitled)

    return SavePlan(type_dir, date_dir, media_dir, pdf_path,
                    legacy_date_dir, legacy_pdf_path)
