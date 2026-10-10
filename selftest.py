# insta_post.py를 로컬 모의 서버(GitHub contents·raw + 인스타 Graph)로 시험하는 자체 점검 스크립트 — 명세 9절 (--serve: 화면 검증용 모의 서버만 띄움)
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image, ImageCms

import insta_post as E

IG_TOKEN = "IGTEST-secret-token-123"
GH_TOKEN = "GHTEST-secret-token-456"
IG_ID = "17841400000000000"
BRANCH = "photo-hosting"


class Mock:
    def __init__(self):
        self.reset()

    def reset(self):
        self.files = {}        # path -> (content_sha, bytes) 브랜치에 현재 있는 파일
        self.commits = {}      # (commit_sha, path) -> bytes 커밋 고정 주소는 삭제 후에도 남는다
        self.containers = {}
        self.published = []
        self.flags = {}
        self.uploads = 0
        self.in_flight = 0
        self.conflicts = 0
        self.seq = getattr(self, "seq", 0)
        self.lock = threading.Lock()

    def next_id(self):
        with self.lock:
            self.seq += 1
            return f"{self.seq:06d}"


M = Mock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, obj=None, raw=None, ctype="application/json"):
        data = raw if raw is not None else json.dumps(obj or {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def auth(self, token):
        return self.headers.get("Authorization") == f"Bearer {token}"

    def route(self, method):
        u = urllib.parse.urlparse(self.path)
        parts = u.path.strip("/").split("/")
        q = dict(urllib.parse.parse_qsl(u.query))
        if parts[0] == "gh":
            return self.github(method, parts[1:], q)
        if parts[0] == "raw":
            key = (parts[3], "/".join(parts[4:]))
            if method == "GET" and key in M.commits and not M.flags.get("raw_block"):
                return self.send(200, raw=M.commits[key], ctype="image/jpeg")
            return self.send(404, raw=b"404", ctype="text/plain")
        if parts[0] == "sample":
            return self.send(200, raw=sample(parts[1]), ctype="image/jpeg")
        if parts[0] == "ig":
            return self.instagram(method, parts[1:], q)
        self.send(404)

    def github(self, method, p, q):
        if not self.auth(GH_TOKEN):
            return self.send(401, {"message": "Bad credentials"})
        if p[0] == "repos" and len(p) == 3 and method == "GET":
            return self.send(200, {"private": False, "permissions": {"push": True}})
        if p[0] == "repos" and len(p) == 5 and p[3] == "branches":
            return self.send(200 if p[4] == BRANCH else 404, {"name": p[4]})
        path = "/".join(p[4:])
        if method == "GET":
            if path in M.files and q.get("ref") == BRANCH:
                return self.send(200, {"sha": M.files[path][0]})
            return self.send(404, {"message": "Not Found"})
        if method == "PUT":
            with M.lock:
                M.in_flight += 1
                M.uploads += 1
                n = M.uploads
                if M.in_flight > 1:
                    M.conflicts += 1
            try:
                time.sleep(0.02)
                req = json.loads(self.body())
                if req.get("branch") != BRANCH:
                    return self.send(404, {"message": "Branch not found"})
                if M.flags.get("fail_upload_at") == n:
                    return self.send(500, {"message": "upload failed"})
                data = base64.b64decode(req["content"])
                content_sha, commit_sha = "c" + M.next_id(), "k" + M.next_id()
                M.files[path] = (content_sha, data)
                M.commits[(commit_sha, path)] = data
                if M.flags.get("lose_upload_at") == n:
                    return self.send(502, raw=b"bad gateway", ctype="text/plain")
                return self.send(201, {"content": {"sha": content_sha}, "commit": {"sha": commit_sha}})
            finally:
                with M.lock:
                    M.in_flight -= 1
        if method == "DELETE":
            req = json.loads(self.body())
            if path not in M.files or M.files[path][0] != req.get("sha"):
                return self.send(409, {"message": "sha mismatch"})
            del M.files[path]
            return self.send(200, {"commit": {"sha": "d" + M.next_id()}})
        self.send(404)

    def instagram(self, method, p, q):
        if not self.auth(IG_TOKEN) or "access_token" in q:
            return self.send(401, {"error": {"message": "Invalid OAuth access token", "code": 190}})
        form = dict(urllib.parse.parse_qsl(self.body().decode())) if method == "POST" else {}
        if method == "GET" and p == ["me"]:
            return self.send(200, {"user_id": IG_ID, "username": "test_account"})
        if method == "POST" and p == [IG_ID, "media"]:
            if form.get("media_type") == "CAROUSEL":
                kids = form["children"].split(",")
                if not 2 <= len(kids) <= 10 or any(M.containers.get(k, {}).get("state") != "FINISHED" for k in kids):
                    return self.send(400, {"error": {"message": "bad children", "code": 100}})
                cid = "car" + M.next_id()
                M.containers[cid] = {"type": "CAROUSEL", "children": kids, "caption": form.get("caption"),
                                     "polls": 0, "state": "IN_PROGRESS"}
                return self.send(200, {"id": cid})
            err = self.inspect(form.get("image_url", ""))
            if err:
                return self.send(400, {"error": {"message": err, "code": 9004, "error_subcode": 2207052}})
            cid = "img" + M.next_id()
            M.containers[cid] = {"type": "IMAGE", "item": form.get("is_carousel_item") == "true",
                                 "caption": form.get("caption"), "polls": 0, "state": "IN_PROGRESS"}
            return self.send(200, {"id": cid})
        if method == "POST" and p == [IG_ID, "media_publish"]:
            c = M.containers.get(form.get("creation_id"))
            if not c or c["state"] != "FINISHED":
                return self.send(400, {"error": {"message": "media not ready", "code": 9007}})
            if M.flags.get("fail_publish"):
                return self.send(400, {"error": {"message": "simulated publish failure", "code": 2}})
            mid = "m" + M.next_id()
            c["state"] = "PUBLISHED"
            M.published.append({"id": mid, **c})
            if M.flags.get("lose_publish_response"):
                return self.send(504, raw=b"gateway timeout", ctype="text/plain")
            return self.send(200, {"id": mid})
        if method == "GET" and len(p) == 1 and p[0] in M.containers:
            c = M.containers[p[0]]
            c["polls"] += 1
            if c["state"] == "IN_PROGRESS" and c["polls"] >= 2:
                c["state"] = "ERROR" if M.flags.get("container_error") else "FINISHED"
            return self.send(200, {"status_code": c["state"], "id": p[0]})
        if method == "GET" and len(p) == 1 and p[0].startswith("m"):
            return self.send(200, {"permalink": f"https://www.instagram.com/p/{p[0]}/", "id": p[0]})
        self.send(404, {"error": {"message": "unknown", "code": 100}})

    @staticmethod
    def inspect(url):
        # 실제 인스타처럼 image_url을 내려받아 규격을 확인한다(상수는 엔진 값이 아닌 문서 값)
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = r.read()
        except Exception as e:  # noqa: BLE001 — 모의 서버는 어떤 실패든 오류 응답으로 돌려준다
            return f"download failed: {e}"
        if len(data) > 8_000_000:
            return "too large"
        with Image.open(io.BytesIO(data)) as im:
            if im.format != "JPEG":
                return "not jpeg"
            if not 0.8 <= im.width / im.height <= 1.91:
                return f"aspect ratio {im.width}x{im.height}"
            if im.width > 1440:
                return f"width {im.width}"
        return None

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_DELETE(self):
        self.route("DELETE")


def sample(name):
    sizes = {"portrait.jpg": (1500, 2000), "tall.jpg": (1080, 1920), "wide.jpg": (2000, 1000),
             "square.jpg": (1200, 1200)}
    w, h = sizes.get(name, (1200, 1500))
    img = Image.new("RGB", (w, h), (70 + len(name) * 9 % 120, 110, 150))
    for x in range(0, w, 100):
        img.paste((240, 240, 240), (x, 0, x + 4, h))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def start_mock(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def make(path, size, mode="RGB", color=(120, 90, 60), **save):
    Image.new(mode, size, color).save(path, **save)
    return str(path)


def rich_jpeg(path):
    # GPS·방향(6)·ICC·XMP·주석이 모두 들어간 사진
    img = Image.new("RGB", (1500, 1200), (30, 60, 90))
    exif = Image.Exif()
    exif[0x010F] = "RICOH"
    exif[0x0112] = 6
    exif[0x8825] = {1: "N", 2: (37.0, 34.0, 0.0), 3: "E", 4: (126.0, 58.0, 0.0)}
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    xmp = b'<x:xmpmeta xmlns:x="adobe:ns:meta/">secret-location</x:xmpmeta>'
    img.save(path, "JPEG", exif=exif.tobytes(), icc_profile=icc, xmp=xmp, comment=b"secret comment")
    return str(path)


def jpeg_markers(data):
    marks, i = set(), 2
    while i + 4 <= len(data) and data[i] == 0xFF:
        m = data[i + 1]
        if m == 0xDA:
            break
        marks.add(m)
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return marks


RESULTS = []


def case(name):
    def deco(fn):
        M.flags = {}
        try:
            fn()
            RESULTS.append((name, True, ""))
        except Exception as e:  # noqa: BLE001 — 시험 하나의 실패가 나머지를 막지 않게 한다
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        M.flags = {}
        return fn
    return deco


def expect_error(fn, *needles):
    try:
        fn()
    except E.PostError as e:
        assert all(n in str(e) for n in needles), str(e)
        return str(e)
    raise AssertionError(f"오류가 나야 하는데 성공함 ({needles})")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    srv, base = start_mock()
    tmp = Path(tempfile.mkdtemp(prefix="insta_selftest_", dir=Path(__file__).resolve().parent / ".insta_post_state"
                                if (Path(__file__).resolve().parent / ".insta_post_state").is_dir() else None))
    cfg = {"access_token": IG_TOKEN, "hosting_token": GH_TOKEN, "graph_base": f"{base}/ig",
           "github_api_base": f"{base}/gh", "github_raw_base": f"{base}/raw", "hosting_repo": "me/hosting",
           "hosting_branch": BRANCH, "state_dir": str(tmp / "state"), "poll_interval": 0.05, "raw_timeout": 5}
    src = tmp / "src"
    src.mkdir()
    n = [0]

    def prep(photos, ratio="auto"):
        n[0] += 1
        return E.prepare({"photos": photos, "ratio": ratio, "out_dir": str(tmp / f"out{n[0]}")}, cfg)

    def ratio_of(p):
        return p["width"] / p["height"]

    def post(job_id, photos, caption="x", c=None):
        return E.publish({"job_id": job_id, "photos": [p["path"] for p in photos], "caption": caption}, c or cfg)

    @case("prepare 3:4 → 4:5")
    def _():
        out = prep([make(src / "a.jpg", (1500, 2000))])["photos"][0]
        assert abs(ratio_of(out) - 0.8) < 2e-3 and out["width"] <= 1440, out

    @case("prepare 9:16 → 4:5")
    def _():
        out = prep([make(src / "b.jpg", (1080, 1920))])["photos"][0]
        assert abs(ratio_of(out) - 0.8) < 2e-3, out

    @case("prepare 2:1 → 1.91:1")
    def _():
        out = prep([make(src / "c.jpg", (2000, 1000))])["photos"][0]
        assert 0.8 <= ratio_of(out) <= 1.91 and abs(ratio_of(out) - 1.91) < 3e-3, out

    @case("prepare 큰 사진 너비 1440 이하")
    def _():
        out = prep([make(src / "d.jpg", (4000, 5000))])["photos"][0]
        assert out["width"] == 1440, out

    @case("prepare 캐러셀은 첫 장 비율로 통일")
    def _():
        outs = prep([make(src / "e1.jpg", (2000, 1000)), make(src / "e2.jpg", (1500, 2000))])["photos"]
        assert all(abs(ratio_of(o) - ratio_of(outs[0])) < 3e-3 for o in outs), outs

    @case("prepare 비율 지정 1:1")
    def _():
        out = prep([make(src / "f.jpg", (1500, 2000))], ratio="1:1")["photos"][0]
        assert out["width"] == out["height"], out

    @case("prepare GPS·방향·ICC·XMP·주석 제거, 회전 적용")
    def _():
        out = prep([rich_jpeg(src / "gps.jpg")])["photos"][0]
        data = Path(out["path"]).read_bytes()
        marks = jpeg_markers(data)
        assert not marks & {0xE1, 0xE2, 0xFE}, sorted(hex(m) for m in marks)
        assert b"secret" not in data and b"RICOH" not in data
        assert out["height"] > out["width"], out  # 방향 6 → 세로로 돌아가야 한다

    @case("prepare PNG 투명(RGBA·RGB tRNS)은 흰 바탕")
    def _():
        a = prep([make(src / "g.png", (800, 1000), "RGBA", (0, 0, 0, 0), format="PNG")])["photos"][0]
        b = prep([make(src / "h.png", (800, 1000), "RGB", (0, 0, 0), format="PNG", transparency=(0, 0, 0))])["photos"][0]
        for o in (a, b):
            with Image.open(o["path"]) as im:
                assert im.format == "JPEG" and min(im.getpixel((10, 10))) > 240, im.getpixel((10, 10))

    @case("prepare 16비트 회색조 PNG는 회색 유지")
    def _():
        p = src / "i16.png"
        Image.new("I;16", (800, 1000), 32768).save(p)
        out = prep([str(p)])["photos"][0]
        with Image.open(out["path"]) as im:
            assert 110 < im.getpixel((10, 10))[0] < 145, im.getpixel((10, 10))

    @case("check 계정·저장소·브랜치 확인")
    def _():
        r = E.check(cfg)
        assert r["username"] == "test_account" and r["push"] and r["public"] and r["branch_exists"] and r["ready"], r
        r2 = E.check({**cfg, "hosting_branch": "nope"})
        assert not r2["branch_exists"] and not r2["ready"], r2

    single = prep([make(src / "s.jpg", (1500, 2000))])["photos"]
    carousel = prep([make(src / f"k{i}.jpg", (1200 + i * 100, 1500)) for i in range(3)])["photos"]

    @case("1장 게시 + 호스팅 삭제")
    def _():
        r = post("one", single, "뮤지엄산에서\n#뮤지엄산")
        pub = M.published[-1]
        assert r["media_id"] == pub["id"] and pub["type"] == "IMAGE" and pub["caption"] == "뮤지엄산에서\n#뮤지엄산", r
        assert r["permalink"].endswith(f"/{r['media_id']}/") and not M.files, (r, M.files)

    @case("캐러셀 게시 + 호스팅 삭제 + 순차 업로드")
    def _():
        r = post("car", carousel, "캐러셀")
        pub = M.published[-1]
        assert pub["type"] == "CAROUSEL" and len(pub["children"]) == 3 and pub["caption"] == "캐러셀", pub
        assert all(M.containers[k]["item"] for k in pub["children"]) and not M.files and M.conflicts == 0
        assert r["photos"] == 3

    @case("같은 작업 중복 게시 거부")
    def _():
        post("dup", single)
        n_pub = len(M.published)
        expect_error(lambda: post("dup", single), "이미 게시")
        assert len(M.published) == n_pub

    @case("게시 응답 유실 → 재시도해도 다시 올리지 않음")
    def _():
        M.flags["lose_publish_response"] = True
        expect_error(lambda: post("lost", single), "게시")
        M.flags = {}
        n_pub = len(M.published)
        expect_error(lambda: post("lost", single), "이미 게시됐다")
        assert len(M.published) == n_pub and not M.files

    @case("게시 실패 → 완료 표시 없음, 다시 시도하면 게시")
    def _():
        M.flags["fail_publish"] = True
        expect_error(lambda: post("retry", carousel), "simulated")
        assert not M.files
        M.flags = {}
        r = post("retry", carousel)
        assert r["media_id"] and not M.files

    @case("컨테이너 ERROR → 중단, 호스팅 삭제, 표시 정리")
    def _():
        M.flags["container_error"] = True
        expect_error(lambda: post("cerr", carousel), "ERROR")
        assert not M.files and not E.marker(E.settings(cfg), "cerr").exists()

    @case("캐러셀 중간 업로드 실패 → 앞서 올린 파일 삭제")
    def _():
        M.flags["fail_upload_at"] = M.uploads + 2
        expect_error(lambda: post("upfail", carousel), "업로드")
        assert not M.files, M.files

    @case("업로드 응답 유실 → 조회해서 삭제")
    def _():
        M.flags["lose_upload_at"] = M.uploads + 1
        expect_error(lambda: post("uplost", carousel), "업로드")
        assert not M.files, M.files

    @case("raw 주소가 열리지 않음 → 시간 초과, 호스팅 삭제")
    def _():
        M.flags["raw_block"] = True
        expect_error(lambda: post("rawblock", single, c={**cfg, "raw_timeout": 1}), "공개 주소")
        assert not M.files

    @case("시간 예산 초과 → 스스로 중단, 호스팅 삭제, 표시 정리")
    def _():
        job = {"job_id": "budget", "photos": [p["path"] for p in carousel], "caption": "x", "time_budget": 0.05}
        expect_error(lambda: E.publish(job, cfg), "시간 예산")
        assert not M.files and not E.marker(E.settings(cfg), "budget").exists()

    @case("같은 작업 동시 진행 거부")
    def _():
        mark = E.marker(E.settings(cfg), "busy")
        mark.parent.mkdir(parents=True, exist_ok=True)
        E.write_mark(mark, {"state": "pending"})
        expect_error(lambda: post("busy", single), "진행 중")
        assert mark.exists()

    @case("규격 밖 입력 거부 (11장·긴 캡션·PNG·3:4 원본·job_id)")
    def _():
        p = single[0]["path"]
        bad = [({"job_id": "b1", "photos": [p] * 11}, "1~10장"),
               ({"job_id": "b2", "photos": [p], "caption": "가" * 2201}, "캡션"),
               ({"job_id": "b3", "photos": [make(src / "p.png", (800, 1000), format="PNG")]}, "JPEG 아님"),
               ({"job_id": "b4", "photos": [make(src / "t.jpg", (1500, 2000))]}, "비율"),
               ({"job_id": "../x", "photos": [p]}, "job_id"),
               ({"job_id": "a" * 81, "photos": [p]}, "job_id")]
        for job, msg in bad:
            expect_error(lambda: E.publish(job, cfg), msg)
        assert not M.files

    @case("CLI: stdin UTF-8(인코딩 설정 없이) → RESULT 한 줄, 토큰 노출 없음")
    def _():
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
        env.update({"INSTAGRAM_ACCESS_TOKEN": IG_TOKEN, "INSTA_HOSTING_TOKEN": GH_TOKEN,
                    "INSTAGRAM_GRAPH_BASE": f"{base}/ig", "GITHUB_API_BASE": f"{base}/gh",
                    "GITHUB_RAW_BASE": f"{base}/raw", "INSTA_HOSTING_REPO": "me/hosting",
                    "INSTA_HOSTING_BRANCH": BRANCH, "INSTA_STATE_DIR": str(tmp / "cli_state")})
        job = {"action": "publish", "job_id": "cli", "photos": [single[0]["path"]], "caption": "줄1\n\"따옴표\" 줄2 #한글"}
        p = subprocess.run([sys.executable, str(Path(E.__file__))], input=(json.dumps(job, ensure_ascii=False) + "\n").encode(),
                           capture_output=True, env=env, timeout=60)
        stdout, stderr = p.stdout.decode("utf-8"), p.stderr.decode("utf-8", "replace")
        lines = [ln for ln in stdout.splitlines() if ln.startswith("RESULT ")]
        assert len(lines) == 1, stdout + stderr
        out = json.loads(lines[0][7:])
        assert out["ok"] and M.published[-1]["caption"] == job["caption"], out
        assert IG_TOKEN not in stdout + stderr and GH_TOKEN not in stdout + stderr
        bad = subprocess.run([sys.executable, str(Path(E.__file__))], input=b'{"action": "nope"}\n',
                             capture_output=True, env=env, timeout=60)
        assert bad.returncode == 1 and json.loads(bad.stdout.decode("utf-8").split("RESULT ", 1)[1])["ok"] is False

    @case("오류 메시지에 토큰 노출 없음")
    def _():
        wrong = {**cfg, "access_token": "WRONG-" + IG_TOKEN[::-1]}
        msg = expect_error(lambda: E.check(wrong), "190")
        assert IG_TOKEN[::-1] not in msg

    srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    failed = [r for r in RESULTS if not r[1]]
    for name, ok, err in RESULTS:
        print(f"{'통과' if ok else '실패'}  {name}" + (f"  — {err}" if err else ""))
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} 통과")
    sys.exit(1 if failed else 0)


def serve(port):
    sys.stdout.reconfigure(encoding="utf-8")
    srv, base = start_mock(port)
    print(f"모의 서버 {base} — server.py에 줄 환경변수:")
    print(f"  INSTAGRAM_ACCESS_TOKEN={IG_TOKEN} INSTA_HOSTING_TOKEN={GH_TOKEN} INSTAGRAM_GRAPH_BASE={base}/ig "
          f"GITHUB_API_BASE={base}/gh GITHUB_RAW_BASE={base}/raw INSTA_HOSTING_REPO=me/hosting INSTA_HOSTING_BRANCH={BRANCH}")
    print(f"  견본 사진: {base}/sample/portrait.jpg · tall.jpg · wide.jpg · square.jpg")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        serve(int(sys.argv[2]) if len(sys.argv) > 2 else 8766)
    else:
        main()
