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


MIN_SLOT = 0.012        # 칸 하나가 카드의 1.2% 는 돼야 글자가 들어간다
MAX_SLOTS = 5


def all_rects(g, mask):
    """빈 칸을 큰 것부터 여러 개 찾는다.

    **제일 큰 칸 하나만 찾으면 안 된다.** 흰 상자가 3~4개 놓인 잡지형 배경이 있는데,
    거기에 글을 다 몰아넣으면 작은 칸은 깨알이 되고 큰 칸은 텅 빈다.
    하나 찾을 때마다 그 자리를 지우고 다시 찾는다.
    """
    out = []
    for _ in range(MAX_SLOTS):
        area, x, y, w, h = largest_rect(mask)
        if area / (SW * SH) < MIN_SLOT:
            break
        # 너무 가늘거나 납작한 것은 글자가 안 들어간다
        if w >= 24 and h >= 12 and max(w / h, h / w) <= 9:
            lum = ImageStat.Stat(g.crop((x, y, x + w, y + h))).mean[0]
            out.append({"x": x, "y": y, "w": w, "h": h, "dark": lum < 120})
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                mask[yy][xx] = 0
    return out


def find(path):
    """빈 칸들을 찾는다. 하나도 없으면 반투명 띠를 깔 자리를 돌려준다."""
    im = Image.open(path)
    g = small(im)
    rects = all_rects(g, blank_mask(g, True))
    if not rects:
        # 밝은 빈칸이 없는 배경이다. 밝기를 안 따지고 다시 찾는다.
        rects = all_rects(g, blank_mask(g, False))

    fx, fy = CARD_W / SW, CARD_H / SH
    if not rects:
        # 글자 놓을 데가 없다 → 아래쪽에 반투명 띠
        return {"mode": "band", "boxes": [
            {"x": 90, "y": 810, "w": CARD_W - 180, "h": 400, "dark": True}]}

    # 위에서 아래로 읽는 순서대로 (사람이 보는 순서)
    rects.sort(key=lambda r: (r["y"], r["x"]))
    boxes = [{"x": round(r["x"] * fx), "y": round(r["y"] * fy),
              "w": round(r["w"] * fx), "h": round(r["h"] * fy),
              "dark": r["dark"]} for r in rects]
    return {"mode": "blank", "boxes": boxes}


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
        odd = [k for k, v in out.items()
               if v["mode"] == "band" or len(v["boxes"]) >= 3]
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
        dr = ImageDraw.Draw(im)
        for j, b in enumerate(out[k]["boxes"]):
            dr.rectangle([b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]],
                         outline=(0, 200, 255) if b.get("dark") else (255, 60, 0),
                         width=10)
            dr.text((b["x"] + 16, b["y"] + 10), str(j + 1), fill=(255, 60, 0))
        x = pad + (i % cols) * (W + pad)
        y = pad + (i // cols) * (H + lab + pad)
        sheet.paste(im.resize((W, H), Image.LANCZOS), (x, y))
        tag = "%s %s  칸%d" % (t, n, len(out[k]["boxes"]))
        if out[k]["mode"] == "band":
            tag += " (띠)"
        d.text((x + 2, y + H + 5), tag, fill=(30, 36, 44))
    sheet.save(path)
    print("  확인용 그림 → %s" % path)


if __name__ == "__main__":
    main()
