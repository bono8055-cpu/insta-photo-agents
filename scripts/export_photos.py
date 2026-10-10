# photos/selected 사진(검수 승인된 톤·보정본 우선)을 Graph API 규격(비율 4:5~1.91:1, 폭 1080, sRGB JPEG, EXIF 제거)으로 photos/export에 내보내는 스크립트
import io
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "photos" / "selected"
OUT = ROOT / "photos" / "export"
CORRECTED = ROOT / "photos" / "corrected"
# 뒤 단계일수록 우선: 톤 승인본 > 보정 승인본 > selected 원본
STAGES = {"correction": CORRECTED, "grade": ROOT / "photos" / "graded"}
MANIFEST = ROOT / "photos" / "manifest.json"
SUPPORTED = {".jpg", ".jpeg", ".png"}
MIN_RATIO = 4 / 5
MAX_RATIO = 1.91
TARGET_WIDTH = 1080
MIN_WIDTH = 320
SRGB = ImageCms.createProfile("sRGB")


def to_srgb(img):
    icc = img.info.get("icc_profile")
    if icc and img.mode in ("RGB", "CMYK"):
        return ImageCms.profileToProfile(
            img, ImageCms.ImageCmsProfile(io.BytesIO(icc)), SRGB, outputMode="RGB"
        )
    return img.convert("RGB")


def crop_to_range(img):
    w, h = img.size
    ratio = w / h
    if ratio < MIN_RATIO:
        new_h = math.floor(w / MIN_RATIO)
        top = (h - new_h) // 2
        return img.crop((0, top, w, top + new_h))
    if ratio > MAX_RATIO:
        new_w = math.floor(h * MAX_RATIO)
        left = (w - new_w) // 2
        return img.crop((left, 0, left + new_w, h))
    return img


def export(path):
    with Image.open(path) as src:
        img = ImageOps.exif_transpose(src)
        img = to_srgb(img)
    img = crop_to_range(img)
    if img.width < MIN_WIDTH:
        raise ValueError(f"폭 {img.width}px < {MIN_WIDTH}px")
    if img.width > TARGET_WIDTH:
        new_h = round(img.height * TARGET_WIDTH / img.width)
        # 반올림으로 비율이 API 허용 범위를 1px 벗어나는 것을 막음
        new_h = min(max(new_h, math.ceil(TARGET_WIDTH / MAX_RATIO)), math.floor(TARGET_WIDTH / MIN_RATIO))
        img = img.resize((TARGET_WIDTH, new_h), Image.LANCZOS)
    dest = OUT / f"{path.stem}.jpg"
    img.save(dest, "JPEG", quality=90, optimize=True)
    return dest, img.size


def main():
    # 파이프 출력은 로캘(CP949)로 인코딩되어 에이전트가 읽을 때 한글이 깨짐
    if not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8")
    reviews = {}
    if MANIFEST.exists():
        reviews = {e["file"]: {s: e.get(s, {}).get("review") for s in STAGES}
                   for e in json.loads(MANIFEST.read_text(encoding="utf-8"))}
    photos = [p for p in sorted(SRC.iterdir()) if p.suffix.lower() in SUPPORTED]
    pending = [f"{p.name} ({s})" for p in photos for s in STAGES
               if reviews.get(p.name, {}).get(s) == "pending"]
    if pending:
        print("검수 대기 중이라 내보내지 않음 — review_corrections.py --stage로 승인/거절 후 다시 실행:")
        for name in pending:
            print(" -", name)
        sys.exit(1)

    OUT.mkdir(exist_ok=True)
    done = 0
    for path in photos:
        source = path
        for stage in reversed(STAGES):
            if reviews.get(path.name, {}).get(stage) == "approved":
                source = STAGES[stage] / f"{path.stem}.jpg"
                break
        if not source.exists():
            print(f"건너뜀 - {path.name}: 승인된 결과 파일 없음 ({source.relative_to(ROOT).as_posix()})")
            continue
        try:
            dest, (w, h) = export(source)
        except (UnidentifiedImageError, OSError, ValueError, ImageCms.PyCMSError) as e:
            print(f"건너뜀 - {path.name}: {e}")
            continue
        done += 1
        print(f"{path.name} -> {dest.name} ({w}x{h})")
    print(f"내보냄 {done}")


if __name__ == "__main__":
    main()
