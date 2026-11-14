"""진행 이상 메모 notes-<코드>.json (세션 파일과 따로 둔다).

형식:
  {"session": {participant_code, facilitator, app_version, repo_commit, site_manifest_hashes, os,
               screen_avail_height, started_at, run_mode, procedure_version},
   "pages": [{order, page_id, participant_reported, completed, completed_confirmed, confirmation_changed,
              auto_stopped_3min, issue, issue_codes, note}, ...]}

- participant_reported: 참가자가 끝낸 방법. done([다 했어요]) | gave_up([그만할게요]) | timeout(3분) |
  closed(브라우저 창을 닫음) | crashed(브라우저 오류) | null(저장되지 않은 페이지, 이미 끝난 세션)
- completed: 페이지가 끝날 때 세션 json에 처음 저장한 값(참가자 답 기준)
- completed_confirmed: 진행자가 확인표에서 확정한 값. 세션 json의 completed는 이 값이다
- confirmation_changed: 진행자가 바꿨으면 true (그때만 세션 json의 completed를 고쳐 다시 저장했다)
- issue는 진행자 확인 전까지 null이다(프로그램이 그 사이에 꺼지면 다시 열 때 확인표에서 받는다).
- issue_codes의 뜻은 procedure_version마다 다르다(ISSUE_CODES).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SELF_GUIDED = "self_guided_v1"
READ_ALOUD = "read_aloud"  # 진행 프로그램 전, 진행자가 읽어 주던 방식(이미 끝난 세션 메모)
ISSUE_CODES: dict[str, dict[int, str]] = {
    SELF_GUIDED: {
        1: "참가자가 진행자에게 도움을 요청해 답해 줌",
        2: "참가자가 과업을 잘못 이해함",
        3: "버튼을 늦게/일찍 누름",
        4: "기술 문제",
        5: "기타",
    },
    READ_ALOUD: {
        1: "과업 문장을 다르게 읽음",
        2: "참가자를 도와줌",
        3: "창을 늦게/잘못 띄움",
        4: "완료 버튼을 늦게/일찍 누름",
        5: "기술 문제",
        6: "기타",
    },
}
OTHER = {SELF_GUIDED: 5, READ_ALOUD: 6}
TECHNICAL = {SELF_GUIDED: 4, READ_ALOUD: 5}
NOTE_MAX = 200
BEFORE_APP = "before-app"
SESSION_FIELDS = ("participant_code", "facilitator", "app_version", "repo_commit", "site_manifest_hashes", "os",
                  "screen_avail_height", "started_at", "run_mode", "procedure_version")
PAGE_FIELDS = ("order", "page_id", "participant_reported", "completed", "completed_confirmed", "confirmation_changed",
               "auto_stopped_3min", "issue", "issue_codes", "note")


def notes_path(folder: Path, code: str) -> Path:
    return folder / f"notes-{code}.json"


def load(folder: Path, code: str) -> dict[str, Any] | None:
    try:
        data = json.loads(notes_path(folder, code).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def new(session: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in SESSION_FIELDS if k not in session]
    if missing:
        raise ValueError(f"notes 세션 정보에 빠진 칸: {missing}")
    return {"session": {k: session[k] for k in SESSION_FIELDS}, "pages": []}


def save(folder: Path, code: str, notes: dict[str, Any]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = notes_path(folder, code)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(notes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def page_entry(notes: dict[str, Any], page_id: str) -> dict[str, Any] | None:
    for p in notes.get("pages", []):
        if p.get("page_id") == page_id:
            return p
    return None


def upsert_page(notes: dict[str, Any], entry: dict[str, Any]) -> None:
    clean = {k: entry.get(k) for k in PAGE_FIELDS}
    pages = [p for p in notes.setdefault("pages", []) if p.get("page_id") != clean["page_id"]]
    pages.append(clean)
    notes["pages"] = sorted(pages, key=lambda p: (p.get("order") or 0))


def check_note(issue_codes: list[int], note: str, version: str = SELF_GUIDED) -> str | None:
    """메모 입력 오류 문장. None이면 통과."""
    if any(c not in ISSUE_CODES[version] for c in issue_codes):
        return "알 수 없는 항목"
    if "\n" in note or "\r" in note:
        return "메모는 한 줄로 적어 주세요"
    if len(note) > NOTE_MAX:
        return f"메모는 {NOTE_MAX}자 이내로 적어 주세요"
    if OTHER[version] in issue_codes and not note.strip():
        return "'기타'를 골랐으면 한 줄 메모를 적어 주세요"
    return None


def apply_note(entry: dict[str, Any], issue_codes: list[int], note: str) -> dict[str, Any]:
    codes = sorted(set(issue_codes))
    return {**entry, "issue": bool(codes), "issue_codes": codes, "note": note.strip()}
