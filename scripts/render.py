#!/usr/bin/env python3
"""
render.py — slides.json + 이미지 → HTML 합성 → Playwright 스크린샷 → PNG

사용법:
    python render.py path/to/slides.json

출력:
    - {output_dir}/slide_01.png ~ slide_NN.png (1080×1350)
"""

import json
import sys
import tempfile
from pathlib import Path

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:
    print("[ERROR] jinja2가 설치되지 않았습니다.")
    print("        pip install jinja2")
    sys.exit(1)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("[ERROR] playwright가 설치되지 않았습니다.")
    print("        pip install playwright && playwright install chromium")
    sys.exit(1)


sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).resolve().parent))
import design  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = SKILL_DIR / "templates"


def load_slides(json_path: Path) -> dict:
    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)


# theme → (템플릿, CSS) 매핑. slides.json의 "theme" 필드로 선택
THEMES = {
    "default": ("slide.html", "styles.css"),
    "magazine": ("slide_magazine.html", "styles_magazine.css"),
    "simple": ("slide_simple.html", "styles_simple.css"),
    "bold": ("slide_bold.html", "styles_bold.css"),
    "frost": ("slide_frost.html", "styles_frost.css"),
}


def render_html(template_env, data: dict, slide: dict, css_url: str) -> str:
    theme = data.get("theme", "default")
    tpl_name = THEMES.get(theme, THEMES["default"])[0]
    template = template_env.get_template(tpl_name)
    cfg = data.get("design") or {}
    return template.render(
        slide=slide,
        total=len(data["slides"]),
        theme=theme,
        brand=data.get("brand", ""),
        palette=data.get("palette", "ice"),
        label=cfg.get("label", ""),
        design_css=design.build_css(theme, cfg),
        css_path=css_url,
    )


def render_slides(json_path: Path, only=None) -> None:
    json_path = json_path.resolve()
    output_dir = json_path.parent
    data = load_slides(json_path)

    print(f"[render] slides.json: {json_path}")
    print(f"[render] output dir : {output_dir}")
    print(f"[render] slide count: {len(data['slides'])}")

    template_env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )

    theme = data.get("theme", "default")
    css_source = TEMPLATE_DIR / THEMES.get(theme, THEMES["default"])[1]
    css_url = css_source.as_uri()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(
                viewport={"width": 1080, "height": 1350},
                device_scale_factor=2,
            )
            page = context.new_page()

            for slide in data["slides"]:
                if only and slide["no"] not in only:
                    continue
                no = slide["no"]

                # 이미지 경로 절대화 (있을 때만) — image_path, cutout 등 모든 이미지 필드
                for field in ("image_path", "cutout", "logo"):
                    if not slide.get(field):
                        continue
                    img = Path(slide[field])
                    if not img.is_absolute():
                        img = (output_dir / img).resolve()
                    if img.exists():
                        slide[field] = img.as_uri()
                    else:
                        print(f"[warn]  slide {no}: {field} 이미지 없음 → {img}")
                        slide[field] = None

                html = render_html(template_env, data, slide, css_url)

                html_file = tmpdir_path / f"slide_{no:02d}.html"
                html_file.write_text(html, encoding="utf-8")

                page.goto(html_file.as_uri(), wait_until="networkidle")
                page.wait_for_timeout(300)  # 폰트 안정화 대기

                out_png = output_dir / f"slide_{no:02d}.png"
                page.screenshot(path=str(out_png), full_page=False, omit_background=False)
                print(f"[ok]    slide {no:02d} → {out_png.name}")

            browser.close()

    # 캡션 dump
    if data.get("caption"):
        caption_file = output_dir / "caption.txt"
        caption_text = data["caption"]
        if data.get("hashtags"):
            caption_text += "\n\n.\n.\n.\n" + " ".join(data["hashtags"])
        caption_file.write_text(caption_text, encoding="utf-8")
        print(f"[ok]    caption  → caption.txt")

    n = len(only) if only else len(data["slides"])
    print(f"\n[done] {n}장 생성 완료 → {output_dir}")


def main():
    if len(sys.argv) < 2:
        print("사용법: python render.py path/to/slides.json")
        sys.exit(1)

    json_path = Path(sys.argv[1])
    if not json_path.exists():
        print(f"[ERROR] 파일이 없습니다: {json_path}")
        sys.exit(1)

    render_slides(json_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python render.py path/to/slides.json [--only 1,2]")
        sys.exit(1)
    only = None
    if "--only" in sys.argv:
        only = {int(x) for x in sys.argv[sys.argv.index("--only") + 1].split(",") if x.strip()}
    render_slides(Path(sys.argv[1]), only)
