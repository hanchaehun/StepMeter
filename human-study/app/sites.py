"""내장 사이트 서버와 시작 전 점검.

정적 서버·SPA 처리·포트·page_id → 주소는 benchmark/serve_variants.py를 그대로 쓴다
(load_config, page_builds, start_servers, probe, stale_builds). 새로 만들지 않는다.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from .resources import Resources


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


class SiteServers:
    """variants.json의 참가자 페이지 빌드 5개를 같은 포트로 127.0.0.1에 띄운다."""

    def __init__(self, res: Resources) -> None:
        self.res = res
        self.sv: ModuleType = res.serve_variants()
        self.config = self.sv.load_config()
        self.builds = self.config.page_builds()
        self.running: list[Any] = []
        self.error: str | None = None

    @property
    def host(self) -> str:
        return str(self.config.host)

    def url_for(self, page_id: str) -> str:
        return str(self.config.url_for(page_id))

    def page_urls(self) -> dict[str, str]:
        return {row["page_id"]: row["url"] for row in self.sv.page_table(self.config)}

    def busy_ports(self) -> list[str]:
        return [f"{b.port}({b.id})" for b in self.builds if self.sv.port_in_use(self.host, b.port)]

    def start(self) -> str | None:
        """띄우고 None, 못 띄우면 이유 문장."""
        if self.running:
            return None
        busy = self.busy_ports()
        if busy:
            self.error = (f"포트를 이미 다른 프로그램이 쓰고 있습니다: {', '.join(busy)}. "
                          "다른 StepMeter 진행 프로그램 창을 닫거나, 소스 방식으로 서버를 띄웠다면 "
                          "python -m benchmark.serve_variants stop 후 이 프로그램을 다시 여세요.")
            return self.error
        try:
            self.running = self.sv.start_servers(self.config, self.builds, self.host)
        except self.sv.ServeError as e:
            self.error = str(e)
            return self.error
        self.error = None
        return None

    def stop(self) -> None:
        if self.running:
            self.sv.stop_servers(self.running)
            self.running = []

    def probe_all(self) -> dict[str, int | str]:
        return {pid: self.sv.probe(url) for pid, url in self.page_urls().items()}

    def manifest_hashes(self) -> dict[str, str | None]:
        """빌드별 결과 sha256 (manifest의 output.sha256). notes에 남긴다."""
        out: dict[str, str | None] = {}
        for b in self.builds:
            m = self.sv.read_json(b.manifest_path) or {}
            out[b.id] = (m.get("output") or {}).get("sha256")
        return out

    def integrity_problems(self) -> list[str]:
        """빌드가 manifest와 같은지(serve_variants stale_builds), check가 통과한 그 빌드인지."""
        problems = list(self.sv.stale_builds(self.config, self.builds))
        if problems:
            return problems
        evidence = self.res.check_evidence
        try:
            summary = json.loads(evidence.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return [f"serve_variants check 결과({evidence.name})가 없습니다. check를 먼저 통과해야 합니다"]
        if not summary.get("ok"):
            return ["마지막 serve_variants check가 실패했습니다"]
        checked = summary.get("builds") or {}
        for bid, sha in self.manifest_hashes().items():
            got = ((checked.get(bid) or {}).get("output") or {}).get("sha256")
            if got != sha:
                problems.append(f"{bid}: check한 빌드와 지금 빌드가 다릅니다. serve_variants check를 다시 하세요")
        return problems


async def _screen_avail_size_async() -> tuple[int, int]:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        try:
            # 뷰포트를 정하면 Playwright가 screen도 뷰포트 크기로 흉내 내므로(availHeight=800) 뷰포트 없이 연다
            page = await browser.new_page(no_viewport=True)
            w, h = await page.evaluate("() => [screen.availWidth, screen.availHeight]")
            return int(w), int(h)
        finally:
            await browser.close()


def screen_avail_size() -> tuple[int, int]:
    """화면 있는 Chromium 창을 잠깐 띄워 (screen.availWidth, screen.availHeight)를 읽는다."""
    return asyncio.run(_screen_avail_size_async())


def folder_writable(folder: Path) -> str | None:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=folder, prefix=".write-test-")
        os.close(fd)
        os.unlink(name)
    except OSError as e:
        return str(e)
    return None
