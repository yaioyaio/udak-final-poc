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

## 후속 작업

선택형 스키마 검토를 기존 보호 로컬 PR 검증에 연결한다. 검증된 사례와 미해결 사례에서 보고서와 종료 코드가 그대로 전달되는지 확인한다. 기존 SQL 전용 호출도 함께 검증한다. [선택형 PR 보고서](25-SQL-INVENTORY-PR-REPORT.md#선택형-스키마-변경과-flyway-이력-검토)

공개 배포는 보류한다. 공식 성능 시험과 남은 DB 지원 검증은 문서화된 선행조건을 충족한 뒤 재개한다. [배포와 지원 증거](30-RELEASE-SUPPORT-EVIDENCE.md) · [제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md)
