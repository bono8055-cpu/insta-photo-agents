# publish.py의 게시 흐름(호스팅 정리·중복 방지 기록)을 네트워크 없이 검증하는 자체 점검 스크립트
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publish as P

sys.stdout.reconfigure(encoding="utf-8")
PKG ={"id": "t1", "format": "carousel", "photos": ["photos/export/a.jpg", "photos/export/b.jpg"],
       "caption": "종로", "hashtags": ["#종로"]}


def run(fail_on=None, public_ok=True):
    calls, deleted = [], []

    def fake_api(method, path, **params):
        calls.append((method, path, params))
        if fail_on and path.endswith(fail_on):
            raise RuntimeError("boom")
        if method == "GET" and params.get("fields", "").startswith("status_code"):
            return {"status_code": "FINISHED"}
        if method == "GET":
            return {"permalink": "https://instagram.com/p/x"}
        return {"id": f"id{len(calls)}"}

    P.api = fake_api
    P.github_headers = lambda: {}
    P.host_upload = lambda path, name, gh: (f"https://raw/{name}", f"sha-{name}")
    def fake_check(url):
        if not public_ok:
            raise RuntimeError("not public")

    P.check_public = fake_check
    P.host_delete = lambda name, sha, gh: deleted.append(name)
    os.environ["IG_USER_ID"] = "123"
    f = Path(tempfile.mkdtemp()) / "t1.json"
    pkg = json.loads(json.dumps(PKG))
    P.save(f, pkg)
    try:
        P.publish(f, pkg)
    except RuntimeError:
        pass
    return calls, deleted, json.loads(f.read_text(encoding="utf-8"))


calls, deleted, saved = run()
posts = [c for c in calls if c[0] == "POST"]
assert [p[2].get("is_carousel_item") for p in posts[:2]] == [True, True]
assert posts[2][2]["media_type"] == "CAROUSEL" and posts[2][2]["children"].count(",") == 1
assert posts[2][2]["caption"] == "종로\n\n#종로"
assert posts[3][1] == "123/media_publish"
assert saved["media_id"] and saved["permalink"] and saved["status"] == "published"
assert len(deleted) == 2, "게시 후 공개 저장소 파일 삭제"

calls, deleted, saved = run(fail_on="123/media_publish")
assert "media_id" not in saved, "게시 실패 시 기록 없음"
assert len(deleted) == 2, "실패해도 공개 저장소 파일 삭제"

calls, deleted, saved = run(public_ok=False)
assert deleted and not calls, "공개 확인 실패 시 올린 파일 삭제, Graph API 호출 없음"

errors = P.validate({**PKG, "photos": ["photos/export/nope.jpg"], "format": "single",
                     "hashtags": [f"#t{i}" for i in range(6)]})
assert any("파일 없음" in e for e in errors) and any("해시태그 6개" in e for e in errors)
print("OK")
