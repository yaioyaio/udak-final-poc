# 기능 개발 핸드오프

[English](../en/33-FEATURE-HANDOFF.md) | 한국어

## ThingsBoard CE 외부 파일럿 의존성

독립 공개 애플리케이션인 ThingsBoard CE `v4.3.1.8`을 선정했다. 고정 체크아웃에서 장치 등록 성공 및 롤백 메서드를 확인했다. 기존 합성 H2 주문 재실행 결과는 별도 증거로 보존한다. [ThingsBoard 파일럿 전제조건](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-외부-파일럿)

## 검증 범위

공식 게시 DAO 테스트 JAR로 격리 PostgreSQL 18에서 ThingsBoard 장치 등록·롤백 기준선을 통과했다. 두 차례 실행에서 각각 테스트 2건과 실패·오류·건너뜀 0건을 기록했다. 새 PostgreSQL 시험 컨테이너가 관측됐고 종료 후 정리를 검증했다. [PostgreSQL 기준선 증거](../../evidence/THINGSBOARD-DEVICE-BASELINE-VALIDATION.json)

## 후속 작업

Hibernate에 테스트 전용 설정으로 Observe를 연결한다. 신규 PostgreSQL 시험 인스턴스에서 같은 두 메서드를 Observe OFF와 ON으로 실행한다. 장치 등록 결과, 롤백 단언, 관측 범위와 연결에 든 시간을 비교한다. 비교를 통과하면 검토된 상류 SQL 변경을 PR 보고서가 탐지하는지 확인한다. [파일럿 절차](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-외부-파일럿)

공개 배포는 보류한다. 공식 성능 시험과 남은 DB 지원 검증은 문서화된 선행조건을 충족한 뒤 재개한다. [배포와 지원 증거](30-RELEASE-SUPPORT-EVIDENCE.md) · [제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md)
