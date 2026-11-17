# Requirement → Design → Implementation → Test → Evidence

[English](../en/16-TRACEABILITY.md) | 한국어

| Requirement | Design | 실제 소스 | Test | 상태 |
|---|---|---|---|---|
| FR-001 Compiler SPI | API-SPEC §2 | core/src/main/java/dev/udak/core/SqlCompiler.java | CoreSmokeTest compiler | PASS |
| FR-003 Basic Dialect subset | DBMS-COMPATIBILITY | core/src/main/java/dev/udak/core/BasicSqlCompiler.java | CoreSmokeTest five vendors | SQL render PASS only |
| FR-004 Identifier/Binding | SECURITY | core/src/main/java/dev/udak/core/BasicSqlCompiler.java | CoreSmokeTest injected identifier/invalid limit | PASS |
| FR-009 Approval Guard | LEGACY-COMPATIBILITY | core/src/main/java/dev/udak/core/ApprovedRewriteGuard.java | CoreSmokeTest exact hash + target mismatch | PASS gate only |
| FR-010 Multi-DS risk | TRANSACTION-CONSISTENCY | core/src/main/java/dev/udak/core/ConsistencyGuard.java | CoreSmokeTest multi-DS | PASS static only |
| FR-005~007 Legacy Observe | LEGACY-COMPATIBILITY | 없음 | 없음 | NOT IMPLEMENTED |
| FR-002 Minimal API | API-SPEC §8 | udak-api/src/main/java/dev/udak/api/CrudClient.java | CrudApiContractTest | MINIMAL PASS; full Fluent API NOT IMPLEMENTED |
| FR-011 DB compatibility report | DBMS-COMPATIBILITY | db-testkit/ | DatabaseFoundationTest | FOUNDATION PASS / REAL DB NOT RUN |
| FR-012 Approved SQL Rewrite runtime | LEGACY-COMPATIBILITY | 없음 | 없음 | NOT IMPLEMENTED |
| Mixed tx demo | TRANSACTION-CONSISTENCY | spring-boot-demo/.../MixedUserService.java | MixedUserServiceTest.java | NOT RUN |

## Phase 1 실행 계획 (2026-11-17)

| 요구 ID | 범위 | 테스트·검증 계획 | 상태 |
|---|---|---|---|
| P1-ENGINE / T-002 | jOOQ·Calcite·JSqlParser 기능·JDK·4 DBMS 관련 범위와 라이선스 비교 | 공식 자료·고정 버전 artifact 라이선스/의존성/체크섬 확인; 선택 근거와 배포 조건 기록 | PASS |
| P1-SPI / FR-001 | 공급자 교체 가능한 SqlCompiler 계약 | 동일 계약을 기본 구현과 외부 parser 연동 구현에 적용; 바인딩 순서·값 비인라인·불변 목록·잘못된 입력/구문 차단 | PASS |
| P1-PROVIDER / FR-003·004 | Core 밖의 외부 라이브러리 연동 PoC | 고정 artifact로 Java 17 컴파일·실제 parser 호출; 5개 렌더 프로필과 실패 경로 검사. 실DB 지원/변환 엔진 완료 주장은 제외 | PASS |
| P1-HARNESS | 재현 가능한 제한 실행과 증거·자동 정리 | 기존 Core smoke 유지; 시간/CPU/JVM/다운로드/파일 상한 아래 Phase 1 검사, 성공·실패 정리와 문서/증거 검증 | PASS |

완료는 비교·선택 artifact 라이선스 검사와 SPI/외부 연동 계약 테스트가 모두 PASS일 때만 판정한다. 실DB, Spring 데모, 상용 엔진 구매·제품 배포 승인, 성능/부하 시험은 이번 범위에 포함하지 않는다.

## 현재 Evidence

## Phase 2 실행 계획 (2026-11-17)

| 요구 ID | 범위 | 테스트·완료 기준 | 상태 |
|---|---|---|---|
| P2-API / FR-002·014 / T-006 | 순수 Java 최소 CRUD/Query 계약 | table별 식별자 allowlist, 결정적 bind 순서, 값 비인라인, PK 없는 수정/삭제 차단, 명시적 RowMapper·건수·조회 cardinality 검사 | PASS (foundation scope) |
| P2-EXEC / FR-010 / T-008 | Spring-aware JDBC Executor | 실제 Spring JDBC와 H2에서 CRUD, SQL NULL·바인딩, 동일 DataSource의 Spring commit/rollback 참여, 자원 회수·민감 예외 차단 확인 | PASS (foundation scope) |
| P2-DB-BASE / FR-003·011 / T-009·010 | 4 DBMS 실환경 검증 기반 | PostgreSQL·MySQL·SQL Server·Oracle별 드라이버·DDL·metadata/CRUD/트랜잭션 시나리오와 명시적 실행/미실행 게이트. H2를 4 DBMS 실행 증거로 대체하지 않음 | PASS (foundation scope) |
| P2-HARNESS | 고정 의존성과 제한·증거·정리 | checksum/라이선스 확인, JDK 17 대상 컴파일, 시간·CPU·메모리·파일 상한, 기존 Core/Phase 1 회귀와 자동 정리·문서 정합성 검사 | PASS (foundation scope) |

이번 요청의 완료 범위는 최소 API·실제 Spring JDBC Executor와 4 DBMS 검증 **기반**이다. 전용 실DB 연결이 준비되지 않은 프로파일은 NOT RUN이며 G2(4종 실DB 검증)는 별도 완료 판정한다. 기존 컨테이너·DB·비밀 설정은 변경하지 않는다.

[PHASE2-VALIDATION.json](../../evidence/PHASE2-VALIDATION.json) — 최소 API·실제 Spring JDBC/H2·4 DBMS 검증 기반 PASS. 전체 실DB G2는 미완료이며 [상세 결과](18-CRUD-JDBC-VALIDATION.md)를 따른다.

[PHASE1-VALIDATION.json](../../evidence/PHASE1-VALIDATION.json) — Core smoke, 기본 계약 74개, 외부 계약 83개, artifact/라이선스/자원·정리 검증 PASS. 상세 범위와 미실행 항목은 [Phase 1 결과](14-POC-RESULTS.md)를 따른다.

`evidence/core-smoke-output.txt` — 실제 `javac`/`java` 실행 출력.

## 실제 G2 실행 계획 (2026-11-17)

| 요구 ID | 범위 | 테스트·완료 기준 | 상태 |
|---|---|---|---|
| P2-G2-DRIVER | 전용 4종 JDBC artifact·버전·라이선스 고정 | 공식 라이선스와 JAR/POM checksum·Java 17 baseline·필수 의존성 검증. 테스트 사용과 제품 재배포 승인을 구분 | PASS (artifact/contract scope only) |
| P2-G2-EVIDENCE | 실제 서버·드라이버 식별 및 안전한 결과 증거 | 승인 provider만 실행; 제품명·숫자 버전·고정 artifact 일치, CRUD/NULL/page/bind/commit/rollback/자체 fixture 정리 검증; H2 대체 금지 | PASS (artifact/contract scope only) |
| P2-G2-LIVE | PostgreSQL·MySQL·SQL Server·Oracle 전용 실환경 | 네 프로파일 모두 실제 실행·결과 매핑 PASS. 연결·라이선스·안전 전제 부재는 NOT RUN, G2 미완료 | NOT RUN |

전용 연결은 비밀값을 출력하지 않는 외부 `RealDatabaseProvider`로 제공한다. 비밀 파일·기존 서비스 계정 열람으로 연결을 추출하지 않는다. 승인된 연결이 없으면 실제 DB 및 G2를 완료 처리하지 않는다.


실행 결과: 기존 계약 회귀와 드라이버 고정·로딩·안전 증거 계약 PASS. 전용 연결 부재로 네 실DB는 NOT RUN, G2 INCOMPLETE. [상세 조건](19-REAL-DB-G2.md)과 [실제 증거](../../evidence/G2-VALIDATION.json)를 따른다.

## 관리 규칙

- 증거 없는 기능은 COMPLETE 금지
- DBMS 실서버 검증은 SQL snapshot과 별도 상태
- PR마다 관련 requirement/document/test/evidence 링크 갱신

## 작업 지침 변경 추적 (2026-11-17)

| 요구 ID | 요구사항 | 대상 | 검증 계획 | 상태 |
|---|---|---|---|---|
| GOV-001 | 지휘자의 작업별 모델 선택·최소 위임·직접 최종 검증 | AGENTS.md, CLAUDE.md, docs/ko/13-AGENT-DEVELOPMENT-GUIDE.md | 세 진입점 지침 연결 확인; 목적 검토만 서브에이전트에 위임 후 지휘자 원문 확인 | PASS |
| GOV-002 | feature 브랜치, 전체 산출물 점검, 제외 규칙, 순차 PR 병합 및 6참조 파일 일치 | AGENTS.md, docs/ko/13-AGENT-DEVELOPMENT-GUIDE.md, .gitignore, .dockerignore | 브랜치명·제외 패턴·파일 목록·Markdown 이름 검사; 원격 미설정 시 push/PR/6참조 검사는 NOT RUN | 지침·로컬 검사 PASS / 원격 NOT RUN |
| GOV-003 | 기존 Core 동작 유지 | tools/run-core-smoke.sh | 기존 실행기로 Core smoke 1회, 임시 빌드 자동 정리 확인; Boot/실DB 실행 제외 | PASS |
| GOV-004 | 보안 민감 파일·원본 스캔 결과·덤프의 Git/Docker 반입 차단 | .gitignore, .dockerignore | 실제 민감 파일 열람 없이 합성 경로의 차단/허용 검사; 두 정책의 동등성 검사 | PASS |
| GOV-005 | 영어/한국어 문서 분리 및 영문 메인 README | README.md, README-KO.md, docs/en/, docs/ko/, AGENTS.md, CLAUDE.md | 17개 문서 쌍·번역 내용·명령/요구 ID·상대 링크·이전 경로·파일명 확인; Core smoke | PASS |

### 최초 지침 반영 시의 실제 실행과 한계

- 시작 시 `.git`이 없는 소스 묶음이었다. 제외 규칙 준비 후 `feature/20261117-project-guidelines`로 로컬 Git을 초기화했다. 기존 이력·브랜치는 없었으며 임의의 원격은 등록하지 않았다.
- `.gitignore`: 금지 경로 표본 21개 차단, 공유 대상 표본 8개 보존 PASS. `.dockerignore`는 정책 정적 확인만 PASS이며 Docker build는 NOT RUN이다.
- 세 지침서의 한국어·서브에이전트·브랜치·6참조·민감정보 규칙, 로컬 링크, 공백, Markdown 파일명 확인 PASS. 최초 일관성 검사의 용어 판정 실패는 가이드의 위임 제목을 명확히 한 후 재확인했다.
- `./tools/run-core-smoke.sh`: 60초 제한, Java heap 256MiB·metaspace 128MiB·활성 CPU 2개 상한 아래 1회 PASS(exit 0). 기존 EXIT trap 실행 후 임시 빌드 잔여 0건/0바이트. 기존 증거 파일은 보존했다.
- 실제 실행한 런타임은 `javac`/`java`뿐이다. Spring 앱·Gradle·Docker·실DB는 NOT RUN이다. 보조 worktree 생성/회수/잔여는 모두 0개다.
- 원격 주소 미제공으로 커밋/푸시·PR 병합·6참조 비교·마감 develop 전환은 NOT RUN이다. Git 완료 이벤트 자동 정리 연결은 이번 작업에서 구현·검증하지 않았으며, 확인한 자동 정리 범위는 기존 Core smoke 실행기뿐이다.

### 보안 제외·두 언어 문서 전환 검증 (2026-11-17)

- GOV-004: Git과 Docker에서 동일한 합성 경로 196개를 확인했다. 민감 경로 178개 차단, 공유 경로 18개 보존 PASS. 실제 민감 파일은 열지 않았다. Docker 패턴은 `github.com/moby/patternmatcher v0.6.0`으로 확인했고 Docker 빌드·컨테이너는 실행하지 않았다.
- Docker 검사 도구는 임시 루트와 작업 폴더를 같은 위치로 설정하여 초기 두 실행이 실패했다. 모듈 다운로드 진단은 성공했고, `TMPDIR`과 모듈 폴더를 분리한 뒤 검사 PASS. 실패 원인을 숨기지 않고 최종 증거에 기록했다.
- GOV-005: 한국어 17개 원문 보존 확인, 영문 17개 전문 번역, 언어 전환 링크, 영문 `README.md`·한국어 `README-KO.md` 구성 PASS. 요구 ID·버전·표·코드 블록 구조와 로컬 링크를 확인했다. 원문 내용 비교는 언어 링크·경로 치환·이번에 추가한 관리/보안 절을 구분하여 수행했다.
- 양쪽 README에서 실제 포함된 Gradle Wrapper 스크립트·설정·jar를 표시하도록 정정했다. 데모 의존성 해석과 실행은 여전히 NOT RUN이다.
- Core smoke 1회 PASS(exit 0); 기존 실행기 자동 정리 후 임시 파일 0건/0바이트. 검사 도구 성공 2회에서 임시 파일 합계 1,184개·109,755,249바이트는 임시 작업 종료 시 자동 정리됐고 잔여 디렉터리는 없다. 보조 worktree 생성/회수/잔여는 모두 0개다.
- 실제 실행은 Java Core 컴파일/테스트와 Go 기반 패턴 매처 검사뿐이다. Spring·Gradle·Docker·실DB·의존성 취약점 스캔·Git 원격 마감은 NOT RUN이다. 제외 규칙을 취약점 수정 완료 또는 이미 추적된 파일의 자동 차단으로 해석하지 않는다.
- 비밀 전용 폴더 안의 `*.example` 24개와 일반 공유 템플릿 5개를 추가 확인했다. Git/Docker 모두 29개 검사 PASS이며 폴더 제외가 템플릿 예외보다 우선한다. 기존 검사와 합쳐 고유 합성 경로 220개를 확인했다.
- 검증 증거: [REPOSITORY-VALIDATION.json](../../evidence/REPOSITORY-VALIDATION.json).
