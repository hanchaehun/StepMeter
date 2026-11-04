"""요소 매칭 v1 단위 테스트 (개발계획서 7.2).

고정 스냅샷 픽스처로 돈다(브라우저 없음). 기대값은 7.2 매칭 규칙 표와 예시에서 가져왔고,
유사도는 손으로 계산했다: Indel 유사도 = 1 − 편집 수 / (두 길이 합).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from worker.matching.match import fingerprint, match
from worker.schemas import ElementSnapshot

MOCK = Path(__file__).resolve().parent / "fixtures" / "mock"


def el(name, role="button", tag="button", landmark="main", label_text=None, el_id=1, bbox=(0, 0, 100, 40)):
    """observe() 한 줄과 같은 모양."""
    x, y, w, h = bbox
    return {
        "el_id": el_id, "tag": tag, "role": role, "name": name, "landmark": landmark,
        "label_text": label_text, "bbox": {"x": x, "y": y, "width": w, "height": h}, "occluded": False,
    }


class NamedTests(unittest.TestCase):
    def test_exact_name(self):  # 1순위: "가입 완료" = "가입 완료"
        target = el("가입 완료", el_id=2)
        m = match(el("가입 완료"), [el("취소"), target])
        self.assertEqual((m.status, m.element, m.step), ("matched", target, 1))

    def test_whitespace_only_change(self):  # 2순위: "가입완료" ≈ "가입 완료" (공백 정규화 후 같음)
        m = match(el("가입 완료"), [el("가입완료")])
        self.assertEqual((m.status, m.step), ("matched", 2))

    def test_case_only_change(self):  # 2순위: 대소문자 정규화
        m = match(el("Sign Up"), [el("sign up")])
        self.assertEqual((m.status, m.step), ("matched", 2))

    def test_small_typo_over_threshold(self):
        # "로그인하기" vs "로그인하기!": 편집 1, 길이 합 11 → 1 − 1/11 = 0.909 ≥ 0.8
        m = match(el("로그인 하기"), [el("로그인하기!")])
        self.assertEqual((m.status, m.step), ("matched", 2))

    def test_containment(self):  # 3순위: "가입 완료" ⊂ "회원가입 완료하기"
        # 유사도: "가입완료"(4) vs "회원가입완료하기"(8), 편집 4 → 1 − 4/12 = 0.667 < 0.8 이라 3순위에서 잡힘
        m = match(el("가입 완료"), [el("회원가입 완료하기")])
        self.assertEqual((m.status, m.step), ("matched", 3))

    def test_save_vs_temp_save(self):
        # "저장" vs "임시 저장": 둘 다 화면에 있으면 1순위 정확 일치가 이긴다
        save = el("저장", el_id=1)
        m = match(el("저장"), [save, el("임시 저장", el_id=2)])
        self.assertEqual((m.status, m.element), ("matched", save))

    def test_different_word_not_matched(self):
        # "로그인" vs "로그아웃": 공통 "로그" 2자, 편집 3, 길이 합 7 → 1 − 3/7 = 0.571, 포함도 아님
        self.assertEqual(match(el("로그인"), [el("로그아웃")]).status, "none")

    def test_semantic_synonym_not_matched_in_v1(self):  # 4순위(의미 유사도)는 v1에 없다
        self.assertEqual(match(el("제출"), [el("보내기")]).status, "none")


class SafetyTests(unittest.TestCase):
    def test_cancel_moved_into_old_position(self):
        # 7.2: [취소]가 원래 [가입 완료] 자리로 와도 위치로 매칭하지 않는다
        recorded = el("가입 완료", bbox=(100, 300, 120, 40))
        self.assertEqual(match(recorded, [el("취소", bbox=(100, 300, 120, 40))]).status, "none")

    def test_position_ignored_when_moved(self):
        target = el("가입 완료", el_id=2, bbox=(500, 50, 120, 40))
        m = match(el("가입 완료", bbox=(100, 300, 120, 40)), [el("취소", bbox=(100, 300, 120, 40)), target])
        self.assertEqual(m.element, target)

    def test_role_must_match(self):  # 링크 "로그인"을 버튼 "로그인"으로 보지 않는다
        recorded = el("로그인", role="link", tag="a")
        self.assertEqual(match(recorded, [el("로그인")]).status, "none")

    def test_two_exact_candidates_ambiguous(self):  # 유일성
        m = match(el("삭제"), [el("삭제", el_id=1), el("삭제", el_id=2)])
        self.assertEqual((m.status, m.element), ("ambiguous", None))

    def test_two_containment_candidates_ambiguous(self):
        m = match(el("가입 완료"), [el("회원가입 완료하기", el_id=1), el("가입 완료 후 이동", el_id=2)])
        self.assertEqual(m.status, "ambiguous")

    def test_empty_screen(self):
        self.assertEqual(match(el("구매"), []).status, "none")


class UnnamedTests(unittest.TestCase):
    def icon(self, **kw):
        return el("", label_text="수량", landmark="form", **kw)

    def test_same_fingerprint(self):
        m = match(self.icon(), [el("확인"), self.icon(el_id=2, bbox=(9, 9, 9, 9))])
        self.assertEqual((m.status, m.element["el_id"], m.step), ("matched", 2, "unnamed"))

    def test_landmark_changed(self):
        self.assertEqual(match(self.icon(), [el("", label_text="수량", landmark="banner")]).status, "none")

    def test_label_changed(self):
        self.assertEqual(match(self.icon(), [el("", label_text="개수", landmark="form")]).status, "none")

    def test_named_candidate_not_used(self):  # 이름 없는 요소는 이름 규칙을 타지 않는다
        self.assertEqual(match(self.icon(), [el("수량")]).status, "none")

    def test_two_same_fingerprints_ambiguous(self):
        self.assertEqual(match(self.icon(), [self.icon(el_id=1), self.icon(el_id=2)]).status, "ambiguous")


class AliasTests(unittest.TestCase):
    def setUp(self):
        alias = json.loads((MOCK / "api" / "element_alias.json").read_text(encoding="utf-8"))
        self.aliases = [(alias["from_fingerprint"], alias["to_fingerprint"])]  # 장바구니 담기 → 구매

    def test_alias_first(self):
        target = el("구매", el_id=3)
        m = match(el("장바구니 담기"), [el("취소"), target], self.aliases)
        self.assertEqual((m.status, m.element, m.step), ("matched", target, 0))

    def test_without_alias_no_match(self):
        self.assertEqual(match(el("장바구니 담기"), [el("구매")]).status, "none")

    def test_alias_target_missing_falls_through(self):  # 별칭 대상이 없으면 1순위부터 다시
        m = match(el("장바구니 담기"), [el("장바구니 담기")], self.aliases)
        self.assertEqual((m.status, m.step), ("matched", 1))


class SnapshotInputTests(unittest.TestCase):
    def test_element_snapshot_as_recorded(self):
        raw = json.loads((MOCK / "element_snapshot.json").read_text(encoding="utf-8"))
        snap = ElementSnapshot.model_validate(raw)
        fp = fingerprint(snap)
        self.assertEqual(set(fp), {"tag", "role", "name", "label_text", "landmark"})
        target = el(snap.name, role=snap.role, tag=snap.tag, landmark=snap.landmark, el_id=7)
        self.assertEqual(match(snap, [target]).element, target)


if __name__ == "__main__":
    unittest.main()
