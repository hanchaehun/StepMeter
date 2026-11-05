"""Local axe scan with exact live DOM bindings, not fuzzy name matching."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from playwright.async_api import ElementHandle, Locator, Page


async def scan_page(page: Page, axe_script_path: str | Path,
                    path_targets: Mapping[int, Locator]) -> dict[str, Any]:
    """Bind caller's nonnegative path keys to targets before action/navigation.

    W2 covers the main document and its open shadow roots. Frame locators are
    rejected explicitly. Results retain violations and incomplete separately.
    Callers must rescan each page state; old locators are not a recorded path.
    """
    handles: list[ElementHandle] = []
    try:
        for path_key, locator in path_targets.items():
            if path_key < 0:
                raise ValueError("Path keys must be nonnegative")
            if await locator.count() != 1:
                raise ValueError(f"Path key {path_key} must resolve to exactly one live element")
            handle = await locator.element_handle()
            if handle is None:
                raise ValueError(f"Missing target for path key {path_key}")
            handles.append(handle)
            if await handle.owner_frame() != page.main_frame:
                raise ValueError("W2 axe scan supports main-frame targets only")
        await page.add_script_tag(path=axe_script_path)
        return await page.evaluate(
            """async ({ids, elements}) => {
                const connected = () => elements.every(el => el.isConnected);
                if (!connected()) throw new Error('Detached path target');
                const result = await axe.run(document, {elementRef: true, iframes: false});
                if (!connected()) throw new Error('Path target changed during axe scan');
                const within = (element, target) => {
                    for (let node = element; node; node = node.parentNode || node.host) {
                        if (node === target) return true;
                    }
                    return false;
                };
                for (const group of ['violations', 'incomplete', 'passes', 'inapplicable']) {
                    for (const rule of result[group]) {
                        for (const node of rule.nodes) {
                            node.path_keys = ids.filter((id, i) => node.element && (
                                node.element === elements[i] ||
                                rule.id === 'color-contrast' && within(node.element, elements[i])
                            ));
                            node.is_reference = node.path_keys.length === 0;
                            const box = node.element?.getBoundingClientRect();
                            node.in_viewport = !!box && box.width > 0 && box.height > 0 &&
                                box.right > 0 && box.bottom > 0 &&
                                box.left < innerWidth && box.top < innerHeight;
                        }
                    }
                }
                // DOM references are only used inside the browser, never persisted.
                return JSON.parse(JSON.stringify(result, (key, value) =>
                    key === 'element' ? undefined : value));
            }""",
            {"ids": list(path_targets), "elements": handles},
        )
    finally:
        for handle in handles:
            await handle.dispose()
