#!/usr/bin/env python3
"""
make_share.py — 남에게 줄 수 있는 배포 폴더 + zip 을 만든다.

    python scripts/make_share.py

개인 파일(.venv, output, 내가 쓴 글, 크롬 프로필)은 빼고
프로그램이 도는 데 필요한 것만 담는다.
결과: 다운로드/쿠팡카드뉴스_공유용/  +  쿠팡카드뉴스_공유용.zip
"""

import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = Path.home() / "Downloads" / "쿠팡카드뉴스_공유용"

# 통째로 담을 폴더
DIRS = ["scripts", "templates", "references", "webapp", ".claude"]

# 낱개로 담을 파일
FILES = [
    "crawl.py", "pipeline.py", "process_images.py",
    "CLAUDE.md", "처음 시작하기.md",
    "설치하기.bat", "카드뉴스 만들기.bat",
]

# 어디에 있든 제외
SKIP_NAMES = {"__pycache__", ".venv", ".git", "output", "profile", "warmup",
              ".DS_Store", "node_modules"}
SKIP_SUFFIX = {".pyc", ".pyo", ".log"}


def ignore(dirpath, names):
    out = []
    for n in names:
        if n in SKIP_NAMES or Path(n).suffix in SKIP_SUFFIX:
            out.append(n)
    return out


def main():
    # 이미 설치를 돌린 폴더면 .venv 를 살려둔다 (지우면 다시 설치해야 한다)
    keep_venv = DEST / ".venv"
    stash = None
    if keep_venv.exists():
        stash = DEST.parent / (DEST.name + "__venv_임시")
        if stash.exists():
            shutil.rmtree(stash)
        keep_venv.rename(stash)
        print("기존 설치(.venv)를 잠시 옮겨둡니다 — 갱신 후 되돌립니다")

    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)

    if stash:
        stash.rename(DEST / ".venv")
        print("기존 설치(.venv) 복구 완료 — 다시 설치할 필요 없습니다")

    copied, missing = [], []

    for d in DIRS:
        src = ROOT / d
        if not src.exists():
            missing.append(d)
            continue
        shutil.copytree(src, DEST / d, ignore=ignore)
        copied.append(d + "/")

    for f in FILES:
        src = ROOT / f
        if not src.exists():
            missing.append(f)
            continue
        shutil.copy2(src, DEST / f)
        copied.append(f)

    # 배포본이 자기 버전을 알아야 "업데이트 확인" 이 제대로 뜬다
    try:
        sys.path.insert(0, str(ROOT / "webapp"))
        import update as updater
        info = updater.remote_version()
        (DEST / "version.json").write_text(
            json.dumps({"sha": info["sha"], "message": info["message"],
                        "applied_at": "배포본"}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print("버전 표시:", info["sha"][:7])
    except Exception as e:
        print("버전 표시 실패(무시하고 진행):", e)

    # 받는 사람이 처음 켰을 때 빈 폴더가 있어야 한다
    (DEST / "output").mkdir(exist_ok=True)
    (DEST / "output" / "여기에 결과가 저장됩니다.txt").write_text(
        "쿠팡 링크로 카드뉴스를 만들면 상품별 폴더가 여기에 생깁니다.\n",
        encoding="utf-8")

    # zip
    zip_path = DEST.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    def shareable(p):
        """받는 사람에게 필요 없는 것은 압축에서 뺀다 (.venv 는 각자 만든다)"""
        return not any(part in SKIP_NAMES for part in p.relative_to(DEST).parts)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in DEST.rglob("*"):
            if p.is_file() and shareable(p):
                z.write(p, p.relative_to(DEST.parent))

    total = sum(p.stat().st_size for p in DEST.rglob("*")
                if p.is_file() and shareable(p))
    print("담은 것:")
    for c in sorted(copied):
        print("  ·", c)
    if missing:
        print("\n[!] 없어서 못 담은 것:", ", ".join(missing))
    print(f"\n폴더 : {DEST}   ({total/1024/1024:.1f} MB)")
    print(f"압축 : {zip_path}  ({zip_path.stat().st_size/1024/1024:.1f} MB)")
    print("\n받는 사람은 압축을 풀고 '처음 시작하기.md' 대로 하면 됩니다.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
