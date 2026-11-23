# prompts/

- **담당 역할:** LLM·프롬프트
- **하는 일:** 버전 번호를 붙인 프롬프트 파일. 바꾸면 버전을 올리고 벤치마크를 다시 돌린다.
- **참고:** 개발계획서 4.4

## ADR 0011에 따른 할 일

결정 내용은 [ADR 0011](../docs/adr/0011-w3-plan-gaps.md)에 있다.

- 행동 프롬프트 `action_v2.md`에 비밀번호 칸 규칙을 반영했다: 과업에 적힌 값만 넣고, 값이 없는데 로그인·가입이 필요하면 `fail`로 끝낸다 (ADR 0011 1번).
- 설명 생성은 run 후처리에서 부른다(`docs/worker_api_spec.md` 2번). `worker/agent/run.py`에 연결하는 방법은 에이전트 코어와 정한다. 설명이 `Issue.explanation`을 바꾸면 axe가 짚은 요소의 selector(지금 `explanation` 끝에만 있다)가 사라지므로, 채점 도구가 읽을 방법을 회귀 비교·인프라, 측정 지표·규칙 담당과 먼저 정한다 (ADR 0011 6번)
- R09는 구현하는 PR에 `worker/agent/loop.py` 호출까지 넣는다. 에이전트 코어가 리뷰한다 (ADR 0011 6번)

## #62: 설명 생성에서 selector 유지

1번 방식(공용 스키마 변경 없음)의 연결 함수는 `worker/rules/axe_target.py`와
`worker/rules/persistence.py`에 있다. 모델은 설명 앞 문장만 생성한다.

```python
from worker.rules.axe_target import split_explanation
from worker.rules.persistence import update_explanation

prose, suffix = split_explanation(issue.explanation)
# DB 잠금 밖에서 prose와 측정 근거로 모델 설명을 생성한다.
# generated는 "대상: ..."을 포함하지 않는 새 설명 문장이다.
# 후보 저장 완료 후, 호출자가 run 권한·취소를 확인한 transaction 안에서:
update_explanation(session, run_id, issue.id, generated)
```

suffix는 LLM 답변이 아닌 DB 원본에서 붙인다. 기존 이슈 ID로 갱신하며,
새 Candidate를 만들어 설명을 저장하지 않는다. target이 없는 R02/R10 또는
손상된 JSON은 오류로 보고 기존 설명을 유지한다. 모델 호출·비용 기록·run 연결은
별도 설명 생성 구현에서 맡는다. 참고: `worker/rules/README.md`.

## 행동 프롬프트 이력

| 버전 | 날짜 | 바뀐 점 | 근거 |
|---|---|---|---|
| `action_v1` | W2 | 처음 버전 | 개발계획서 4.4 |
| `action_v2` | W3 | 비밀번호 칸 규칙: 과업에 적힌 값만 넣고, 값이 없는데 로그인·가입이 필요하면 `fail` | ADR 0011 1번 |
| `action_v3` | 2026-11-23 | `type`의 `submit`(입력 후 Enter) 설명 한 단락. Enter로만 실행되는 칸이고 실행 버튼이 보이지 않을 때 `submit: true`, `type`이 아니면 `null` | #75, ADR 0011 10번 |

지금 쓰는 버전은 `worker/agent/persistence.py`의 `PROMPT_VERSION`이다. 예전 파일은 기록 재현을 위해 지우지 않는다.
