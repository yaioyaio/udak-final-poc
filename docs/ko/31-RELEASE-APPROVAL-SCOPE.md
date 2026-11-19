# 배포 승인 범위

[English](../en/31-RELEASE-APPROVAL-SCOPE.md) | 한국어

G0는 아래 Apache-2.0 적용 범위에 대해 **APPROVED**다. G5는 승인된 한도에서 1회 실행하여 **PASS**했다. 정식 배포는 **BLOCKED**(`authorize_publish=false`)이며 제품 지원은 **NOT CERTIFIED**다. [배포 게이트와 지원 증거](30-RELEASE-SUPPORT-EVIDENCE.md) · [승인 결정](../../evidence/RELEASE-G0-G5-DECISION.json)

## G0 프로젝트 라이선스 및 배포 (RELEASE-004)

공개 대상인 UDAK 소유 소스에 Apache-2.0을 적용하고 해당 제3자 고지를 보존한다. 승인된 상업적 사용 범위는 버전 `0.1.0-poc`에서 검토한 범위와 `dev.udak`의 thin Maven 패키지 6종(`core`, `udak-api`, `jdbc-spring`, `observe-core`, `starter-boot3`, `starter-boot4`)이다. 바이너리 배포에서는 JDBC 드라이버, DB 이미지, 테스트 하네스, 외부 바이너리 JAR, fat 데모 JAR를 제외한다.

검토 근거는 모듈별 JAR·POM·Gradle 메타데이터·sources JAR·Javadoc JAR 30개와 SBOM·NOTICE·체크섬 등 5개다. 소비자 및 테스트 그래프의 외부 의존성 29개를 동봉 범위와 구분한다. `approval-history`와 별도 `rewrite-*` 모듈은 위 Maven 배포 목록에서 제외한다. 후보에 LICENSE·NOTICE와 Maven POM 라이선스 표기를 포함한다. 후보 검증에서 이 파일들과 다시 빌드한 패키지 내용을 확인한다. 정식 게시 대상 저장소, 네임스페이스, 좌표, 버전 및 게시 권한은 별도 승인 대상이다. [후보 패키지와 의존성 그래프](24-STARTERS-CLI-RELEASE-GATES.md) · [Apache-2.0 원문](https://www.apache.org/licenses/LICENSE-2.0) · [Central 게시 요건](https://central.sonatype.org/publish/requirements/)

라이선스를 적용한 후보 빌드가 통과했다. 기존 패키지 30개 해시를 재현하고, 새 후보의 POM 6개에 Apache-2.0이 표기됐으며 JAR 18개에 LICENSE와 NOTICE가 들어 있는지 확인했다. 기존 아카이브 항목, 의존성 그래프와 모듈 체크섬을 검증했다. 검증 후 임시 후보 저장소를 회수했다. [라이선스 적용 후보 증거](../../evidence/RELEASE-G0-CANDIDATE.json)

## G5 제한된 네이티브 DB 실행 (RELEASE-005)

| 항목 | 승인 한도 |
|---|---|
| 대상 | 일회용 네이티브 PostgreSQL 17.11 / JDBC 42.7.14 및 MySQL 8.0.46 / Connector/J 26.10.0. 루프백에서 DB를 하나씩 실행한다. 운영 연결은 피하고 보존 중인 컨테이너 12개를 유지한다. |
| 작업 | DB마다 동시 진행 최대 2건, 시작 최대 48건이다. 시작 간격은 최소 250 ms이며 임의의 연속 1초 동안 최대 4건을 시작한다. 소규모 고정 fixture에서 준비된 읽기와 단일 행 쓰기의 완료·실패·커밋·롤백을 관측한다. |
| 시간 | 전체 최대 300초, 네이티브 DB별 기동 최대 60초, DB 서버별 수명 최대 150초다. |
| 자원 | DB별 소유 프로세스 트리의 PID는 최대 48개, RSS 합계는 최대 1 GiB다. DB 임시 작업 공간은 최대 768 MiB이며 프로세스별 CPU 시간은 최대 90초다. 클라이언트 JVM 힙은 256 MiB, 활성 CPU는 2개, 자식 로그는 최대 16 MiB로 제한한다. |
| 상태 확인 및 정리 | 작업 시작 전에 루프백 리스너의 소유권과 접속 상태를 확인한다. 오류나 한도 초과 시 중지하고 소유 프로세스가 종료됐는지와 임시 파일이 정리됐는지 검증한다. |
| 증거 | 정확한 실행 환경, 실측값, 완료·실패 건수, 정리 상태를 기록한다. 결과는 실행한 조합에 한정한다. |

승인은 이 한도 안에서의 1회 실행에 적용된다. 현재 제품 합격 기준과 동시성·풀·취소·복구 검증 상태는 제품 G5 증거에 기록한다. [기존 G5 계획](30-RELEASE-SUPPORT-EVIDENCE.md#g5-1차-실행-계획) · [제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md) · [기존 기능 복구 증거](../../evidence/DB-RECOVERY-VALIDATION.json)

## G5 파일럿 결과

| DB / 드라이버 | 시작 / 완료 | 읽기 / 커밋 / 롤백 | 독립 검증 | 오류 | 최대 동시 진행 | 연속 1초당 최대 시작 | p50 / p95 / 최대 (µs) |
|---|---:|---:|---:|---:|---:|---:|---:|
| PostgreSQL 17.11 / JDBC 42.7.14 | 48 / 48 | 16 / 16 / 16 | 48 | 0 | 2 | 4 | 527 / 1,015 / 1,406 |
| MySQL 8.0.46 / Connector/J 26.10.0 | 48 / 48 | 16 / 16 / 16 | 48 | 0 | 2 | 4 | 1,087 / 3,379 / 12,196 |

지연 시간은 이 파일럿의 준비된 JDBC 작업과 트랜잭션 결과를 관측한 값이며 작업 시작 간격 및 의도적인 동기화 대기 시간은 측정에서 제외했다. 두 임시 네이티브 서버는 종료됐으며 임시 파일은 자동 회수됐다. 이번 실행으로 G5 1회 승인을 소진했다. 추가 실행에는 별도 승인이 필요하다. 제품 성능 및 지원 인증은 미완료 상태다. [G5 파일럿 증거](../../evidence/RELEASE-G5-PILOT.json)

## 이전 제안 검증 증거

이전 제안은 `python3 -B tools/verify-release-approval-scope.py`로 아티팩트 범위·네이티브 DB와 드라이버·자원 한도를 보존 증거와 대조했다. 범위 검사와 Core smoke가 통과했다. 게시 게이트는 기존 증거를 검증하고 종료 코드 2로 배포를 차단했다. 이 검증 증거에는 제안 당시의 두 승인 상태가 PENDING으로 기록되어 있다. [기계 판독용 제안](../../tools/phase6-approval-scope.json) · [검증 증거](../../evidence/RELEASE-APPROVAL-SCOPE.json)
