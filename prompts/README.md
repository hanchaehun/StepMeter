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
| `action_v4` | 2026-11-25 | 요소 목록의 실제 한 줄 형식(`번호\|역할\|이름\|영역\|x,y,너비x높이\|표시`)과 예시 줄, 상태 표시(가려짐·입력됨·비어 있음·선택됨·펼쳐짐·비활성), select 옵션, 최근 행동의 `target_name`. 요소는 최대 60개 | ADR 0011 11번 |

지금 쓰는 버전은 `worker/agent/persistence.py`의 `PROMPT_VERSION`이다. 예전 파일은 기록 재현을 위해 지우지 않는다.

## 설명 생성 (`explain_v1`)

코드는 `worker/llm/explain.py`, 호출 위치는 `worker/agent/run.py`의 후처리(지표·점수 저장 뒤, `completed` 기록 전)다.
에이전트 측정에서만 부르고(재생만 끝까지 된 측정은 부르지 않는다), 가짜 어댑터면 부르지 않는다.

- run 하나에 한 번 묻는다. 같은 (규칙, 측정값, 기준값, 요소, 지금 설명) 이슈는 한 줄로 묶어 같은 답을 쓴다. 한 번에 최대 60줄.
- 한 줄은 `번호|규칙 이름|심각도|측정값|기준값|요소|지금 설명`이다. 답은 `[{"id", "explanation", "suggestion"}]`.
- 프롬프트에 규칙마다 무엇을 재는지 한 줄씩 적었다. 처음엔 없어서, 대비 부족의 요소 칸(글자가 아니라 연결된 조작 요소가 들어간다)을 "입력한 글자"로, 먼 이동 + 작은 타겟을 "시선" 문제로 짐작해 썼다 (michi run 14).
- 답 길이 한도는 설명 호출 동안만 8192토큰이다. 어댑터 기본값 1024로는 michi 한 run의 답도 잘렸다 (run 13).
- 답의 설명은 `update_explanation`으로 `Issue.explanation` 앞부분을 바꾸고("대상: …"은 DB 원본 유지), 고칠 방법은 `Issue.suggestion`에 넣는다.
- 답에 그 줄에 없던 숫자가 있으면 그 줄은 버리고 템플릿 설명을 둔다(개발계획서 6.1). 모델 호출이 실패해도 템플릿 설명이 남고 측정은 그대로 끝난다.
- 호출은 `llm_call`에 `purpose=explain`, `prompt_version=explain_v1`로 남고 run 비용에 더해진다.
- 6.1과 다른 점: 스크린샷을 보내지 않는다. 이슈마다 이미지를 보내면 설명 비용이 측정보다 커질 수 있어 v1은 글만 보낸다.
