# Codex / Claude Code 공통 개발 지침

[English](../en/13-AGENT-DEVELOPMENT-GUIDE.md) | 한국어

## 지휘·브랜치·Git 운영 (2026-11-17 확정)

모든 작업자의 공통 진입점은 [`AGENTS.md`](../../AGENTS.md)다. 답변·보고는 한국어로 하고 문서 파일명은 대문자 basename과 소문자 `.md`를 사용한다.

### 지휘와 서브에이전트 위임

- 주 세션이 범위·선행조건·검증·마감을 책임진다. 작업에 맞는 사용 가능한 Codex 모델을 선택하고, 토큰 비용과 코드·문서 품질을 함께 판단한다.
- 단순 문서·정리는 가벼운 모델, 일반 구현은 중간 등급, 설계·보안·독립 검토는 강한 모델을 우선 고려한다. 짧은 확인은 직접 처리하고 과도한 분할·중복 검토는 피한다.
- 읽기 전용 분석은 기존 공간에서 수행한다. 동시 쓰기가 필요한 경우만 소유 경로와 회수 조건을 정한 보조 worktree를 사용한다. 위임 결과는 지휘자가 검증하고 merge·push·삭제·배포와 최종 검증은 직접 수행한다.
- 모든 위임 지시서에 시크릿 파일 열람 금지, 민감값·환경 전체·로그 원문 출력 금지, 동일 규칙의 재전달 의무를 포함한다.

### 브랜치와 전체 산출물

1. 편집 전 `git branch --show-current`와 변경 파일 목록을 확인한다. 최신 develop에서 `feature/{오늘날짜 YYYYMMDD}-{영문기능요약}`을 만든다. 기존 브랜치는 이름을 유지하며 main/develop에서 직접 편집하지 않는다.
2. Git 이력이 없는 최초 도입에서는 `.gitignore`·`.dockerignore`를 먼저 준비하고 feature 브랜치로 초기화한다. 원격 주소는 추측하지 않는다.
3. 로컬 설정·런타임 파일·캐시·로그·빌드 결과·개인 편집/에이전트 이력·시크릿을 값 열람 없이 식별하고 두 ignore 파일로 차단한다. 이미 추적된 항목은 ignore만으로 제외되지 않으므로 원본을 보존하고 인덱스에서도 제외한다.
4. 작성자·세션·AI 도구와 무관하게 tracked/staged/unstaged/untracked/삭제 전체를 확인한다. 공유 대상 소스·문서·Gradle Wrapper·의도적으로 남긴 검증 증거는 보존한다.
5. 스테이지 파일 목록에 금지 항목이 없고 전체 공유 대상이 포함됐는지 확인한다. 민감 파일을 열거나 raw diff·로그에 민감값을 출력하는 방식으로 검사하지 않는다.

### 순차 병합과 마감

1. 로컬 검증 후 feature를 커밋/푸시한다. 원격 GitHub Actions가 켜져 있으면 첫 push 전에 끈다. 워크플로를 추가·실행하지 않는다.
2. feature → develop PR을 병합하고, 이어서 develop → main PR을 병합한다. 충돌은 양쪽 기능을 유지하도록 분석·통합하고 검증 근거를 보고한다.
3. 원격 참조를 갱신하고 로컬/원격의 feature·develop·main 총 6개 참조를 확인한다. 하나를 기준으로 나머지 5개와 파일 diff가 모두 비어 있는지 검사한다. merge commit 때문에 커밋 ID가 다른 것과 파일 내용 차이를 구분한다.
4. 원격 브랜치는 삭제하지 않는다. 보조 worktree는 검증 결과의 로컬/원격 feature 반영 직후 회수하고, 전체 마감에서 잔여 예외를 다시 확인한다. 주 작업 폴더는 `git switch develop`으로 마친다.
5. 원격 주소·권한·브랜치 등 선행조건이 없으면 그 단계는 NOT RUN으로 기록한다. 로컬 검증을 원격 병합 또는 6참조 일치 완료로 대신 보고하지 않는다.

자동 정리는 등록된 실행기·Git 완료 이벤트에 실제 연결된 범위에서만 주장한다. 완료 보조 worktree와 재생성 산출물만 직전 검사와 자원 상한 아래 회수하며 원본·미커밋/미추적 자료·DB·비밀 설정·복구/감사 증거는 보존한다. 자동 실행·회수·보존 건수와 용량을 확인하고 임의 외부 명령까지 정리된다고 주장하지 않는다.

## 두 언어 문서 관리

- 메인 `README.md`는 영문, `README-KO.md`는 한국어로 유지한다.
- `docs/en/`과 `docs/ko/`에 같은 대문자 영문 파일명으로 문서를 한 쌍씩 관리하고 각 문서에 상대 언어 전환 링크를 넣는다.
- 내용 변경 시 두 언어를 같은 작업에서 갱신하고 요구 ID·명령·버전·테스트 상태를 일치시킨다. 번역 시 미구현·NOT RUN 상태와 보장하지 않는 범위를 축약하거나 강화하지 않는다.
- `.security-local/`에는 공유 전 원본 스캔 결과를 보관한다. 인증정보·인프라 상태·덤프·캡처·민감 스캔 결과는 Git/Docker 제외 규칙으로 차단하고 정제된 보안 문서와 검증 증거는 보존한다.
- ignore는 기본 추가와 빌드 컨텍스트의 제외 규칙이다. 이미 추적된 파일이나 `git add -f`를 자동 차단하지 않으므로 Git 작업 전에 인덱스의 파일 목록도 확인한다. 의존성 취약점의 진단·수정은 별도 검증이다.

## SSOT (Single Source of Truth)

- PRD: `docs/ko/01-PRD.md`
- Architecture ADR: `docs/ko/00-EXECUTIVE-DECISIONS.md`, `docs/ko/02-ARCHITECTURE.md`
- API contract: `docs/ko/03-API-SPEC.md`
- DBMS capability: `docs/ko/04-DBMS-COMPATIBILITY.md`
- Tests/Evidence: `docs/ko/08-TEST-VALIDATION.md`, `evidence/`
- Implementation progress: `docs/ko/09-WBS-ROADMAP.md`

## 작업 절차

1. 요구사항 ID와 영향을 받는 API/SPI/Adapter 확인
2. 위험 분류: SQL/transaction/legacy/cross-database
3. 기존 계약/회귀 테스트부터 작성
4. 최소 변경 구현, SQL parameter binding/identifier allowlist 준수
5. core smoke 및 지원 조합 DB 테스트 실행
6. 실제 PASS / BLOCKED / NOT_RUN을 구분하여 evidence 기록
7. 문서 Traceability 갱신

## 금지

- 테스트를 실행하지 않고 '검증 완료' 표시
- 정규식 기반 전체 SQL 자동 변환
- @Transactional이 다중 DB 원자성을 보장한다고 주장
- JPA flush/cache 자동 동기화 가정
- SQL 값 연결, 광범위한 보안 로그
- Boot3/MyBatis3 및 Boot4/MyBatis4 Starter 의존성 혼합
- 지원 불명 DBMS 버전을 '지원' 표시
- 외부 라이브러리의 상용 사용 조건 미확인 배포

## 현재 환경에서 가능한 명령

```bash
./tools/run-core-smoke.sh
```

## 네트워크 및 Gradle 설치 후

```bash
gradle :spring-boot-demo:test
# 실제 DB 환경 구축 후 Docker/Testcontainers 테스트 별도 구현
gradle :spring-boot-demo:bootRun
```

## 예제 작업 지시

> FR-009 승인 SQL 정책을 확장하라. 소스/대상 DBMS 버전, provider version, schema version, SQL hash, test evidence가 모두 동일할 때만 변환을 허용하라. 먼저 단위 테스트로 불일치 차단을 검증하고, `docs/ko/16-TRACEABILITY.md`와 evidence를 갱신하라. 승인 정책과 SQL Translator를 별도 모듈로 유지하라.
