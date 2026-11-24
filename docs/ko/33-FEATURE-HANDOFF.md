# 기능 개발 핸드오프

[English](../en/33-FEATURE-HANDOFF.md) | 한국어

## ThingsBoard CE 외부 파일럿 검증

독립 공개 애플리케이션인 ThingsBoard CE `v4.3.1.8`을 선정했다. 고정 체크아웃에서 장치 등록 성공 및 롤백 메서드를 확인했다. 기존 합성 H2 주문 재실행 결과는 별도 증거로 보존한다. [ThingsBoard 파일럿 전제조건](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-외부-파일럿)

## 검증 범위

ThingsBoard 장치 등록·롤백 기준선과 Hibernate Observe OFF/ON 비교를 통과했다. 이어 검증한 상류 COUNT 변경을 PostgreSQL에서 재현해 업무 결과 단언과 PR 보고서 탐지를 통과했다. [외부 파일럿 증거](../../evidence/THINGSBOARD-OBSERVE-AND-SQL-CHANGE-VALIDATION.json)

NEXT-005 담당자 직접 검토를 완료했다. 설정 16.368초와 직접 확인을 포함한 검증 45.044초를 확인했다. 수행자 역할은 자기 선언이다. [직접 검토 증거](../../evidence/THINGSBOARD-NEXT-005-MAINTAINER-REVIEW.json)

같은 장치 DAO의 별도 PR #14036에서도 고객 ID 반환 컬럼 추가를 탐지했고 PR 보고서가 영향 테스트 한 건을 정확히 연결했다. 격리 PostgreSQL 결과 단언 3건, UUID 대조군 변경 0건과 정리를 확인했다. [추가 SQL 재현 증거](../../evidence/THINGSBOARD-DEVICE-DAO-FOLLOWUP-VALIDATION.json)

## 후속 작업

NEXT-004의 쿼리별 실DB 회귀에 이 장치 조회를 연결한다. 격리 PostgreSQL에서 고객 ID 컬럼이 있는 기준 환경과 빠진 비교 환경을 대조한다. 영향 분석에서 장치 조회의 등록된 재현 테스트 한 건을 선택하고, 쿼리가 사용하지 않는 컬럼의 변경은 대조군으로 제외되는지 확인한다. [스키마 영향·실DB 회귀 계획](27-SCHEMA-IMPACT-REGRESSION.md)

공개 배포는 보류한다. 공식 성능 시험과 남은 DB 지원 검증은 문서화된 선행조건을 충족한 뒤 재개한다. [배포와 지원 증거](30-RELEASE-SUPPORT-EVIDENCE.md) · [제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md)
