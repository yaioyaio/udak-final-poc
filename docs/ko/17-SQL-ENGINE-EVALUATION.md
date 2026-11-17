# Phase 1 SQL 엔진 비교와 라이선스 검토

[English](../en/17-SQL-ENGINE-EVALUATION.md) | 한국어

검토일: 2026-11-17. 요구 ID: **P1-ENGINE / T-002, P1-SPI / FR-001, P1-PROVIDER / FR-003·004**.

이번 PoC의 선택은 **upstream `com.github.jsqlparser:jsqlparser:5.4`의 Apache-2.0 경로와 Core 밖의 parser-validation adapter**다. 기존 제한 렌더러의 출력 SQL을 실제 외부 파서로 검사하여 SPI 교체 가능성을 검증한다. SQL 방언 번역기나 기존 SQL Rewrite 실행 엔진을 완성했다는 뜻은 아니다. 최종 실행 상태는 [추적표](16-TRACEABILITY.md)와 [PoC 결과](14-POC-RESULTS.md)의 증거를 따른다.

## 비교 기준

파싱은 SQL을 AST로 읽는 기능, 렌더링은 모델을 SQL로 출력하는 기능, 번역은 소스 방언의 의미를 대상 방언으로 옮기는 기능이다. 파싱 성공과 출력 문자열 일치는 DB에서의 실행·결과 동등성을 입증하지 않는다. 네 DBMS의 스키마·함수·타입·NULL·정렬·페이지네이션 차이는 별도 실DB 테스트 대상이다.

| 후보·검토 기준 | 기능과 UDAK 적합성 | JDK·의존성 | 라이선스·edition 판단 |
|---|---|---|---|
| jOOQ 3.21 계열; 소스 POM 3.21.9 | DSL, parser, dialect renderer와 parser→다른 dialect 렌더링 제공. 향후 번역 후보 | OSS 3.21은 Java 21. Java 17은 OSS 3.19 계열 또는 해당 상용 Java 17 배포본 검토. 3.21.9 POM에 R2DBC SPI·SLF4J, 선택적 JAXB 등이 있어 실제 선택 artifact의 의존성 해석 필요 | OSS Apache-2.0. Oracle·SQL Server 일반 상용 edition 대상은 Professional/Enterprise 경로 검토; Express의 Express DB 범위와 구분 |
| Apache Calcite 1.42.0 | parser·validator·관계 대수·optimizer·dialect unparser 제공. 스키마/타입 모델을 포함하는 향후 분석 후보 | 공식 HOWTO가 JDK 17을 빌드 선행조건 목록에 포함. UDAK Java 17 실행 검증은 NOT RUN. linq4j·Avatica·Guava·Jackson 등 의존성 범위가 넓음 | Apache-2.0. 실제 배포 구성의 전체 의존성·NOTICE 별도 검토 필요 |
| JSqlParser upstream 5.4 | SQL↔AST, visitor·deparse. 이번에는 제한된 생성 SQL의 구문 검사에만 사용 | 고정 POM은 Java release 11, 빌드 toolchain `[17,24)`. 직접 compile/runtime 의존성 없이 test 의존성 선언; 실제 JAR·JDK 검증은 별도 실행 증거 | LGPL-2.1 또는 Apache-2.0 중 선택 가능. 이번 PoC는 Apache-2.0 선택 |

jOOQ의 기능 근거는 [parser translator](https://www.jooq.org/doc/latest/manual/sql-building/sql-parser/sql-parser-translator/), [JDK matrix](https://www.jooq.org/download/support-matrix-jdk), [3.21.9 POM](https://raw.githubusercontent.com/jOOQ/jOOQ/version-3.21.9/jOOQ/pom.xml), [edition 비교](https://www.jooq.org/download/)다. Calcite는 [공식 기능 문서](https://calcite.apache.org/docs/), [1.42.0 다운로드](https://calcite.apache.org/downloads/), [빌드 선행조건](https://calcite.apache.org/docs/howto.html), [고정 버전 의존성](https://raw.githubusercontent.com/apache/calcite/calcite-1.42.0/core/build.gradle.kts)을 확인했다. JSqlParser는 [고정 tag README](https://raw.githubusercontent.com/JSQLParser/JSqlParser/jsqlparser-5.4/README.md)와 [고정 tag POM](https://raw.githubusercontent.com/JSQLParser/JSqlParser/jsqlparser-5.4/pom.xml)을 확인했다.

## 네 DBMS 범위

| 후보 | PostgreSQL | MySQL | SQL Server | Oracle |
|---|---|---|---|---|
| jOOQ | OSS dialect 범위; 버전 조건 확인 | OSS dialect 범위; 버전 조건 확인 | OSS 범위 아님. Express DB와 일반 edition 계약 구분 | OSS 범위 아님. Express DB와 일반 edition 계약 구분 |
| Calcite | `PostgresqlSqlDialect` | `MysqlSqlDialect` | `MssqlSqlDialect` | `OracleSqlDialect` |
| JSqlParser | 통합 grammar 대상 | 통합 grammar 대상 | 통합 grammar 대상; 인용 식별자 설정 주의 | 통합 grammar 대상 |

jOOQ는 [edition별 DB 목록](https://www.jooq.org/download/)과 [RDBMS 버전 matrix](https://www.jooq.org/download/support-matrix)를 함께 적용한다. Calcite의 클래스는 [JDBC dialect unparser API](https://calcite.apache.org/javadocAggregate/org/apache/calcite/sql/dialect/package-summary.html)에 존재한다. JSqlParser의 범위는 [upstream README의 grammar 대상](https://raw.githubusercontent.com/JSQLParser/JSqlParser/jsqlparser-5.4/README.md)이다. 이 표는 공급자 기능 분류이며 UDAK의 네 DBMS 지원 완료표가 아니다. 이번 실DB 검증은 모두 **NOT RUN**이다. Oracle 11g/12c 등 렌더 프로필이 여러 개여도 별도 DBMS 개수나 실DB 지원 증거로 세지 않는다.

## 선택 근거와 artifact 식별

JSqlParser는 제한된 SPI 실험에 필요한 AST 파싱을 작은 의존성 경계로 추가할 수 있다. 자체 범용 parser 구현을 피하고 Core의 외부 의존성 없음도 유지한다. jOOQ는 향후 번역 요구에 적합하지만 JDK·edition·계약 선택이 먼저다. Calcite의 planner/metadata 통합은 이번 단순 compiler 계약 검증에 비해 범위가 크다는 설계 판단으로 보류한다. 속도·메모리 우위를 주장하지 않으며 성능 시험은 실행하지 않는다.

- 고정 좌표: `com.github.jsqlparser:jsqlparser:5.4`; 소스 tag: `jsqlparser-5.4`.
- 배포 확인 대상: [Maven Central POM](https://repo.maven.apache.org/maven2/com/github/jsqlparser/jsqlparser/5.4/jsqlparser-5.4.pom), [JAR](https://repo.maven.apache.org/maven2/com/github/jsqlparser/jsqlparser/5.4/jsqlparser-5.4.jar), [공식 SHA-512](https://repo.maven.apache.org/maven2/com/github/jsqlparser/jsqlparser/5.4/jsqlparser-5.4.jar.sha512). 실제 해시·크기·class 버전은 실행 증거에 기록한다.
- README/현재 웹의 Manticore 추천 좌표 `com.manticore-projects.jsqlformatter:jsqlparser`와 upstream 좌표를 혼용하지 않는다. 가변 버전이나 문서의 예제 버전을 채택하지 않는다. tag README의 배포 안내도 artifact/POM 동일성 검증을 대신하지 않는다.
- 지휘자의 사전 artifact 검사에서 JAR 내부 LICENSE/NOTICE entry가 없음을 확인했다. JAR만 복사하는 배포는 라이선스 고지를 충족했다고 판정할 수 없다. 고정 tag의 라이선스를 별도 번들하고 그 번들을 검증해야 한다.

## 라이선스 적용·배포 조건

JSqlParser의 선택 근거는 이중 라이선스를 명시한 README와 POM, [고정 tag LICENSE_APACHEV2](https://raw.githubusercontent.com/JSQLParser/JSqlParser/jsqlparser-5.4/LICENSE_APACHEV2)다. Apache-2.0 경로에서는 라이선스 사본 제공, 수정 파일 표시, 해당 원본 고지 보존, 원 배포에 NOTICE가 있으면 관련 고지 전달이 필요하다. 상표 권리·무조건적 보증은 부여되지 않는다. 이 선택을 근거로 LGPL 경로 의무를 함께 적용한다고 쓰거나 라이선스 고지를 생략하지 않는다.

Calcite도 [1.42.0 LICENSE](https://raw.githubusercontent.com/apache/calcite/calcite-1.42.0/LICENSE)의 Apache-2.0 조건과 포함 구성요소의 고지를 확인해야 한다. jOOQ는 [라이선스 구분](https://www.jooq.org/legal/licensing)에 따라 OSS와 상용 경로를 분리하고, 상용 도입 시 [공식 계약](https://www.jooq.org/legal/250331_jOOQ_License_and_Maintenance_Agreement.pdf)의 개발자·배포 범위를 실제 계약 주체와 확인한다. 엔진 라이선스만으로 제삼자 의존성 조건이 사라지지 않는다.

이번 판정은 **PoC 기술 검증에 사용할 라이선스 선택의 근거 확인**이다. ADR-007의 제품 배포 승인, 법무 판단, 상용 계약 체결 또는 구매 승인을 대체하지 않는다. 의존성이 없다는 POM 관찰도 포함 코드의 출처 감사·취약점 검사 완료를 뜻하지 않는다. 외부 배포 전 실제 패키지의 라이선스/고지와 선택 좌표를 다시 확인한다.

## 검증 게이트

| 게이트 | 필요한 증거 | 이 문서의 상태 |
|---|---|---|
| P1-ENGINE / T-002 공식 비교 | 위 공식 자료, 고정 좌표·라이선스 선택·한계 | 문서 조사 완료 |
| 고정 artifact 무결성·라이선스 번들 | POM/JAR/라이선스 해시, scope 구분, JAR 고지 부재와 별도 번들 확인 | 최종 상태는 추적표·PoC 결과의 별도 실행 증거 참조 |
| P1-SPI / FR-001 | 기본/외부 provider에 동일 계약: 바인딩 순서·값 비인라인·불변성·잘못된 입력 거부 | 실행 담당 검증; 이 문서만으로 PASS 아님 |
| P1-PROVIDER / FR-003·004 | Java 17 대상 컴파일, 실제 parser 호출, 제한 프로필 및 실패 경로 | 실행 담당 검증; 이 문서만으로 PASS 아님 |
| 실DB·레거시 번역·제품 배포 | 후속 범위의 별도 검증과 승인 | NOT RUN |

Phase 1 완료는 문서 비교만으로 선언하지 않는다. [추적표](16-TRACEABILITY.md)의 계획과 연결된 artifact·계약 테스트의 실제 PASS가 필요하다. 이 문서 작성 작업 자체에서는 빌드·테스트·앱·DB·Docker를 실행하지 않았다.
