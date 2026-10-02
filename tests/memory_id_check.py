# -*- coding: utf-8 -*-
"""게시물 id 형식을 고정한다.

id 는 증분 백업 기록(downloaded_items.json)에 그대로 쌓인다. [새 항목만 선택]과
표의 'O' 표시가 이것으로 '이미 받은 글'을 알아보므로, 형식이 조금만 바뀌어도
이미 받은 글 전부가 새 글로 보인다. 날짜 표기를 손볼 때 특히 깨지기 쉽다.

세 가지를 본다.
  1. 정해진 입력에 정해진 id 가 나온다 (형식 고정)
  2. 예전 인라인 공식과 결과가 같다 (리팩토링이 형식을 바꾸지 않았다)
  3. 이 PC의 실제 기록이 이 공식으로 만든 모양과 맞는다 (있을 때만, 제목은 출력하지 않는다)
"""
import itertools
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import kidsnote_engine as m  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want
    print("[%s] %s" % ("PASS" if ok else "FAIL", name), end="")
    print("" if ok else "\n        기대=%r\n        실제=%r" % (want, got))
    if not ok:
        fails.append(name)


print("\n== 제목 ==")
check("35자 이하는 그대로", m.format_list_title("가" * 35), "가" * 35)
check("36자부터 35자 + '...'", m.format_list_title("가" * 36), "가" * 35 + "...")
check("앞뒤 공백은 지움", m.format_list_title("  오늘 하루  "), "오늘 하루")
check("줄바꿈은 공백으로", m.format_list_title("첫 줄\n둘째 줄"), "첫 줄 둘째 줄")
check("자른 뒤에 줄바꿈을 바꿈",
      m.format_list_title("가" * 34 + "\n" + "나" * 10), "가" * 34 + " " + "...")
check("빈 본문", m.format_list_title(""), "")
check("None 본문", m.format_list_title(None), "")

print("\n== id ==")
check("형식: 유형_날짜_제목_주소",
      m.make_memory_id("알림장", "2026.07.14", "물놀이", "https://x/1"),
      "알림장_2026.07.14_물놀이_https://x/1")
# 지금까지 쌓인 기록은 전부 주소 자리가 'None' 이다. 빈 문자열로 바꾸면 안 된다.
check("주소가 없으면 문자열 'None'",
      m.make_memory_id("앨범", "2026.07.14", "물놀이", None),
      "앨범_2026.07.14_물놀이_None")
check("날짜를 못 읽은 글",
      m.make_memory_id("알림장", "날짜 알 수 없음", "x", None),
      "알림장_날짜 알 수 없음_x_None")


print("\n== 예전 인라인 공식과 같은가 ==")
def old_title(full_text):
    # kidsnote_engine._scrape_list_pages 에 있던 식 그대로 (수정 금지)
    full_text = full_text.strip()
    return (full_text[:35].replace('\n', ' ') + "..."
            if len(full_text) > 35 else full_text.replace('\n', ' '))


samples = [
    "", " ", "a", "가" * 35, "가" * 36, "가" * 80, "첫\n둘", "가" * 34 + "\n나나",
    "\n앞줄바꿈", "끝줄바꿈\n", "  공백  ", "탭\t포함", "이모지 🎉 포함" * 3,
    "오늘은...", "가" * 33 + "...",
]
lengths = [0, 1, 34, 35, 36, 37, 70]
mismatch = 0
for text in samples + ["나" * n for n in lengths] + ["다\n" * n for n in lengths]:
    if old_title(text) != m.format_list_title(text):
        mismatch += 1
check("모든 표본에서 동일 (%d개)" % (len(samples) + 2 * len(lengths)), mismatch, 0)


print("\n== 이 PC의 실제 기록과 모양이 맞는가 ==")
path = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                    "KidsnoteMemoriesSaver", "downloaded_items.json")
if not os.path.exists(path):
    print("   [건너뜀] 기록 파일이 없습니다")
else:
    data = json.load(open(path, encoding="utf-8"))
    ids = data if isinstance(data, list) else list(data)
    shape = re.compile(r'^(알림장|앨범)_(\d{4}\.\d{2}\.\d{2}|날짜 알 수 없음)_(.*)_(https?://\S+|None)$')
    bad_shape = 0
    bad_title = 0
    for i in ids:
        mt = shape.match(i)
        if not mt:
            bad_shape += 1
            continue
        title = mt.group(3)
        # 이 공식이 만드는 제목은 둘 중 하나다:
        #   35자 이하(줄바꿈 없음)  또는  35자 + '...' = 38자
        if "\n" in title or not (len(title) <= 35 or (len(title) == 38 and title.endswith("..."))):
            bad_title += 1
    print("   기록 %d건 확인 (제목은 출력하지 않음)" % len(ids))
    check("모든 id 가 '유형_yyyy.MM.dd_제목_주소' 모양", bad_shape, 0)
    check("모든 제목이 이 공식으로 만들 수 있는 모양", bad_title, 0)

print()
if fails:
    print("RESULT: %d FAIL: %s" % (len(fails), fails))
    sys.exit(1)
print("RESULT: ALL PASSED")
