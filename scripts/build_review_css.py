#!/usr/bin/env python3
"""
build_review_css.py — PPTX 템플릿 → styles_review.css

**좌표를 손으로 옮기지 않는다.** 눈으로 베끼면 반드시 어긋난다.
PPT 파일에서 도형의 자리·크기·글자 크기·색을 그대로 읽어 CSS 를 찍어낸다.

    python scripts/build_review_css.py

원본:  templates/source/book_review_cardnews_6themes.pptx
결과:  templates/styles_review.css

PPT 는 pt, CSS 는 px 이라 **4/3** 을 곱한다 (11.25인치 = 1080px → 96dpi).
템플릿 PPT 가 바뀌면 이 스크립트만 다시 돌리면 된다.
"""

import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
PPTX = ROOT / "templates" / "source" / "book_review_cardnews_6themes.pptx"
OUT = ROOT / "templates" / "styles_review.css"

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS = {"a": A, "p": P}
EMU = 914400
DPI = 96.0
PT2PX = 4 / 3

# 1번 테마의 색 → CSS 변수. 나머지 테마는 변수만 갈아끼운다.
COLORVAR = {
    "#F3F0E8": "var(--paper)",
    "#17201C": "var(--ink)",
    "#173F31": "var(--deep)",
    "#A14938": "var(--accent)",
    "#E4DDD0": "var(--soft)",
    "#DFD5C6": "var(--note)",
}

# 도형이 나오는 순서 → CSS 선택자.
# 순서는 PPT 안에서 고정이다 (readppt/geom 로 확인함).
ROW = lambda t, i: [f".slide--{t} .r{i}-dot", f".slide--{t} .r{i}-num",
                    f".slide--{t} .r{i}-h", f".slide--{t} .r{i}-p",
                    f".slide--{t} .r{i}-line"]

MAP = {
    1: [".hdr-no", ".hdr-kind", ".rule-top",
        ".cv-sub", ".cv-title", ".cv-book", ".cv-book-title", ".cv-dot",
        ".cv-author", ".cv-rating", ".foot", ".rule-bot"],
    2: [None, None, None,
        ".slide--oneline .sec", ".mark", ".big", ".rule-short", ".body",
        ".note", ".note-text", None, None],
    3: [None, None, None, ".slide--ideas .sec"]
       + ROW("ideas", 1) + ROW("ideas", 2) + ROW("ideas", 3) + [None, None],
    4: [None, None, None,
        ".slide--insight .sec", ".rule-accent", ".body--lead",
        ".callout", ".callout-text", ".strong", None, None],
    5: [None, None, None,
        ".qbox", ".mark--in", ".big--in", ".rule-short--in", ".who",
        ".body--foot", None, None],
    6: [None, None, None,
        ".slide--afterword .sec", ".body--wide", ".rule-accent--mid",
        ".body--wide2", ".sign", None, None],
    7: [None, None, None, ".slide--foryou .sec"]
       + ROW("foryou", 1) + ROW("foryou", 2) + ROW("foryou", 3) + [None, None],
    8: [None, None, None,
        ".cl-lead", ".cl-ask", ".rule-mid", ".cl-stars", ".cl-score",
        ".cl-foot", None, None],
}

ALIGN = {"ctr": "center", "r": "right", "l": "left"}


def px(v):
    return round(int(v) / EMU * DPI)


def read_shapes(root):
    out = []
    for sp in root.iter("{%s}sp" % P):
        xf = sp.find(".//a:xfrm", NS)
        box = None
        if xf is not None:
            o, e = xf.find("a:off", NS), xf.find("a:ext", NS)
            if o is not None and e is not None:
                box = (px(o.get("x")), px(o.get("y")), px(e.get("cx")), px(e.get("cy")))
        f = sp.find("p:spPr/a:solidFill/a:srgbClr", NS)
        fill = "#" + f.get("val").upper() if f is not None else None
        g = sp.find(".//a:prstGeom", NS)
        geom = g.get("prst") if g is not None else "rect"

        size = weight = color = algn = None
        lines = 0
        for p_ in sp.iter("{%s}p" % A):
            runs = [r for r in p_.iter("{%s}r" % A)]
            if not runs:
                continue
            lines += 1
            if size is None:
                pPr = p_.find("a:pPr", NS)
                algn = pPr.get("algn") if pPr is not None else None
                rPr = runs[0].find("a:rPr", NS)
                if rPr is not None:
                    if rPr.get("sz"):
                        size = int(rPr.get("sz")) / 100
                    weight = 800 if rPr.get("b") == "1" else 500
                    c = rPr.find("a:solidFill/a:srgbClr", NS)
                    if c is not None:
                        color = "#" + c.get("val").upper()
        out.append({"box": box, "fill": fill, "geom": geom, "size": size,
                    "weight": weight, "color": color, "algn": algn, "lines": lines})
    return out


def rule(sel, s, *, absolute=True, with_size=True):
    b = s["box"]
    d = []
    if absolute and b:
        d.append("position: absolute")
        d.append("left: %dpx" % b[0])
        d.append("top: %dpx" % b[1])
        d.append("width: %dpx" % b[2])
    if s["fill"]:
        # 얇은 줄은 높이가 곧 굵기다. 글자 상자는 높이를 고정하면 넘칠 때 잘린다.
        if b and (b[3] <= 6 or s["size"] is None):
            d.append("height: %dpx" % b[3])
        d.append("background: %s" % COLORVAR.get(s["fill"], s["fill"]))
        if s["geom"] == "ellipse":
            d.append("border-radius: 50%")
    if with_size and s["size"]:
        d.append("font-size: %dpx" % round(s["size"] * PT2PX))
        d.append("font-weight: %d" % (s["weight"] or 500))
        if s["color"]:
            d.append("color: %s" % COLORVAR.get(s["color"], s["color"]))
        if s["algn"] in ALIGN and s["algn"] != "l":
            d.append("text-align: %s" % ALIGN[s["algn"]])
        # 줄간격은 PPT 파일에 값이 없다 (단일 간격). 큰 글씨는 좁게, 본문은 넓게.
        d.append("line-height: %s" % ("1.32" if s["size"] >= 30 else "1.62"))
        d.append("letter-spacing: %s" % ("-.03em" if s["size"] >= 30 else "-.01em"))
    return "%s { %s; }" % (sel, "; ".join(d))


HEAD = """/* ── 북리뷰 테마 — PPTX 템플릿에서 자동으로 뽑은 CSS ──────────────────
   ⚠️ 이 파일을 직접 고치지 마라. 다음 명령으로 다시 만든다.
        python scripts/build_review_css.py
   원본: templates/source/book_review_cardnews_6themes.pptx
   자리·크기·글자 크기·색은 전부 그 PPT 에서 읽은 값이다 (pt × 4/3 = px). */

:root {
  --paper:  #F3F0E8; --ink: #17201C; --deep: #173F31;
  --accent: #A14938; --soft: #E4DDD0; --note: #DFD5C6;
}
body.pal-navy   { --paper:#F5F2EA; --ink:#101B31; --deep:#172B55; --accent:#D94C3D; }
body.pal-cobalt { --paper:#F6F2E8; --ink:#111111; --deep:#1947D1; --accent:#FF6B35; }
body.pal-sepia  { --paper:#EDE3CF; --ink:#33291E; --deep:#70533B; --accent:#6B7651; }
body.pal-wine   { --paper:#F3EAE5; --ink:#25191B; --deep:#6C1F32; --accent:#B98282; }
body.pal-mist   { --paper:#EEF4F5; --ink:#20282C; --deep:#7397A6; --accent:#CADDE2; }

* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: 'Pretendard Variable', Pretendard, 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
  -webkit-font-smoothing: antialiased; color: var(--ink);
}
.slide { position: relative; width: 1080px; height: 1350px; overflow: hidden; background: var(--paper); }
mark { background: none; color: var(--accent); }
/* PPT 는 도형을 겹쳐 놓는 방식이라, HTML 도 칸을 중첩하지 않고 나란히 둔다.
   글자 상자는 PPT 에서 모두 위쪽 정렬(anchor="t")이라 세로 가운데 맞춤을 쓰지 않는다. */
.cv-book { display: flex; align-items: center; justify-content: center; }
.cv-book.cv-book--img { background: none; }   /* 자동 생성 규칙보다 세게 */
.cv-img { max-width: 100%; max-height: 100%; object-fit: contain;
          filter: drop-shadow(0 18px 34px rgba(0,0,0,.28)); }
"""


def main():
    if not PPTX.exists():
        raise SystemExit("템플릿 PPT 를 찾지 못했습니다: %s" % PPTX)

    with ZipFile(PPTX) as z:
        slides = {n: ET.fromstring(z.read("ppt/slides/slide%d.xml" % n))
                  for n in range(1, 9)}

    out = [HEAD]
    for n in range(1, 9):
        shapes = read_shapes(slides[n])
        sels = MAP[n]
        if len(shapes) != len(sels):
            print("  [주의] slide %d — 도형 %d개인데 선택자는 %d개"
                  % (n, len(shapes), len(sels)))
        out.append("\n/* ── slide %02d ── */" % n)
        for sel, s in zip(sels, shapes):
            if sel and s["box"]:
                out.append(rule(sel, s))

    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("  %s (%d줄)" % (OUT, len(out)))


if __name__ == "__main__":
    main()
