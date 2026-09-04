#!/usr/bin/env python3
"""
images.py — 상세페이지 긴 이미지에서 카드용 제품컷을 자동으로 골라낸다.

사람이 하던 일:
  세로로 긴 상세 이미지를 눈으로 훑고, 글자·배너가 없고 제품이 크게 나온
  구간을 골라서 카드 비율로 자른다.

여기서 하는 일:
  1) 긴 이미지를 겹치게 잘라 후보 타일을 만든다
  2) 번호를 새긴 대조표(contact sheet)를 만들어 AI에게 보여주고 고르게 한다
  3) AI가 못 고르면 글자 밀도 휴리스틱으로 대신 고른다
  4) 고른 구간을 원본 해상도에서 카드 비율로 잘라 card_images/ 에 저장
"""

import base64
import io
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CARD_W, CARD_H = 1080, 1050        # 카드 사진 영역 비율
MAX_TILES = 24


# ── 후보 타일 ───────────────────────────────────────────────

def slice_tiles(images_dir):
    """긴 이미지 → 겹치는 정사각 후보 타일 목록"""
    tiles = []
    for f in sorted(Path(images_dir).iterdir()):
        if f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        try:
            im = Image.open(f)
        except Exception:
            continue
        w, h = im.size
        if w < 400 or h < 300:
            continue
        tile_h = w                      # 정사각
        if h <= tile_h * 1.2:
            tiles.append({"file": f.name, "y0": 0, "y1": h})
            continue
        step = int(tile_h * 0.7)        # 30% 겹침 — 좋은 컷이 경계에 걸리는 걸 줄인다
        y = 0
        while y + tile_h <= h and len(tiles) < MAX_TILES * 3:
            tiles.append({"file": f.name, "y0": y, "y1": y + tile_h})
            y += step
    return tiles[:MAX_TILES]


def _textiness(im):
    """글자·배너가 많을수록 높은 점수 (가로 방향 밝기 변화가 잦다)"""
    g = im.convert("L").resize((160, 160))
    px = g.load()
    edges = 0
    for yy in range(160):
        for xx in range(1, 160):
            if abs(px[xx, yy] - px[xx - 1, yy]) > 45:
                edges += 1
    return edges / (160 * 159)


def contact_sheet(images_dir, tiles, cols=4, cell=210):
    """번호가 찍힌 대조표 이미지를 만들어 bytes 로 돌려준다"""
    rows = -(-len(tiles) // cols)
    sheet = Image.new("RGB", (cols * cell, rows * cell), (245, 245, 245))
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 30)
    except Exception:
        font = ImageFont.load_default()
    for i, t in enumerate(tiles):
        im = Image.open(Path(images_dir) / t["file"]).convert("RGB")
        crop = im.crop((0, t["y0"], im.size[0], t["y1"])).resize((cell, cell))
        x, y = (i % cols) * cell, (i // cols) * cell
        sheet.paste(crop, (x, y))
        d = ImageDraw.Draw(sheet)
        d.rectangle([x + 4, y + 4, x + 46, y + 42], fill=(20, 20, 20))
        d.text((x + 14, y + 6), str(i + 1), fill=(255, 255, 255), font=font)
        d.rectangle([x, y, x + cell - 1, y + cell - 1], outline=(200, 200, 200))
    buf = io.BytesIO()
    sheet.save(buf, "PNG")
    return buf.getvalue()


# ── AI에게 고르게 하기 ──────────────────────────────────────

PROMPT = """이건 쇼핑몰 상세페이지를 잘라 만든 후보 이미지 모음이다. 각 칸 왼쪽 위에 번호가 있다.

카드뉴스 배경으로 쓸 **제품 사진**을 좋은 순서대로 최대 5개 골라라.

고르는 기준
- 제품이 크고 선명하게 보이는 컷 ⭕
- 사용 장면·연출 컷 ⭕
- 글자가 화면을 덮은 컷 ❌
- 배너·표·인증서·가격 안내 ❌
- 잘려서 뭔지 알 수 없는 컷 ❌

번호만 JSON 배열로 답하라. 설명 금지. 예: [3, 7, 2]
쓸 만한 게 하나도 없으면 [] 로 답하라."""


def _b64(data):
    return base64.b64encode(data).decode()


def pick_with_vision(provider, api_key, model, sheet_png, post):
    """post 는 gen._post — 제공사별 형식으로 이미지 질의"""
    b = _b64(sheet_png)
    if provider == "gemini":
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model or 'gemini-2.5-flash'}:generateContent")
        data = post(url, {"contents": [{"parts": [
            {"text": PROMPT},
            {"inline_data": {"mime_type": "image/png", "data": b}}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 256}},
            {"x-goog-api-key": api_key}, provider="gemini")
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    elif provider == "claude":
        data = post("https://api.anthropic.com/v1/messages",
                    {"model": model or "claude-sonnet-4-5", "max_tokens": 256,
                     "messages": [{"role": "user", "content": [
                         {"type": "text", "text": PROMPT},
                         {"type": "image", "source": {"type": "base64",
                                                      "media_type": "image/png", "data": b}}]}]},
                    {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                    provider="claude")
        text = data["content"][0]["text"]
    else:
        data = post("https://api.openai.com/v1/chat/completions",
                    {"model": model or "gpt-4o", "temperature": 0.1,
                     "messages": [{"role": "user", "content": [
                         {"type": "text", "text": PROMPT},
                         {"type": "image_url",
                          "image_url": {"url": "data:image/png;base64," + b}}]}]},
                    {"Authorization": f"Bearer {api_key}"}, provider="gpt")
        text = data["choices"][0]["message"]["content"]

    m = re.search(r"\[[^\]]*\]", text)
    return [int(n) for n in re.findall(r"\d+", m.group(0))] if m else []


def pick_by_heuristic(images_dir, tiles, want=4):
    """AI를 못 쓸 때 — 글자가 적은 타일을 고른다"""
    scored = []
    for i, t in enumerate(tiles):
        im = Image.open(Path(images_dir) / t["file"]).convert("RGB")
        crop = im.crop((0, t["y0"], im.size[0], t["y1"]))
        scored.append((_textiness(crop), i + 1))
    scored.sort()
    return [n for _, n in scored[:want]]


# ── 저장 ────────────────────────────────────────────────────

def _fit(im, tw=CARD_W, th=CARD_H):
    w, h = im.size
    if w / h > tw / th:
        nw = int(h * tw / th)
        im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w * th / tw)
        top = (h - nh) // 2
        im = im.crop((0, top, w, top + nh))
    return im.resize((tw, th), Image.LANCZOS)


def build_card_images(output_dir, tiles, picks):
    """고른 번호 → card_images/*.jpg"""
    output_dir = Path(output_dir)
    images_dir = output_dir / "images"
    dst = output_dir / "card_images"
    dst.mkdir(exist_ok=True)
    made = []
    for rank, n in enumerate(picks, 1):
        if not (1 <= n <= len(tiles)):
            continue
        t = tiles[n - 1]
        im = Image.open(images_dir / t["file"]).convert("RGB")
        crop = im.crop((0, t["y0"], im.size[0], t["y1"]))
        name = f"photo_{rank:02d}.jpg"
        _fit(crop).save(dst / name, quality=94)
        made.append(f"card_images/{name}")
    return made


def prepare(output_dir, provider=None, api_key=None, model=None, post=None, log=print):
    """전체 흐름. 만들어진 이미지 경로 목록을 돌려준다."""
    output_dir = Path(output_dir)
    images_dir = output_dir / "images"
    if not images_dir.exists():
        log("상세 이미지 폴더가 없습니다")
        return []

    tiles = slice_tiles(images_dir)
    if not tiles:
        log("쓸 만한 상세 이미지가 없습니다")
        return []
    log(f"후보 {len(tiles)}구간 추출")

    picks = []
    if provider and api_key and post:
        try:
            sheet = contact_sheet(images_dir, tiles)
            picks = pick_with_vision(provider, api_key, model, sheet, post)
            log(f"AI가 고른 제품컷: {picks or '없음'}")
        except Exception as e:
            log(f"AI 이미지 선별 실패 ({e}) — 자동 선별로 대체")

    if not picks:
        picks = pick_by_heuristic(images_dir, tiles)
        log(f"자동 선별 결과: {picks}")

    made = build_card_images(output_dir, tiles, picks[:5])
    log(f"제품컷 {len(made)}장 생성")
    return made
