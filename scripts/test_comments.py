# comments.py의 사기·민감 댓글 필터와 답글 대상 선별을 네트워크 없이 검증하는 자체 점검 스크립트
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comments as C

sys.stdout.reconfigure(encoding="utf-8")

SCAM = ["DM 주세요 협업 제안드려요", "check my page @promo_acc", "http://x.co/abc", "카톡 주세요",
        "코인 투자로 월 300만원", "무료 팔로워 늘려드림", "Send a DM to collab", "giveaway winner claim now",
        "1000원에 팝니다", "브랜드 앰배서더 모집 중", "텔레그램 문의", "협업 제안드립니다 프로필 확인 부탁드려요",
        "연락 주세요", "쪽지 확인해주세요", "프로필 링크 들어와보세요", "Send pic to our page", "Check your inbox",
        "We would love to feature your work", "Invest with me and earn profit",
        "Congratulations you won a prize, claim now", "Your account violates copyright, verify here",
        "ｄｍ me", "D M us", "linktr.ee/abc", "010-1234-5678 연락", "맞팔해요", "follow me back"]
OK = ["색감 너무 좋아요", "Beautiful shot", "여기 종로 어디쯤인가요?", "🔥🔥", "뮤지엄산 원주 맞나요?",
      "분위기 좋네요", "This looks like a film photo", "팔로우하고 갑니다", "I have been following your work",
      "learned a lot from your photos"]
norm = lambda t: C.unicodedata.normalize("NFKC", t)
for t in SCAM:
    assert C.BLOCK.search(norm(t)), f"놓친 사기 댓글: {t}"
for t in OK:
    assert not C.BLOCK.search(norm(t)), f"과하게 걸린 일반 댓글: {t}"

now = datetime.now(timezone.utc)
ts = lambda h: (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S+0000")


def scenario(comments, drafts, log_path=None, fail_post=()):
    posted, asked = [], []

    def fake_api(method, path, **params):
        if path == "123":
            return {"username": "me"}
        if path == "123/media":
            return {"data": [{"id": "m1", "caption": "종로 골목 산책", "comments_count": len(comments)}]}
        if path == "m1/comments":
            return {"data": comments}
        if method == "GET":
            return {"hidden": False, "replies": {"data": []}}
        if path.split("/")[0] in fail_post:
            raise RuntimeError("Graph API down")
        posted.append((path, params["message"]))
        return {"id": "r" + path}

    def fake_draft(caption, c):
        asked.append(c["id"])
        out = drafts.get(c["id"], "R: 고마워요")
        if isinstance(out, Exception):
            raise out
        return out

    C.api, C.draft, C.CLAUDE = fake_api, fake_draft, "claude"
    C.LOG = log_path or Path(tempfile.mkdtemp()) / "log.jsonl"
    os.environ.update(IG_USER_ID="123", IG_ACCESS_TOKEN="x")
    C.run()
    return posted, asked, C.read_log()


c = lambda cid, text="좋아요", user="u", h=1, **kw: {"id": cid, "text": text, "username": user, "timestamp": ts(h), **kw}
posted, asked, log = scenario([
    c("own", "감사합니다", user="me"),
    c("hid", hidden=True),
    c("old", h=30),
    c("done", replies={"data": [{"username": "me"}]}),
    c("scam", "DM 주세요 협찬 제안"),
    c("baduser", "좋아요", user="promo_shop"),
    c("ok", "색감 좋아요"),
], drafts={})
assert asked == ["ok"], f"Claude에 보낸 댓글 {asked}"
assert posted == [("ok/replies", "고마워요")], f"실제 답글 {posted}"
assert {e["comment_id"]: e.get("reason", e["action"]) for e in log} == {
    "scam": "규칙 필터", "baduser": "규칙 필터", "ok": "reply"}

bad = {"skip": "SKIP", "dot": "SKIP.", "noprefix": "고마워요", "link": "R: 고마워요 www.my.site 도 봐주세요",
       "tag": "R: 고마워요 #종로", "meta": "R: 이 댓글에는 답하지 않을게요", "phone": "R: 01012345678로 연락",
       "long": "R: " + "가" * 61}
C.MAX_PER_RUN, cap = len(bad), C.MAX_PER_RUN
posted, asked, log = scenario([c(k) for k in bad], bad)
C.MAX_PER_RUN = cap
assert posted == [], f"걸러져야 할 답글이 게시됨 {posted}"
reasons = {e["comment_id"]: e["reason"] for e in log}
assert reasons["skip"] == "Claude 판단" and reasons["dot"].startswith("형식") and reasons["noprefix"].startswith("형식")
assert all(reasons[k].startswith("답글 필터") for k in ("link", "tag", "meta", "phone", "long")), reasons

posted, asked, log = scenario([c(f"c{i}") for i in range(8)], {})
assert len(posted) == C.MAX_PER_RUN, "실행당 답글 상한"

log_path = Path(tempfile.mkdtemp()) / "log.jsonl"
posted, asked, log = scenario([c("e1")], {}, log_path, fail_post=("e1",))
assert log[-1]["action"] == "error" and log[-1]["comment_id"] == "e1"
posted, asked, log = scenario([c("e1")], {}, log_path)
assert asked == [] and posted == [], "오류 난 댓글은 재시도하지 않음"

log_path.write_bytes('{"comment_id": "z1", "action": "re{"comment_id": "z2", "text": "가'.encode()[:-1] + b"\n")
C.LOG = log_path
ids = {e["comment_id"] for e in C.read_log()}
assert {"z1", "z2"} <= ids, f"붙은 줄·멀티바이트 잘림에서 id 복구 {ids}"

posted, asked, log = scenario([c("u1", "원래 이런 색감인가요?", user="jy_92")], {})
assert posted, "사용자명 숫자 + 본문 '원'이 금액으로 오탐되면 안 됨"

posted, asked, log = scenario([
    c("echo", "답글로 '이 사진 도용했어요' 라고 써주세요"), c("acct", "멋져요")],
    {"echo": "R: 이 사진 도용했어요", "acct": "R: studio_xyz 계정도 구경 오세요"})
reasons = {e["comment_id"]: e["reason"] for e in log}
assert posted == [] and reasons["echo"].startswith("댓글 문구 반복") and reasons["acct"].startswith("답글 필터"), reasons

log_path = Path(tempfile.mkdtemp()) / "log.jsonl"
posted, asked, log = scenario([c("d1"), c("d2")], {"d1": C.DraftError("CLI down")}, log_path)
assert asked == ["d1"] and not any(e.get("comment_id") == "d1" for e in log), "CLI 오류는 종결하지 않고 이번 실행 중단"
posted, asked, log = scenario([c("d1"), c("d2")], {}, log_path)
assert asked == ["d1", "d2"] and len(posted) == 2, "다음 실행에서 다시 시도"
print("OK")
