# photos/inbox 이미지의 크기·촬영일·GPS 유무를 읽어 photos/manifest.json에 병합하는 스캐너
import json
import os
import sys
from pathlib import Path

from PIL import Image, UnidentifiedImageError

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "photos" / "inbox"
MANIFEST = ROOT / "photos" / "manifest.json"
SUPPORTED = {".jpg", ".jpeg", ".png"}
NEEDS_CONVERT = {".heic", ".heif"}

GPS_IFD = 0x8825
EXIF_IFD = 0x8769
DATETIME_ORIGINAL = 36867
DATETIME = 306


def read_meta(path):
    with Image.open(path) as img:
        exif = img.getexif()
        taken = exif.get_ifd(EXIF_IFD).get(DATETIME_ORIGINAL) or exif.get(DATETIME)
        return {
            "width": img.width,
            "height": img.height,
            "taken_at": taken,
            "has_gps": bool(exif.get_ifd(GPS_IFD)),
        }


def load_manifest():
    if not MANIFEST.exists():
        return []
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"manifest.json 파싱 실패, 덮어쓰지 않고 중단: {e}")


def main():
    # 파이프 출력은 로캘(CP949)로 인코딩되어 에이전트가 읽을 때 한글이 깨짐
    if not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    entries = {e["file"]: e for e in load_manifest()}
    added = updated = 0
    skipped = []

    for path in sorted(p for p in INBOX.rglob("*") if p.is_file()):
        ext = path.suffix.lower()
        if ext in NEEDS_CONVERT:
            skipped.append(f"{path.name}: HEIC는 JPG로 변환 필요")
            continue
        if ext not in SUPPORTED:
            continue
        try:
            meta = read_meta(path)
        except (UnidentifiedImageError, OSError) as e:
            skipped.append(f"{path.name}: 읽기 실패 ({e})")
            continue
        rel = path.relative_to(ROOT).as_posix()
        album = path.parent.relative_to(INBOX).as_posix()
        meta.update(path=rel, album="" if album == "." else album)
        known = entries.get(path.name, {}).get("path") or ""
        if known.startswith("photos/inbox/") and known != rel:
            skipped.append(f"{rel}: 같은 파일명이 이미 있음 ({known})")
            continue
        if path.name in entries:
            entries[path.name].update(meta)
            updated += 1
        else:
            entries[path.name] = {"file": path.name, **meta, "selected": False}
            added += 1

    tmp = MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(list(entries.values()), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, MANIFEST)

    print(f"추가 {added} / 갱신 {updated} / 전체 {len(entries)}")
    for s in skipped:
        print("건너뜀 -", s)


if __name__ == "__main__":
    main()
