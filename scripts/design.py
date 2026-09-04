#!/usr/bin/env python3
"""
design.py — slides.json 의 "design" 값 → 덮어쓰기 CSS

테마 CSS는 그대로 두고 이 CSS를 뒤에 붙여 값만 바꾼다.
색은 테마·팔레트가 담당하므로 여기서는 건드리지 않는다.

조절 가능한 것
  label      계정 라벨 (@handle) — 문구·위치
  titleScale 제목 크기 %
  bodyScale  본문 크기 %
  pad        좌우 여백 가감 (px)
  page       페이지 번호 표시 여부

⚠️ 글자 크기는 반드시 **절대 px** 로 낸다.
   `calc(1em * 0.9)` 는 부모 기준이라 152px 제목이 14px 가 되어버린다.
   그래서 테마별 기준 크기를 아래에 적어두고 곱해서 쓴다.
   테마 CSS에서 폰트 크기를 바꾸면 이 표도 같이 고쳐야 한다.
"""

DEFAULTS = {
    "label": "",
    "labelPos": "bottom",   # top | bottom
    "titleScale": 100,
    "bodyScale": 100,
    "pad": 0,
    "page": True,
}

# 테마별: 선택자 → 기준 font-size(px)
THEMES = {
    "frost": {
        "pad": ".pad",
        "title": {".sec": 68, ".cta h1": 84, ".slide--cover .mega": 152, ".band h2": 50},
        "body": {".list li": 38, ".spec dd": 36, ".spec dt": 30, ".quotes li p": 33,
                 ".quotes--1 li p": 46, ".band .sub": 26, ".pad .sub": 28,
                 ".slide--cover .mega-sub": 31},
    },
    "bold": {
        "pad": ".pad",
        "title": {".statement h1": 94, ".body h2": 74, ".quotes h2": 54,
                  ".cta h1": 90, ".band h2": 52},
        "body": {".body li": 39, ".quotes li p": 37, ".quotes--1 li p": 58,
                 ".band .sub": 27, ".statement .sub": 33},
    },
    "simple": {
        "pad": ".hook-box, .body-box, .quotes-box, .cta-box",
        "title": {".hook-box h1": 96, ".body-box h2": 76, ".quotes-box h2": 54,
                  ".review-title": 58, ".cta-box h1": 92, ".photo-caption h2": 54},
        "body": {".body-box li": 40, ".quotes-box li p": 38, ".quotes-box--1 li p": 60,
                 ".hook-box .sub": 31, ".photo-caption .sub": 27},
    },
}

# 테마별 .pad 기본 좌우 여백(px) — pad 가감의 기준
BASE_PAD = {"frost": 84, "bold": 88, "simple": 96}


def _num(v, fallback=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return fallback


def _scale_rules(sizes, scale):
    if scale == 100:
        return []
    return [f"{sel} {{ font-size: {round(px * scale / 100)}px; }}"
            for sel, px in sizes.items()]


def build_css(theme, design):
    """design dict → 덮어쓰기 CSS. 기본값이면 빈 문자열."""
    if not design:
        return ""
    d = {**DEFAULTS, **design}
    t = THEMES.get(theme)
    if not t:
        return ""

    out = []

    pad = _num(d["pad"])
    if pad:
        base = BASE_PAD.get(theme, 84)
        out.append(f'{t["pad"]} {{ left: {base + pad:.0f}px; right: {base + pad:.0f}px; }}')

    out += _scale_rules(t["title"], _num(d["titleScale"], 100))
    out += _scale_rules(t["body"], _num(d["bodyScale"], 100))

    if d["label"]:
        pos = "top: 42px;" if d["labelPos"] == "top" else "bottom: 42px;"
        out.append(
            ".slide-label { position:absolute; " + pos + " left:0; right:0; text-align:center;"
            " font-size:22px; font-weight:600; letter-spacing:.03em; opacity:.5; z-index:5; }")
        if d["labelPos"] == "bottom" and d["page"]:
            out.append(".page, .page--float { bottom: 84px; }")

    if not d["page"]:
        out.append(".page, .page--float { display: none !important; }")

    return "\n".join(out)
