# -*- coding: utf-8 -*-
"""저장 위치·파일 이름 규칙 검증.

이 규칙이 어긋나면 같은 날짜가 두 폴더로 갈라지거나 같은 글이 두 벌로 쌓이는데,
둘 다 조용히 일어나서 한참 뒤에야 발견된다. GUI도 네트워크도 없이 돌아간다.
"""
import datetime
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kidsnote_paths import (  # noqa: E402
    parse_post_date, safe_title_fragment, pdf_filename, plan_save_paths,
)

fails = []


def check(name, got, want):
    ok = got == want
    print("[%s] %s" % ("PASS" if ok else "FAIL", name), end="")
    print("" if ok else "\n        기대=%r\n        실제=%r" % (want, got))
    if not ok:
        fails.append(name)


TODAY = datetime.date(2026, 9, 10)

# ---------------------------------------------------------------- 날짜 해석
print("\n== 날짜 해석 ==")
for raw, folder, prefix in [
    ("2026.07.14", "20260714", "260714"),   # 흔한 형태
    ("2026.7.4",   "20260704", "260704"),   # 한 자리 월/일 (점을 먼저 지우면 깨지는 경우)
    ("2026. 7. 4", "20260704", "260704"),   # 점 뒤에 공백
    ("2026.12.31", "20261231", "261231"),
    ("2026.01.01", "20260101", "260101"),
    ("2026년 7월 14일", "20260714", "260714"),
    ("7월 14일",   "20260714", "260714"),   # 연도 없으면 올해
]:
    d = parse_post_date(raw, today=TODAY)
    check("날짜 %-14s -> 폴더 %s / 파일 %s" % (raw, folder, prefix),
          (d.folder, d.prefix), (folder, prefix))

d = parse_post_date("2026.07.14")
check("점 있는 원본은 옛 폴더 이름으로 보관", d.raw, "2026.07.14")
check("점 있는 원본은 넘겨받을 대상", d.needs_legacy_rename, True)
check("이미 점 없는 이름은 넘겨받지 않음",
      parse_post_date("20260714").needs_legacy_rename, False)

# 날짜를 못 읽어도 폴더 이름은 나와야 한다 (빈 폴더명은 저장 자체를 깨뜨린다)
weird = parse_post_date("어제")
check("해석 실패해도 폴더명은 비지 않음", bool(weird.folder), True)
check("해석 실패는 parsed=False", weird.parsed, False)
check("빈 날짜도 예외 없이 처리", parse_post_date("").parsed, False)
check("None 날짜도 예외 없이 처리", parse_post_date(None).parsed, False)

# 파일명 금지문자는 날짜에서도 제거된다
check("날짜의 금지문자 제거", parse_post_date('2026/07:14').folder, "20260714")

# ---------------------------------------------------------------- 제목 조각
print("\n== 제목 조각 ==")
check("금지문자는 공백으로", safe_title_fragment('여름 <물놀이>: 1일차'), "여름 물놀이 1일차")
check("줄바꿈도 공백으로", safe_title_fragment("첫째 줄\n둘째 줄"), "첫째 줄 둘째 줄")
check("길이 제한", len(safe_title_fragment("가" * 50)), 30)
check("제목 없는 글은 빈 문자열", safe_title_fragment("제목 알 수 없음"), "")
check("빈 제목은 빈 문자열", safe_title_fragment(""), "")
check("None 제목은 빈 문자열", safe_title_fragment(None), "")
# 윈도우는 마침표로 끝나는 파일 이름을 조용히 잘라낸다
check("끝 마침표 제거", safe_title_fragment("오늘의 활동..."), "오늘의 활동")
check("잘린 자리의 공백 제거", safe_title_fragment("가" * 29 + " 나"), "가" * 29)

# ---------------------------------------------------------------- PDF 이름
print("\n== PDF 이름 ==")
check("첫 글은 순번 없음",
      pdf_filename("260714", "알림장", 0, "물놀이"), "260714_알림장_물놀이.pdf")
check("같은 날 둘째 글부터 순번",
      pdf_filename("260714", "알림장", 1, "물놀이"), "260714_알림장_1_물놀이.pdf")
check("제목 없으면 제목 없이",
      pdf_filename("260714", "알림장", 0, ""), "260714_알림장.pdf")
check("제목 없는 둘째 글",
      pdf_filename("260714", "앨범", 2, ""), "260714_앨범_2.pdf")

# ---------------------------------------------------------------- 저장 위치
print("\n== 저장 위치 ==")
BASE = os.path.join("C:", os.sep, "backup")
date = parse_post_date("2026.07.14")

p = plan_save_paths(BASE, "홍길동", "알림장", date, post_index=0, title="물놀이")
check("유형 폴더", p.type_dir, os.path.join(BASE, "홍길동_알림장"))
check("날짜 폴더", p.date_dir, os.path.join(BASE, "홍길동_알림장", "20260714"))
check("사진은 날짜 폴더에", p.media_dir, p.date_dir)
check("PDF 경로", p.pdf_path,
      os.path.join(BASE, "홍길동_알림장", "20260714", "260714_알림장_물놀이.pdf"))
check("점 있는 옛 폴더를 넘겨받음", p.legacy_date_dir,
      os.path.join(BASE, "홍길동_알림장", "2026.07.14"))
check("제목 없던 옛 PDF를 넘겨받음", p.legacy_pdf_path,
      os.path.join(BASE, "홍길동_알림장", "20260714", "260714_알림장.pdf"))

# 한 폴더에 모으기: 날짜 폴더를 만들지 않으므로 넘겨받을 옛 폴더도 없다
s = plan_save_paths(BASE, "홍길동", "앨범", date, title="물놀이", single_folder=True)
check("모으기: 날짜 폴더 없음", s.date_dir, None)
check("모으기: 사진도 유형 폴더에", s.media_dir, s.type_dir)
check("모으기: PDF도 유형 폴더에", s.pdf_path,
      os.path.join(BASE, "홍길동_앨범", "260714_앨범_물놀이.pdf"))
check("모으기: 옛 폴더 넘겨받지 않음", s.legacy_date_dir, None)

# 사진만 받는 모드에서는 PDF 경로를 만들지 않는다
m = plan_save_paths(BASE, "홍길동", "앨범", date, want_pdf=False)
check("사진만: PDF 경로 없음", m.pdf_path, None)
check("사진만: 옛 PDF도 없음", m.legacy_pdf_path, None)
check("사진만: 사진 폴더는 있음", m.media_dir,
      os.path.join(BASE, "홍길동_앨범", "20260714"))

# 제목이 없으면 옛 이름과 새 이름이 같으므로 넘겨받을 것이 없다
n = plan_save_paths(BASE, "홍길동", "알림장", date, title="")
check("제목 없으면 넘겨받을 옛 PDF 없음", n.legacy_pdf_path, None)

# 이미 점 없는 날짜라면 넘겨받을 폴더가 없다
already = plan_save_paths(BASE, "홍길동", "알림장", parse_post_date("20260714"))
check("점 없는 날짜는 넘겨받을 폴더 없음", already.legacy_date_dir, None)

# ------------------------------------------------------- 같은 날 여러 글 충돌
print("\n== 같은 날 여러 글이 서로 덮어쓰지 않는가 ==")
names = {pdf_filename("260714", "알림장", i, "같은 제목") for i in range(3)}
check("순번이 붙어 이름이 모두 다름", len(names), 3)

print()
if fails:
    print("RESULT: %d FAIL: %s" % (len(fails), fails))
    sys.exit(1)
print("RESULT: ALL PASSED")
