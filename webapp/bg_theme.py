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


MIN_TEXT_W = 470        # 이보다 좁으면 어절 중간에서 끊긴다
MIN_TEXT_H = 190
MIN_COVER_W = 260       # 표지가 이보다 좁으면 우표만 해진다


def pick_text_box(bs):
    """글자를 넣을 칸을 고른다.

    ⚠️ **제일 큰 칸이 늘 답은 아니다.** 세로로 길고 좁은 칸이 면적은 커도
       거기에 글을 넣으면 '성공한 IT 기 / 업가에서 / 나홀로 아빠 / 로' 처럼
       한 글자씩 끊긴다. 글이 들어갈 만한 너비부터 본다.
    """
    if not bs:
        return None
    ok = [b for b in bs if b["w"] >= MIN_TEXT_W and b["h"] >= MIN_TEXT_H]
    if not ok:
        ok = [b for b in bs if b["w"] >= MIN_TEXT_W]        # 납작해도 넓은 쪽이 낫다
    return max(ok or bs, key=lambda b: b["w"] * b["h"])


def split_stack(bs):
    """줄지어 선 '목록 칸' 을 골라낸다. → (머리 칸, [목록 칸들])

    잡지형 배경은 비슷한 너비의 상자가 세로로 줄지어 있다 (metro·pop·citymap).
    그런 배경은 칸마다 한 줄씩 넣어야 한다. 한 칸에 몰아넣으면 깨알이 된다.

    ⚠️ 맨 위 제목 칸은 **너비가 다르다**. 전부를 한 묶음으로 보고 너비를 재면
       판정이 실패한다 (metro/03 은 900 vs 495 라서 목록이 아니라고 나왔었다).
       그래서 흔한 너비를 기준으로 목록 칸을 먼저 고르고, 나머지를 머리로 본다.
    """
    if len(bs) < 3:
        return None, []
    ws = sorted(b["w"] for b in bs)
    mid = ws[len(ws) // 2]
    body = [b for b in bs if 0.75 <= b["w"] / mid <= 1.33]
    if len(body) < 3:
        return None, []

    # 높이도 비슷해야 목록이다.
    # ⚠️ 이게 없으면 **종이 한 장을 쪼갠 것**을 목록으로 오해한다.
    #    (forest/03 은 230·110·200 처럼 들쭉날쭉한데 너비만 보면 통과해 버린다)
    hs = [b["h"] for b in body]
    if min(hs) / max(hs) < 0.6:
        return None, []

    body.sort(key=lambda b: b["y"])
    for a, c in zip(body, body[1:]):       # 위아래로 안 겹쳐야 한다
        if c["y"] < a["y"] + a["h"] * 0.6:
            return None, []

    # 머리 칸은 목록 **위에** 있는 것을 먼저 쓴다 (제목이 위에 와야 읽힌다).
    # 위에 없으면 남은 칸 중 제일 큰 것을 쓴다. 제목을 버리는 것보다는 낫다.
    rest = [b for b in bs if b not in body]
    above = [b for b in rest if b["y"] + b["h"] <= body[0]["y"] + 40]
    head = (min(above, key=lambda b: b["y"]) if above
            else max(rest, key=lambda b: b["w"] * b["h"]) if rest else None)
    return head, body


def apply(data, theme_id, cover=None):
    """slides 각 장에 배경 그림과 글자 칸을 붙인다.

    cover — 책 표지 그림 경로. 1번 카드의 빈 책에 그대로 얹는다.
    """
    tbl = boxes()
    for sl in data.get("slides", []):
        n = CARD_BG.get(sl.get("no"), 1)
        key = "%s/%02d" % (theme_id, n)
        img = BG / theme_id / ("%02d.jpg" % n)
        sl["image_path"] = str(img) if img.exists() else None

        info = tbl.get(key) or {}
        bs = info.get("boxes") or []
        sl["mode"] = info.get("mode", "band")
        sl["box"] = pick_text_box(bs)

        # 표지 카드 — 배경의 빈 책 자리에 진짜 표지를 얹는다.
        # 글자를 쓰는 것보다 이게 훨씬 자연스럽다.
        # 다만 **세로로 선 칸일 때만** 그렇다. 가로로 납작한 띠에 넣으면 책이 찌그러진다.
        if sl.get("no") == 1 and cover:
            up = [b for b in bs if b["h"] > b["w"] * 1.1 and b["w"] >= MIN_COVER_W]
            if up:
                sl["cover"] = str(cover)
                sl["box"] = max(up, key=lambda b: b["w"] * b["h"])
                continue

        # 목록 카드 — 칸이 줄지어 있으면 한 칸에 한 줄씩
        if sl.get("lines"):
            head, body = split_stack(bs)
            # 머리 칸이 따로 없는데 칸이 남으면 맨 위 칸을 제목 자리로 쓴다
            if head is None and len(body) > len(sl["lines"]):
                head, body = body[0], body[1:]
            if body:
                sl["head_box"] = head
                sl["slots"] = [{"box": b, "text": t}
                               for b, t in zip(body, sl["lines"])]
    return data
