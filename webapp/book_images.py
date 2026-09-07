#!/usr/bin/env python3
"""
book_images.py — 책 표지 한 장 → 카드뉴스에 쓸 이미지들

상품과 달리 책은 사진이 표지 한 장뿐이다.
그 한 장을 잘라 쓰면 제목이 잘리므로, 표지는 **절대 자르지 않고**
같은 표지를 흐리게 깐 배경 위에 통째로 얹는다.

만드는 것
  card_images/cover.jpg   940×1536  표지 슬라이드 오른쪽 칸 (470×768 의 2배)
  card_images/wide.jpg    1080×1350 표지를 가운데 놓은 전면 컷
"""

from pathlib import Path

from PIL import Image, ImageFilter, ImageEnhance

COVER_BOX = (940, 1536)     # 표지 슬라이드 칸 (실제 470×768 의 2배)
WIDE_BOX = (1080, 1050)     # 사진 카드의 사진 칸 (.bleed) — 카드 전체 높이가 아니다
MARGIN = 0.86               # 칸 안에서 표지가 차지할 비율

# ⚠️ WIDE_BOX 는 styles_frost.css 의 `.bleed` 크기와 같아야 한다.
#    1350(카드 전체 높이)으로 만들면 background-size:cover 가 위아래를 잘라서
#    책 제목이 날아간다. 테마 CSS 에서 .bleed 를 고치면 여기도 같이 고칠 것.


def _backdrop(img, size, blur=52, wash=0.62, sat=0.55):
    """같은 표지를 크게 흐려서 배경으로 깐다.

    어둡게 깔면 밝은 테마에서 탁해 보인다.
    그래서 흰색을 섞어(wash) 파스텔로 만들고 채도도 낮춘다.
    """
    w, h = size
    ratio = max(w / img.width, h / img.height)
    big = img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
                     Image.LANCZOS)
    left = (big.width - w) // 2
    top = (big.height - h) // 2
    bg = big.crop((left, top, left + w, top + h)).filter(ImageFilter.GaussianBlur(blur))
    bg = ImageEnhance.Color(bg).enhance(sat)
    return Image.blend(bg.convert("RGB"), Image.new("RGB", size, (255, 255, 255)), wash)


def _fit(img, box, margin=MARGIN):
    """표지를 칸 안에 통째로 들어가게 줄인다 (자르지 않는다)"""
    bw, bh = box
    ratio = min(bw * margin / img.width, bh * margin / img.height)
    return img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
                      Image.LANCZOS)


def _shadow(canvas, box_xy, size, blur=30, alpha=72):
    """표지 아래 그림자. 투명 캔버스 위에 직접 그린다."""
    x, y = box_xy
    w, h = size
    layer = Image.new("L", canvas.size, 0)
    layer.paste(255, (x + 6, y + 14, x + w - 6, y + h + 18))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    layer = layer.point(lambda v: int(v * alpha / 255))
    dark = Image.new("RGBA", canvas.size, (14, 20, 28, 0))
    dark.putalpha(layer)
    canvas.alpha_composite(dark)


def _compose(cover, box, margin=MARGIN, center_y=0.5):
    """표지 뒤에 아무것도 깔지 않는다.

    흐린 배경을 깔면 카드 안에 액자가 하나 더 생긴 것처럼 보인다.
    투명하게 두면 카드 바탕(테마 색)이 그대로 비쳐서 훨씬 깔끔하다.
    그림자는 CSS 로 못 주니 여기서 그려 넣는다.
    """
    canvas = Image.new("RGBA", box, (0, 0, 0, 0))
    fit = _fit(cover, box, margin).convert("RGBA")
    x = (box[0] - fit.width) // 2
    y = int((box[1] - fit.height) * center_y)
    _shadow(canvas, (x, y), fit.size)
    canvas.alpha_composite(fit, (x, y))
    return canvas


# 이름 → (칸 크기, 표지가 차지할 비율, 세로 위치)
# 투명 배경이 필요하므로 PNG 다.
VARIANTS = {
    "cover.png": (COVER_BOX, 0.90, 0.50),
    "wide.png":  (WIDE_BOX,  0.86, 0.50),
}


def build_book_images(output_dir):
    """output_dir/cover.jpg → output_dir/card_images/*.png. 만든 파일 경로 목록 반환."""
    out = Path(output_dir)
    src = out / "cover.jpg"
    if not src.exists():
        return []

    dest = out / "card_images"
    dest.mkdir(exist_ok=True)
    # 예전 방식(흐린 배경 깔린 jpg)이 남아 있으면 AI 가 그걸 골라 쓴다
    for old in ("cover.jpg", "wide.jpg"):
        (dest / old).unlink(missing_ok=True)

    cover = Image.open(src).convert("RGB")
    made = []
    for name, (box, margin, cy) in VARIANTS.items():
        p = dest / name
        _compose(cover, box, margin, cy).save(p, "PNG")
        made.append(p)
    return made


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for p in build_book_images(sys.argv[1]):
        im = Image.open(p)
        print("  %s  %dx%d" % (p.name, im.width, im.height))
