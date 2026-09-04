#!/usr/bin/env python3
"""
이미지 가공 모듈
1. 리뷰 카드 렌더링 (HTML → PNG via Playwright)
2. 상세이미지 크롭 (Claude 지시 → Pillow 실행)

사용법:
  python3 process_images.py <output_dir>                 # 리뷰카드만
  python3 process_images.py <output_dir> --prepare-crops # 크롭 매니페스트
  python3 process_images.py <output_dir> --execute-crops # 크롭 실행
  python3 process_images.py <output_dir> --top-reviews 3 # 리뷰카드 3장
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)

SCRIPT_DIR = Path(__file__).parent
TEMPLATE_PATH = SCRIPT_DIR / "templates" / "review_card.html"

# 쿠팡 설문 접미사 패턴 (리뷰 하단에 붙는 평가 항목)
SURVEY_PATTERNS = [
    r"^가성비$", r"^청소 성능$", r"^센서 성능$", r"^소음$",
    r"^먼지통.*용량$", r"^물통.*용량$", r"^디자인$",
    r"^적당한 편이에요$", r"^보통이에요$", r"^아주.*나요$",
    r"^기대이상.*나요$", r"^아주넉넉해요$", r"^생각보다.*요$",
    r"^적당해요$",
]
SURVEY_RE = re.compile("|".join(SURVEY_PATTERNS))


# ── 리뷰 텍스트 클리닝 ────────────────────────────────

def clean_review_text(text: str) -> str:
    """쿠팡 설문 접미사 제거 + 트리밍"""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if SURVEY_RE.match(stripped):
            continue
        cleaned.append(line)

    # 뒤에서부터 빈줄 제거
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()

    return "\n".join(cleaned)


def truncate_text(text: str, max_chars: int = 200) -> str:
    """200자로 자르고 말줄임"""
    if len(text) <= max_chars:
        return text
    # 단어 단위로 자르기
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    last_newline = truncated.rfind("\n")
    cut = max(last_space, last_newline)
    if cut > max_chars * 0.7:
        truncated = truncated[:cut]
    return truncated.rstrip() + "..."


# ── 리뷰 카드 렌더링 ─────────────────────────────────

def render_review_cards(output_dir: Path, top_n: int = 5):
    """베스트 리뷰를 HTML → PNG 카드로 렌더링"""
    from jinja2 import Environment, FileSystemLoader
    from playwright.sync_api import sync_playwright

    result_path = output_dir / "result.json"
    if not result_path.exists():
        print("  result.json 없음 — 스킵")
        return []

    data = json.loads(result_path.read_text(encoding='utf-8'))
    reviews = data.get("reviews", [])
    if not reviews:
        print("  리뷰 없음 — 스킵")
        return []

    # likes순 정렬
    sorted_reviews = sorted(reviews, key=lambda r: r.get("likes", 0), reverse=True)
    top_reviews = sorted_reviews[:top_n]

    # 출력 폴더
    cards_dir = output_dir / "review_cards"
    cards_dir.mkdir(exist_ok=True)

    # Jinja2 템플릿
    env = Environment(loader=FileSystemLoader(str(SCRIPT_DIR / "templates")))
    template = env.get_template("review_card.html")

    rendered = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1080, "height": 1080},
            device_scale_factor=2,
        )

        for i, review in enumerate(top_reviews, 1):
            # 텍스트 가공
            content = clean_review_text(review.get("content", ""))
            content = truncate_text(content, 200)

            rating_str = review.get("rating", "5")
            try:
                rating_int = int(float(rating_str))
            except (ValueError, TypeError):
                rating_int = 5

            # HTML 렌더
            html = template.render(
                rating=rating_str,
                rating_int=rating_int,
                content=content,
                user=review.get("user", "익명"),
                date=review.get("date", ""),
                likes=review.get("likes", 0),
            )

            html_path = (cards_dir / f"review_{i:02d}.html").resolve()
            png_path = (cards_dir / f"review_{i:02d}.png").resolve()
            html_path.write_text(html, encoding='utf-8')

            # Playwright 스크린샷
            page = context.new_page()
            page.goto(html_path.as_uri(), wait_until="networkidle")
            page.wait_for_timeout(500)  # 폰트 로딩 대기
            page.screenshot(path=str(png_path), full_page=False)
            page.close()

            rendered.append(str(png_path))
            likes = review.get("likes", 0)
            print(f"  [{i}/{len(top_reviews)}] review_{i:02d}.png (좋아요 {likes})")

        browser.close()

    return rendered


# ── 이미지 크롭 ───────────────────────────────────────

def prepare_crop_manifest(output_dir: Path):
    """높이 2000px 초과 이미지 목록 → crop_todo.json"""
    from PIL import Image

    images_dir = output_dir / "images"
    if not images_dir.exists():
        print("  images/ 폴더 없음")
        return

    manifest = []
    for img_path in sorted(images_dir.glob("detail_*")):
        try:
            with Image.open(img_path) as img:
                w, h = img.size
                if h > 2000:
                    manifest.append({
                        "file": img_path.name,
                        "width": w,
                        "height": h,
                        "ratio": round(h / w, 1),
                    })
                    print(f"  {img_path.name}: {w}x{h} (크롭 필요)")
                else:
                    print(f"  {img_path.name}: {w}x{h} (작은 이미지, 스킵)")
        except Exception as e:
            print(f"  {img_path.name}: 읽기 실패 ({e})")

    todo_path = output_dir / "crop_todo.json"
    todo_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n  매니페스트 저장: {todo_path} ({len(manifest)}개 이미지)")


def execute_crops(output_dir: Path):
    """crop_commands.json 읽고 Pillow로 크롭 실행"""
    from PIL import Image

    cmd_path = output_dir / "crop_commands.json"
    if not cmd_path.exists():
        print("  crop_commands.json 없음 — Claude에게 작성 요청 필요")
        return []

    commands = json.loads(cmd_path.read_text(encoding='utf-8'))
    images_dir = output_dir / "images"
    cropped_dir = output_dir / "cropped"
    cropped_dir.mkdir(exist_ok=True)

    results = []
    idx = 1
    for entry in commands:
        source = images_dir / entry["source"]
        if not source.exists():
            print(f"  {entry['source']} 없음 — 스킵")
            continue

        with Image.open(source) as img:
            w, h = img.size
            for crop in entry.get("crops", []):
                if not crop.get("keep", True):
                    continue
                y_start = crop["y_start"]
                y_end = min(crop["y_end"], h)
                label = crop.get("label", f"section_{idx}")

                cropped_img = img.crop((0, y_start, w, y_end))

                # x좌표도 지정된 경우 (카드뉴스용 정밀 크롭)
                if "x_start" in crop:
                    x_start = crop.get("x_start", 0)
                    x_end = crop.get("x_end", w)
                    cropped_img = img.crop((x_start, y_start, x_end, y_end))

                purpose = crop.get("purpose", "section")

                if purpose == "card":
                    # 카드뉴스용: 1080x1350 (4:5)에 맞게 리사이즈
                    cropped_img = _fit_to_card(cropped_img)
                    card_dir = output_dir / "card_images"
                    card_dir.mkdir(exist_ok=True)
                    out_name = f"card_{idx:03d}_{label}.jpg"
                    out_path = card_dir / out_name
                else:
                    out_name = f"crop_{idx:03d}_{label}.jpg"
                    out_path = cropped_dir / out_name

                cropped_img.save(out_path, quality=95)
                results.append(str(out_path))
                print(f"  [{idx}] {out_name} ({cropped_img.size[0]}x{cropped_img.size[1]}) [{purpose}]")
                idx += 1

    print(f"\n  크롭 완료: {len(results)}장")
    return results


def _fit_to_card(img):
    """이미지를 1080x1350 캔버스에 맞춤 (cover 방식 — 잘라서 채움)"""
    from PIL import Image

    target_w, target_h = 1080, 1350
    target_ratio = target_w / target_h  # 0.8

    w, h = img.size
    img_ratio = w / h

    if img_ratio > target_ratio:
        # 이미지가 더 넓음 → 좌우 잘라냄
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        # 이미지가 더 좁음 → 상하 잘라냄
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))

    return img.resize((target_w, target_h), Image.LANCZOS)


# ── 메인 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="쿠팡 상품 이미지 가공")
    parser.add_argument("output_dir", help="크롤링 출력 디렉토리")
    parser.add_argument("--prepare-crops", action="store_true",
                        help="크롭 대상 이미지 매니페스트 생성")
    parser.add_argument("--execute-crops", action="store_true",
                        help="crop_commands.json 기반 크롭 실행")
    parser.add_argument("--skip-reviews", action="store_true",
                        help="리뷰 카드 렌더링 스킵")
    parser.add_argument("--top-reviews", type=int, default=5,
                        help="리뷰 카드 생성 수 (기본 5)")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if not output_dir.exists():
        print(f"폴더 없음: {output_dir}")
        sys.exit(1)

    # 리뷰 카드
    if not args.skip_reviews and not args.execute_crops and not args.prepare_crops:
        print("\n[리뷰 카드 렌더링]")
        cards = render_review_cards(output_dir, args.top_reviews)
        print(f"  완료: {len(cards)}장")

    # 크롭 매니페스트
    if args.prepare_crops:
        print("\n[크롭 매니페스트 생성]")
        prepare_crop_manifest(output_dir)

    # 크롭 실행
    if args.execute_crops:
        print("\n[이미지 크롭 실행]")
        execute_crops(output_dir)


if __name__ == "__main__":
    main()
