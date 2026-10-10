# insta-photo-agents

짧은 글과 함께 올라가는 감성 사진 인스타 계정을 운영하는 Claude Code 에이전트 팀.

## 파이프라인

```
photos/inbox ─▶ photo-curator ─▶ photos/selected + manifest.json
                                        │
                     correct_photos (회전·키스톤 자동 보정 → photos/corrected)
                                        │
                     [사용자 검수: 전후 비교 확인 → 승인/거절, 대기 중이면 export 불가]
                                        │
trend-researcher ─▶ research/*.md ──────┤
                                        ▼
                               content-planner ─▶ content/drafts/*.json
                                                        │
                                                caption-writer (캡션·해시태그)
                                                        │
                                  [사용자 검토: drafts → approved 로 파일 이동]
                                                        │
                                        publisher (dry-run → 채팅 승인 → Graph API)
                                                        │
                                               growth-analyst ─▶ 주간 리포트 ─▶ 다음 기획
```

## 팀

| 에이전트 | 역할 | 쓰기 권한 |
|---|---|---|
| trend-researcher | 감성 레퍼런스 계정·성장 전략 조사 | research/ |
| photo-curator | 사진 태깅·점수·선별·시리즈 묶기 | photos/selected, manifest.json |
| content-planner | 주간 캘린더·그리드 흐름·패키지 골격 | content/drafts |
| caption-writer | 짧은 글·해시태그 | content/drafts |
| publisher | 승인분만 Graph API 게시 | content/scheduled, photos/posted |
| growth-analyst | 인사이트 수집·리포트 | research/insights.csv, weekly-*.md |

## 사용법
1. 사진을 `photos/inbox/`에 넣는다.
2. 이 폴더에서 Claude Code를 열고 "photo-curator로 inbox 분류해줘"처럼 요청한다.
3. 캡션이 채워진 `content/drafts/*.json`을 검토하고, 올릴 것만 `content/approved/`로 옮긴다.
4. "publisher로 dry-run 보여줘" → 확인 후 "게시해줘".

## 게시 설정 (최초 1회, 사용자가 직접)
1. 인스타그램 앱 → 설정 → 계정 유형을 **프로페셔널(크리에이터 또는 비즈니스)** 로 전환.
2. developers.facebook.com → 앱 만들기 → 유형 **Business**, Instagram API 사용 사례 추가.
3. 앱 대시보드 → Instagram → **API setup with Instagram business login** → 계정 추가 → **Generate token** (60일 토큰, 권한 `instagram_business_basic`·`instagram_business_content_publish`, 댓글 자동 답글을 쓰면 `instagram_business_manage_comments`도).
4. 아래 요청 결과의 `user_id`가 `IG_USER_ID`다(브라우저 주소창에 넣어도 됨, 결과 화면은 공유 금지).
   `https://graph.instagram.com/v25.0/me?fields=user_id,username&access_token=<토큰>`
5. 프로젝트 루트에 `.env` 작성 (커밋 금지, .gitignore에 등록됨):
   ```
   IG_USER_ID=...
   IG_ACCESS_TOKEN=...
   ```
   새 게시 엔진(아래 "게시 화면" 절)은 `INSTAGRAM_ACCESS_TOKEN`·`INSTA_HOSTING_TOKEN` 이름을 쓴다. 위 `IG_*` 이름은 기존 `scripts/` 스크립트용이다. 두 이름을 같은 `.env`에 함께 둬도 된다.
6. 토큰은 60일 뒤 만료된다. 만료 전(발급 24시간 이후) 갱신: `https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=<토큰>` → 새 토큰으로 `.env` 교체.

Graph API는 이미지 파일을 직접 받지 않고 공개 URL에서 가져간다. `scripts/publish.py --publish <id>`가 게시 동안만 공개 저장소 `bono8055-cpu/insta-photo-hosting`에 사진을 올렸다가 지운다(삭제 후에도 커밋 이력 URL로는 접근 가능 — 어차피 인스타에 공개될 1080px·GPS 제거본만 올라간다).

## 게시 화면 (insta_post 엔진)

PC에서 사진을 골라 인스타 규격으로 맞추고, 캡션을 붙여 게시하는 화면이다. 게시 엔진은 `insta_post.py`, 화면은 `server.py`와 `web/index.html`이다. 설계는 `docs/insta-post-spec.md`, 화면은 `docs/insta-post-screen.md`에 있다.

### 실행

```
python server.py
```

`http://127.0.0.1:8765`가 열리고 브라우저가 뜬다. 브라우저를 띄우지 않으려면 `python server.py --no-browser`를 쓴다. 포트를 바꾸려면 `INSTA_SERVER_PORT` 환경변수를 쓴다. 서버는 `127.0.0.1`에만 열리므로 같은 네트워크의 다른 기기에서는 접근할 수 없다. 끄려면 터미널에서 Ctrl+C를 누른다.

### 게시 흐름

1. **사진 고르기** — 최대 10장. 끌어다 놓아도 된다. 첫 장이 캐러셀 비율 기준이 된다.
2. **비율** — 자동(기본), 4:5, 1:1, 1.91:1 중 하나를 고른다. 자동이면 첫 장 비율을 4:5~1.91:1 범위 안에서 쓴다.
3. **캡션** — 글자 수와 해시태그 수가 표시된다. 한도를 넘으면 게시 버튼이 막힌다.
4. **게시** — 확인창에서 [게시]를 누르면 인스타에 실제로 올라간다. 되돌릴 수 없다.

업로드 전에 사진은 JPEG로 바뀌고, 너비 1440px 이하, 8MB 이하로 맞춰진다. GPS 등 메타데이터는 모두 제거된다.

### .env 설정

프로젝트 루트의 `.env`(커밋 금지)에 필수 키 두 개를 넣는다.

```
INSTAGRAM_ACCESS_TOKEN=...
INSTA_HOSTING_TOKEN=...
```

- `INSTAGRAM_ACCESS_TOKEN` — 인스타 장기 토큰이다. 발급과 갱신은 위 "게시 설정" 절과 같다.
- `INSTA_HOSTING_TOKEN` — GitHub 세분화 토큰이다. 대상 저장소는 이 저장소 하나로 한정하고, 권한은 Contents 읽기·쓰기만 준다.

선택 키는 기본값과 같으면 넣지 않는다.

| 키 | 기본값 | 용도 |
|---|---|---|
| `INSTAGRAM_USER_ID` | 토큰으로 `/me` 조회 | 있으면 조회를 생략한다 |
| `INSTAGRAM_GRAPH_BASE` | `https://graph.instagram.com/v25.0` | Graph API 주소 |
| `INSTA_HOSTING_REPO` | `bono8055-cpu/insta-photo-agents` | 사진을 잠깐 올리는 저장소 |
| `INSTA_HOSTING_BRANCH` | `photo-hosting` | 사진 전용 브랜치 |
| `INSTA_HOSTING_DIR` | `posts` | 브랜치 안의 사진 폴더 |
| `INSTA_MAX_CAPTION` | `2200` | 캡션 글자 수 상한 |
| `INSTA_MAX_HASHTAGS` | `30` | 해시태그 개수 상한 |

- 해시태그 상한은 `5`로 두기를 권장한다. 인스타가 캡션 해시태그를 5개로 제한한다고 밝혔다(`research/growth-playbook.md` 3-1절).
- `server.py`는 `.env`를 읽지 않는다. 엔진(`insta_post.py`)만 `.env`를 읽는다. 화면에 표시되는 글자 수·해시태그 한도는 `server.py` 프로세스의 셸 환경변수에서 읽는다. 그래서 `INSTA_MAX_CAPTION`·`INSTA_MAX_HASHTAGS`는 셸에서 설정한다.

```powershell
$env:INSTA_MAX_HASHTAGS = "5"
python server.py
```

### 사진 전용 브랜치

게시할 사진은 `photo-hosting` 브랜치의 `posts/` 폴더에 한 장씩 올렸다가, 게시가 끝나면 지운다. 인스타는 공개 주소에서 사진을 가져가므로 이 저장소는 공개 상태여야 하고, 브랜치는 미리 만들어져 있어야 한다. 브랜치가 없으면 화면이 "호스팅 브랜치가 저장소에 없다"고 표시한다. 생성 절차는 `docs/publish-checklist.md` 6단계에 있다.

- 지운 사진도 커밋 주소(`https://raw.githubusercontent.com/<저장소>/<커밋 sha>/posts/<파일>`)로는 계속 열린다. 그래서 메타데이터를 미리 전부 제거한다.
- 삭제에 실패한 파일은 결과 로그에 `경고 - 호스팅 삭제 실패, 수동 삭제 필요`로 남는다. 이때는 `posts/` 폴더에서 직접 지운다.

### 검증

```
python selftest.py
```

모의 서버(가짜 GitHub·인스타)를 띄워 엔진을 시험한다. 실계정과 실제 GitHub에는 요청하지 않는다. 마지막 줄이 `N/N 통과`이고 종료 코드가 0이면 통과다.

화면을 모의 서버에 연결해 확인하려면 창을 두 개 쓴다. 첫 번째 창에서 모의 서버를 띄운다.

```
python selftest.py --serve 8766
```

이 창은 Ctrl+C를 누를 때까지 켜 둔다. 출력된 환경변수 줄의 값을 두 번째 PowerShell 창에 넣고 서버를 띄운다. 토큰 두 줄의 `<...>` 자리에는 출력된 값을 그대로 넣는다.

```powershell
$env:INSTAGRAM_ACCESS_TOKEN = "<serve 출력의 INSTAGRAM_ACCESS_TOKEN 값>"
$env:INSTA_HOSTING_TOKEN = "<serve 출력의 INSTA_HOSTING_TOKEN 값>"
$env:INSTAGRAM_GRAPH_BASE = "http://127.0.0.1:8766/ig"
$env:GITHUB_API_BASE = "http://127.0.0.1:8766/gh"
$env:GITHUB_RAW_BASE = "http://127.0.0.1:8766/raw"
$env:INSTA_HOSTING_REPO = "me/hosting"
$env:INSTA_HOSTING_BRANCH = "photo-hosting"
python server.py
```

확인 항목은 `docs/insta-post-screen.md` 6절을 따른다.

### publish.py와의 관계

`scripts/publish.py`는 `IG_USER_ID`·`IG_ACCESS_TOKEN`과 `insta-photo-hosting` 저장소를 쓴다. 새 엔진과 이름과 저장소가 다르므로 두 체계를 함께 쓸 수 있다. 새 엔진으로 실계정 첫 게시가 확인되면 `scripts/publish.py`는 정리할 예정이다.

## 폰에서 쓰기 (Remote Control)
- PC의 Claude 데스크톱 앱 Code 탭에서 이 폴더 세션을 열고 `/remote-control` 입력(항상 켜려면 Settings → Claude Code → Connect new sessions to Remote Control).
- 폰 Claude 앱 → Code → 세션 선택 → 평소처럼 "dry-run 보여줘", "게시해줘".
- 폰에서 첨부한 사진은 PC의 `~/.claude/uploads/`에 파일로 저장된다 → "이 사진들 photos/inbox로 옮겨줘"로 파이프라인에 넣는다.
- 사진·코드·토큰은 모두 PC에 있으므로 용량 제한이 없다. 대신 PC가 켜져 있고 앱이 실행 중이어야 한다(절전 후 깨어나면 자동 재연결).
- 클라우드 세션은 쓰지 않는다: 사진(22GB)이 git에서 제외돼 클라우드로 가지 않고, 기본 네트워크 설정이 Instagram API를 막는다.

## 댓글 자동 답글
- 켜기·끄기·상태: 폰에서 "댓글 답글 켜줘 / 꺼줘 / 상태 보여줘" → `python scripts/comments.py --on | --off | --status`.
- 켜면 Windows 작업 스케줄러가 5분마다 최근 게시물 10개의 **24시간 안** 새 댓글을 보고, 한 번에 최대 5개까지 Claude CLI(Haiku, 구독 사용량)로 짧은 해요체 한 문장 답글을 단다.
- 답하지 않는 댓글(3단계): ① 규칙 필터 — 링크·계정 언급·DM/카톡/텔레그램 유도·협찬/광고/홍보·이벤트/당첨/무료·코인/투자/부업·계좌/송금·금액 ② Claude 판단 — 정치·종교·사건사고·건강·법률, 초상권·저작권, 비판·논쟁, 개인정보 질문, 애매한 것 전부 ③ 답글 필터 — 생성된 답글에 링크·멘션·해시태그·계정명·연락처가 있거나, 길거나, 댓글 문구를 그대로 따라 쓰면 버림.
- 건너뛴 댓글은 `--status`와 `content/comment-log.jsonl`(커밋 안 됨)에 남는다 → 필요하면 직접 답하거나 앱에서 숨긴다. 숨김·삭제는 자동으로 하지 않는다.
- PC가 켜져 있고 로그인돼 있어야 돈다(배터리 상태에서도 동작). 실시간 웹훅은 앱 검수 + 사업자 인증이 필요해 쓰지 않는다.

## 안전 원칙
- 팔로우·좋아요·남의 게시물 댓글 자동화, 비공식 API 사용은 하지 않는다(계정 정지 위험). 자동화는 공식 API의 게시와 내 게시물 댓글 답글만 한다.
- 게시는 approved 폴더 + 채팅 승인 두 단계를 모두 통과해야 한다.
- 토큰은 `.env`에만 두고 커밋하지 않는다.
