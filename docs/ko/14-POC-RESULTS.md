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
- jOOQ 또는 다른 외부 Parser/Translator Provider
- SQL rewriting runtime, JPA/MyBatis/JDBC Interceptors
- 실제 PostgreSQL/MySQL/SQL Server/Oracle 연결 및 integration tests
- 외부 SQL Engine 라이선스 검증 결과
- SQL semantics equivalence 증명/검증 리포트
- Boot4 Starter, CI/CD, performance benchmark

## 호환성 주장 금지

**SQL 렌더링 문자열은 4개 DBMS에 대한 실DB 동작 증거가 아니다.**

SQL parser의 제한, SQL Server ORDER BY 규칙, Oracle 11g 구문, 각 DBMS Driver와 차이는 반드시 실제 DB 통합 테스트 후 제품 지원 선언을 한다.
