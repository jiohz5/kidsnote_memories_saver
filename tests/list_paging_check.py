# -*- coding: utf-8 -*-
"""목록 쪽 넘기기(_scrape_list_pages)를 실제 헤드리스 Edge 로 확인한다.

'다음'을 누른 뒤 새 쪽이 떴는지 판단하는 방식이 핵심이다. 화면을 그리는 방식에 따라
결과가 달라지므로 세 가지를 모두 본다.

  새로 그림   누르면 카드 요소를 지우고 새로 만든다
  재사용      요소는 그대로 두고 안의 글만 바꾼다 (React 가 흔히 이렇게 한다)
              예전 판단은 '첫 카드 요소가 사라졌는가'만 봐서, 이 방식이면 쪽마다
              5초를 기다리고 1초를 더 쉬었다
  껍데기 먼저 글이 빈 카드가 먼저 뜨고 잠시 뒤 채워진다
              빈 카드로 바뀐 순간을 넘어간 것으로 보면 빈 카드를 읽어 글을 놓친다

Edge 와 msedgedriver 가 없으면 건너뛰고 RESULT: SKIPPED 를 찍는다.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import kidsnote_engine as m  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want
    print("[%s] %s" % ("PASS" if ok else "FAIL", name), end="")
    print("" if ok else "\n        기대=%r\n        실제=%r" % (want, got))
    if not ok:
        fails.append(name)


PAGES = 3
PER_PAGE = 12


def page_html(mode):
    """키즈노트 목록과 같은 클래스 구조의 가짜 목록. mode 에 따라 쪽을 넘기는 방식이 다르다."""
    return """
<html><body>
<div id="list"></div>
<button id="next"><span>다음</span></button>
<script>
var MODE = '%(mode)s', PAGES = %(pages)d, PER = %(per)d, page = 1;
function cardText(p, i) { return '%(mode)s 글 ' + p + '-' + i + ' 오늘도 즐겁게 지냈어요'; }
function dateText(p, i) { return '2026.0' + (9 - p) + '.' + (10 + i); }
function card(p, i) {
  return '<div class="exa4ze60"><div class="exa4ze65"><div>' + dateText(p, i) +
         '</div></div><div class="e14iqn2g4">' + cardText(p, i) + '</div></div>';
}
function render(p) {
  var h = ''; for (var i = 0; i < PER; i++) h += card(p, i);
  document.getElementById('list').innerHTML = h;
}
function fill(p) {
  var cards = document.querySelectorAll('.exa4ze60');
  for (var i = 0; i < cards.length; i++) {
    cards[i].querySelector('.exa4ze65 > div').textContent = dateText(p, i);
    cards[i].querySelector('.e14iqn2g4').textContent = cardText(p, i);
  }
}
render(1);
document.getElementById('next').addEventListener('click', function () {
  if (page >= PAGES) return;
  page += 1;
  if (MODE === 'replace') { render(page); }
  else if (MODE === 'reuse') { fill(page); }
  else if (MODE === 'skeleton') {
    var cards = document.querySelectorAll('.exa4ze60');
    for (var i = 0; i < cards.length; i++) {
      cards[i].querySelector('.exa4ze65 > div').textContent = '';
      cards[i].querySelector('.e14iqn2g4').textContent = '';
    }
    setTimeout(function () { fill(page); }, 700);
  }
  if (page >= PAGES) { document.getElementById('next').disabled = true; }
});
</script>
</body></html>
""" % {"mode": mode, "pages": PAGES, "per": PER_PAGE}


def make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    path = os.path.join(ROOT, 'msedgedriver.exe')
    if not os.path.exists(path):
        return None
    opts = webdriver.EdgeOptions()
    opts.add_argument('--headless=new')
    opts.add_argument('--window-size=1100,900')
    return webdriver.Edge(service=Service(executable_path=path), options=opts)


def scrape(driver, mode):
    driver.get("data:text/html;charset=utf-8," + page_html(mode))
    memories, info, logs = [], {}, []
    started = time.time()
    m._scrape_list_pages(driver, "알림장", memories, logs.append,
                         request=m.ScrapeRequest(), callbacks=m.ScrapeCallbacks(),
                         result_info=info)
    return memories, info, time.time() - started


skipped_reason = None
try:
    driver = make_driver()
    if driver is None:
        skipped_reason = "msedgedriver.exe 없음"
except Exception as e:
    driver = None
    skipped_reason = "Edge를 띄우지 못함(%s) - Edge와 드라이버 버전을 확인하세요" % type(e).__name__

if driver is None:
    print("\n[건너뜀] 브라우저 검사: %s" % skipped_reason)
else:
    try:
        expected = PAGES * PER_PAGE
        for mode, label in (("replace", "새로 그림"), ("reuse", "재사용"), ("skeleton", "껍데기 먼저")):
            print("\n== %s ==" % label)
            memories, info, took = scrape(driver, mode)
            titles = [x["title"] for x in memories]
            check("모든 쪽의 글을 모음 (%d개)" % expected, len(memories), expected)
            check("빈 글(껍데기)을 읽지 않음", sum(1 for t in titles if not t), 0)
            check("같은 글을 두 번 모으지 않음", len(set(titles)), len(titles))
            check("쪽 수 기록", info.get("pages"), PAGES)
            check("넘김을 기다리다 시간초과한 적 없음", info.get("next_timeouts", 0), 0)
            # 예전 방식이면 '재사용' 화면에서 쪽마다 6초씩, 두 번 넘기니 12초가 넘었다
            print("   걸린 시간 %.1f초" % took)
            check("오래 걸리지 않음 (8초 안)", took < 8, True)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

print()
if fails:
    print("RESULT: %d FAIL: %s" % (len(fails), fails))
    sys.exit(1)
if skipped_reason:
    print("RESULT: SKIPPED - 브라우저 검사를 하지 못함 (%s)" % skipped_reason)
    sys.exit(2)
print("RESULT: ALL PASSED")
