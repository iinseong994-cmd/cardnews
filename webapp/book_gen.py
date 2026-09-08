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
import book_theme
import bg_theme

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
    {"no":2,"type":"statement","headline":"<이 책이 어떤 책인지 한 문장. 두 줄로 끊는다>",
     "subhead":"<그 한 문장을 받쳐주는 한 줄>","image_path":null},
    {"no":3,"type":"list","eyebrow":"<한 단어>","headline":"<제목 두 줄>",
     "bullets":["<한 문장>","<한 문장>","<한 문장>","<한 문장>"],"subhead":"<마무리 한 줄>"},
    {"no":4,"type":"list","eyebrow":"지은이","headline":"<제목 두 줄>",
     "bullets":["<한 문장>","<한 문장>","<한 문장>","<한 문장>"],"subhead":"<마무리 한 줄>"},
    {"no":5,"type":"quotes","headline":"<짧은 제목 한 줄>","image_path":null,
     "quotes":[{"text":"<책에서 뽑은 한 문장. 40~70자. 원문 그대로>",
                "who":"<어디서 가져왔는지 — 예: 『제목』 중에서>"}]},
    {"no":6,"type":"quotes","headline":"<제목 두 줄>","image_path":null,
     "quotes":[{"text":"<추천사 원문 그대로>","who":"<추천한 사람·매체>"},
               {"text":"<추천사 원문 그대로>","who":"<추천한 사람·매체>"},
               {"text":"<추천사 원문 그대로>","who":"<추천한 사람·매체>"}]},
    {"no":7,"type":"photo","eyebrow":"독자 반응","headline":"리뷰 **<N>개** · 평점 **<X>**",
     "subhead":"<리뷰에서 많이 나온 말 한 줄>","image_path":"card_images/wide.png"},
    {"no":8,"type":"quotes","headline":"<제목>","image_path":null,
     "quotes":[{"text":"<독자 리뷰 원문 그대로>","who":"교보문고 구매자"},
               {"text":"<독자 리뷰 원문 그대로>","who":"교보문고 구매자"},
               {"text":"<독자 리뷰 원문 그대로>","who":"교보문고 구매자"}]},
    {"no":9,"type":"list","eyebrow":"<한 단어>","headline":"<제목 두 줄>",
     "bullets":["<한 문장>","<한 문장>","<한 문장>","<한 문장>"],
     "subhead":"<이런 분께 권한다는 한 줄>","image_path":null},
    {"no":10,"type":"cta","headline":"<읽는 사람에게 던지는 물음. 두 줄. 물음표로 끝난다>",
     "chips":["#해시태그","#해시태그","#해시태그"],
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
7. **카드마다 다른 각도여야 한다. 같은 사실을 두 번 쓰지 마라.**
   3번에 "부자가 되는 세 가지 방법" 을 썼으면 4번에 또 쓰면 안 된다.
   쓸 것이 모자라면 카드를 줄이지 말고 **목차를 더 파고들어** 다른 대목을 찾아라.

   목차의 장 제목은 bullets 재료로 아주 좋다. 그 책만 쓸 수 있는 말이라 힘이 있다.
   다만 `Part 2. 두 번째 법칙` 처럼 번호만 있는 줄은 빼고, 뜻이 담긴 제목만 골라라.

   **책 정보(ISBN·쪽수·판형·출판사)는 카드에 쓰지 않는다.**
   읽는 사람이 궁금해하는 정보가 아니고, 열 장 중 한 장을 거기 쓰기엔 아깝다.
   저자 이름은 4번(지은이) 카드에서만 다룬다.

## 카드별로 해야 할 것

**2번 — 한 문장으로 이 책은**
   표지를 넘긴 사람이 제일 먼저 보는 카드다. 여기서 "아 이런 책이구나" 가 안 오면 나간다.
   설명을 늘어놓지 말고 **한 문장으로 못 박아라.** bullets 를 쓰지 마라.
   ⭕ "결심이 아니라\\n시스템을 만드는 책입니다"
   ⭕ "2027년에 돈이\\n어디로 흐르는지 봅니다"
   ❌ "이 책은 습관에 관한 여러 이야기를 담고 있습니다" ← 아무 말도 안 한 것
   두 줄로 끊고, `subhead` 에 그 문장을 받쳐주는 한 줄을 붙인다.

**5번 — 이 책의 한 문장**
   열 장 중 제일 오래 붙잡는 카드다. 책이 하려는 말을 담은 한 문장을 크게 하나만 보여준다.
   · 40~70자. 두 문장이 되면 힘이 빠진다
   · **반드시 주어진 데이터 안에 있는 문장을 그대로** 가져온다 (책 소개·출판사 리뷰·추천사·MD 한마디)
     지어내거나 다듬어 쓰면 안 된다. 없으면 5번을 list 로 바꿔라
   · `who` 에 어디서 온 말인지 적는다 (예: 『돈의 속성』 중에서 · 지은이 김승호)
   · `headline` 은 짧게 한 줄 (예: "이 책은 이렇게 말합니다")
   ⭕ "돈은 인격체다. 함부로 대하는 사람에게는 돈이 오래 머물지 않는다"
   ❌ "이 책은 돈의 속성에 대해 다룬다" ← 설명이지 문장이 아니다

**6번 — 추천사, 없으면 두 번째 문장**
   추천사 데이터가 있으면 이름 있는 사람·매체의 말 3개를 원문 그대로 쓴다.
   **추천사가 없으면 5번과 같은 모양으로 '두 번째 문장' 을 하나 더 보여줘라.**
   (quotes 하나짜리. 5번과 다른 대목에서 골라야 한다)
   문장도 더 없으면 그때 list 로 바꿔 '이 책이 받은 평가' 를 정리한다.

**9번 — 읽고 나면 / 남는 것**
   여기가 이 카드뉴스에서 **유일하게 사람 목소리가 들어가는 자리**다.
   앞의 카드들은 전부 인용과 사실이라, 이 카드가 없으면 안내문처럼 읽힌다.
   책을 요약하지 말고 **읽고 나서 무엇이 달라지는지** 를 써라.
   `subhead` 에 이런 분께 권한다는 한 줄을 붙인다.
   (성격별로 누구 목소리인지는 맨 아래 지침을 따른다)

**10번 — 물음으로 닫는다**
   "만나보세요" 로 끝나면 거기서 대화가 끝난다. **읽는 사람에게 물어라.**
   책의 주제를 자기 이야기로 끌어오는 물음이어야 한다. 물음표로 끝낸다.
   ⭕ "여러분은 돈을\\n어떻게 대하고 계신가요?"
   ⭕ "2주를 못 넘긴 결심,\\n뭐가 있으세요?"
   ❌ "지금 바로 만나보세요" ❌ "댓글 남겨주세요" ← 물음이 아니다
8. **bullets 에는 책 "안의 내용" 을 쓴다. 책 "에 대한 설명" 을 쓰지 마라.**

   제일 흔한 실패가 목차를 남의 말로 바꿔 적는 것이다. 이러면 아무 정보가 없다.
   ❌ "돈을 모으지 못하는 이유를 **설명**" ❌ "부자가 되는 세 가지 방법을 **제시**"
   ❌ "돈을 다루는 네 가지 능력을 **소개**" ❌ "~에 대해 **강조**" ❌ "~를 **다룸**"
   → `설명·제시·소개·강조·다룸·언급·분석` 으로 끝나는 줄은 **한 줄도 쓰지 마라.**

   그 자리에 **그 책이 실제로 하는 말**을 넣어라.
   ⭕ "돈은 인격체다 — 함부로 대하면 떠난다"
   ⭕ "제3법칙 — 쉬워야 한다"
   ⭕ "고교 야구선수 시절 동료의 배트에 얼굴을 정통으로 맞았다"

   형용사만 늘어놓는 것도 안 된다.
   ❌ "감동적인 이야기" ❌ "탄탄한 구성" ❌ "깊은 울림"

   **목차의 장 제목을 그대로 가져오는 게 가장 안전하고 힘이 있다.**
   그 책만 쓸 수 있는 말이기 때문이다.
9. **6번은 추천사 카드다.** 평론가·작가·매체처럼 **이름이 있는 누군가가 한 말**을 옮긴다.

   **추천사 데이터가 비어 있으면 6번을 `list` 로 바꿔라.**
   '이 책이 받은 평가'(수상·쇄수·판매 부수·번역 출간·미디어 소개)를 bullets 로 정리한다.
   없는 사람의 말을 지어내면 안 되고, `who` 에 "출판사" · "AI 리뷰" 를 적는 것도 안 된다.
   그건 인용이 아니라 요약문이다. **인용은 누가 했는지 이름을 댈 수 있을 때만 쓴다.**
10. **8번은 독자 리뷰 카드다.** 서로 다른 얘기를 하는 리뷰 3개를 고른다.
    리뷰가 2개뿐이면 2개만 쓴다. 없으면 8번을 list 로 바꾼다.
11. **책을 깎는 말은 쓰지 않는다.** (9번·10번이 어떤 카드인지는 맨 아래 성격별 지침을 따른다)
    한계를 굳이 적어야 한다면 흠이 아니라 **용도 한정**으로 쓴다.
    (예: "이론을 더 알고 싶은 분보다, 오늘 당장 할 한 가지를 찾는 분께 맞습니다")
12. **분량을 채운다.** 카드가 비어 보이면 안 된다.
    - `list` 의 bullets 는 **4개**, 각 한 문장 (25~45자)
    - `quotes` 는 **3개**
    - 모든 list 카드에 `subhead` 를 한 줄 넣는다
    - `chips` — cover 3개(수상·판매고 같은 자랑거리), cta 3개(해시태그)

13. **마지막 카드의 chips 는 해시태그다.** `#` 을 붙여 3개 쓴다.
    그대로 복사해 게시글에 붙일 수 있어야 하므로, 사람들이 실제로 검색하는 말을 쓴다.
    책 데이터의 키워드·분야에서 가져오고, 붙여 쓴다(띄어쓰기 없이).
    ⭕ `#책추천` `#자기계발` `#대화의기술` `#말하기` `#커뮤니케이션`
    ❌ `#북플레저` (출판사 이름) ❌ `#328쪽` (쪽수) ❌ `#자기계발서적추천베스트`
    출판사 이름·쪽수·판형은 해시태그로 쓰지 않는다. 아무도 그걸로 찾지 않는다.
14. **JSON만 출력한다.** 설명·코드펜스 없이 `{` 로 시작해 `}` 로 끝낸다.
"""


### 배경 사진 테마 — 10장 ###################################################
# 사진 위 빈 칸에 글자를 얹는다. 칸이 좁아서 **짧게** 써야 한다.
# 칸 자리와 배경은 webapp/bg_theme.py 가 붙인다.

SCHEMA_BG = """{
  "theme": "bg",
  "palette": "<배경 테마>",
  "slides": [
    {"no":1,"kicker":"BOOK REVIEW","headline":"<책 제목 그대로>",
     "note":"<지은이 · 펴낸곳 · 쪽수>"},
    {"no":2,"kicker":"한 문장으로","headline":"<이 책이 무슨 책인지 한 문장. \\\\n 으로 두 줄>",
     "note":"<받쳐주는 한 줄. 45자 안쪽>"},
    {"no":3,"kicker":"이 책이 하는 말","headline":"<제목 두 줄>",
     "lines":["<한 줄 25~35자>","<한 줄>","<한 줄>"]},
    {"no":4,"kicker":"책의 한 문장","headline":"<책에서 뽑은 문장. \\\\n 으로 2~3줄. 원문 그대로>",
     "note":"— 『<책 제목>』 중에서"},
    {"no":5,"kicker":"지은이","headline":"<지은이를 한 마디로. 두 줄>",
     "lines":["<한 줄>","<한 줄>","<한 줄>"]},
    {"no":6,"kicker":"<한 단어>","headline":"<제목 두 줄>",
     "lines":["<한 줄>","<한 줄>","<한 줄>"]},
    {"no":7,"kicker":"이런 분께","headline":"이런 분께\\\\n권합니다",
     "lines":["<어떤 사람인지 한 줄>","<한 줄>","<한 줄>"]},
    {"no":8,"kicker":"독자 리뷰","headline":"<독자 리뷰 원문. \\\\n 으로 2~3줄>",
     "note":"<리뷰 수와 평점 한 줄>"},
    {"no":9,"kicker":"<한 단어>","headline":"<제목 두 줄>",
     "lines":["<한 줄>","<한 줄>","<한 줄>"]},
    {"no":10,"kicker":"CLOSING","headline":"<읽는 사람에게 던지는 물음. 두 줄. 물음표로 끝>",
     "note":"<한 줄 안내>"}
  ],
  "caption": "<게시용 캡션. 4~6줄>",
  "hashtags": ["#태그1","#태그2","#태그3","#태그4","#태그5"]
}"""

RULES_BG = """
## 절대 규칙

1. **짧게 써라.** 사진 위 빈 칸에 얹는 카드라 자리가 좁다. 길면 글자가 깨알이 된다.
   · `headline` — 줄당 **10~16자**, `\\\\n` 으로 직접 끊는다. 최대 3줄
   · `lines` — 한 줄 **25~35자**, 세 줄
   · `note` — **45자 안쪽** 한 줄
   길이를 넘기면 카드가 망가진다. 다른 규칙보다 이게 먼저다.
2. **숫자·사실은 주어진 책 데이터에서만.** 없는 수상·판매고를 지어내면 허위 표시가 된다.
3. **4번과 8번은 원문 그대로 인용한다.** 다듬거나 지어내면 안 된다.
   · 4번 — 책 소개·출판사 리뷰·MD 한마디 안에 실제로 있는 문장
   · 8번 — 독자 리뷰 하나. note 에 리뷰 수와 평점
4. **1번 headline 은 책 제목 그대로**다.
5. **책 정보(ISBN·판형)와 가격은 쓰지 않는다.**
6. **6번은 이 책이 받은 평가·화제성**을 쓴다 (수상·미디어 소개·판매고).
   자료가 없으면 목차에서 이 책이 다루는 것을 뽑아 쓴다.
7. **9번이 유일하게 사람 목소리가 들어가는 자리다.**
   책을 요약하지 말고 읽고 나서 무엇이 달라지는지를 써라.
8. **10번은 물음으로 닫는다.** 물음표로 끝낸다.
9. **카드마다 다른 얘기를 해라.** 3번에서 한 말을 6번에서 또 하지 마라.
10. **JSON만 출력한다.** 설명·코드펜스 없이 `{` 로 시작해 `}` 로 끝낸다.
"""


### 북리뷰 테마 — 10장 구성 ################################################
# 카드 **모양**은 받은 PPTX 템플릿에서 가져오고,
# 카드 **순서와 내용**은 우리가 정한 10장 흐름을 따른다.
# PPT 가 8장이라고 8장으로 만들면 정해둔 흐름이 깨진다.
#
# 템플릿이 주는 여덟 가지 모양을 열 자리에 나눠 쓴다.
#   cover · oneline · ideas · quote · insight · quote · foryou · quote · afterword · closing

SCHEMA_10 = """{
  "theme": "review",
  "palette": "<팔레트>",
  "slides": [
    {"no":1,"type":"cover",
     "eyebrow":"<이 책이 무엇에 대한 책인지 한 줄. 20~28자>",
     "headline":"<책 제목 그대로. 길면 \\n 으로 두 줄>"},

    {"no":2,"type":"oneline","headline":"이 책을 한 문장으로",
     "line":"<이 책이 무슨 책인지 한 문장. \\n 으로 2~3줄. 줄당 8~12자>",
     "subhead":"<그 문장을 받쳐주는 두 줄>",
     "note":"<작은 상자에 들어갈 짧은 말 두 줄>"},

    {"no":3,"type":"ideas","headline":"이 책이 하는 말",
     "points":[{"k":"<주제 8~14자>","v":"<한 문장 25~35자>"},
               {"k":"<주제>","v":"<설명>"},
               {"k":"<주제>","v":"<설명>"}]},

    {"no":4,"type":"quote",
     "line":"<이 책의 한 문장. \\n 으로 2~3줄. 원문 그대로>",
     "who":"<지은이, 『책 제목』>",
     "subhead":"<그 문장에 대한 두 줄>"},

    {"no":5,"type":"insight",
     "headline":"<지은이를 한 마디로. \\n 으로 두 줄>",
     "body":"<지은이가 어떤 사람인지 두 줄>",
     "callout":"<어두운 상자에 들어갈 문장. \\n 으로 세 줄. 줄당 10~14자>",
     "close":"<마무리 두 줄>"},

    {"no":6,"type":"quote",
     "line":"<추천사 원문 그대로. 없으면 이 책의 두 번째 문장. \\n 으로 2~3줄>",
     "who":"<추천한 사람·매체>",
     "subhead":"<두 줄>"},

    {"no":7,"type":"foryou","headline":"이런 분께 추천해요",
     "points":[{"k":"<어떤 사람인지 앞 구절>","v":"<뒤 구절>"},
               {"k":"<앞 구절>","v":"<뒤 구절>"},
               {"k":"<앞 구절>","v":"<뒤 구절>"}]},

    {"no":8,"type":"quote",
     "line":"<독자 리뷰 원문 그대로. \\n 으로 2~3줄>",
     "who":"교보문고 구매자",
     "subhead":"<리뷰 수와 평점을 알려주는 한 줄>"},

    {"no":9,"type":"afterword","headline":"<제목 한 줄>",
     "body":"<두 줄>","body2":"<세 줄>",
     "close":"<크게 들어갈 마무리. \\n 으로 두 줄. 줄당 8~12자>"},

    {"no":10,"type":"closing",
     "eyebrow":"<마무리 인사 두 줄>",
     "headline":"<읽는 사람에게 던지는 물음. \\n 으로 두 줄. 물음표로 끝>",
     "subhead":"<한 줄 안내>"}
  ],
  "caption": "<게시용 캡션. 4~6줄>",
  "hashtags": ["#태그1","#태그2","#태그3","#태그4","#태그5"]
}"""

RULES_10 = """
## 절대 규칙

1. **숫자·사실은 주어진 책 데이터에서만.** 없는 수상·판매고·순위를 지어내면 허위 표시가 된다.
2. **인용(4·6·8번)은 원문 그대로.** 주어진 데이터 안에 실제로 있는 문장만 쓴다.
   다듬거나 지어내면 안 된다. `who` 에 누가 한 말인지 밝힌다.
   · 4번 — 책이 하려는 말을 담은 한 문장 (책 소개·출판사 리뷰·MD 한마디에서)
   · 6번 — 이름 있는 사람·매체의 추천사. **추천사가 없으면 4번과 다른 대목에서 문장을 하나 더** 고른다
   · 8번 — 독자 리뷰 하나. subhead 에 리뷰 수와 평점을 적는다
3. **책 본문을 길게 옮기지 않는다.** 한 문장까지다.
4. **가격·책 정보(ISBN·쪽수·판형)는 카드에 쓰지 않는다.**
5. **1번 headline 은 책 제목 그대로**다. 후크는 eyebrow 에 쓴다.
   ⭕ "조금 느려도 괜찮은 삶에 대하여" ❌ "베스트셀러 화제작" ← 아무 정보가 없다
6. **줄 길이를 지켜라.** 칸이 정해진 템플릿이라 길면 넘친다.
   · 2번 `line`, 5번 `callout`, 9번 `close`, 10번 `headline` — **줄당 8~14자**, `\\n` 으로 직접 끊는다
   · 3번·7번 `k` 는 8~14자, `v` 는 25~35자 한 문장
   · 4·6·8번 `line` 은 2~3줄, 줄당 10~16자
7. **카드마다 다른 얘기를 해라.** 3번에서 한 말을 5번에서 또 하지 마라.
8. **책에 대한 설명 말고 책 안의 말을 써라.**
   ❌ "~를 설명한다" "~를 제시한다" "감동적인 이야기"
   ⭕ 목차의 장 제목, 저자가 겪은 일, 책이 내놓는 구체적인 방법
9. **9번이 유일하게 사람 목소리가 들어가는 자리다.**
   앞 카드가 전부 사실과 인용이라, 여기가 없으면 안내문처럼 읽힌다.
   책을 요약하지 말고 **읽고 나서 무엇이 달라지는지**를 써라.
10. **10번은 물음으로 닫는다.** 물음표로 끝낸다.
11. **JSON만 출력한다.** 설명·코드펜스 없이 `{` 로 시작해 `}` 로 끝낸다.
"""


### 카드 성격 ############################################################
# 같은 책이라도 **누가 올리느냐**에 따라 말이 달라져야 한다.
#   review — 읽은 사람이 남에게 권한다 (개인 계정·파트너스)
#   promo  — 만든 사람이 자기 책을 알린다 (출판사 공식 계정)
# 구조(10장)는 같고 목소리와 몇 장의 성격만 바뀐다.

MODES = {
    "review": {
        "name": "리뷰형",
        "voice": "(아래 페르소나의 목소리로 쓴다)",
        "stance": """너는 **이 책을 읽고 남에게 권하는 사람**이다.
출판사가 아니라 독자 편에 서서 쓴다. 좋았던 점을 말하되 광고처럼 들리면 안 된다.""",
        "s9": """9번은 **읽은 사람으로서 남은 것**을 쓴다. 페르소나의 목소리 그대로.
줄거리 요약이 아니라 '읽고 나서 뭐가 달라졌는지' 다.
확인되지 않은 사실을 지어내면 안 되지만, **느낌과 해석은 네 말로 써도 된다.**
⭕ "결심을 안 하게 됐어요. 대신 자리를 바꿨습니다"
❌ "이 책은 네 가지 법칙을 소개합니다" ← 앞에서 이미 한 말
subhead 에 이런 분께 권한다는 한 줄을 붙인다.""",
        "s10": """10번은 물음으로 닫되, 링크가 어디 있는지도 알린다.
headline 을 물음으로 쓰고, 링크 안내는 subhead 나 캡션에 넣는다.""",
    },
    "promo": {
        "name": "홍보형",
        "voice": """**출판사 공식 계정의 목소리**로 쓴다.
· 담백한 존댓말. 차분하고 자신 있게. 호들갑스러운 감탄사·이모지 남발 금지
· '저희가 만든 책' 이라는 자리에서 말한다. 독자인 척하지 않는다
· 파는 말('강추', '지금 사세요')이 아니라 **알리는 말**을 쓴다""",
        "stance": """너는 **이 책을 만든 출판사**다. 자기 책을 세상에 알리는 카드뉴스를 쓴다.
읽는 사람에게 '이런 책이 나왔고, 왜 지금 이 책인지' 를 전한다.

홍보형에서 특히 살릴 것 — 이게 출판사가 가진 무기다
  · **왜 지금 이 책인가** (책이 답하려는 물음, 나온 배경)
  · **지은이가 누구인가** (경력·이력이 곧 신뢰다)
  · **이미 받은 평가** (수상·쇄수·판매 부수·번역 출간·미디어 소개)
  · **목차로 보여주는 알맹이** (무엇이 들어 있는지 구체적으로)

절대 하지 않는 것
  · 다른 책과 비교하거나 깎아내리기
  · '최고의' '유일한' '단 하나의' 같은 단정 — 데이터에 있는 사실만
  · 독자 리뷰를 출판사가 쓴 것처럼 섞기""",
        "s9": """9번은 **만든 사람의 말**이다. 이 책을 왜 냈는지, 무엇을 전하고 싶었는지.
출판사 리뷰가 곧 출판사가 직접 쓴 글이니 거기서 가져와 정리해라.
'저희가' 라고 말할 수 있는 유일한 카드다. 여기서 사람 목소리가 나야 한다.
⭕ "불안을 부추기는 책은 이미 많다고 생각했습니다"
⭕ "읽고 나서 오늘 할 일 하나가 정해지길 바랐습니다"
❌ "이 책은 여섯 개의 장으로 구성되어 있습니다" ← 만든 사람의 말이 아니다
subhead 에 이런 분께 권한다는 한 줄을 붙인다.""",
        "s10": """10번은 물음으로 닫는다. 파는 말로 끝내지 마라.
책의 주제를 읽는 사람 자기 이야기로 끌어오는 물음이어야 한다.
어디서 살 수 있는지는 캡션에 적고, 카드에는 물음만 남긴다.""",
    },
}


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

    # 없는 재료는 없다고 분명히 말해준다. 안 그러면 그럴듯하게 지어낸다.
    missing = [h for h, key in (("추천사", "추천사"), ("목차", "목차"),
                                ("작가 정보", "작가정보"), ("수상·미디어 추천", "수상내역"))
               if not (b.get(key) or "").strip()]
    if missing:
        L += ["", "## 이 책에 없는 것", "",
              "다음 자료는 **이 책에 없다.** 없는 것을 지어내지 말고 카드 구성을 바꿔라:",
              "- " + "\n- ".join(missing)]

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


def build_prompt(brief, reviews, persona_md, hooks_md, theme, palette,
                 hook_style, mode="review"):
    m = MODES.get(mode, MODES["review"])
    voice = persona_md if mode == "review" else m["voice"]
    return f"""너는 책 카드뉴스의 문구를 쓰는 사람이다.
아래 책 데이터와 규칙을 읽고 slides.json 을 만들어라.

# 이 카드뉴스의 성격 — {m["name"]}
{m["stance"]}

# 목소리
{voice}

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
{SCHEMA_BG if theme == "bg" else SCHEMA_10 if theme == "review" else SCHEMA}
{RULES_BG if theme == "bg" else RULES_10 if theme == "review" else RULES}

## 이 성격에서 달라지는 것
9번 — {m["s9"]}
10번 — {m["s10"]}
"""


# ── 결과 정리 ───────────────────────────────────────────────

def review_headline(b):
    n, r = b.get("리뷰수"), b.get("평점")
    if not n:
        return None
    return f"리뷰 **{n:,}개**" + (f" · 평점 **{r}**" if r else "")


# 인용한 사람 자리에 이런 말이 오면 그건 인용이 아니라 요약이다.
# ('교보문고 구매자' 는 진짜 독자 리뷰라서 여기 넣으면 안 된다)
FAKE_WHO = ("출판사", "ai ", "ai리뷰", "ai 리뷰", "리뷰 요약",
            "책 소개", "소개글", "미상", "익명", "편집부")


def _real_quote(q, book):
    """정말 누가 한 말을 옮긴 것인지 본다.

    · who 가 사람·매체 이름이어야 한다 ('출판사' · 'AI 리뷰' 는 아니다)
    · 그 문장이 크롤링해온 원문 안에 실제로 있어야 한다
      (앞·중간 두 곳을 본다. 인용하며 앞머리를 조금 자르는 일이 있어서다)
    """
    who = (q.get("who") or "").strip()
    text = (q.get("text") or "").strip()
    if not who or not text:
        return False
    w = who.lower()
    # '『돈의 속성』 중에서' 처럼 책을 출처로 밝힌 것은 정직한 표기다.
    # 사람 이름이 아니어도 통과시킨다 ('이 책의 한 문장' 카드가 이걸 쓴다)
    title = re.sub(r"\(.*?\)", "", book.get("제목") or "").strip()
    from_book = bool(title) and title[:6] in who
    if not from_book and (any(bad in w for bad in FAKE_WHO) or w == "ai"):
        return False

    hay = re.sub(r"\s+", "", " ".join(
        [str(book.get(k) or "") for k in ("추천사", "출판사서평", "책소개", "작가정보")]
        + [r.get("text", "") for r in (book.get("리뷰") or [])]))
    t = re.sub(r"\s+", "", text)
    if len(t) < 8:
        return False
    probes = [t[:12], t[len(t) // 2: len(t) // 2 + 12]]
    return any(p and p in hay for p in probes)


def hashtags(chips, book):
    """마지막 카드의 알약을 해시태그로 만든다.

    출판사 이름·쪽수가 들어가 있으면 아무도 그걸로 찾지 않는다.
    AI 가 안 붙였거나 엉뚱한 걸 넣었으면 책 데이터의 키워드·분야로 채운다.
    """
    out = []
    for c in (chips or []):
        c = str(c).strip()
        if not c.startswith("#"):
            continue
        body = c[1:]
        if not body or body.replace(",", "").isdigit() or "쪽" in body:
            continue
        if book.get("출판사") and book["출판사"].replace(" ", "") in body:
            continue
        if c not in out:
            out.append(c)

    if len(out) < 3:
        # 책 제목이 제일 많이 검색되는 태그다. 그 다음이 리뷰에 많이 나온 말.
        title = re.sub(r"\(.*?\)|\[.*?\]", "", book.get("제목") or "")
        pool = [title] + list(book.get("ai키워드") or []) + list(book.get("키워드") or []) \
            + list(reversed(book.get("분야") or [])) + ["책추천"]
        junk = {"국내도서", "외국도서", "서양도서", "eBook", "오디오북", "전체"}
        for w in pool:
            w = re.sub(r"[^0-9A-Za-z가-힣]", "", str(w))
            if not w or len(w) > 14 or w in junk:
                continue
            tag = "#" + w
            # 앞 두 글자가 같으면 사실상 같은 태그다 (#경제전망 · #경제일반)
            if any(t[1:3] == tag[1:3] for t in out):
                continue
            out.append(tag)
            if len(out) >= 3:
                break
    return out[:3]


def five_point(book):
    """교보 평점(10점 만점) → 템플릿의 5점 만점.

    올림하지 않고 내린다. 9.9 → 4.95 를 5.0 으로 올리면
    받지 않은 만점을 적는 셈이 된다. 숫자는 실제보다 좋게 쓰지 않는다.
    """
    v = book.get("평점")
    try:
        return "%.1f" % (int(float(v) / 2 * 10) / 10)
    except (TypeError, ValueError):
        return ""


def sanitize_review(data, output_dir, book, palette):
    """북리뷰 테마(10장) 정리. 칸이 정해진 템플릿이라 손볼 게 적다."""
    output_dir = Path(output_dir)
    data["theme"] = "review"
    data["palette"] = palette
    cover = "card_images/cover.png"
    has_cover = (output_dir / cover).exists()
    rating = five_point(book)

    # 오른쪽 위 영문 라벨. 같은 모양(quote)을 세 번 쓰므로 **장 번호로** 정한다.
    KINDS = ["BOOK REVIEW", "ONE LINE", "KEY IDEAS", "QUOTATION", "AUTHOR",
             "PRAISE", "FOR YOU", "READERS", "MY REVIEW", "CLOSING"]

    for i, sl in enumerate(data.get("slides", []), 1):
        sl["no"] = i
        sl["kind"] = KINDS[i - 1] if i <= len(KINDS) else ""

        if sl.get("type") == "cover":
            sl["image_path"] = cover if has_cover else None
            sl["book_title"] = book.get("제목") or sl.get("headline")
            who = book.get("저자") or ""
            if book.get("역자"):
                who += " · 옮김 " + book["역자"]
            sl["author"] = ("저자  " + who) if who else ""
            sl["rating"] = rating
        elif sl.get("type") == "closing":
            sl["rating"] = rating
        elif sl.get("type") == "quote":
            # 인용은 원문에 있는 문장만. 지어낸 문장이면 출처를 지운다.
            q = {"text": sl.get("line") or "", "who": sl.get("who") or "책"}
            if not _real_quote(q, book):
                sl["who"] = ""
            # 독자 리뷰 장(8번)의 리뷰 수·평점은 AI 를 믿지 않고 크롤 데이터로 적는다
            if i == 8 and book.get("리뷰수"):
                sl["subhead"] = "교보문고 리뷰 %s개 · 평점 %s / 5" % (
                    format(book["리뷰수"], ","), rating or "-")
        elif sl.get("type") in ("ideas", "foryou"):
            sl["points"] = [p for p in (sl.get("points") or []) if (p.get("k") or "").strip()][:3]

    return data


def sanitize_bg(data, output_dir, book, palette):
    """배경 사진 테마 정리. 배경과 글자 칸은 bg_theme 가 붙인다."""
    output_dir = Path(output_dir)
    data["theme"] = "bg"
    data["palette"] = palette
    rating = book.get("평점")

    for i, sl in enumerate(data.get("slides", []), 1):
        sl["no"] = i
        sl["lines"] = [l for l in (sl.get("lines") or []) if str(l).strip()][:3]
        # 독자 리뷰 장의 리뷰 수·평점은 AI 를 믿지 않고 크롤 데이터로 적는다
        if i == 8 and book.get("리뷰수"):
            sl["note"] = "교보문고 리뷰 %s개 · 평점 %s / 10" % (
                format(book["리뷰수"], ","), rating or "-")

    cover = output_dir / "cover.jpg"
    bg_theme.apply(data, palette or "forest", cover=cover if cover.exists() else None)
    return data


def sanitize(data, output_dir, book, theme, palette, disclosure=""):
    if theme == "bg":
        return sanitize_bg(data, output_dir, book, palette)
    if theme == "review":
        return sanitize_review(data, output_dir, book, palette)
    return sanitize_frost(data, output_dir, book, theme, palette, disclosure)


def sanitize_frost(data, output_dir, book, theme, palette, disclosure=""):
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
            if (output_dir / "card_images" / "cover.png").exists():
                sl["image_path"] = "card_images/cover.png"

        if sl.get("type") == "photo":
            # 표지 칸과 사진 칸은 비율이 다르다.
            # 표지용 세로 그림을 사진 카드에 넣으면 위아래가 잘려 제목이 날아간다.
            if (output_dir / "card_images" / "wide.png").exists():
                sl["image_path"] = "card_images/wide.png"
            elif (sl.get("image_path") or "").endswith("cover.png"):
                sl["image_path"] = None
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

        # 값이 없는 줄은 빼야 한다. '옮긴이 [빈칸]' 이 남으면 안 만든 티가 난다
        if sl.get("type") == "spec" and sl.get("rows"):
            sl["rows"] = [r for r in sl["rows"]
                          if str(r.get("v") or "").strip() not in ("", "-", "없음", "미상")]

        # 인용이 하나도 없는 quotes 카드는 빈 카드가 된다
        if sl.get("type") == "quotes" and not sl.get("quotes"):
            sl["type"] = "list"

        # 없는 사람 말을 인용하지 않는다.
        # 추천사가 비어 있는 책인데도 quotes 카드를 만들고
        # who 에 "출판사" · "AI 리뷰" 를 적어 넣은 적이 있다. 인용이 아니라 요약문이다.
        if sl.get("type") == "quotes":
            keep = [q for q in sl["quotes"] if _real_quote(q, book)]
            # 하나만 남아도 그게 진짜면 쓴다 ('이 책의 한 문장' 카드가 원래 하나다).
            # 하나도 안 남으면 인용할 게 없다는 뜻이니 목록 카드로 바꾼다.
            if not keep:
                sl["type"] = "list"
                sl["bullets"] = [q.get("text", "") for q in sl["quotes"] if q.get("text")][:4]
                sl.pop("quotes", None)
                # 인용이 아니게 됐는데 제목만 '추천사' 로 남으면 말이 안 맞는다
                if re.search(r"추천사|먼저 읽|이 사람들", sl.get("headline") or ""):
                    sl["headline"] = "이 책이\n받은 평가"
                if not sl.get("subhead"):
                    sl["subhead"] = "책 소개와 출판사 자료에서 옮겼습니다"
            else:
                sl["quotes"] = keep

        fixed.append(sl)

    data["slides"] = fixed
    if fixed and fixed[-1].get("type") == "cta":
        fixed[-1]["subhead"] = disclosure or fixed[-1].get("subhead") or ""
        fixed[-1]["chips"] = hashtags(fixed[-1].get("chips"), book)

    # 표지 색에 카드 색을 맞춘다. 금색 표지에 파란 배경이면 따로 논다.
    # (북리뷰 테마는 팔레트 6개가 정해져 있으므로 건드리지 않는다)
    data["extra_css"] = book_theme.apply(output_dir)
    return data


# ── 실행 ────────────────────────────────────────────────────

def generate(output_dir, provider, api_key, model, theme, palette,
             persona, hook_style, disclosure="", mode="review"):
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
                          persona_md, hooks_md, theme, palette, hook_style, mode)

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
