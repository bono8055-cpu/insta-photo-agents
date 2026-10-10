# manifest에서 앨범·촬영일로 사진을 골라 번호 붙은 밀착 인화지(썸네일 격자)를 photos/sheets에 만드는 스크립트
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "photos" / "manifest.json"
OUT = ROOT / "photos" / "sheets"
COLS, ROWS, CELL, LABEL_H = 5, 4, 360, 28


def thumb(path):
    with Image.open(path) as img:
        img.draft("RGB", (CELL * 2, CELL * 2))
        img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((CELL, CELL))
    return img


def main():
    if not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--album", required=True)
    ap.add_argument("--date", required=True, help="촬영일 접두어, 예: 2026:07:25")
    args = ap.parse_args()

    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
    picked = sorted(
        (e for e in entries if e.get("album") == args.album and (e.get("taken_at") or "").startswith(args.date)),
        key=lambda e: e["taken_at"],
    )
    if not picked:
        sys.exit("조건에 맞는 사진 없음")
    OUT.mkdir(exist_ok=True)
    per = COLS * ROWS
    tag = args.date.replace(":", "")
    for n in range(0, len(picked), per):
        sheet = Image.new("RGB", (COLS * CELL, ROWS * (CELL + LABEL_H)), "white")
        draw = ImageDraw.Draw(sheet)
        for i, e in enumerate(picked[n:n + per]):
            x, y = (i % COLS) * CELL, (i // COLS) * (CELL + LABEL_H)
            t = thumb(ROOT / e["path"])
            sheet.paste(t, (x + (CELL - t.width) // 2, y + (CELL - t.height) // 2))
            label = f"{e['file'].split('_')[-1].split('.')[0]}  {e['taken_at'][11:16]}"
            draw.text((x + 6, y + CELL + 6), label, fill="black")
        dest = OUT / f"{tag}_{n // per + 1}.jpg"
        sheet.save(dest, quality=85)
        print(dest.relative_to(ROOT).as_posix(), len(picked[n:n + per]))


if __name__ == "__main__":
    main()
