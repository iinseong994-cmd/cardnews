#!/usr/bin/env python3
"""
book_theme.py — 책 표지 색 → 카드 배경·글자색

표지는 금색인데 카드 배경이 파란색이면 따로 논다.
표지에서 제일 눈에 띄는 색 하나를 뽑아 그 색조로 카드 전체를 맞춘다.

만드는 것은 CSS 한 덩어리다. 테마 CSS 뒤에 붙어서 색 변수만 덮어쓴다.
자리·크기는 건드리지 않으므로 어떤 테마에 붙여도 레이아웃이 깨지지 않는다.
"""

import colorsys
from pathlib import Path

from PIL import Image


def _hex(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


def dominant_hue(path, boxes=8):
    """표지에서 '색이라고 할 만한' 색 하나. (hue, saturation) 을 돌려준다.

    가장 넓은 면적이 아니라 **가장 눈에 띄는 색**을 고른다.
    표지는 흰 여백이 넓은 경우가 많아서 면적만 보면 늘 회색이 나온다.
    """
    im = Image.open(path).convert("RGB")
    im.thumbnail((160, 160))
    im = im.quantize(colors=boxes, method=Image.MEDIANCUT).convert("RGB")

    best = None
    for n, (r, g, b) in (im.getcolors(boxes * 4) or []):
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if s < 0.18 or l < 0.12 or l > 0.92:
            continue                      # 흰색·검정·회색은 색조가 없다
        score = n * (0.4 + s)             # 넓이 × 선명함
        if best is None or score > best[0]:
            best = (score, h, s)

    if best is None:                      # 무채색 표지 — 원래 테마 색을 쓴다
        return None
    return best[1], min(0.9, max(0.35, best[2]))


# 표지 이미지는 투명 PNG 다. 잘라 채우지 말고 통째로 보여야 하고,
# 액자처럼 보이는 모서리·그림자도 없어야 한다 (그림자는 PNG 에 그려져 있다).
CUTOUT_CSS = """/* 책 표지는 배경 없이 그림만 */
.slide--cover .coverphoto, .slide--photo .bleed {
  background-size: contain; background-repeat: no-repeat; background-position: center;
  background-color: transparent;
  box-shadow: none; border-radius: 0;
}
"""


def build_css(cover_path):
    """표지 → 카드 CSS. 무채색 표지면 색은 그대로 두고 모양만 잡는다."""
    got = dominant_hue(cover_path)
    if not got:
        return CUTOUT_CSS
    h, s = got

    ink = _hex(h, min(0.42, s * 0.6), 0.17)      # 본문 진한 색
    ink2 = _hex(h, min(0.30, s * 0.5), 0.44)     # 보조 글자
    line = _hex(h, min(0.34, s * 0.5), 0.84)     # 테두리
    chip = _hex(h, min(0.52, s * 0.7), 0.34)     # 알약 글자
    acc = _hex(h, s, 0.44)                       # 강조
    acc2 = _hex(h, min(0.8, s * 0.9), 0.72)

    bg1 = _hex(h, min(0.45, s * 0.62), 0.905)    # 배경 위
    bg2 = _hex(h, min(0.32, s * 0.45), 0.955)    # 가운데
    bg3 = _hex(h, min(0.18, s * 0.3), 0.988)     # 아래

    mega1 = _hex(h, s, 0.56)                     # 표지 큰 글씨 그라데이션
    mega2 = _hex(h, min(0.95, s * 1.05), 0.33)

    return CUTOUT_CSS + f"""
/* 표지 색에서 뽑은 팔레트 */
:root, body {{
  --ink: {ink}; --ink-2: {ink2}; --line: {line};
  --chip-bg: #FFFFFF; --chip-ink: {chip};
  --accent: {acc}; --accent-2: {acc2};
}}
.slide {{
  background:
    radial-gradient(900px 620px at 78% 12%, rgba(255,255,255,.95), rgba(255,255,255,0) 70%),
    linear-gradient(178deg, {bg1} 0%, {bg2} 44%, {bg3} 100%) !important;
}}
.slide--cover .mega {{
  background: linear-gradient(180deg, {mega1} 0%, {mega2} 100%);
  -webkit-background-clip: text; background-clip: text;
}}
.band {{ border-top-color: var(--line); }}
/* 페이지 번호는 테마에 파란색이 박혀 있어서 따로 맞춰준다 */
.page, .page--float, .page--onphoto {{ color: {ink2}; opacity: .62; }}
.disclosure {{ color: {ink2}; }}
"""


def apply(output_dir):
    """book.json 폴더 → slides.json 에 넣을 CSS 문자열. 표지가 없으면 빈 문자열."""
    cover = Path(output_dir) / "cover.jpg"
    if not cover.exists():
        return ""
    try:
        return build_css(cover)
    except Exception:
        return ""                          # 색 못 뽑아도 카드는 나와야 한다


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(apply(sys.argv[1]) or "(무채색 표지 — 테마 기본색 유지)")
