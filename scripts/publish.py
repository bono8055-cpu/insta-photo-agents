# content/approved 게시 패키지를 검증하고 Instagram Graph API로 게시하는 스크립트 (기본 dry-run, --publish <id>로 실제 게시)
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
GRAPH = "https://graph.instagram.com/v25.0"
# Graph API는 파일을 직접 받지 않고 공개 URL을 가져가므로, 게시 동안만 이 공개 저장소에 올렸다가 지운다
HOST_REPO = "bono8055-cpu/insta-photo-hosting"
GITHUB_API = "https://api.github.com"
KST = timezone(timedelta(hours=9))
APPROVED = ROOT / "content" / "approved"
EXPORT = ROOT / "photos" / "export"
MAX_BYTES = 8 * 1024 * 1024
MIN_RATIO, MAX_RATIO = 4 / 5, 1.91
MIN_WIDTH, MAX_WIDTH = 320, 1440
MAX_CAPTION = 2200
MAX_HASHTAGS = 5
MAX_CAROUSEL = 10
GPS_IFD = 0x8825


def full_caption(pkg):
    tags = " ".join(pkg.get("hashtags", []))
    return f"{pkg.get('caption', '').strip()}\n\n{tags}".strip()


def validate(pkg):
    errors = []
    photos = [ROOT / p for p in pkg.get("photos", [])]
    fmt = pkg.get("format")
    if fmt == "single" and len(photos) != 1:
        errors.append(f"single인데 사진 {len(photos)}장")
    elif fmt == "carousel" and not 2 <= len(photos) <= MAX_CAROUSEL:
        errors.append(f"캐러셀은 2~{MAX_CAROUSEL}장 — 현재 {len(photos)}장")
    elif fmt not in ("single", "carousel"):
        errors.append(f"format 값 이상: {fmt!r}")
    ratios = set()
    for p in photos:
        if p.parent != EXPORT:
            errors.append(f"{p.name}: photos/export 밖의 파일 — export_photos.py 결과만 게시")
        if not p.exists():
            errors.append(f"{p.name}: 파일 없음")
            continue
        if p.stat().st_size > MAX_BYTES:
            errors.append(f"{p.name}: 8MB 초과")
        with Image.open(p) as im:
            w, h = im.size
            if im.format != "JPEG":
                errors.append(f"{p.name}: JPEG 아님({im.format})")
            if not MIN_WIDTH <= w <= MAX_WIDTH:
                errors.append(f"{p.name}: 폭 {w}px 범위 밖")
            if not MIN_RATIO <= w / h <= MAX_RATIO:
                errors.append(f"{p.name}: 비율 {w}x{h} 범위 밖")
            if im.getexif().get_ifd(GPS_IFD):
                errors.append(f"{p.name}: GPS 정보 남아 있음")
        ratios.add(round(w / h, 3))
    if len(ratios) > 1:
        errors.append(f"캐러셀 비율 불일치 {sorted(ratios)}")
    text = full_caption(pkg)
    if len(text) > MAX_CAPTION:
        errors.append(f"캡션 {len(text)}자 > {MAX_CAPTION}")
    tags = re.findall(r"#\w+", text)
    if len(tags) > MAX_HASHTAGS:
        errors.append(f"해시태그 {len(tags)}개 > {MAX_HASHTAGS}")
    return errors


def load_packages():
    pkgs = []
    for f in sorted(APPROVED.glob("*.json")):
        try:
            pkgs.append((f, json.loads(f.read_text(encoding="utf-8"))))
        except json.JSONDecodeError as e:
            print(f"건너뜀 - {f.name}: JSON 오류 {e}")
    return pkgs


def dry_run(pkgs):
    ok = 0
    for f, pkg in pkgs:
        print(f"\n[{pkg.get('id', f.stem)}] {pkg.get('format')} {len(pkg.get('photos', []))}장 · 예정 {pkg.get('scheduled_at', '-')}")
        if pkg.get("media_id"):
            print(f"  이미 게시됨 — {pkg.get('permalink', pkg['media_id'])}")
            continue
        errors = validate(pkg)
        for e in errors:
            print(f"  ✗ {e}")
        if not errors:
            ok += 1
            print("  ✓ 검증 통과")
            print("  캡션 ↓\n    " + full_caption(pkg).replace("\n", "\n    "))
    print(f"\n게시 가능 {ok} / approved {len(pkgs)}")


def github_headers():
    token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def host_upload(path, name, gh):
    r = requests.put(f"{GITHUB_API}/repos/{HOST_REPO}/contents/{name}", headers=gh, timeout=60,
                     json={"message": f"add {name}", "content": base64.b64encode(path.read_bytes()).decode()})
    r.raise_for_status()
    body = r.json()
    return f"https://raw.githubusercontent.com/{HOST_REPO}/{body['commit']['sha']}/{name}", body["content"]["sha"]


def check_public(url):
    for _ in range(5):
        head = requests.head(url, timeout=15)
        if head.status_code == 200 and head.headers.get("content-type") == "image/jpeg":
            return
        time.sleep(2)
    raise RuntimeError(f"공개 URL 확인 실패 {url} ({head.status_code} {head.headers.get('content-type')})")


def host_delete(name, sha, gh):
    try:
        r = requests.delete(f"{GITHUB_API}/repos/{HOST_REPO}/contents/{name}", headers=gh, timeout=60,
                            json={"message": f"remove {name}", "sha": sha})
        ok, why = r.ok, r.status_code
    except requests.RequestException as e:
        ok, why = False, type(e).__name__
    if not ok:
        print(f"  경고 - 공개 저장소에서 {name} 삭제 실패({why}) — 수동 삭제 필요")


def api(method, path, **params):
    headers = {"Authorization": f"Bearer {os.environ['IG_ACCESS_TOKEN']}"}
    if method == "GET":
        r = requests.get(f"{GRAPH}/{path}", params=params, headers=headers, timeout=60)
    else:
        r = requests.post(f"{GRAPH}/{path}", json=params, headers=headers, timeout=60)
    body = r.json()
    if not r.ok or "error" in body:
        err = body.get("error", {})
        raise RuntimeError(f"Graph API {path}: {err.get('message', r.status_code)} "
                           f"(code {err.get('code')}/{err.get('error_subcode')})")
    return body


def wait_ready(container):
    # 문서 권장: 상태 조회는 최대 5분
    for _ in range(30):
        res = api("GET", container, fields="status_code,status")
        if res.get("status_code") == "FINISHED":
            return
        if res.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"컨테이너 {container} {res['status_code']}: {res.get('status')}")
        time.sleep(10)
    raise RuntimeError(f"컨테이너 {container} 5분 안에 준비되지 않음")


def save(f, pkg):
    f.write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def publish(f, pkg):
    ig = os.environ["IG_USER_ID"]
    gh = github_headers()
    stamp = int(time.time())
    hosted = []
    try:
        urls = []
        for i, p in enumerate(pkg["photos"], 1):
            name = f"{stamp}_{i:02d}.jpg"
            url, sha = host_upload(ROOT / p, name, gh)
            hosted.append((name, sha))
            check_public(url)
            urls.append(url)
        print(f"  공개 URL {len(urls)}개 준비")
        caption = full_caption(pkg)
        if len(urls) == 1:
            creation = api("POST", f"{ig}/media", image_url=urls[0], caption=caption)["id"]
        else:
            children = []
            for u in urls:
                child = api("POST", f"{ig}/media", image_url=u, is_carousel_item=True)["id"]
                wait_ready(child)
                children.append(child)
            creation = api("POST", f"{ig}/media", media_type="CAROUSEL",
                           children=",".join(children), caption=caption)["id"]
        wait_ready(creation)
        try:
            res = api("POST", f"{ig}/media_publish", creation_id=creation)
        except (requests.RequestException, RuntimeError, ValueError):
            print("  media_publish 응답 실패 — 실제 게시 여부 불확실. 인스타그램에서 확인하기 전에는 재실행 금지.")
            raise
        pkg.update(media_id=res["id"], status="published",
                   published_at=datetime.now(KST).isoformat(timespec="seconds"))
        save(f, pkg)
        if res.get("config_issue"):
            print(f"  경고 - 게시됐지만 config_issue={res['config_issue']} — 앱에서 캡션 확인")
        try:
            pkg["permalink"] = api("GET", res["id"], fields="permalink").get("permalink")
            save(f, pkg)
        except (requests.RequestException, RuntimeError, ValueError) as e:
            print(f"  게시는 완료, permalink 조회 실패: {e}")
        print(f"게시 완료 {pkg['id']} media_id={pkg['media_id']} {pkg.get('permalink', '')}")
    finally:
        for name, sha in hosted:
            host_delete(name, sha, gh)


def main():
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty():
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", metavar="ID", help="approved 패키지 하나를 실제로 게시(채팅 승인 후에만)")
    args = ap.parse_args()
    pkgs = load_packages()
    if not args.publish:
        if not pkgs:
            print("content/approved 에 패키지 없음 — 검토한 초안을 drafts에서 옮겨야 게시 대상이 된다.")
            return
        dry_run(pkgs)
        return

    match = [(f, p) for f, p in pkgs if p.get("id") == args.publish]
    if not match:
        sys.exit(f"approved에 id={args.publish} 패키지 없음")
    f, pkg = match[0]
    if pkg.get("media_id"):
        sys.exit(f"이미 게시됨 media_id={pkg['media_id']} — 중복 게시 거부")
    errors = validate(pkg)
    if errors:
        sys.exit("검증 실패:\n" + "\n".join(f"  ✗ {e}" for e in errors))
    load_dotenv(ROOT / ".env")
    missing = [k for k in ("IG_USER_ID", "IG_ACCESS_TOKEN") if not os.environ.get(k)]
    if missing:
        sys.exit(f".env에 {', '.join(missing)} 없음")
    try:
        publish(f, pkg)
    except (requests.RequestException, RuntimeError, KeyError, ValueError, subprocess.CalledProcessError) as e:
        sys.exit(f"게시 실패: {e}")


if __name__ == "__main__":
    main()
