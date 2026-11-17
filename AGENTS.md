# UDAK Agents — 공통 안전 지침

## 사용자 확정 작업 규칙 (2026-11-17, 모든 작업자 공통)

1. **언어와 지휘:** 답변·보고는 한국어로 한다. 주 세션은 오케스트레이션 지휘자다. 작업에 맞는 사용 가능한 Codex 모델을 선택해 서브에이전트를 사용하고 토큰 비용과 구현·문서 품질을 함께 고려한다. 간단한 문서·정리는 가벼운 모델, 일반 구현은 중간 등급, 설계·보안·독립 검토는 강한 모델을 우선 고려한다. 필요한 범위만 위임하며 결과는 지휘자가 검증한다. 짧은 확인, merge·push·삭제·배포와 최종 검증은 지휘자가 직접 수행한다.
2. **브랜치:** 편집 전에 `git branch --show-current`를 확인한다. 새 브랜치는 최신 develop에서 `feature/{오늘날짜 YYYYMMDD}-{영문기능요약}`으로 만든다(예: `feature/20261117-project-guidelines`). 기존 브랜치는 이름을 바꾸지 않는다. main/develop에서 직접 편집하지 않는다. Git 이력이 없는 최초 도입은 제외 규칙을 먼저 준비하고 feature 브랜치로 초기화한다.
3. **업로드 차단:** Git 작업 전에 로컬·런타임 산출물, 캐시, 로그, 빌드 결과, 개인 편집·에이전트 이력, 시크릿·민감정보를 값 열람 없이 식별하여 `.gitignore`와 `.dockerignore`에 등록한다. 스테이지에도 금지 항목이 없는지 점검한다. 이미 추적된 금지 항목은 ignore만으로 차단되지 않으므로 원본을 보존하고 인덱스 제외를 처리한다. 공유가 필요한 소스·문서·Wrapper·검증 증거는 누락하지 않는다.
4. **전체 산출물:** 작성자·세션·도구와 무관하게 저장소 전체의 추적 변경, staged/unstaged 변경, 신규 파일, 삭제를 확인하고 금지 대상만 제외한다. 지휘자 자신의 수정만 선택해 다른 산출물을 누락하지 않는다.
5. **Git 마감 순서:** feature 커밋/푸시 → feature에서 develop으로 PR 병합 → develop에서 main으로 PR 병합 → 로컬/원격 feature·develop·main **6개 참조의 파일 diff 일치** 검사 순서를 지킨다. 충돌은 양쪽 기능·의도를 분석해 통합하고 근거를 보고한다. 한쪽 전체 채택으로 덮어쓰지 않는다. 원격 주소·권한 등 선행조건이 없으면 해당 단계만 NOT RUN으로 보고한다.
6. **원격과 마감:** GitHub Actions는 추가·실행하지 않는다. 원격에서 켜져 있으면 첫 push 전에 끄고 검증은 로컬에서 수행한다. 원격 브랜치는 삭제하지 않는다. 보조 worktree 정리와 6참조 파일 일치 확인 후 주 작업 폴더를 `git switch develop`으로 마친다. 다음 작업은 최신 develop에서 새 feature로 시작한다.
7. **보조 worktree와 정리:** 읽기 전용 위임은 기존 공간을 공유한다. 동시 쓰기에 필요한 경우만 목적·담당·브랜치·기준 HEAD·소유 경로·회수 조건을 기록하여 보조 worktree를 만든다. 결과를 검증하고 로컬/원격 feature에 반영한 뒤 미사용·잠금 없음·미보존 자료 없음·HEAD 보존을 확인하여 정상 회수한다. 원본·미커밋/미추적 자료·DB·비밀 설정·감사 증거를 지우지 않는다. 실행기/Git 이벤트 자동 정리는 실제 연결된 경로와 실행·회수·보존 결과로 확인하며 수동 명령 추가만으로 완료라 하지 않는다.
8. **민감정보:** `.env`, `.env.*`, `*.env`, `*.env.*` 및 백업본, `*.deploy.*env`, `image-pins.local.env`, 키·토큰·비밀번호·접속/계정정보를 읽거나 출력·복사·로그·커밋하지 않는다. 정제된 `*.example`만 예외다. 환경 전체 출력, `docker compose config`, 전체/Env/전체 Config `docker inspect`, 로그 원문 출력은 금지한다. 상태는 제한된 필드로만 확인한다. 위임 시 이 규칙을 모든 작업자에게 전달한다. 노출되면 사고로 보고하고 값 교체를 요청한다.
9. **파일명과 실행:** Markdown 파일명은 대문자 basename과 소문자 `.md`를 사용한다. 실행은 최소 범위로 제한하고 기존 보호 실행기·자원/시간 상한·정리 절차를 유지한다. 부하·성능·스트레스 등 자원 증폭 테스트는 사용자의 명시적 승인과 제한 계획 없이 실행하지 않는다. 미실행 항목과 실제 실행한 런타임을 구분해 보고한다.
10. **두 언어 문서:** 메인 `README.md`는 영문, `README-KO.md`는 한국어로 유지한다. 제품·개발 문서는 `docs/en/`과 `docs/ko/`에 같은 영문 대문자 파일명으로 한 쌍씩 관리한다. 각 문서에 상대 언어 전환 링크를 넣고, 내용 변경 시 두 언어를 함께 갱신하여 요구 ID·명령·버전·검증 상태를 일치시킨다. 에이전트 진입점 `AGENTS.md`·`CLAUDE.md`와 사용자 답변·보고의 한국어 규칙은 유지한다.

## 제품 안전 지침

1. `README.md`(또는 `README-KO.md`)와 `docs/ko/00-EXECUTIVE-DECISIONS.md`를 먼저 읽는다. 영문 대응 문서는 `docs/en/`에 있다.
2. 구현 전에 `docs/ko/16-TRACEABILITY.md`와 `docs/en/16-TRACEABILITY.md`에 요구 ID와 테스트 계획을 등록한다.
3. Core에서 Spring Boot, Hibernate, MyBatis에 의존하지 않는다.
4. 기존 SQL은 **Observe 기본, Rewrite 기본 금지**. 승인 변환은 Query ID + fingerprint + 버전 + evidence 검증 후.
5. 여러 DBMS 원자적 commit, JPA flush/cache 동기화를 UDAK가 자동으로 보장한다고 말하지 않는다.
6. 값은 bind, table/column/order는 allowlist, 로그에는 민감값 미표시.
7. 실제 실행하지 않은 테스트는 NOT RUN이라고 쓴다.
8. `./tools/run-core-smoke.sh`를 실행하고 실패 시 수정 후 재실행한다.
9. Boot3/Boot4 Starter 별도 유지, 지원 버전 확정 전 검증 필요.
10. 공통 SQL API는 고유 ORM semantics를 감추지 않는다.

세부: [한국어 개발 지침](docs/ko/13-AGENT-DEVELOPMENT-GUIDE.md), [English development guide](docs/en/13-AGENT-DEVELOPMENT-GUIDE.md)
