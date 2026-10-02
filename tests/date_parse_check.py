# -*- coding: utf-8 -*-
"""날짜 해석을 한 곳으로 모은 것이 결과를 바꾸지 않았는지 대조한다.

같은 정규식이 엔진 네 곳과 kidsnote_paths 한 곳에 복사되어 있었다. 각각 정하는 것이
달랐다. 어떤 글을 수집할지(기간 거르기), 어떤 글을 내려받을지(다운로드 대상 찾기),
사진 파일 이름 앞부분, 저장 파일의 시각. 이제 모두 kidsnote_paths.parse_ymd 를 쓴다.

예전 코드를 아래에 그대로 옮겨 두고, 많은 입력에 대해 새 코드와 결과를 비교한다.
특히 '수집할 날짜 표기'가 하나라도 바뀌면 증분 백업 기록의 id 가 달라져 이미 받은 글이
새 글로 보이므로, 여기서 한 건이라도 다르면 실패다.
"""
import datetime
import itertools
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import kidsnote_engine as m  # noqa: E402
import kidsnote_paths as p  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want
    print("[%s] %s" % ("PASS" if ok else "FAIL", name), end="")
    print("" if ok else "\n        기대=%r\n        실제=%r" % (want, got))
    if not ok:
        fails.append(name)


# ------------------------------------------------------------ 예전 코드 (수정 금지)
def old_list_date(raw_date):
    """_scrape_list_pages 의 기간 거르기 앞 날짜 정규화."""
    date = raw_date
    if date != "날짜 알 수 없음" and date:
        match_dot = re.search(r'(\d{4})\.?\s*(\d{1,2})\.?\s*(\d{1,2})', date)
        match_kor = re.search(r'(?:(\d{4})\s*년)?\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', date)
        current_year = datetime.date.today().year
        if match_dot:
            y, mo, d = match_dot.groups()
            date = f"{y}.{int(mo):02d}.{int(d):02d}"
        elif match_kor:
            y = match_kor.group(1) or current_year
            mo = match_kor.group(2)
            d = match_kor.group(3)
            date = f"{y}.{int(mo):02d}.{int(d):02d}"
    return date


def old_find_target_date(raw_date):
    """download_item._find_target 의 날짜 정규화."""
    d = raw_date
    if d and d != "날짜 알 수 없음":
        match_dot = re.search(r'(\d{4})\.?\s*(\d{1,2})\.?\s*(\d{1,2})', d)
        match_kor = re.search(r'(?:(\d{4})\s*년)?\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', d)
        current_year = datetime.date.today().year
        if match_dot:
            y, mo, day = match_dot.groups()
            d = f"{y}.{int(mo):02d}.{int(day):02d}"
        elif match_kor:
            y = match_kor.group(1) or current_year
            mo = match_kor.group(2)
            day = match_kor.group(3)
            d = f"{y}.{int(mo):02d}.{int(day):02d}"
    return d


def old_media_prefix(post_info):
    date_prefix = "unknown"
    try:
        date_str = post_info.get("date", "") or ""
        match_dot = re.search(r'(\d{4})\.?\s*(\d{1,2})\.?\s*(\d{1,2})', date_str)
        match_kor = re.search(r'(?:(\d{4})\s*년)?\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', date_str)
        current_year = datetime.date.today().year
        if match_dot:
            y, mo, d = match_dot.groups()
        elif match_kor:
            y = match_kor.group(1) or current_year
            mo = match_kor.group(2)
            d = match_kor.group(3)
        else:
            y, mo, d = None, None, None
        if y and mo and d:
            date_prefix = f"{str(y)[-2:]}{int(mo):02d}{int(d):02d}"
    except Exception:
        date_prefix = "unknown"
    post_index = post_info.get('post_index', 0)
    item_type = post_info.get('type', '사진')
    return f"{date_prefix}_{item_type}" if post_index == 0 else f"{date_prefix}_{item_type}_{post_index}"


def old_post_timestamp(post_info):
    date_str = post_info.get("date", "") or ""
    match_dot = re.search(r'(\d{4})\.?\s*(\d{1,2})\.?\s*(\d{1,2})', date_str)
    match_kor = re.search(r'(?:(\d{4})\s*년)?\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', date_str)
    try:
        if match_dot:
            y, mo, d = match_dot.groups()
        elif match_kor:
            y = match_kor.group(1) or datetime.date.today().year
            mo = match_kor.group(2)
            d = match_kor.group(3)
        else:
            return None
        return datetime.datetime(int(y), int(mo), int(d), 12, 0, 0).timestamp()
    except Exception:
        return None


# ------------------------------------------------------------ 입력
DATES = [
    "2026.07.14", "2026.7.4", "2026. 7. 4", "2026.12.31", "2026.01.01", "2024.02.29",
    "2026.07.14.", "20260714", "2026.1.5", "2026.10.5", "2026.11.09",
    "2026년 7월 14일", "2026년7월4일", "7월 14일", "12월 1일", "7월4일",
    "2026.07.14 (화)", "작성일 2026.07.14", "2026-07-14", "2026/07/14",
    "2026.13.40", "2026.00.00", "날짜 알 수 없음", "", "어제", "방금 전",
    "2026.7.4 7월 5일",          # 숫자 표기와 한글 표기가 함께 있으면 숫자 쪽
    "가나다", "123", "2026",
]

print("\n== 기간 거르기용 날짜 (id 에도 들어감) ==")
diff = [d for d in DATES if old_list_date(d) != p.normalize_list_date(d)]
check("목록 날짜 정규화 동일 (%d개 입력)" % len(DATES), diff, [])

print("\n== 내려받을 글 찾기용 날짜 ==")
diff = [d for d in DATES if old_find_target_date(d) != p.normalize_list_date(d)]
check("다운로드 대상 날짜 동일", diff, [])
# None 도 예외 없이 그대로 돌려줘야 한다
check("None 은 None", p.normalize_list_date(None), old_find_target_date(None))

print("\n== 사진 파일 이름 앞부분 ==")
diff = []
for d, idx, typ in itertools.product(DATES, (0, 1, 3), ("알림장", "앨범", None)):
    info = {"date": d, "post_index": idx}
    if typ:
        info["type"] = typ
    if old_media_prefix(info) != m._media_prefix(info):
        diff.append((d, idx, typ))
check("접두사 동일 (%d개 조합)" % (len(DATES) * 9), diff, [])
check("날짜 키가 없어도 동일", m._media_prefix({}), old_media_prefix({}))

print("\n== 저장 파일 시각 ==")
diff = [d for d in DATES if old_post_timestamp({"date": d}) != m._post_timestamp({"date": d})]
check("파일 시각 동일", diff, [])

print("\n== 폴더 이름 (원래 테스트가 있던 쪽) ==")
check("2026.7.4 -> 20260704", p.parse_post_date("2026.7.4").folder, "20260704")
check("7월 14일 -> 올해", p.parse_post_date("7월 14일", today=datetime.date(2026, 9, 1)).folder,
      "20260714")
check("못 읽으면 원문", p.parse_post_date("어제").folder, "어제")

print("\n== 정규화 결과가 문자열 비교에 맞는가 ==")
# 기간 거르기는 문자열 비교다. 한 자리 월이 그대로 남으면 7월이 9월보다 '크다'고 나온다.
check("한 자리 월도 두 자리로", p.normalize_list_date("2026.7.4") < "2026.09.10", True)

print()
if fails:
    print("RESULT: %d FAIL: %s" % (len(fails), fails))
    sys.exit(1)
print("RESULT: ALL PASSED")
