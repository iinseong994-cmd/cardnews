#!/usr/bin/env python3
"""
교보문고 책 크롤러  (쿠팡 crawl.py 와 별개 — 서로 건드리지 않는다)

쿠팡과 달리 Akamai 차단이 없어서 헤드리스 브라우저로 그냥 열린다.
그래서 크롤링 중에 Chrome 창이 뜨지 않는다.

사용법:
  python book_crawl.py "https://product.kyobobook.co.kr/detail/S000000610612"
  python book_crawl.py "9788936434120"          # ISBN
  python book_crawl.py "소년이 온다"             # 검색어 (첫 결과)

결과: output/<제목>_<ISBN>/  ├ book.json  ├ book.md  └ cover.jpg
"""

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

DETAIL = "https://product.kyobobook.co.kr/detail/{}"
SEARCH = "https://search.kyobobook.co.kr/search?keyword={}"


# ── 입력 해석 ────────────────────────────────────────────

def resolve_target(arg):
    """URL / ISBN / 검색어 → 교보 상세 URL"""
    arg = arg.strip()

    m = re.search(r"product\.kyobobook\.co\.kr/detail/([A-Z]\d+)", arg)
    if m:
        return DETAIL.format(m.group(1))

    if re.fullmatch(r"[\d-]{10,17}", arg):          # ISBN
        return _first_search_hit(arg.replace("-", ""))

    if arg.startswith("http"):
        return arg

    return _first_search_hit(arg)


def _first_search_hit(keyword):
    """검색 결과 첫 번째 책의 상세 URL. 검색 페이지는 서버렌더라 그냥 받아진다."""
    from urllib.parse import quote
    req = urllib.request.Request(
        SEARCH.format(quote(keyword)),
        headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9",
                 "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=20) as r:
        html = r.read().decode("utf-8", "replace")

    ids = re.findall(
        r"searchResultItemClickEvent\(&#39;상품 제목&#39;,\s*&quot;([A-Z]\d+)&quot;",
        html)
    if not ids:
        ids = re.findall(r"/detail/([A-Z]\d+)", html)
    if not ids:
        raise SystemExit("검색 결과가 없습니다: " + keyword)

    # E... 는 eBook. 종이책(S...)을 우선한다.
    paper = [i for i in ids if i.startswith("S")]
    return DETAIL.format((paper or ids)[0])


# ── 본문 파싱 ────────────────────────────────────────────
# 페이지의 눈에 보이는 텍스트를 통째로 받아 구간을 잘라 쓴다.
# 클래스명이 바뀌어도 화면 문구가 그대로면 계속 동작한다.

SECTIONS = [
    ("책소개",     "책 소개"),
    ("수상내역",   "미디어추천/수상내역"),
    ("md평",       "MD의 한마디"),
    ("목차",       "목차"),
    ("작가정보",   "작가정보"),
    ("추천사",     "추천사"),
    ("출판사서평", "출판사 리뷰"),   # 교보 화면 표기는 '출판사 리뷰'
]

# 위 구간이 끝나는 지점을 알려주는 표지들
STOPS = ["패키지", "이 책과 함께", "함께 구매", "교환/반품", "교환/반품/품절",
         "이 책이 속한 분야", "카테고리", "AI 연관 추천",
         "키워드 Pick", "기본정보", "미리보기", "리뷰 쓰기",
         # 마지막 구간(추천사)이 페이지 바닥까지 흘러가지 않게
         "리뷰", "Klover 리뷰", "북로그 리뷰", "상품문의", "상품정보 제공고시",
         "배송/반품/교환 안내", "고객센터", "회사소개", "이용약관"]


def _cut(body, head, others):
    """head 다음부터, 다른 머리말이나 STOPS 가 나오기 전까지.

    ⚠️ 뒤 표지를 찾을 때는 start 가 아니라 start-1 부터 본다.
       구간이 곧바로 다른 머리말로 시작하는 경우(책 소개 → 수상내역)
       그 앞의 줄바꿈이 start 바로 앞에 있어서 못 찾고 지나쳐 버린다.
    """
    i = body.find("\n" + head + "\n")
    if i < 0:
        return ""
    start = i + len(head) + 2
    end = len(body)
    for mark in others + STOPS:
        j = body.find("\n" + mark + "\n", max(0, start - 1))
        if 0 <= j < end:
            end = j
    return body[start:end].strip() if end > start else ""


def split_intro(region):
    """'책 소개' 구간 안에는 세 덩어리가 머리말 없이 이어져 있다.

        [미디어추천/수상내역 … 펼치기]  [MD의 한마디 … 날짜]  [출판사 보도자료]

    앞의 두 덩어리는 시작 표지가 있으니 그것만 도려내고
    남는 것을 진짜 책 소개로 본다.
    """
    award = md = ""
    spans = []

    i = region.find("미디어추천/수상내역")
    if i >= 0:
        j = region.find("\n펼치기\n", i)
        end = (j + 5) if j > 0 else len(region)
        award = region[i + len("미디어추천/수상내역"):end].replace("\n펼치기", "").strip()
        spans.append((i, end))

    i = region.find("MD의 한마디")
    if i >= 0:
        m = re.search(r"\n\d{4}\.\d{2}\.\d{2}\n", region[i:])
        end = (i + m.end()) if m else len(region)
        md = region[i + len("MD의 한마디"):(i + m.start()) if m else end].strip()
        spans.append((i, end))

    keep = region
    for a, b in sorted(spans, reverse=True):
        keep = keep[:a] + keep[b:]

    return keep.strip(), award, md


# 구간 뒤에 딸려오는 '이런 책도 있어요' 상품 목록의 시작 표지.
# 이 줄이 통째로 한 줄일 때만 자른다 (본문 안의 같은 낱말은 안 건드린다).
CAROUSEL = {"국내도서", "외국도서", "서양도서", "eBook", "오디오북", "핫트랙스",
            "공지사항", "당첨자발표", "더보기", "CASTing", "선물하기",
            "장바구니", "바로드림", "주문하기", "TOP", "이벤트"}


def strip_carousel(text):
    lines = text.split("\n")
    for n, l in enumerate(lines):
        if l.strip() in CAROUSEL:
            lines = lines[:n]
            break
    # 접기 버튼 글자가 끝에 남는다
    while lines and lines[-1].strip() in ("펼치기", "접기", ""):
        lines.pop()
    return "\n".join(lines).strip()


def parse_body(body):
    out = {}
    heads = [h for _, h in SECTIONS]
    for key, head in SECTIONS:
        out[key] = strip_carousel(_cut(body, head, [x for x in heads if x != head]))

    # 책 소개 구간은 통째로 받아서 안에서 나눈다
    intro = _cut(body, "책 소개",
                 ["목차", "작가정보", "추천사", "출판사 리뷰"])
    if intro:
        blurb, award, md = split_intro(intro)
        out["책소개"] = strip_carousel(blurb)
        out["수상내역"] = strip_carousel(award)
        out["md평"] = strip_carousel(md)

    # ── 기본정보
    m = re.search(r"ISBN\s*\n\s*([0-9Xx]{10,13})", body)
    out["isbn"] = m.group(1) if m else ""

    m = re.search(r"발행\(출시\)일자\s*\n\s*(\d{4}년\s*\d{1,2}월\s*\d{1,2}일)", body)
    out["출간일"] = re.sub(r"\s+", " ", m.group(1)) if m else ""

    m = re.search(r"쪽수/크기\s*\n\s*(\d+)\s*쪽", body)
    out["쪽수"] = int(m.group(1)) if m else None

    m = re.search(r"쪽수/크기\s*\n\s*\d+\s*쪽\s*\|\s*([^\n/]+)", body)
    out["판형"] = m.group(1).strip() if m else ""

    # ── 저자 / 역자 / 출판사
    # 화면에는 이렇게 이어져 있다 (번역서는 역자가 중간에 낀다):
    #   제임스 클리어 / 저자(글) / 이한이 / 번역 / 비즈니스북스 / · / 2019년 02월 26일
    # 그래서 "출판사는 저자(글) 바로 다음" 이 아니라
    # "출간일 바로 앞" 으로 잡아야 역자와 안 헷갈린다.
    ROLES = ("저자(글)", "저자", "지은이", "번역", "역자", "그림", "옮김",
             "감수", "편저", "엮음", "사진")
    lines = [l.strip() for l in body.split("\n")]
    out["저자"] = ""
    out["역자"] = ""
    out["출판사"] = ""
    for n, l in enumerate(lines):
        if l in ("저자(글)", "저자", "지은이") and n > 0:
            out["저자"] = lines[n - 1]
            for k in range(n + 1, min(n + 14, len(lines))):
                if lines[k] in ("번역", "역자", "옮김") and k > 0:
                    out["역자"] = lines[k - 1]
                if re.match(r"^\d{4}년\s*\d{1,2}월\s*\d{1,2}일$", lines[k]):
                    for b in range(k - 1, n, -1):        # 출간일 바로 앞
                        v = lines[b]
                        if v and v != "·" and v not in ROLES:
                            out["출판사"] = v
                            break
                    break
            break

    # ── 평점 · 리뷰 수
    m = re.search(r"\n(\d{1,2}\.\d)\n리뷰\s*([\d,]+)", body)
    if m:
        out["평점"] = float(m.group(1))
        out["리뷰수"] = int(m.group(2).replace(",", ""))
    else:
        out["평점"] = None
        out["리뷰수"] = None

    # ── 가격 — "10%\n13,500\n원\n15,000\n원" 형태
    m = re.search(r"\n([\d,]{4,})\s*\n원\s*\n([\d,]{4,})\s*\n원", body)
    if m:
        out["판매가"] = int(m.group(1).replace(",", ""))
        out["정가"] = int(m.group(2).replace(",", ""))
    else:
        m = re.search(r"\n([\d,]{4,})원\n", body)
        out["판매가"] = int(m.group(1).replace(",", "")) if m else None
        out["정가"] = None

    # ── 분류 / 키워드
    cat = _cut(body, "이 책이 속한 분야", heads)
    out["분야"] = [c for c in cat.split("\n") if c][:5]

    kw = _cut(body, "키워드 Pick", [])
    out["키워드"] = [k for k in kw.split("\n")
                    if k and k not in ("툴팁 열기 버튼", "펼치기")][:8]

    # ── AI 리뷰 요약 (교보가 리뷰를 모아 정리해 준 것)
    ai = _cut(body, "AI 리뷰 요약 Beta", [])
    # 요약 다음에 바로 리뷰 목록이 붙는다. 목록 시작 표지에서 끊는다.
    for mark in ("\n전체\n", "\n구매한 리뷰만 보기\n", "\n최신 순\n"):
        j = ai.find(mark)
        if j > 0:
            ai = ai[:j]
    ai_lines = [l for l in ai.split("\n") if l and l != "툴팁 열기 버튼"]
    tags = [l for l in ai_lines if l.startswith("#")]
    text = [l for l in ai_lines if not l.startswith("#")]
    out["ai요약제목"] = text[0] if text else ""
    out["ai요약"] = " ".join(text[1:])[:600] if len(text) > 1 else ""
    out["ai키워드"] = [t.lstrip("#") for t in tags][:6]

    # ── 구매 리뷰 건수 (종이책 기준)
    m = re.search(r"종이책\s*\n구매 리뷰\s*([\d,]+)건", body)
    out["종이책리뷰수"] = int(m.group(1).replace(",", "")) if m else None

    return out


# 리뷰 한 건의 생김새:
#   종이책 / 구매자 / 아이디 / 날짜 / 신고 / 차단 / <본문> / <추천수> / 댓글 0
REVIEW_RE = re.compile(
    r"\n신고\n차단\n(.+?)\n\d+\n댓글\s*\d+", re.DOTALL)


def parse_reviews(body):
    """리뷰 본문만 뽑는다. 없으면 빈 리스트 — 지어내지 않는다."""
    seen = set()
    out = []
    for m in REVIEW_RE.finditer(body):
        t = re.sub(r"\s+", " ", m.group(1)).strip()
        if len(t) < 12 or t in seen:
            continue
        seen.add(t)
        out.append({"text": t})
    # 길수록 카드에 쓸 말이 있다
    out.sort(key=lambda r: -len(r["text"]))
    return out[:15]


# ── 크롤 ─────────────────────────────────────────────────

def crawl(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="ko-KR", user_agent=UA,
                                viewport={"width": 1400, "height": 1000})
        print("  여는 중: " + url)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)

        # 지연 로딩되는 아래쪽(목차·작가정보·추천사)까지 내려간다
        for _ in range(10):
            page.mouse.wheel(0, 2600)
            page.wait_for_timeout(400)
        page.wait_for_timeout(1500)

        def meta(prop):
            el = page.query_selector('meta[property="%s"]' % prop)
            return el.get_attribute("content") if el else ""

        title = (meta("og:title") or page.title() or "").replace(" - 교보문고", "").strip()
        cover = meta("og:image")

        body = re.sub(r"\n{2,}", "\n", page.inner_text("body"))
        data = parse_body(body)
        reviews = parse_reviews(body)

        browser.close()

    data["제목"] = title
    data["표지URL"] = upscale_cover(cover, data.get("isbn"))
    data["교보링크"] = url
    data["리뷰"] = reviews
    data["crawled_at"] = datetime.now().isoformat(timespec="seconds")
    return data


def upscale_cover(url, isbn):
    """og:image 는 400px. 교보는 같은 경로에서 큰 사이즈도 준다."""
    if url and "/sih/fit-in/" in url:
        return re.sub(r"/fit-in/\d+x\d+/", "/fit-in/1200x0/", url)
    if isbn:
        return ("https://contents.kyobobook.co.kr/sih/fit-in/1200x0/pdt/%s.jpg" % isbn)
    return url or ""


def download(url, dest):
    if not url:
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            dest.write_bytes(r.read())
        return dest.stat().st_size > 3000
    except Exception as e:
        print("  표지 내려받기 실패: %s" % e)
        return False


# ── 저장 ─────────────────────────────────────────────────

def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]', "", s).strip()[:60] or "book"


def to_markdown(d):
    L = ["# " + d["제목"], ""]
    L.append("- 저자: " + (d.get("저자") or "-"))
    if d.get("역자"):
        L.append("- 옮긴이: " + d["역자"])
    L.append("- 출판사: " + (d.get("출판사") or "-"))
    L.append("- 출간일: " + (d.get("출간일") or "-"))
    L.append("- 쪽수: %s쪽  (%s)" % (d.get("쪽수") or "-", d.get("판형") or "-"))
    L.append("- ISBN: " + (d.get("isbn") or "-"))
    if d.get("정가"):
        L.append("- 정가 %s원 / 판매가 %s원" % (format(d["정가"], ","),
                                              format(d.get("판매가") or 0, ",")))
    if d.get("평점"):
        L.append("- 평점 %s · 리뷰 %s건" % (d["평점"], format(d.get("리뷰수") or 0, ",")))
    if d.get("분야"):
        L.append("- 분야: " + " > ".join(d["분야"]))
    if d.get("키워드"):
        L.append("- 키워드: " + ", ".join(d["키워드"]))
    L.append("")
    for key, head in SECTIONS:
        if d.get(key):
            L += ["## " + head, "", d[key], ""]
    if d.get("ai요약제목"):
        L += ["## AI 리뷰 요약 (교보)", "", "**" + d["ai요약제목"] + "**", ""]
        if d.get("ai요약"):
            L += [d["ai요약"], ""]
        if d.get("ai키워드"):
            L += ["키워드: " + ", ".join(d["ai키워드"]), ""]
    if d.get("리뷰"):
        L += ["## 독자 리뷰", ""]
        L += ["- " + r["text"] for r in d["리뷰"]]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="교보 URL / ISBN / 검색어")
    ap.add_argument("--out", default="output", help="결과 폴더 (기본 output)")
    args = ap.parse_args()

    url = resolve_target(args.target)
    data = crawl(url)

    if not data["제목"]:
        raise SystemExit("제목을 못 읽었습니다. 링크를 확인해 주세요.")

    folder = Path(args.out) / ("%s_%s" % (safe_name(data["제목"]),
                                          data.get("isbn") or "noisbn"))
    folder.mkdir(parents=True, exist_ok=True)

    ok = download(data["표지URL"], folder / "cover.jpg")
    data["표지파일"] = "cover.jpg" if ok else ""

    (folder / "book.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "book.md").write_text(to_markdown(data), encoding="utf-8")

    print("")
    print("  제목    " + data["제목"])
    print("  저자    %s%s / %s" % (
        data.get("저자") or "-",
        (" (옮김 " + data["역자"] + ")") if data.get("역자") else "",
        data.get("출판사") or "-"))
    print("  출간    %s  %s쪽" % (data.get("출간일") or "-", data.get("쪽수") or "-"))
    print("  평점    %s · 리뷰 %s건" % (data.get("평점") or "-",
                                       format(data.get("리뷰수") or 0, ",")))
    print("  표지    " + ("받음" if ok else "실패"))
    for key, head in SECTIONS:
        n = len(data.get(key) or "")
        print("  %-14s %5d자%s" % (head, n, "" if n else "   ← 없음"))
    print("  독자리뷰 %d건" % len(data["리뷰"]))
    print("\n  저장 → %s" % folder)
    # 서버가 결과 폴더를 확실히 알 수 있게.
    # 수정시각으로 짐작하면 이미 받아둔 책을 다시 받을 때 엉뚱한 폴더를 집는다.
    print("RESULT_DIR=" + str(folder.resolve()))


if __name__ == "__main__":
    main()
