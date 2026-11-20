# 기능 개발 핸드오프

[English](../en/33-FEATURE-HANDOFF.md) | 한국어

## NEXT-001부터 시작

- 기록일은 2026-11-21이다.
- 검토 기준은 `develop`의 `5694c55`다.
- 상태는 TODO다. 소스와 보존 증거를 대조했으며 구현과 변경분 회귀 검증은 대기 상태다.
- 제품 기능 완성을 우선한다. 안전한 진단 출력과 레거시 SQL 인벤토리부터 진행한다. [기능 우선 백로그](09-WBS-ROADMAP.md#기능-우선-백로그)

## 범위와 인수 조건

`Bind`, `CompiledQuery`, `QueryDefinition`은 Java record의 자동 생성 문자열 출력을 사용한다. 이 객체를 문자열로 변환하면 바인딩 값, SQL 원문 또는 필터 값이 노출될 수 있다. NEXT-001에서는 NFR-03에 따라 세 타입의 문자열 출력을 안전한 메타데이터로 제한한다. [Core 타입](../../core/src/main/java/dev/udak/core) · [NFR-03](01-PRD.md)

- 합성 표식을 써서 SQL 원문, 바인딩 이름·값, 필터 값이 출력에서 빠지는지 확인한다. `toString()`이 호출되면 실패하는 값 객체를 포함한다.
- 기존 생성자·접근자·동등성·바인딩 순서·실행 계약을 검증한다. 저장소 보호 경로로 `./tools/run-core-smoke.sh`를 실행하고 결과를 기록한다.
- 최신 `develop`에서 feature 브랜치로 시작한다. 구현 전에 한·영 추적성 문서에 요구 ID와 테스트 계획을 등록한다. [추적성](16-TRACEABILITY.md) · [개발 지침](13-AGENT-DEVELOPMENT-GUIDE.md)

## 후속 작업

NEXT-001이 통과하면 NEXT-002에서 로컬 MyBatis Mapper XML 스캐너를 기존 base/head PR 보고서에 연결한다. 외부 엔터티와 네트워크 접근을 차단한 제한된 fixture에서 파일·줄·분류·해시 출력을 확인한다. 이후 과제의 인수 조건은 백로그를 따른다. [SQL 인벤토리와 PR 보고서](25-SQL-INVENTORY-PR-REPORT.md) · [기능 우선 백로그](09-WBS-ROADMAP.md#기능-우선-백로그)

공개 배포는 보류한다. 공식 성능 시험과 남은 DB 지원 검증은 문서화된 선행조건을 충족한 뒤 재개한다. [배포와 지원 증거](30-RELEASE-SUPPORT-EVIDENCE.md) · [제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md)
