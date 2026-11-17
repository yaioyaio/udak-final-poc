# Claude Code UDAK 공통 지침

`AGENTS.md`와 `docs/ko/13-AGENT-DEVELOPMENT-GUIDE.md`를 읽고 준수한다(영문 대응: `docs/en/13-AGENT-DEVELOPMENT-GUIDE.md`). Codex, Claude Code와 모든 작업자에게 동일하게 적용한다.

- 답변·보고는 한국어로 한다. 주 세션이 지휘하고, 작업 적합성과 비용을 고려해 필요한 서브에이전트를 사용하며 결과와 최종 검증을 직접 확인한다.
- 편집 전 브랜치를 확인한다. 새 브랜치는 `feature/{오늘날짜 YYYYMMDD}-{영문기능요약}`이며 main/develop에서 직접 편집하지 않는다.
- 금지 항목을 `.gitignore`·`.dockerignore`로 차단하고, 작성자·세션과 무관하게 금지 대상 외 전체 산출물을 확인한다.
- feature 커밋/푸시 → PR(develop) 병합 → PR(main) 병합 → 로컬/원격 6참조 파일 diff 일치 검증 순서를 따른다. Actions는 사용하지 않고 원격 브랜치는 보존하며 마감 후 develop으로 전환한다.
- 시크릿 파일과 민감값은 읽거나 노출하지 않으며 위임 시 같은 규칙을 전달한다.
- SSOT 요구 ID와 테스트 증거를 유지한다. 승인 없는 Rewrite와 분산 트랜잭션 보장 주장은 금지한다.
- 메인 `README.md`는 영문, `README-KO.md`는 한국어다. `docs/en/`·`docs/ko/`의 같은 이름 문서를 한 쌍으로 함께 갱신하고 요구 ID·명령·버전·검증 상태를 일치시킨다.
