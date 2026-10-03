# 최초 설치 실패 수정 — 2026-10-02

대상: [이슈 #2](https://github.com/zirubak/ziru-jev-codex-router/issues/2).
기준 커밋: `7eaa91ca606a07a7568ee6c1fa030840c466a4a0`.

## 원인과 변경

최초 설치는 discovery를 활성화한 뒤 Jev 등록 전에 embedded setup을 실행했다.
그 setup의 doctor는 활성 공급자와 실행 가능한 모델을 요구하므로 중간 상태를 거부했다.
기존 테스트 fixture는 이 검증을 생략했다.

`configure_jev`는 기존 공급자를 보존하면서 Jev 공급자·두 모델·로컬 인증을 준비한다.
신규 설치는 이 준비 후 embedded setup을 실행한다. 기존 선택 파일이 있는 재설치는
embedded 설치로 서비스 정의를 먼저 복구한 뒤 준비 명령을 실행한다.
공급자 변경 명령은 서비스를 재시작하기 때문에 두 경로의 순서는 의도적으로 다르다.
Discovery, native catalog 검증, 소유권 이전 및 전체 root rollback은 유지한다.

## 후보와 검증

| 파일 | SHA-256 |
| --- | --- |
| `install.sh` | `400556427726e138ee45d615d266aa454a4699e2659232c8f421366327a77ff6` |
| `server/test_install_transaction.py` | `113aeff2cfc992bb69ef5dddf779657bcc59c72e56cc6965e9879267ac22b7f3` |

- 최초 RED: 실제 `genericProviderConfigured` 및 `selectedConfiguredListedModels`를 호출하는 fixture에서 기존 순서의 `FAIL Enabled providers: none`을 확인했다. 21개 검사 중 10개 실패.
- 통합 리뷰에서 기존 서비스 복구 전 provider 명령의 재시작 회귀를 발견하고 수정했다.
- 회귀 검출 확인: 이전의 무조건 사전 등록 후보에 stale-service 검사 1개를 적용하면 예상 assertion failure가 발생했다. 최종 소스는 변경하지 않고 격리 fixture에만 이전 순서를 적용했다.
- 최종 설치 트랜잭션 검사: 22 PASS.
- 전체 Python 검사: 261 PASS (78.457초).
- Python compileall, 변경 테스트 ruff, shell 구문, 오프라인 routing dossier 16개 및 whitespace 검사 PASS.
- 코드·Python 전문가가 위 동일 해시 후보를 읽기 전용 검토했고 차단 finding 없이 승인했다.
- 실제 generic CLI add/enable, 모델·인증 설정 및 준비 상태 검사를 비어 있는 임시 HOME에서 실행했다. 7개 단계 PASS. 기본 config 생성이나 서비스 설치는 없었다.
- Embedded `router/` 소스는 기준 커밋과 동일하다. 해당 기준에 기록된 Node 4,481 PASS·37 SKIP 증거를 재사용한다. 이번 변경에서 Node 전체 suite를 재실행한 것으로 보고하지 않는다.
- GitHub Actions `enabled=false`를 확인했다. 원격 CI를 실행하거나 PASS로 취급하지 않았다.

## 한계와 설치 상태

설치 테스트는 CLI/provider descriptor·인증 marker·서비스 실패를 합성하고 실제 준비 상태 함수와 모델 설정을 실행한다.
Rollback 결과는 fixture 상태와 인증 marker 복구에 대한 증거다. 실제 credential store 및 launchd/systemd의 완전한 복구 검사로 확대하지 않는다.
추가 실제 CLI 검사는 최초 등록 준비 경계를 검증하며 전체 root 설치·doctor·live smoke 검사가 아니다.
사용자 환경 서비스 재설치·Desktop 재시작은 수행하지 않았다.

No durable learning: 등록 순서와 재설치의 재시작 경계는 최종 소스·회귀 검사·이 문서에서 복구할 수 있다.
