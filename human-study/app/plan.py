"""human-study/session_plan.json 읽기."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CODE = re.compile(r"^P(\d{2})$")
ORDER_MARKS = "①②③④⑤⑥⑦⑧⑨"
VIEWPORT_WIDTH = 1280  # session.DEFAULT_VIEWPORT


@dataclass(frozen=True)
class PlanPage:
    order: int
    task_no: int
    title: str
    page_id: str
    preface_say: str | None
    task_say: str
    show_values: tuple[str, ...]
    done_when: str
    facilitator_note: str | None

    @property
    def mark(self) -> str:
        return ORDER_MARKS[self.order - 1]

    @property
    def label(self) -> str:
        return f"{self.mark} 과업 {self.task_no} — {self.title}"


@dataclass(frozen=True)
class Facilitator:
    github: str
    first: str
    last: str

    def codes(self) -> list[str]:
        a, b = code_number(self.first), code_number(self.last)
        return [f"P{n:02d}" for n in range(a, b + 1)]

    @property
    def range_text(self) -> str:
        return self.first if self.first == self.last else f"{self.first}–{self.last}"


@dataclass(frozen=True)
class Plan:
    raw: dict[str, Any]
    pages: tuple[PlanPage, ...]
    facilitators: tuple[Facilitator, ...]

    @property
    def device(self) -> str:
        return str(self.raw["device"])

    @property
    def page_limit_seconds(self) -> float:
        return float(self.raw["page_limit_seconds"])

    @property
    def min_screen_avail_height(self) -> int:
        return int(self.raw["min_screen_avail_height"])

    @property
    def practice_code(self) -> str:
        return str(self.raw["practice_code"])

    @property
    def procedure_version(self) -> str:
        return str(self.raw["procedure_version"])

    @property
    def panel_width(self) -> int:
        """참가자 패널 너비(Chromium 창 테두리 16px 포함)."""
        return int(self.raw["panel_width"])

    @property
    def min_screen_avail_width(self) -> int:
        """Chromium 뷰포트 1280 + 오른쪽 참가자 패널."""
        return VIEWPORT_WIDTH + self.panel_width

    def p(self, key: str) -> str:
        """참가자 화면 문구."""
        return str(self.raw["participant"][key])

    def text(self, *keys: str) -> Any:
        node: Any = self.raw
        for k in keys:
            node = node[k]
        return node

    def c5_say(self, code: str) -> str:
        return str(self.raw["c5"]["say"]).format(code=code)

    def facilitator(self, github: str) -> Facilitator | None:
        for f in self.facilitators:
            if f.github == github:
                return f
        return None

    def page(self, page_id: str) -> PlanPage | None:
        for p in self.pages:
            if p.page_id == page_id:
                return p
        return None


def code_number(code: str) -> int:
    m = CODE.match(code)
    if not m:
        raise ValueError(f"참가자 코드 형식이 아님: {code!r} (P01 같은 형식)")
    return int(m.group(1))


def load_plan(path: Path) -> Plan:
    raw = json.loads(path.read_text(encoding="utf-8"))
    pages = tuple(sorted((PlanPage(order=p["order"], task_no=p["task_no"], title=p["title"], page_id=p["page_id"],
                                   preface_say=p.get("preface_say"), task_say=p["task_say"],
                                   show_values=tuple(p.get("show_values") or ()), done_when=p["done_when"],
                                   facilitator_note=p.get("facilitator_note"))
                          for p in raw["pages"]), key=lambda p: p.order))
    facilitators = tuple(Facilitator(f["github"], f["first"], f["last"]) for f in raw["facilitators"])
    return Plan(raw=raw, pages=pages, facilitators=facilitators)
