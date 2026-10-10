# photos/selected 사진의 세로선을 검출해 회전·수직 키스톤을 자동 보정하고 photos/corrected에 저장하는 스크립트
import argparse
import json
import math
import os
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "photos" / "selected"
OUT = ROOT / "photos" / "corrected"
MANIFEST = ROOT / "photos" / "manifest.json"
PREVIEW = ROOT / "photos" / "sheets" / "corrected_preview.jpg"
SUPPORTED = {".jpg", ".jpeg", ".png"}

MIN_LINES = 6
MAX_RESIDUAL = 2.5
MAX_ROTATE = 6.0
MAX_KEYSTONE = 12.0
MIN_ROTATE = 0.3
MIN_KEYSTONE = 0.8


def detect(img):
    """세로선 각도를 가로 위치에 회귀해 (회전각, 좌우 수렴각)을 추정. 실패 시 사유 문자열."""
    small = img.copy()
    small.thumbnail((1000, 1000))
    g = cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2GRAY)
    h, w = g.shape
    lines = cv2.HoughLinesP(cv2.Canny(g, 60, 160), 1, np.pi / 360, 80, minLineLength=h // 8, maxLineGap=8)
    segs = []
    for x1, y1, x2, y2 in (lines.reshape(-1, 4) if lines is not None else []):
        if y2 < y1:
            x1, y1, x2, y2 = x2, y2, x1, y1
        ang = math.degrees(math.atan2(x2 - x1, y2 - y1))
        if abs(ang) < 20:
            segs.append(((x1 + x2) / 2 / w - 0.5, ang, math.hypot(x2 - x1, y2 - y1)))
    if len(segs) < MIN_LINES:
        return f"세로선 부족({len(segs)})"
    x, ang, wt = map(np.array, zip(*segs))
    if not ((x < -0.1).any() and (x > 0.1).any()):
        return "세로선이 한쪽에 몰림"
    sw = np.sqrt(wt)
    (rot, conv), *_ = np.linalg.lstsq(np.c_[np.ones_like(x), x] * sw[:, None], ang * sw, rcond=None)
    resid = math.sqrt(np.average((ang - rot - conv * x) ** 2, weights=wt))
    if resid > MAX_RESIDUAL:
        return f"선 방향 불일치(잔차 {resid:.1f}°)"
    if abs(rot) > MAX_ROTATE or abs(conv) > MAX_KEYSTONE:
        return f"보정량 과다(회전 {rot:+.1f}°, 수렴 {conv:+.1f}°)"
    return float(rot), float(conv)


def homography(w, h, rot, conv):
    # rot>0 은 선의 아래쪽이 오른쪽으로 기운 상태 → 시계 방향(cv2 기준 음수)으로 돌려 세운다
    r = np.vstack([cv2.getRotationMatrix2D((w / 2, h / 2), -rot, 1.0), [0, 0, 1]])
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([
        [h * math.tan(math.radians(-conv / 2)), 0],
        [w + h * math.tan(math.radians(conv / 2)), 0],
        [w, h],
        [0, h],
    ])
    return cv2.getPerspectiveTransform(src, dst) @ r


def inner_rect(m, w, h):
    corners = cv2.perspectiveTransform(np.float32([[[0, 0], [w, 0], [w, h], [0, h]]]), m)[0]
    (tlx, tly), (trx, try_), (brx, bry), (blx, bly) = corners
    left, right = max(tlx, blx, 0), min(trx, brx, w)
    top, bottom = max(tly, try_, 0), min(bly, bry, h)
    return int(math.ceil(left)), int(math.ceil(top)), int(right), int(bottom)


def correct(img, rot, conv):
    w, h = img.size
    m = homography(w, h, rot, conv)
    warped = cv2.warpPerspective(np.asarray(img), m, (w, h), flags=cv2.INTER_LANCZOS4)
    return Image.fromarray(warped).crop(inner_rect(m, w, h))


def load_manifest():
    return {e["file"]: e for e in json.loads(MANIFEST.read_text(encoding="utf-8"))} if MANIFEST.exists() else {}


def save_manifest(entries):
    tmp = MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(list(entries.values()), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, MANIFEST)


def preview(pairs):
    cell = 300
    sheet = Image.new("RGB", (cell * 2 * 2, (cell + 24) * math.ceil(len(pairs) / 2)), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (name, before, after) in enumerate(pairs):
        x0, y0 = (i % 2) * cell * 2, (i // 2) * (cell + 24)
        for j, im in enumerate((before, after)):
            t = im.copy()
            t.thumbnail((cell - 8, cell - 8))
            sheet.paste(t, (x0 + j * cell + (cell - t.width) // 2, y0 + (cell - t.height) // 2))
        draw.text((x0 + 6, y0 + cell + 4), f"{name}  before | after", fill="black")
    PREVIEW.parent.mkdir(exist_ok=True)
    sheet.save(PREVIEW, quality=85)


def main():
    if not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip", nargs="*", default=[], help="보정하지 않을 파일명 일부(예: R0008764)")
    args = ap.parse_args()

    entries = load_manifest()
    OUT.mkdir(exist_ok=True)
    pairs = []
    for path in sorted(SRC.iterdir()):
        if path.suffix.lower() not in SUPPORTED:
            continue
        review = entries.get(path.name, {}).get("correction", {}).get("review")
        if review in ("approved", "rejected"):
            print(path.name, f"검수 완료({review}) — 유지")
            continue
        with Image.open(path) as src:
            icc = src.info.get("icc_profile")
            img = ImageOps.exif_transpose(src).convert("RGB")
        if any(s in path.name for s in args.skip):
            result = "수동 제외"
        else:
            result = detect(img)
        dest = OUT / f"{path.stem}.jpg"
        if isinstance(result, str):
            status = {"status": "skipped", "reason": result}
            dest.unlink(missing_ok=True)
        elif abs(result[0]) < MIN_ROTATE and abs(result[1]) < MIN_KEYSTONE:
            status = {"status": "none", "rotate": round(result[0], 2), "keystone": round(result[1], 2)}
            dest.unlink(missing_ok=True)
        else:
            fixed = correct(img, *result)
            fixed.save(dest, quality=95, icc_profile=icc)
            pairs.append((path.stem.split("_")[-1], img, fixed))
            status = {"status": "applied", "rotate": round(result[0], 2), "keystone": round(result[1], 2),
                      "review": "pending"}
        if path.name in entries:
            entries[path.name]["correction"] = status
        print(path.name, status)

    if entries:
        save_manifest(entries)
    if pairs:
        preview(pairs)
        print("미리보기:", PREVIEW.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
