"""sb-admin-2 결함 변이의 발현 확인 (개발계획서 8.1: 렌더링 결과로 확인한 것만 정답에 넣는다).

StepMeter 규칙 코드(worker/rules)를 쓰지 않고 DOM 측정값과 axe-core로 직접 잰다.
변이를 기준선과 같은 방법으로 재서, 결함이 변이에서만 나타나는지 본다.

준비: 기준선 패치만 적용한 앱과, 그 위에 변이 패치(mutations/sb-admin-2/{변이}.patch)를 적용한 앱을 각각 띄운다.
    python -m http.server 8766 --bind 127.0.0.1    # 기준선
    python -m http.server 8791 --bind 127.0.0.1    # small
    python -m benchmark.verify_sb_admin_2
결과: benchmark/evidence/sb-admin-2/verification.json, 스크린샷 (git 제외)
"""
from __future__ import annotations

import argparse
import asyncio
import json
from math import hypot
from pathlib import Path

from playwright.async_api import Page, async_playwright

ROOT = Path(__file__).resolve().parents[1]
AXE = ROOT / "node_modules" / "axe-core" / "axe.min.js"
OUTPUT = ROOT / "benchmark" / "evidence" / "sb-admin-2"

# 정답지(labels/sb-admin-2.json)의 target과 같은 선택자. 기준선과 변이에서 정확히 1개를 가리킨다
REMEMBER_ME = "#customCheck"
DEFAULT_PORTS = {"small": 8791}

# 체크박스를 실제로 누를 수 있는 영역: label 상자와, Bootstrap custom-checkbox가 그리는 label::before 상자의 합.
# 입력 요소 자체는 투명(opacity 0)하고 z-index -1이라 직접 눌리지 않는다.
HIT_AREA = """el => {
  const lab = document.querySelector(`label[for="${el.id}"]`);
  const L = lab.getBoundingClientRect(), s = getComputedStyle(lab, '::before');
  const b = {x: L.left + parseFloat(s.left), y: L.top + parseFloat(s.top),
             w: parseFloat(s.width), h: parseFloat(s.height)};
  const boxes = [b];
  if (L.width > 0 && L.height > 0) boxes.push({x: L.left, y: L.top, w: L.width, h: L.height});
  const x0 = Math.min(...boxes.map(r => r.x)), y0 = Math.min(...boxes.map(r => r.y));
  const x1 = Math.max(...boxes.map(r => r.x + r.w)), y1 = Math.max(...boxes.map(r => r.y + r.h));
  const others = [...document.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea')]
    .filter(o => o !== el && !lab.contains(o) && o.getClientRects().length)
    .map(o => { const r = o.getBoundingClientRect();
      return {tag: o.tagName.toLowerCase(), text: (o.innerText || o.placeholder || '').trim().slice(0, 30),
              x: r.left, y: r.top, w: r.width, h: r.height}; });
  return {hit: {x: x0, y: y0, w: x1 - x0, h: y1 - y0}, others};
}"""


async def axe_rules(page: Page, rules: list[str] | None = None) -> list[dict]:
    await page.add_script_tag(path=str(AXE))
    return await page.evaluate(
        """async rules => (await axe.run(document, rules ? {runOnly: {type: 'rule', values: rules}} : {})).violations
            .map(v => ({id: v.id, targets: v.nodes.map(n => n.target)}))""",
        rules,
    )


def gap_to_rect(cx: float, cy: float, r: dict) -> float:
    """중심점에서 사각형까지 가장 가까운 거리."""
    dx = max(r["x"] - cx, 0, cx - (r["x"] + r["w"]))
    dy = max(r["y"] - cy, 0, cy - (r["y"] + r["h"]))
    return hypot(dx, dy)


async def small(page: Page, origin: str) -> dict:
    """R01: 누를 수 있는 영역이 24px 미만이고, 중심에 그린 지름 24px 원이 다른 타겟과 겹친다 (WCAG 2.5.8 간격 예외 불충족)."""
    await page.goto(origin + "/login.html")
    m = await page.locator(REMEMBER_ME).evaluate(HIT_AREA)
    hit = m["hit"]
    cx, cy = hit["x"] + hit["w"] / 2, hit["y"] + hit["h"] / 2
    nearest = min(m["others"], key=lambda o: gap_to_rect(cx, cy, o))
    gap = gap_to_rect(cx, cy, nearest)
    size = min(hit["w"], hit["h"])
    # 글자를 눌러도 체크되는지 (참가자 체감 확인용, 판정에는 쓰지 않는다)
    await page.get_by_text("Remember Me", exact=True).click()
    text_click_checks = await page.locator(REMEMBER_ME).is_checked()
    name_ok = await page.get_by_role("checkbox", name="Remember Me").count() == 1
    return {
        "hit_area_px": {k: round(v, 2) for k, v in hit.items()},
        "size_px": round(size, 2),
        "nearest_target": {"tag": nearest["tag"], "text": nearest["text"]},
        "center_to_nearest_target_px": round(gap, 2),
        "text_click_checks_box": text_click_checks,
        "accessible_name_remember_me": name_ok,
        "axe_target_size": await axe_rules(page, ["target-size"]),
        "defect": size < 24 and gap < 12,
    }


CASES = {"small": ("R01", REMEMBER_ME, small)}


async def verify(baseline: str, variants: dict[str, str]) -> dict:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"kind": "sb-admin-2 variant verification, not StepMeter accuracy", "baseline": baseline, "cases": {}}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            for name, origin in variants.items():
                rule, target, measure = CASES[name]
                result = {"rule": rule, "target": target}
                for label, url in (("baseline", baseline), ("variant", origin)):
                    page = await browser.new_page(viewport={"width": 1280, "height": 800})
                    errors: list[str] = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    measured = await measure(page, url.rstrip("/"))
                    # 의도한 결함 말고 늘어난 위반이 없는지 보려고 전체 axe도 남긴다 (체크 전 상태로 다시 연다)
                    await page.goto(url.rstrip("/") + "/login.html")
                    measured["axe_all"] = await axe_rules(page)
                    result[label] = {**measured, "page_errors": errors}
                    await page.screenshot(path=str(OUTPUT / f"{name}-{label}.png"))
                    await page.close()
                result["manifested"] = result["variant"]["defect"] and not result["baseline"]["defect"]
                report["cases"][name] = result
                print(f"{name} ({rule}): {'발현' if result['manifested'] else '미발현'}")
        finally:
            await browser.close()
    (OUTPUT / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", default="http://127.0.0.1:8766")
    parser.add_argument("--variant", action="append", default=[], help="name=origin, 여러 번")
    args = parser.parse_args()
    variants = dict(v.split("=", 1) for v in args.variant) or {
        name: f"http://127.0.0.1:{port}" for name, port in DEFAULT_PORTS.items()}
    asyncio.run(verify(args.baseline, variants))


if __name__ == "__main__":
    main()
