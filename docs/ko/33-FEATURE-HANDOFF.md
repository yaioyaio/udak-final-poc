# 기능 개발 핸드오프

[English](../en/33-FEATURE-HANDOFF.md) | 한국어

## ThingsBoard CE 외부 파일럿 검증

독립 공개 애플리케이션인 ThingsBoard CE `v4.3.1.8`을 선정했다. 고정 체크아웃에서 장치 등록 성공 및 롤백 메서드를 확인했다. 기존 합성 H2 주문 재실행 결과는 별도 증거로 보존한다. [ThingsBoard 파일럿 전제조건](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-외부-파일럿)

## 검증 범위

ThingsBoard 장치 등록·롤백 기준선과 Hibernate Observe OFF/ON 비교를 통과했다. 이어 검증한 상류 COUNT 변경을 PostgreSQL에서 재현해 업무 결과 단언과 PR 보고서 탐지를 통과했다. [외부 파일럿 증거](../../evidence/THINGSBOARD-OBSERVE-AND-SQL-CHANGE-VALIDATION.json)

NEXT-005 담당자 직접 검토를 완료했다. 설정 16.368초와 직접 확인을 포함한 검증 45.044초를 확인했다. 수행자 역할은 자기 선언이다. [직접 검토 증거](../../evidence/THINGSBOARD-NEXT-005-MAINTAINER-REVIEW.json)

같은 장치 DAO의 별도 PR #14036에서도 고객 ID 반환 컬럼 추가를 탐지했고 PR 보고서가 영향 테스트 한 건을 정확히 연결했다. 격리 PostgreSQL 결과 단언 3건, UUID 대조군 변경 0건과 정리를 확인했다. [추가 SQL 재현 증거](../../evidence/THINGSBOARD-DEVICE-DAO-FOLLOWUP-VALIDATION.json)

PR #14036의 장치 조회를 NEXT-004 스키마 영향 분석에 연결했다. 격리 PostgreSQL에서 고객 ID 누락은 등록 테스트 한 건을 선정했고 재실행으로 `42703`을 확인했다. 미사용 컬럼 변경은 0건이었다. [장치 스키마 영향 증거](../../evidence/THINGSBOARD-DEVICE-SCHEMA-IMPACT-VALIDATION.json)

NEXT-004의 환경 간 수집·비교를 PostgreSQL로 확장했다. 같은 리비전의 로컬·개발 모사 DB에서 읽기 전용으로 수집했다. 컬럼 구성이 같으면 `MATCH`, `customer_id`가 빠지면 `DRIFT`와 제거 1건을 반환했다. [PostgreSQL 검증 증거](../../evidence/POSTGRESQL-SCHEMA-DRIFT-VALIDATION.json)

NEXT-004의 PostgreSQL 스냅샷을 기존 마이그레이션 이력 대조에 연결했다. 검토한 버전·체크섬·컬럼 변경이 일치하면 `MATCHED`였다. 이력 누락, 버전·체크섬 불일치 및 추가 컬럼 변경은 각각 `UNRESOLVED`였다. [PostgreSQL 이력 대조 증거](../../evidence/POSTGRESQL-SCHEMA-MIGRATION-VALIDATION.json)

격리 PostgreSQL에서 Flyway가 실제 적용한 V002 이력을 읽기 전용으로 수집했다. 검토 파일의 적용 당시 증거가 일치한 경우만 기존 대조기에 전달했다. 이력 누락은 `HISTORY_MISSING`이었고, 적용 당시 증거가 없거나 파일 SHA-256이 다르면 입력 생성을 차단했다. [Flyway 이력 검증 증거](../../evidence/POSTGRESQL-FLYWAY-HISTORY-VALIDATION.json)

선택형 PR 보고서에서 동일한 `device.customer_id` 제거의 Flyway 판정과 등록 테스트 1건을 표시했다. 이력 누락과 파일 근거 미확인은 사유와 테스트 후보를 표시하고 종료 코드 2로 판정했다. [PR 보고서 통합 증거](../../evidence/POSTGRESQL-FLYWAY-PR-SCHEMA-REVIEW-VALIDATION.json)

`run-sql-inventory.py --pr-report`에 선택형 스키마 검토를 연결했다. 기존 CLI의 보고서와 종료 코드를 그대로 전달하며, Flyway 네 사례와 SQL 전용 호출에서 동일한 결과를 확인했다. [보호 로컬 PR 검증 증거](../../evidence/GUARDED-LOCAL-PR-SCHEMA-REVIEW-VALIDATION.json)

보호 PR 보고서가 선정한 ThingsBoard 장치 조회 한 건을 등록 재현에 연결했다. 격리 PostgreSQL의 대상 스키마 해시 확인 뒤 `42703`을 재현했다. 미해결 이력, 미등록 해시, 스키마 불일치는 대상 조회 전에 차단했다. [등록 재실행 검증 증거](../../evidence/GUARDED-PR-REGISTERED-REPLAY-VALIDATION.json)

보호 PR 보고서는 원본 보고서·등록 테스트·실행 대상 스키마 해시를 대조한 뒤 JSON과 Markdown에 재실행 판정을 표시한다. 격리 PostgreSQL의 ThingsBoard 조회 한 건은 두 형식에 `VERIFIED`와 재현 결과 `PASS`를 표시했다. 누락, 잘못된 기록, 해시 불일치, 불완전 보고서는 `UNVERIFIED`로 검증했다. [판정 표시 증거](../../evidence/GUARDED-PR-REPLAY-VERDICT-VALIDATION.json)

NEXT-004의 MySQL 8.0 컬럼 계약 수집을 기존 비교 CLI에 연결했다. 격리 MySQL 8.0.46에서 단언 27건, MATCH, DRIFT 5종, 다른 DBMS 범위 거부와 정리를 검증했다. [MySQL 증거](../../evidence/MYSQL-SCHEMA-DRIFT-VALIDATION.json)

NEXT-004의 실제 MySQL Flyway 이력을 기존 보호 PR 보고서에 연결했다. 격리 MySQL의 일치·누락·체크섬 불일치·증거 미확인 단언 61건과 PostgreSQL Flyway PR 회귀 단언 25건이 통과했다. [MySQL Flyway 검증 증거](../../evidence/MYSQL-FLYWAY-HISTORY-VALIDATION.json)

T-007 Fluent JOIN의 API·렌더링 단언 52개와 Spring JDBC/H2·PostgreSQL·MySQL 각각의 11개 단언이 통과했다. 실DB는 복합 조인, NULL, 바인딩·페이지, 커밋 전 가시성과 롤백을 검증했고 시험 자원을 정리했다. [T-007 실DB 증거](../../evidence/FLUENT-JOIN-REAL-DB-VALIDATION.json)

T-001 고객 업무 흐름 5건과 대조군·측정 기준을 정의했다. 한·영 문서와 보존된 기술 증거의 대조는 통과했다. 고객 직접 확인은 남아 있다. 승인된 유지보수 팀 한 곳의 업무 흐름 하나부터 현장 검증을 시작한다. [시나리오 증거](../../evidence/T-001-CUSTOMER-SCENARIO-VALIDATION.json)

T-001-S2 로컬 대행 비교를 임베디드 H2와 격리 PostgreSQL에서 통과했다. Git diff와 UDAK 모두 COUNT 변경 1건을 찾고 UUID 대조군의 오탐 0건을 기록했으며 같은 등록 재현 테스트를 선정했다. 고객 직접 비교는 NOT RUN이다. [로컬 대행 증거](../../evidence/T-001-LOCAL-PAIRED-REVIEW.json) · [비교 절차](34-LEGACY-ADOPTION-PILOT.md#t-001-동일-담당자-비교-검토) · [PostgreSQL 로컬 대행 증거](../../evidence/T-001-LOCAL-PAIRED-REVIEW-POSTGRESQL.json)

T-001-S2 독립 로컬 검토자가 순서대로 Git diff와 UDAK 보호 PR 보고서를 검토해 같은 판정과 등록 회귀 테스트를 선택했다. 외부 유지보수팀 승인은 확인되지 않았으며 고객 직접 비교는 NOT RUN이다. [로컬 검토자 기록](../../evidence/T-001-LOCAL-OPERATOR-PAIRED-REVIEW.json)

RELEASE-021 로컬 번들 리허설을 통과했다. 모듈 6종의 파일 30개, 고정 의존성, ZIP·매니페스트 시험 서명과 정리를 검증했다. [전체 리허설 증거](../../evidence/RELEASE-READINESS-LOCAL.json)

RELEASE-021 현재 비공개 G6와 보호 로컬 CI가 통과했다. 독립 게시 게이트는 `VERIFIED_EVIDENCE`를 반환한다. 다음은 로컬에서 가능한 제품 G5의 선행조건과 남은 DB 지원 범위를 확인하는 단계다. [보호 로컬 CI](../../evidence/PHASE6-CURRENT-LOCAL-CI.json) · [비공개 G6](../../evidence/PHASE6-CURRENT-GATE.json) · [독립 게시 게이트 대조](../../evidence/PHASE6-CURRENT-PUBLICATION-CHECK.json)

## 후속 작업

캐시 미적중에서 측정한 984 B/op 중 지문 계산 704 B/op(71.5%)를 우선 개선한다. 먼저 암묵 Query ID 해시의 문자열 결합과 UTF-8 변환에서 생기는 임시 객체를 줄이는 후보를 검토하고, 기존 지문·Query ID와 회귀 테스트를 검증한 뒤 같은 DB 없는 하네스로 비교한다. [할당 실측 증거](../../evidence/OBSERVE-L1-JDBC-ALLOCATION-ATTRIBUTION-01-RESULT.json)

2026-11-28 로컬 제품 G5 점검에서 Core 스모크와 오프라인 72건이 통과했다. 실DB 기능 갱신은 메모리 압력 2단계로 **NOT RUN**이다. 다음은 정상 상태에서 PostgreSQL·MySQL 16건과 기존 Oracle 시험 컨테이너 7건의 기능 증거 갱신이다. `OBSERVE-PG-BASELINE-AA-01`의 2026-11-27 예약은 종료됐고 기존 승인 해시는 현재 입력과 다르다. 현재 입력으로 승인한 A/A와 별도 승인한 두 DB의 공식 +5% 인수를 차례로 통과한 뒤 Oracle 인스턴스 사전 점검을 진행한다. 네이티브 SQL Server는 로컬 범위에서 제외했다. [로컬 검증 기록](../../evidence/PRODUCT-G5-LOCAL-SCOPE-20261128.json) · [이전 예약 기록](../../evidence/OBSERVE-PG-BASELINE-AA-01-LOCAL-SCHEDULE.json)
