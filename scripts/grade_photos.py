# 시리즈 단위로 톤 프리셋(warm-film / calm-neutral)을 입혀 photos/graded에 저장하고 검수 대기로 기록하는 스크립트
import argparse
import json
import math
import os
import sys
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from export_photos import to_srgb

ROOT = Path(__file__).resolve().parent.parent
SELECTED = ROOT / "photos" / "selected"
CORRECTED = ROOT / "photos" / "corrected"
OUT = ROOT / "photos" / "graded"
MANIFEST = ROOT / "photos" / "manifest.json"
SHEETS = ROOT / "photos" / "sheets"
# export가 폭 1080으로 줄이므로 원본 해상도 대신 이 크기에서 처리해 메모리를 아낀다
MAX_SIDE = 2400


def luminance(a):
    return a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def warm_film(a, seed):
    a = a * np.array([1.06, 1.01, 0.90], dtype=np.float32)
    a = 0.05 + 0.92 * a
    lum = luminance(a)[..., None]
    cream = np.array([1.0, 0.97, 0.88], dtype=np.float32)
    a = a + (cream - a) * 0.15 * np.clip(lum, 0, 1) ** 2
    lum = luminance(a)[..., None]
    a = lum + (a - lum) * 0.82
    grain = np.random.default_rng(seed).normal(0, 0.012, a.shape[:2]).astype(np.float32)[..., None]
    return a + grain


def calm_neutral(a, seed):
    means = a.reshape(-1, 3).mean(0)
    gains = np.clip(1 + (means.mean() / means - 1) * 0.5, 0.9, 1.1)
    a = a * gains
    lum = luminance(a)[..., None]
    sat = (a.max(-1) - a.min(-1))[..., None]
    a = lum + (a - lum) * np.clip(0.85 + 0.25 * sat, 0, 1.05)
    return np.clip(a, 0, 1) ** 1.05


PRESETS = {"warm-film": warm_film, "calm-neutral": calm_neutral}


def grade(img, preset, name):
    a = np.asarray(img, dtype=np.float32) / 255
    out = PRESETS[preset](a, zlib.crc32(name.encode()))
    return Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8))


def source_for(e):
    review = e.get("correction", {}).get("review")
    if review == "pending":
        return None
    if review == "approved":
        return CORRECTED / f"{Path(e['file']).stem}.jpg"
    return SELECTED / e["file"]


def preview(series, pairs):
    cell = 280
    cols = 4
    rows = math.ceil(len(pairs) / 2)
    sheet = Image.new("RGB", (cell * cols, (cell + 22) * rows), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (name, before, after) in enumerate(pairs):
        x0, y0 = (i % 2) * cell * 2, (i // 2) * (cell + 22)
        for j, im in enumerate((before, after)):
            t = im.copy()
            t.thumbnail((cell - 8, cell - 8))
            sheet.paste(t, (x0 + j * cell + (cell - t.width) // 2, y0 + (cell - t.height) // 2))
        draw.text((x0 + 6, y0 + cell + 4), f"{name}  before | after", fill="black")
    SHEETS.mkdir(exist_ok=True)
    dest = SHEETS / f"grade_{series}.jpg"
    sheet.save(dest, quality=88)
    return dest


def main():
    if not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", required=True)
    ap.add_argument("--preset", required=True, choices=sorted(PRESETS))
    args = ap.parse_args()

    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
    targets = sorted((e for e in entries if e.get("series") == args.series and e.get("selected")),
                     key=lambda e: e.get("series_order", 0))
    if not targets:
        sys.exit(f"시리즈 '{args.series}'에 선별된 사진 없음")

    OUT.mkdir(exist_ok=True)
    pairs = []
    for e in targets:
        if e.get("grade", {}).get("review") in ("approved", "rejected"):
            print(e["file"], f"톤 검수 완료({e['grade']['review']}) — 유지")
            continue
        src = source_for(e)
        if src is None:
            print(e["file"], "키스톤·회전 보정 검수 대기 — 톤 단계로 넘기지 않음")
            continue
        if not src.exists():
            print(e["file"], f"원본 없음({src.relative_to(ROOT).as_posix()})")
            continue
        with Image.open(src) as im:
            img = to_srgb(ImageOps.exif_transpose(im))
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        out = grade(img, args.preset, e["file"])
        out.save(OUT / f"{Path(e['file']).stem}.jpg", quality=95)
        e["grade"] = {"preset": args.preset, "review": "pending"}
        pairs.append((e["file"].split("_")[-1].rsplit(".", 1)[0], img, out))
        print(e["file"], f"{args.preset} 적용 ← {src.parent.name}")

    tmp = MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, MANIFEST)
    if pairs:
        print("미리보기:", preview(args.series, pairs).relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
