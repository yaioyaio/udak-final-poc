# 기능 개발 핸드오프

[English](../en/33-FEATURE-HANDOFF.md) | 한국어

## NEXT-002부터 시작

- 기록일은 2026-11-21이다.
- 검토 기준은 `develop`의 `5694c55`다.
- NEXT-001은 2026-11-22 보호 Core 스모크를 통과했다. NEXT-002는 TODO다.
- 제품 기능 완성을 우선한다. 안전한 진단 출력과 레거시 SQL 인벤토리부터 진행한다. [기능 우선 백로그](09-WBS-ROADMAP.md#기능-우선-백로그)

## 범위와 인수 조건

명시한 로컬 MyBatis Mapper XML의 스캐너를 기존 base/head PR 보고서에 연결한다. 제한된 fixture에서 쿼리 추가·변경, 동적 치환 및 미지원 사례를 검증한다. [SQL 인벤토리와 PR 보고서](25-SQL-INVENTORY-PR-REPORT.md)

- 파일·줄·분류·해시 출력을 확인한다. 외부 엔터티와 네트워크 접근을 차단한다.
- 기존 인벤토리 비교 계약을 지키고 인벤토리 회귀와 보호 Core 스모크를 실행한다.
- 최신 `develop`에서 feature 브랜치로 시작한다. 구현 전에 한·영 추적성 문서에 요구 ID와 테스트 계획을 등록한다. [추적성](16-TRACEABILITY.md) · [개발 지침](13-AGENT-DEVELOPMENT-GUIDE.md)

## 후속 작업

NEXT-002가 통과하면 NEXT-003에서 기존 Hibernate inspector를 보존하는 명시적 합성부터 진행한다. [기능 우선 백로그](09-WBS-ROADMAP.md#기능-우선-백로그)

공개 배포는 보류한다. 공식 성능 시험과 남은 DB 지원 검증은 문서화된 선행조건을 충족한 뒤 재개한다. [배포와 지원 증거](30-RELEASE-SUPPORT-EVIDENCE.md) · [제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md)
