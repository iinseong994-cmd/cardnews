# Coupang Contents — 쿠팡 링크 하나로 쓰레드 글 + 카드뉴스

쿠팡 파트너스 링크 하나를 주면: 크롤링 → 이미지 가공 → 쓰레드 글 + 카드뉴스 PNG까지 자동 생성.

## 사용자 프로필

개발을 모르는 일반인 (오토워커 수강생). 터미널 명령어를 직접 치지 않는다.
모든 작업은 **자연어로 요청**하면 Claude가 대신 실행한다.
에러가 나면 Claude가 에러 메시지를 보고 스스로 해결을 시도하고, 안 되면 쉬운 말로 설명한다.

## ⚠️ 파트너스 링크 취급 (중요)

- 사용자가 준 **원본 파트너스 링크(link.coupang.com/a/...)를 반드시 변수로 보관**한다.
  크롤러는 추적 파라미터를 제거한 URL로 접속하지만, **게시할 때 쓰는 링크는 원본 파트너스 링크**다 (수익 트래킹).
- 파트너스 링크가 노출되는 모든 곳에 고지문구 동반 (하단 "파트너스 고지" 참고).

## 트리거별 동작

### "초기 세팅해줘" / "세팅해줘" / "설치해줘"

프로젝트 폴더(이 CLAUDE.md가 있는 폴더)에서 순서대로 실행:

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install playwright pillow jinja2
playwright install chromium
```

```powershell
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\activate
pip install playwright pillow jinja2
playwright install chromium
```

완료 후: "세팅 완료! 이제 쿠팡 링크를 주시면 크롤링할 수 있습니다."

### 쿠팡 URL 감지 / "이 링크로 콘텐츠 만들어줘"

사용자가 쿠팡 링크(`link.coupang.com` 또는 `coupang.com/vp/products`)를 주면:

1. **원본 링크를 기억해 둔다** (게시용)
2. 크롤링+이미지 가공:
   ```bash
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   python3 pipeline.py "<URL>"
   ```
   - 크롤링 중 Chrome 창이 새로 뜨는 건 정상 (차단 우회용). 사용자에게 미리 안내.
   - **Access Denied** 발생 시: 떠 있는 Chrome 창에서 coupang.com을 직접 한번 둘러본 뒤 재실행하면 통과. 사용자에게 안내.
3. 완료 후 `/make-coupang-contents` 스킬 자동 연결 (가장 최근 output 폴더 사용)
4. 콘텐츠 생성이 끝나면 **preview.html 생성 + 자동 열기**:
   ```bash
   python3 scripts/preview.py "output/<제품폴더>" && open "output/<제품폴더>/preview.html"
   ```
   (윈도우는 `start` 사용) — 쓰레드 게시글 미리보기 + 원클릭 복사 화면으로 결과를 보여준다.

### "카드뉴스 앱 켜줘" / "웹앱 켜줘"

프로젝트 폴더의 **`카드뉴스 만들기.bat`을 더블클릭**하면 브라우저가 열린다 (사용자가 직접 실행).
Claude가 대신 켤 때는:

```powershell
Start-Process "카드뉴스 만들기.bat"
```

쿠팡 링크 + 본인 API 키(Gemini 무료 가능)를 넣으면 크롤링 → 이미지 가공 → 문구 생성 → 렌더링까지 한 번에 돈다.
- 코드: `webapp/server.py`(로컬 서버) · `webapp/ui.html`(화면) · `webapp/gen.py`(문구 생성 프롬프트)
- 표준 라이브러리만 쓴다 (추가 설치 없음). 포트 8765.
- 결과 화면 아래 **디자인 다듬기**: 계정 라벨(@핸들)·제목/본문 크기·좌우 여백·페이지 번호를 조절하고 `1장 미리보기`(2~3초) → `전체 적용`. 값은 slides.json의 `design` 블록에 저장된다 (`scripts/design.py`).
- **넷리파이 같은 공개 웹으로는 못 만든다** — 쿠팡 크롤링에 로컬 Chrome이 필요하다.

### "쿠팡 콘텐츠 만들어줘" / "/make-coupang-contents"

→ `.claude/skills/make-coupang-contents/SKILL.md` 스킬 실행.

### "카드뉴스 만들어줘" / "카드뉴스 다시 만들어줘"

스킬의 카드뉴스 단계(slides.json 작성 → 렌더링)만 다시 실행:

```bash
source .venv/bin/activate
python3 scripts/render.py "output/<제품폴더>/slides.json"
```

### "리뷰카드 만들어줘"

```bash
source .venv/bin/activate
python3 process_images.py output/<제품폴더> --top-reviews 5
```

### "미리보기 보여줘" / "결과 보여줘"

```bash
python3 scripts/preview.py "output/<제품폴더>"
open "output/<제품폴더>/preview.html"   # Windows: start
```

### "광고형 이미지로도 만들어줘" / "AI 이미지 버전"

→ 스킬의 Step 6-4 (옵션) 실행. `GEMINI_API_KEY` 필요 — 없으면 aistudio.google.com에서 무료 발급 안내.

### 페르소나 시스템 (쓰레드 글 4종)

쓰레드 글은 **페르소나 6명 각각의 목소리로 총 6개** 생성된다 (`threads_유진.md` 외 5종):

| 이름 | 컨셉 | 파일 |
|---|---|---|
| 유진 (기본) | 26살 자취러 마케터, 텐션 높은 반말 | `references/personas/유진.md` |
| 살까말까 | 20대 중반 직장인, 본가 거주, 결론부터+근거로 말하는 비교형 | `references/personas/살까말까.md` |
| 수현 | 35살 워킹맘, 현실 공감+ㅠㅠ | `references/personas/수현.md` |
| 태오 | 24살 대학생, 음슴체 밈 드립 | `references/personas/태오.md` |
| 하루 | 28살 직장인, 단문·장면으로 보여줌 | `references/personas/하루.md` |
| 정원 | 33살, 다 찾아보고 정리해주는 존댓말 | `references/personas/정원.md` |

- 공통 규칙(글 구조·길이·사실성 가드레일)은 `references/persona.md`
- **후크(표지 문구·첫 줄)는 `references/hooks.md`** — 심리 6분류로 서로 다른 후보를 뽑고, 금지 패턴을 피한다
- preview.html 상단의 **페르소나 버튼**으로 4개 글을 전환하며 비교 → 마음에 드는 것만 게시
- 사용자가 "말투 바꿔줘", "내 페르소나로 해줘", "페르소나 추가해줘"라고 하면:
  `references/personas/<이름>.md`를 수정/추가하고 `references/persona.md`의 목록 표 + `scripts/preview.py`의 `PERSONA_META`(핸들·아바타 색)도 함께 갱신한다.

## 파트너스 고지 (의무 — 생략 금지)

쿠팡 파트너스 링크를 게시하는 모든 곳에 다음 문구가 함께 노출돼야 한다:

> 이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.

- 쓰레드: 링크를 다는 **첫 댓글에 링크와 함께**
- 카드뉴스: **CTA(마지막) 슬라이드의 subhead**에 포함

## 프로젝트 구조

```
coupang-contents/
├── CLAUDE.md              ← 이 파일
├── crawl.py               ← 쿠팡 상품 크롤러 (Chrome remote debug)
├── process_images.py      ← 리뷰카드 렌더링 + 이미지 크롭
├── pipeline.py            ← crawl + process_images 한 번에
├── .claude/skills/
│   └── make-coupang-contents/
│       └── SKILL.md       ← 콘텐츠 생성 스킬 (쓰레드 글 + 카드뉴스)
├── references/            ← 플랫폼별 글쓰기 규칙
│   ├── hooks.md           ← 후킹멘트 6분류 + 금지 패턴 (표지 후크·첫 줄)
│   ├── persona.md         ← 쓰레드 페르소나 공통 규칙 + 6인 목록
│   └── personas/          ← 페르소나별 목소리 (유진·살까말까·수현·태오·하루·정원)
├── webapp/                ← 로컬 웹앱 (쿠팡 링크 → 카드뉴스)
│   ├── server.py          ← 로컬 서버 (표준 라이브러리만)
│   ├── ui.html            ← 브라우저 화면
│   └── gen.py             ← 문구 생성 (Gemini/Claude/GPT)
├── 카드뉴스 만들기.bat     ← 더블클릭하면 앱이 켜진다
├── templates/             ← 카드뉴스/리뷰카드 HTML 템플릿
├── scripts/render.py      ← slides.json → 카드뉴스 PNG 렌더링
└── output/                ← 크롤링 결과 + 완성 콘텐츠 (제품별 폴더)
    └── 에어뮤즈 멜라이드 자외선차단패치_7441341673/   ← 완주 예시
```

## 주의사항

- Chrome이 뜨는 건 Akamai 차단 우회를 위한 정상 동작. 크롤링 중 그 브라우저를 직접 조작하지 않기.
- output/ 폴더는 상품별로 자동 생성됨 (상품명_상품ID)
- 숫자(가격·리뷰 수·평점)는 절대 지어내지 않는다 — 전부 크롤링 데이터에서.
- Windows: Chrome이 기본 경로에 없으면 crawl.py 상단 `CHROME_PATH`를 본인 설치 경로로 수정.
