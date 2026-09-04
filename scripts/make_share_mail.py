#!/usr/bin/env python3
"""
make_share_mail.py — 메일로 보낼 수 있는 배포본을 만든다.

    python scripts/make_share_mail.py

네이버·다음 등 메일 서비스는 .bat 을 실행파일로 보고 차단한다.
압축 안에 있어도 검사해서 걸러낸다.
그래서 .bat 을 .bat.txt 로 바꿔 담고, 되돌리는 방법을 안내문으로 넣는다.

프로젝트 원본에서 새로 싼다 (기존 공유용 폴더를 복사하지 않는다 —
거기서 설치를 돌렸으면 .venv 가 딸려 들어간다).
결과: 다운로드/쿠팡카드뉴스_메일용.zip
"""

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_share  # noqa: E402

DEST = Path.home() / "Downloads" / "쿠팡카드뉴스_메일용"

FIRST_STEP = """# 먼저 이것부터 하세요 (30초)

메일로 보내면 실행 파일이 막혀서, 이름을 살짝 바꿔 두었습니다.
**압축을 푼 뒤 아래 두 파일 이름 끝의 `.txt` 를 지워주세요.**

    설치하기.bat.txt        →   설치하기.bat
    카드뉴스 만들기.bat.txt  →   카드뉴스 만들기.bat

## 파일 이름 끝에 `.txt` 가 안 보이면

윈도우가 확장자를 숨기고 있어서 그렇습니다.

1. 탐색기 위쪽 **보기** 탭 클릭
2. **파일 확장명** 체크

이제 `.txt` 가 보입니다. 파일 우클릭 → **이름 바꾸기** 로 `.txt` 만 지우세요.
"확장명을 바꾸면 사용할 수 없게 될 수 있습니다" 라고 물으면 **예** 를 누르시면 됩니다.

---

이름을 바꾼 뒤 **`처음 시작하기.md`** 를 열어 그대로 따라 하시면 됩니다.
"""


def main():
    # 원본에서 깨끗하게 새로 싼다
    make_share.DEST = DEST
    make_share.main()

    renamed = []
    for f in sorted(DEST.glob("*.bat")):
        target = f.with_name(f.name + ".txt")
        f.rename(target)
        renamed.append(target.name)

    (DEST / "0. 먼저 읽어주세요.md").write_text(FIRST_STEP, encoding="utf-8")

    zip_path = DEST.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in DEST.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(DEST.parent))

    print("\n─── 메일용으로 이름 바꾼 파일 ───")
    for r in renamed:
        print("  ·", r)
    print(f"\n메일에 첨부할 파일: {zip_path}  "
          f"({zip_path.stat().st_size/1024/1024:.1f} MB)")
    print("받는 사람은 '0. 먼저 읽어주세요.md' 대로 이름만 되돌리면 됩니다.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
