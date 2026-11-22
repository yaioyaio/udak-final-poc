# 기능 개발 핸드오프

[English](../en/33-FEATURE-HANDOFF.md) | 한국어

## NEXT-003부터 시작

- 기록일은 2026-11-21이다.
- 검토 기준은 `develop`의 `5694c55`다.
- NEXT-001과 NEXT-002는 2026-11-22 작업 범위의 검증을 통과했다. NEXT-003은 TODO다. [추적성](16-TRACEABILITY.md)
- 제품 기능 완성을 우선한다. 안전한 진단 출력과 레거시 SQL 인벤토리부터 진행한다. [기능 우선 백로그](09-WBS-ROADMAP.md#기능-우선-백로그)

## 범위와 인수 조건

애플리케이션의 기존 Hibernate `StatementInspector`를 보존하면서 최종 SQL을 관측하는 명시적 합성을 추가한다. 기존 레거시 호환성 fixture부터 사용한다. [레거시 Observe 검증](21-LEGACY-OBSERVE-RESULTS.md)

- Observe OFF/ON에서 inspector의 동작, 업무 결과, 롤백, 관측 이벤트를 대조한다.
- 기존 어댑터 계약과 보호 Core 스모크를 검증한다.
- 최신 `develop`에서 feature 브랜치로 시작한다. 구현 전에 한·영 추적성 문서에 요구 ID와 테스트 계획을 등록한다. [추적성](16-TRACEABILITY.md) · [개발 지침](13-AGENT-DEVELOPMENT-GUIDE.md)

## 후속 작업

Hibernate 합성이 통과하면 NEXT-003에서 안전한 `UNAVAILABLE` 사유별 집계를 추가한다. 다음 백로그 묶음은 NEXT-004 스키마 계약과 환경 drift다. [기능 우선 백로그](09-WBS-ROADMAP.md#기능-우선-백로그)

공개 배포는 보류한다. 공식 성능 시험과 남은 DB 지원 검증은 문서화된 선행조건을 충족한 뒤 재개한다. [배포와 지원 증거](30-RELEASE-SUPPORT-EVIDENCE.md) · [제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md)
