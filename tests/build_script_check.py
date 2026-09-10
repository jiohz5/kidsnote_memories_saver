# -*- coding: utf-8 -*-
"""릴리스 빌드 스크립트가 cmd.exe 가 읽을 수 있는 상태인지 확인한다.

두 가지가 깨지면 빌드가 '조용히' 실패한다. 오류 메시지가 원인을 가리키지 않아
찾는 데 시간이 오래 걸리므로, 사람이 아니라 여기서 먼저 잡는다.

  줄바꿈: cmd 는 배치 파일을 CRLF 기준 바이트 위치로 읽는다. LF 로만 저장되면
          줄 중간부터 이어 읽어, 변수 대입문 조각을 명령으로 실행한다.
          ('BUILD_PY'은(는) 내부 명령이 아닙니다 같은 엉뚱한 오류가 난다)

  글자:   chcp 65001 아래에서 한글 주석이 섞이면 파서가 위치를 잃는다.
          특히 따옴표까지 있는 줄에서 뒷부분이 명령으로 실행된다.

.gitattributes 가 체크아웃 시 CRLF 를 보장하지만, sed 같은 도구로 파일을 고치면
그때 벗겨진다. 실제로 V1.08 과 V1.09 준비 중에 두 번 다 이렇게 됐다.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []


def check(name, cond, detail=""):
    print("[%s] %s" % ("PASS" if cond else "FAIL", name), end="")
    print("" if cond else "  (%s)" % detail)
    if not cond:
        fails.append(name)


for name in sorted(f for f in os.listdir(ROOT) if f.lower().endswith('.bat')):
    path = os.path.join(ROOT, name)
    raw = open(path, 'rb').read()

    crlf = raw.count(b'\r\n')
    lone_lf = raw.count(b'\n') - crlf
    check("%s: 모든 줄이 CRLF" % name, lone_lf == 0,
          "LF 단독 %d줄 (cmd 가 줄 중간부터 읽는다)" % lone_lf)

    bad_lines = [i + 1 for i, line in enumerate(raw.split(b'\r\n'))
                 if any(b > 127 for b in line)]
    check("%s: ASCII 만 쓴다" % name, not bad_lines,
          "비ASCII 줄 %s" % bad_lines)

    # goto 로 넘어가는 라벨이 실제로 있는지 (오타가 나면 빌드가 중간에 끝난다)
    text = raw.decode('ascii', errors='replace')
    labels = {l.strip()[1:].split()[0].lower()
              for l in text.splitlines() if l.strip().startswith(':') and len(l.strip()) > 1}
    targets = set()
    for line in text.splitlines():
        parts = line.strip().lower().split()
        if parts and parts[0] == 'goto' and len(parts) > 1:
            targets.add(parts[1].lstrip(':'))
    missing = sorted(targets - labels - {'eof'})
    check("%s: goto 대상이 모두 있음" % name, not missing, "없는 라벨 %s" % missing)

print()
if fails:
    print("RESULT: %d FAIL: %s" % (len(fails), fails))
    sys.exit(1)
print("RESULT: ALL PASSED")
