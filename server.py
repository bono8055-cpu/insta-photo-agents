# insta_post 엔진을 브라우저 화면(web/index.html)에 연결하는 로컬 서버 — 127.0.0.1 전용, 표준 라이브러리 + Pillow (docs/insta-post-screen.md 0~4절)
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from insta_post import load_env_file

HERE = Path(__file__).resolve().parent
ENGINE = HERE / "insta_post.py"
PAGE = HERE / "web" / "index.html"
WORK = HERE / "work"
PORT = int(os.environ.get("INSTA_SERVER_PORT") or 8765)
JOB_RE = re.compile(r"[0-9a-f]{16}")
EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_UPLOAD = 60 * 1024 * 1024
MAX_PHOTOS = 10
# x로 뺀 사진도 작업 폴더에 남으므로 누적 업로드는 따로 넉넉히 센다(게시 장수 10은 prepare에서 검사)
MAX_UPLOADS = 50
MAX_PIXELS = 50_000_000
PUBLISH_TIMEOUT = 300
# 엔진이 스스로 멈추고 호스팅을 정리할 여유를 서버 시간 제한보다 앞에 둔다
PUBLISH_BUDGET = 200
JOB_LOCK = threading.Lock()
RATIO_LABELS = {"4:5": 0.8, "1:1": 1.0, "1.91:1": 1.91}
ENGINE_LOCK = threading.Lock()
MESSAGES = {
    "token": "인스타 토큰이 없거나 만료됐다. .env의 INSTAGRAM_ACCESS_TOKEN을 새로 넣는다",
    "hosting_token": "호스팅 토큰이 없거나 틀렸다. .env의 INSTA_HOSTING_TOKEN을 확인한다",
    "push": "호스팅 토큰에 저장소 쓰기 권한이 없다",
    "private": "저장소가 비공개라 인스타가 사진을 가져갈 수 없다",
    "branch": "호스팅 브랜치가 저장소에 없다. 사진 전용 브랜치를 먼저 만든다",
    "raw": "GitHub에서 사진 주소가 열리지 않았다. 잠시 뒤 다시 시도한다",
    "limit": "24시간 게시 한도를 넘었다",
}


class ApiError(Exception):
    def __init__(self, status, message, step="", log=None):
        super().__init__(message)
        self.status, self.message, self.step, self.log = status, message, step, log or []


def engine(job, timeout, state_dir=None):
    env = dict(os.environ)
    if state_dir:
        env["INSTA_STATE_DIR"] = str(state_dir)
    with ENGINE_LOCK:
        p = subprocess.Popen([sys.executable, str(ENGINE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, env=env, cwd=HERE)
        try:
            out, err = p.communicate((json.dumps(job, ensure_ascii=False) + "\n").encode("utf-8"), timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
            raise ApiError(504, f"엔진이 {timeout}초 안에 끝나지 않았다", "엔진")
    for line in out.decode("utf-8", "replace").splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[7:])
    raise ApiError(500, f"엔진 응답이 없다: {err.decode('utf-8', 'replace')[-300:]}", "엔진")


def friendly(error):
    # 엔진 오류를 화면 문구(명세 4절)로 바꾸고, 멈춘 단계를 뽑는다
    head, sep, rest = error.partition(":")
    step = head.split()[0] if sep and head.strip() and len(head) <= 60 else ""
    detail = rest.strip() if step else error
    if "INSTAGRAM_ACCESS_TOKEN" in error or "code 190" in error:
        return MESSAGES["token"], step
    if "INSTA_HOSTING_TOKEN" in error or "Bad credentials" in error:
        return MESSAGES["hosting_token"], step
    if "2207042" in error:
        return MESSAGES["limit"], step
    if "공개 주소가 열리지 않음" in error:
        return MESSAGES["raw"], "호스팅"
    if "Branch not found" in error:
        return MESSAGES["branch"], step
    if step == "업로드" and ("HTTP 403" in error or "HTTP 404" in error):
        return MESSAGES["push"], step
    # 단계 이름은 따로 돌려주므로 본문에서 빼서 화면에 두 번 나오지 않게 한다
    return re.sub(r"access_token=[^&\s]+", "access_token=***", detail), step


def job_dir(job, must_exist=True):
    if not isinstance(job, str) or not JOB_RE.fullmatch(job):
        raise ApiError(400, "작업 id가 올바르지 않다")
    d = WORK / job
    if must_exist and not d.is_dir():
        raise ApiError(404, "작업을 찾을 수 없다. 화면을 새로 고친다")
    return d


def cleanup_old():
    if not WORK.is_dir():
        return
    for d in WORK.iterdir():
        if d.is_dir() and JOB_RE.fullmatch(d.name) and time.time() - d.stat().st_mtime > 86400:
            shutil.rmtree(d, ignore_errors=True)


def load_meta(d):
    f = d / "meta.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def ensure_open(d):
    if (d / "published.json").exists():
        raise ApiError(409, "이미 게시한 작업이다. [새 게시]로 새 작업을 만든다")


# ---------- API ----------

def api_check():
    r = engine({"action": "check"}, 60)
    if not r.get("ok"):
        msg, _ = friendly(r.get("error", ""))
        return {"ok": False, "username": None, "push": False, "public": False, "ready": False, "error": msg, **limits()}
    error = None
    if not r.get("push"):
        error = MESSAGES["push"]
    elif not r.get("public"):
        error = MESSAGES["private"]
    elif not r.get("branch_exists"):
        error = MESSAGES["branch"]
    return {"ok": True, "username": r.get("username"), "push": bool(r.get("push")), "public": bool(r.get("public")),
            "ready": bool(r.get("ready")), "error": error, **limits()}


def limits():
    return {"maxCaption": int(os.environ.get("INSTA_MAX_CAPTION") or 2200),
            "maxHashtags": int(os.environ.get("INSTA_MAX_HASHTAGS") or 30)}


def api_job():
    cleanup_old()
    job = secrets.token_hex(8)
    (WORK / job).mkdir(parents=True)
    return {"job": job}


def api_photo(query, body):
    d = job_dir(query.get("job"))
    ensure_open(d)
    ext = Path(query.get("name") or "").suffix.lower()
    if ext not in EXTS:
        raise ApiError(400, "jpg·png·webp만 받는다")
    meta = load_meta(d)
    if len(meta) >= MAX_UPLOADS:
        raise ApiError(400, f"한 작업에서 올릴 수 있는 사진은 {MAX_UPLOADS}장까지다. [새 게시]로 새로 시작한다")
    i = max((int(k) for k in meta), default=0) + 1
    path = d / f"src_{i:02d}{ext}"
    path.write_bytes(body)
    try:
        with Image.open(path, formats=["JPEG", "PNG", "WEBP"]) as im:
            w, h = im.size
            if w * h > MAX_PIXELS:
                raise ValueError("too many pixels")
            # 방향 태그 5~8은 90도 회전이라 가로세로가 바뀐다
            if im.getexif().get(0x0112) in (5, 6, 7, 8):
                w, h = h, w
    except (OSError, ValueError, Image.DecompressionBombError):
        path.unlink(missing_ok=True)
        raise ApiError(400, f"이미지로 열 수 없거나 너무 큰 파일이다(jpg·png·webp, {MAX_PIXELS // 1_000_000}백만 화소 이하)")
    meta[str(i)] = {"file": path.name, "w": w, "h": h, "name": query.get("name")}
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return {"i": i, "w": w, "h": h}


def ratio_label(r):
    for label, v in RATIO_LABELS.items():
        if abs(r - v) < 0.005:
            return label
    return f"{r:.2f}:1"


def api_prepare(req):
    d = job_dir(req.get("job"))
    ensure_open(d)
    meta = load_meta(d)
    order = req.get("order") or []
    ratio = req.get("ratio") or "auto"
    if ratio not in ("auto", *RATIO_LABELS):
        raise ApiError(400, "비율 값이 올바르지 않다")
    if not order or len(order) > MAX_PHOTOS or any(str(i) not in meta for i in order) or len(set(order)) != len(order):
        raise ApiError(400, "사진 순서가 올바르지 않다")
    tmp = d / "prepare_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    r = engine({"action": "prepare", "photos": [str(d / meta[str(i)]["file"]) for i in order],
                "ratio": ratio, "out_dir": str(tmp)}, 60)
    if not r.get("ok"):
        msg, step = friendly(r.get("error", ""))
        raise ApiError(400, msg, step, r.get("log"))
    for old in d.glob("post_*.jpg"):
        old.unlink()
    items = []
    for k, (i, ph) in enumerate(zip(order, r["photos"]), 1):
        Path(ph["path"]).replace(d / f"post_{k:02d}.jpg")
        sw, sh = meta[str(i)]["w"], meta[str(i)]["h"]
        sr, tr = sw / sh, r["ratio"]
        axis, pct = (None, 0.0)
        if sr > tr + 1e-6:
            axis, pct = "가로", (1 - tr / sr) * 100
        elif sr < tr - 1e-6:
            axis, pct = "세로", (1 - sr / tr) * 100
        items.append({"k": k, "i": i, "w": ph["width"], "h": ph["height"], "bytes": ph["bytes"],
                      "cropPct": round(pct, 1), "cropAxis": axis})
    shutil.rmtree(tmp, ignore_errors=True)
    return {"ratio": r["ratio"], "ratioLabel": ratio_label(r["ratio"]), "items": items}


def api_publish(req):
    d = job_dir(req.get("job"))
    ensure_open(d)
    posts = sorted(d.glob("post_*.jpg"))
    if not posts:
        raise ApiError(400, "준비된 사진이 없다")
    r = engine({"action": "publish", "job_id": d.name, "photos": [str(p) for p in posts],
                "caption": req.get("caption") or "", "time_budget": PUBLISH_BUDGET}, PUBLISH_TIMEOUT, state_dir=d)
    log = r.get("log") or []
    if not r.get("ok"):
        msg, step = friendly(r.get("error", ""))
        raise ApiError(502, msg, step, log)
    result = {"mediaId": r.get("media_id"), "permalink": r.get("permalink"), "log": log,
              "warnings": [line for line in log if line.startswith("경고")]}
    (d / "published.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"{self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}\n")

    def send(self, code, obj=None, raw=None, ctype="application/json; charset=utf-8"):
        data = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def allowed(self):
        # 토큰을 쥔 서버라 다른 사이트(DNS 리바인딩·CSRF)에서 오는 요청을 막는다
        if self.headers.get("Host") not in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"):
            return False
        return not self.path.startswith("/api/") or self.headers.get("X-Requested-With") == "insta-post"

    def read_body(self, limit):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "Content-Length가 올바르지 않다")
        if n < 0 or n > limit:
            raise ApiError(413, "파일이 너무 크다")
        return self.rfile.read(n) if n else b""

    def handle_api(self, method):
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        if method == "GET" and u.path == "/api/check":
            return self.send(200, api_check())
        if method == "GET" and u.path == "/api/image":
            d = job_dir(q.get("job"))
            k = q.get("k") or ""
            f = d / f"post_{int(k):02d}.jpg" if k.isascii() and k.isdigit() else None
            if not f or not f.is_file():
                raise ApiError(404, "미리보기가 없다")
            return self.send(200, raw=f.read_bytes(), ctype="image/jpeg")
        if method == "POST" and u.path == "/api/job":
            return self.send(200, api_job())
        if method == "POST" and u.path == "/api/photo":
            return self.send(200, api_photo(q, self.read_body(MAX_UPLOAD)))
        if method == "POST" and u.path in ("/api/prepare", "/api/publish"):
            try:
                req = json.loads(self.read_body(1024 * 1024) or b"{}")
            except ValueError:
                raise ApiError(400, "요청 본문이 JSON이 아니다")
            if not isinstance(req, dict):
                raise ApiError(400, "요청 본문이 JSON 객체가 아니다")
            # 같은 작업 폴더를 prepare·publish가 동시에 건드리지 않게 한다
            with JOB_LOCK:
                return self.send(200, (api_prepare if u.path == "/api/prepare" else api_publish)(req))
        raise ApiError(404, "없는 경로다")

    def dispatch(self, method):
        if not self.allowed():
            return self.send(403, {"error": "허용되지 않은 요청이다"})
        if method == "GET" and urllib.parse.urlparse(self.path).path in ("/", "/index.html"):
            return self.send(200, raw=PAGE.read_bytes(), ctype="text/html; charset=utf-8")
        try:
            self.handle_api(method)
        except ApiError as e:
            self.send(e.status, {"error": e.message, "step": e.step, "log": e.log})
        except Exception as e:  # noqa: BLE001 — 화면에는 항상 JSON 오류로 돌려준다
            self.send(500, {"error": f"서버 오류: {type(e).__name__}: {e}", "step": "", "log": []})

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    # 화면의 캡션·해시태그 한도를 엔진과 같은 .env 값으로 맞춘다
    load_env_file(HERE / ".env")
    WORK.mkdir(exist_ok=True)
    cleanup_old()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"인스타 게시 화면: {url}  (끄려면 Ctrl+C)")
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
