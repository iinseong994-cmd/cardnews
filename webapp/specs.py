#!/usr/bin/env python3
"""
specs.py — 상세페이지 이미지를 AI에게 읽혀서 사실 정보를 뽑아낸다.

크롤러가 주는 summary.md 에는 브랜드·가격·평점·리뷰 수밖에 없다.
소재·용량·성능 수치·인증번호·A/S·구성품은 전부 **상세페이지 이미지 안**에
그림으로 들어 있어서 사람이 눈으로 읽어야 한다.

사람이 하는 방식 그대로 두 단계로 한다.
  1단계 (찾기)  상세 이미지를 전부 잘라 번호 붙인 대조표를 보여주고
                "제품 사양표·구성품·인증이 적힌 칸이 어디냐" 고 묻는다
  2단계 (읽기)  지목된 칸만 **확대해서** 다시 보내 글자를 읽게 한다

작은 표 글씨는 축소하면 안 읽힌다. 그래서 2단계는 해상도를 크게 쓴다.
결과는 product_notes.md 로 저장하고 gen.py 가 프롬프트에 넣는다.
"""

import base64
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from images import _textiness

FIND_W = 300         # 1단계: 어디 있나만 보면 되니 작게
READ_W = 1280        # 2단계: 표 글씨가 읽혀야 하니 크게
MAX_READ = 8         # 확대해서 읽을 칸 수
MAX_CHUNKS = 40      # 후보 상한


# ── 후보 자르기 ─────────────────────────────────────────────

PER_FILE_CAP = 12    # 아주 긴 이미지 하나가 후보를 다 잡아먹지 않게


def chunk_all(images_dir):
    """상세 이미지 전부를 훑어 후보 칸을 만든다.

    제품 사양표는 거의 항상 **맨 뒤 이미지의 맨 아래**에 있다.
    그래서 상한에 걸려도 뒤쪽을 버리지 않는다 — 긴 이미지의 가운데를 솎아낸다.
    """
    per_file = []
    for f in sorted(Path(images_dir).iterdir()):
        if f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        try:
            im = Image.open(f)
        except Exception:
            continue
        w, h = im.size
        if w < 300 or h < 120:
            continue
        step = int(w * 1.5)
        if h <= step * 1.2:                       # 짧으면 통째로
            per_file.append([{"file": f.name, "y0": 0, "y1": h}])
            continue
        cs, y = [], 0
        while y < h:
            y1 = min(y + step, h)
            if y1 - y > w * 0.3:
                cs.append({"file": f.name, "y0": y, "y1": y1})
            y += int(step * 0.85)                 # 15% 겹침 — 표가 경계에 걸려도 잡히게
        if len(cs) > PER_FILE_CAP:                # 앞·뒤는 남기고 가운데를 솎는다
            keep = cs[:2] + cs[-4:]
            middle = cs[2:-4]
            need = PER_FILE_CAP - len(keep)
            if need > 0 and middle:
                stride = max(1, len(middle) // need)
                keep = cs[:2] + middle[::stride][:need] + cs[-4:]
            cs = keep
        per_file.append(cs)

    # 파일 수가 많아 상한을 넘으면, 뒤쪽 파일부터 자리를 확보한다
    out = []
    for cs in per_file:
        out.extend(cs)
    if len(out) > MAX_CHUNKS:
        tail_room = 0
        trimmed = []
        for cs in reversed(per_file):             # 뒤 파일 우선
            room = MAX_CHUNKS - tail_room
            if room <= 0:
                break
            take = cs if len(cs) <= room else cs[-room:]
            trimmed.insert(0, take)
            tail_room += len(take)
        out = [c for cs in trimmed for c in cs]
    return out


def _crop(images_dir, c):
    im = Image.open(Path(images_dir) / c["file"]).convert("RGB")
    return im.crop((0, c["y0"], im.size[0], c["y1"]))


def _encode(im, width, quality=90):
    w, h = im.size
    if w != width:
        im = im.resize((width, max(1, int(h * width / w))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


# ── 1단계: 어디에 있나 ──────────────────────────────────────

FIND_PROMPT = """쇼핑몰 상세페이지를 위에서 아래로 잘라 번호를 붙인 것이다.

**제품의 사실 정보가 적힌 칸**을 모두 골라라. 이런 것들이다.
- 제품 사양표 · 상품 기본정보 · 제품정보 (표 형태로 항목:값 이 나열된 것)
- 구성품 안내
- 인증 정보 (KC 등), 인증번호
- A/S · 제조사 · 제조국 · 고객센터
- 성능 수치가 적힌 설명 (용량, 무게, 크기, 시간, 등급 등)
- FAQ 중 사양을 설명하는 부분

**고르지 말 것**: 분위기 사진, 모델 컷, 배너, 가격 광고, 후기 캡처

번호만 JSON 배열로, 정보가 많아 보이는 순서대로 답하라. 설명 금지.
예: [12, 3, 11]
없으면 [] 로 답하라."""


def find_sheet(images_dir, chunks, cols=6, cell=FIND_W // 2):
    rows = -(-len(chunks) // cols)
    sheet = Image.new("RGB", (cols * cell, rows * cell), (240, 240, 240))
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 26)
    except Exception:
        font = ImageFont.load_default()
    d = ImageDraw.Draw(sheet)
    for i, c in enumerate(chunks):
        im = _crop(images_dir, c)
        w, h = im.size
        scale = cell / max(w, h)
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        x, y = (i % cols) * cell, (i // cols) * cell
        sheet.paste(im, (x, y))
        d.rectangle([x + 3, y + 3, x + 40, y + 36], fill=(20, 20, 20))
        d.text((x + 10, y + 5), str(i + 1), fill=(255, 255, 255), font=font)
        d.rectangle([x, y, x + cell - 1, y + cell - 1], outline=(190, 190, 190))
    buf = io.BytesIO()
    sheet.save(buf, "PNG")
    return buf.getvalue()


# ── 2단계: 확대해서 읽기 ────────────────────────────────────

READ_PROMPT = """이건 쿠팡 상품 상세페이지에서 **사양 정보가 있는 부분만** 확대한 이미지들이다.
카드뉴스에 쓸 **사실 정보만** 빠짐없이 뽑아라.

## 뽑을 것
- 제품명 · 모델명
- 소재 · 성분 · 원재료
- 크기 · 무게 · 용량 · 수량
- 성능 수치 (출력, 회전수, 지속시간, 등급, 버전 등)
- 배터리 용량 · 충전 방식
- 인증 (KC 등) 과 인증번호
- A/S 연락처 · 제조사 · 판매원 · 제조국 · 출시 시기
- 구성품 (**포함되지 않는 것도 함께**)
- 사용법 · 주의사항 중 중요한 것
- 전작·경쟁 제품과의 차이로 적혀 있는 수치

## 규칙
- **이미지에 실제로 적혀 있는 것만** 쓴다. 추측·보완 금지.
- 광고 문구("최고의", "혁신적인")는 빼고 사실만.
- 숫자는 **단위까지 그대로** 옮긴다. (예: 24bit/96kHz, 5.1g, 26시간, v6.1, 19.8%)
- 표는 `항목: 값` 으로 한 줄씩 옮긴다. **표에 있는 항목을 빠뜨리지 마라.**
- 깨알같이 작게 적힌 각주·단서도 수치가 있으면 옮긴다.
- 확인 안 되는 항목은 아예 적지 않는다.

마크다운 목록으로만 답하라. 다른 설명은 쓰지 마라.
읽을 수 있는 정보가 없으면 `(상세페이지에서 확인된 정보 없음)` 이라고만 답하라."""


def _ask(provider, api_key, model, prompt, images_b64, post, max_tokens=2048):
    if provider == "gemini":
        parts = [{"text": prompt}]
        for b in images_b64:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b}})
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model or 'gemini-2.5-flash'}:generateContent")
        d = post(url, {"contents": [{"parts": parts}],
                       "generationConfig": {"temperature": 0.1,
                                            "maxOutputTokens": max_tokens}},
                 {"x-goog-api-key": api_key}, provider="gemini")
        return d["candidates"][0]["content"]["parts"][0]["text"]

    if provider == "claude":
        content = [{"type": "text", "text": prompt}]
        for b in images_b64:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg", "data": b}})
        d = post("https://api.anthropic.com/v1/messages",
                 {"model": model or "claude-sonnet-4-5", "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": content}]},
                 {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                 provider="claude")
        return d["content"][0]["text"]

    content = [{"type": "text", "text": prompt}]
    for b in images_b64:
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + b, "detail": "high"}})
    d = post("https://api.openai.com/v1/chat/completions",
             {"model": model or "gpt-4o", "temperature": 0.1,
              "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": content}]},
             {"Authorization": f"Bearer {api_key}"}, provider="gpt")
    return d["choices"][0]["message"]["content"]


def _numbers(text, n):
    import re
    m = re.search(r"\[[^\]]*\]", text)
    if not m:
        return []
    out = []
    for x in re.findall(r"\d+", m.group(0)):
        i = int(x)
        if 1 <= i <= n and i not in out:
            out.append(i)
    return out


def fallback_picks(images_dir, chunks, want=MAX_READ):
    """AI가 못 고를 때.

    사양표는 상세페이지 **맨 끝**에 있다. 그래서 뒤에서부터 챙기고,
    남는 자리는 글자가 빽빽한 칸으로 채운다.
    """
    picks = []
    seen = {}
    for i, c in enumerate(chunks):
        seen.setdefault(c["file"], []).append(i + 1)

    # 뒤쪽 파일부터, 각 파일의 마지막 칸부터
    for f in reversed(list(seen)):
        for n in reversed(seen[f][-2:]):
            if n not in picks:
                picks.append(n)
        if len(picks) >= want - 2:                # 글자 밀도용 자리 2칸 남긴다
            break

    scored = sorted(((_textiness(_crop(images_dir, c)), i + 1)
                     for i, c in enumerate(chunks)), reverse=True)
    for _, n in scored:
        if len(picks) >= want:
            break
        if n not in picks:
            picks.append(n)
    return picks[:want]


# ── 전체 흐름 ───────────────────────────────────────────────

def prepare(output_dir, provider, api_key, model, post, log=print):
    output_dir = Path(output_dir)
    images_dir = output_dir / "images"
    if not (provider and api_key and post):
        log("AI 연결이 없어 상세페이지 읽기를 건너뜁니다")
        return ""
    if not images_dir.exists():
        log("상세페이지 이미지가 없습니다")
        return ""

    chunks = chunk_all(images_dir)
    if not chunks:
        log("읽을 구간을 찾지 못했습니다")
        return ""
    log(f"상세페이지를 {len(chunks)}칸으로 훑는 중...")

    # 1단계 — 사양 정보가 어디 있나
    picks = []
    try:
        sheet = find_sheet(images_dir, chunks)
        text = _ask(provider, api_key, model, FIND_PROMPT,
                    [base64.b64encode(sheet).decode()], post, max_tokens=256)
        picks = _numbers(text, len(chunks))
        log(f"사양 정보가 있는 칸: {picks or '못 찾음'}")
    except Exception as e:
        log(f"위치 찾기 실패 ({e})")

    if not picks:
        picks = fallback_picks(images_dir, chunks)
        log(f"자동 선별로 대체: {picks}")

    # 2단계 — 그 칸만 확대해서 읽기
    picks = picks[:MAX_READ]
    imgs = [_encode(_crop(images_dir, chunks[n - 1]), READ_W) for n in picks]
    log(f"{len(imgs)}칸을 {READ_W}px 로 확대해 읽는 중...")

    try:
        notes = _ask(provider, api_key, model, READ_PROMPT, imgs, post,
                     max_tokens=3000).strip()
    except Exception as e:
        log(f"상세페이지 읽기 실패 ({e}) — 크롤링 정보만으로 진행합니다")
        return ""

    (output_dir / "product_notes.md").write_text(notes, encoding="utf-8")
    lines = [x for x in notes.splitlines() if x.strip().startswith(("-", "*"))]
    log(f"사실 {len(lines)}건 확보 → product_notes.md")
    return notes
