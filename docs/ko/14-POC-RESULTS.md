# 실행 결과 및 검증 한계 (2026-11-17)

[English](../en/14-POC-RESULTS.md) | 한국어

## 실제 실행 — PASS

실행 환경: OpenJDK 21, `javac --release 17`로 컴파일, 외부 의존성 없음.

명령:

```bash
./tools/run-core-smoke.sh
```

결과 파일: `evidence/core-smoke-output.txt`.

테스트에 포함된 항목:

- PostgreSQL/MySQL LIMIT ? OFFSET ? 렌더링
- SQL Server/Oracle 19 OFFSET ? ROWS FETCH NEXT ? ROWS ONLY 렌더링
- Oracle 11 ROWNUM 렌더링(문자열 시연만)
- SQL 조건 필터 및 페이징 bind 순서
- 허용되지 않은 식별자 차단
- 유효하지 않은 pageSize 차단
- SQL hash가 변하면 승인 변환 차단
- 대상 DBMS가 바뀌면 승인 변환 차단
- 복수 DataSource 로컬 원자성 정책 경고(예외)

## 소스 제공 — NOT RUN

- `spring-boot-demo`: Spring Boot 3.5.16 / JPA / MyBatis / JdbcTemplate / H2.
- Gradle이 설치되지 않았고 Maven Central 접근이 가능한 네트워크 환경이 없어 빌드·실행하지 못함.
- 따라서 Spring Boot 데모의 컴파일, Spring 컨텍스트 기동, @Transactional 테스트 결과는 주장하지 않음.

## 미구현 — NOT IMPLEMENTED

- 신규 공개 Fluent DSL 전체, CRUD executor
- SQL 방언 Translator Provider·jOOQ 연동(Phase 1 parser-validation provider는 구현됨)
- SQL rewriting runtime, JPA/MyBatis/JDBC Interceptors
- 실제 PostgreSQL/MySQL/SQL Server/Oracle 연결 및 integration tests
- 외부 SQL Engine 라이선스 검증 결과
- SQL semantics equivalence 증명/검증 리포트
- Boot4 Starter, CI/CD, performance benchmark

## 호환성 주장 금지

**SQL 렌더링 문자열은 4개 DBMS에 대한 실DB 동작 증거가 아니다.**

SQL parser의 제한, SQL Server ORDER BY 규칙, Oracle 11g 구문, 각 DBMS Driver와 차이는 반드시 실제 DB 통합 테스트 후 제품 지원 선언을 한다.

## Phase 1 실행 검증 — PASS

재현 명령: `python3 tools/run-phase1.py`. 증거: [PHASE1-VALIDATION.json](../../evidence/PHASE1-VALIDATION.json).

- 공식 자료 기반 jOOQ·Calcite·JSqlParser 비교와 upstream `com.github.jsqlparser:jsqlparser:5.4` Apache-2.0 경로의 기술적 적합성 검증 완료. 제품 배포·법무·상용 계약 승인과 구분한다.
- 고정 JAR/POM SHA-512와 공식 JAR SHA-512, 번들 LICENSE 해시·고지, 직접 compile/runtime 의존성 없음, class major 55를 확인했다. JAR에 고지가 없어 어댑터 META-INF에 별도 LICENSE/NOTICE를 포함했다.
- Core smoke PASS, 기본 Compiler 계약 74개·외부 parser 계약 83개 PASS. Java 17 대상으로 실제 컴파일하고 5개 렌더 프로필, 바인딩 전체 이름/값/순서·값 비인라인·얕은 불변성·잘못된 입력·단일 SELECT·다중 문장 차단을 검사했다.
- 최초 외부 부정 테스트가 다중 문장 누락을 검출했다. statement-list 파싱과 정확히 한 개 SELECT 검사로 수정한 뒤 통과했다. 이전 실패 보고서는 `.git/udak-phase1/previous-reports/`에 보존했다. 독립 검토에서 확인한 테스트 공유·bind 값·parser 독립 거절 검사도 보강했다.
- 시간·CPU·JVM·다운로드·파일/출력 상한 아래 실행했다. 실패·timeout·signal·실제 예외 전파·래퍼 종료 후 후손 프로세스 정리 검사가 통과했고, 실제 회수 파일/용량·잔여 여부·process group 종료는 증거에 기록한다. 불명 자료는 보존하며 기존 Core smoke trap을 유지한다.
- 이번 완료 범위는 외부 엔진 비교·선택 artifact 라이선스 검증·SPI/파서 계약이다. G0 전체 제품 배포 승인, 4종 실DB 동등성, Spring 데모, Gradle 태스크 실행, SQL 번역·성능/부하 검증은 NOT RUN이다.

차기 작업은 Phase 2의 최소 CRUD/Query 계약(FR-002·FR-014, T-006)과 Spring-aware JDBC executor(T-008), DBMS별 실환경 검사 기반이다. 시작 전에 양언어 추적표에 테스트 계획을 등록하고 기존 ORM 의미와 트랜잭션 경계를 보존한다.

## Phase 2 요청 기반 검증 — PASS / 전체 G2 미완료

[PHASE2-VALIDATION.json](../../evidence/PHASE2-VALIDATION.json)의 실제 검사에서 Core smoke, Java 17 대상 컴파일, Phase 1 기본 74개·외부 parser 83개 회귀, CRUD API 313개, 실제 Spring JDBC 6.2.19/H2 2.3.232 기능 검사, DB foundation 45개와 정리 probe 5개가 PASS다. [상세 계약과 범위](18-CRUD-JDBC-VALIDATION.md)를 따른다.

PostgreSQL·MySQL·SQL Server·Oracle은 전용 승인 provider가 없어 모두 NOT RUN이다. 실제 서버/driver 버전·결과·트랜잭션 증거가 없어 전체 Phase 2 G2를 완료로 판정하지 않는다. 새로운 컨테이너·Spring Boot 앱·Gradle·실DB는 실행하지 않았다.

초기 공개 checksum 다운로드와 정리 probe 오류 기록은 `.git/udak-phase2/previous-reports/`에 보존했다. 공개 SHA-512가 없는 Spring artifact는 공식 공개 SHA1과 별도 고정 SHA-512 pin을 구분해 확인했다. 이후 제한된 probe 및 전체 실제 검사는 통과했다. 초기 권한 오류의 빈 진단 파일 1개/0바이트는 불명 자료로 보존하며 소유·미사용 확인 전 삭제하지 않는다. 최신 성공 실행의 임시 자료 회수와 이 보존 예외를 구분한다.
