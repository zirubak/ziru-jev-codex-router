# 소진 상태 복구를 확인하는 설치 검사

기준 소스: `7691ef560caf27f5ce4eddcaf5ca7763f9aab1cf`.
이 변경은 기존 [Responses-lite 복구 수정](lite-quota-recovery-2026-10-08.md)의
설치 검증 경로를 보완한다.

## 문제와 동작

계정 사용량이 복구돼도 일반 Responses 요청은 저장된 자동 quota 상태에 따라
외부 fallback으로 전달될 수 있다. 기존 설치 smoke는 일반 요청을 사용하므로,
Responses-lite 복구 수정이 정상이어도 외부 경로가 없으면 503으로 설치를 되돌린다.

설치 smoke는 이제 실제 native에서 확인한 Responses-lite 계약을 사용한다.
`x-openai-internal-codex-responses-lite: true`, `reasoning.context: all_turns`,
`parallel_tool_calls: false`를 함께 전달한다. 정상 native 응답은 자동 quota 상태를
해제하며, 실제 quota 거부는 설치 오류로 남는다. 외부 replay 보호, 수동 dry marker,
canonical 요청 전달 및 root transaction의 실패 복구는 유지한다.

## 검증 근거

- 격리된 parent → Jev → native HTTP fixture에서 기존 smoke가 503으로 실패하는
  RED를 관측했다. 실제 소진 거부 경로도 별도로 검사한다.
- 기존 fixture의 요청 완료 이벤트를 기다린 뒤 상태 삭제를 검사하여, HTTP 응답
  종료와 서버의 상태 갱신 사이의 경쟁을 제거했다.
- 실제 native에 동일한 계약으로 작은 확인 요청을 보냈고 HTTP 200 및
  `response.completed`를 확인했다. 이는 설치 후 전체 Desktop UI 검증을 대신하지 않는다.
- 동일 후보의 코드·Python 읽기 전용 통합 리뷰에서 지적한 테스트 동기화를 수정하고
  두 전문가의 최종 승인을 받았다.

| 파일 | SHA-256 |
| --- | --- |
| `server/smoke.py` | `8c0a87ce067d0a22f33c04e4ef0b561fc7a79fb81fed85d1f4bc1865a50d1be0` |
| `server/test_smoke.py` | `b159e9a2def3d6dd81308d75defeb02026cfd651b0eb3db69c3fb646f3ec282a` |

최종 Python 검사 358개 중 357 PASS·1 조건부 SKIP, Node 검사 4,670개 중
4,627 PASS·43 조건부 SKIP·실패 0건이다. 관련 HTTP 검사 24개, Python 구문,
오프라인 routing dossier, Node 구문·application manifest, Ruff 및 문서 공백 검사를
통과했다. 첫 Node 시도의 누락된 개발 의존성은 잠금 파일대로 복원한 뒤 전체 검사를
재실행했다. 수치 coverage는 측정하지 않았다.

실제 설치 결과는 로컬 적용 기록으로 별도 검증한다. GitHub Actions는 사용자 정책에
따라 비활성 상태이며 원격 CI 성공을 주장하지 않는다.

## 남아 있는 범위

- [Plan UI 즉시 해제 #30](https://github.com/zirubak/ziru-jev-codex-router/issues/30)는
  별도 미해결 증상이다.
- 모든 HTTP 429를 quota로 분류하는 기존 동작은 이번 변경 범위 밖이다.
- 실제 native quota 소진 시 Responses-lite 외부 fallback은 지원하지 않는다.
- 원격 소스 전달과 실행 서비스 설치, Desktop 프로세스 재시작은 서로 다른 상태다.

No durable learning: 동작과 회귀 조건은 코드·테스트·이 문서에서 복구 가능하다.
