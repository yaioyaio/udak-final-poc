# 배포 승인 범위

[English](../en/31-RELEASE-APPROVAL-SCOPE.md) | 한국어

G0는 아래 Apache-2.0 적용 범위에 대해 **APPROVED**다. G5 1차 파일럿의 **PASS**는 해당 실행에 적용된다. 제품 G5와 정식 배포는 **BLOCKED**(`authorize_publish=false`)이며 제품 지원은 **NOT CERTIFIED**다. [배포 게이트와 지원 증거](30-RELEASE-SUPPORT-EVIDENCE.md) · [승인 결정](../../evidence/RELEASE-G0-G5-DECISION.json)

## G0 프로젝트 라이선스 및 배포 (RELEASE-004)

공개 대상인 UDAK 소유 소스에 Apache-2.0을 적용하고 해당 제3자 고지를 보존한다. 승인된 상업적 사용 범위는 버전 `0.1.0-poc`에서 검토한 범위와 `dev.udak`의 thin Maven 패키지 6종(`core`, `udak-api`, `jdbc-spring`, `observe-core`, `starter-boot3`, `starter-boot4`)이다. 바이너리 배포에서는 JDBC 드라이버, DB 이미지, 테스트 하네스, 외부 바이너리 JAR, fat 데모 JAR를 제외한다.

검토 근거는 모듈별 JAR·POM·Gradle 메타데이터·sources JAR·Javadoc JAR 30개와 SBOM·NOTICE·체크섬 등 5개다. 소비자 및 테스트 그래프의 외부 의존성 29개를 동봉 범위와 구분한다. `approval-history`와 별도 `rewrite-*` 모듈은 위 Maven 배포 목록에서 제외한다. 후보에 LICENSE·NOTICE와 Maven POM 라이선스 표기를 포함한다. 후보 검증에서 이 파일들과 다시 빌드한 패키지 내용을 확인한다. 정식 게시 대상 저장소, 네임스페이스, 좌표, 버전 및 게시 권한은 별도 승인 대상이다. [후보 패키지와 의존성 그래프](24-STARTERS-CLI-RELEASE-GATES.md) · [Apache-2.0 원문](https://www.apache.org/licenses/LICENSE-2.0) · [Central 게시 요건](https://central.sonatype.org/publish/requirements/)

라이선스를 적용한 후보 빌드가 통과했다. 기존 패키지 30개 해시를 재현하고, 새 후보의 POM 6개에 Apache-2.0이 표기됐으며 JAR 18개에 LICENSE와 NOTICE가 들어 있는지 확인했다. 기존 아카이브 항목, 의존성 그래프와 모듈 체크섬을 검증했다. 검증 후 임시 후보 저장소를 회수했다. [라이선스 적용 후보 증거](../../evidence/RELEASE-G0-CANDIDATE.json)

## 정식 게시 범위 결정안 (RELEASE-034)

아래 항목은 책임자 승인 대기(**PENDING**)다. 기존 G0 범위와 POC 버전을 기준으로 제안한다.

| 결정 항목 | 제안과 확인할 근거 |
|---|---|
| 게시 대상과 방식 | Central Publisher Portal을 통해 Maven Central에 게시한다. Portal 검증을 통과하면 권한을 가진 게시 담당자가 수동으로 게시를 확정한다. 게시 대상과 방식에 대한 책임자 승인을 받는다. |
| 네임스페이스 | 소유권과 Portal 게시 권한을 확인할 수 있으면 `dev.udak`을 사용한다. 책임자가 다른 네임스페이스를 선택하면 재빌드 전에 변경된 좌표와 소비자 메타데이터를 G0 승인 범위와 대조한다. |
| 릴리스 좌표 | POC 좌표로 `dev.udak:core:0.1.0-poc`, `dev.udak:udak-api:0.1.0-poc`, `dev.udak:jdbc-spring:0.1.0-poc`, `dev.udak:observe-core:0.1.0-poc`, `dev.udak:starter-boot3:0.1.0-poc`, `dev.udak:starter-boot4:0.1.0-poc`을 승인 대상으로 삼는다. 게시 전에 대상 저장소에서 버전 사용 가능 여부를 확인한다. |
| 권한과 서명 | 릴리스 승인자, 운영 서명 담당자, Portal 게시 담당자를 지정한다. 승인 기록에 허용된 네임스페이스, 좌표와 후보 리비전을 명시한다. 필수 검증을 통과한 뒤 업로드와 게시에 대한 1회 권한을 부여한다. 자격 증명과 서명 키는 저장소 외부에서 관리한다. |

Portal의 네임스페이스 검증과 수동 게시 절차를 적용한다. 제출 전에 후보의 메타데이터, 소스, Javadoc, 체크섬과 분리 서명이 게시 대상의 요구를 충족하는지 확인한다. [Central 네임스페이스 검증](https://central.sonatype.org/register/namespace/) · [Central 게시 요건](https://central.sonatype.org/publish/requirements/) · [Central Portal 검증과 게시](https://central.sonatype.org/publish/publish-portal-guide/)

후보 검토에서는 빌드 입력과 아카이브 해시를 승인된 커밋 하나에 연결하고, 모듈 파일 30개와 지원 파일 5개 및 위 G0 제외 범위 준수를 확인한다. 정식 게시에는 운영 서명 검증, 제품 G5 PASS, 대상 저장소에 맞는 게시 경로와 해당 후보의 명시적 게시 승인도 필요하다. 오프라인 검증에서 현재 게이트 차단과 각 선행조건의 증거를 확인했다. [게시 게이트 오프라인 검증](30-RELEASE-SUPPORT-EVIDENCE.md#release-034-게시-게이트-오프라인-검증)

### 게시 대상 조회와 담당 역할 (RELEASE-035)

공개 조회 대상은 Maven Central이었다. 수동 게시 결정안은 책임자 결정 대기다. 제안한 POC 좌표 6개는 각각 POM과 버전 경로에서 HTTP 404를 반환했다. 대조군의 두 경로는 모두 HTTP 200을 반환했다. 이 결과는 조회 시점의 공개 상태를 기록한다. 네임스페이스 예약과 게시 권한은 별도로 확인해야 한다. [공개 저장소 조회 기록](../../evidence/RELEASE-PUBLICATION-REGISTRY-CHECK.json)

`udak.dev`의 NS 질의에 공개 DNS는 `NXDOMAIN`을 반환했다. 책임자가 DNS 관리 권한을 확인하고, Portal에서 지정된 게시 역할의 권한과 네임스페이스 검증 완료 상태가 확인될 때까지 `dev.udak`을 후보로 둔다. 이 경로를 사용할 수 없으면 책임자가 관리 가능한 도메인이나 검증된 코드 호스팅 네임스페이스를 선택한다. 새 선택으로 후보를 빌드하기 전에 변경된 GAV 좌표를 G0 승인 범위와 대조한다. [Central 네임스페이스 검증](https://central.sonatype.org/register/namespace/)

| 역할 | 책임 | 담당자 지정 |
|---|---|---|
| 릴리스 승인자 | 대상, 네임스페이스, 정확한 GAV와 후보 리비전을 승인한다. 검증된 번들에 연결해 최종 1회 게시 결정을 기록한다. | PENDING |
| 운영 서명 담당자 | 승인된 번들을 서명하고 동일 번들에 연결된 서명 검증 증거를 제공한다. | PENDING |
| Portal 게시 담당자 | 선택한 네임스페이스의 게시 권한을 확인한다. Portal 검증과 최종 승인 후 수동으로 게시를 확정한다. | PENDING |

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
