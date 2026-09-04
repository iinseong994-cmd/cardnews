#!/usr/bin/env python3
"""
update.py — GitHub 에서 최신 코드를 받아 프로그램을 갱신한다.

받는 사람이 zip 을 다시 받거나 설치를 다시 할 필요가 없다.
앱 화면의 "업데이트" 버튼이 이걸 부른다.

건드리지 않는 것: .venv (설치 환경), output (내 작업물), 크롬 프로필
"""

import io
import json
import shutil
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REPO = "iinseong994-cmd/cardnews"
BRANCH = "main"
API_URL = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
ZIP_URL = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"
VERSION_FILE = ROOT / "version.json"

# 업데이트가 덮어쓰면 안 되는 것 — 각자의 환경·작업물
PROTECTED = {".venv", "venv", "output", "__pycache__", "profile", "warmup",
             ".git", "version.json", "threads.md"}

UA = {"User-Agent": "cardnews-updater"}


def local_version():
    if VERSION_FILE.exists():
        try:
            return json.loads(VERSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def remote_version(timeout=15):
    req = urllib.request.Request(API_URL, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    return {
        "sha": d["sha"],
        "message": (d.get("commit", {}).get("message") or "").split("\n")[0],
        "date": (d.get("commit", {}).get("author") or {}).get("date", ""),
    }


def check():
    """지금 버전이 최신인지 확인만 한다"""
    remote = remote_version()
    local = local_version()
    same = local.get("sha") == remote["sha"]
    return {
        "latest": same,
        "current": (local.get("sha") or "")[:7] or "알 수 없음",
        "newest": remote["sha"][:7],
        "message": remote["message"],
        "date": remote["date"][:10],
    }


def _safe_members(zf):
    """zip 안의 경로가 폴더 밖으로 튀지 않는지 검사"""
    out = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        parts = Path(info.filename).parts[1:]     # 맨 앞 저장소명 폴더 제거
        if not parts:
            continue
        if any(p in ("..",) for p in parts):
            continue
        if any(p in PROTECTED for p in parts):
            continue
        out.append((info, Path(*parts)))
    return out


def apply(log=print):
    """최신 코드를 받아 덮어쓴다. 내 작업물(output)과 설치(.venv)는 건드리지 않는다."""
    remote = remote_version()
    local = local_version()
    if local.get("sha") == remote["sha"]:
        log("이미 최신입니다")
        return {"updated": False, "current": remote["sha"][:7]}

    log("최신 파일을 받는 중...")
    req = urllib.request.Request(ZIP_URL, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        blob = r.read()
    log(f"내려받기 완료 ({len(blob)/1024/1024:.1f} MB)")

    changed = []
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        members = _safe_members(zf)
        for info, rel in members:
            target = ROOT / rel
            data = zf.read(info)
            if target.suffix.lower() in (".bat", ".cmd"):
                # Windows cmd 는 배치 파일에 CRLF 가 없으면 줄을 못 끊는다.
                # 어디선가 LF 로 바뀌어 와도 여기서 되돌린다.
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            if target.exists() and target.read_bytes() == data:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            changed.append(str(rel).replace("\\", "/"))

    VERSION_FILE.write_text(json.dumps({
        "sha": remote["sha"],
        "message": remote["message"],
        "applied_at": datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"파일 {len(changed)}개 갱신됨")
    for c in changed[:12]:
        log("  · " + c)
    if len(changed) > 12:
        log(f"  · 외 {len(changed)-12}개")

    return {"updated": True, "count": len(changed), "files": changed[:20],
            "current": remote["sha"][:7], "message": remote["message"]}


def stamp_current(sha=None):
    """지금 폴더를 '최신'으로 표시 (개발 컴퓨터에서 배포본을 만들 때 사용)"""
    info = remote_version() if sha is None else {"sha": sha, "message": ""}
    VERSION_FILE.write_text(json.dumps({
        "sha": info["sha"],
        "message": info.get("message", ""),
        "applied_at": datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return info["sha"][:7]
