#!/usr/bin/env python3
"""
find_bg_boxes.py — 배경 사진에서 '글자 넣을 빈 칸' 찾기

templates/backgrounds/ 의 배경 96장은 저마다 빈 칸 위치가 다르다.
그 칸을 못 찾으면 글자가 사진 위에 아무렇게나 얹힌다.

    python scripts/find_bg_boxes.py            # 전부 찾아서 boxes.json 에 저장
    python scripts/find_bg_boxes.py --check    # 찾은 칸을 그려서 눈으로 확인

⚠️ 처음엔 다 실패했다. **종이 결과 그림자를 무늬로 오해**해서다.
   살짝 흐리게 만든 뒤 재야 잡힌다. 아래 GaussianBlur 를 빼면 안 된다.

찾는 순서
  1) 밝고 무늬 없는 곳 (흰 종이)                    → 90장
  2) 없으면 밝기를 안 따지고 다시 (진한 남색 판)      →  2장
  3) 그래도 없으면 반투명 띠를 깐다 (실루엣 콜라주)   →  4장

3) 이 중요하다. 빈 칸이 아예 없는 배경이 있는데, 억지로 글자를 얹으면 안 읽힌다.
띠를 깔면 어떤 배경이든 확실히 읽힌다.

boxes.json 의 각 항목
  x·y·w·h  글자 넣을 자리
  dark     그 자리가 어두운가 (참이면 흰 글씨)
  mode     "blank" 빈 칸에 바로 / "band" 반투명 띠를 깔고
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageStat

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
BG = ROOT / "templates" / "backgrounds"
OUT = BG / "boxes.json"

CARD_W, CARD_H = 1080, 1350
SW, SH = 216, 270          # 줄여서 계산 — 빠르고 잡티에 덜 흔들린다
MIN_AREA = 0.06            # 카드의 6% 보다 작으면 못 찾은 것으로 본다


def small(im):
    return (im.convert("L").resize((SW, SH), Image.LANCZOS)
              .filter(ImageFilter.GaussianBlur(2.2)))


def blank_mask(g, bright_only=True):
    """무늬 없는 곳 = 글자 놓을 수 있는 곳.

    bright_only=True 면 밝은 곳만 (흰 종이).
    False 면 밝기를 안 따진다 — **진한 남색 판 위에 흰 글씨**를 얹는 배경이 있다.
    그런 배경은 밝은 곳만 찾으면 아무것도 못 찾는다.
    """
    edge = g.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(3))
    th = max(118, ImageStat.Stat(g).mean[0] * 0.98)
    pg, pe = g.load(), edge.load()
    return [[1 if (pe[x, y] <= 7 and (not bright_only or pg[x, y] >= th)) else 0
             for x in range(SW)] for y in range(SH)]


def largest_rect(m):
    """1 로만 채워진 가장 큰 직사각형 (히스토그램 방식)"""
    best = (0, 0, 0, 0, 0)
    h = [0] * SW
    for y in range(SH):
        for x in range(SW):
            h[x] = h[x] + 1 if m[y][x] else 0
        stack = []
        for x in range(SW + 1):
            cur = h[x] if x < SW else 0
            start = x
            while stack and stack[-1][1] >= cur:
                sx, sh = stack.pop()
                if sh * (x - sx) > best[0]:
                    best = (sh * (x - sx), sx, y - sh + 1, x - sx, sh)
                start = sx
            stack.append((start, cur))
    return best


def find(path):
    """빈 칸을 찾는다. 없으면 반투명 띠를 깔 자리를 돌려준다.

    빈 칸이 없는 배경이 있다 (실루엣 콜라주 같은 것).
    그런 배경에 억지로 글자를 얹으면 안 읽힌다.
    그래서 못 찾으면 mode="band" 로 표시하고, 렌더할 때 반투명 띠를 깔고 그 위에 쓴다.
    이러면 96장 전부 확실히 읽힌다.
    """
    im = Image.open(path)
    g = small(im)
    area, x, y, w, h = largest_rect(blank_mask(g, True))
    if area / (SW * SH) < MIN_AREA:
        # 밝은 빈칸이 없는 배경이다. 밝기를 안 따지고 다시 찾는다.
        area, x, y, w, h = largest_rect(blank_mask(g, False))

    fill = area / (SW * SH)
    fx, fy = CARD_W / SW, CARD_H / SH

    if fill < MIN_AREA:
        # 글자 놓을 데가 없다 → 아래쪽에 반투명 띠
        return {"x": 90, "y": 810, "w": CARD_W - 180, "h": 400,
                "fill": round(fill, 3), "dark": True, "mode": "band"}

    lum = ImageStat.Stat(g.crop((x, y, x + max(w, 1), y + max(h, 1)))).mean[0]
    return {"x": round(x * fx), "y": round(y * fy),
            "w": round(w * fx), "h": round(h * fy),
            "fill": round(fill, 3),
            "dark": lum < 120, "mode": "blank"}


def main():
    check = "--check" in sys.argv
    out = {}
    weak = []
    for d in sorted(p for p in BG.iterdir() if p.is_dir()):
        for f in sorted(d.glob("*.jpg")):
            key = "%s/%s" % (d.name, f.stem)
            box = find(f)
            out[key] = box
            if box["mode"] == "band":
                weak.append(key)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("  %d장 → %s" % (len(out), OUT))
    if weak:
        print("  빈 칸이 없어 반투명 띠를 쓸 것 %d장: %s" % (len(weak), ", ".join(weak)))

    if check:
        # 이상한 게 있으면 사용자가 짚어줘야 한다. 그러려면 **이름이 보여야** 한다.
        contact(out, list(out), BG / "boxes_check.png", cols=8)

        # 의심스러운 것만 모아 크게 — 칸이 너무 작거나 지나치게 길쭉한 것
        odd = [k for k, b in out.items()
               if b["mode"] == "band" or b["fill"] < 0.11
               or b["w"] < 240 or b["h"] < 200
               or b["w"] / max(b["h"], 1) > 3 or b["h"] / max(b["w"], 1) > 3.4]
        if odd:
            contact(out, odd, BG / "boxes_odd.png", cols=6, big=True)
            print("  수상한 것 %d장 → %s" % (len(odd), BG / "boxes_odd.png"))


def contact(out, keys, path, cols=8, big=False):
    """찾은 칸을 그려서 한 장에 모은다. 칸마다 이름을 적는다."""
    W, H = (280, 350) if big else (150, 188)
    pad, lab = 8, 22
    rows = (len(keys) + cols - 1) // cols
    sheet = Image.new("RGB", (W * cols + pad * (cols + 1),
                              (H + lab) * rows + pad * (rows + 1)), (238, 240, 244))
    d = ImageDraw.Draw(sheet)
    for i, k in enumerate(keys):
        t, n = k.split("/")
        im = Image.open(BG / t / (n + ".jpg")).copy()
        b = out[k]
        ImageDraw.Draw(im).rectangle(
            [b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]],
            outline=(0, 200, 255) if b.get("dark") else (255, 60, 0), width=10)
        x = pad + (i % cols) * (W + pad)
        y = pad + (i // cols) * (H + lab + pad)
        sheet.paste(im.resize((W, H), Image.LANCZOS), (x, y))
        tag = "%s %s" % (t, n)
        if b["mode"] == "band":
            tag += "  (띠)"
        d.text((x + 2, y + H + 5), tag, fill=(30, 36, 44))
    sheet.save(path)
    print("  확인용 그림 → %s" % path)


if __name__ == "__main__":
    main()
