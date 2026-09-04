#!/usr/bin/env python3
"""
쿠팡 콘텐츠 파이프라인
쿠팡 링크 → 크롤링 → 이미지 가공 → 콘텐츠 생성 안내

사용법:
  python3 pipeline.py "https://link.coupang.com/a/XXXXXX"   # 내 쿠팡 파트너스 링크
  python3 pipeline.py "https://www.coupang.com/vp/products/1234567890"
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
SCRIPT_DIR = Path(__file__).parent


def run_crawl(url: str, max_review_pages: int = 1) -> Path | None:
    """crawl.py 실행 후 output 디렉토리 반환"""
    cmd = [
        sys.executable, str(SCRIPT_DIR / "crawl.py"),
        url,
        "--max-review-pages", str(max_review_pages),
    ]
    proc = subprocess.run(cmd, capture_output=False, text=True, cwd=str(SCRIPT_DIR))
    if proc.returncode != 0:
        print("\n크롤링 실패")
        return None

    # output/ 에서 가장 최근 폴더 찾기
    output_root = SCRIPT_DIR / "output"
    if not output_root.exists():
        return None
    dirs = sorted(output_root.iterdir(), key=lambda d: d.stat().st_mtime, reverse=True)
    return dirs[0] if dirs else None


def run_process_images(output_dir: Path, top_reviews: int = 5):
    """리뷰 카드 렌더링 + 크롭 매니페스트 생성"""
    cmd = [
        sys.executable, str(SCRIPT_DIR / "process_images.py"),
        str(output_dir),
        "--top-reviews", str(top_reviews),
    ]
    subprocess.run(cmd, cwd=str(SCRIPT_DIR))

    # 크롭 매니페스트도 생성
    cmd_crop = [
        sys.executable, str(SCRIPT_DIR / "process_images.py"),
        str(output_dir),
        "--prepare-crops",
    ]
    subprocess.run(cmd_crop, cwd=str(SCRIPT_DIR))


def main():
    parser = argparse.ArgumentParser(description="쿠팡 콘텐츠 파이프라인")
    parser.add_argument("url", help="쿠팡 상품 URL")
    parser.add_argument("--max-review-pages", type=int, default=1)
    parser.add_argument("--top-reviews", type=int, default=5)
    args = parser.parse_args()

    print("=" * 50)
    print("  쿠팡 콘텐츠 파이프라인")
    print("=" * 50)

    # 1. 크롤링
    print("\n[Step 1/3] 크롤링...")
    output_dir = run_crawl(args.url, args.max_review_pages)
    if not output_dir:
        print("크롤링 실패 — 종료")
        sys.exit(1)
    print(f"  출력: {output_dir}")

    # 2. 이미지 가공
    print("\n[Step 2/3] 이미지 가공...")
    run_process_images(output_dir, args.top_reviews)

    # 3. 결과 안내
    print("\n" + "=" * 50)
    print("  파이프라인 완료")
    print("=" * 50)

    # 파일 목록
    files = {
        "summary.md": (output_dir / "summary.md").exists(),
        "review.md": (output_dir / "review.md").exists(),
        "images/": (output_dir / "images").exists(),
        "review_cards/": (output_dir / "review_cards").exists(),
        "crop_todo.json": (output_dir / "crop_todo.json").exists(),
    }

    print(f"\n  {output_dir}/")
    for name, exists in files.items():
        mark = "v" if exists else " "
        print(f"    [{mark}] {name}")

    # 리뷰 카드 수
    cards_dir = output_dir / "review_cards"
    if cards_dir.exists():
        pngs = list(cards_dir.glob("*.png"))
        print(f"\n  리뷰 카드: {len(pngs)}장 생성됨")

    # 다음 단계 안내
    rel_path = output_dir.relative_to(SCRIPT_DIR) if output_dir.is_relative_to(SCRIPT_DIR) else output_dir
    print(f"""
  다음 단계:
  /make-coupang-contents {rel_path}
""")


if __name__ == "__main__":
    main()
