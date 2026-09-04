#!/usr/bin/env python3
"""
server.py — 쿠팡 링크 → 카드뉴스 로컬 웹앱

실행: python webapp/server.py   (또는 바탕화면의 "카드뉴스 만들기" 바로가기)
브라우저가 자동으로 열린다. 터미널을 직접 쓸 일은 없다.

외부 의존성 없음 — 파이썬 표준 라이브러리만 쓴다.
"""

import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import traceback
import urllib.parse
import uuid
import webbrowser
import zipfile
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = Path(__file__).resolve().parent.parent
WEBAPP = ROOT / "webapp"
OUTPUT = ROOT / "output"
PY = sys.executable
PORT = int(os.environ.get("CARDNEWS_PORT", "8765"))

sys.path.insert(0, str(WEBAPP))
import gen  # noqa: E402
import images as imgpick  # noqa: E402
import specs  # noqa: E402
import review as reviewer  # noqa: E402
import update as updater  # noqa: E402

JOBS = {}
JOBS_LOCK = threading.Lock()

THEMES = [
    {"id": "frost", "name": "프로스트", "desc": "얼음빛 바탕 + 알약 라벨 + 큰 타이포",
     "palettes": [{"id": "ice", "name": "아이스 블루"}, {"id": "sage", "name": "세이지 그린"}]},
    {"id": "bold", "name": "볼드", "desc": "딥잉크 전면 + 풀블리드 사진", "palettes": []},
    {"id": "simple", "name": "심플", "desc": "화이트 + 굵은 고딕 + 형광 하이라이트", "palettes": []},
    {"id": "magazine", "name": "매거진", "desc": "크림톤 에디토리얼", "palettes": []},
    {"id": "default", "name": "다크 라임", "desc": "네이비 + 라임", "palettes": []},
]

HOOK_STYLES = [
    {"id": "auto", "name": "AI가 알아서", "prompt": "hooks.md의 6분류 중 이 상품에 가장 맞는 것을 골라라."},
    {"id": "problem", "name": "문제언급", "prompt": "1번 문제언급형(고통·결핍 자극)으로 후크를 잡아라. 원문에 전환율이 가장 높다고 적혀 있다."},
    {"id": "negative", "name": "통념 반박", "prompt": "3번 부정형(인지 충돌·통념 반박)으로 후크를 잡아라. 예상을 깨는 문장이어야 한다."},
    {"id": "gap", "name": "궁금증", "prompt": "4번 정보갭형으로 후크를 잡아라. 단, 통계·수치를 지어내지 말고 상품 데이터에 있는 사실로만."},
    {"id": "target", "name": "타겟 지정", "prompt": "5번 타겟언급형으로 후크를 잡아라. '~한 분만 보세요' 형태."},
    {"id": "benefit", "name": "이득 제시", "prompt": "2번 이득제시형으로 후크를 잡아라. 단, 금액은 쓰지 말 것."},
]


def personas():
    d = ROOT / "references" / "personas"
    out = []
    for f in sorted(d.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        first = text.splitlines()[0]
        desc = first.split("—", 1)[1].strip() if "—" in first else ""
        m = re.search(r"핸들\s*`([^`]+)`", text)
        out.append({"id": f.stem, "name": f.stem, "desc": desc,
                    "handle": m.group(1) if m else ""})
    return out


# ── 잡 실행 ────────────────────────────────────────────────

def log(job, msg):
    with JOBS_LOCK:
        JOBS[job]["log"].append(msg)
    print(f"[{job[:6]}] {msg}")


def stage(job, s):
    with JOBS_LOCK:
        JOBS[job]["stage"] = s
    log(job, f"── {s}")


def run(job, cmd, label):
    p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", bufsize=1)
    for line in p.stdout:
        line = line.rstrip()
        if line:
            log(job, line)
    p.wait()
    if p.returncode != 0:
        raise RuntimeError(f"{label} 실패 (코드 {p.returncode})")


def newest_output(before):
    dirs = [d for d in OUTPUT.iterdir() if d.is_dir()]
    fresh = [d for d in dirs if d not in before]
    if fresh:
        return max(fresh, key=lambda d: d.stat().st_mtime)
    return max(dirs, key=lambda d: d.stat().st_mtime) if dirs else None


def worker(job, req):
    try:
        OUTPUT.mkdir(exist_ok=True)

        if req.get("folder"):
            # 크롤링 건너뛰기 — 이미 받아둔 상품 폴더 재사용
            folder = (OUTPUT / req["folder"]).resolve()
            if not str(folder).startswith(str(OUTPUT.resolve())) or not folder.exists():
                raise RuntimeError("상품 폴더를 찾지 못했습니다")
            with JOBS_LOCK:
                JOBS[job]["folder"] = folder.name
            log(job, f"크롤링 건너뜀 — 기존 폴더 사용: {folder.name}")
        else:
            before = {d for d in OUTPUT.iterdir() if d.is_dir()}
            stage(job, "크롤링 — Chrome 창이 뜹니다. 건드리지 마세요")
            run(job, [PY, str(ROOT / "crawl.py"), req["url"], "--max-review-pages", "1"], "크롤링")

            folder = newest_output(before)
            if not folder:
                raise RuntimeError("크롤링 결과 폴더를 찾지 못했습니다")
            with JOBS_LOCK:
                JOBS[job]["folder"] = folder.name
            log(job, f"상품 폴더: {folder.name}")

            stage(job, "이미지 가공 — 리뷰 카드 렌더링")
            run(job, [PY, str(ROOT / "process_images.py"), str(folder), "--top-reviews", "5"], "이미지 가공")
            run(job, [PY, str(ROOT / "process_images.py"), str(folder), "--prepare-crops"], "크롭 준비")

        stage(job, "제품 사진 고르기 — 상세페이지에서 쓸 컷을 추립니다")
        imgpick.prepare(folder, req.get("provider"), req.get("apiKey"),
                        req.get("model"), gen._post, lambda m: log(job, m))

        stage(job, "상세페이지 읽기 — 스펙·인증·구성품을 뽑습니다")
        specs.prepare(folder, req.get("provider"), req.get("apiKey"),
                      req.get("model"), gen._post, lambda m: log(job, m))

        stage(job, "문구 생성 — AI가 카드 문구를 씁니다")
        hook_prompt = next((h["prompt"] for h in HOOK_STYLES if h["id"] == req.get("hook")),
                           HOOK_STYLES[0]["prompt"])
        gen.generate(folder, req["provider"], req["apiKey"], req.get("model") or None,
                     req.get("theme", "frost"), req.get("palette", "ice"),
                     req.get("persona", "정원"), hook_prompt)
        log(job, "slides.json 작성 완료")

        stage(job, "카드 렌더링 — PNG 만드는 중")
        run(job, [PY, str(ROOT / "scripts" / "render.py"), str(folder / "slides.json")], "렌더링")

        fixes = []
        if req.get("review", True):
            stage(job, "검수 — 만든 카드를 보고 잘못된 곳을 고칩니다")
            fixes = reviewer.run(folder, req.get("provider"), req.get("apiKey"),
                                 req.get("model"), gen._post, lambda m: log(job, m))
        if fixes:
            stage(job, f"수정한 {len(fixes)}장 다시 그리는 중")
            run(job, [PY, str(ROOT / "scripts" / "render.py"), str(folder / "slides.json"),
                      "--only", ",".join(str(n) for n in fixes)], "재렌더링")

        slides = sorted(folder.glob("slide_*.png"))
        with JOBS_LOCK:
            JOBS[job].update(done=True, stage="완료",
                             slides=[f.name for f in slides],
                             caption=(folder / "caption.txt").read_text(encoding="utf-8")
                             if (folder / "caption.txt").exists() else "")
        log(job, f"완료 — {len(slides)}장")

    except Exception as e:
        with JOBS_LOCK:
            JOBS[job].update(done=True, error=str(e), stage="실패")
        log(job, "오류: " + str(e))
        if not isinstance(e, gen.ApiError):
            log(job, traceback.format_exc(limit=3))


# ── HTTP ───────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)

        if u.path in ("/", "/index.html"):
            return self._send(200, (WEBAPP / "ui.html").read_text(encoding="utf-8"),
                              "text/html; charset=utf-8")

        if u.path == "/api/update/check":
            try:
                return self._send(200, updater.check())
            except Exception as e:
                return self._send(200, {"error": f"업데이트 확인 실패: {e}"})

        if u.path == "/api/config":
            return self._send(200, {"themes": THEMES, "personas": personas(),
                                    "hooks": HOOK_STYLES})

        if u.path == "/api/status":
            job = q.get("job", [""])[0]
            with JOBS_LOCK:
                j = JOBS.get(job)
                return self._send(200, dict(j) if j else {"error": "없는 작업"})

        if u.path == "/api/file":
            folder = q.get("folder", [""])[0]
            name = q.get("name", [""])[0]
            f = (OUTPUT / folder / name).resolve()
            if not str(f).startswith(str(OUTPUT.resolve())) or not f.exists():
                return self._send(404, {"error": "없는 파일"})
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if u.path == "/api/save":
            folder = q.get("folder", [""])[0]
            src = (OUTPUT / folder).resolve()
            if not str(src).startswith(str(OUTPUT.resolve())) or not src.exists():
                return self._send(404, {"error": "없는 폴더"})
            safe = re.sub(r'[\\/*?:"<>|,]', "", folder).strip()[:40] or "카드뉴스"
            dest = Path.home() / "Downloads" / f"{safe}_카드뉴스"
            dest.mkdir(parents=True, exist_ok=True)
            n = 0
            for f in sorted(src.glob("slide_*.png")):
                shutil.copy2(f, dest / f.name)
                n += 1
            for extra in ("caption.txt", "slides.json"):
                if (src / extra).exists():
                    shutil.copy2(src / extra, dest / extra)
            return self._send(200, {"path": str(dest), "count": n})

        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")

        if u.path == "/api/update/apply":
            lines = []
            try:
                r = updater.apply(log=lambda m: lines.append(m))
                r["log"] = lines
                return self._send(200, r)
            except Exception as e:
                return self._send(200, {"error": f"업데이트 실패: {e}", "log": lines})

        if u.path == "/api/redesign":
            folder = (body.get("folder") or "").strip()
            src = (OUTPUT / folder).resolve()
            sj = src / "slides.json"
            if not str(src).startswith(str(OUTPUT.resolve())) or not sj.exists():
                return self._send(404, {"error": "슬라이드 정보를 찾지 못했습니다"})
            data = json.loads(sj.read_text(encoding="utf-8"))
            data["design"] = {**(data.get("design") or {}), **(body.get("design") or {})}
            sj.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

            cmd = [PY, str(ROOT / "scripts" / "render.py"), str(sj)]
            only = body.get("only")
            if only:
                cmd += ["--only", ",".join(str(n) for n in only)]
            try:
                subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=600, check=True)
            except subprocess.CalledProcessError as e:
                tail = (e.stdout or "")[-800:]
                return self._send(500, {"error": "렌더링 실패\n" + tail})
            slides = sorted(f.name for f in src.glob("slide_*.png"))
            return self._send(200, {"slides": slides, "stamp": int(datetime.now().timestamp())})

        if u.path == "/api/create":
            url = (body.get("url") or "").strip()
            if not body.get("folder") and not re.search(r"(coupang\.com|link\.coupang\.com)", url):
                return self._send(400, {"error": "쿠팡 상품 링크가 아닙니다"})
            if not body.get("apiKey"):
                return self._send(400, {"error": "API 키를 입력해 주세요"})
            job = uuid.uuid4().hex
            with JOBS_LOCK:
                JOBS[job] = {"stage": "대기 중", "log": [], "done": False,
                             "error": None, "folder": None, "slides": [],
                             "caption": "", "started": datetime.now().isoformat()}
            threading.Thread(target=worker, args=(job, body), daemon=True).start()
            return self._send(200, {"job": job})

        return self._send(404, {"error": "not found"})


def main():
    OUTPUT.mkdir(exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print("=" * 52)
    print("  쿠팡 카드뉴스 만들기")
    print("=" * 52)
    print(f"  브라우저가 열립니다 → {url}")
    print("  끄려면 이 창을 닫으세요.")
    print("=" * 52)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")


if __name__ == "__main__":
    main()
