#!/usr/bin/env python3
"""
find_bg_boxes.py — 배경 사진에서 '글자 넣을 빈 칸' 찾기

templates/backgrounds/ 의 배경 96장은 저마다 빈 칸 위치가 다르다.
그 칸을 못 찾으면 글자가 사진 위에 아무렇게나 얹힌다.

    python scripts/find_bg_boxes.py            # 전부 찾아서 boxes.json 에 저장
    python scripts/find_bg_boxes.py --check    # 찾은 칸을 그려서 눈으로 확인

⚠️ 처음엔 다 실패했다. **종이 결과 그림자를 무늬로 오해**해서다.
   살짝 흐리게 만든 뒤 재야 잡힌다. 아래 GaussianBlur 를 빼면 안 된다.

24장으로 시험했을 때 20장은 제자리를 잡았고 4장은 빗나갔다
(창문을 빈 칸으로 보거나, 커튼 사이 좁은 틈을 잡는다).
빗나간 것은 boxes.json 을 손으로 고친다.
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


def blank_mask(im):
    """밝고 무늬 없는 곳 = 글자 놓을 수 있는 곳"""
    g = (im.convert("L").resize((SW, SH), Image.LANCZOS)
           .filter(ImageFilter.GaussianBlur(2.2)))
    edge = g.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(3))
    lum = ImageStat.Stat(g).mean[0]
    th = max(118, lum * 0.98)
    pg, pe = g.load(), edge.load()
    return [[1 if (pg[x, y] >= th and pe[x, y] <= 7) else 0
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
    im = Image.open(path)
    area, x, y, w, h = largest_rect(blank_mask(im))
    fx, fy = CARD_W / SW, CARD_H / SH
    return {"x": round(x * fx), "y": round(y * fy),
            "w": round(w * fx), "h": round(h * fy),
            "fill": round(area / (SW * SH), 3)}


def main():
    check = "--check" in sys.argv
    out = {}
    weak = []
    for d in sorted(p for p in BG.iterdir() if p.is_dir()):
        for f in sorted(d.glob("*.jpg")):
            key = "%s/%s" % (d.name, f.stem)
            box = find(f)
            out[key] = box
            if box["fill"] < MIN_AREA:
                weak.append(key)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("  %d장 → %s" % (len(out), OUT))
    if weak:
        print("  손봐야 할 것 %d장: %s" % (len(weak), ", ".join(weak)))

    if check:
        keys = list(out)
        cols = 8
        rows = (len(keys) + cols - 1) // cols
        W, H = 150, 188
        sheet = Image.new("RGB", (W * cols + 8 * (cols + 1),
                                  H * rows + 8 * (rows + 1)), (238, 240, 244))
        for i, k in enumerate(keys):
            t, n = k.split("/")
            im = Image.open(BG / t / (n + ".jpg")).copy()
            b = out[k]
            ImageDraw.Draw(im).rectangle(
                [b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]],
                outline=(255, 60, 0), width=10)
            sheet.paste(im.resize((W, H), Image.LANCZOS),
                        (8 + (i % cols) * (W + 8), 8 + (i // cols) * (H + 8)))
        p = BG / "boxes_check.png"
        sheet.save(p)
        print("  확인용 그림 → %s" % p)


if __name__ == "__main__":
    main()
