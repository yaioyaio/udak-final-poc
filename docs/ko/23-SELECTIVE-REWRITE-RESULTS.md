# Phase 5 승인 SQL 선택 변환 결과

[English](../en/23-SELECTIVE-REWRITE-RESULTS.md) | 한국어

## 상태

**IN_PROGRESS / LOCAL PASS.** 4종 실DB 동등성, 전체 증거 검증 및 G4는 **NOT RUN**이다. 기존 전용 DB 8개를 보존하고 새 검증용 DB 4개를 추가하는 보존 상한 12개는 사용자 승인 대기 중이다. Phase 5에서 새 Docker 컨테이너를 생성하거나 기동한 수는 0개다.

| 실행한 검사 | 결과 |
|---|---|
| 승인 정책 / 파서 / JDBC 계약 | PASS, 단언 330 / 147 / 67개 |
| 인메모리 H2 동등성 | PASS, 단언 323개. 고정 paging·NULL 사례 7개를 포함한 검증 범주 8개 |
| 기존 Core / 파서 / API / 트랜잭션 정책 | PASS, 단언 74 / 83 / 313 / 123개 |
| 기존 혼용 H2 | PASS, 시나리오 10개 |
| 로컬 증거 검증 | PASS, 전체 20개 중 로컬 7개. 실DB 의존 13개 NOT RUN. 기본 보존 상한 8 차단 검사 PASS |
| 자동 임시 작업공간 정리 | PASS, 251개 파일과 40,499,519바이트 회수. worker 정지 확인, 임시 폴더 잔여 0개 |

[로컬 실행 증거](../../evidence/PHASE5-VALIDATION.json) · [로컬 증거 검증](../../evidence/PHASE5-LOCAL-VERIFIER-VALIDATION.json)

모듈 등록으로 `settings.gradle.kts` 해시가 바뀌어 Phase 4 증거 3개를 같은 보호 실행기로 재검증·갱신했다. Phase 4 소스와 실행기, 기존 G3 실DB 증거는 그대로 보존했다. 바로잡은 초기 Phase 5 사전검사의 증거는 `.git/udak-phase5/previous-reports`에 보존했다.

## 구현 계약

- `rewrite-core`의 JDK 전용 `Rewrite`가 `Registry`, `Template`, `Environment`, `Approval`, `Evidence`, `Provider`, `Plan` 계약을 제공한다. 신뢰된 운영자가 승인과 증거를 등록한다. 테스트용 승인을 운영 승인으로 간주하지 않으며, 운영 승인 발급은 별도의 신뢰된 운영자 판단이 필요하다.
- `rewrite-jsqlparser`의 `PaginationRewriteProvider`(`jsqlparser-5.4-subset-1`)는 정확히 `SELECT c1, c2 FROM t WHERE filter = ? ORDER BY c1 ASC LIMIT ? OFFSET ?` 형태인 PostgreSQL 문을 받는다. `t`와 컬럼들은 허용 목록의 식별자이며 `c1`은 검증 fixture의 고유 non-NULL 키다. 주석·추가 절 등 정규 형태 밖의 입력은 거부한다. 대상 PostgreSQL·MySQL·H2는 `LIMIT ? OFFSET ?`, SQL Server·Oracle은 `OFFSET ? ROWS FETCH NEXT ? ROWS ONLY`를 사용한다. 바인드 순서는 각각 filter/limit/offset, filter/offset/limit이다. DB별 인용 방식으로 `AS` 별칭을 붙여 원본 결과 라벨을 정확히 보존한다.
- Registry는 Query ID, 정확한 UTF-8 SQL의 SHA-256, 8개 환경 필드(소스·대상 DBMS, 소스·대상 서버 및 대상 드라이버 전체 버전 문자열의 SHA-256, 스키마·provider·runtime 버전), 증거 ID·해시·검증 항목, 대상 SQL과 바인드 순서·결과 라벨의 계획 지문, 유효기간 및 폐기 상태를 확인한다. 변환 전후에 승인 유효성을 다시 확인한다. 마지막 승인 검사 전 폐기는 진입을 차단한다. 이미 진입한 쿼리의 취소는 보장하지 않는다. 고정 드라이버 artifact 및 이미지 검증은 실행기의 별도 계약이다. 같은 버전 문자열을 반환하는 바이너리 진위는 버전 지문만으로 확인할 수 없다. 실행기는 manifest 식별자와 이미지 config ID를 구별하고 실행 전후 고정 입력을 대조한다.
- `rewrite-jdbc`의 `SelectiveJdbcClient.query(Template, Parameters, RowMapper)`가 변환을 명시적으로 실행한다. 대상 DB 제품 및 서버·드라이버 버전은 SQL 준비 전에 JDBC 메타데이터에서 확인한다. 입력은 filter 문자열(최대 1,024자) 또는 NULL, limit 1–1,000, offset 0–1,000,000이다. 읽기 SELECT만 준비하고 타입에 맞게 바인딩한다. 결과 라벨을 검사한 뒤 행 매핑을 위임하며 JDBC 쿼리 타임아웃은 5초다. 기존 Spring DataSource 트랜잭션에 참여한다. 거부 시 SQL 준비는 0회다. 원문 fallback, JPA flush/cache 자동 동기화, TransactionManager 변경은 수행하지 않는다. 기존 JPA·MyBatis·JdbcTemplate Observe 경로는 유지한다. UDAK 경계에서 예외를 정제한다. 외부 JDBC·Spring 및 운영 로깅에는 별도 설정이 적용된다.
- `rewrite-testkit`은 해당 승인 범위의 계약·행 결과·트랜잭션 경계를 검사한다. 동등성 범위는 고유 non-NULL 정수 키, 비어 있지 않은 문자열과 NULL, active/NULL 필터가 들어 있는 고정 fixture다. PostgreSQL INTEGER와 Oracle NUMERIC 같은 JDBC 타입 차이는 행 매퍼의 논리 int/String 값으로 비교한다. Oracle 빈 문자열과 MySQL collation을 포함한 일반 동등성은 범위 밖이다.

## 남은 검증

로컬 재현은 `python3 tools/run-phase5.py`다. 실DB 실행은 보존 자원 승인 이후에만 `python3 tools/run-phase5-real.py --retention-cap 12`로 진행한다. 기본 상한 8에서는 생성 전에 NOT RUN으로 종료한다. 실행기는 기존 관리형 DB의 소유권·정지 상태를 확인하고 새 실행 UUID를 기록한다. 한 번에 DB 하나를 기동하고 정지·보존한다. 실패 시 자원을 정지·보존하고 일회용 자격 증명을 폐기한다. 예를 들어 기존 8개와 실패 보존 1개가 남으면 4개를 새로 검증하는 데 최소 상한 13이 필요하다. 재개는 실보존 수에 맞는 상한 또는 동등 provider 승인에 따른다.

G4 완료에는 실제 PostgreSQL 원문 실행, 4종 대상 각각 8개씩 총 32개 범주의 원문·번역·독립 기대 결과 대조, 전체 verifier 20개 무건너뜀 통과가 필요하다. 해당 증거가 갖춰지면 `python3 tools/verify-phase5.py`로 G4를 확인한다. Phase 6은 G4 이후에 진행한다.

성능·부하, 일반 SQL과 다른 변환 방향, Boot/Gradle, XA, 정상 shutdown·recovery, 운영 승인 발급은 NOT RUN이다.
