"""요소 매칭 v1 (개발계획서 7.2). 재생(7.2)과 문제 매칭(7.3)이 같이 쓴다.

확실할 때만 매칭한다. 애매하면 매칭하지 않고 재생기가 경로 변경으로 처리한다.
위치·구조(bbox, XPath, 형제 순서)는 쓰지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, Literal, NamedTuple

from rapidfuzz.fuzz import ratio

from worker.schemas import ElementSnapshot

# 지문 필드는 openapi.yaml의 ElementFingerprint와 같다
FINGERPRINT_KEYS = ("tag", "role", "name", "label_text", "landmark")
SIMILARITY = 0.8  # 낮추지 않는다 (7.2: "저장" vs "임시 저장")

Element = Mapping[str, Any]  # observe() 결과 한 줄 또는 지문 dict


class Match(NamedTuple):
    status: Literal["matched", "none", "ambiguous"]
    element: Element | None = None  # matched일 때 현재 화면의 요소
    step: int | str | None = None  # 찾은 순위: 0 별칭, 1 정확, 2 유사도, 3 포함, "unnamed" 지문


def fingerprint(el: ElementSnapshot | Element) -> dict[str, Any]:
    """ElementSnapshot이나 observe() 한 줄에서 매칭 지문(ElementFingerprint)을 뽑는다."""
    if isinstance(el, ElementSnapshot):
        el = el.model_dump()
    return {k: el[k] for k in FINGERPRINT_KEYS}


def _norm(name: str) -> str:
    return "".join(name.split()).casefold()


def _similar(a: str, b: str) -> bool:
    return ratio(_norm(a), _norm(b)) / 100 >= SIMILARITY


def _contains(a: str, b: str) -> bool:
    """한쪽 이름의 단어가 다른 쪽에 모두 들어 있음 ("가입 완료" ⊂ "회원가입 완료하기")."""

    def inside(x: str, y: str) -> bool:
        return all(w in y.casefold() for w in x.casefold().split())

    return inside(a, b) or inside(b, a)


def _pick(cands: list[Element], pred: Callable[[Element], bool], step: int | str) -> Match | None:
    hits = [c for c in cands if pred(c)]
    if len(hits) == 1:
        return Match("matched", hits[0], step)
    if hits:
        return Match("ambiguous")
    return None


def match(
    recorded: ElementSnapshot | Element,
    screen: Iterable[Element],
    aliases: Iterable[tuple[Element, Element]] = (),
) -> Match:
    """기록된 요소를 현재 화면(observe() 결과)에서 찾는다.

    aliases: 사용자가 확인한 (이전 지문, 새 지문) 쌍 (element_alias, 0순위).
    앞 순위에서 후보가 하나면 매칭, 둘 이상이면 애매함, 없으면 다음 순위로.
    """
    fp = fingerprint(recorded)
    cands = [c for c in screen if c["role"] == fp["role"]]  # 모든 순위에 역할 일치

    targets = [fingerprint(new) for old, new in aliases if fingerprint(old) == fp]
    if targets and (m := _pick(cands, lambda c: fingerprint(c) in targets, 0)):
        return m

    name = fp["name"]
    if not name:
        # 이름 없는 요소는 지문(태그·역할·레이블·랜드마크)이 같을 때만
        return _pick(cands, lambda c: fingerprint(c) == fp, "unnamed") or Match("none")

    named = [c for c in cands if c["name"]]
    # ponytail: 4순위 의미 유사도(sentence-transformers)는 선택 항목이라 뺐다. 문구 변경 버전 재생 완주율 80% 미만이면 추가.
    for step, pred in (
        (1, lambda c: c["name"] == name),
        (2, lambda c: _similar(c["name"], name)),
        (3, lambda c: _contains(c["name"], name)),
    ):
        if m := _pick(named, pred, step):
            return m
    return Match("none")
