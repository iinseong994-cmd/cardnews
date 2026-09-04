#!/usr/bin/env python3
"""
review.py — 만든 카드를 AI가 눈으로 보고 고친다.

사람이 하는 마지막 단계다.
  뽑아본다 → 글자가 넘쳤나, 사진이 어색하게 잘렸나, 허전한가 → 고쳐서 다시 뽑는다

여기서는 렌더된 PNG 를 그대로 AI에게 보여주고,
slides.json 에 덮어쓸 수정안을 JSON 으로 받아 적용한 뒤
바뀐 카드만 다시 렌더한다.
"""

import base64
import io
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SHOT_W = 540          # 카드 한 장을 보낼 해상도 (글자가 읽혀야 한다)
MAX_SHOTS = 10


PROMPT = """네가 만든 카드뉴스를 실제로 렌더한 결과다. 카드마다 왼쪽 위에 번호가 있다.
아래 원본 문구(slides.json)와 나란히 놓고 **잘못된 것만** 찾아 고쳐라.

## 볼 것
1. **글자 넘침·잘림** — 제목이나 설명이 카드 밖으로 나가거나 잘렸는가
2. **겹침** — 글자끼리, 또는 글자와 사진이 겹쳤는가
3. **사진 문제** — 제품이 어중간하게 잘렸는가, 글자만 가득한 이미지가 들어갔는가
4. **허전함** — 카드에 내용이 너무 없어 빈 공간만 큰가
5. **반복** — 앞 카드와 같은 얘기를 하고 있는가

## 고치는 법
- 글자가 넘치면 → 그 슬라이드의 문구를 **짧게 다시 써라** (뜻은 유지)
- 사진이 이상하면 → `image_path` 를 아래 목록의 **다른 사진으로 바꿔라**
  (마땅한 게 없으면 `null` 로 두고 type 을 `statement` 로)
- 허전하면 → `subhead` 를 채우거나 `chips` 를 더해라
- 반복이면 → 다른 각도로 다시 써라

## 규칙
- **문제가 없는 카드는 건드리지 마라.** 멀쩡한 걸 고치면 안 된다.
- 숫자·리뷰 인용은 절대 바꾸지 마라. 원문 그대로여야 한다.
- 파트너스 고지문구(마지막 카드 subhead)는 절대 건드리지 마라.

## 출력
고칠 카드만 담아 JSON 으로. 설명 없이 JSON 만.

{"fixes":[
  {"no":3,"why":"제목이 두 줄로 넘쳐 잘림","set":{"headline":"짧게 고친 문구"}},
  {"no":6,"why":"사진에 글자만 가득","set":{"image_path":"card_images/photo_02.jpg"}}
]}

고칠 게 없으면 {"fixes":[]} 로 답하라."""


def _shot(path, width=SHOT_W):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    im = im.resize((width, int(h * width / w)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=86)
    return base64.b64encode(buf.getvalue()).decode()


def _numbered(path, no, width=SHOT_W):
    """카드 왼쪽 위에 번호를 찍어 보낸다"""
    im = Image.open(path).convert("RGB")
    w, h = im.size
    im = im.resize((width, int(h * width / w)), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 34)
    except Exception:
        font = ImageFont.load_default()
    d.rectangle([6, 6, 62, 52], fill=(220, 30, 30))
    d.text((20, 8), str(no), fill=(255, 255, 255), font=font)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=86)
    return base64.b64encode(buf.getvalue()).decode()


def _ask(provider, api_key, model, prompt, imgs, post, max_tokens=2500):
    if provider == "gemini":
        parts = [{"text": prompt}]
        for b in imgs:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b}})
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model or 'gemini-2.5-flash'}:generateContent")
        d = post(url, {"contents": [{"parts": parts}],
                       "generationConfig": {"temperature": 0.2,
                                            "maxOutputTokens": max_tokens}},
                 {"x-goog-api-key": api_key}, timeout=90, provider="gemini")
        return d["candidates"][0]["content"]["parts"][0]["text"]
    if provider == "claude":
        content = [{"type": "text", "text": prompt}]
        for b in imgs:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg", "data": b}})
        d = post("https://api.anthropic.com/v1/messages",
                 {"model": model or "claude-sonnet-4-5", "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": content}]},
                 {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                 timeout=90, provider="claude")
        return d["content"][0]["text"]
    content = [{"type": "text", "text": prompt}]
    for b in imgs:
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + b,
                                      "detail": "auto"}})
    d = post("https://api.openai.com/v1/chat/completions",
             {"model": model or "gpt-4o", "temperature": 0.2,
              "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": content}]},
             {"Authorization": f"Bearer {api_key}"}, timeout=90, provider="gpt")
    return d["choices"][0]["message"]["content"]


def _extract(text):
    t = re.sub(r"^```(?:json)?\s*", "", text.strip())
    t = re.sub(r"\s*```$", "", t)
    a, b = t.find("{"), t.rfind("}")
    if a == -1 or b == -1:
        return []
    return (json.loads(t[a:b + 1]) or {}).get("fixes", [])


# 함부로 바꾸면 안 되는 것들
LOCKED = {"no", "type", "quotes", "rows"}


def apply_fixes(data, fixes, output_dir, log=print):
    """수정안을 slides.json 에 반영. 바뀐 슬라이드 번호를 돌려준다."""
    by_no = {s["no"]: s for s in data["slides"]}
    changed = []
    last = max(by_no) if by_no else 0
    for fx in fixes:
        no = fx.get("no")
        s = by_no.get(no)
        if not s or not isinstance(fx.get("set"), dict):
            continue
        if no == last:                     # 마지막 카드의 고지문구는 보호
            fx["set"].pop("subhead", None)
        touched = False
        for k, v in fx["set"].items():
            if k in LOCKED:
                continue
            if k in ("image_path", "cutout") and v:
                if not (Path(output_dir) / v).exists():
                    continue               # 없는 파일이면 무시
                if v.startswith("review_cards/") and s.get("type") != "review":
                    continue
            if s.get(k) == v:
                continue
            s[k] = v
            touched = True
        if touched:
            changed.append(no)
            log(f"  {no}번 고침 — {fx.get('why', '')}")
    return changed


def run(output_dir, provider, api_key, model, post, log=print):
    """렌더된 카드를 보고 고칠 것을 찾아 slides.json 에 반영.
    다시 렌더해야 할 슬라이드 번호 목록을 돌려준다."""
    output_dir = Path(output_dir)
    sj = output_dir / "slides.json"
    shots = sorted(output_dir.glob("slide_*.png"))
    if not (provider and api_key and post):
        log("AI 연결이 없어 검수를 건너뜁니다")
        return []
    if not sj.exists() or not shots:
        log("검수할 카드가 없습니다")
        return []

    data = json.loads(sj.read_text(encoding="utf-8"))
    shots = shots[:MAX_SHOTS]
    log(f"카드 {len(shots)}장을 보고 검수하는 중...")

    imgs = [_numbered(p, i + 1) for i, p in enumerate(shots)]
    photos = []
    for sub in ("card_images", "cropped"):
        d = output_dir / sub
        if d.exists():
            photos += [f"{sub}/{f.name}" for f in sorted(d.iterdir())
                       if f.suffix.lower() in (".jpg", ".jpeg", ".png")]

    prompt = (PROMPT
              + "\n\n## 지금 문구 (slides.json)\n"
              + json.dumps({"slides": data["slides"]}, ensure_ascii=False, indent=1)
              + "\n\n## 바꿔 쓸 수 있는 사진\n"
              + ("\n".join("- " + p for p in photos) or "(없음)"))

    try:
        text = _ask(provider, api_key, model, prompt, imgs, post)
        fixes = _extract(text)
    except Exception as e:
        log(f"검수 실패 ({e}) — 그대로 둡니다")
        return []

    if not fixes:
        log("고칠 곳 없음 — 그대로 둡니다")
        return []

    changed = apply_fixes(data, fixes, output_dir, log)
    if changed:
        sj.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"{len(changed)}장 수정 — 다시 렌더합니다")
    return changed
