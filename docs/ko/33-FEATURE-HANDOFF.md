# 기능 개발 핸드오프

[English](../en/33-FEATURE-HANDOFF.md) | 한국어

## 한 Query ID에서 관측된 지문의 의존성 검증 완료

H2 주문 파일럿에서 MyBatis 지문 두 개를 같은 Query ID로 수집했다. 활성 컬럼 변경은 ON 테스트만 선정했다. 지문 행을 하나라도 빼면 `INCOMPLETE`로 판정하고 확인된 영향은 표시했다. [관측된 지문별 의존성 검증](27-SCHEMA-IMPACT-REGRESSION.md#관측된-지문별-의존성-검증)

## 검증 범위

보호 H2 실행에서 수집 단언 89개, 선정 테스트 재실행 단언 27개, 스키마 영향 계약 30건, 추출 계약 16건과 Core 스모크를 통과했다. 기존 감사 테스트 선정과 마이그레이션 계약 15건도 통과했다. 외부 DB 연동은 NOT RUN이다. [주문 지문 의존성 검증 증거](../../evidence/ORDER-FINGERPRINT-DEPENDENCIES-VALIDATION.json)

## 후속 작업

SQL 인벤토리에 지문과 실제 테스트의 연결을 기록한다. 같은 Query ID에 속한 테스트 해시라도 지문 간 연결을 뒤바꾸면 탐지되는지 검증한다. 기존 v1 인벤토리 읽기 호환성을 유지한다.

공개 배포는 보류한다. 공식 성능 시험과 남은 DB 지원 검증은 문서화된 선행조건을 충족한 뒤 재개한다. [배포와 지원 증거](30-RELEASE-SUPPORT-EVIDENCE.md) · [제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md)
