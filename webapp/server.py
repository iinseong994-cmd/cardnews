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
import book_gen  # noqa: E402
import book_images  # noqa: E402


# 교보문고 링크 / ISBN 이면 책 흐름으로 간다. 쿠팡 흐름은 그대로 둔다.
BOOK_HOST = re.compile(r"(product|search)\.kyobobook\.co\.kr", re.I)
ISBN_ONLY = re.compile(r"^\s*97[89][\d-]{10,14}\s*$")


def is_book_job(req):
    if req.get("folder"):
        return (OUTPUT / req["folder"] / "book.json").exists()
    u = req.get("url") or ""
    return bool(BOOK_HOST.search(u) or ISBN_ONLY.match(u))

def setup_problem():
    """설치가 안 됐으면 사람이 읽을 수 있는 안내를 돌려준다. 정상이면 None."""
    missing = []
    for mod, why in (("playwright", "쿠팡 크롤링·카드 렌더링"),
                     ("PIL", "이미지 처리"),
                     ("jinja2", "카드 템플릿")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(f"{mod} ({why})")
    if not missing:
        return None
    venv = ROOT / ".venv" / "Scripts" / "python.exe"
    return ("설치가 끝나지 않았습니다.\n\n"
            "없는 것: " + ", ".join(missing) + "\n\n"
            + ("이 폴더에 설치가 안 돼 있습니다.\n"
               if not venv.exists() else
               "설치 폴더(.venv)는 있는데 그걸로 실행되지 않았습니다.\n")
            + f"→ 폴더에서 '설치하기.bat' 를 더블클릭해 주세요.\n   ({ROOT})")


SETUP_ERROR = setup_problem()

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


def stage(job, s, pct=None):
    with JOBS_LOCK:
        JOBS[job]["stage"] = s
        if pct is not None:
            JOBS[job]["percent"] = pct
    log(job, f"── {s}")


def run(job, cmd, label):
    p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", bufsize=1)
    lines = []
    for line in p.stdout:
        line = line.rstrip()
        if line:
            log(job, line)
            lines.append(line)
    p.wait()
    if p.returncode != 0:
        raise RuntimeError(f"{label} 실패 (코드 {p.returncode})")
    return lines


def result_dir(lines, before):
    """크롤러가 알려준 결과 폴더. 못 찾으면 예전 방식(수정시각)으로 넘어간다.

    ⚠️ 수정시각 추측은 **이미 받아둔 걸 다시 받을 때 틀린다.**
       그 폴더는 '새로 생긴 폴더' 가 아니어서, 마침 더 최근에 손댄
       다른 폴더를 집어 엉뚱한 상품의 카드가 나온 적이 있다.
    """
    for line in reversed(lines or []):
        if line.startswith("RESULT_DIR="):
            d = Path(line.split("=", 1)[1].strip())
            if d.exists():
                return d
    return newest_output(before)


def newest_output(before):
    dirs = [d for d in OUTPUT.iterdir() if d.is_dir()]
    fresh = [d for d in dirs if d not in before]
    if fresh:
        return max(fresh, key=lambda d: d.stat().st_mtime)
    return max(dirs, key=lambda d: d.stat().st_mtime) if dirs else None


def prepare_book(job, req):
    """교보문고 링크 → book.json → 표지 카드 → slides.json. 폴더를 돌려준다."""
    if req.get("folder"):
        folder = (OUTPUT / req["folder"]).resolve()
        if not str(folder).startswith(str(OUTPUT.resolve())) or not folder.exists():
            raise RuntimeError("책 폴더를 찾지 못했습니다")
        log(job, f"크롤링 건너뜀 — 기존 폴더 사용: {folder.name}")
        with JOBS_LOCK:
            JOBS[job].update(folder=folder.name, percent=40)
    else:
        before = {d for d in OUTPUT.iterdir() if d.is_dir()}
        stage(job, "교보문고에서 책 정보 가져오는 중", 8)
        lines = run(job, [PY, str(ROOT / "book_crawl.py"), req["url"]], "책 크롤링")
        folder = result_dir(lines, before)
        if not folder:
            raise RuntimeError("크롤링 결과 폴더를 찾지 못했습니다")
        with JOBS_LOCK:
            JOBS[job].update(folder=folder.name, percent=45)
        log(job, f"책 폴더: {folder.name}")

    stage(job, "표지 카드 만드는 중", 55)
    made = book_images.build_book_images(folder)
    log(job, f"표지 이미지 {len(made)}장" if made else "표지 파일이 없습니다 — 글자 카드로만 만듭니다")

    stage(job, "문구 생성 — AI가 카드 문구를 씁니다", 68)
    hook_prompt = next((h["prompt"] for h in HOOK_STYLES if h["id"] == req.get("hook")),
                       HOOK_STYLES[0]["prompt"])
    book_gen.generate(folder, req["provider"], req["apiKey"], req.get("model") or None,
                      req.get("theme", "frost"), req.get("palette", "ice"),
                      req.get("persona", "정원"), hook_prompt,
                      disclosure=req.get("disclosure", ""))
    log(job, "slides.json 작성 완료")
    return folder


def worker(job, req):
    try:
        OUTPUT.mkdir(exist_ok=True)

        if is_book_job(req):
            folder = prepare_book(job, req)
        elif req.get("folder"):
            # 크롤링 건너뛰기 — 이미 받아둔 상품 폴더 재사용
            folder = (OUTPUT / req["folder"]).resolve()
            if not str(folder).startswith(str(OUTPUT.resolve())) or not folder.exists():
                raise RuntimeError("상품 폴더를 찾지 못했습니다")
            with JOBS_LOCK:
                JOBS[job]["folder"] = folder.name
            log(job, f"크롤링 건너뜀 — 기존 폴더 사용: {folder.name}")
            with JOBS_LOCK:
                JOBS[job]["percent"] = 40
        else:
            before = {d for d in OUTPUT.iterdir() if d.is_dir()}
            stage(job, "크롤링 — Chrome 창이 뜹니다. 건드리지 마세요", 5)
            lines = run(job, [PY, str(ROOT / "crawl.py"), req["url"],
                              "--max-review-pages", "1"], "크롤링")

            folder = result_dir(lines, before)
            if not folder:
                raise RuntimeError("크롤링 결과 폴더를 찾지 못했습니다")
            with JOBS_LOCK:
                JOBS[job]["folder"] = folder.name
            log(job, f"상품 폴더: {folder.name}")

            stage(job, "이미지 가공 — 리뷰 카드 렌더링", 40)
            run(job, [PY, str(ROOT / "process_images.py"), str(folder), "--top-reviews", "5"], "이미지 가공")
            run(job, [PY, str(ROOT / "process_images.py"), str(folder), "--prepare-crops"], "크롭 준비")

        if not is_book_job(req):
            # 여기부터는 상품 전용 — 책은 사진이 표지 한 장뿐이라 고를 것도, 읽을 상세페이지도 없다
            stage(job, "제품 사진 고르기 — 상세페이지에서 쓸 컷을 추립니다", 48)
            imgpick.prepare(folder, req.get("provider"), req.get("apiKey"),
                            req.get("model"), gen._post, lambda m: log(job, m))

            stage(job, "상세페이지 읽기 — 스펙·인증·구성품을 뽑습니다", 58)
            specs.prepare(folder, req.get("provider"), req.get("apiKey"),
                          req.get("model"), gen._post, lambda m: log(job, m))

            stage(job, "문구 생성 — AI가 카드 문구를 씁니다", 72)
            hook_prompt = next((h["prompt"] for h in HOOK_STYLES if h["id"] == req.get("hook")),
                               HOOK_STYLES[0]["prompt"])
            gen.generate(folder, req["provider"], req["apiKey"], req.get("model") or None,
                         req.get("theme", "frost"), req.get("palette", "ice"),
                         req.get("persona", "정원"), hook_prompt)
            log(job, "slides.json 작성 완료")

        stage(job, "카드 렌더링 — PNG 만드는 중", 80)
        run(job, [PY, str(ROOT / "scripts" / "render.py"), str(folder / "slides.json")], "렌더링")

        fixes = []
        if req.get("review", True):
            stage(job, "검수 — 만든 카드를 보고 잘못된 곳을 고칩니다", 90)
            fixes = reviewer.run(folder, req.get("provider"), req.get("apiKey"),
                                 req.get("model"), gen._post, lambda m: log(job, m))
        if fixes:
            stage(job, f"수정한 {len(fixes)}장 다시 그리는 중", 96)
            run(job, [PY, str(ROOT / "scripts" / "render.py"), str(folder / "slides.json"),
                      "--only", ",".join(str(n) for n in fixes)], "재렌더링")

        slides = sorted(folder.glob("slide_*.png"))
        with JOBS_LOCK:
            JOBS[job].update(done=True, stage="완료", percent=100,
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
                                    "hooks": HOOK_STYLES, "setupError": SETUP_ERROR})

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
            # 카드 파일 이름은 매번 slide_01.png 로 같다.
            # 이게 없으면 두 번째 만들 때 브라우저가 예전 그림을 꺼내 보여준다.
            self.send_header("Cache-Control", "no-store, must-revalidate")
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
            if SETUP_ERROR:
                return self._send(400, {"error": SETUP_ERROR})
            url = (body.get("url") or "").strip()
            known = (re.search(r"coupang\.com", url) or is_book_job(body))
            if not body.get("folder") and not known:
                return self._send(400, {"error":
                    "알아볼 수 없는 링크입니다.\n\n"
                    "· 쿠팡 상품 링크 (coupang.com / link.coupang.com)\n"
                    "· 교보문고 책 링크 (product.kyobobook.co.kr)\n"
                    "· 또는 ISBN 13자리"})
            if not body.get("apiKey"):
                return self._send(400, {"error": "API 키를 입력해 주세요"})
            job = uuid.uuid4().hex
            with JOBS_LOCK:
                JOBS[job] = {"stage": "대기 중", "percent": 0, "log": [], "done": False,
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
    print("  카드뉴스 만들기 — 쿠팡 상품 · 교보문고 책")
    print("=" * 52)
    if SETUP_ERROR:
        print()
        print("  [!] " + SETUP_ERROR.replace("\n", "\n      "))
        print()
        print("=" * 52)
    print(f"  브라우저가 열립니다 → {url}")
    print("  끄려면 이 창을 닫으세요.")
    print("=" * 52)
    # CARDNEWS_NO_BROWSER=1 이면 브라우저를 안 연다 (자동 점검용)
    if not os.environ.get("CARDNEWS_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")


if __name__ == "__main__":
    main()
