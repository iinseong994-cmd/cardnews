#!/usr/bin/env python3
"""
make_theme_previews.py — 테마 고르는 화면에 쓸 미리보기 그림 만들기

앱에서 테마를 이름만 보고 고를 수 없어서, 실제로 그려본 카드를 줄여 보여준다.
템플릿을 고치면 이 스크립트를 다시 돌려 그림도 새로 만든다.

    python scripts/make_theme_previews.py

결과: webapp/previews/<테마>_<팔레트>.png
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "webapp" / "previews"
PY = sys.executable

# 미리보기에 쓸 예시 내용 — PPTX 원본의 견본 문구를 그대로 쓴다
SAMPLE = {
    "no": 1, "type": "cover", "kind": "BOOK REVIEW",
    "eyebrow": "조금 느려도 괜찮은 삶에 대하여",
    "headline": "생각의 틈", "book_title": "생각의 틈",
    "author": "저자  김하늘", "rating": "4.5",
}

# (테마, 팔레트id, 푸터에 넣을 이름)
TARGETS = [
    ("review", "",       "01 포레스트 에디토리얼"),
    ("review", "navy",   "02 네이비 매거진"),
    ("review", "cobalt", "03 코발트 모던"),
    ("review", "sepia",  "04 세피아 아카이브"),
    ("review", "wine",   "05 버건디 문학"),
    ("review", "mist",   "06 소프트블루 미니멀"),
]

W, H = 360, 450          # 화면에 놓일 크기의 2배쯤. 줄여 쓰면 선명하다


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    from PIL import Image

    made = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for theme, pal, label in TARGETS:
            d = tmp / (theme + "_" + (pal or "default"))
            d.mkdir()
            (d / "slides.json").write_text(json.dumps({
                "theme": theme, "palette": pal, "slides": [SAMPLE],
                "design": {"label": label, "page": False},
            }, ensure_ascii=False), encoding="utf-8")

            r = subprocess.run([PY, str(ROOT / "scripts" / "render.py"),
                                str(d / "slides.json")],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            png = d / "slide_01.png"
            if not png.exists():
                print("  실패:", label, r.stdout[-300:] or r.stderr[-300:])
                continue

            dest = OUT / ("%s_%s.png" % (theme, pal or "default"))
            Image.open(png).resize((W, H), Image.LANCZOS).save(dest, "PNG")
            made.append(dest)
            print("  %-26s → %s" % (label, dest.name))

    print("\n  %d장 만들었습니다 → %s" % (len(made), OUT))


if __name__ == "__main__":
    main()
