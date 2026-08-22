# -*- coding: utf-8 -*-
"""GUI 상태를 기계적으로 수집해 JSON으로 남긴다.

Qt5 -> Qt6 전환처럼 겉보기 변화가 큰 작업에서, '무엇이 달라졌는지'를
눈이 아니라 데이터로 비교하기 위한 도구.

사용법:
    python tests/ui_snapshot.py before.json      # 현재 상태 기록
    python tests/ui_snapshot.py after.json       # 전환 후 기록
    python tests/ui_snapshot.py --diff before.json after.json
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def collect():
    from PyQt6 import QtWidgets, QtGui  # noqa
    import kidsnote_saver as ks

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    os.chdir(ROOT)
    w = ks.KidsnoteApp()
    w.show()
    app.processEvents()

    data = {"app_version": ks.APP_VERSION, "window": {"w": w.width(), "h": w.height()}, "widgets": {}, "clipped": []}

    named = {
        "status_label": w.status_label, "progress_bar": w.progress_bar,
        "diag_btn": w.diag_btn, "feedback_btn": w.feedback_btn,
        "login_btn": w.login_btn, "load_btn": w.load_btn,
        "download_btn": w.download_btn, "stop_btn": w.stop_btn, "pause_btn": w.pause_btn,
        "pdf_radio": w.pdf_radio, "photo_radio": w.photo_radio, "both_radio": w.both_radio,
        "chk_exclude_video": w.chk_exclude_video,
        "folder_individual_radio": w.folder_individual_radio,
        "folder_single_radio": w.folder_single_radio,
        "overwrite_allow_radio": w.overwrite_allow_radio,
        "overwrite_skip_radio": w.overwrite_skip_radio,
        "period_combo": w.period_combo, "child_combo": w.child_combo,
        "table": w.table, "dir_input": w.dir_input,
    }
    for name, obj in named.items():
        hint = obj.sizeHint()
        entry = {
            "text": obj.text() if hasattr(obj, "text") and not hasattr(obj, "currentText") else None,
            "w": obj.width(), "h": obj.height(),
            "hint_w": hint.width(), "hint_h": hint.height(),
            "enabled": obj.isEnabled(),
            "clipped": obj.width() < hint.width(),
        }
        data["widgets"][name] = entry
        if entry["clipped"]:
            data["clipped"].append(name)

    data["period_items"] = [w.period_combo.itemText(i) for i in range(w.period_combo.count())]
    data["period_current"] = w.period_combo.currentText()
    data["table_headers"] = [w.table.horizontalHeaderItem(i).text() for i in range(w.table.columnCount())]
    data["save_dir"] = w.dir_input.text()

    # 상태 문구 말줄임 동작
    long_msg = "다운로드 중 (50/681) · 약 6분 40초 남음: 오늘은 바깥놀이를 다녀왔어요 친구들과 함께 즐겁게"
    w._set_status_text(long_msg)
    app.processEvents()
    data["status_long_shown"] = w.status_label.text()
    data["status_elided"] = w.status_label.text() != long_msg
    return data


def diff(a_path, b_path):
    a = json.load(open(a_path, encoding="utf-8"))
    b = json.load(open(b_path, encoding="utf-8"))
    print(f"창 크기 : {a['window']} -> {b['window']}")
    print(f"잘린 위젯: {a['clipped']} -> {b['clipped']}")
    if b["clipped"]:
        print("  *** 전환 후 잘린 위젯이 있습니다")
    print()
    print(f"{'위젯':28} {'before(w/hint)':>18} {'after(w/hint)':>18}  상태")
    for name in a["widgets"]:
        x, y = a["widgets"][name], b["widgets"].get(name)
        if not y:
            print(f"{name:28} {'':>18} {'사라짐':>18}  ***")
            continue
        mark = "CLIP" if y["clipped"] else ("변경" if (x["w"], x["h"]) != (y["w"], y["h"]) else "")
        print(f"{name:28} {x['w']:>7}/{x['hint_w']:<10} {y['w']:>7}/{y['hint_w']:<10}  {mark}")
    print()
    for key in ("period_items", "period_current", "table_headers", "status_elided"):
        if a.get(key) != b.get(key):
            print(f"※ {key} 달라짐:\n   before={a.get(key)}\n   after ={b.get(key)}")
    print("\n잘린 위젯 없음 -> OK" if not b["clipped"] else "\n확인 필요")


if __name__ == "__main__":
    if "--diff" in sys.argv:
        i = sys.argv.index("--diff")
        diff(sys.argv[i + 1], sys.argv[i + 2])
    else:
        out = sys.argv[1] if len(sys.argv) > 1 else "snapshot.json"
        d = collect()
        with open(out, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        print(f"기록 완료: {out}")
        print(f"  창 {d['window']['w']}x{d['window']['h']}, 잘린 위젯 {len(d['clipped'])}개 {d['clipped']}")
