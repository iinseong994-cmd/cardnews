#!/usr/bin/env python3
"""
bg_theme.py — 배경 사진 테마: 카드마다 배경과 '글자 넣을 칸'을 붙여준다

배경은 테마마다 8장인데 우리 카드는 10장이다.
그래서 두 장은 다시 쓴다 (인용 배경과 본문 배경).

칸의 자리는 templates/backgrounds/boxes.json 이 갖고 있다.
좌표를 CSS 에 못 박을 수 없어서 (배경마다 다르다) 슬라이드 데이터에 실어 보낸다.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BG = ROOT / "templates" / "backgrounds"

# 우리 10장 → 배경 8장.
#   1 표지 2 한문장 3 하는말 4 책의문장 5 지은이
#   6 추천사 7 이런분께 8 독자리뷰 9 읽고나면 10 마무리
# 8번은 4번(인용) 배경을, 9번은 5번(본문) 배경을 다시 쓴다.
CARD_BG = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 4, 9: 5, 10: 8}

_boxes = None


def boxes():
    global _boxes
    if _boxes is None:
        f = BG / "boxes.json"
        _boxes = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    return _boxes


def themes():
    f = BG / "themes.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def apply(data, theme_id):
    """slides 각 장에 배경 그림과 글자 칸을 붙인다."""
    b = boxes()
    for sl in data.get("slides", []):
        n = CARD_BG.get(sl.get("no"), 1)
        key = "%s/%02d" % (theme_id, n)
        img = BG / theme_id / ("%02d.jpg" % n)
        sl["image_path"] = str(img) if img.exists() else None
        sl["box"] = b.get(key)
    return data
