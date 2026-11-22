# 기능 개발 핸드오프

[English](../en/33-FEATURE-HANDOFF.md) | 한국어

## 한 SQL 변경의 여러 관측 지점 검토

NEXT-005는 사용자 지정 독립 H2 주문 서비스에서 통과했다. 운영 레거시 적용은 NOT RUN이다. 재고 조건 변경은 MyBatis와 JDBC의 관측을 근거로 한 번 검토했다. [파일럿 결과](34-LEGACY-ADOPTION-PILOT.md#독립-주문-서비스-파일럿) · [추적성](16-TRACEABILITY.md)

## 범위와 인수 조건

인벤토리 PR 보고서에서 한 SQL 형태 변경을 확인한 두 관측 지점의 근거를 함께 볼 수 있도록 개선한다. 관측 지점을 보존하고 관련 없는 쿼리는 개별 후보로 표시한다. 재고 SQL 변경과 바인딩 값 대조군으로 검증한다. [인벤토리 보고서](25-SQL-INVENTORY-PR-REPORT.md)

## 후속 작업

검토 결과를 토대로 도입 예제나 관측 공백 진단의 보완 대상을 정한다. [기능 우선 백로그](09-WBS-ROADMAP.md#기능-우선-백로그)

공개 배포는 보류한다. 공식 성능 시험과 남은 DB 지원 검증은 문서화된 선행조건을 충족한 뒤 재개한다. [배포와 지원 증거](30-RELEASE-SUPPORT-EVIDENCE.md) · [제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md)
