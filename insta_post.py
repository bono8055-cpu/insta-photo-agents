# 사진을 인스타 규격으로 맞추고 공개 저장소 임시 호스팅을 거쳐 Instagram Graph API로 게시하는 엔진 (표준 라이브러리 + Pillow만, docs/insta-post-spec.md)
import base64
import http.client
import io
import json
import math
import os
import re
import secrets
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageCms, ImageOps

HERE = Path(__file__).resolve().parent
MIN_RATIO, MAX_RATIO = 4 / 5, 1.91
RATIOS = {"4:5": 4 / 5, "1:1": 1.0, "1.91:1": 1.91}
MAX_WIDTH = 1440
# 공식 문서 표기가 "8 MB"(레퍼런스)와 "8MiB"(오류 코드)로 갈려 작은 쪽에 맞춘다
MAX_BYTES = 8_000_000
MAX_PHOTOS = 10
DEFAULTS = {
    "graph_base": "https://graph.instagram.com/v25.0",
    # 2026-10-10 사용자 결정: 이 저장소를 공개로 두고 사진은 전용 브랜치에만 올렸다 지운다(명세 기본값 insta-photo-hosting·main 대체)
    "hosting_repo": "bono8055-cpu/insta-photo-agents",
    "hosting_branch": "photo-hosting",
    "hosting_dir": "posts",
    "github_api_base": "https://api.github.com",
    "github_raw_base": "https://raw.githubusercontent.com",
    "state_dir": str(HERE / ".insta_post_state"),
    "max_caption": 2200,
    "max_hashtags": 30,
    "poll_interval": 2.0,
    "poll_timeout": 60.0,
    "raw_timeout": 30.0,
}
ENV = {
    "access_token": "INSTAGRAM_ACCESS_TOKEN",
    "user_id": "INSTAGRAM_USER_ID",
    "graph_base": "INSTAGRAM_GRAPH_BASE",
    "hosting_token": "INSTA_HOSTING_TOKEN",
    "hosting_repo": "INSTA_HOSTING_REPO",
    "hosting_branch": "INSTA_HOSTING_BRANCH",
    "hosting_dir": "INSTA_HOSTING_DIR",
    "github_api_base": "GITHUB_API_BASE",
    "github_raw_base": "GITHUB_RAW_BASE",
    "state_dir": "INSTA_STATE_DIR",
    "max_caption": "INSTA_MAX_CAPTION",
    "max_hashtags": "INSTA_MAX_HASHTAGS",
}


class PostError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # 리다이렉트를 따라가면 Authorization 헤더가 다른 호스트로 넘어간다
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(_NoRedirect)
JOB_ID = re.compile(r"[A-Za-z0-9._-]{1,80}")
STALE_PENDING = 600


def settings(cfg):
    s = {**DEFAULTS, **{k: v for k, v in cfg.items() if v not in (None, "")}}
    for k in ("max_caption", "max_hashtags"):
        s[k] = int(s[k])
    for k in ("graph_base", "github_api_base", "github_raw_base"):
        s[k] = s[k].rstrip("/")
    return s


def http(method, url, token=None, form=None, body=None, timeout=60):
    headers = {"User-Agent": "insta-post/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/vnd.github+json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with OPENER.open(req, timeout=timeout) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()
    except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
        # 주소에는 토큰이 없지만 쿼리는 빼고 남긴다
        raise PostError(f"{method} {url.split('?')[0]} 연결 실패: {getattr(e, 'reason', e)}")


def call_json(method, url, token, what, **kw):
    status, _, raw = http(method, url, token, **kw)
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        body = {}
    if status >= 400 or (isinstance(body, dict) and "error" in body):
        err = body.get("error") if isinstance(body, dict) else None
        msg = err.get("message") if isinstance(err, dict) else body.get("message") if isinstance(body, dict) else None
        code = f" code {err.get('code')}/{err.get('error_subcode')}" if isinstance(err, dict) else ""
        raise PostError(f"{what}: HTTP {status} {msg or raw[:200]!r}{code}")
    return body


def graph(s, method, path, what, **params):
    url = f"{s['graph_base']}/{path}"
    if method == "GET":
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return call_json("GET", url, s["access_token"], what)
    return call_json("POST", url, s["access_token"], what, form=params)


def ig_user(s, log):
    if s.get("user_id"):
        return str(s["user_id"]), None
    me = graph(s, "GET", "me", "계정 조회", fields="user_id,username")
    me = (me.get("data") or [{}])[0] if "data" in me else me
    log.append(f"인스타 계정 @{me.get('username')}")
    return str(me["user_id"]), me.get("username")


# ---------- check ----------

def check(cfg):
    s, log = settings(cfg), []
    missing = [ENV[k] for k in ("access_token", "hosting_token") if not s.get(k)]
    if missing:
        raise PostError(f"환경변수 없음: {', '.join(missing)}")
    me = graph(s, "GET", "me", "계정 조회", fields="user_id,username")
    me = (me.get("data") or [{}])[0] if "data" in me else me
    repo = call_json("GET", f"{s['github_api_base']}/repos/{s['hosting_repo']}", s["hosting_token"], "호스팅 저장소 조회")
    can_push = bool((repo.get("permissions") or {}).get("push"))
    branch_url = f"{s['github_api_base']}/repos/{s['hosting_repo']}/branches/{urllib.parse.quote(s['hosting_branch'])}"
    has_branch = http("GET", branch_url, s["hosting_token"])[0] == 200
    log.append(f"인스타 @{me.get('username')} · 저장소 {s['hosting_repo']} push={can_push} "
               f"공개={not repo.get('private')} 브랜치 {s['hosting_branch']} 있음={has_branch}")
    return {"username": me.get("username"), "user_id": me.get("user_id"), "repo": s["hosting_repo"],
            "branch": s["hosting_branch"], "push": can_push, "public": not repo.get("private"),
            "branch_exists": has_branch, "ready": can_push and not repo.get("private") and has_branch, "log": log}


# ---------- prepare ----------

def to_rgb(img):
    if img.mode.startswith("I"):
        # 16비트 회색조를 그냥 RGB로 바꾸면 255에서 잘려 하얗게 된다
        icc = img.info.get("icc_profile")
        img = img.point(lambda v: v / 257).convert("L")
        img.info["icc_profile"] = icc
    if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        bg.info["icc_profile"] = img.info.get("icc_profile")
        return bg
    out = img.convert("RGB")
    out.info["icc_profile"] = img.info.get("icc_profile")
    return out


def to_srgb(img):
    icc = img.info.get("icc_profile")
    if not icc:
        return img
    try:
        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        if "srgb" in ImageCms.getProfileDescription(src).lower():
            return img
        return ImageCms.profileToProfile(img, src, ImageCms.createProfile("sRGB"), outputMode="RGB")
    except (ImageCms.PyCMSError, OSError, ValueError):
        return img


def target_ratio(ratio, first_size):
    if ratio in (None, "", "auto"):
        w, h = first_size
        return min(max(w / h, MIN_RATIO), MAX_RATIO)
    if ratio not in RATIOS:
        raise PostError(f"비율 값 이상: {ratio!r} (auto, 4:5, 1:1, 1.91:1)")
    return RATIOS[ratio]


def fit(img, r):
    w, h = img.size
    if w / h > r:
        nw = max(1, round(h * r))
        left = (w - nw) // 2
        img = img.crop((left, 0, left + nw, h))
    else:
        nh = max(1, round(w / r))
        top = (h - nh) // 2
        img = img.crop((0, top, w, top + nh))
    if img.width > MAX_WIDTH:
        nh = round(img.height * MAX_WIDTH / img.width)
        img = img.resize((MAX_WIDTH, nh), Image.LANCZOS)
    w, h = img.size
    # 반올림으로 허용 비율 경계를 1px 벗어나면 그만큼 잘라낸다
    if w / h > MAX_RATIO:
        img = img.crop((0, 0, math.floor(h * MAX_RATIO), h))
    elif w / h < MIN_RATIO:
        img = img.crop((0, 0, w, math.floor(w / MIN_RATIO)))
    return img


def encode(img):
    img.info.clear()
    for q in (90, 80, 70, 60, 50):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True)
        if buf.tell() <= MAX_BYTES:
            return buf.getvalue(), q
    raise PostError("품질 50으로도 8MB를 넘는다")


def prepare(job, cfg=None):
    photos = job.get("photos") or []
    if not 1 <= len(photos) <= MAX_PHOTOS:
        raise PostError(f"사진은 1~{MAX_PHOTOS}장 — 현재 {len(photos)}장")
    # 시스템 임시 폴더는 다른 사용자도 쓸 수 있는 곳일 수 있어(이 PC는 TMPDIR가 Everyone 쓰기) 상태 폴더 아래에 둔다
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
    prepared = Path(settings(cfg or {})["state_dir"]) / "prepared"
    if not job.get("out_dir") and prepared.is_dir():
        for old in prepared.iterdir():
            if old.is_dir() and time.time() - old.stat().st_mtime > 86400:
                shutil.rmtree(old, ignore_errors=True)
    out_dir = Path(job.get("out_dir") or prepared / stamp)
    out_dir.mkdir(parents=True, exist_ok=True)
    log, outs, r = [], [], None
    for i, src in enumerate(photos, 1):
        with Image.open(src) as raw:
            img = ImageOps.exif_transpose(raw)
            img.info["icc_profile"] = raw.info.get("icc_profile")
            img = to_srgb(to_rgb(img))
        if r is None:
            r = target_ratio(job.get("ratio", "auto"), img.size)
            log.append(f"비율 {r:.4f}")
        img = fit(img, r)
        data, q = encode(img)
        dest = out_dir / f"{i:02d}.jpg"
        dest.write_bytes(data)
        outs.append({"source": str(src), "path": str(dest), "width": img.width, "height": img.height,
                     "bytes": len(data), "quality": q})
        log.append(f"{Path(src).name} → {dest.name} {img.width}x{img.height} {len(data) // 1024}KB q{q}")
    return {"photos": outs, "ratio": r, "out_dir": str(out_dir), "log": log}


# ---------- publish ----------

def validate(job, s):
    photos = job.get("photos") or []
    caption = job.get("caption") or ""
    if not JOB_ID.fullmatch(str(job.get("job_id") or "")):
        raise PostError("job_id는 영문·숫자·._- 80자 이내여야 한다(중복 게시 방지용 작업 이름)")
    if not 1 <= len(photos) <= MAX_PHOTOS:
        raise PostError(f"사진은 1~{MAX_PHOTOS}장 — 현재 {len(photos)}장")
    if len(caption) > s["max_caption"]:
        raise PostError(f"캡션 {len(caption)}자 > {s['max_caption']}")
    tags = [w for w in caption.split() if w.startswith("#") and len(w) > 1]
    if len(tags) > s["max_hashtags"]:
        raise PostError(f"해시태그 {len(tags)}개 > {s['max_hashtags']}")
    for p in photos:
        p = Path(p)
        if not p.is_file():
            raise PostError(f"파일 없음: {p}")
        if p.stat().st_size > MAX_BYTES:
            raise PostError(f"{p.name}: 8MB 초과 — prepare를 먼저 실행")
        with Image.open(p) as im:
            if im.format != "JPEG":
                raise PostError(f"{p.name}: JPEG 아님({im.format}) — prepare를 먼저 실행")
            if not MIN_RATIO - 1e-3 <= im.width / im.height <= MAX_RATIO + 1e-3:
                raise PostError(f"{p.name}: 비율 {im.width}x{im.height} 범위 밖 — prepare를 먼저 실행")


def marker(s, job_id):
    return Path(s["state_dir"]) / f"{job_id}.json"


def write_mark(mark, data):
    mark.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def claim(s, mark, log):
    # 게시 전에 표시 파일을 원자적으로 만들어 동시 실행·재실행 중복 게시를 막는다
    mark.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(mark, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            prev = json.loads(mark.read_text(encoding="utf-8"))
        except ValueError:
            raise PostError(f"표시 파일이 손상됐다 — 인스타에서 게시 여부를 확인한 뒤 {mark} 를 지운다")
        state = prev.get("state")
        if state == "published":
            raise PostError(f"이미 게시한 작업이다: {prev.get('permalink') or prev.get('media_id')}")
        if state == "publishing" and prev.get("creation_id"):
            try:
                st = graph(s, "GET", prev["creation_id"], "이전 게시 확인", fields="status_code").get("status_code")
            except PostError as e:
                raise PostError(f"이전 시도의 게시 여부를 확인하지 못했다 — 인스타에서 확인한 뒤 {mark} 를 지운다: {e}")
            if st == "PUBLISHED":
                write_mark(mark, {**prev, "state": "published"})
                raise PostError("이전 시도에서 이미 게시됐다(응답만 유실) — 다시 올리지 않는다")
            log.append(f"이전 시도 컨테이너 {st} — 게시되지 않아 다시 시도")
        elif state == "pending" and time.time() - mark.stat().st_mtime < STALE_PENDING:
            raise PostError("같은 작업이 이미 진행 중이다")
        write_mark(mark, {"state": "pending"})
        return
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"state": "pending"}, f)


def contents_url(s, name):
    return f"{s['github_api_base']}/repos/{s['hosting_repo']}/contents/{s['hosting_dir']}/{name}"


def upload(s, path, name):
    body = call_json("PUT", contents_url(s, name), s["hosting_token"], f"업로드 {name}",
                     body={"message": f"add {name}", "branch": s["hosting_branch"],
                           "content": base64.b64encode(Path(path).read_bytes()).decode()})
    return body["content"]["sha"], body["commit"]["sha"]


def find_hosted(s, name):
    # 업로드는 커밋됐는데 응답만 잃은 경우 지울 sha를 찾는다
    try:
        url = f"{contents_url(s, name)}?ref={urllib.parse.quote(s['hosting_branch'])}"
        return call_json("GET", url, s["hosting_token"], f"조회 {name}").get("sha")
    except PostError:
        return None


def within_budget(end, what):
    # 호출자가 프로세스를 강제 종료하기 전에 스스로 멈춰야 finally에서 호스팅 정리가 된다
    if end is not None and time.monotonic() > end:
        raise PostError(f"{what}: 시간 예산을 넘어 중단했다")


def wait_raw(s, url, end=None):
    deadline = time.monotonic() + s["raw_timeout"]
    if end is not None:
        deadline = min(deadline, end)
    while True:
        try:
            status, headers, _ = http("GET", url, timeout=15)
        except PostError:
            status, headers = 0, None
        ctype = headers.get("Content-Type", "") if headers else ""
        if status == 200 and ctype.startswith("image/"):
            return
        if time.monotonic() > deadline:
            raise PostError(f"공개 주소가 열리지 않음 {url} (HTTP {status} {ctype})")
        time.sleep(1)


def remove(s, name, sha, log):
    try:
        call_json("DELETE", contents_url(s, name), s["hosting_token"], f"삭제 {name}",
                  body={"message": f"remove {name}", "sha": sha, "branch": s["hosting_branch"]})
        log.append(f"호스팅 삭제 {name}")
    except Exception as e:  # noqa: BLE001 — 한 장 삭제 실패가 나머지 삭제를 막으면 안 된다
        log.append(f"경고 - 호스팅 삭제 실패, 수동 삭제 필요: {e}")


def wait_ready(s, cids, deadline):
    pending = list(cids)
    while True:
        for cid in list(pending):
            st = graph(s, "GET", cid, "컨테이너 상태", fields="status_code").get("status_code")
            if st == "FINISHED":
                pending.remove(cid)
            elif st in ("ERROR", "EXPIRED"):
                raise PostError(f"컨테이너 {cid} {st}")
        if not pending:
            return
        if time.monotonic() > deadline:
            raise PostError(f"컨테이너 {s['poll_timeout']:.0f}초 안에 준비되지 않음 ({', '.join(pending)})")
        time.sleep(s["poll_interval"])


def publish(job, cfg):
    s, log = settings(cfg), []
    missing = [ENV[k] for k in ("access_token", "hosting_token") if not s.get(k)]
    if missing:
        raise PostError(f"환경변수 없음: {', '.join(missing)}")
    validate(job, s)
    budget = job.get("time_budget")
    end = time.monotonic() + float(budget) if budget else None
    mark = marker(s, job["job_id"])
    claim(s, mark, log)
    state = "pending"
    caption = job.get("caption") or ""
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
    hosted, urls = [], []
    try:
        ig, _ = ig_user(s, log)
        for i, p in enumerate(job["photos"], 1):
            name = f"{stamp}-{i:02d}.jpg"
            within_budget(end, "업로드")
            try:
                content_sha, commit_sha = upload(s, p, name)
            except PostError:
                sha = find_hosted(s, name)
                if sha:
                    hosted.append((name, sha))
                raise
            hosted.append((name, content_sha))
            url = f"{s['github_raw_base']}/{s['hosting_repo']}/{commit_sha}/{s['hosting_dir']}/{name}"
            wait_raw(s, url, end)
            urls.append(url)
            log.append(f"호스팅 업로드 {name}")
        within_budget(end, "컨테이너 생성")
        deadline = time.monotonic() + s["poll_timeout"]
        if end is not None:
            deadline = min(deadline, end)
        if len(urls) == 1:
            cid = graph(s, "POST", f"{ig}/media", "컨테이너 생성", image_url=urls[0], caption=caption)["id"]
        else:
            children = [graph(s, "POST", f"{ig}/media", "캐러셀 항목 생성", image_url=u, is_carousel_item="true")["id"]
                        for u in urls]
            wait_ready(s, children, deadline)
            cid = graph(s, "POST", f"{ig}/media", "캐러셀 생성", media_type="CAROUSEL",
                        children=",".join(children), caption=caption)["id"]
        wait_ready(s, [cid], deadline)
        log.append(f"컨테이너 {cid} 준비 완료")
        # 게시 응답을 잃어도 재실행 때 이 컨테이너가 게시됐는지 확인할 수 있게 먼저 남긴다
        write_mark(mark, {"state": "publishing", "creation_id": cid})
        state = "publishing"
        res = graph(s, "POST", f"{ig}/media_publish", "게시", creation_id=cid)
        state = "published"
        result = {"state": "published", "media_id": res["id"], "creation_id": cid, "job_id": job["job_id"],
                  "photos": len(urls), "published_at": datetime.now().astimezone().isoformat(timespec="seconds")}
        log.append(f"게시 완료 media_id={res['id']}")
        if res.get("config_issue"):
            log.append(f"경고 - config_issue={res['config_issue']} (캡션 누락 등) — 앱에서 확인")
        try:
            result["permalink"] = graph(s, "GET", res["id"], "링크 조회", fields="permalink").get("permalink")
        except PostError as e:
            log.append(f"링크 조회 실패(게시는 완료): {e}")
        try:
            write_mark(mark, result)
        except OSError as e:
            log.append(f"경고 - 게시 완료 표시 저장 실패(게시는 완료, 같은 작업 재시도 금지): {e}")
        return {**result, "log": log}
    finally:
        if state == "pending":
            mark.unlink(missing_ok=True)
        for name, sha in hosted:
            remove(s, name, sha, log)
        job["_log"] = log


# ---------- CLI ----------

def load_env_file(path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def config_from_env():
    return {k: os.environ.get(env) for k, env in ENV.items()}


def run(job, cfg):
    action = job.get("action")
    if action == "check":
        return check(cfg)
    if action == "prepare":
        return prepare(job, cfg)
    if action == "publish":
        return publish(job, cfg)
    raise PostError(f"action 값 이상: {action!r} (check, prepare, publish)")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_env_file(HERE / ".env")
    job = {}
    try:
        # Windows 파이프 stdin은 cp949로 읽히므로 바이트를 UTF-8로 직접 푼다
        job = json.loads(sys.stdin.buffer.readline().decode("utf-8") or "{}")
        out = {"ok": True, **run(job, config_from_env())}
    except Exception as e:  # noqa: BLE001 — 호출자는 RESULT 한 줄만 읽으므로 어떤 오류든 그 형식으로 낸다
        msg = str(e) if isinstance(e, PostError) else f"{type(e).__name__}: {e}"
        out = {"ok": False, "error": msg, "log": job.get("_log", []) if isinstance(job, dict) else []}
    print("RESULT " + json.dumps(out, ensure_ascii=False))
    sys.exit(0 if out["ok"] else 1)


if __name__ == "__main__":
    main()
