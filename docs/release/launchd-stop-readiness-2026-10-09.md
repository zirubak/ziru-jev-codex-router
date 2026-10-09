# 재설치와 복원에서 launchd 종료 확인

기준 소스: `098679c486f17f7363ab7699b0240bb95be80c44`.

## 원인과 수정

macOS의 `launchctl bootout` 성공은 서비스 제거 완료를 뜻하지 않는다.
실제 재설치에서 이전 Jev 프로세스가 종료되기 직전에 새 bootstrap이 실행돼
`37: Operation already in progress`로 거절됐다. 자동 복원의 embedded router
재등록에도 같은 경쟁이 있었다. 기존 서비스와 Desktop 등록은 원본 정의로 복구했다.

Jev 설치, root transaction 복원, Desktop 등록 교체·복원은 이제 bootout 뒤
`launchctl print`가 서비스 부재 상태 `113`을 반환할 때까지 확인한다.
조회 오류는 부재로 간주하지 않으며, 전체 종료 확인에는 15초 제한을 둔다.
확인 전에는 해당 plist를 교체하거나 bootstrap하지 않고, root 복원은 모든 writer의
제거를 확인한 뒤 공유 상태를 교체한다. 소유권 검사와 Desktop 재시작 제한은 유지한다.

## 검증

격리된 shell 설치 fixture에 지연 종료를 넣어 수정 전 bootstrap 실패와 복원 실패를
재현했다. 수정 후 설치 성공, 실패 시 원본 복원, Desktop 재등록과 복원,
조회 오류·제한 시간·정상 제거 확인의 회귀검사 6개가 통과했다.
기존 service fixture도 실제 macOS의 부재 상태와 정지 후 상태 변화를 반영한다.

코드·Python 전문가가 같은 후보를 읽기 전용으로 검토했고 두 리뷰 모두 승인했다.
전체 Python 364개 중 363 PASS·1 조건부 SKIP, Python 구문, 오프라인 routing
dossier, 변경 Python 파일 Ruff 및 공백 검사가 통과했다. 수치 coverage는 측정하지
않았다. Node 소스는 앞선 후보와 동일한 tree
`f08c93696e19485b963b995f3cf2970cb116be52`이며, 같은 실행 환경에서 확인한
`npm run check` PASS 및 전체 Node 4,627 PASS·43 SKIP 증거를 재사용한다.
GitHub Actions는 사용자의 정책에 따라 비활성 상태다.

| 파일 | SHA-256 |
| --- | --- |
| `server/install_services.py` | `390b7376e09d111a8cb8de54c7ae9e35b9dab52a1a1e64d6c0d30a5003237d60` |
| `server/install_service.py` | `8dd757d7f7a54a62649709adaebddd622b73b54fe11c56d2f9b4a4a273907556` |
| `server/install_transaction.py` | `d2f4061093cc94e2576d7d41b98e6b7174f427448807a46c62209a8dac2a89ac` |
| `server/desktop_session.py` | `55c57eb8e9ca08ac45d948a2865c01feaf43383db5a9f1c2b4837a0d6f0b76c1` |
| `server/test_service_shutdown.py` | `9bb3b59e04dc3cc802ce648d1d7ff5094be1cf587e3488ab723c122aec5dee5a` |
| `server/test_install_rollback.py` | `7137b22996fd0828e6f3e3193fc595951fd82db781a256ad1eb8e88c89924d4c` |
| `server/test_install_transaction.py` | `39997b2afe8f6b30067b7176cd377ae497ac2b4a9835e681fe28f0064133d60c` |

실제 root `./install.sh --desktop`는 종료 코드 0으로 끝났으며 transaction은
`committed` 상태다. Jev·embedded router·Desktop 등록 모두 검토한 소스 경로를
가리키고 두 HTTP health endpoint가 200을 반환했다. 설치 전 존재하던 자동 quota
파일은 native smoke의 HTTP 200 / `response.completed` 이후 사라졌다.
이미지 확인 요청도 parent → Jev → native 경로에서 HTTP 200으로 완료했고,
Luna가 합성 이미지의 파랑·빨강을 정확히 답했다.

기존 사용자 채팅을 대신 재전송하거나 Desktop 앱을 재시작하지 않았다.
따라서 이 증거는 실행 서비스와 API 경로 검증이며 기존 채팅의 UI 재시도 성공을
주장하지 않는다. 개인 설치 백업·원시 로그는 공개 저장소에 포함하지 않는다.

## 범위

이 변경은 [소진 복구 설치 검사](quota-recovery-install-2026-10-09.md)를 실제 서비스에
적용하는 과정에서 발견한 설치·복원 결함이다. quota 판정, 라우팅 정책, canonical
요청, 외부 fallback 지원 범위는 바꾸지 않는다. Node router 소스도 변경하지 않는다.

No durable learning: 원인과 재현 조건은 코드·검사·이 문서에서 복구 가능하다.
