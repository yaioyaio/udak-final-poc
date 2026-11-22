# 기능 개발 핸드오프

[English](../en/33-FEATURE-HANDOFF.md) | 한국어

## NEXT-004부터 시작

NEXT-001~NEXT-003은 작업 범위의 검증을 통과했다. Hibernate 합성과 `UNAVAILABLE` 사유별 집계를 포함한다. [추적성](16-TRACEABILITY.md)

## 범위와 인수 조건

JDBC 메타데이터에서 지정 테이블의 컬럼 타입·길이·NULL 여부를 수집한다. 같은 DBMS를 실행하는 두 환경의 검증된 스냅샷을 비교하고 지원하는 변경 유형을 각각 확인한다. 구현 전에 요구 사항과 시험 계획을 등록한다. [개발 지침](13-AGENT-DEVELOPMENT-GUIDE.md)

## 후속 작업

NEXT-004가 통과하면 NEXT-005 도입 지원과 가치 검증을 시작한다. [기능 우선 백로그](09-WBS-ROADMAP.md#기능-우선-백로그)

공개 배포는 보류한다. 공식 성능 시험과 남은 DB 지원 검증은 문서화된 선행조건을 충족한 뒤 재개한다. [배포와 지원 증거](30-RELEASE-SUPPORT-EVIDENCE.md) · [제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md)
