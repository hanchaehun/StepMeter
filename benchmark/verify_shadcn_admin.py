"""shadcn-admin 결함 변이 6종의 발현 확인 (개발계획서 8.1: 렌더링 결과로 확인한 것만 정답에 넣는다).

StepMeter 규칙 코드(worker/rules)를 쓰지 않고 DOM 측정값과 axe-core로 직접 잰다.
각 변이를 기준선과 같은 방법으로 재서, 결함이 변이에서만 나타나는지 본다.

준비 (selection.md "shadcn-admin 클리닝"): 기준선과 변이별 빌드를 vite preview로 띄운다.
    python -m benchmark.verify_shadcn_admin                # 기본 포트: 기준선 8772, 변이 8781~8786
    python -m benchmark.verify_shadcn_admin --baseline http://127.0.0.1:8772 --variant small=http://127.0.0.1:8781
결과: benchmark/evidence/shadcn-admin/verification.json, 스크린샷 (git 제외)
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
OUTPUT = ROOT / "benchmark" / "evidence" / "shadcn-admin"

# 정답지(labels/shadcn-admin.json)의 target과 같은 표준 CSS 선택자. 기준선에서 정확히 1개를 가리킨다
INVITE_USER = "main button:has(svg.lucide-mail-plus)"
ADD_USER = "main button:has(svg.lucide-user-plus)"
EDIT_ITEM = '[role="menu"] > [role="menuitem"]:first-child'
INVITE_SUBMIT = 'button[form="user-invite-form"]'
STATUS_FILTER = 'button[data-slot="popover-trigger"]:first-of-type'  # Status·Priority 형제 중 첫째
ROW_MENU = 'tbody tr:first-child button[data-slot="dropdown-menu-trigger"]'
TOAST = "You submitted the following values:"
DEFAULT_PORTS = {"small": 8781, "contrast": 8782, "inert": 8783, "overlay": 8784, "below-fold": 8785, "unnamed": 8786}


async def axe_on(page: Page, selector: str, rule: str) -> list[dict]:
    """selector 요소 하나에만 axe 규칙 하나를 돌린다."""
    await page.add_script_tag(path=str(AXE))
    return await page.locator(selector).evaluate(
        """async (el, rule) => (await axe.run(el, {runOnly: {type: 'rule', values: [rule]}})).violations
            .flatMap(v => v.nodes.map(n => ({target: n.target, data: (n.any[0] || {}).data || null})))""",
        rule,
    )


async def open_invite(page: Page, origin: str) -> None:
    await page.goto(origin + "/users")
    await page.locator(INVITE_USER).click()
    await page.get_by_label("Email").fill("kim@example.com")
    await page.get_by_role("combobox").click()
    await page.get_by_role("option").first.click()


async def small(page: Page, origin: str) -> dict:
    """R01: 대상이 24px 미만이고 가까운 타겟과 중심 거리 24px 미만 (WCAG 2.5.8 간격 예외 불충족)."""
    await page.goto(origin + "/users")
    a, b = await page.locator(INVITE_USER).bounding_box(), await page.locator(ADD_USER).bounding_box()
    distance = hypot(a["x"] + a["width"] / 2 - b["x"] - b["width"] / 2, a["y"] + a["height"] / 2 - b["y"] - b["height"] / 2)
    size = min(a["width"], a["height"])
    return {"size_px": size, "center_distance_px": round(distance, 2), "defect": size < 24 and distance < 24}


async def contrast(page: Page, origin: str) -> dict:
    """R02: axe color-contrast 위반과 대비비."""
    await page.goto(origin + "/tasks")
    await page.locator(ROW_MENU).click()
    await page.locator(EDIT_ITEM).wait_for()
    nodes = await axe_on(page, EDIT_ITEM, "color-contrast")
    ratio = nodes[0]["data"]["contrastRatio"] if nodes else None
    return {"text": await page.locator(EDIT_ITEM).inner_text(), "axe_violation": bool(nodes), "contrast_ratio": ratio,
            "defect": bool(nodes)}


async def inert(page: Page, origin: str) -> dict:
    """R03: 유효한 입력 뒤 제출을 눌러도 3초 안에 결과(알림)가 없고 대화상자가 그대로."""
    await open_invite(page, origin)
    await page.locator(INVITE_SUBMIT).click()
    await page.wait_for_timeout(3000)
    toast = await page.get_by_text(TOAST).count()
    dialog_open = await page.get_by_role("dialog").count() > 0
    return {"toast_count": toast, "dialog_still_open": dialog_open, "defect": toast == 0 and dialog_open}


async def overlay(page: Page, origin: str) -> dict:
    """R04: 대상 중심점의 최상단 요소가 대상(또는 그 안쪽)이 아니다. 실제로 그 점을 눌러 열리는지도 본다."""
    await page.goto(origin + "/tasks")
    target = page.locator(STATUS_FILTER)
    box = await target.bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    hit = await target.evaluate(
        """(el, [x, y]) => { const h = document.elementFromPoint(x, y);
            return {covered: !el.contains(h), hit: h.tagName.toLowerCase() + '.' + [...h.classList].slice(0, 4).join('.')} }""",
        [cx, cy],
    )
    await page.mouse.click(cx, cy)
    await page.wait_for_timeout(500)
    opened = await page.locator('[data-slot="popover-content"]').count() > 0
    return {**hit, "click_at_center_opened_filter": opened, "defect": hit["covered"]}


async def below_fold(page: Page, origin: str) -> dict:
    """R06: 과업 2의 첫 클릭 대상이 로드 때 1280×800 첫 화면 밖."""
    await page.goto(origin + "/users")
    await page.wait_for_timeout(500)
    rect = await page.locator(INVITE_USER).evaluate(
        "el => { const r = el.getBoundingClientRect(); return {top: r.top, bottom: r.bottom, vh: innerHeight, sy: scrollY} }")
    in_view = rect["top"] >= 0 and rect["bottom"] <= rect["vh"]
    return {"top_px": rect["top"], "viewport_height": rect["vh"], "in_first_view": in_view,
            "scroll_needed_px": max(0, rect["bottom"] - rect["vh"]), "defect": not in_view}


async def unnamed(page: Page, origin: str) -> dict:
    """R10: axe button-name 위반."""
    await page.goto(origin + "/tasks")
    nodes = await axe_on(page, ROW_MENU, "button-name")
    return {"axe_violation": bool(nodes), "defect": bool(nodes)}


CASES = {"small": ("R01", INVITE_USER, small), "contrast": ("R02", EDIT_ITEM, contrast),
         "inert": ("R03", INVITE_SUBMIT, inert), "overlay": ("R04", STATUS_FILTER, overlay),
         "below-fold": ("R06", INVITE_USER, below_fold), "unnamed": ("R10", ROW_MENU, unnamed)}


async def verify(baseline: str, variants: dict[str, str]) -> dict:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"kind": "shadcn-admin variant verification, not StepMeter accuracy", "baseline": baseline, "cases": {}}
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
                    result[label] = {**await measure(page, url.rstrip("/")), "page_errors": errors}
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
    parser.add_argument("--baseline", default="http://127.0.0.1:8772")
    parser.add_argument("--variant", action="append", default=[], help="name=origin, 여러 번")
    args = parser.parse_args()
    variants = dict(v.split("=", 1) for v in args.variant) or {
        name: f"http://127.0.0.1:{port}" for name, port in DEFAULT_PORTS.items()}
    asyncio.run(verify(args.baseline, variants))


if __name__ == "__main__":
    main()
