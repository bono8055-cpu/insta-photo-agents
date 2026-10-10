# 인스타 게시 기능 — 구현 명세

작성 2026-10-10. 구현 전 정리본이다. 코드는 아직 없다.

## 1. 목표

- 1단계(이 문서 범위): 사진 선택 → 인스타 규격으로 맞춤 → 공개 저장소에 잠깐 올림 → 인스타 게시 → 저장소에서 삭제.
- 최종: 서버 없이 폰에 설치하는 앱. 갤러리 사진에 키스톤·색감 보정을 걸고, 고른 사진을 자동으로 인스타에 게시한다.

## 2. 확정한 결정

| 결정 | 근거 |
|---|---|
| 게시 엔진은 파이썬 파일 하나(표준 라이브러리 + Pillow만) | 안드로이드 앱에 Chaquopy(앱 안에서 파이썬을 돌리는 도구)로 그대로 옮긴다. 키스톤 엔진도 파이썬이다 |
| 사진 호스팅은 `bono8055-cpu/insta-photo-hosting`(공개 저장소) | 인스타 API는 파일을 직접 받지 않고 공개 URL에서 가져간다. 서버 없이 공개 URL을 만드는 방법이다 |
| 인스타에 넘기는 주소는 **커밋 고정 raw URL** `https://raw.githubusercontent.com/<repo>/<커밋sha>/<경로>` | 2026-10-10 실측: 브랜치 주소(`.../main/...`)는 파일을 지우면 404, 커밋 주소는 지운 뒤에도 200·`image/jpeg`. 올린 직후 캐시 문제도 없다 |
| 인스타 API는 "Instagram API with Instagram Login"(`graph.instagram.com`) | 페이스북 페이지 연결이 필요 없다 |
| 업로드용 사진은 메타데이터를 전부 지운다 | 저장소에서 지워도 git 기록에 남아 누구나 열 수 있다. 위치정보(GPS)가 노출되면 안 된다 |

## 3. 인스타 규격

| 항목 | 값 | 확인 상태 |
|---|---|---|
| 비율 | 4:5 ~ 1.91:1 (폰 세로 3:4는 거부됨) | Meta 오류 코드 문서 |
| 형식 | JPEG (MPO·JPS 등 확장 JPEG 불가) | Meta 문서 |
| 용량 | 8MB | 비공식 자료만 확인 |
| 너비 | 최대 1440 (넘으면 인스타가 줄임) | 미확인 |
| 캐러셀 | 최대 10장, 첫 장 비율로 나머지가 잘림 | Meta 문서 |
| 캡션 | 2200자, 해시태그 30개 | 미확인 — 구현 전 확인 |
| 게시 한도 | 24시간 100건 (캐러셀은 1건) | Meta 문서(구버전 문서는 50건) |
| 계정 | 인스타 프로페셔널(비즈니스·크리에이터) | Meta 문서 |
| 토큰 | 장기 토큰 60일, 갱신 필요 | 미확인 |

## 4. 엔진 — `insta_post.py`

입력: stdin으로 JSON 한 줄. 출력: stdout에 `RESULT {json}` 한 줄. (Windows 명령줄은 줄바꿈·따옴표 캡션이 깨질 수 있어 stdin을 쓴다.)

| action | 하는 일 |
|---|---|
| `check` | 환경변수 확인, `GET /me?fields=user_id,username`, GitHub 저장소 접근(`push` 권한·공개 여부) 확인 |
| `prepare` | 원본 → 업로드용 JPEG 생성 (아래 5절) |
| `publish` | 업로드 → 게시 → 삭제 (아래 6절) |

설정은 함수 인자(dict)로 받고, CLI에서만 환경변수로 채운다. 앱으로 옮길 때 토큰을 앱 저장소에서 넘길 수 있게 하기 위해서다.

## 5. prepare 처리 순서

1. EXIF 방향 적용(`ImageOps.exif_transpose`).
2. RGB 변환. PNG 투명 영역은 흰 바탕에 합성.
3. ICC 프로필이 sRGB가 아니면 sRGB로 변환(`ImageCms`, 실패하면 그대로).
4. 비율 결정: `auto`면 첫 장 비율을 4:5~1.91:1 안으로 자른 값. 지정값은 `4:5`·`1:1`·`1.91:1`. 캐러셀은 모든 장을 같은 비율로.
5. 가운데 기준으로 자른다.
6. 너비 1440 넘으면 줄인다.
7. JPEG 품질 90, 메타데이터 없이 저장. 8MB 넘으면 품질을 낮춰 다시 저장.

## 6. publish 처리 순서

1. 검사: 사진 1~10장, 캡션 길이, 같은 작업 중복 게시 금지(게시 완료 표시 파일).
2. 인스타 사용자 id: `INSTAGRAM_USER_ID`가 있으면 사용, 없으면 `/me`의 `user_id`.
3. 사진마다 `PUT /repos/{repo}/contents/{dir}/{이름}` — **순차로** 올린다(동시에 올리면 같은 브랜치 커밋 충돌 409). 응답의 `content.sha`(삭제용)·`commit.sha`(주소용)를 보관. 이름은 매번 새로(`날짜시각-난수-번호.jpg`).
4. raw URL이 200·이미지로 열리는지 확인(최대 30초 재시도).
5. 컨테이너 생성 `POST /{ig}/media`
   - 1장: `image_url`, `caption`
   - 여러 장: 장마다 `image_url`, `is_carousel_item=true` → 묶음 `media_type=CAROUSEL`, `children=<id,id,...>`, `caption`
6. 모든 컨테이너 `GET /{id}?fields=status_code`가 `FINISHED`일 때까지 대기(2초 간격, 최대 60초). `ERROR`·`EXPIRED`면 중단.
7. `POST /{ig}/media_publish` `creation_id=<컨테이너 id>` → 게시물 id.
8. `GET /{게시물 id}?fields=permalink`로 링크 조회(실패해도 게시는 성공 처리).
9. **finally**: 올린 파일을 `DELETE /repos/{repo}/contents/{경로}`(sha 필요)로 삭제. 게시가 실패해도 삭제한다. 삭제 실패는 경고로만 남긴다.

- 토큰은 POST 본문(form)으로 보낸다. 오류 메시지에 URL 쿼리를 넣지 않는다(토큰 노출 방지).
- 결과에 단계 기록(`log`)을 넣어 화면에 보여 준다.

## 7. 환경변수

| 이름 | 필수 | 기본값 |
|---|---|---|
| `INSTAGRAM_ACCESS_TOKEN` | O | — |
| `INSTAGRAM_USER_ID` | | `/me`로 조회 |
| `INSTAGRAM_GRAPH_BASE` | | `https://graph.instagram.com/v26.0` (버전 미확인 — 발급 화면의 버전으로 맞춘다) |
| `INSTA_HOSTING_TOKEN` | O | — (GitHub 세분화 토큰, 이 저장소 Contents 읽기·쓰기만) |
| `INSTA_HOSTING_REPO` | | `bono8055-cpu/insta-photo-hosting` |
| `INSTA_HOSTING_BRANCH` | | `main` |
| `INSTA_HOSTING_DIR` | | `posts` |
| `GITHUB_API_BASE` / `GITHUB_RAW_BASE` | | `https://api.github.com` / `https://raw.githubusercontent.com` (모의 서버 시험용) |

토큰은 코드·저장소에 넣지 않는다. 이 저장소는 공개다.

## 8. 화면 (PC 1단계)

- 사진 고르기(최대 10장), 순서 바꾸기(← →), 빼기(×). 첫 장이 캐러셀 비율 기준이다.
- 비율: 자동 / 4:5 / 1:1 / 1.91:1 → 바꾸면 prepare 다시 실행, 잘린 미리보기 표시.
- 캡션 입력 + 글자 수·해시태그 수 표시.
- 상단: 연결 상태(인스타 `@계정`, 호스팅 저장소 쓰기 가능 여부).
- 게시 버튼 → 확인창("실제로 인스타에 올라간다") → 결과 링크. 게시 중에는 버튼을 막는다.

## 9. 검증

- `selftest.py`: 로컬 모의 서버 하나가 GitHub(contents 올리기·삭제, raw 제공)와 인스타(컨테이너·상태·게시)를 흉내 낸다. 모의 인스타는 실제로 `image_url`을 내려받아 JPEG·비율·용량을 검사한다.
  - 1장 게시, 캐러셀 게시, 인스타 오류 시에도 호스팅 파일이 지워지는지, 3:4·9:16·2:1 사진의 비율 처리, GPS 포함 사진의 메타데이터 제거.
- 실계정 시험: 모의 시험 통과 후 1장 → 캐러셀 순서로 한 번씩.

## 10. 사용자 준비물

1. 인스타 계정을 프로페셔널(비즈니스 또는 크리에이터)로 전환.
2. Meta 개발자 앱 생성 → Instagram Login으로 장기 토큰 발급(권한 `instagram_business_basic`, `instagram_business_content_publish`).
3. GitHub 세분화 토큰 발급 — 저장소 `insta-photo-hosting`만, Contents 읽기·쓰기.

## 11. 이후 단계 (폰 앱)

- 키스톤: edif_editor `modules/keystone/engine/keystone.py`(numpy·OpenCV·Pillow)를 그대로 옮긴다. Chaquopy의 OpenCV에 LSD(직선 검출기)가 있는지 먼저 확인 — 없으면 정확도가 낮은 Canny+Hough로 넘어간다. 폰에서 `selftest.py`가 "통과"인지로 판정.
- 색감: edif_editor `modules/tone-match/lib/`의 변환·자동값(흰 표면 기준) 함수를 파이썬으로 옮긴다. 자동 선택(HQ-SAM·OWLv2, GPU 필요)은 폰에서 못 돌려 뺀다.
- 앱: 안드로이드 + Chaquopy, APK 직접 설치. 아이폰은 엔진 재작성·Mac·연 $99가 필요해 범위 밖.

## 12. 주의

- 저장소에서 지워도 git 기록에 사진이 남는다. 장당 약 1MB씩 쌓이므로 GitHub 권장 한도(1GB)에 가까워지면 저장소를 새로 만든다.
- 사진은 순차로 올리고 지운다. 캐러셀 10장이면 커밋 20개가 생긴다.
