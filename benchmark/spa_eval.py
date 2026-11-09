"""SPA collector evaluation against independently reviewed, exhaustive state labels.

Only trusted, loopback-hosted test applications are allowed. This is a collector
and numeric snapshot-click adapter, not the unimplemented production agent loop.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import ipaddress
import json
import math
from pathlib import Path
import statistics
import time
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
COVERAGE = {"cookie_modal", "fixed_header", "virtual_scroll", "open_shadow", "same_origin_iframe"}


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def near_box(left, right, tolerance=2):
    return all(abs(left[k] - right[k]) <= tolerance for k in ("x", "y", "width", "height"))


def evaluate_state(truth, observed, tolerance=2):
    """One-to-one geometry matching, independent of names/roles under evaluation.

    Ambiguous collisions are unresolved, never greedily credited as correct.
    Labels marked excluded are negative controls, not recall denominators.
    Occluded targets are valid raw collector entries, not contamination.
    """
    expected = [t for t in truth if t.get("include", True)]
    candidates = {t["key"]: [i for i, o in enumerate(observed)
                                  if t.get("bbox") and near_box(t["bbox"], o["bbox"], tolerance)]
                  for t in expected}
    owners = Counter(i for indices in candidates.values() for i in indices)
    matches = {key: indices[0] for key, indices in candidates.items()
               if len(indices) == 1 and owners[indices[0]] == 1}
    matched = set(matches.values())
    ambiguities = [key for key, indices in candidates.items()
                   if indices and (len(indices) != 1 or owners[indices[0]] != 1)]
    mismatches = []
    for target in expected:
        if target["key"] in matches:
            item = observed[matches[target["key"]]]
            for field in ("name", "role", "occluded"):
                if field in target and item.get(field) != target[field]:
                    mismatches.append({"key": target["key"], "field": field,
                                       "expected": target[field], "actual": item.get(field)})
    missing = [t["key"] for t in expected if t["key"] not in matches]
    extras = [o["el_id"] for i, o in enumerate(observed) if i not in matched]
    omission = ratio(len(missing), len(expected))
    contamination = ratio(len(extras), len(observed))
    filtered = [o for o in observed if not o["occluded"]]
    return {"expected": len(expected), "observed": len(observed), "matched": len(matches),
            "omitted": missing, "unmatched_observed_ids": extras, "ambiguous": ambiguities,
            "omission_rate": omission, "contamination_rate": contamination,
            "name_role_occlusion_mismatches": mismatches,
            "raw_ids": [o["el_id"] for o in observed],
            "unoccluded_ids": [o["el_id"] for o in filtered],
            "capped_30_ids": [o["el_id"] for o in filtered[:30]],
            "cap_excluded_count": max(0, len(filtered) - 30),
            "matches": {key: observed[index]["el_id"] for key, index in matches.items()},
            "thresholds_pass": omission is not None and omission <= .10
                and contamination is not None and contamination <= .05 and not ambiguities}


def validate_manifest(manifest):
    if manifest.get("version") != 1:
        raise ValueError("unsupported manifest version")
    app = manifest.get("app", {})
    if app.get("kind") not in {"synthetic", "benchmark", "teammate"} or not app.get("id") or not app.get("revision"):
        raise ValueError("app id, revision and kind are required")
    review = manifest.get("ground_truth_review", {})
    if review.get("status") not in {"pending", "approved"}:
        raise ValueError("ground_truth_review status must be pending or approved")
    if review["status"] == "approved" and not (review.get("reviewer") and review.get("date")):
        raise ValueError("approved truth requires reviewer and date")
    viewport = manifest.get("viewport", {})
    if any(type(viewport.get(k)) is not int or viewport[k] <= 0 for k in ("width", "height")):
        raise ValueError("positive integer viewport required")
    scenarios = manifest.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("at least one labeled scenario required")
    ids = []
    for scenario in scenarios:
        ids.append(scenario["id"])
        if not scenario["id"].replace("-", "").replace("_", "").isalnum():
            raise ValueError("scenario id must be filename-safe")
        if scenario.get("exhaustive") is not True or not scenario.get("truth"):
            raise ValueError("each scenario needs exhaustive independently authored truth")
        if not set(scenario.get("coverage", [])) <= COVERAGE:
            raise ValueError("unknown coverage label")
        keys = [t["key"] for t in scenario["truth"]]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate truth key")
        for t in scenario["truth"]:
            if not t.get("selector") or "name" not in t or "role" not in t:
                raise ValueError("truth needs selector, expected name and role")
        if not set(scenario.get("clicks", [])) <= set(keys):
            raise ValueError("clicks must refer to truth keys")
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate scenario id")


def local_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise ValueError("only credential-free loopback HTTP(S) test URLs are allowed")
    try:
        local = ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        local = parsed.hostname == "localhost"
    if not local:
        raise ValueError("only loopback test apps are allowed; no production actions")
    return url


def locator_for(page, spec):
    root = page.frame_locator(spec["frame"]) if spec.get("frame") else page
    return root.locator(spec["selector"])


async def setup_state(page, base_url, scenario):
    from worker.collect.collector import record_first_view
    await page.goto(local_url(urljoin(base_url, scenario["path"])), wait_until="load")
    await record_first_view(page)
    await apply_steps(page, scenario.get("setup", []))
    if scenario.get("ready"):
        await locator_for(page, scenario["ready"]).wait_for(state="visible")


async def apply_steps(page, steps):
    for step in steps:
        action = step["action"]
        if action == "scroll":
            await locator_for(page, step).evaluate("(el, top) => { el.scrollTop = top; }", step["top"])
        elif action == "window_scroll":
            await page.evaluate("([x,y]) => window.scrollTo(x,y)", [step.get("x", 0), step["y"]])
        elif action == "click":
            await locator_for(page, step).click()
        elif action == "fill":
            await locator_for(page, step).fill(step["value"])
        elif action == "press":
            await locator_for(page, step).press(step["key"])
        elif action == "wait_visible":
            await locator_for(page, step).wait_for(state="visible")
        else:
            raise ValueError(f"unsupported setup action: {action}")
    # Let scheduled render and scroll handlers settle; application ready selectors
    # remain required when completion depends on asynchronous app work.
    await page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")


async def resolve_truth(page, truth):
    result = []
    for target in truth:
        loc = locator_for(page, target)
        count = await loc.count()
        if count != 1:
            raise ValueError(f"truth {target['key']}: expected one node, found {count}")
        box = await loc.bounding_box()  # Playwright uses top-level CSS coordinates for frames.
        result.append({**target, "bbox": box})
    return result


async def axe_comparison(page, truth, observed):
    """Report separate rule outcomes; an accessible name is not full axe validity."""
    axe = ROOT / "node_modules/axe-core/axe.min.js"
    if not axe.exists():
        return {"status": "not_run", "reason": "npm ci required for axe-core"}
    await page.add_script_tag(path=str(axe))
    audit = await page.evaluate("""async () => {
        const r = await axe.run(document, {runOnly: {type:'rule', values:['button-name','link-name']}});
        return Object.fromEntries(['violations','incomplete','passes'].map(k =>
            [k, r[k].map(v => ({id:v.id, nodes:v.nodes.map(n => ({target:n.target,
                summary:n.failureSummary || null}))}))]));
    }""")
    comparisons = []
    for target in truth:
        if target["role"] not in ("button", "link") or not target.get("include", True):
            continue
        loc = locator_for(page, target)
        details = await loc.evaluate("el => ({tag:el.tagName.toLowerCase(), explicitRole:el.getAttribute('role')})")
        rule = "button-name" if target["role"] == "button" else "link-name"
        # Axe selectors can be nested arrays through frames/shadow roots. Do not
        # equate these with collector IDs, nor silently flatten across contexts.
        outcomes = []
        unresolved_nested = False
        for category, rules in audit.items():
            for result in rules:
                if result["id"] != rule:
                    continue
                for node in result["nodes"]:
                    selectors = node["target"]
                    if target.get("frame") or len(selectors) != 1 or not isinstance(selectors[0], str):
                        unresolved_nested = True
                        continue
                    same = await loc.evaluate("""(el, selector) => {
                        try { return el.ownerDocument.querySelector(selector) === el; }
                        catch { return false; }
                    }""", selectors[0])
                    if same:
                        outcomes.append(category)
        collected = [o for o in observed if target.get("bbox") and near_box(target["bbox"], o["bbox"])]
        actual_name = collected[0]["name"] if len(collected) == 1 else None
        explanation = "No disagreement between collected name presence and the matched axe rule result."
        if actual_name is None:
            explanation = "Collector identity is missing/ambiguous; do not compare unrelated nodes."
        elif not outcomes:
            explanation = ("Nested frame/shadow selectors require explicit review." if unresolved_nested else
                           "Not matched to this native axe rule; ARIA-only widgets have different rule scope.")
        elif ("violations" in outcomes and actual_name) or ("passes" in outcomes and not actual_name):
            explanation = "Disagreement: inspect labeling/hidden state and axe failure details; do not equate name presence with full rule validity."
        comparisons.append({"key": target["key"], "expected_name": target["name"], "collected_name": actual_name,
                            "axe_outcomes": sorted(set(outcomes)), "rule": rule, **details,
                            "explanation": explanation})
    return {"status": "ran", "results": audit, "targets": comparisons,
            "collector_unnamed_ids": [o["el_id"] for o in observed if o["role"] in ("button", "link") and not o["name"]],
            "interpretation": "Name/role mismatches are separately scored. axe rule scope, hidden/occluded nodes and nested frame selectors differ; an empty violation list is not proof of name/role equality."}


async def numeric_click(page, key, truth, observed, matches, before_click=()):
    """Exercise collector ID -> snapshot -> resolved DOM handle click, not label locator click."""
    from worker.collect.collector import resolve_element, snapshot
    target = next(t for t in truth if t["key"] == key)
    el_id = matches.get(key)
    if el_id is None:
        return {"key": key, "status": "unmatched"}
    old = next(o for o in observed if o["el_id"] == el_id)
    await apply_steps(page, before_click)
    try:
        snap = await snapshot(page, el_id)
    except Exception as exc:
        return {"key": key, "el_id": el_id, "status": "stale", "error_type": type(exc).__name__}
    box = snap.bbox.model_dump()
    if snap.name != old["name"] or snap.role != old["role"] or not near_box(box, old["bbox"]):
        return {"key": key, "el_id": el_id, "status": "stale", "reason": "snapshot identity/geometry changed since observe"}
    if snap.occluded:
        return {"key": key, "el_id": el_id, "status": "occluded"}
    expected = locator_for(page, target)
    await expected.evaluate("""el => {
        globalThis.__spaExpectedClick = false;
        el.addEventListener('click', e => { if(e.composedPath().includes(el)) globalThis.__spaExpectedClick = true; }, {once:true});
    }""")
    x = (max(0, box["x"]) + min(snap.viewport.width, box["x"] + box["width"])) / 2
    y = (max(0, box["y"]) + min(snap.viewport.height, box["y"] + box["height"])) / 2
    handle = None
    try:
        handle = await resolve_element(page, el_id)
        await handle.click(timeout=5000)
    except Exception as exc:
        return {"key": key, "el_id": el_id, "status": "click_error", "error_type": type(exc).__name__}
    finally:
        if handle is not None:
            await handle.dispose()
    # A detached/replaced target is OK; capture the signal in the same frame global.
    frame = page.frame_locator(target["frame"]) if target.get("frame") else page
    try:
        hit = await frame.locator("html").evaluate("() => globalThis.__spaExpectedClick === true")
    except Exception:
        return {"key": key, "el_id": el_id, "status": "unverified_navigation"}
    return {"key": key, "el_id": el_id, "status": "matched" if hit else "wrong_target", "xy": [x, y]}


async def run_manifest(manifest, base_url, output, executable=None):
    from playwright.async_api import async_playwright
    from worker.collect.collector import observe
    validate_manifest(manifest)
    local_url(base_url)
    output.mkdir(parents=True, exist_ok=True)
    report = {"version": 1, "app": manifest["app"], "ground_truth_review": manifest["ground_truth_review"],
              "recorded_at": datetime.now(timezone.utc).isoformat(), "viewport": manifest["viewport"],
              "adapter": "collector numeric handle click, not production driver", "scenarios": []}
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(**({"executable_path": executable} if executable else {}))
        except Exception as exc:
            report["startup_error"] = {"type": type(exc).__name__, "message": str(exc)[:600]}
            report["scenarios"] = [{"id": s["id"], "status": "not_run", "coverage": []}
                                   for s in manifest["scenarios"]]
            report["summary"] = summarize(report)
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return report
        try:
            report["browser"] = browser.version
            for scenario in manifest["scenarios"]:
                item = {"id": scenario["id"], "coverage": scenario.get("coverage", [])}
                context = await browser.new_context(viewport=manifest["viewport"])
                page = await context.new_page()
                page.set_default_timeout(5000)
                # Benchmark actions must not leak to an upstream service. Local
                # apps must vendor resources; denied requests remain in evidence.
                denied = []
                async def route(request_route):
                    url = request_route.request.url
                    try:
                        local_url(url)
                    except ValueError:
                        denied.append(urlsplit(url).hostname)
                        await request_route.abort()
                    else:
                        await request_route.continue_()
                await context.route("**/*", route)
                try:
                    await setup_state(page, base_url, scenario)
                    truth = await resolve_truth(page, scenario["truth"])
                    start = time.perf_counter()
                    observed = await observe(page)
                    item["extraction_ms"] = (time.perf_counter() - start) * 1000
                    item["metrics"] = evaluate_state(truth, observed)
                    item["observed"] = observed
                    item["truth"] = truth
                    item["axe"] = await axe_comparison(page, truth, observed)
                    await page.screenshot(path=str(output / f"{scenario['id']}.png"))
                    item["clicks"] = []
                    for key in scenario.get("clicks", []):
                        # Independent fresh state for each click; never reuse IDs
                        # after mutation/navigation or carry a previous click forward.
                        click_context = await browser.new_context(viewport=manifest["viewport"])
                        try:
                            await click_context.route("**/*", route)
                            click_page = await click_context.new_page()
                            click_page.set_default_timeout(5000)
                            await setup_state(click_page, base_url, scenario)
                            current_truth = await resolve_truth(click_page, scenario["truth"])
                            current = await observe(click_page)
                            matches = evaluate_state(current_truth, current)["matches"]
                            item["clicks"].append(await numeric_click(click_page, key, current_truth, current, matches,
                                                                   scenario.get("between_observe_and_click", [])))
                        finally:
                            await click_context.close()
                    item["status"] = "measured"
                except Exception as exc:
                    item.update(status="error", error_type=type(exc).__name__, error=str(exc)[:600])
                finally:
                    item["blocked_external_hosts"] = sorted(set(denied))
                    await context.close()
                report["scenarios"].append(item)
        finally:
            await browser.close()
    report["summary"] = summarize(report)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def summarize(report):
    states = report["scenarios"]
    measured = [s for s in states if s["status"] == "measured"]
    times = sorted(s["extraction_ms"] for s in measured)
    clicks = [c for s in measured for c in s["clicks"]]
    expected = sum(s["metrics"]["expected"] for s in measured)
    observed = sum(s["metrics"]["observed"] for s in measured)
    omitted = sum(len(s["metrics"]["omitted"]) for s in measured)
    extras = sum(len(s["metrics"]["unmatched_observed_ids"]) for s in measured)
    status_counts = dict(Counter(c["status"] for c in clicks))
    quality = bool(measured) and len(measured) == len(states) and all(s["metrics"]["thresholds_pass"]
        and not s["metrics"]["name_role_occlusion_mismatches"] and not s["blocked_external_hosts"] for s in measured)
    quality = quality and bool(clicks) and all(c["status"] == "matched" for c in clicks)
    approved = report["ground_truth_review"]["status"] == "approved"
    return {"measured_states": len(measured), "error_states": len(states) - len(measured),
            "omission_rate": ratio(omitted, expected), "contamination_rate": ratio(extras, observed),
            "click_status_counts": status_counts, "number_click_match_rate": ratio(status_counts.get("matched", 0), len(clicks)),
            "extraction_median_ms": statistics.median(times) if times else None,
            "extraction_p95_ms": times[max(0, math.ceil(len(times) * .95) - 1)] if times else None,
            "coverage_measured": sorted({c for s in measured for c in s["coverage"]}),
            "quality_thresholds_pass": quality,
            "status": "not_run" if not measured else "passed" if quality and approved else "review_pending" if quality else "failed",
            "certifies_three_spas": False,
            "limitations": ["One manifest is not 2 benchmark SPAs + 1 teammate SPA certification.",
                            "LLM filtered/capped counts are diagnostic projections, not a production agent execution.",
                            "No extraction-time pass threshold is specified. Report latency, do not invent one."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chromium-executable")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = asyncio.run(run_manifest(manifest, args.base_url, args.output, args.chromium_executable))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["summary"]["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
