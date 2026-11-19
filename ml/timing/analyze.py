"""Read-only task-time analysis under the frozen ml/timing/README contract.

Completion is a human-reviewed original event index, never guessed from last input.
CLI manifest and outputs are private local artifacts; this module has no network/DB.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import median
from typing import Any

from ml.timing.human import click_events

BOUNDARIES = {"click", "key", "down", "up", "scroll"}


def analyze_session(session: Mapping[str, Any], notes: Mapping[str, Any] | None, *,
                    completion_index: int | None = None,
                    completion_reason: str = "", prior_procedure: bool = False) -> dict[str, Any]:
    """Return explicit exclusions and provenance; never alter session or notes."""
    if type(prior_procedure) is not bool or not isinstance(completion_reason, str):
        raise ValueError("Prior procedure must be boolean and completion reason must be text")
    events = session["events"]
    clicks = click_events(events)  # also validates chronological times/coordinates
    if type(session.get("completed")) is not bool:
        raise ValueError("Session completed must be boolean")
    code, page = session["participant_code"], session["page_id"]
    result: dict[str, Any] = dict(participant_code=code, page_id=page,
        completed=session["completed"], procedure_version="unknown", status="excluded",
        exclusion_reasons=[], observed_seconds=None, response_seconds=None, adjusted_seconds=None,
        start_index=None, completion_index=completion_index, completion_reason=completion_reason,
        response_intervals=[], unresolved_waits=[], clicks=clicks)
    reasons = result["exclusion_reasons"]
    if notes is None:
        reasons.append("notes_missing")
    else:
        meta = notes["session"]
        if meta["participant_code"] != code:
            raise ValueError("Notes participant does not match session")
        version = meta["procedure_version"]
        if version not in {"read_aloud", "self_guided_v1"}:
            raise ValueError("Unknown procedure version")
        result["procedure_version"] = version
        entries = [item for item in notes["pages"] if item["page_id"] == page]
        if len(entries) != 1:
            reasons.append("page_notes_missing_or_duplicate")
        else:
            entry = entries[0]
            if entry.get("issue") is True:
                reasons.append("notes_issue")
            elif entry.get("issue") is not False:
                reasons.append("notes_unconfirmed")
            if entry.get("issue_codes") and entry.get("issue") is False:
                raise ValueError("Notes issue flag conflicts with issue_codes")
            confirmed = entry.get("completed_confirmed")
            if type(confirmed) is not bool:
                reasons.append("completion_unconfirmed")
            elif confirmed != session["completed"]:
                raise ValueError("Notes completed_confirmed conflicts with session")
            result["issue_codes"] = list(entry.get("issue_codes", []))
            result["note"] = entry.get("note", "")
    if not session["completed"]:
        reasons.append("incomplete")
    if session.get("viewport") != {"width": 1280, "height": 800}:
        reasons.append("nonstandard_viewport")
    start = next((i for i, e in enumerate(events) if e["type"] == "stable"), None)
    result["start_index"] = start
    if start is None:
        reasons.append("start_missing")
    elif any(e["type"] in BOUNDARIES for e in events[:start]):
        reasons.append("early_action")
    actions = [dict(c, origin=c["click_index"] if c["click_index"] is not None else c["up_index"])
               for c in clicks]
    actions += [dict(e, origin=i) for i, e in enumerate(events) if e["type"] == "key"]
    actions.sort(key=lambda item: (item["t_ms"], item["origin"]))
    end = next((a for a in actions if type(completion_index) is int and a["origin"] == completion_index), None)
    if end is None or not completion_reason.strip() or not end.get("target_key"):
        reasons.append("end_unresolved")
    if reasons:
        return result
    assert start is not None and end is not None
    assert completion_index is not None
    if completion_index <= start or end["t_ms"] < events[start]["t_ms"]:
        raise ValueError("Completion precedes task start")
    start_ms, end_ms = events[start]["t_ms"], end["t_ms"]
    intervals = []
    unresolved = []
    for action in actions:
        origin = action["origin"]
        if not start < origin < completion_index:
            continue
        own = {action.get("down_index"), action.get("up_index"), action.get("click_index")}
        later = [(i, e) for i, e in enumerate(events) if i > origin and i not in own]
        stable = next(((i, e) for i, e in later if e["type"] == "stable"), None)
        boundary = next(((i, e) for i, e in later if e["type"] in BOUNDARIES), None)
        if (stable is not None and action["t_ms"] < stable[1]["t_ms"] <= end_ms
                and (boundary is None or stable[1]["t_ms"] < boundary[1]["t_ms"])):
            intervals.append(dict(action_index=origin, stable_index=stable[0],
                                  start_ms=action["t_ms"], end_ms=stable[1]["t_ms"]))
        else:
            unresolved.append(origin)
    # Union prevents double subtraction even when distinct records share times.
    union: list[list[float]] = []
    for interval in sorted(intervals, key=lambda item: item["start_ms"]):
        a, b = interval["start_ms"], interval["end_ms"]
        if union and a <= union[-1][1]:
            union[-1][1] = max(union[-1][1], b)
        else:
            union.append([a, b])
    observed = (end_ms - start_ms) / 1000
    response = sum(b-a for a, b in union) / 1000
    if response > observed:
        raise ValueError("Response intervals exceed task duration")
    result.update(status="included", observed_seconds=observed, response_seconds=response,
                  adjusted_seconds=observed-response, response_intervals=intervals,
                  response_union_ms=union, unresolved_waits=unresolved,
                  completion_event=end)
    if prior_procedure:
        result["status"] = "excluded"
        result["exclusion_reasons"].append("prior_procedure")
    return result


def summarize(results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Page/procedure summaries. <3 eligible successes: completion rate only.

    Counts use distinct participant/page sessions; duplicates must be resolved first.
    Unknown-wait sensitivity is reported separately, never treated as zero latency.
    """
    seen = set()
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for item in results:
        key = (item["participant_code"], item["page_id"])
        if key in seen:
            raise ValueError("Duplicate participant/page analysis")
        seen.add(key)
        groups[(item["page_id"], item["procedure_version"])].append(item)
        groups[(item["page_id"], "all")].append(item)
    output = []
    for (page, procedure), rows in sorted(groups.items()):
        eligible = [r for r in rows if r["status"] == "included"]
        resolved = [r for r in eligible if not r["unresolved_waits"]]
        with_prior = [r for r in rows if r["status"] == "included" or r["exclusion_reasons"] == ["prior_procedure"]]
        def times(items):
            return ({"observed_median": median(r["observed_seconds"] for r in items),
                     "adjusted_median": median(r["adjusted_seconds"] for r in items)}
                    if len(items) >= 3 else {"observed_median": None, "adjusted_median": None})
        output.append(dict(page_id=page, procedure_version=procedure, total=len(rows),
            completed=sum(r["completed"] for r in rows),
            completion_rate=sum(r["completed"] for r in rows)/len(rows),
            eligible_successes=len(eligible), report="time" if len(eligible) >= 3 else "completion_only",
            exclusions=dict(Counter(reason for r in rows for reason in r["exclusion_reasons"])),
            **times(eligible), prior_procedure_included=dict(n=len(with_prior), **times(with_prior)), resolved_waits_only=dict(n=len(resolved), **times(resolved))))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = [(manifest_path.parent / row["session"]).resolve() for row in entries]
    notes_paths = [(manifest_path.parent / row["notes"]).resolve() if row.get("notes") else None for row in entries]
    if args.output.resolve() in {manifest_path, *paths, *[p for p in notes_paths if p is not None]}:
        raise ValueError("Output must not overwrite any input")
    results = [analyze_session(json.loads(path.read_text(encoding="utf-8")),
        json.loads(note.read_text(encoding="utf-8")) if note else None,
        completion_index=entry.get("completion_index"), completion_reason=entry.get("completion_reason", ""),
        prior_procedure=entry.get("prior_procedure", False))
        for entry, path, note in zip(entries, paths, notes_paths)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(sessions=results, pages=summarize(results)),
                                     ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
