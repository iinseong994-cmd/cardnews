#!/usr/bin/env python3
"""
쿠팡 상품 페이지 크롤러
실제 Chrome을 remote debugging으로 띄워서 Akamai 차단 우회.

사용법:
  python3 crawl.py "https://link.coupang.com/a/XXXXXX"   # 내 쿠팡 파트너스 링크
  python3 crawl.py "https://www.coupang.com/vp/products/1234567890"
"""

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright

# stdout 즉시 출력
sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)


# ── URL 처리 ──────────────────────────────────────────────

def resolve_and_clean_url(url: str) -> str:
    """쿠팡 단축/추적 URL → 깨끗한 상품 URL"""
    if "link.coupang.com" in url:
        import http.client
        parsed = urlparse(url)
        conn = http.client.HTTPSConnection(parsed.netloc, timeout=10)
        conn.request("HEAD", parsed.path + ("?" + parsed.query if parsed.query else ""),
                      headers={"User-Agent": "Mozilla/5.0"})
        resp = conn.getresponse()
        if resp.status in (301, 302, 303, 307, 308):
            url = resp.getheader("Location", url)

    m = re.search(r"coupang\.com/vp/products/(\d+)", url)
    if m:
        pid = m.group(1)
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        clean = f"https://www.coupang.com/vp/products/{pid}"
        if "itemId" in qs:
            clean += f"?itemId={qs['itemId'][0]}"
        return clean
    return url


# ── Chrome 관리 ────────────────────────────────────────────

if sys.platform == "darwin":
    CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
elif sys.platform == "win32":
    CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not Path(CHROME_PATH).exists():
        CHROME_PATH = str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe")
else:
    CHROME_PATH = "/usr/bin/google-chrome"
DEBUG_PORT = 9222


PROFILE_DIR = str(Path.home() / ".crawl-coupang-chrome")


def launch_chrome_debug():
    """별도 프로필로 Chrome을 remote debugging 모드로 실행.
    사용자의 기존 Chrome은 건드리지 않음."""
    # 이미 포트 9222가 열려있는지 체크
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("localhost", DEBUG_PORT)) == 0:
            print(f"  포트 {DEBUG_PORT} 이미 사용 중 — 기존 세션에 연결합니다.")
            return None  # 이미 떠있음

    chrome_proc = subprocess.Popen(
        [
            CHROME_PATH,
            f"--remote-debugging-port={DEBUG_PORT}",
            f"--user-data-dir={PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # 포트 열릴 때까지 대기
    for _ in range(20):
        time.sleep(0.5)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("localhost", DEBUG_PORT)) == 0:
                break
    else:
        print("  ❌ Chrome 시작 실패 (포트 대기 타임아웃)")
        sys.exit(1)

    return chrome_proc


def connect_to_chrome(pw):
    """CDP로 실행 중인 Chrome에 연결"""
    browser = pw.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
    context = browser.contexts[0]  # 기존 context 사용
    return browser, context


# ── 파싱 ──────────────────────────────────────────────────

def get_json_ld_product(page) -> dict:
    """SEO용 JSON-LD(@type: Product) 구조화 데이터 추출.
    CSS 클래스는 개편 때마다 바뀌지만 JSON-LD는 검색엔진용이라 안정적."""
    try:
        items = page.evaluate("""
            (() => Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
                .map(s => { try { return JSON.parse(s.textContent) } catch (e) { return null } })
                .filter(d => d && d['@type'] === 'Product'))()
        """)
        return items[0] if items else {}
    except Exception:
        return {}


def parse_product_info(page) -> dict:
    """상품 기본 정보 파싱 — JSON-LD 우선, CSS 셀렉터는 fallback"""
    info = {}
    ld = get_json_ld_product(page)
    offers = ld.get("offers") or {}
    agg = ld.get("aggregateRating") or {}
    brand = ld.get("brand") or {}

    # 제목
    info["title"] = (ld.get("name") or "").strip()
    if not info["title"]:
        for sel in ["h1.prod-buy-header__title", "h2.prod-buy-header__title",
                    "h1[class*='title']", ".prod-buy-header__title"]:
            el = page.query_selector(sel)
            if el:
                info["title"] = el.inner_text().strip()
                break
        else:
            info["title"] = page.title().replace(" | 쿠팡", "").strip()

    # 브랜드
    info["brand"] = brand.get("name", "") if isinstance(brand, dict) else str(brand)

    # 최종 가격 — JSON-LD offers.price
    price_raw = str(offers.get("price", "")).replace(",", "").strip()
    if price_raw and price_raw.replace(".", "", 1).isdigit():
        info["price"] = f"{int(float(price_raw)):,}원"
    else:
        for sel in [".final-price-amount", "span.total-price strong",
                    ".total-price", ".prod-sale-price .total-price"]:
            el = page.query_selector(sel)
            if el and el.inner_text().strip():
                info["price"] = el.inner_text().strip()
                break
        else:
            info["price"] = ""

    # 원래가격/할인율 — 가격 표시 영역 텍스트에서 정규식으로 (할인 중일 때만 존재)
    price_area_text = page.evaluate("""
        (() => {
            const el = document.querySelector('.price-container, .price-layout-container, .prod-price-container, .prod-coupon-price');
            return el ? el.innerText : '';
        })()
    """)
    m = re.search(r"(\d{1,2})\s*%", price_area_text)
    info["discount_rate"] = f"{m.group(1)}%" if m else ""
    price_nums = sorted({int(p.replace(",", ""))
                         for p in re.findall(r"(\d[\d,]{2,})\s*원", price_area_text)})
    if len(price_nums) >= 2:
        info["original_price"] = f"{price_nums[-1]:,}원"  # 최고가 = 정가
        if not info["price"]:
            info["price"] = f"{price_nums[0]:,}원"
    else:
        info["original_price"] = ""

    # 평점/리뷰 수 — JSON-LD aggregateRating
    info["rating"] = str(agg.get("ratingValue", "")).strip()
    info["review_count"] = str(agg.get("ratingCount", "") or agg.get("reviewCount", "")).strip()
    if not info["review_count"]:
        info["review_count"] = page.evaluate("""
            (() => {
                // 탭에서 "상품평 (1,950)" 형태로 추출
                const tabs = document.querySelectorAll('[class*="tab"], a[href*="review"]');
                for (const t of tabs) {
                    const m = t.textContent.match(/상품평.*?\\((\\d[\\d,]*)\\)/);
                    if (m) return m[1];
                }
                return '';
            })()
        """)

    # 품절 여부
    availability = str(offers.get("availability", ""))
    info["in_stock"] = "InStock" in availability if availability else None

    # 옵션
    options = []
    for el in page.query_selector_all(
        ".prod-option__item, .prod-option__button, "
        "[class*='option__item'], [class*='option-item']"
    ):
        txt = el.inner_text().strip()
        if txt:
            options.append(txt)
    info["options"] = options

    return info


def scroll_and_collect_detail_images(page) -> list[str]:
    """상세페이지 이미지 수집 (lazy-load 대응)"""
    # 상품상세 탭 클릭
    for sel in ["#btfTab a[href='#productDetail']",
                ".tab-titles__btn--product-detail",
                "a:has-text('상품상세')"]:
        try:
            tab = page.query_selector(sel)
            if tab:
                tab.click()
                time.sleep(1)
                break
        except Exception:
            continue

    # 더보기 버튼 클릭
    for sel in [".product-detail-content-inside__btn",
                ".product-detail__btn--more",
                "button:has-text('상품정보 더보기')"]:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                time.sleep(1)
                break
        except Exception:
            continue

    # 스크롤
    prev_height = 0
    for _ in range(40):
        page.evaluate("window.scrollBy(0, 600)")
        time.sleep(0.4)
        curr_height = page.evaluate("document.body.scrollHeight")
        if curr_height == prev_height:
            break
        prev_height = curr_height

    # 이미지 수집
    image_urls = []
    for sel in [".product-detail-content-inside img",
                "#productDetail img",
                ".product-body img",
                ".vendor-item-content-wrap img"]:
        for img in page.query_selector_all(sel):
            src = img.get_attribute("src") or img.get_attribute("data-src") or ""
            if src and not src.startswith("data:"):
                if src.startswith("//"):
                    src = "https:" + src
                if src not in image_urls:
                    image_urls.append(src)

    return image_urls


def download_images(image_urls: list[str], output_dir: Path, page) -> list[str]:
    """이미지 다운로드 — 브라우저 쿠키로 다운로드"""
    img_dir = output_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    # 브라우저 쿠키를 가져와서 urllib에 사용
    cookies = page.context.cookies()
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies
                           if "coupang" in c.get("domain", ""))

    downloaded = []
    for i, url in enumerate(image_urls):
        ext = Path(urlparse(url).path).suffix or ".jpg"
        filename = f"detail_{i+1:03d}{ext}"
        filepath = img_dir / filename
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 Chrome/136.0.0.0 Safari/537.36",
                "Referer": "https://www.coupang.com/",
                "Cookie": cookie_str,
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                filepath.write_bytes(resp.read())
            downloaded.append(str(filepath))
            print(f"  [{i+1}/{len(image_urls)}] {filename}")
        except Exception as e:
            print(f"  [{i+1}/{len(image_urls)}] FAIL: {e}")
    return downloaded


def collect_reviews(page, max_pages: int = 5) -> list[dict]:
    """리뷰 수집 (신규 Tailwind UI + 레거시 대응)"""
    reviews = []

    # 리뷰 탭 클릭
    for sel in ["a:has-text('상품평')", "button:has-text('상품평')",
                "#btfTab a[href='#productReview']"]:
        try:
            tab = page.query_selector(sel)
            if tab:
                tab.click()
                time.sleep(3)
                break
        except Exception:
            continue

    # 스크롤
    for _ in range(5):
        page.evaluate("window.scrollBy(0, 500)")
        time.sleep(0.3)

    for page_num in range(1, max_pages + 1):
        print(f"  리뷰 페이지 {page_num} 수집 중...")

        # 리뷰 article = twc-border-b 클래스 포함 article (사이드바 article 제외)
        review_els = page.query_selector_all(
            "article[class*='twc-border-b']"
        )
        if not review_els:
            review_els = page.query_selector_all(
                ".sdp-review__article__list__review"
            )

        for el in review_els:
            review = {}

            # 별점
            stars = el.query_selector_all("[class*='full-star']")
            half = el.query_selector_all("[class*='half-star']")
            if stars:
                score = len(stars) + len(half) * 0.5
                review["rating"] = f"{score:.0f}" if score == int(score) else f"{score}"
            else:
                star_el = el.query_selector("[class*='star__count']")
                review["rating"] = star_el.inner_text().strip() if star_el else ""

            # 작성자
            review["user"] = page.evaluate("""(el) => {
                const bold = el.querySelector('[class*="font-bold"][class*="bluegray-900"]');
                return bold ? bold.textContent.trim() : '';
            }""", el)

            # 날짜
            review["date"] = page.evaluate("""(el) => {
                const d = el.querySelector('[class*="bluegray-700"]');
                return d ? d.textContent.trim() : '';
            }""", el)

            # 좋아요 수 ("N명에게 도움이 됐어요")
            review["likes"] = page.evaluate("""(el) => {
                const full = el.innerText;
                const m = full.match(/(\\d+)명에게 도움이/);
                return m ? parseInt(m[1]) : 0;
            }""", el)

            # 본문 — article의 전체 텍스트에서 메타 제거
            review["content"] = page.evaluate("""(el) => {
                const full = el.innerText;
                const lines = full.split('\\n').filter(l => {
                    const t = l.trim();
                    if (!t) return false;
                    if (t.match(/^\\d{4}\\.\\d{2}\\.\\d{2}$/)) return false;
                    if (t.match(/판매자:/)) return false;
                    if (t.match(/명에게 도움이/)) return false;
                    if (t === '신고하기') return false;
                    if (t.match(/^(0:\\d|\\d:\\d)/)) return false;
                    if (t.length < 3) return false;
                    return true;
                });
                // 첫 줄은 닉네임 → 건너뜀. 상품명 줄도 제거
                const filtered = lines.slice(1).filter(l => {
                    // 상품명 패턴 (쿠팡 옵션 표시줄) 제거
                    if (l.match(/^.{5,80},\\s*(화이트|블랙|그레이)/)) return false;
                    if (l.match(/^[A-Z0-9]{5,}/)) return false;
                    return true;
                });
                return filtered.join('\\n').substring(0, 1500);
            }""", el)

            if review.get("content") and len(review["content"]) > 5:
                reviews.append(review)

        # 다음 페이지 — 페이지 번호 버튼 클릭
        try:
            clicked = page.evaluate(f"""
                (() => {{
                    const btns = document.querySelectorAll('button');
                    for (const b of btns) {{
                        if (b.textContent.trim() === '{page_num + 1}'
                            && b.offsetParent !== null) {{
                            b.click();
                            return true;
                        }}
                    }}
                    return false;
                }})()
            """)
            if clicked:
                time.sleep(2)
            else:
                break
        except Exception:
            break

    return reviews


def save_results(product_info: dict, image_files: list[str],
                 reviews: list[dict], output_dir: Path):
    """결과 저장: result.json + summary.md + review.md"""
    result = {
        "product": product_info,
        "detail_images": image_files,
        "reviews": reviews,
        "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # JSON (원본 데이터)
    json_path = output_dir / "result.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n결과 저장: {json_path}")

    # ── summary.md: 상품 정보 + 이미지 목록 ──
    summary = [
        f"# {product_info.get('title', '상품명 없음')}",
        "",
        "## 기본 정보",
        "",
        f"| 항목 | 내용 |",
        f"|------|------|",
        f"| 브랜드 | {product_info.get('brand') or '-'} |",
        f"| 가격 | {product_info.get('price') or '-'} |",
        f"| 원래가격 | {product_info.get('original_price') or '-'} |",
        f"| 할인율 | {product_info.get('discount_rate') or '-'} |",
        f"| 평점 | {product_info.get('rating') or '-'} |",
        f"| 리뷰 수 | {product_info.get('review_count') or '-'} |",
        f"| URL | {product_info.get('url') or '-'} |",
        "",
    ]
    if product_info.get("options"):
        summary.append("## 옵션")
        for opt in product_info["options"]:
            summary.append(f"- {opt}")
        summary.append("")

    summary.append(f"## 상세페이지 이미지 ({len(image_files)}장)")
    summary.append("")
    summary.append("> 이미지 분석은 별도로 진행 (Claude에게 images/ 폴더 읽기 요청)")
    summary.append("")
    for f in image_files:
        summary.append(f"- `{Path(f).name}`")
    summary.append("")

    (output_dir / "summary.md").write_text("\n".join(summary), encoding='utf-8')
    print(f"요약 저장: {output_dir / 'summary.md'}")

    # ── review.md: 추천순 (좋아요 수) 정렬 ──
    if reviews:
        sorted_reviews = sorted(reviews, key=lambda r: r.get("likes", 0), reverse=True)

        rev_lines = [
            f"# {product_info.get('title', '')} — 상품평",
            "",
            f"총 {len(sorted_reviews)}건 (추천순 정렬)",
            "",
        ]
        for i, r in enumerate(sorted_reviews, 1):
            likes = r.get("likes", 0)
            stars = r.get("rating", "?")
            user = r.get("user", "-")
            date = r.get("date", "-")
            content = r.get("content", "")

            rev_lines.append(f"---")
            rev_lines.append(f"### {i}. {'★' * int(float(stars))} ({stars}/5) | {user} | {date} | 좋아요 {likes}")
            rev_lines.append("")
            rev_lines.append(content)
            rev_lines.append("")

        (output_dir / "review.md").write_text("\n".join(rev_lines), encoding='utf-8')
        print(f"리뷰 저장: {output_dir / 'review.md'}")


# ── 메인 ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="쿠팡 상품 크롤러")
    parser.add_argument("url", help="쿠팡 상품 URL (단축 URL 가능)")
    parser.add_argument("-o", "--output", default=None, help="출력 디렉토리")
    parser.add_argument("--max-review-pages", type=int, default=1)
    parser.add_argument("--no-images", action="store_true")
    parser.add_argument("--no-reviews", action="store_true")
    args = parser.parse_args()

    url = resolve_and_clean_url(args.url)
    print(f"URL: {url}")

    m = re.search(r"/products/(\d+)", url)
    pid = m.group(1) if m else "unknown"
    if args.output:
        output_dir = Path(args.output)
    else:
        output_dir = Path(f"output/{pid}")  # 임시, 파싱 후 rename
    output_dir.mkdir(parents=True, exist_ok=True)

    # Chrome을 remote debugging 모드로 실행
    print("\n[0/4] Chrome 시작 (remote debugging)...")
    chrome_proc = launch_chrome_debug()

    try:
        with sync_playwright() as pw:
            print("[1/4] Chrome에 연결 중...")
            browser, context = connect_to_chrome(pw)
            page = context.new_page()

            # 상품 페이지 접속
            print("  → 상품 페이지 이동...")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            # Access Denied 체크
            if "Access Denied" in (page.content() or ""):
                print("\n❌ Access Denied — 쿠팡이 여전히 차단 중입니다.")
                print("   브라우저 창에서 직접 coupang.com을 한번 열어보세요.")
                page.screenshot(path=str(output_dir / "screenshot.png"))
                browser.close()
                return

            # 상품 정보 파싱
            print("[2/4] 상품 정보 파싱...")
            product_info = parse_product_info(page)
            product_info["url"] = url
            print(f"  제목: {product_info.get('title', '-')}")
            print(f"  가격: {product_info.get('price', '-')}"
                  + (f" (정가 {product_info['original_price']}, {product_info['discount_rate']} 할인)"
                     if product_info.get("original_price") else ""))
            print(f"  평점: {product_info.get('rating', '-')} / 리뷰 {product_info.get('review_count', '-')}건")

            # 상품명으로 폴더 rename (사용자가 -o 지정 안 한 경우만)
            if not args.output and product_info.get("title"):
                safe_title = re.sub(r'[\\/*?:"<>|]', '', product_info["title"])
                safe_title = safe_title.strip()[:50]  # 길이 제한
                new_dir = Path(f"output/{safe_title}_{pid}")
                if not new_dir.exists():
                    output_dir.rename(new_dir)
                    output_dir = new_dir
                    print(f"  폴더: {output_dir}")

            # 상세 이미지
            image_files = []
            if not args.no_images:
                print("[3/4] 상세페이지 이미지 수집...")
                image_urls = scroll_and_collect_detail_images(page)
                print(f"  발견: {len(image_urls)}장")
                if image_urls:
                    image_files = download_images(image_urls, output_dir, page)
            else:
                print("[3/4] 이미지 수집 스킵")

            # 리뷰
            reviews = []
            if not args.no_reviews:
                print("[4/4] 리뷰 수집...")
                reviews = collect_reviews(page, args.max_review_pages)
                print(f"  수집: {len(reviews)}건")
            else:
                print("[4/4] 리뷰 수집 스킵")

            page.screenshot(path=str(output_dir / "screenshot.png"), full_page=False)
            page.close()
            browser.close()

        save_results(product_info, image_files, reviews, output_dir)
        print(f"\n완료! 결과: {output_dir}/")

    finally:
        # Chrome 종료 (우리가 직접 띄운 경우만)
        if chrome_proc:
            chrome_proc.terminate()
            try:
                chrome_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome_proc.kill()


if __name__ == "__main__":
    main()
