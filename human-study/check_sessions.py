"""세션 직후 한 참가자의 수집 파일 6개를 검사한다 (session-procedure.md "세션 뒤").

    python human-study/check_sessions.py P01
    python human-study/check_sessions.py P01 --dir data/human

오류(종료 코드 1): 페이지 빠짐·중복, 스키마 오류, *.invalid.json, 뷰포트가 1280×800이 아님, 이벤트 없음, 시각 역행.
경고(종료 코드 0): 3분 넘은 페이지, 대상이 null인 클릭. 본문 글자를 누른 클릭도 null이라 경고만 한다.
읽기만 하고 파일을 고치거나 지우지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import validate_session  # noqa: E402

DEFAULT_DIR = ROOT / "data" / "human"
VARIANTS = ROOT / "benchmark" / "variants.json"
VIEWPORT = {"width": 1280, "height": 800}
PAGE_LIMIT_MS = 3 * 60 * 1000  # session-procedure.md: 페이지당 3분


def expected_pages() -> list[str]:
    return [p["page_id"] for p in json.loads(VARIANTS.read_text(encoding="utf-8"))["pages"]]


def check_file(data: dict) -> tuple[list[str], list[str]]:
    """(오류, 경고)."""
    errors = list(validate_session(data))
    warnings: list[str] = []
    if data.get("viewport") != VIEWPORT:
        errors.append(f"뷰포트 {data.get('viewport')} (기대 1280×800)")
    events = data.get("events") or []
    if not events:
        errors.append("이벤트 없음")
        return errors, warnings
    times = [e.get("t_ms", 0) for e in events]
    if any(a > b for a, b in zip(times, times[1:])):
        errors.append("t_ms가 거꾸로 가는 이벤트가 있음")
    if times[-1] > PAGE_LIMIT_MS:
        warnings.append(f"{times[-1] / 1000:.0f}초 걸림 (3분 제한)")
    null_clicks = [e for e in events if e.get("type") == "click" and e.get("target_key") is None]
    if null_clicks:
        where = ", ".join(f"({e['x']}, {e['y']})" for e in null_clicks[:5])
        warnings.append(f"대상이 null인 클릭 {len(null_clicks)}개: {where} — 과업 대상을 누른 것이면 수집 스크립트 담당에게 알린다")
    return errors, warnings


def check_participant(code: str, folder: Path) -> tuple[list[str], list[str], list[dict]]:
    """(오류, 경고, 페이지별 요약)."""
    errors: list[str] = []
    warnings: list[str] = []
    rows: list[dict] = []
    invalid = sorted(folder.glob(f"human-session-{code}-*.invalid.json"))
    for f in invalid:
        errors.append(f"{f.name}: 스키마 검증에 실패해 따로 저장된 파일")
    found: dict[str, list[tuple[Path, dict]]] = {}
    for f in sorted(folder.glob(f"human-session-{code}-*.json")):
        if f.name.endswith(".invalid.json"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("participant_code") != code:
            continue
        found.setdefault(data.get("page_id"), []).append((f, data))
    pages = expected_pages()
    for page in pages:
        if page not in found:
            errors.append(f"{page}: 파일 없음")
        elif len(found[page]) > 1:
            errors.append(f"{page}: 파일 {len(found[page])}개 ({', '.join(f.name for f, _ in found[page])})")
    for page in sorted(set(found) - set(pages), key=str):
        errors.append(f"{page}: 6페이지 목록(benchmark/variants.json)에 없는 page_id")
    for page in pages:
        for f, data in found.get(page, []):
            e, w = check_file(data)
            errors += [f"{page}: {m}" for m in e]
            warnings += [f"{page}: {m}" for m in w]
            last = data["events"][-1]["t_ms"] if data.get("events") else 0
            rows.append({"page_id": page, "completed": data.get("completed"), "seconds": round(last / 1000),
                         "clicks": sum(1 for ev in data.get("events", []) if ev.get("type") == "click")})
    return errors, warnings, rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("participant", help="참가자 코드, 예: P01")
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help=f"수집 폴더 (기본 {DEFAULT_DIR})")
    args = parser.parse_args(argv)
    errors, warnings, rows = check_participant(args.participant, args.dir)
    for r in rows:
        done = "완료" if r["completed"] else "미완료"
        print(f"  {r['page_id']:<40} {done:<4} {r['seconds']:>4}초  클릭 {r['clicks']}")
    if rows:
        print(f"  6페이지 합계 {sum(r['seconds'] for r in rows) / 60:.1f}분 (동의서·안내 시간 제외)")
    for w in warnings:
        print(f"경고: {w}")
    for e in errors:
        print(f"오류: {e}")
    print("정상" if not errors else f"오류 {len(errors)}건 — 파일을 지우지 말고 수집 스크립트 담당에게 알린다")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
