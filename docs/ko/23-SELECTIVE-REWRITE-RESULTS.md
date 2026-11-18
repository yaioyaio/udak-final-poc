# Phase 5 승인 SQL 선택 변환 결과

[English](../en/23-SELECTIVE-REWRITE-RESULTS.md) | 한국어

## 상태

**G4 PASS.** Phase 5 승인 SQL 선택 변환의 고정 fixture 구현·검증을 완료했다. 원문 PostgreSQL SQL은 실제 PostgreSQL에서 실행했다. 네 DBMS 대상의 canonical 결과 digest는 H2와 일치했다. 전체 증거 verifier 20개가 건너뜀 없이 통과했다. 운영 승인은 미부여다.

| 실행한 검사 | 결과 |
|---|---|
| 승인 정책 / 파서 / JDBC 계약 | PASS, 단언 330 / 147 / 67개 |
| 인메모리 H2 동등성 | PASS, 단언 323개. 고정 paging·NULL 사례 7개를 포함한 검증 범주 8개 |
| 기존 Core / 파서 / API / 트랜잭션 정책 | PASS, 단언 74 / 83 / 313 / 123개 |
| 기존 혼용 H2 | PASS, 시나리오 10개 |
| 전체 증거 검증 | PASS, 검사 20개, 건너뜀 0개 |

| 대상 DBMS | 검증 범주 | 단언 | 정지·보존한 컨테이너 | 종료 코드 | OOM |
|---|---:|---:|---|---:|---|
| PostgreSQL | 8 | 379 | `udak-g2-bf826cd260b74d22bda11df37f0a4b4b-postgresql` | 0 | false |
| MySQL | 8 | 323 | `udak-g2-bf826cd260b74d22bda11df37f0a4b4b-mysql` | 0 | false |
| SQL Server | 8 | 323 | `udak-g2-bf826cd260b74d22bda11df37f0a4b4b-sqlserver` | 137 | false |
| Oracle | 8 | 323 | `udak-g2-bf826cd260b74d22bda11df37f0a4b4b-oracle` | 143 | false |
| **합계** | **32** | **1,348** | | | |

[로컬 실행](../../evidence/PHASE5-VALIDATION.json) · [실DB 실행](../../evidence/PHASE5-REAL-VALIDATION.json) · [전체 verifier](../../evidence/PHASE5-VERIFIER-VALIDATION.json) · [G4 판정](../../evidence/PHASE5-GATE.json) · [컨테이너 보존](../../evidence/PHASE5-CONTAINER-RETENTION.json)

모듈 등록으로 `settings.gradle.kts` 해시가 바뀌어 Phase 4 증거 3개를 같은 보호 실행기로 재검증·갱신했다. Phase 4 소스와 실행기, 기존 G3 실DB 증거는 그대로 보존했다. 바로잡은 초기 Phase 5 사전검사의 증거는 `.git/udak-phase5/previous-reports`에 보존했다.

## 구현 계약

- `rewrite-core`의 JDK 전용 `Rewrite`가 `Registry`, `Template`, `Environment`, `Approval`, `Evidence`, `Provider`, `Plan` 계약을 제공한다. 신뢰된 운영자가 승인과 증거를 등록한다. 테스트용 승인을 운영 승인으로 간주하지 않으며, 운영 승인 발급은 별도의 신뢰된 운영자 판단이 필요하다.
- `rewrite-jsqlparser`의 `PaginationRewriteProvider`(`jsqlparser-5.4-subset-1`)는 정확히 `SELECT c1, c2 FROM t WHERE filter = ? ORDER BY c1 ASC LIMIT ? OFFSET ?` 형태인 PostgreSQL 문을 받는다. `t`와 컬럼들은 허용 목록의 식별자이며 `c1`은 검증 fixture의 고유 non-NULL 키다. 주석·추가 절 등 정규 형태 밖의 입력은 거부한다. 대상 PostgreSQL·MySQL·H2는 `LIMIT ? OFFSET ?`, SQL Server·Oracle은 `OFFSET ? ROWS FETCH NEXT ? ROWS ONLY`를 사용한다. 바인드 순서는 각각 filter/limit/offset, filter/offset/limit이다. DB별 인용 방식으로 `AS` 별칭을 붙여 원본 결과 라벨을 정확히 보존한다.
- Registry는 Query ID, 정확한 UTF-8 SQL의 SHA-256, 8개 환경 필드(소스·대상 DBMS, 소스·대상 서버 및 대상 드라이버 전체 버전 문자열의 SHA-256, 스키마·provider·runtime 버전), 증거 ID·해시·검증 항목, 대상 SQL과 바인드 순서·결과 라벨의 계획 지문, 유효기간 및 폐기 상태를 확인한다. 변환 전후에 승인 유효성을 다시 확인한다. 마지막 승인 검사 전 폐기는 진입을 차단한다. 이미 진입한 쿼리의 취소는 보장하지 않는다. 고정 드라이버 artifact 및 이미지 검증은 실행기의 별도 계약이다. 같은 버전 문자열을 반환하는 바이너리 진위는 버전 지문만으로 확인할 수 없다. 실행기는 manifest 식별자와 이미지 config ID를 구별하고 실행 전후 고정 입력을 대조한다.
- `rewrite-jdbc`의 `SelectiveJdbcClient.query(Template, Parameters, RowMapper)`가 변환을 명시적으로 실행한다. 대상 DB 제품 및 서버·드라이버 버전은 SQL 준비 전에 JDBC 메타데이터에서 확인한다. 입력은 filter 문자열(최대 1,024자) 또는 NULL, limit 1–1,000, offset 0–1,000,000이다. 읽기 SELECT만 준비하고 타입에 맞게 바인딩한다. 결과 라벨을 검사한 뒤 행 매핑을 위임하며 JDBC 쿼리 타임아웃은 5초다. 기존 Spring DataSource 트랜잭션에 참여한다. 거부 시 SQL 준비는 0회다. 원문 fallback, JPA flush/cache 자동 동기화, TransactionManager 변경은 수행하지 않는다. 기존 JPA·MyBatis·JdbcTemplate Observe 경로는 유지한다. UDAK 경계에서 예외를 정제한다. 외부 JDBC·Spring 및 운영 로깅에는 별도 설정이 적용된다.
- `rewrite-testkit`은 해당 승인 범위의 계약·행 결과·트랜잭션 경계를 검사한다. 동등성 범위는 고유 non-NULL 정수 키, 비어 있지 않은 문자열과 NULL, active/NULL 필터가 들어 있는 고정 fixture다. PostgreSQL INTEGER와 Oracle NUMERIC 같은 JDBC 타입 차이는 행 매퍼의 논리 int/String 값으로 비교한다. Oracle 빈 문자열과 MySQL collation을 포함한 일반 동등성은 범위 밖이다.

## 보존·재현·다음 단계

사용자가 보존 상한 8→12개를 승인한 뒤 `python3 tools/run-phase5-real.py --retention-cap 12`로 4종을 한 번에 하나씩 기동했다. 새 4개와 기존 8개는 모두 정지·보존 상태이며 활성 관리형 컨테이너는 0개다. 기존 자원 변경, 컨테이너 삭제, DB 볼륨 삭제는 각각 0건이다. 보존 데이터 용량은 미측정이다. SQL Server 종료 코드 137의 OOM 표시는 false다. Oracle 종료 코드는 143이다. 정상 종료·재시작 복구 및 SQL Server 네이티브 플랫폼 인증은 NOT RUN이며 G4는 기능 검증에 한정된다.

자동 정리는 로컬 251개 파일·40,499,519바이트와 실DB 271개 파일·56,807,090바이트를 회수했다. 총 522개 파일·97,306,609바이트이며 임시 폴더 잔여는 0개다. 별도로 verifier와 G4 점검이 각각 소유 파일 한 개(119바이트, 64바이트)를 회수했다.

로컬 재현은 `python3 tools/run-phase5.py`다. 기존 증거만 확인하는 명령은 `python3 tools/verify-phase5.py`다. 현재 보존 12개 상태에서 새 4종을 다시 실행하려면 총 16개를 보존할 여유에 대한 별도 승인 또는 동등하게 검증된 provider가 필요하다. 기존 상한 승인 범위는 12개이며 자동 자원 삭제는 수행하지 않는다.

일반 SQL 동등성, 임의 데이터·bind, 다른 변환 방향, Oracle 빈 문자열 및 MySQL collation, Boot/Gradle, XA, 성능·부하, 운영 승인 발급은 검증 범위 밖이다. 다음 Phase 6은 Boot3·Boot4 별도 Starter, CLI, 로컬 CI 및 정식 배포를 다룬다. GitHub Actions는 사용하지 않는다. 배포·라이선스 승인은 별도 게이트다.
