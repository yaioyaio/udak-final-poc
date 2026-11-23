# 기능 개발 핸드오프

[English](../en/33-FEATURE-HANDOFF.md) | 한국어

## ThingsBoard CE 외부 파일럿 검증

독립 공개 애플리케이션인 ThingsBoard CE `v4.3.1.8`을 선정했다. 고정 체크아웃에서 장치 등록 성공 및 롤백 메서드를 확인했다. 기존 합성 H2 주문 재실행 결과는 별도 증거로 보존한다. [ThingsBoard 파일럿 전제조건](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-외부-파일럿)

## 검증 범위

ThingsBoard 장치 등록·롤백 기준선과 Hibernate Observe OFF/ON 비교를 통과했다. 이어 검증한 상류 COUNT 변경을 PostgreSQL에서 재현해 업무 결과 단언과 PR 보고서 탐지를 통과했다. [외부 파일럿 증거](../../evidence/THINGSBOARD-OBSERVE-AND-SQL-CHANGE-VALIDATION.json)

## 후속 작업

유지보수 담당자와 외부 파일럿을 검토한다. COUNT 변경 탐지와 UUID 대조군을 대조하고 수동 설정·검증 시간을 기록한다. 실제 결과를 바탕으로 관측 범위 확대 대상을 정한다. [도입 검토 기준](34-LEGACY-ADOPTION-PILOT.md#승인된-레거시-프로젝트에-적용)

공개 배포는 보류한다. 공식 성능 시험과 남은 DB 지원 검증은 문서화된 선행조건을 충족한 뒤 재개한다. [배포와 지원 증거](30-RELEASE-SUPPORT-EVIDENCE.md) · [제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md)
