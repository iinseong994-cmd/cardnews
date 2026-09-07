#!/usr/bin/env python3
"""
book_gen.py — 교보문고 크롤링 결과(book.json) → slides.json

쿠팡용 gen.py 와 별개다. 모델 호출·키 확인·JSON 뽑기는 gen.py 것을 그대로 쓴다.

책이 상품과 다른 점
  · 사진이 표지 한 장뿐이다 → photo 슬라이드를 남발하면 같은 표지만 반복된다
  · 대신 **추천사·목차·작가 이야기** 라는, 상품에는 없는 재료가 있다
  · 책 본문은 저작권물이다 → 길게 옮기지 않는다
"""

import json
import re
from pathlib import Path

import gen

ROOT = Path(__file__).resolve().parent.parent


# ── 프롬프트 ────────────────────────────────────────────────

SCHEMA = """{
  "theme": "<테마>",
  "palette": "<팔레트>",
  "slides": [
    {"no":1,"type":"cover","eyebrow":"<판매고·수상 같은 짧은 뱃지>",
     "headline":"<대형문구 줄당 2~4자, \\n으로 줄바꿈, 최대 2줄>",
     "subhead":"<그 문구가 무슨 말인지 한 줄>","image_path":"card_images/cover.jpg",
     "chips":["<뱃지>","<뱃지>","<뱃지>"]},
    {"no":2,"type":"list","eyebrow":"<한 단어>","headline":"<제목 두 줄>",
     "bullets":["<한 문장>","<한 문장>","<한 문장>","<한 문장>"],"subhead":"<마무리 한 줄>"},
    {"no":3,"type":"list","eyebrow":"<한 단어>","headline":"<제목 두 줄>",
     "bullets":["<한 문장>","<한 문장>","<한 문장>","<한 문장>"],"subhead":"<마무리 한 줄>"},
    {"no":4,"type":"list","eyebrow":"<한 단어>","headline":"<제목 두 줄>",
     "bullets":["<한 문장>","<한 문장>","<한 문장>","<한 문장>"],"subhead":"<마무리 한 줄>"},
    {"no":5,"type":"spec","headline":"책 정보",
     "rows":[{"k":"지은이","v":"<값>"},{"k":"옮긴이","v":"<값>"},{"k":"펴낸곳","v":"<값>"},
             {"k":"출간","v":"<값>"},{"k":"분량","v":"<값>"},{"k":"분야","v":"<값>"},
             {"k":"ISBN","v":"<값>"}],
     "chips":["<수상·판매고 뱃지>","<뱃지>"]},
    {"no":6,"type":"quotes","headline":"<제목 두 줄>","image_path":null,
     "quotes":[{"text":"<추천사 원문 그대로>","who":"<추천한 사람·매체>"},
               {"text":"<추천사 원문 그대로>","who":"<추천한 사람·매체>"},
               {"text":"<추천사 원문 그대로>","who":"<추천한 사람·매체>"}]},
    {"no":7,"type":"photo","eyebrow":"독자 반응","headline":"리뷰 **<N>개** · 평점 **<X>**",
     "subhead":"<리뷰에서 많이 나온 말 한 줄>","image_path":"card_images/wide.jpg"},
    {"no":8,"type":"quotes","headline":"<제목>","image_path":null,
     "quotes":[{"text":"<독자 리뷰 원문 그대로>","who":"교보문고 구매자"},
               {"text":"<독자 리뷰 원문 그대로>","who":"교보문고 구매자"},
               {"text":"<독자 리뷰 원문 그대로>","who":"교보문고 구매자"}]},
    {"no":9,"type":"list","headline":"이런 분께\\n맞습니다",
     "bullets":["<대상1>","<대상2>","<대상3>","<이 책이 특히 맞는 상황 한 줄>"],"image_path":null},
    {"no":10,"type":"cta","headline":"<마무리 두 줄>","chips":["<출판사>","<쪽수>","<분야>"],
     "subhead":"<고지문구가 필요하면 여기. 없으면 빈 문자열>"}
  ],
  "caption": "<게시용 캡션. 페르소나 말투. 4~6줄>",
  "hashtags": ["#태그1","#태그2","#태그3","#태그4","#태그5"]
}"""

RULES = """
## 절대 규칙

1. **숫자·사실은 주어진 책 데이터에서만 가져온다.**
   판매 부수·수상·평점·리뷰 수·쪽수·출간일 전부 아래 데이터에 있는 것만 쓴다.
   없는 수치나 순위를 지어내면 허위 표시가 된다.
2. **인용은 원문 그대로.** 추천사도 독자 리뷰도 한 글자도 고치지 않는다.
   길면 문장 단위로 잘라 쓰되 말을 바꾸지 않는다. `who` 에 누가 한 말인지 반드시 적는다.
3. **책 본문을 옮기지 않는다.** 목차의 장 제목은 인용해도 되지만
   본문 문장을 길게 베끼면 저작권 문제가 된다. 요약해서 네 말로 쓴다.
4. **가격을 카드에 넣지 않는다.** 가격은 자주 바뀌는데 카드는 이미지로 굳는다.
5. **image_path 는 `card_images/cover.jpg` 와 `card_images/wide.jpg` 두 개뿐이다.**
   다른 파일명을 지어내지 마라. 사진은 표지 한 장뿐이니 photo 슬라이드는 7번 하나만 쓴다.
   나머지는 전부 글자 카드(list / spec / quotes / cta)로 채운다.
6. **표지 후크는 책 소개·작가 이야기에서 가장 의외인 사실 하나로 잡는다.**
   제목·저자 이름을 크게 쓴 표지는 아무 정보가 없다.
   ❌ "아주 작은 / 습관" ❌ "한강 / 소년이" ← 이름만 크게 쓴 표지
   ⭕ "뼈가 / 30조각" (저자가 사고로 얼굴 뼈 30조각이 났다는 사실)
   ⭕ "6개월 / 만에" (걷지 못하던 사람이 6개월 만에 복귀했다)
   대형 문구는 **한 줄에 2~4자, 최대 2줄.** 길면 잘린다.
7. **2·3·4번 카드는 서로 다른 각도여야 한다.** 같은 얘기를 두 번 쓰지 마라.
   고를 수 있는 각도: 이 책이 나온 배경 / 저자가 겪은 일 / 핵심 주장 /
   책이 제시하는 방법 / 목차에서 보이는 흐름 / 이 책이 받은 평가 / 누가 왜 읽었나
   `eyebrow` 에 그 각도를 한 단어로 적는다. (예: 시작, 핵심, 방법, 배경)
8. **bullets 는 형용사만 늘어놓지 말고 확인된 사실이나 구체적인 문장을 쓴다.**
   ❌ "감동적인 이야기" ❌ "탄탄한 구성" ❌ "깊은 울림"
   ⭕ "고교 야구선수 시절 동료의 배트에 얼굴을 정통으로 맞았다"
   ⭕ "제3법칙 — 쉬워야 한다"
   목차의 장 제목을 그대로 가져오는 것도 좋다. 그 책만의 말이라 힘이 있다.
9. **6번은 추천사 카드다.** 평론가·작가·매체가 한 말을 쓴다.
   추천사가 없으면 출판사 리뷰나 수상 내역에서 가져오고, 그것도 없으면
   6번을 list 로 바꿔 '이 책이 받은 평가' 를 정리한다.
10. **8번은 독자 리뷰 카드다.** 서로 다른 얘기를 하는 리뷰 3개를 고른다.
    리뷰가 2개뿐이면 2개만 쓴다. 없으면 8번을 list 로 바꾼다.
11. **9번은 이 책이 맞는 사람을 쓴다.** 책을 깎는 말은 쓰지 않는다.
    맞지 않는 사람을 굳이 적어야 한다면 흠이 아니라 **용도 한정**으로 쓴다.
    (예: "이론을 더 알고 싶은 분보다, 오늘 당장 할 한 가지를 찾는 분께 맞습니다")
12. **분량을 채운다.** 카드가 비어 보이면 안 된다.
    - `list` 의 bullets 는 **4개**, 각 한 문장 (25~45자)
    - `spec` 의 rows 는 **6~7줄**. 데이터에 있는 항목을 최대한 담는다
    - `quotes` 는 **3개**
    - `chips` — cover 3개, spec 2개, cta 2~3개
    - 모든 list 카드에 `subhead` 를 한 줄 넣는다
13. **JSON만 출력한다.** 설명·코드펜스 없이 `{` 로 시작해 `}` 로 끝낸다.
"""


def _clip(text, n):
    text = (text or "").strip()
    return text[:n] + (" …" if len(text) > n else "")


def book_brief(b):
    """book.json → 프롬프트에 넣을 요약. 긴 구간은 잘라서 넣는다."""
    L = ["## 기본", ""]
    L.append("| 항목 | 값 |")
    L.append("|---|---|")
    for k in ("제목", "저자", "역자", "출판사", "출간일", "판형", "isbn"):
        if b.get(k):
            L.append(f"| {k} | {b[k]} |")
    if b.get("쪽수"):
        L.append(f"| 쪽수 | {b['쪽수']}쪽 |")
    if b.get("평점") is not None:
        L.append(f"| 평점 | {b['평점']} |")
    if b.get("리뷰수") is not None:
        L.append(f"| 리뷰 수 | {b['리뷰수']:,} |")
    if b.get("분야"):
        L.append(f"| 분야 | {' > '.join(b['분야'])} |")
    if b.get("키워드"):
        L.append(f"| 키워드 | {', '.join(b['키워드'])} |")

    parts = [
        ("책 소개 (출판사가 쓴 소개글)", _clip(b.get("책소개"), 2600)),
        ("수상·미디어 추천", _clip(b.get("수상내역"), 700)),
        ("서점 MD 한마디", _clip(b.get("md평"), 600)),
        ("목차", _clip(b.get("목차"), 2600)),
        ("작가 정보", _clip(b.get("작가정보"), 1400)),
        ("추천사 (6번 카드에 원문 그대로 인용)", _clip(b.get("추천사"), 3000)),
        ("출판사 리뷰", _clip(b.get("출판사서평"), 2400)),
    ]
    for head, body in parts:
        if body:
            L += ["", "## " + head, "", body]

    if b.get("ai요약제목"):
        L += ["", "## 교보 AI 리뷰 요약", "",
              "제목: " + b["ai요약제목"], _clip(b.get("ai요약"), 600)]
        if b.get("ai키워드"):
            L.append("리뷰에 많이 나온 말: " + ", ".join(b["ai키워드"]))
    return "\n".join(L)


def reviews_text(b):
    rv = b.get("리뷰") or []
    if not rv:
        return "(가져온 독자 리뷰 없음 — 8번을 list 로 바꿀 것)"
    return "\n".join("- " + r["text"] for r in rv)


def build_prompt(brief, reviews, persona_md, hooks_md, theme, palette, hook_style):
    return f"""너는 책 카드뉴스의 문구를 쓰는 사람이다.
아래 책 데이터와 규칙을 읽고 slides.json 을 만들어라.

# 페르소나 (이 목소리로 쓴다)
{persona_md}

# 후킹멘트 규칙
{hooks_md}

# 이번 카드뉴스의 후크 방향
{hook_style}

# 책 데이터  ← 카드에 들어가는 모든 사실은 여기서만 가져온다
{brief}

# 독자 리뷰 원문 (8번 카드에 그대로 인용)
{reviews}

# 출력 형식
theme 은 "{theme}", palette 는 "{palette}" 로 고정한다.
{SCHEMA}
{RULES}
"""


# ── 결과 정리 ───────────────────────────────────────────────

def review_headline(b):
    n, r = b.get("리뷰수"), b.get("평점")
    if not n:
        return None
    return f"리뷰 **{n:,}개**" + (f" · 평점 **{r}**" if r else "")


def sanitize(data, output_dir, book, theme, palette, disclosure=""):
    """없는 이미지 제거 + 숫자 바로잡기 + 표지 사진 채우기"""
    output_dir = Path(output_dir)
    data["theme"] = theme
    data["palette"] = palette
    head = review_headline(book)

    fixed = []
    for i, sl in enumerate(data.get("slides", []), 1):
        sl["no"] = i

        for field in ("image_path", "cutout"):
            p = sl.get(field)
            if p and not (output_dir / p).exists():
                sl[field] = None

        if sl.get("type") == "cover" and not sl.get("cutout"):
            if (output_dir / "card_images" / "cover.jpg").exists():
                sl["image_path"] = "card_images/cover.jpg"

        if sl.get("type") == "photo":
            if not sl.get("image_path") and (output_dir / "card_images" / "wide.jpg").exists():
                sl["image_path"] = "card_images/wide.jpg"
            if not sl.get("image_path"):
                sl["type"] = "list"            # 사진이 없으면 글자 카드로

        # 리뷰 수·평점은 AI 가 쓴 값을 믿지 않고 크롤 데이터로 덮어쓴다
        if head and sl.get("headline") and re.search(r"리뷰\s*\*{0,2}[\d,]+", sl["headline"]):
            sl["headline"] = head

        # 표지 대형 문구는 2줄까지 (3줄 넘으면 아래 설명과 겹친다)
        if sl.get("type") == "cover" and sl.get("headline"):
            lines = [x for x in sl["headline"].split("\n") if x.strip()]
            if len(lines) > 2:
                lines = lines[:1] + [" ".join(lines[1:])]
            sl["headline"] = "\n".join(lines)

        # 인용이 하나도 없는 quotes 카드는 빈 카드가 된다
        if sl.get("type") == "quotes" and not sl.get("quotes"):
            sl["type"] = "list"

        fixed.append(sl)

    data["slides"] = fixed
    if fixed and fixed[-1].get("type") == "cta":
        fixed[-1]["subhead"] = disclosure or fixed[-1].get("subhead") or ""
    return data


# ── 실행 ────────────────────────────────────────────────────

def generate(output_dir, provider, api_key, model, theme, palette,
             persona, hook_style, disclosure=""):
    output_dir = Path(output_dir)
    bf = output_dir / "book.json"
    if not bf.exists():
        raise gen.ApiError("book.json 이 없습니다. 크롤링이 끝나지 않은 폴더입니다.")
    book = json.loads(bf.read_text(encoding="utf-8"))

    hooks_md = (ROOT / "references" / "hooks.md").read_text(encoding="utf-8")
    pf = ROOT / "references" / "personas" / f"{persona}.md"
    persona_md = pf.read_text(encoding="utf-8") if pf.exists() \
        else "(페르소나 없음 — 담백한 존댓말로 쓴다)"

    prompt = build_prompt(book_brief(book), reviews_text(book),
                          persona_md, hooks_md, theme, palette, hook_style)

    fn = gen.PROVIDERS.get(provider)
    if not fn:
        raise gen.ApiError(f"지원하지 않는 모델: {provider}")
    api_key = gen.check_key(provider, api_key)
    kwargs = {"model": model} if model else {}
    text = fn(prompt, api_key, **kwargs)

    data = sanitize(gen.extract_json(text), output_dir, book, theme, palette, disclosure)
    (output_dir / "slides.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
