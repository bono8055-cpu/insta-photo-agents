# PLAN — 감성 사진 인스타 자동화 에이전트 팀

목표: 로컬 폴더의 내 사진을 분류·기획·캡션 작성해 Graph API로 예약 게시하고, 성과를 분석해 다음 기획에 반영한다.
사람 승인 지점: 캡션 초안을 `content/drafts` → `content/approved`로 옮기는 것, 실제 게시 실행 직전 채팅 승인.

## 체크리스트
- [x] 프로젝트 골격·에이전트 6종 정의 (.claude/agents)
- [x] 감성 레퍼런스 계정 리서치 → research/reference-accounts.md — 18개 계정, 방향 후보 A~D
- [x] 노출·팔로우 성장 전략 리서치 → research/growth-playbook.md — 해시태그 5개 제한·API 4:5 비율 제약을 caption-writer/publisher에 반영
- [x] 브랜드 보이스 가이드 → brand/voice.md — 방향 A(따뜻한 필름) 톤 + C(도시 산책) 피사체·캐러셀
- [x] 사진 분류 파이프라인: EXIF/GPS 추출 스크립트 + manifest 병합 (scripts/scan_photos.py) — 픽스처 4종(GPS jpg/png/heic/손상)·병합 보존·깨진 manifest 중단 검증
- [x] API 규격 내보내기 스크립트 (scripts/export_photos.py) — 회전·GPS 제거·sRGB·CMYK·비율 경계 1px 반올림까지 픽스처 검증
- [x] 첫 사진 배치로 분류 실행 — GR WORLD 최신일(2026-07-25) 78장 중 8장 선별(을지로 산책 캐러셀 초안), 스캔 하위폴더 지원·밀착 인화지 스크립트 추가
- [x] 회전·키스톤 자동 보정 + 검수 게이트 (correct_photos / review_corrections / export 게이트) — 합성 5종 부호·잔여 검증, 실사진 오검출(8764) 잔차로 차단 확인
- [x] 보정본 검수 — R0008752·R0008790 사용자 승인, export 8장(4:5·GPS 제거) 생성, 승인분이 보정본에서 나온 것 확인
- [x] 두 번째 배치(뮤지엄산 9장) — 8장 캐러셀 선별, 자동 보정 전부 제외(의도된 원근·조각 윤곽) 육안 확인, 검수 완료분 재처리 방지 수정, export 16장
- [x] 시리즈별 톤 프리셋 (grade_photos: warm-film / calm-neutral) + 톤 검수 게이트(review --stage grade, export 우선순위 graded>corrected>selected) — 합성 회색·재현성·float32 검증, 두 시리즈 16장 적용
- [x] 톤 검수 — 을지로 8장 승인, 뮤지엄산 7장 승인·09 거절(청록 원본 유지), export 16장 소스 경로 픽셀 대조 확인
- [x] 주간 기획 → content/calendar-2026-09-28.md + drafts 2개(9/29 화 19:00 을지로, 10/1 목 08:00 뮤지엄산)
- [x] 캡션·해시태그 작성 — 후보 3개씩, 을지로는 한영 병기(외국인 타깃), 해시태그 5개, 규격 검증 통과
- [x] 을지로 → 종로 시리즈 교체(사용자 제공 9장, 표지 토마토, 한영 캡션·#종로 #jongno), 06 보정 승인·톤 전부 거절(사용자 보정 유지), export 25장
- [ ] 초안 검토 → content/approved 이동 (정지: 사용자가 직접 파일 이동)
- [x] Graph API 게시 스크립트 (scripts/publish.py, --dry-run 기본) — 인자 없으면 dry-run, `--publish <id>`로 실제 게시. GitHub 공개 저장소 임시 호스팅(합성 이미지로 업로드→Meta UA 200 image/jpeg→삭제 실검증), test_publish.py로 캐러셀 순서·실패 시 정리·중복 방지 기록 검증
- [x] 폰 운영 방식 — Remote Control 채택(사진 22GB·토큰이 PC에 남음, 클라우드는 git 제외 사진 미전달·Instagram 도메인 기본 차단), README "폰에서 쓰기"
- [x] Meta 앱·비즈니스 계정·토큰 설정 가이드 → README "게시 설정" (정지: 계정 전환·토큰 발급·.env 작성은 사용자가 직접)
- [x] 댓글 자동 답글 (scripts/comments.py, --on/--off/--status) — 5분 주기 작업 스케줄러 + Claude CLI(Haiku), 사기·민감 댓글 3단계 차단. 보안 리뷰 에이전트 2회(P1 2·P2 10건 반영). test_comments.py 통과, 실제 CLI로 민감·사기·주입 8건 SKIP·일반 3건 답글 확인, 작업 등록→강제 실행→제거 확인 (정지: 켜기는 사용자가 직접)
- [ ] 첫 게시 dry-run → 승인 후 실제 게시 (정지: 외부 발송) — 2026-10-05 막힘: Meta 개발자 등록 Contact info 단계에서 모든 이메일 거부. 다음: 계정 센터에서 두 번째 개인 이메일을 Facebook 계정에만 추가·인증 → 개발자 등록 재시도 → 앱(Business)·토큰(사진 계정으로 로그인)·.env → 뮤지엄산 게시
- [ ] 인사이트 수집·주간 리포트 (scripts/insights.py)
- [x] 게시 엔진 insta_post.py + selftest.py (docs/insta-post-spec.md 4~6·9절, 표준 라이브러리 + Pillow) — 리뷰 P1 3·P2 8 반영, selftest 23/23, 결함 주입 3종 검출 확인
- [x] 게시 화면 server.py + web/index.html (docs/insta-post-screen.md 0~4절) — 모의 서버로 6절 검증: 1장·3장 캐러셀 링크, 순서 변경 시 비율 재계산, 토큰 없음 빨강·버튼 막힘, 4회 클릭에 게시 1회
- [x] 저장소 공개 (docs/publish-checklist.md) — 2026-10-10 github.com/bono8055-cpu/insta-photo-agents 공개, main 단일 커밋(noreply 작성자), photo-hosting 브랜치 생성, 실제 업로드→raw 200 image/jpeg→삭제 확인. 과거 기록은 로컬 private-history-backup(push 금지). insta-photo-hosting은 사용자가 삭제
- [ ] scripts/publish.py는 삭제된 insta-photo-hosting을 기본값으로 가리킨다 — 실계정 첫 게시 후 위 정리 항목에서 함께 삭제
- [ ] 새 엔진 실계정 첫 게시(1장 → 캐러셀) 후 정리: comments.py·publisher 에이전트를 insta_post로 옮기고 scripts/publish.py·test_publish.py 삭제 (정지: 삭제 전 사용자 확인)
