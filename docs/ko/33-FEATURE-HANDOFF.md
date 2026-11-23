# 기능 개발 핸드오프

[English](../en/33-FEATURE-HANDOFF.md) | 한국어

## 주문 재고 UPDATE 의존성 검증 완료

MyBatis 재고 UPDATE의 두 분기에서 추출한 참조가 검토한 SET·WHERE 참조와 일치했다. `active` 컬럼 변경은 활성 재고 조건을 켠 테스트만 선정했다. 미사용 컬럼 대조군의 선정은 0건이었다. [재고 UPDATE 회귀](27-SCHEMA-IMPACT-REGRESSION.md#렌더링된-주문-재고-update-의존성-검증)

## 검증 범위

보호 H2 실행에서 수집 단언 89개, 재실행 단언 27개, 추출 계약 16건, 스키마 영향 계약 17건과 Core 스모크를 통과했다. 동적·모호한 SQL은 미해결로 남았다. ON 의존성 누락은 `INCOMPLETE`였고 재실행은 스키마 해시 불일치를 거부했다. 외부 DB 연동은 NOT RUN이다. [주문 재고 UPDATE 검증 증거](../../evidence/ORDER-STOCK-UPDATE-VALIDATION.json)

## 후속 작업

같은 Query ID에서 SQL 지문이 여러 개 관측되는 경우의 의존성 검증 범위를 확인한다. 의존성이 누락되거나 검토되지 않은 지문이 있으면 해당 범위의 영향 보고서가 `INCOMPLETE`로 남고, 모든 지문을 검토하면 예상한 테스트가 선정되는지 검증한다. [기능 우선 백로그](09-WBS-ROADMAP.md#기능-우선-백로그)

공개 배포는 보류한다. 공식 성능 시험과 남은 DB 지원 검증은 문서화된 선행조건을 충족한 뒤 재개한다. [배포와 지원 증거](30-RELEASE-SUPPORT-EVIDENCE.md) · [제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md)
