# Requirement → Design → Implementation → Test → Evidence

[English](../en/16-TRACEABILITY.md) | 한국어

| Requirement | Design | 실제 소스 | Test | 상태 |
|---|---|---|---|---|
| FR-001 Compiler SPI | API-SPEC §2 | core/src/main/java/dev/udak/core/SqlCompiler.java | CoreSmokeTest compiler | PASS |
| FR-003 Basic Dialect subset | DBMS-COMPATIBILITY | core/src/main/java/dev/udak/core/BasicSqlCompiler.java | CoreSmokeTest five vendors | SQL render PASS only |
| FR-004 Identifier/Binding | SECURITY | core/src/main/java/dev/udak/core/BasicSqlCompiler.java | CoreSmokeTest injected identifier/invalid limit | PASS |
| FR-009 Approval Guard | LEGACY-COMPATIBILITY | core/src/main/java/dev/udak/core/ApprovedRewriteGuard.java | CoreSmokeTest exact hash + target mismatch | PASS gate only |
| FR-010 Multi-DS risk | TRANSACTION-CONSISTENCY | core/src/main/java/dev/udak/core/ConsistencyGuard.java | CoreSmokeTest multi-DS | PASS (기존 Core 정적 검사). 분리된 Phase 4 모듈의 검증 범위는 P4-CORE·P4-SPRING·P4-TX 참조 |
| FR-005~007 Legacy Observe | LEGACY-COMPATIBILITY | observe-core/, legacy-observe/ | ObserveContractTest / LegacyObserveAdapterContractTest / LegacyCompatibilityTest | PASS (verified scope) |
| FR-002 Minimal API | API-SPEC §8 | udak-api/src/main/java/dev/udak/api/CrudClient.java | CrudApiContractTest | MINIMAL PASS; full Fluent API NOT IMPLEMENTED |
| FR-011 DB compatibility report | DBMS-COMPATIBILITY | db-testkit/ | DatabaseFoundationTest | FOUNDATION / MINIMAL REAL G2 PASS |
| FR-012 Approved SQL Rewrite runtime | LEGACY-COMPATIBILITY | rewrite-core/ · rewrite-jsqlparser/ · rewrite-jdbc/ | rewrite-testkit/ · tools/run-phase5.py | G4 PASS (고정 fixture) |
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

[PHASE2-VALIDATION.json](../../evidence/PHASE2-VALIDATION.json) — 최소 API·실제 Spring JDBC/H2·4 DBMS 검증 기반 PASS. 기반 실행기는 연결 없는 inventory 모드를 유지하며, 실제 최소 기능 G2 PASS는 [관리형 결과](20-MANAGED-G2-RESULTS.md)와 구분하여 [상세 결과](18-CRUD-JDBC-VALIDATION.md)를 따른다.

[PHASE1-VALIDATION.json](../../evidence/PHASE1-VALIDATION.json) — Core smoke, 기본 계약 74개, 외부 계약 83개, artifact/라이선스/자원·정리 검증 PASS. 상세 범위와 미실행 항목은 [Phase 1 결과](14-POC-RESULTS.md)를 따른다.

`evidence/core-smoke-output.txt` — 실제 `javac`/`java` 실행 출력.

## 실제 G2 실행 계획 (2026-11-17)

| 요구 ID | 범위 | 테스트·완료 기준 | 상태 |
|---|---|---|---|
| P2-G2-DRIVER | 전용 4종 JDBC artifact·버전·라이선스 고정 | 공식 라이선스와 JAR/POM checksum·Java 17 baseline·필수 의존성 검증. 테스트 사용과 제품 재배포 승인을 구분 | PASS (artifact/contract scope only) |
| P2-G2-EVIDENCE | 실제 서버·드라이버 식별 및 안전한 결과 증거 | 승인 provider만 실행; 제품명·숫자 버전·고정 artifact 일치, CRUD/NULL/page/bind/commit/rollback/자체 fixture 정리 검증; H2 대체 금지 | PASS (artifact/contract scope only) |
| P2-G2-LIVE | PostgreSQL·MySQL·SQL Server·Oracle 전용 실환경 | 네 프로파일 모두 실제 실행·결과 매핑 PASS. 연결·라이선스·안전 전제 부재는 NOT RUN, G2 미완료 | NOT RUN |

전용 연결은 비밀값을 출력하지 않는 외부 `RealDatabaseProvider`로 제공한다. 비밀 파일·기존 서비스 계정 열람으로 연결을 추출하지 않는다. 승인된 연결이 없으면 실제 DB 및 G2를 완료 처리하지 않는다.


2026-11-17 준비 단계 기록: 기존 계약 회귀와 드라이버 고정·로딩·안전 증거 계약 PASS. 전용 연결 부재로 네 실DB는 NOT RUN, G2 INCOMPLETE. [상세 조건](19-REAL-DB-G2.md)과 [실제 증거](../../evidence/G2-VALIDATION.json)를 따른다.

## 전용 provider·VM 실검증 재개 계획 (2026-11-18)

| 요구 ID | 범위 | 테스트·완료 기준 | 상태 |
|---|---|---|---|
| P2-G2-PROVIDER | 직접 준비하는 전용 DataSource provider | 비밀 파일/값 출력 없이 전용 런타임 연결 주입, 4종 ServiceLoader 등록, 승인·연결 timeout·기본 로그 차단 검증 | PASS (minimal functional scope) |
| P2-G2-ENV | Parallels VM 및 격리된 DB 환경 준비 | CPU 아키텍처·OS·자원·서버 이미지/사용권 확인, 상한·소유권·상태·실행/정리 증거, 기존 VM/DB/자료 보존 | PASS (minimal functional scope) |
| P2-G2-LIVE | 실제 4종 DB 순차 실행 | 네 DB의 실제 제품/버전·10개 계약·fixture 정리 PASS; 미실행/실패는 완료 금지 | PASS (40 checks; native platform NOT RUN) |

사용자는 Parallels VM 활용 및 필요한 환경 직접 준비를 승인했다. 전용 환경만 제한 실행하며 기존 VM·DB·비밀 설정을 추출하거나 삭제하지 않는다. 아키텍처/운영 조건 제약은 증거와 함께 기록하며 실DB 실행을 H2로 대체하지 않는다.

완료 근거: [G2-REAL-VALIDATION.json](../../evidence/G2-REAL-VALIDATION.json). SQL Server 1종과 나머지 3종을 동일 소스·드라이버·이미지로 실행한 두 보고서를 대조했다. 기존 VM은 기동/수정하지 않았고 새 전용 Docker DB 4개를 순차 실행·정지·보존했다. 차기는 FR-005~007 / T-011~013 Observe 및 기존 접근 호환성 검사다.

## Phase 3 Observe·혼용 호환성 실행 계획 (2026-11-18)

| 요구 ID | 범위 | 테스트·완료 기준 | 상태 |
|---|---|---|---|
| P3-OBS / FR-005~008 / T-011~013 | JPA/Hibernate·MyBatis·JDBC Observe 어댑터와 비민감 이벤트 | 원 SQL/인수/결과/예외·캐시 키 변경 없음, raw SQL·바인드/리터럴·접속/계정·원본 예외 미노출, 안정된 fingerprint/query ID, listener 실패 격리 | PASS (verified framework/version scope) |
| P3-COMPAT / FR-005~007·010 | 동일 DataSource 혼용의 flush/cache/commit/rollback | 실제 Hibernate/Spring JPA·MyBatis-Spring·JdbcTemplate 연결, 기존 Entity/Repository/Mapper/service 사용, flush 전후 가시성·JPA/MyBatis 캐시 stale/명시적 refresh/clear·정상 commit/예외 rollback 검사 | PASS (verified framework/version scope) |
| P3-HARNESS | 고정 의존성·라이선스/체크섬·제한 실행·회귀·정리 | Core/기존 계약 유지, Java 17 대상, 순차 제한 JVM/네트워크/임시 자료 자동 정리·원본 증거 보존, 두 언어 정합성 | PASS (verified framework/version scope) |

Observe는 자동 flush/캐시 동기화나 SQL rewrite를 수행하지 않는다. 정확 SQL 승인 해시 계약은 변경하지 않는다. 직접 실행한 프레임워크·DB 조합만 PASS로 기록하고 부하/성능/미실행 조합은 별도 NOT RUN으로 남긴다.

완료 증거: [PHASE3-GATE.json](../../evidence/PHASE3-GATE.json). H2 10개와 실제 네 DB의 같은 10개씩, 총 실DB 40개 항목 PASS. 이벤트·어댑터 202/188 assertions와 기존 Core 74 assertions를 확인했다. 관측 공백·원본 데이터/풀 소유·SQL Server 운영 한계와 다음 Phase 4는 [결과](21-LEGACY-OBSERVE-RESULTS.md)를 따른다.

## Phase 4 트랜잭션 진단 실행 계획 (2026-11-18)

| 요구 ID | 범위·허용 경로 | 테스트·완료 기준 | 상태 |
|---|---|---|---|
| P4-CORE / FR-010 / T-014 / NFR-03·NFR-06 | consistency-core/의 JDK 전용 불변 진단·실행 정책 모델 | 구성/트랜잭션 상태의 정상·부정 계약, REPORT_ONLY/BLOCK 명시적 정책, 비민감 enum 보고서, 미확인 결과 자동 재시도 금지 | PASS (정책 123 assertions) |
| P4-SPRING / FR-010 / T-014 | consistency-spring/의 명시적 DataSource·TxManager·JPA·MyBatis·JDBC 구성 및 현재 스레드 상태 진단 | 다중 DS/잘못된 TM/자원 불일치 감지, 외부 연결·SQL·Bean 전체 탐색 없이 검사, 원본 설정·트랜잭션 수명 불변 | PASS (Spring 연결 52 assertions) |
| P4-TX / FR-010 / T-014 | consistency-testkit/의 실제 Spring/H2 트랜잭션 검사 | REQUIRED 참여·rollback-only, REQUIRES_NEW 독립 commit/외부 rollback, NESTED savepoint/JPA 위험, readOnly·isolation·timeout·불명 결과 진단, 기존 Phase 3 H2 회귀 | PASS (Spring/H2 9개 + 정책 1개, 205 assertions 및 기존 H2 회귀 10개) |
| P4-HARNESS | tools/run-phase4.py, tools/verify-phase4.py, 해당 검증 테스트·evidence/PHASE4-*.json, settings.gradle.kts, README*.md, docs/en/ 및 docs/ko/ 대응 문서 | Java 17·고정 Phase 3 의존성·순차 제한 JVM·자동 정리·증거 위변경/누락 거부·양언어 정합성·Core smoke | PASS (자동 정리·검증기 13개 및 회귀 검사) |

기존 core/·Phase 3 Java 및 하네스·의존성 고정 목록은 유지하여 G2/G3 증거를 보존한다. Phase 4는 명시적으로 제공한 구성과 현재 스레드만 진단하며 Starter 자동 발견·XA/다중 DB 원자성·자동 flush/cache·SQL 변환은 범위 밖이다. 새 벤더별 readOnly/isolation/timeout 조합, 네이티브 SQL Server 및 운영 복구 검증은 NOT RUN으로 별도 기록한다. 기존 관리형 DB 8개와 데이터·비밀 설정은 기동·수정·삭제하지 않는다. 부하/성능 테스트는 실행하지 않는다.

완료 근거는 [Phase 4 판정](../../evidence/PHASE4-GATE.json)과 [상세 결과](22-TRANSACTION-GUARD-RESULTS.md)에 있다. T-014 완료 범위는 명시적 구성·현재 스레드 진단 및 Spring/H2 계약이다.

## Phase 5 승인 선택 변환 계획 (2026-11-18)

| 요구 ID | 범위·허용 경로 | 테스트·완료 기준 | 상태 |
|---|---|---|---|
| P5-POLICY / FR-009·013 / T-016 / ADR-008 | rewrite-core/의 JDK 전용 승인·증거 Registry와 선택 변환 SPI | Query ID/정확 SQL/소스·대상/서버·드라이버·스키마·provider/runtime·evidence 해시·유효기간·폐기·실제 변환 계획 일치, 미승인 기본 거부 | LOCAL PASS (330) |
| P5-PROVIDER / FR-012 / T-015 | rewrite-jsqlparser/의 JSqlParser 5.4 제한 SELECT 변환 | allowlist AST와 전체 canonical 원문 검증, 단일 equality/고유키 정렬/paging만 허용, 바인드 값 비인라인·정확 순열·결과 라벨 유지, 미지원 부가절 거부 | LOCAL PASS (147) |
| P5-EXEC / FR-007·009·012 / T-017 | rewrite-jdbc/의 명시적 Spring JDBC 선택 실행, rewrite-testkit/ | 매 실행 승인 재검증·실제 대상 identity 확인·bind/RowMapper/외부 tx 유지, 거부시 prepare 0·원문 fallback 없음, 원본/대상/독립 기대 행의 실제 동등성 | PASS (67 + H2 323 + real DB 1,348) |
| P5-HARNESS / FR-011·013 | tools/run-phase5*.py, tools/verify-phase5.py, 해당 검증 테스트, evidence/PHASE5-*.json, settings.gradle.kts, README*.md, docs/en/·docs/ko/ | 기존 보호 실행기·고정 deps 재사용, 로컬 계약/회귀·실제 4종 결과·누락/변조 거부·자동 정리·두 언어 일치 | G4 PASS (고정 fixture) |

기존 core/·Observe·Phase 1~4 소스/하네스/고정 manifest는 유지한다. 전역 모듈 등록(settings.gradle.kts) 변경에 따른 Phase 4 회귀 증거(evidence/PHASE4-VALIDATION.json·PHASE4-VERIFIER-VALIDATION.json·PHASE4-GATE.json)는 동일 보호 하네스로 재검증·갱신하고 이전 원본은 .git/에 보존한다. 운영 승인 발급은 신뢰된 호출자 책임이며 테스트 승인과 구분한다. 기존 JPA/MyBatis는 Observe를 유지하고 자동 변환은 연결하지 않는다. 부하/성능·일반 SQL 동등성·Boot/Gradle/XA·운영 복구는 NOT RUN이다. 상한 12개 승인 후 기존 8개를 보존하며 새 DB 4개를 동시 활성 1개 및 CPU·메모리·PID·시간 제한 아래 실행했다.

실DB 검증 범주 32개와 전체 verifier 20개(건너뜀 0개)로 고정 fixture의 G4를 통과했다. 운영 승인은 미부여다. [G4 증거](../../evidence/PHASE5-GATE.json). [Phase 5 결과](23-SELECTIVE-REWRITE-RESULTS.md)

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

## Phase 6 작업 계약 (2026-11-18, VERIFIED)

| 요구 ID | 구현 대상 / allowed_paths | 테스트·완료 기준 | 상태 |
|---|---|---|---|
| P6-STARTER / T-018·019 / ADR-006 | starter-boot3/, starter-boot4/, starter-testkit/, core/build.gradle.kts, udak-api/build.gradle.kts, jdbc-spring/build.gradle.kts, observe-core/build.gradle.kts, settings.gradle.kts | Boot 3.5.16 / Boot 4.1.2 별도 실제 앱 시작·종료, 자동설정 발견·비활성·사용자 빈 우선·DataSource 모호성·안전 설정·H2 외부 트랜잭션, 격리 classpath와 배포 JAR/POM 소비 | PASS (3 configurations / 6 consumers) |
| P6-CLI / T-021 | udak-cli/, tools/udak-cli.py | 네트워크·DB·비밀 파일 접근 없는 read-only inspect, 고정 출력·종료코드, 입력·경로·심볼릭 링크·크기 제한과 오류 정제 | PASS (41) |
| P6-LOCAL-CI / T-020 | tools/run-phase6*.py, tools/verify-phase6.py, tools/test-phase6*.py, tools/phase6-*.json, tools/local-ci.py, evidence/PHASE6-*.json, .gitignore, .dockerignore | 기존 보호 실행기 재사용, 순차 제한 실행·의존성/POM/라이선스/hash 고정, 검증 누락·변조 거부, 성공/실패 자동 정리, Core 회귀 | PASS (13 steps / 50 verifier tests) |
| P6-RELEASE / T-020 / ADR-007 | tools/phase6-release*.json, tools/release-gate.py, README*.md, docs/en/, docs/ko/ | 재현 가능 후보 artifact·checksum·SBOM·NOTICE·버전/API 평가, G0/G5 및 운영 승인 누락 시 정식 배포 fail closed, 로컬 검증과 실제 외부 배포 구분, 두 언어 일치 | PASS (deny); formal release BLOCKED |

기존 Phase 1~5 실행 증거와 12개 정지 DB는 보존한다. 전역 Gradle 설정 변경의 영향은 별도 평가하고, 이전 실행 증거를 재실행 증거로 꾸미지 않는다. GitHub Actions·새 DB 생성·부하/성능 테스트·외부 artifact 공개는 이번 실행에 포함하지 않는다. 로컬 후보 검증과 정식 배포 승인은 별도 상태다.

[로컬 CI](../../evidence/PHASE6-LOCAL-CI.json)와 [G6 후보 게이트](../../evidence/PHASE6-GATE.json)는 PASS다. Boot 3 POM, Boot 4 POM, Boot 4 BOM에서 각각 79개 단언·11개 시나리오, 혼합·메이저 불일치 거부 3개가 통과했다. 패키지 30개 파일의 재빌드 바이트가 일치했다. 외부 아티팩트 29개에 두 해석 그래프를 함께 고정했다. 외부 게시와 새 DB 기동은 각각 0건이다. 해당 검증 당시 G0는 NOT GRANTED, G5는 NOT RUN이었다. [현재 승인 범위](31-RELEASE-APPROVAL-SCOPE.md) · [현재 제품 G5](32-PRODUCT-G5-ACCEPTANCE.md)

## 제품 확장 Phase 1 작업 계약

| 요구 ID | 허용 경로 | 검증 기준 | 상태 |
|---|---|---|---|
| INV-001 / FR-008·016 | sql-inventory/ | 명시적 ObservationSink 연결, 수집 상한, 안정적인 Query·테스트 참조, 정적 등록과 런타임 관측 구분, 메타데이터만 수집; 실제 세 어댑터를 fixture에서 사용 | PASS (48 + 14 assertions) |
| INV-002 / FR-011·017 | tools/sql-inventory.py, tools/test-sql-inventory.py, sql-inventory/ | 동일 시나리오 프로필의 base/head 비교, 관측 SQL 형태·커버리지 변화 표시, 불명/불완전 입력 구분, 영향 테스트 참조를 JSON과 PR용 Markdown으로 출력 | PASS (12 CLI tests) |
| INV-003 / FR-017 | tools/run-sql-inventory.py, evidence/SQL-INVENTORY-*.json, README.md, README-KO.md, docs/en/, docs/ko/ | 제한된 로컬 하네스, 기존 Core smoke와 실제 레거시 H2 회귀, CLI 거부·성공/실패 자동 정리, 한·영 보고서; 기존 단계 게이트는 별도 재검증 가능 | PASS (13 stages, 10 legacy H2 cases) |

정적 항목은 애플리케이션 테스트 코드가 등록한다. 대응 항목이 없거나 미관측이면 SQL 삭제의 증거가 아니다. 인벤토리는 해시, 열거 값, 상한이 있는 수량을 기록한다. 변경 리포트는 관측 범위를 비교하며 SQL 변환 승인을 발급하지 않는다.

[실제 실행 증거와 정제된 예시 보고서](../../evidence/SQL-INVENTORY-VALIDATION.json).

## 제품 확장 Phase 2 작업 계약

| 요구 ID | 허용 경로 | 검증 기준 | 상태 |
|---|---|---|---|
| TXTRACE-001 / FR-008·010 | tx-trace-spring/ | 기존 Spring 트랜잭션에 명시적 추적 등록, SQL 관측을 일치하는 스레드 자원에 연계, 미등록·외부·트랜잭션 밖 구분, 상한·누락 표시와 불변 메타데이터 보고서 | PASS (explicit Spring registration and bounded capture) |
| TXTRACE-002 / FR-010 | tx-trace-spring/ | 실제 H2에서 JPA·MyBatis·JdbcTemplate 같은 경계, commit·rollback-only, REQUIRES_NEW 중단·재개, JDBC savepoint/rollback 요청, 명시적 flush 순서, 결과 불명 처리 | PASS (8 scenarios / 318 assertions) |
| TXTRACE-003 / FR-017 | tools/run-tx-trace.py, evidence/TX-TRACE-*.json, README.md, README-KO.md, docs/en/, docs/ko/ | 고정 의존성 및 보호 실행기, Core/Observe/Guard 회귀, 한·영 문서, 성공·실패 정리, 메타데이터 증거 및 별도 Git 마감 | PASS (9 stages / 20 H2 regression cases) |

추적은 명시적으로 연결한 Spring 로컬 트랜잭션의 스레드 자원과 콜백을 관찰한다. SQL 관측은 실행 성공이나 같은 물리 커넥션의 증명이 아니다. savepoint 롤백 알림은 실제 작업 전 콜백이다. 원본 SQL·값·연결 주소·트랜잭션 이름·예외 원문을 보고서에 넣지 않는다.

[추적 실행과 메타데이터 타임라인](../../evidence/TX-TRACE-VALIDATION.json). 다음은 확장 Phase 3, 스키마 변경 영향 분석과 쿼리별 실DB 회귀다.

## 제품 확장 Phase 3 작업 계약

| 요구 ID | 허용 경로 | 검증 기준 | 상태 |
|---|---|---|---|
| SCHEMA-001 / FR-008·011 | tools/schema-impact.py, tools/test-schema-impact.py | 버전이 있는 구조 스냅샷의 컬럼 추가·삭제·길이·타입·NULL 변경, Phase 1 Query ID·테스트 연결, 참조 불명과 비교 불완전 표시 | PASS (17 tests) |
| SCHEMA-002 / FR-011·013 | schema-regression/, tools/schema-native.py | 실제 PostgreSQL·MySQL의 격리 fixture에 동일한 변경 적용, 대상 쿼리별 원본·후보 결과·라벨·Java 매핑·NULL 확인, 수집 원천과 실행 조합 증거 | PASS (4 query and DB combinations / 196 assertions) |
| SCHEMA-003 / FR-017 | tools/run-schema-regression.py, evidence/SCHEMA-*.json, README.md, README-KO.md, docs/en/, docs/ko/ | 고정 JDBC 검증, 보호 실행·순차 DB 기동·자동 정리, Core/Inventory 회귀, 한·영 증거와 Git 마감 | PASS (Core smoke, Inventory 48, native cleanup) |

정규화한 구조와 명시적으로 선언한 의존성으로 영향 범위를 계산한다. 기존 DB나 컨테이너 12개를 변경하지 않고 별도 임시 테스트 인스턴스를 사용한다. SQL Server·Oracle의 이번 쿼리별 회귀는 별도 검증 범위다.

[실행 증거](../../evidence/SCHEMA-REGRESSION-VALIDATION.json) · [저장소 및 정리 검증](../../evidence/SCHEMA-REPOSITORY-VALIDATION.json). 다음은 확장 Phase 4, DB·드라이버별 취소와 복구 검증이다.

## 제품 확장 Phase 4 작업 계약

| 요구 ID | 허용 경로 | 완료 조건 | 상태 |
|---|---|---|---|
| RECOVERY-001 / FR-010·011 | db-recovery/ | 격리된 PostgreSQL과 MySQL에서 잠금 대기 중인 쓰기 한 건을 확인한 뒤 JDBC 명시 취소와 쿼리 타임아웃을 독립된 서버 관측으로 검증 | PASS (4건) |
| RECOVERY-002 / FR-010·011 | db-recovery/ | 취소 뒤 트랜잭션 상태·롤백·쓰기 가시성·물리 세션 재사용, 테스트 세션 단절 뒤 커밋 전 작업의 롤백과 새 세션 복구를 검증 | PASS (6건, 두 요구사항 검증 합계 112개 단언) |
| RECOVERY-003 / FR-017 | tools/run-db-recovery.py, tools/test-db-recovery.py, evidence/DB-RECOVERY-*.json, README.md, README-KO.md, docs/en/, docs/ko/ | 고정 JDBC와 자원 제한 네이티브 하네스를 재사용하고 전체 증거와 정제 여부를 검사한 뒤 Core smoke, 자동 정리, Git 마감 확인 | PASS (Core smoke, 결과 형식 테스트 8건, 네이티브 정리) |

기능 검증은 한 번에 DB 하나와 잠금 대기 쓰기 하나로 제한했다. 격리된 PostgreSQL 17.11과 JDBC 42.7.14 조합, MySQL 8.0.46과 Connector/J 26.10.0 조합을 검증했다. SQL Server, Oracle, 커넥션 풀 동작, 결과가 불명확한 커밋의 복구는 NOT RUN이다. G5 인증은 별도 작업이다.

[실행 증거](../../evidence/DB-RECOVERY-VALIDATION.json) · [취소와 복구 가이드](28-DB-CANCELLATION-RECOVERY.md). 다음은 확장 Phase 5, 쿼리별 승인·폐기 이력이다.

## 제품 확장 Phase 5 작업 계약

| 요구 ID | 허용 경로 | 완료 조건 | 상태 |
|---|---|---|---|
| APPROVAL-001 / FR-012·013 / ADR-008 | approval-history/ | Query ID, 원본·대상·실행 계획 fingerprint, 실행 환경 버전, 증거와 승인 세대에 연결된 승인·폐기 이벤트를 일정 범위 안에서 보존한다. 재개방 후 이력을 조회하고 유효하지 않은 상태를 거부한다. | PASS (Core 단언 65개) |
| APPROVAL-002 / FR-012·013 / ADR-003 | approval-history/ | 기존 승인 SELECT 실행 경로에서 명시적으로 사용한다. 폐기·교체된 승인 세대는 재개방 이후에도 후속 실행을 허용하지 않는다. 오래된 폐기 요청, 다른 쿼리 분리, 진행 중 실행과 사전 승인 판정, 신규 승인을 검증한다. | PASS (H2/JDBC 단언 36개와 Core 실행 허용 경계) |
| APPROVAL-003 / FR-017 | tools/run-approval-history.py, evidence/APPROVAL-HISTORY-*.json, .gitignore, .dockerignore, README.md, README-KO.md, docs/en/, docs/ko/ | 보호 실행기에서 Core, 이력과 H2/JDBC를 고정 의존성으로 검증하고 정제된 증거, 자동 임시 파일 정리, Git 마감을 확인한다. | PASS (Core smoke, H2 회귀 8건, Gradle과 정리) |

이력 파일은 단일 로컬 프로세스가 독점해 사용한다. 승인 등록을 호출하는 애플리케이션이 검사한 신뢰 증거를 제공하며, 실행 허용 판정에는 기존 만료·버전·증거 계약을 계속 적용한다. 신규 이력 경로는 H2 2.3.232에서 검증했다. 이 경로의 실DB 조합 검증은 NOT RUN이다.

[실행 증거](../../evidence/APPROVAL-HISTORY-VALIDATION.json) · [쿼리별 승인·폐기 이력](29-QUERY-APPROVAL-HISTORY.md). 다음은 확장 Phase 6, 릴리스와 지원 증거 검증이다.

## 제품 확장 Phase 6 작업 계약

| 요구 ID | 허용 경로 | 완료 조건 | 상태 |
|---|---|---|---|
| RELEASE-001 / FR-017 / ADR-006 | tools/run-release-demo.py, evidence/RELEASE-DEMO-*.json | 실제 JDK 17에서 전체 Spring Boot 데모 빌드, JPA·MyBatis·JdbcTemplate 혼합 접근 테스트와 패키지 기동 검증 | PASS (JDK 17.0.10, 테스트 2건, 패키지 기동·종료) |
| RELEASE-002 / FR-010·013 / ADR-005 | tools/release-support/, tools/run-release-support*.py, evidence/RELEASE-SUPPORT-*.json, docs/en/, docs/ko/ | DB와 드라이버 조합을 기록하고 격리된 실DB 추가 시나리오를 실행하며 G5와 지원 인증의 경계를 명시 | PASS (승인 이력 신규 10건과 기존 매트릭스). G5 NOT RUN, 제품 지원 NOT CERTIFIED |
| RELEASE-003 / FR-017 / ADR-007 | tools/run-release-signing.py, evidence/RELEASE-SIGNING-*.json, README.md, README-KO.md, docs/en/, docs/ko/ | 로컬 서명과 변경 검출, 라이선스·릴리스 증거 정합성, 필수 승인에 따른 게시 판정 검증 | PASS (테스트 서명 2건과 변경 입력 거부 2건). G0 NOT GRANTED, 배포 BLOCKED |

기존 릴리스 지원 검증은 G0 범위 승인과 G5 1차 시험 전의 실행이다. 제품 G5와 DB 지원 인증, 게시 경로 승인·구현, 운영용 서명·게시가 남아 있다. [배포와 지원 근거](30-RELEASE-SUPPORT-EVIDENCE.md) · [검증 매트릭스](../../evidence/RELEASE-SUPPORT-MATRIX.json)

## 확장 Phase 6 승인 범위

| 요구 ID | 허용 경로 | 완료 조건 | 상태 |
|---|---|---|---|
| RELEASE-004 / ADR-007 | tools/phase6-approval-scope.json, tools/verify-release-approval-scope.py, evidence/RELEASE-APPROVAL-SCOPE.json, docs/en/, docs/ko/ | 제안한 자체 라이선스와 배포 목록을 기존 G6 후보 및 의존성 증거와 대조한다. 권리자의 범위 결정을 게시 권한과 별개로 기록한다. | 제안 검증과 범위 승인 완료. |
| RELEASE-005 / FR-017 | tools/phase6-approval-scope.json, tools/verify-release-approval-scope.py, evidence/RELEASE-APPROVAL-SCOPE.json, docs/en/, docs/ko/ | 제안한 G5 시험 한도를 기존 네이티브 테스트 환경과 대조한다. 운영자의 명시적 승인을 기록하고 실제 실행 증거와 구분한다. | 제안 검증과 제한된 1회 시험 승인 완료. |

[승인 범위](31-RELEASE-APPROVAL-SCOPE.md) · [제안 검증](../../evidence/RELEASE-APPROVAL-SCOPE.json) · [승인 결정](../../evidence/RELEASE-G0-G5-DECISION.json).

| 요구 ID | 허용 경로 | 완료 조건 | 상태 |
|---|---|---|---|
| RELEASE-006 / ADR-007 | LICENSE, NOTICE, tools/release-g0/, tools/run-g0-candidate.py, evidence/RELEASE-G0-*.json, docs/en/, docs/ko/, README.md, README-KO.md | 승인 범위에 대한 권리자 결정을 기록하고 라이선스 표기를 적용한 라이브러리 6종의 재빌드와 아카이브 내용 검증 | PASS (POM 6개, JAR 18개, Gradle 메타데이터 6개). [후보 증거](../../evidence/RELEASE-G0-CANDIDATE.json) |
| RELEASE-007 / FR-017 | tools/release-g5/, tools/run-g5-pilot.py, evidence/RELEASE-G5-*.json, docs/en/, docs/ko/ | 운영자 승인을 기록하고 한도를 적용한 네이티브 DB 순차 시험을 1회 실행해 스케줄, 트랜잭션 결과, 실측과 정리를 검증 | PASS (DB별 48건). [시험 증거](../../evidence/RELEASE-G5-PILOT.json) |

| 요구 ID | 허용 경로 | 완료 조건 | 상태 |
|---|---|---|---|
| RELEASE-008 / NFR-02 | tools/product-g5-criteria.json, tools/release-performance/, tools/run-g5-performance.py, tools/verify-product-g5.py, evidence/PRODUCT-G5-*.json, docs/en/, docs/ko/ | 기준 대비 Observe p95 증가율 5% 상한과 측정 범위를 확정한다. 승인된 계획으로 실측한 쌍을 판정하고 미실행을 구분한다. | 증거 PASS. PostgreSQL (+47.8143%)·MySQL (+27.3076%) Observe p95 FAIL. |
| RELEASE-009 / FR-010·013 / ADR-005 | tools/release-pool/, tools/run-g5-pool.py, tools/verify-product-g5.py, evidence/PRODUCT-G5-*.json, docs/en/, docs/ko/ | 격리 실DB에서 풀의 롤백·상태 초기화·커넥션 재사용과 교체를 제한된 기능 시험으로 확인하고 남은 플랫폼·복구 범위를 기록한다. | PASS (네이티브 PostgreSQL·MySQL 4건). SQL Server·Oracle 확장 NOT RUN. |
| RELEASE-010 / FR-010 / ADR-005 | tools/release-pool/, tools/verify-product-g5.py, evidence/PRODUCT-G5-*.json, docs/en/, docs/ko/ | 소유한 네이티브 DB를 정상 종료하고 동일 fixture 데이터를 루프백에서 재기동해 기존 커밋·롤백과 후속 쓰기를 검증한다. | PASS (네이티브 PostgreSQL·MySQL 2건). 비정상 종료 복구와 커밋 결과 불명 NOT RUN. |

[제품 G5 기준](32-PRODUCT-G5-ACCEPTANCE.md) · [범위별 판정](../../evidence/PRODUCT-G5-ACCEPTANCE.json).

| 요구 ID | 허용 경로 | 완료 조건 | 상태 |
|---|---|---|---|
| RELEASE-011 / FR-010·013 / ADR-005 | tools/release-failure/, tools/verify-product-g5.py, evidence/PRODUCT-G5-*.json, docs/en/, docs/ko/ | 소유한 시험 DB의 비정상 종료를 증명하고 재기동 후 승인된 커밋이 남고 미커밋 데이터가 없는지 확인한다. 격리 연결에서 커밋 응답 유실을 재현해 독립 연결로 결과를 확인하고 Guard의 자동 재시도 금지를 검증한다. | PASS (네이티브 PostgreSQL·MySQL 4건). |
| RELEASE-012 / FR-017 / ADR-005 | tools/release-provider/, tools/verify-product-g5.py, evidence/PRODUCT-G5-*.json, docs/en/, docs/ko/ | SQL Server와 Oracle 지원 범위를 넓히기 전에 플랫폼·격리·라이선스·정확한 DBMS와 드라이버를 확인한다. 프로파일별 실행 결과와 확보하지 못한 선행조건을 기록한다. | Oracle Free ARM64 풀 일부 PASS (2건). SQL Server 네이티브 환경 미확보로 NOT RUN. |
| RELEASE-013 / FR-010·013·017 / ADR-005 | tools/release-provider/, tools/verify-product-g5.py, evidence/PRODUCT-G5-*.json, docs/en/, docs/ko/ | Oracle JDBC 취소·타임아웃·물리 세션 교체와 복구를 격리된 시험 범위에서 검증한다. SQL Server 전용 호스트 선행조건을 확인하고 검증 증거를 바탕으로 G5를 재판정한다. | Oracle 기능 5건 PASS. SQL Server 네이티브 G5 NOT RUN. 제품 G5 BLOCKED. |
| RELEASE-014 / FR-010·013·017 / ADR-005 | tools/release-provider/, evidence/PRODUCT-G5-*.json, tools/verify-product-g5.py, docs/en/, docs/ko/ | 전용 네이티브 호스트의 준비 상태를 검증하고, Oracle 동시성·인스턴스 강제 종료 시험의 격리와 상한을 적용한 뒤 새 제품 G5 증거를 인정한다. | 준비 검증 PASS. SQL Server 호스트 및 Oracle 저장소·승인 대기. 신규 실DB 시험 NOT RUN. |
| RELEASE-026 / FR-010·013·017 / ADR-005 | tools/release-provider/, docs/en/, docs/ko/ | 기존 Linux ARM64 게스트의 가용 자원, 전용 로컬 Docker 인벤토리, 고정 Oracle 이미지, XFS 프로젝트 쿼터 선행조건을 점검한다. DB 워크로드 기동 없이 오프라인과 macOS에서 차단 경로를 검증한다. | PASS(오프라인 9건, macOS 플랫폼 차단, Core 스모크). 게스트 점검과 Oracle G5 NOT RUN. |
| RELEASE-025 / FR-010·013·017 / ADR-005 | tools/release-provider/, tools/verify-product-g5.py, evidence/PRODUCT-G5-SQLSERVER-*, docs/en/, docs/ko/ | 전용 네이티브 SQL Server 시험의 보호 실행기와 증거 검증을 구현한다. 승인, 소유권, 자원 상한, 실제 시나리오 결과와 정리를 오프라인 회귀로 검증한다. | 구현 및 오프라인 검증 PASS(테스트 22건, Java 17 대상 컴파일과 Core 스모크). 현 맥은 네이티브 호스트 조건에서 차단됐다. 네이티브 SQL Server G5 NOT RUN. [준비 증거](../../evidence/PRODUCT-G5-SQLSERVER-PREPARATION.json) |
| RELEASE-015 / NFR-02 / FR-008 | observe-core/, legacy-observe/, tools/release-performance/, tools/run-g5-performance.py, tools/verify-product-g5.py, evidence/PRODUCT-G5-*.json, docs/en/, docs/ko/ | Observe 반복 비용을 줄이고 메타데이터·JDBC 위임·관측 실패 격리를 보존한다. 기능 회귀를 검증하고 기존 실측을 보존한 뒤 별도 승인으로 실행한 후보를 검증한다. | 기능 PASS (Observe 215단언, 어댑터 196단언, H2 10건). OBSERVE-V2 p95 PostgreSQL FAIL (+26.2141%), MySQL PASS (-5.1442%). |
| RELEASE-016 / NFR-02 | tools/release-performance/, evidence/PRODUCT-G5-POSTGRESQL-ATTRIBUTION*.json, docs/en/, docs/ko/ | 제한된 PostgreSQL 쌍별 진단으로 JDBC 위임, SQL 지문 계산과 이벤트 처리를 계측한다. 시간 구간 합계·소스 일치·정리를 검증한다. | 진단 PASS (조회 208건, 실측 96쌍). OBSERVE-V2 G5 판정 보존. |
| RELEASE-021 / FR-017 | tools/release-provider/, evidence/RELEASE-READINESS-*.json, docs/en/, docs/ko/ | macOS와 기존 Parallels Ubuntu 게스트를 DB provider 선행조건에 대조한다. 체크아웃한 커밋에서 승인된 thin 모듈 6종의 로컬 패키징과 시험 키 서명을 검증한다. 최신 증거를 남기고 기존 런타임과 게시 게이트를 보존한다. | 실행 가능성 검토 완료. Core 스모크와 모의 번들 서명 PASS. 라이브러리 6종 재빌드, 실제 번들 리허설, Oracle 인스턴스 G5는 환경 준비까지 보류(NOT RUN). 네이티브 SQL Server G5는 별도 x86-64 호스트 필요(NOT RUN). 정식 게시 BLOCKED. [재개 조건](30-RELEASE-SUPPORT-EVIDENCE.md#현재-환경-판정과-재개-조건) |
| RELEASE-031 / NFR-02 / FR-017 | tools/release-performance/, docs/en/, docs/ko/ | 단일 A/A 잡음 규칙, 짝별 버전 차이 신뢰구간, 선언한 자원 기록 한도와 L2 중단 상태를 벤치마크 기동 없이 검증한다. 기존 L2 작업량과 G5 판정을 보존한다. | PASS(합성 테스트 15건, 보존 중단 기록 2건, Core 스모크, 기존 G5 판정 재현). JMH 실행기와 파일럿은 대기. |
| RELEASE-032 / NFR-02 / FR-017 | tools/release-performance/, evidence/OBSERVE-L1-JMH-PREPARATION.json, docs/en/, docs/ko/ | 고정 Observe 소스에 JDBC 캐시 적중 JMH 벤치마크 한 가지를 연결한다. 실측 없이 빌드·발견을 검증하고, 승인 없음 차단과 합성 자식의 자원 초과 종료·회수·정리를 검증한다. | PASS(Java 17 대상, 두 후보 연결·캐시 적중, 합성 12건, 진단 회귀 15건, Core 스모크). JMH 실측 NOT RUN. |
| RELEASE-033 / NFR-02 / FR-017 | evidence/OBSERVE-L1-HMAC-AA-01-*.json, docs/en/, docs/ko/ | 승인된 DB 없는 HMAC A/A 실행을 고정 실행기에 결합한다. 1회 승인 사용, 표본 3쌍, 자원 한도와 정리를 검증한다. | 승인, 수치 자원 한도와 정리 검증. 세 쌍 중 두 쌍을 확보했고 다섯 번째 표본 도중 메모리 압력이 상승해 파일럿 INCONCLUSIVE. 1회 승인 사용 완료. |
| RELEASE-034 / FR-017 / ADR-007 | docs/en/, docs/ko/, evidence/RELEASE-PUBLICATION-OFFLINE.json | 게시 결정안을 승인된 GAV 좌표 6개 및 제외 범위와 대조한다. 현재 배포 차단을 재현하고 Phase 6 CLI 합성 테스트와 G0 범위·제품 G5 증거를 독립 검증한다. | PASS(CLI 7건, Core 스모크, GAV 6개, G0와 제품 G5 증거 검증). 게시 범위 PENDING. 정식 배포 BLOCKED(HASH_MISMATCH). [오프라인 기록](../../evidence/RELEASE-PUBLICATION-OFFLINE.json) |
| RELEASE-035 / FR-017 / ADR-007 | docs/en/, docs/ko/, evidence/RELEASE-PUBLICATION-REGISTRY-CHECK.json | 기존 공개 좌표를 대조군으로 사용해 G0 승인 후보 좌표 6개의 Maven Central 공개 경로를 확인한다. 네임스페이스 검증 선행조건과 게시 역할 지정 상태를 기록한다. | 공개 조회 PASS(GAV 6개, 후보 HTTP 404 12건, 대조군 HTTP 200 2건). Core 스모크 PASS. 네임스페이스와 Portal 권한 UNVERIFIED. 게시 대상과 담당자 지정 PENDING. [공개 조회 기록](../../evidence/RELEASE-PUBLICATION-REGISTRY-CHECK.json) |
| RELEASE-036 / FR-017 / ADR-007 | docs/en/, docs/ko/, evidence/RELEASE-PUBLICATION-ALTERNATIVE.json | 대체 Maven 좌표 6개와 패키지 범위를 G0 승인과 대조하고 내부 POM 의존성 매핑을 오프라인에서 확인하며 공개 경로를 조회한다. | PASS(좌표 6개, 예상 내부 POM 참조 10개, 후보 HTTP 404 12건, 대조군 HTTP 200 2건, Core 스모크). 새 좌표 G0와 담당자 지정 PENDING. Portal 권한 UNVERIFIED. [비교 기록](../../evidence/RELEASE-PUBLICATION-ALTERNATIVE.json) |

## 기능 우선 검증

| 요구 ID | 경로 | 인수 검사 | 상태 |
|---|---|---|---|
| NEXT-001 / NFR-03 | core/, docs/en/, docs/ko/ | 합성 표식과 문자열 변환 시 실패하는 값 객체로 Core record 3개의 안전한 출력을 확인한다. 보호 Core 스모크에서 기존 값 계약, 컴파일과 바인딩 순서를 검증한다. | 2026-11-22 PASS. 보호 Core 스모크에서 정제 회귀, 기존 컴파일러 및 바인딩 검사를 통과했다. |
| NEXT-002 / FR-008 / FR-016 / NFR-03 | tools/sql-inventory-mapper.py, tools/test-sql-inventory-mapper.py, docs/en/, docs/ko/ | 로컬 base/head 인벤토리 보고서에서 Mapper XML 추가·변경·삭제, 동적 치환 위치와 불완전 범위를 검증한다. 메타데이터 출력, 입력 상한, DTD 처리, 종료 코드와 기존 보고서 회귀를 확인한다. | 2026-11-22 PASS. Mapper 테스트 9건, 인벤토리 회귀 12건, CLI 스모크와 보호 Core 스모크를 통과했다. 현재 리비전 DB 통합 검증은 NOT RUN이다. |
| NEXT-003 / FR-005 / FR-008 / FR-010 | legacy-observe/, legacy-compat-testkit/, tools/run-hibernate-observe.py, evidence/HIBERNATE-INSPECTOR-VALIDATION.json, docs/en/, docs/ko/ | Hibernate inspector 합성의 반환 참조·null·예외 계약을 검증한다. 기존 Hibernate/Spring/H2 fixture로 Observe OFF/ON의 SQL 치환, 업무 결과, 롤백과 관측 이벤트를 대조한다. 어댑터 계약과 보호 Core 스모크를 실행한다. | 2026-11-22 inspector 합성 PASS. H2 합성 4건, 기존 H2 10건, 어댑터 계약 213건과 Core 스모크 통과. 외부 DB 통합은 NOT RUN. 사유별 집계는 별도 행을 참조한다. |
| NEXT-003 사유 / FR-008 / NFR-03 | observe-core/, sql-inventory/, docs/en/, docs/ko/ | 직접 관측과 JDBC 캐시 적중 시의 enum 사유, 기존 지문 보존, 원문·값이 없는 수락 이벤트 집계를 확인한다. Observe·인벤토리 계약, 어댑터·H2 호환성 및 보호 Core 스모크를 실행한다. | 2026-11-22 PASS. Observe 246건·인벤토리 54건·어댑터 통합 14건, H2 호환 10건, 보고서 14건·Mapper 9건·스키마 영향 회귀 17건 및 Core 스모크 통과. 외부 DB 통합 NOT RUN. |

[NEXT-003 검증 증거](../../evidence/OBSERVE-REASONS-VALIDATION.json)
