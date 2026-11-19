# 배포 승인 범위 제안

[English](../en/31-RELEASE-APPROVAL-SCOPE.md) | 한국어

권리자의 G0 결정과 운영자의 G5 실행 승인을 기다리고 있다. 정식 배포는 **BLOCKED**(`authorize_publish=false`)다. G0는 **NOT GRANTED**, G5는 **NOT RUN**, 제품 지원은 **NOT CERTIFIED**다. [배포 게이트와 지원 증거](30-RELEASE-SUPPORT-EVIDENCE.md)

## G0 프로젝트 라이선스 및 배포 (RELEASE-004)

공개를 제안하는 UDAK 소유 소스에 Apache-2.0을 적용하고 해당하는 제3자 고지를 보존하는 방안을 제안한다. 버전 `0.1.0-poc`에서 검토한 범위와 `dev.udak`의 thin Maven 패키지 6종(`core`, `udak-api`, `jdbc-spring`, `observe-core`, `starter-boot3`, `starter-boot4`)의 상업적 사용 승인을 요청한다. 바이너리 배포에서는 JDBC 드라이버, DB 이미지, 테스트 하네스, 외부 바이너리 JAR, fat 데모 JAR를 제외한다.

검토 근거는 모듈별 JAR·POM·Gradle 메타데이터·sources JAR·Javadoc JAR 30개와 SBOM·NOTICE·체크섬 등 5개다. 소비자 및 테스트 그래프의 외부 의존성 29개를 동봉 범위와 구분한다. `approval-history`와 별도 `rewrite-*` 모듈은 위 Maven 배포 목록에서 제외한다. 공개 소스의 UDAK 소유 범위와 해당하는 제3자 고지는 권리자 결정에 기록한다. 승인 후 LICENSE·NOTICE와 POM 라이선스 표기를 갖추고 후보를 다시 빌드해 내용을 대조한다. 게시 대상 저장소, 네임스페이스, 좌표, 버전, 게시 권한자는 별도 승인을 받는다. [후보 패키지와 의존성 그래프](24-STARTERS-CLI-RELEASE-GATES.md) · [Apache-2.0 원문](https://www.apache.org/licenses/LICENSE-2.0) · [Central 게시 요건](https://central.sonatype.org/publish/requirements/)

## G5 제한된 네이티브 DB 실행 (RELEASE-005)

| 항목 | 제안 한도 |
|---|---|
| 대상 | 일회용 네이티브 PostgreSQL 17.11 / JDBC 42.7.14 및 MySQL 8.0.46 / Connector/J 26.10.0. 루프백에서 DB를 하나씩 실행한다. 운영 연결은 피하고 보존 중인 컨테이너 12개를 유지한다. |
| 작업 | DB마다 동시 진행 최대 2건, 시작 최대 48건이다. 시작 간격은 최소 250 ms이며 임의의 연속 1초 동안 최대 4건을 시작한다. 소규모 고정 fixture에서 준비된 읽기와 단일 행 쓰기의 완료·실패·커밋·롤백을 관측한다. |
| 시간 | 전체 최대 300초, 네이티브 DB별 기동 최대 60초, DB 서버별 수명 최대 150초다. |
| 자원 | DB별 소유 프로세스 트리의 PID는 최대 48개, RSS 합계는 최대 1 GiB다. DB 임시 작업 공간은 최대 768 MiB이며 프로세스별 CPU 시간은 최대 90초다. 클라이언트 JVM 힙은 256 MiB, 활성 CPU는 2개, 자식 로그는 최대 16 MiB로 제한한다. |
| 상태 확인 및 정리 | 작업 시작 전에 루프백 리스너의 소유권과 접속 상태를 확인한다. 오류나 한도 초과 시 중지하고 소유 프로세스가 종료됐는지와 임시 파일이 정리됐는지 검증한다. |
| 증거 | 정확한 실행 환경, 실측값, 완료·실패 건수, 정리 상태를 기록한다. 결과는 실행한 조합에 한정한다. |

운영자의 결정은 이 한도 안에서의 1회 실행에 적용된다. 제품 성능 합격 기준은 미정이다. 제품 인증에는 추가 DB·플랫폼 조합의 동시성·풀·취소·복구 증거도 필요하다. [기존 G5 계획](30-RELEASE-SUPPORT-EVIDENCE.md#g5-1차-실행-계획) · [기존 기능 복구 증거](../../evidence/DB-RECOVERY-VALIDATION.json)

## 승인 범위 검증

저장소 루트에서 `python3 -B tools/verify-release-approval-scope.py`를 실행해 제안서의 아티팩트 범위·네이티브 DB와 드라이버·자원 한도를 보존 증거와 대조한다. 범위 검사와 Core smoke가 통과했다. 게시 게이트는 기존 증거를 검증하고 종료 코드 2로 배포를 차단했다. 실행 증거의 두 승인 상태는 PENDING이다. [기계 판독용 제안](../../tools/phase6-approval-scope.json) · [검증 증거](../../evidence/RELEASE-APPROVAL-SCOPE.json)
