<!-- 저장소를 개인정보 없이 GitHub 공개 저장소로 전환하는 단계별 절차 (실행 계획이며 승인 없이 실행하지 않는다) -->

# 공개 저장소 전환 체크리스트

이 문서는 `insta-photo-agents` 저장소를 GitHub 공개 저장소로 전환하는 절차다. 방식은 **(C) 새 단일 커밋으로 공개**다. 기존 `master`의 기록은 올리지 않는다. 기록이 없는 새 `main` 커밋 하나로 시작한다.

## 실행 주체 표기

- **[사용자]** GitHub 웹 설정 화면에서 직접 한다. Claude가 대신 할 수 없다.
- **[Claude 승인 후]** 사용자가 채팅으로 명시 승인한 뒤 Claude가 실행한다. 승인은 단계마다 따로 받는다.
- **되돌림 "불가"** 표시는 공개 노출이나 삭제처럼 원상복구가 안 되는 단계다.

| 단계 | 내용 | 실행 주체 | 되돌림 |
|---|---|---|---|
| 0 | 감사 결과 확인 | 사용자 확인 | — |
| 1 | 작업 트리의 개인 정보 일반화 | [Claude 승인 후] | 가능 |
| 2 | GitHub 이메일 보호 설정 | [사용자] | 가능 |
| 3 | 이 저장소만 noreply 이메일로 설정 | [Claude 승인 후] | 가능 |
| 4 | 공개 전 최종 점검 | Claude 실행, 결과는 사용자 확인 | 읽기 전용 |
| 5 | 단일 커밋 `main` 생성과 공개 push | [사용자] 저장소 생성, [Claude 승인 후] 커밋과 push | 불가 |
| 6 | 사진 전용 브랜치 `photo-hosting` 생성 | [Claude 승인 후] | 불가 |
| 7 | 로컬 백업과 작업 이어가기 | [Claude 승인 후] | 가능 |
| 8 | 기존 `insta-photo-hosting` 저장소 삭제 | [사용자] | 불가 |

## 0. 감사 결과

| 위치 | 발견 내용 |
|---|---|
| 모든 기존 커밋의 작성자 이메일 | 개인 Gmail 주소 |
| `context-notes.md` 18행 부근 | 개인 이메일로 가입한 사실, Facebook 계정 설명 |
| `PLAN.md` 27행 부근 | 두 번째 개인 이메일 설명, Facebook 계정 설명, 반려동물 계정 이름 |
| `.gitignore` | `.env`, `photos/**`, `content/comment-log.jsonl`, `.insta_post_state/`, `work/`, `**/.omc/`, `.claude/settings.local.json`이 이미 제외된다 |

- 작업 트리 기준으로 이메일 주소 문자열은 남아 있지 않다. 그래도 개인 정보를 가리키는 문장이 남아 있으므로 1단계에서 일반화한다.
- `PLAN.md`와 `context-notes.md`는 다른 세션이 편집 중이다. 1단계는 그 세션이 끝나 파일이 안정된 뒤에만 실행한다.
- 공개 전환 후에도 과거 커밋이 살아 있으면 작성자 이메일이 노출된다. 그래서 과거 기록은 올리지 않고 5단계에서 새 커밋으로 끊는다.

## 1단계 — 작업 트리의 개인 정보 일반화 [Claude 승인 후]

영향 범위: 개인 정보를 가리키는 문장만 바꾼다. 다른 줄, 서식, 체크 상태(`- [x]`)는 건드리지 않는다. 이 단계는 `PLAN.md`와 `context-notes.md`를 포함해 저장소 안의 모든 추적 대상 파일에 적용한다.

먼저 개인 식별 단어 목록을 `.git` 안에 만든다. `.git` 안의 파일은 커밋되지 않으므로 목록 자체가 공개되지 않는다. 한 줄에 단어 하나씩 적는다. 목록에는 본인 이름, 페이스북 표시 이름, 반려동물 계정 이름, 개인 이메일 주소 같은 단어를 넣는다.

```bash
TERMS="$(git rev-parse --git-dir)/private-terms.txt"
touch "$TERMS"
# 사용자가 $TERMS 파일에 단어를 한 줄씩 적는다. 비어 있으면 4단계 검사가 아무것도 잡지 못한다.
```

단어가 들어 있는 줄을 찾는다. 출력은 파일명과 줄 번호만 보여 준다.

```bash
grep -nIF -f "$TERMS" PLAN.md context-notes.md
```

바꿀 표현 예시는 다음과 같다. 원래 문장을 그대로 두지 않고 역할만 남긴다.

| 원래 내용 | 바꿀 표현 |
|---|---|
| 개인 이메일 주소 또는 개인 이메일 설명 | `(연락처 생략)` |
| Facebook 계정 또는 표시 이름 | `개발자 계정` |
| 반려동물 계정 이름 | `별도 계정(비공개)` |

- 같은 정보가 다른 파일에 있으면 4단계 검사에서 잡힌다. 4단계를 통과하기 전에는 1단계를 끝난 것으로 보지 않는다.
- 일반화 후 `PLAN.md`의 체크리스트 의미가 바뀌지 않는지 확인한다.

## 2단계 — GitHub 이메일 보호 설정 [사용자]

1. https://github.com/settings/emails 에 들어간다.
2. **Keep my email addresses private** 를 켠다.
3. **Block command line pushes that expose my email** 를 켠다. 개인 이메일이 든 커밋을 push할 때 GitHub가 거부한다.
4. 같은 화면에서 noreply 주소를 확인한다. 형식은 `<숫자 id>+<GitHub 사용자명>@users.noreply.github.com`이다. 3단계에서 쓴다.
5. https://github.com/settings/profile 에서 공개 프로필의 Public email이 개인 메일이면 비운다.

영향: 이후 push 차단과 주소 숨김이 적용된다. 과거 커밋은 바뀌지 않는다.

## 3단계 — 이 저장소만 noreply 이메일로 설정 [Claude 승인 후]

2단계에서 확인한 값을 넣는다. `--local`을 붙여 이 저장소에만 적용한다. 전역 설정은 건드리지 않는다.

```bash
git config --local user.name "<GitHub 사용자명>"
git config --local user.email "<숫자 id>+<GitHub 사용자명>@users.noreply.github.com"
git config --local --list | grep "^user\."
```

- 영향: 이 저장소에서 이후 만드는 커밋의 작성자가 바뀐다. 다른 저장소와 전역 설정에는 영향이 없다.
- 가정: 2단계의 noreply 주소가 맞다. 틀리면 push가 2단계의 차단 설정에 걸린다.

## 4단계 — 공개 전 최종 점검 [Claude 실행, 결과는 사용자 확인]

공개될 파일 목록을 만든다. 추적 파일과 무시되지 않은 새 파일을 모두 포함한다.

```bash
LIST="$(git rev-parse --git-dir)/publish-list.txt"
SCAN="$(git rev-parse --git-dir)/publish-scan.txt"
git ls-files -co --exclude-standard > "$LIST"
grep -v '^docs/publish-checklist\.md$' "$LIST" > "$SCAN"
wc -l < "$LIST"
```

점검 명령은 모두 파일 이름만 출력한다. 출력이 나오면 그 파일을 고친 뒤 4단계를 처음부터 다시 한다.

```bash
# 이메일 주소 — noreply 주소가 든 파일은 줄 단위로 따로 확인한다
xargs -a "$SCAN" -d '\n' grep -lIE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'

# 개인 식별 단어 — 1단계 목록
xargs -a "$SCAN" -d '\n' grep -lIF -f "$TERMS"

# API 토큰 형태 — 테스트 파일의 가짜 값(IGTEST-, GHTEST-)만 예외다
xargs -a "$SCAN" -d '\n' grep -lIE '(IG[A-Z]{1,2}|EAA|github_pat_|gh[pousr]_)[A-Za-z0-9_-]{20,}'

# 토큰 대입 — 실제 값이 들어간 줄
xargs -a "$SCAN" -d '\n' grep -lIE '(TOKEN|ACCESS_TOKEN|USER_ID)[ ]*=[ ]*[A-Za-z0-9_-]{16,}'

# 개인 경로 — Windows 사용자 폴더
xargs -a "$SCAN" -d '\n' grep -lIE '[A-Za-z]:[\\/]Users[\\/]'

# 금지 파일 — photos/ 안의 .gitkeep만 허용
grep -E '^(\.env$|work/|\.insta_post_state/|content/comment-log\.jsonl$|\.claude/settings\.local\.json$|.*\.omc/|photos/)' "$SCAN" | grep -v 'photos/.*\.gitkeep$'
```

- 판정: 여섯 명령의 출력이 모두 비어야 한다. 이메일 명령이 `PLAN.md`를 내면 1단계가 덜 끝난 것이다.
- `1단계`의 `$TERMS` 파일이 비어 있으면 두 번째 명령은 아무것도 잡지 못한다. 목록이 채워졌는지 먼저 확인한다.
- 검사 목록의 파일을 사람이 한 번 훑는다. 특히 `.claude/`와 `content/`의 설명 문장을 본다.
- 4단계 결과를 사용자가 확인하기 전에는 5단계로 넘어가지 않는다.

## 5단계 — 단일 커밋 `main` 만들기와 공개 push [사용자 + Claude 승인 후]

### 5-1. 원격 상태 확인 [Claude 실행]

```bash
git remote -v
git branch --list main
git log --oneline -1 origin/master 2>/dev/null
```

- 원격이 없으면 **A 경우**다.
- 두 번째 명령이 `main`을 출력하면 로컬에 `main`이 이미 있다. 5-3에서 먼저 이름을 바꾼다.
- 세 번째 명령이 커밋을 출력하면 과거 기록이 이미 올라가 있다. **B 경우**다.

B 경우의 영향: force push로 덮어써도 과거 커밋이 GitHub 서버에 한동안 남고 커밋 주소로 열릴 수 있다. 그래서 원격 저장소를 삭제하고 같은 이름으로 새로 만드는 쪽이 안전하다. 삭제는 되돌릴 수 없으므로 사용자가 직접 결정하고 직접 한다.

### 5-2. 공개 저장소 만들기 [사용자]

1. https://github.com/new 에서 이름을 `insta-photo-agents`, 공개(Public)로 정한다. 이름이 같으면 `INSTA_HOSTING_REPO` 기본값과 맞는다.
2. "Add a README", ".gitignore", "license" 옵션을 모두 끈다. 빈 저장소여야 한다.
3. 생성된 주소를 Claude에 알린다.

B 경우에는 기존 저장소를 먼저 삭제한 뒤 같은 이름으로 만든다.

### 5-3. 로컬에서 단일 커밋 만들기 [Claude 승인 후]

```bash
git branch -m master private-history-backup
git branch --list main
```

- 두 번째 명령이 `main`을 출력하면 `git branch -m main private-main-old`로 먼저 옮긴다.

```bash
git checkout --orphan main
git rm -r -q --cached .
```

- `git rm --cached`는 스테이징 목록만 비운다. 작업 트리의 파일은 그대로 남는다.
- 파일 목록을 다시 만들어 사용자가 확인한다. 4단계의 `$LIST`와 같아야 한다.

```bash
git ls-files -co --exclude-standard > "$LIST"
cat "$LIST"
```

사용자가 목록을 승인하면 그 파일만 명시해서 추가한다. `git add .`는 쓰지 않는다.

```bash
xargs -a "$LIST" -d '\n' git add --
git status --short
git commit -m "공개 저장소 초기 커밋"
git log --format="%an <%ae>"
```

- `git log` 결과의 작성자 이메일이 noreply 주소여야 한다.

### 5-4. push [Claude 승인 후]

```bash
git remote add origin https://github.com/<GitHub 사용자명>/insta-photo-agents.git
git push -u origin main
```

- `git remote add`는 원격이 없을 때만 한다. 원격이 있으면 그대로 쓴다.
- 금지: `git push --all`, `git push --mirror`. 둘 다 로컬 백업 브랜치를 올린다.
- 금지: `git push --force`. push가 거부되면 원인(2단계 차단 설정, 이메일)을 먼저 확인한다.
- 영향: 공개 노출이다. 올라간 뒤에는 되돌릴 수 없다.

## 6단계 — 사진 전용 브랜치 `photo-hosting` 만들기 [Claude 승인 후]

이유: `INSTA_HOSTING_BRANCH` 기본값이 `photo-hosting`이다. GitHub Contents API로 사진을 올리려면 이 브랜치가 있어야 한다.

작업 트리를 건드리지 않도록 별도 worktree에서 만든다. `git worktree add --orphan`은 git 2.42 이상이 필요하다. `git --version`으로 먼저 확인한다.

```bash
git worktree add --orphan -b photo-hosting ../insta-photo-hosting-init
cd ../insta-photo-hosting-init
git commit --allow-empty -m "사진 호스팅 브랜치 초기화"
mkdir -p posts && touch posts/.gitkeep
git add -- posts/.gitkeep
git commit -m "posts 폴더 추가"
git push -u origin photo-hosting
cd C:/Users/Lim/workspace/insta-photo-agents
git worktree remove ../insta-photo-hosting-init
```

- 영향: `photo-hosting` 브랜치는 공개된다. 게시 중에만 사진이 잠깐 공개 주소에 놓이고, 게시가 끝나면 지워진다. 이 동작은 설계에 따른 것이다.
- 주의: 메인 작업 트리에서 `git checkout photo-hosting`을 하지 않는다. 추적되지 않는 파일이 충돌해 checkout이 실패한다.

## 7단계 — 로컬 백업과 작업 이어가기 [Claude 승인 후]

- 과거 기록은 로컬 브랜치 `private-history-backup`에 남는다(5-3). 이 브랜치는 push하지 않는다.
- 로컬 `.git` 안에 과거 기록이 그대로 있다. 이 폴더를 압축하거나 복사해 밖으로 내보내면 백업도 함께 나간다. 내보내지 않는다.
- 이후 작업은 `main`에서 한다. 커밋 전에 `git config --local --list`로 3단계 설정이 유지되는지 확인한다.
- 백업을 완전히 지울지는 사용자가 결정한다. 되돌릴 수 없다.

```bash
git branch -D private-history-backup
git reflog expire --expire=now --all
git gc --prune=now
```

## 8단계 — 기존 `insta-photo-hosting` 저장소 삭제 [사용자, 실계정 게시 성공 후]

전제 조건을 모두 충족해야 한다.

- 새 저장소에서 `python selftest.py`가 `N/N 통과`이고 종료 코드가 0이다.
- 실계정 1장 게시가 성공했다(`docs/insta-post-spec.md` 9절).
- 실계정 캐러셀 게시가 성공했다.
- `scripts/publish.py`가 더 이상 필요 없다. 이 스크립트는 `insta-photo-hosting`을 쓴다. 정리 전에 지우면 그 경로가 깨진다.

절차: GitHub에서 `insta-photo-hosting` → Settings → Danger Zone → Delete this repository. 저장소 이름을 입력해 확인한다.

영향: 저장소와 그 안의 과거 사진 커밋이 사라진다. 되돌릴 수 없다.

## 실패 시 대응

- 4단계 점검에서 출력이 나오면 5단계로 넘어가지 않는다. 해당 파일을 1단계로 고친 뒤 4단계를 처음부터 다시 한다.
- push가 거부되면 `--force`로 밀어 넣지 않는다. 원인을 확인하고 사용자에게 보고한다.
- 6단계에서 worktree 생성이 실패하면 git 버전을 확인한다. 2.42 미만이면 사용자에게 업그레이드를 요청한다.

## 완료 확인

- 공개 저장소 `main`에 커밋이 1개다.
- 공개 저장소에 `photo-hosting` 브랜치가 있다.
- 커밋 작성자가 noreply 주소다.
- `python server.py`를 띄우면 연결 상태가 정상이다. 공개 여부, push 권한, 호스팅 브랜치가 모두 확인된다.
