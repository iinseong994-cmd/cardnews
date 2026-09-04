#!/usr/bin/env python3
"""
gen.py — 크롤링 결과 + 규칙 파일 → slides.json (LLM 호출)

지원 모델: Gemini (무료 가능) / Claude / GPT
API 키는 서버에 저장하지 않는다. 요청마다 브라우저에서 받아 그대로 쓴다.
"""

import json
import re
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ── 프롬프트 ────────────────────────────────────────────────

SCHEMA = """{
  "theme": "<테마>",
  "palette": "<팔레트>",
  "slides": [
    {"no":1,"type":"cover","eyebrow":"<후크 12~20자>","headline":"<대형문구 줄당 3~4자, \\n으로 줄바꿈>",
     "subhead":"<한두 줄 설명>","image_path":"<표지 사진 또는 null>","chips":["<뱃지>","<뱃지>","<뱃지>"]},
    {"no":2,"type":"statement","headline":"<제목, **강조** 가능>","subhead":"<두세 줄>","image_path":null},
    {"no":3,"type":"photo","eyebrow":"<라벨>","headline":"<한 줄>","subhead":"<보조 한 줄>","image_path":"<사진>"},
    {"no":4,"type":"photo","headline":"<한 줄>","subhead":"<보조>","image_path":"<사진>"},
    {"no":5,"type":"spec","headline":"확인한 것만\\n적었습니다","rows":[{"k":"<항목>","v":"<값>"}],"chips":["<인증·AS>"]},
    {"no":6,"type":"photo","eyebrow":"<라벨>","headline":"<한 줄>","subhead":"<보조>","image_path":"<사진>"},
    {"no":7,"type":"review","headline":"리뷰 **<N>개** · 평점 <X>","image_path":"<리뷰카드 png>"},
    {"no":8,"type":"quotes","headline":"<제목>","quotes":[{"text":"<리뷰 원문 그대로>","who":"<작성자>"}],"image_path":null},
    {"no":9,"type":"list","headline":"이런 분께\\n맞아요","bullets":["<대상1>","<대상2>","<대상3>","<안 맞는 대상>"],"image_path":null},
    {"no":10,"type":"cta","headline":"가격은 첫 댓글에\\n적어둘게요 👇","chips":["<뱃지>"],
     "subhead":"이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다"}
  ],
  "caption": "<게시용 캡션. 페르소나 말투. 마지막 줄은 '가격은 자주 바뀌어서 첫 댓글에 적어둘게요 👇'>",
  "hashtags": ["#태그1","#태그2","#태그3","#태그4","#태그5"]
}"""

RULES = """
## 절대 규칙

1. **숫자는 주어진 데이터에서만.** 가격·평점·리뷰 수는 상품정보에서, 스펙 숫자는 상세페이지 분석 내용에서만 가져온다.
   데이터에 없는 숫자·통계·판매조건(선착순·기간한정·재고)을 지어내면 허위 표시가 된다.
2. **리뷰 인용은 원문 그대로.** 한 글자도 고치지 않는다. 길면 문장 단위로 자르되 말을 바꾸지 않는다.
3. **가격·금액은 카드에 넣지 않는다.** 쿠팡 가격은 자주 바뀌는데 카드는 이미지로 굳는다. CTA에서 첫 댓글로 유도한다.
4. **CTA 슬라이드의 subhead는 파트너스 고지문구 그대로** 넣는다 (생략 금지).
5. **image_path는 반드시 아래 목록에 있는 파일명만** 쓴다. 없는 파일명을 지어내지 않는다.
   - cover / photo 슬라이드 → **제품 사진** 목록에서만
   - review 슬라이드 → **리뷰 카드** 목록에서만
   - **리뷰 카드를 cover·photo 에 쓰면 안 된다** (글자만 가득한 이미지라 카드가 망가진다)
   - 제품 사진이 photo 슬라이드 수보다 적으면 남는 photo 는 statement / list 타입으로 바꾼다
   - 제품 사진이 하나도 없으면 cover 의 image_path 는 null 로 두고 photo 슬라이드를 아예 쓰지 않는다
6. **9번 마지막 bullet은 "안 맞는 대상"**을 쓴다 (제품 흠이 아니라 용도 한정). 예: "조용한 실내에서만 쓰실 거면 이건 아니에요"
7. 대형 문구(cover headline)는 **한 줄에 3~4자**, 최대 2줄. 길면 잘린다.
8. **JSON만 출력한다.** 설명·마크다운 코드펜스 없이 `{` 로 시작해서 `}` 로 끝낸다.
"""


def build_prompt(summary, reviews, images, review_imgs, hooks_md, persona_md,
                 theme, palette, hook_style, product_notes=""):
    return f"""너는 쿠팡 파트너스 카드뉴스의 문구를 쓰는 사람이다.
아래 상품 데이터와 규칙을 읽고 slides.json 을 만들어라.

# 페르소나 (이 목소리로 쓴다)
{persona_md}

# 후킹멘트 규칙
{hooks_md}

# 이번 카드뉴스의 후크 방향
{hook_style}

# 상품 정보
{summary}

# 리뷰 (원문 — 인용은 여기서 그대로 가져온다)
{reviews}

# 상세페이지에서 확인한 내용
{product_notes or "(별도 분석 없음 — 상품 정보와 리뷰에 있는 것만 쓸 것)"}

# 제품 사진 (cover / photo 슬라이드의 image_path 에 이것만 쓴다)
{images}

# 리뷰 카드 (7번 review 슬라이드에만 쓴다. 다른 슬라이드에 쓰지 말 것)
{review_imgs}

# 출력 형식
theme 은 "{theme}", palette 는 "{palette}" 로 고정한다.
{SCHEMA}
{RULES}
"""


# ── 모델별 호출 ─────────────────────────────────────────────

class ApiError(RuntimeError):
    """사용자에게 그대로 보여줄 수 있는 한국어 오류"""


# 제공사별 키 앞글자 — 키를 엉뚱한 칸에 넣는 실수가 제일 흔하다
KEY_PREFIX = {
    "gemini": ("AIza", "Gemini(Google AI Studio)"),
    "gpt":    ("sk-",  "OpenAI"),
    "claude": ("sk-ant-", "Anthropic"),
}


def detect_provider(key):
    """키 앞글자로 제공사를 알아낸다. sk-ant- 를 sk- 보다 먼저 본다."""
    if key.startswith("AIza"):
        return "gemini"
    if key.startswith("sk-ant-"):
        return "claude"
    if key.startswith("sk-"):
        return "gpt"
    return ""


def check_key(provider, api_key):
    """제공사와 키 형태가 어긋나면 미리 잡아준다"""
    key = (api_key or "").strip().strip('"').strip("'")
    if not key:
        raise ApiError("API 키가 비어 있습니다.")
    found = detect_provider(key)
    if found and found != provider:
        raise ApiError(
            f"{KEY_PREFIX[found][1]} 키를 넣으셨는데 선택된 모델은 "
            f"{KEY_PREFIX[provider][1]}입니다.\n"
            f"위에서 모델을 {KEY_PREFIX[found][1]}로 바꾸시거나, "
            f"{KEY_PREFIX[provider][1]} 키를 넣어주세요.")
    return key


def _post(url, payload, headers, timeout=180, provider=""):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            body = json.loads(e.read().decode("utf-8", "replace"))
            detail = (body.get("error") or {}).get("message", "") if isinstance(body, dict) else ""
        except Exception:
            pass
        name = KEY_PREFIX.get(provider, ("", provider or "AI"))[1]
        if e.code in (401, 403):
            raise ApiError(
                f"{name} 키가 거부됐습니다 (HTTP {e.code}).\n"
                "· 키를 복사할 때 앞뒤 공백이나 따옴표가 섞이지 않았는지\n"
                "· 만료·삭제된 키가 아닌지\n"
                "· 선택한 모델과 키의 제공사가 같은지 확인해 주세요."
                + (f"\n\n원문: {detail}" if detail else "")) from None
        if e.code == 429:
            raise ApiError(
                f"{name} 사용량 한도에 걸렸습니다 (HTTP 429).\n"
                "무료 등급은 분당 요청 수 제한이 있습니다. 1~2분 뒤에 다시 시도해 주세요."
                + (f"\n\n원문: {detail}" if detail else "")) from None
        if e.code == 404:
            raise ApiError(
                f"{name}에서 모델을 찾지 못했습니다 (HTTP 404).\n"
                "모델 이름이 바뀌었을 수 있습니다."
                + (f"\n\n원문: {detail}" if detail else "")) from None
        raise ApiError(f"{name} 요청 실패 (HTTP {e.code}).\n{detail or e.reason}") from None
    except urllib.error.URLError as e:
        raise ApiError(f"인터넷 연결을 확인해 주세요.\n{e.reason}") from None


def call_gemini(prompt, api_key, model="gemini-2.5-flash"):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    data = _post(url, {"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.8, "maxOutputTokens": 8192}},
                 {"x-goog-api-key": api_key}, provider="gemini")
    return data["candidates"][0]["content"]["parts"][0]["text"]


def call_claude(prompt, api_key, model="claude-sonnet-4-5"):
    data = _post("https://api.anthropic.com/v1/messages",
                 {"model": model, "max_tokens": 8192, "temperature": 0.8,
                  "messages": [{"role": "user", "content": prompt}]},
                 {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                 provider="claude")
    return data["content"][0]["text"]


def call_gpt(prompt, api_key, model="gpt-4o"):
    data = _post("https://api.openai.com/v1/chat/completions",
                 {"model": model, "temperature": 0.8,
                  "messages": [{"role": "user", "content": prompt}]},
                 {"Authorization": f"Bearer {api_key}"}, provider="gpt")
    return data["choices"][0]["message"]["content"]


PROVIDERS = {"gemini": call_gemini, "claude": call_claude, "gpt": call_gpt}


# ── 결과 정리 ───────────────────────────────────────────────

def extract_json(text):
    """코드펜스나 앞뒤 설명이 섞여 나와도 JSON만 뽑는다"""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("응답에서 JSON을 찾지 못했습니다:\n" + text[:500])
    return json.loads(t[start:end + 1])


def sanitize(data, output_dir, theme, palette):
    """존재하지 않는 이미지 경로 제거 + 필수 항목 보정"""
    data["theme"] = theme
    data["palette"] = palette
    fixed = []
    for i, sl in enumerate(data.get("slides", []), 1):
        sl["no"] = i
        for field in ("image_path", "cutout"):
            path = sl.get(field)
            if not path:
                continue
            # 리뷰 카드는 review 슬라이드 전용 — 사진 자리에 오면 버린다
            if path.startswith("review_cards/") and sl.get("type") != "review":
                sl[field] = None
                path = None
            elif not (output_dir / path).exists():
                sl[field] = None
                path = None
        if sl.get("type") == "photo" and not sl.get("image_path"):
            sl["type"] = "statement"           # 사진 없으면 텍스트 카드로
        if sl.get("type") == "cover" and not sl.get("image_path") and not sl.get("cutout"):
            first = sorted((output_dir / "card_images").glob("*.jpg")) \
                if (output_dir / "card_images").exists() else []
            if first:
                sl["image_path"] = f"card_images/{first[0].name}"
        # 표지 대형 문구는 3줄까지만 (4줄 넘으면 아래 설명과 겹친다)
        if sl.get("type") == "cover" and sl.get("headline"):
            lines = [x for x in sl["headline"].split("\n") if x.strip()]
            if len(lines) > 3:
                lines = lines[:2] + [" ".join(lines[2:])]
            sl["headline"] = "\n".join(lines)
        fixed.append(sl)
    data["slides"] = fixed
    if fixed and fixed[-1].get("type") == "cta" and not fixed[-1].get("subhead"):
        fixed[-1]["subhead"] = ("이 포스팅은 쿠팡 파트너스 활동의 일환으로, "
                                "이에 따른 일정액의 수수료를 제공받습니다")
    return data


def list_images(output_dir):
    """(제품 사진, 리뷰 카드) — 리뷰 카드는 review 슬라이드 전용이라 따로 준다"""
    photos, reviews = [], []
    for sub, bucket in (("card_images", photos), ("cropped", photos),
                        ("review_cards", reviews)):
        d = output_dir / sub
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix.lower() in (".jpg", ".jpeg", ".png"):
                bucket.append(f"{sub}/{f.name}")
    return photos, reviews


def generate(output_dir, provider, api_key, model, theme, palette,
             persona, hook_style, product_notes=""):
    output_dir = Path(output_dir)
    summary = (output_dir / "summary.md").read_text(encoding="utf-8")
    rv = output_dir / "review.md"
    reviews = rv.read_text(encoding="utf-8")[:12000] if rv.exists() else "(리뷰 없음)"
    hooks_md = (ROOT / "references" / "hooks.md").read_text(encoding="utf-8")
    pf = ROOT / "references" / "personas" / f"{persona}.md"
    persona_md = pf.read_text(encoding="utf-8") if pf.exists() else "(페르소나 없음 — 담백한 존댓말)"
    if not product_notes:
        nf = output_dir / "product_notes.md"
        product_notes = nf.read_text(encoding="utf-8") if nf.exists() else ""
    photos, review_imgs = list_images(output_dir)
    images = "\n".join("- " + x for x in photos) or "(제품 사진 없음 — photo 슬라이드를 쓰지 말 것)"
    rimgs = "\n".join("- " + x for x in review_imgs) or "(리뷰 카드 없음)"

    prompt = build_prompt(summary, reviews, images, rimgs, hooks_md, persona_md,
                          theme, palette, hook_style, product_notes)

    fn = PROVIDERS.get(provider)
    if not fn:
        raise ApiError(f"지원하지 않는 모델: {provider}")
    api_key = check_key(provider, api_key)
    kwargs = {"model": model} if model else {}
    text = fn(prompt, api_key, **kwargs)

    data = sanitize(extract_json(text), output_dir, theme, palette)
    (output_dir / "slides.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
