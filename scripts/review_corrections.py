# 키스톤·회전 보정본과 톤 프리셋 결과의 검수 결과(승인/거절)를 manifest에 기록하고 남은 검수 대기 목록을 보여주는 스크립트
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "photos" / "manifest.json"


def main():
    if not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--approve", nargs="*", default=[], help="승인할 파일명 일부(예: R0008790)")
    ap.add_argument("--reject", nargs="*", default=[], help="거절할 파일명 일부 → 원본 사용")
    ap.add_argument("--stage", choices=["correction", "grade"], default="correction")
    ap.add_argument("--approve-pending", action="store_true", help="이 단계의 검수 대기를 모두 승인")
    args = ap.parse_args()
    if set(args.approve) & set(args.reject):
        sys.exit("같은 사진을 승인과 거절에 동시에 넣을 수 없음")

    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
    applied = [e for e in entries if "review" in e.get(args.stage, {})]
    for key, verdict in [(k, "approved") for k in args.approve] + [(k, "rejected") for k in args.reject]:
        hits = [e for e in applied if key in e["file"]]
        if len(hits) != 1:
            sys.exit(f"'{key}'에 맞는 검수 대상이 {len(hits)}개 — 하나만 맞도록 지정할 것")
        hits[0][args.stage]["review"] = verdict
        print(f"{hits[0]['file']}: {verdict}")
    if args.approve_pending:
        for e in applied:
            if e[args.stage]["review"] == "pending":
                e[args.stage]["review"] = "approved"
                print(f"{e['file']}: approved")

    tmp = MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, MANIFEST)

    pending = [e["file"] for e in applied if e[args.stage].get("review") == "pending"]
    print(f"{args.stage} 검수 대기 {len(pending)}")
    for f in pending:
        print(" -", f)


if __name__ == "__main__":
    main()
