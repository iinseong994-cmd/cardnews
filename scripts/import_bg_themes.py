#!/usr/bin/env python3
"""
import_bg_themes.py — 배경 PPTX(사진 96장) → 테마별 배경 그림 + 미리보기

이 PPTX 는 앞의 템플릿과 성격이 다르다.
도형·글자가 없고 **슬라이드 한 장이 통짜 사진 한 장**이다.
즉 편집할 판이 아니라 **글자를 얹을 배경**이다.

    python scripts/import_bg_themes.py "<pptx 경로>"

결과
    templates/backgrounds/<테마>/01.jpg ~ 08.jpg   카드 자리별 배경
    webapp/previews/bg_<테마>.png                  테마 고르는 화면용 미리보기
    templates/backgrounds/themes.json              테마 목록 (이름·설명)
"""

import io
import json
import re
import sys
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageFile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
BG = ROOT / "templates" / "backgrounds"
PREV = ROOT / "webapp" / "previews"

PER_THEME = 8

# 표지 사진을 보고 붙인 이름. 순서는 PPT 순서(1~12테마) 그대로다.
THEMES = [
    ("forest",    "숲속 서재",   "초록 벽에 기댄 책과 들꽃"),
    ("metro",     "메트로",      "흑백 건축 + 네이비·레드"),
    ("pop",       "팝 컬러",     "파랑·주황 도형과 책"),
    ("antique",   "고서",        "낡은 종이와 밀랍 봉인"),
    ("velvet",    "벨벳",        "와인빛 천과 마른 꽃"),
    ("seaside",   "창가",        "흰 꽃이 놓인 바다 창가"),
    ("pine",      "침엽수",      "이끼와 전나무 사이의 종이"),
    ("citymap",   "도시 지도",   "항공 사진과 붉은 원"),
    ("arch",      "아치",        "파란 아치와 손에 든 책"),
    ("dryflower", "말린 꽃",     "빛바랜 종이와 눌린 꽃"),
    ("theater",   "극장",        "붉은 커튼과 객석"),
    ("linen",     "린넨",        "흰 커튼 너머 바다"),
]

PREVIEW_W, PREVIEW_H = 360, 450

# 원본 PPT 안에서 파일이 잘려 있는 그림.
# 아래쪽 데이터가 아예 없어서 복구가 안 된다 (회색으로 나온다).
# 같은 테마의 다른 장을 **좌우로 뒤집어** 쓴다. 그냥 복사하면 같은 배경이 두 번 나온다.
#   "테마/번호": 대신 쓸 번호
REPLACE_BROKEN = {
    "arch/04": 2,
}


def slide_images(pptx):
    """슬라이드 순서대로 media 파일 이름을 돌려준다.

    media 폴더 이름순(image10 이 image2 보다 앞)으로 읽으면 순서가 뒤집힌다.
    반드시 슬라이드의 관계 파일을 따라가야 한다.
    """
    out = []
    with ZipFile(pptx) as z:
        names = z.namelist()
        total = len([n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)])
        for i in range(1, total + 1):
            rel = z.read("ppt/slides/_rels/slide%d.xml.rels" % i).decode("utf-8")
            m = re.search(r'Target="/ppt/media/([^"]+)"', rel)
            if not m:
                raise SystemExit("slide %d 에 그림이 없습니다" % i)
            out.append(m.group(1))
    return out


def main():
    pptx = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if not pptx or not pptx.exists():
        raise SystemExit("사용법: python scripts/import_bg_themes.py <pptx 경로>")

    order = slide_images(pptx)
    if len(order) != PER_THEME * len(THEMES):
        print("  [주의] 슬라이드 %d장 — %d테마 × %d장 이 아닙니다"
              % (len(order), len(THEMES), PER_THEME))

    BG.mkdir(parents=True, exist_ok=True)
    PREV.mkdir(parents=True, exist_ok=True)

    meta = []
    with ZipFile(pptx) as z:
        for t, (tid, name, desc) in enumerate(THEMES):
            d = BG / tid
            d.mkdir(exist_ok=True)
            for k in range(PER_THEME):
                idx = t * PER_THEME + k
                if idx >= len(order):
                    break
                # zip 스트림째로 열면 끝이 잘렸다는 오류가 나는 그림이 있다.
                # 통째로 읽어서 넘긴다.
                raw = io.BytesIO(z.read("ppt/media/" + order[idx]))
                try:
                    im = Image.open(raw).convert("RGB")
                except OSError as e:
                    print("  [주의] %s %d번째 그림이 온전하지 않습니다 (%s)"
                          % (tid, k + 1, e))
                    ImageFile.LOAD_TRUNCATED_IMAGES = True
                    raw.seek(0)
                    im = Image.open(raw).convert("RGB")
                    ImageFile.LOAD_TRUNCATED_IMAGES = False
                # 카드가 1080×1350 이라 크기가 다르면 맞춰 담는다
                if im.size != (1080, 1350):
                    im = im.resize((1080, 1350), Image.LANCZOS)
                im.save(d / ("%02d.jpg" % (k + 1)), "JPEG",
                        quality=86, optimize=True)
            # 깨진 장을 같은 테마의 다른 장(좌우 반전)으로 대신한다
            for k in range(PER_THEME):
                key = "%s/%02d" % (tid, k + 1)
                src = REPLACE_BROKEN.get(key)
                if not src:
                    continue
                good = d / ("%02d.jpg" % src)
                if good.exists():
                    Image.open(good).transpose(Image.FLIP_LEFT_RIGHT) \
                         .save(d / ("%02d.jpg" % (k + 1)), "JPEG",
                               quality=86, optimize=True)
                    print("       %s ← %02d번을 좌우 반전 (원본이 깨져 있음)"
                          % (key, src))

            cover = Image.open(d / "01.jpg")
            cover.resize((PREVIEW_W, PREVIEW_H), Image.LANCZOS) \
                 .save(PREV / ("bg_%s.png" % tid), "PNG")
            meta.append({"id": tid, "name": name, "desc": desc,
                         "preview": "bg_%s.png" % tid, "slides": PER_THEME})
            print("  %-10s %-8s %s" % (tid, name, desc))

    (BG / "themes.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    size = sum(f.stat().st_size for f in BG.rglob("*.jpg")) / 1024 / 1024
    print("\n  테마 %d개 · 배경 %d장 · %.1f MB → %s"
          % (len(meta), len(order), size, BG))
    print("  미리보기 %d장 → %s" % (len(meta), PREV))


if __name__ == "__main__":
    main()
