#!/usr/bin/env python3
"""
preview.py — 산출물 폴더(threads_*.md + slide_*.png)를 쓰레드 UI 목업 HTML로 합성

사용법:
    python3 scripts/preview.py "output/<제품폴더>"

동작:
    - threads_유진.md, threads_살까말까.md ... 페르소나별 파일을 자동 인식 → 상단 버튼으로 전환
    - 페르소나 파일이 없으면 구버전 threads.md 단일 모드
    - 출력: {폴더}/preview.html ← 게시글 미리보기 + 카드뉴스 캐러셀 + 원클릭 복사
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path

# 페르소나 표시 정보 (references/personas/ 와 세트 — 새 페르소나 추가 시 여기도 갱신)
PERSONA_META = {
    "유진": {"handle": "yujin.daily",  "grad": ("#00C471", "#007A46"), "tag": "26 · 자취러 텐션"},
    "살까말까": {"handle": "salkka_buy6", "grad": ("#4A7DFF", "#1E3FA8"), "tag": "20대 중반 · 따지는 직장인"},
    "수현": {"handle": "soohyun.home", "grad": ("#FF7A9E", "#C2385F"), "tag": "35 · 워킹맘 공감"},
    "태오": {"handle": "taeo.zip",     "grad": ("#FFB03A", "#D9641E"), "tag": "24 · 음슴체 드립"},
    "하루": {"handle": "haru.cut",     "grad": ("#5B6B7A", "#242F3A"), "tag": "28 · 단문 장면형"},
    "정원": {"handle": "jungwon.pick", "grad": ("#2E9BD6", "#12608F"), "tag": "33 · 다 정리해주는 사람"},
}
PERSONA_ORDER = ["유진", "살까말까", "수현", "태오", "하루", "정원"]
FALLBACK_GRADS = [("#9B7BFF", "#5B34C9"), ("#4AD1D4", "#1E8A8D")]  # 미등록 페르소나용


def parse_threads_md(path: Path):
    """threads md → (본문, 첫 댓글) 추출"""
    text = path.read_text(encoding="utf-8")

    def section(title_prefix):
        m = re.search(rf"^## {title_prefix}.*?$", text, re.M)
        if not m:
            return ""
        rest = text[m.end():]
        stop = re.search(r"^---\s*$", rest, re.M)
        body = rest[: stop.start()] if stop else rest
        return body.strip()

    comment = section("첫 댓글")

    # 본문: `## 본문` 섹션이 있으면 그걸, 없으면 파일 시작 ~ 첫 `---` 전까지를 본문으로.
    body = section("본문")
    if not body:
        stop = re.search(r"^---\s*$", text, re.M)
        head = text[: stop.start()] if stop else text
        lines = head.splitlines()
        while lines and (lines[0].strip().startswith("#") or not lines[0].strip()):
            lines.pop(0)
        body = "\n".join(lines).strip()

    return body, comment


def collect_posts(d: Path):
    """페르소나별 threads_*.md 수집. 없으면 threads.md 단일(유진) 폴백."""
    posts = {}
    for p in sorted(d.glob("threads_*.md")):
        name = p.stem[len("threads_"):]
        body, comment = parse_threads_md(p)
        if body:
            posts[name] = {"body": body, "comment": comment}
    if not posts and (d / "threads.md").exists():
        body, comment = parse_threads_md(d / "threads.md")
        posts["유진"] = {"body": body, "comment": comment}

    # 표시 순서: 표준 4인 먼저, 그 외는 이름순
    ordered = [n for n in PERSONA_ORDER if n in posts] + sorted(
        n for n in posts if n not in PERSONA_ORDER
    )
    return {n: posts[n] for n in ordered}


def build_html(product: str, posts: dict, slides: list, caption: str) -> str:
    # 페르소나 메타 합성 (미등록 이름은 폴백 색 + 이름 기반 핸들)
    personas = {}
    for i, name in enumerate(posts):
        meta = PERSONA_META.get(name)
        if meta:
            personas[name] = meta
        else:
            grad = FALLBACK_GRADS[i % len(FALLBACK_GRADS)]
            personas[name] = {"handle": f"{name}.threads", "grad": grad, "tag": "커스텀"}

    data = {
        "posts": {
            n: {
                "body": posts[n]["body"],
                "comment": posts[n]["comment"],
                "handle": personas[n]["handle"],
                "g1": personas[n]["grad"][0],
                "g2": personas[n]["grad"][1],
            }
            for n in posts
        },
        "caption": caption or "",
    }
    # </script> 조기 종료 방지
    data_json = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")

    tab_btns = "\n".join(
        f'      <button class="tab" data-p="{html.escape(n)}" onclick="setPersona(\'{html.escape(n)}\')">'
        f'<span class="dot" style="background:linear-gradient(135deg,{personas[n]["grad"][0]},{personas[n]["grad"][1]})"></span>'
        f'<b>{html.escape(n)}</b><small>{html.escape(personas[n]["tag"])}</small></button>'
        for n in posts
    )
    slide_imgs = "\n".join(
        f'      <img src="{html.escape(s)}" alt="slide" loading="lazy">' for s in slides
    )
    dots = "".join(f'<i data-i="{i}"></i>' for i in range(len(slides)))

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>미리보기 — {html.escape(product)}</title>
<style>
  :root{{--bg:#101010;--card:#181818;--line:#2e2e2e;--ink:#f3f5f7;--sub:#777;--acc:#00C471}}
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:var(--bg);color:var(--ink);font-family:'Apple SD Gothic Neo','Pretendard',-apple-system,'Malgun Gothic',sans-serif;
       display:flex;justify-content:center;gap:28px;padding:36px 20px;min-height:100vh}}
  .phone{{width:540px;max-width:94vw}}
  .brandbar{{display:flex;align-items:center;justify-content:center;gap:8px;color:var(--sub);font-size:13px;font-weight:700;margin-bottom:14px}}
  .brandbar b{{color:var(--ink);font-size:15px}}
  /* 페르소나 탭 */
  .tabs{{display:flex;gap:8px;margin-bottom:12px}}
  .tab{{flex:1;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px 6px 9px;
       color:var(--ink);cursor:pointer;text-align:center;transition:.15s;display:flex;flex-direction:column;align-items:center;gap:3px}}
  .tab .dot{{width:22px;height:22px;border-radius:50%}}
  .tab b{{font-size:13.5px}}
  .tab small{{color:var(--sub);font-size:10.5px;font-weight:600;letter-spacing:-.02em}}
  .tab:hover{{border-color:#555}}
  .tab.on{{border-color:var(--pacc,#00C471);box-shadow:0 0 0 1px var(--pacc,#00C471) inset}}
  .tab.on b{{color:var(--pacc,#00C471)}}
  .post{{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:20px 18px}}
  .head{{display:flex;align-items:center;gap:10px}}
  .avatar{{width:40px;height:40px;border-radius:50%;
          display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;color:#fff}}
  .who b{{font-size:15px}} .who span{{color:var(--sub);font-size:13px;margin-left:6px}}
  .body{{margin:14px 2px 6px;font-size:15.5px;line-height:1.62;word-break:keep-all;white-space:pre-wrap}}
  /* 캐러셀 */
  .carousel{{position:relative;margin-top:12px}}
  .strip{{display:flex;gap:8px;overflow-x:auto;scroll-snap-type:x mandatory;border-radius:14px;scrollbar-width:none}}
  .strip::-webkit-scrollbar{{display:none}}
  .strip img{{height:380px;border-radius:14px;scroll-snap-align:start;border:1px solid var(--line)}}
  .nav{{position:absolute;top:50%;transform:translateY(-50%);width:34px;height:34px;border-radius:50%;
       background:rgba(0,0,0,.65);color:#fff;border:1px solid var(--line);font-size:16px;cursor:pointer;display:flex;align-items:center;justify-content:center}}
  .nav.prev{{left:8px}} .nav.next{{right:8px}}
  .dots{{display:flex;gap:5px;justify-content:center;margin-top:10px}}
  .dots i{{width:6px;height:6px;border-radius:50%;background:#444;display:block}}
  .dots i.on{{background:var(--acc)}}
  /* 액션바 */
  .actions{{display:flex;gap:18px;margin:14px 2px 4px;color:var(--sub);font-size:14px;font-weight:600}}
  .actions svg{{width:21px;height:21px;stroke:var(--ink);fill:none;stroke-width:1.7;vertical-align:-5px;margin-right:4px}}
  /* 첫 댓글 */
  .reply{{display:flex;gap:10px;border-top:1px solid var(--line);margin-top:14px;padding-top:14px}}
  .reply .avatar{{width:30px;height:30px;font-size:13px;flex-shrink:0}}
  .reply .txt{{font-size:14px;line-height:1.6;color:#cfd4d9;word-break:break-all}}
  .reply .txt .cmt{{white-space:pre-wrap}}
  /* 우측 패널 */
  .panel{{width:300px;max-width:94vw;display:flex;flex-direction:column;gap:12px}}
  .panel h3{{font-size:14px;color:var(--sub);font-weight:800;letter-spacing:.06em;margin-bottom:2px}}
  .btn{{background:var(--card);border:1px solid var(--line);color:var(--ink);border-radius:12px;padding:13px 14px;
       font-size:14px;font-weight:700;cursor:pointer;text-align:left;transition:.15s}}
  .btn:hover{{border-color:var(--acc)}}
  .btn small{{display:block;color:var(--sub);font-weight:600;margin-top:3px}}
  .btn.copied{{border-color:var(--acc);color:var(--acc)}}
  .guide{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;font-size:12.5px;color:#9aa2ab;line-height:1.7}}
  .guide b{{color:var(--ink)}}
  @media (max-width:920px){{body{{flex-direction:column;align-items:center}}.panel{{width:540px}}}}
</style>
</head>
<body>
  <div class="phone">
    <div class="brandbar">🧵 <b>Threads 미리보기</b>· 페르소나 버튼으로 전환</div>
    <div class="tabs" id="tabs">
{tab_btns}
    </div>
    <div class="post">
      <div class="head">
        <div class="avatar" id="avatar">유</div>
        <div class="who"><b id="handle">-</b><span>지금</span></div>
      </div>
      <div class="body" id="body"></div>
      <div class="carousel">
        <div class="strip" id="strip">
{slide_imgs}
        </div>
        <button class="nav prev" onclick="slide(-1)">‹</button>
        <button class="nav next" onclick="slide(1)">›</button>
        <div class="dots" id="dots">{dots}</div>
      </div>
      <div class="actions">
        <span><svg viewBox="0 0 24 24"><path d="M12 21s-7.5-4.6-10-9.6C.6 8 2.4 4.6 6 4.2c2.2-.2 4 .9 6 3 2-2.1 3.8-3.2 6-3 3.6.4 5.4 3.8 4 7.2-2.5 5-10 9.6-10 9.6z"/></svg>좋아요</span>
        <span><svg viewBox="0 0 24 24"><path d="M21 11.5a8.4 8.4 0 0 1-8.5 8.3 8.9 8.9 0 0 1-3.9-.9L3 20l1.2-4.3a8 8 0 0 1-1.2-4.2A8.4 8.4 0 0 1 11.5 3.2 8.4 8.4 0 0 1 21 11.5z"/></svg>답글</span>
        <span><svg viewBox="0 0 24 24"><path d="M17 2l4 4-4 4M3 11v-1a4 4 0 0 1 4-4h14M7 22l-4-4 4-4m14-1v1a4 4 0 0 1-4 4H3"/></svg>리포스트</span>
      </div>
      <div class="reply">
        <div class="avatar" id="avatar2">유</div>
        <div class="txt"><b id="handle2">-</b> · 첫 댓글<br><span class="cmt" id="comment"></span></div>
      </div>
    </div>
  </div>

  <div class="panel">
    <h3>📋 원클릭 복사 <span id="who-copy" style="color:var(--acc)"></span></h3>
    <button class="btn" onclick="copyText(this, () => POSTS[CUR].body)">① 본문 복사<small>쓰레드 새 글에 붙여넣기</small></button>
    <button class="btn" onclick="copyText(this, () => POSTS[CUR].comment)">② 첫 댓글 복사<small>게시 직후 내 글에 답글로 — 링크+고지문구 세트</small></button>
    <button class="btn" onclick="copyText(this, () => DATA.caption)">③ 인스타 캡션 복사<small>카드뉴스 그대로 인스타에 올릴 때</small></button>
    <div class="guide">
      <b>페르소나 4종 활용법</b><br>
      버튼 눌러 4개 글을 비교 → 계정 컨셉에 맞는 걸 게시.<br>
      계정을 여러 개 굴리면 페르소나별로 나눠 쓰기.<br><br>
      <b>게시 순서</b><br>
      1️⃣ 본문 붙여넣기 → 2️⃣ 카드뉴스 이미지 첨부 → 3️⃣ 게시 → 4️⃣ <b>첫 댓글</b>에 ② 붙여넣기<br><br>
      ⚖️ 첫 댓글의 파트너스 고지문구는 <b>법적 의무</b> — 링크와 항상 세트!
    </div>
  </div>

<script>
const DATA = {data_json};
const POSTS = DATA.posts;
let CUR = Object.keys(POSTS)[0];

function setPersona(name){{
  if(!POSTS[name]) return;
  CUR = name;
  const p = POSTS[name];
  const grad = `linear-gradient(135deg, ${{p.g1}}, ${{p.g2}})`;
  document.getElementById('body').textContent = p.body;
  document.getElementById('comment').textContent = p.comment;
  document.getElementById('handle').textContent = p.handle;
  document.getElementById('handle2').textContent = p.handle;
  for(const id of ['avatar','avatar2']){{
    const el = document.getElementById(id);
    el.textContent = name[0];
    el.style.background = grad;
  }}
  document.getElementById('who-copy').textContent = '· ' + name;
  document.querySelectorAll('.tab').forEach(t => {{
    const on = t.dataset.p === name;
    t.classList.toggle('on', on);
    t.style.setProperty('--pacc', p.g1);
  }});
}}
setPersona(CUR);

const strip = document.getElementById('strip');
const dots = [...document.querySelectorAll('.dots i')];
function slide(dir){{
  const w = strip.querySelector('img')?.clientWidth || 300;
  strip.scrollBy({{left: dir * (w + 8), behavior: 'smooth'}});
}}
strip.addEventListener('scroll', () => {{
  const w = (strip.querySelector('img')?.clientWidth || 300) + 8;
  const i = Math.round(strip.scrollLeft / w);
  dots.forEach((d, k) => d.classList.toggle('on', k === i));
}});
dots[0]?.classList.add('on');
function copyText(btn, getText){{
  const text = getText() || '';
  const done = () => {{
    btn.classList.add('copied');
    const old = btn.firstChild.textContent;
    btn.firstChild.textContent = '✓ 복사됨!';
    setTimeout(() => {{ btn.classList.remove('copied'); btn.firstChild.textContent = old; }}, 1400);
  }};
  if (navigator.clipboard && window.isSecureContext !== false) {{
    navigator.clipboard.writeText(text).then(done).catch(() => fallback());
  }} else fallback();
  function fallback(){{
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); ta.remove(); done();
  }}
}}
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("output_dir")
    args = ap.parse_args()

    d = Path(args.output_dir).resolve()
    posts = collect_posts(d)
    if not posts:
        print(f"[ERROR] threads_*.md / threads.md 없음: {d}")
        sys.exit(1)

    slides = sorted(p.name for p in d.glob("slide_*.png"))
    if not slides:
        slides = sorted(f"cards/{p.name}" for p in (d / "cards").glob("*.png")) if (d / "cards").exists() else []
    caption = (d / "caption.txt").read_text(encoding="utf-8") if (d / "caption.txt").exists() else ""
    product = d.name

    out = d / "preview.html"
    out.write_text(build_html(product, posts, slides, caption), encoding="utf-8")
    print(f"[ok] preview.html 생성 → {out}  (페르소나 {len(posts)}명: {', '.join(posts)})")
    print("     브라우저로 열기: open preview.html (윈도우: start preview.html)")


if __name__ == "__main__":
    main()
