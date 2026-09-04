#!/usr/bin/env python3
"""
specs.py — 상세페이지 이미지를 AI에게 읽혀서 사실 정보를 뽑아낸다.

크롤러가 주는 summary.md 에는 브랜드·가격·평점·리뷰 수밖에 없다.
소재·용량·성능 수치·인증번호·A/S·구성품은 전부 **상세페이지 이미지 안**에 그림으로 들어 있어서
사람이 눈으로 읽어야 한다. 그 일을 AI 비전에 맡긴다.

결과는 product_notes.md 로 저장하고, gen.py 가 프롬프트에 그대로 넣는다.
"""

import base64
import io
from pathlib import Path

from PIL import Image

from images import _textiness

MAX_CHUNKS = 6          # 한 번에 보낼 이미지 수 (많으면 느리고 비싸다)
CHUNK_W = 860           # 글자가 읽힐 정도의 가로 해상도


PROMPT = """이건 쿠팡 상품 상세페이지를 잘라낸 이미지들이다.
카드뉴스에 쓸 **사실 정보만** 뽑아라.

## 뽑을 것
- 제품명 · 모델명
- 소재 · 성분 · 원재료
- 크기 · 무게 · 용량 · 수량
- 성능 수치 (출력, 회전수, 용량, 지속시간, 등급 등)
- 배터리 · 충전 방식
- 인증 (KC 등) 과 인증번호
- A/S 연락처 · 제조사 · 판매원 · 제조국
- 구성품
- 사용법 · 주의사항 중 중요한 것
- 경쟁 제품과의 차이로 적혀 있는 것

## 규칙
- **이미지에 실제로 적혀 있는 것만** 쓴다. 추측·보완 금지.
- 광고 문구("최고의", "혁신적인", "감동적인")는 빼고 사실만.
- 숫자는 단위까지 그대로 옮긴다. (예: 15,000rpm / 3,000mAh / 60×60×160mm)
- 확인 안 되는 항목은 아예 적지 않는다.
- 표로 정리돼 있으면 `항목: 값` 형태로 옮긴다.

마크다운 목록으로만 답하라. 다른 설명은 쓰지 마라.
읽을 수 있는 정보가 없으면 `(상세페이지에서 확인된 정보 없음)` 이라고만 답하라."""


def pick_text_chunks(images_dir, k=MAX_CHUNKS):
    """글자가 빽빽한 구간을 고른다 — 스펙표·인증정보가 거기 있다"""
    cands = []
    for f in sorted(Path(images_dir).iterdir()):
        if f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        try:
            im = Image.open(f)
        except Exception:
            continue
        w, h = im.size
        if w < 400:
            continue
        step = int(w * 1.4)                  # 세로로 길쭉하게 잘라야 표가 안 잘린다
        for y in range(0, h, step):
            y1 = min(y + step, h)
            if y1 - y < w * 0.4:
                continue
            crop = im.convert("RGB").crop((0, y, w, y1))
            cands.append((_textiness(crop), f.name, y, y1))
    cands.sort(reverse=True)                 # 글자 많은 순
    return [{"file": n, "y0": a, "y1": b} for _, n, a, b in cands[:k]]


def _encode(images_dir, chunk):
    im = Image.open(Path(images_dir) / chunk["file"]).convert("RGB")
    crop = im.crop((0, chunk["y0"], im.size[0], chunk["y1"]))
    w, h = crop.size
    if w > CHUNK_W:
        crop = crop.resize((CHUNK_W, int(h * CHUNK_W / w)), Image.LANCZOS)
    buf = io.BytesIO()
    crop.save(buf, "JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()


def read_specs(images_dir, chunks, provider, api_key, model, post):
    imgs = [_encode(images_dir, c) for c in chunks]

    if provider == "gemini":
        parts = [{"text": PROMPT}]
        for b in imgs:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b}})
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model or 'gemini-2.5-flash'}:generateContent")
        data = post(url, {"contents": [{"parts": parts}],
                          "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048}},
                    {"x-goog-api-key": api_key}, provider="gemini")
        return data["candidates"][0]["content"]["parts"][0]["text"]

    if provider == "claude":
        content = [{"type": "text", "text": PROMPT}]
        for b in imgs:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg", "data": b}})
        data = post("https://api.anthropic.com/v1/messages",
                    {"model": model or "claude-sonnet-4-5", "max_tokens": 2048,
                     "messages": [{"role": "user", "content": content}]},
                    {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                    provider="claude")
        return data["content"][0]["text"]

    content = [{"type": "text", "text": PROMPT}]
    for b in imgs:
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + b}})
    data = post("https://api.openai.com/v1/chat/completions",
                {"model": model or "gpt-4o", "temperature": 0.1,
                 "messages": [{"role": "user", "content": content}]},
                {"Authorization": f"Bearer {api_key}"}, provider="gpt")
    return data["choices"][0]["message"]["content"]


def prepare(output_dir, provider, api_key, model, post, log=print):
    """상세페이지를 읽어 product_notes.md 를 만든다. 실패해도 흐름을 막지 않는다."""
    output_dir = Path(output_dir)
    images_dir = output_dir / "images"
    notes_path = output_dir / "product_notes.md"

    if not (provider and api_key and post):
        log("AI 연결이 없어 상세페이지 읽기를 건너뜁니다")
        return ""
    if not images_dir.exists():
        log("상세페이지 이미지가 없습니다")
        return ""

    chunks = pick_text_chunks(images_dir)
    if not chunks:
        log("읽을 만한 구간을 찾지 못했습니다")
        return ""

    log(f"상세페이지 {len(chunks)}구간을 읽는 중...")
    try:
        text = read_specs(images_dir, chunks, provider, api_key, model, post).strip()
    except Exception as e:
        log(f"상세페이지 읽기 실패 ({e}) — 크롤링 정보만으로 진행합니다")
        return ""

    notes_path.write_text(text, encoding="utf-8")
    lines = [x for x in text.splitlines() if x.strip().startswith(("-", "*"))]
    log(f"상세페이지에서 사실 {len(lines)}건 확보 → product_notes.md")
    return text
