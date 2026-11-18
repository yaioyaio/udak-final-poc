# Phase 3 레거시 Observe 검증 결과 (2026-11-18)

[English](../en/21-LEGACY-OBSERVE-RESULTS.md) | 한국어

## 검증 결과

| 요구 ID | 범위 | 결과 |
|---|---|---|
| P3-OBS / FR-005~008 / T-011~013 | JDK만으로 외부 classpath 없이 `observe-core` 컴파일·실행, `legacy-observe` 어댑터 계약 | PASS (202 + 188 assertions) |
| P3-COMPAT / FR-005~007·010 | `legacy-compat-testkit`의 실제 동일 DataSource 혼용 계약 | H2 10건 PASS, 관리형 실DB 4종 40건 G3 PASS |
| P3-HARNESS | Java 17 대상 컴파일, 기존 Core 계약·스모크, 고정 의존성·자동 정리 | PASS (Core 74 checks + smoke) |

Hibernate 6.6.53.Final, Spring Framework 6.2.19, Spring Data JPA 3.5.13, MyBatis 3.5.19, MyBatis-Spring 3.0.5를 사용했다. 실DB의 이미지 고정값과 상세 실행 결과는 증거에 기록했다. [최종 G3 판정](../../evidence/PHASE3-GATE.json) · [로컬 검증](../../evidence/PHASE3-VALIDATION.json) · [실DB 검증](../../evidence/PHASE3-REAL-VALIDATION.json) · [요구 추적](16-TRACEABILITY.md)

| DBMS | 서버 버전 | 드라이버 고정 버전 | 결과 |
|---|---|---|---|
| H2 | 2.3.232 | 2.3.232 | 10/10 PASS |
| PostgreSQL | 17.12 | 42.7.14 (`checker-qual` 3.55.1) | 10/10 PASS |
| MySQL | 8.4 | 26.10.0 (`protobuf-java` 4.36.1) | 10/10 PASS |
| SQL Server | 16.0 | 13.6.2.jre11 | 10/10 PASS (linux/amd64 에뮬레이션) |
| Oracle | 23.26 | 23.26.4.0.0 | 10/10 PASS |

실DB 드라이버와 전이 의존성 6개는 G2 고정 목록을 그대로 사용했다. [G2 드라이버 목록](../../tools/g2-dependencies.json) · [실DB 이미지 목록](../../tools/g2-server-images.json)

동작 8건은 Observe OFF 기준 실행과 ON 실행 모두에서 통과했다. 기존 Entity, Repository, Mapper, `MixedUserService`를 수정 없이 사용했고, 동일 물리 연결 공유, dirty UPDATE의 명시적 flush 전후 가시성, JPA/MyBatis 캐시의 stale 상태와 명시적 refresh/clear, 3개 접근 경로의 commit/rollback, JDBC RowMapper와 MyBatis ResultMap을 검증했다. 이벤트 메타데이터와 listener 실패 격리 2건은 ON에서 실행했다.

## Observe 계약과 한계

- Hibernate `StatementInspector`, MyBatis `StatementHandler.prepare`, JDBC `execute*` 시도 시점에 이벤트를 발행한다. 이 시점의 이벤트 수로 DB 실행 성공 건수를 산출할 수 없다. prepare를 건너뛰는 MyBatis 캐시 히트는 해당 이벤트를 발행하지 않는다.
- 이벤트는 enum과 SHA-256 해시 2개로 구성된다. raw SQL, 바인드·리터럴, 원본 ID, 접속·계정정보, 원본 예외는 이벤트에 담기지 않는다. SQL 입력은 최대 16,384자, 원본 query ID 입력은 최대 256자까지 처리한다. 지원 밖의 `EXEC`, 해석이 모호한 문자열, 복수 문장은 `UNAVAILABLE`로 수렴한다. 인용된 식별자는 공통 토큰으로 정규화하므로 서로 다른 SQL도 같은 shape 해시를 가질 수 있다.
- shape fingerprint는 인벤토리 분류용이다. 승인 판단은 기존 Core `SqlFingerprint`의 정확 SQL 해시 계약을 따른다. Observe가 추가하는 동작은 이벤트 발행이며, flush·캐시 관리는 애플리케이션과 프레임워크가 담당한다. SQL rewrite는 Phase 3 범위 밖이다.
- sink는 동기 호출된다. sink 소유자가 스레드 안전성과 신속한 비차단 반환을 책임진다. 비치명적 관찰 실패는 격리하고 `VirtualMachineError`와 `ThreadDeath`는 전파한다.
- MyBatis cursor·중첩 내부 호출이 Executor 프록시를 거치지 않으면 가장 가까운 인터셉트된 상위 ID 또는 shape 기반 대체 ID가 쓰인다. JPA/JDBC도 shape 기반 대체 ID를 사용하며 자동 호출 지점 ID는 미구현이다.
- 벤더 `unwrap`, JDBC connection builder, `ResultSet.getStatement`, `DatabaseMetaData.getConnection`에서 얻은 원본 객체 경로와 plain `Statement` 배치의 SQL은 관찰 범위 밖이다. 공유 wrapper는 명시적으로 연결하고 원본 DataSource와 풀의 수명은 소유자가 관리한다.

## 의존성과 실행 경계

Spring Boot 3.5.16 BOM으로 공개 Maven 의존성을 해석했다. JAR 36개(37,749,029 B)의 POM 라이선스·체크섬과 해당 고지 항목을 검증했다. LGPL Hibernate는 어댑터의 `compileOnly` 의존성으로 사용했고 저장소에 Phase 3 라이브러리 바이너리를 포함하지 않았다. 제품 재배포 승인 상태는 **NOT GRANTED**다. [Phase 3 의존성 목록](../../tools/phase3-dependencies.json)

| 항목 | 제한 및 정리 결과 |
|---|---|
| 자식 프로세스·JVM | CPU 시간 30초, heap 256 MiB, metaspace 128 MiB, 활성 CPU 2 |
| 전용 실DB | 동시 1개, 각 최대 4 GiB·CPU 2·PID 512, restart 정책 `no`, log driver `none`, loopback 바인딩 |
| 최종 H2 / 실DB 임시 작업 공간 | H2 105개·37,951,356 B, 실DB 143개·54,312,032 B 자동 제거, 잔여 작업 공간 0 |
| 컨테이너·데이터 | 생성 전 원자적으로 저널 기록, 종료 처리에서 컨테이너 정지·데이터 보존. 새 Phase 3 DB 4개와 기존 G2 DB 4개 모두 정지(8/8), 기존 자원 변경 0, DB 컨테이너·볼륨 삭제 0, 데이터 용량 미측정 |

SQL Server는 exit 137 / OOM 표시 false, Oracle은 143, PostgreSQL과 MySQL은 0으로 정지했다. 검증 상태는 고정 환경에서 수행한 기능 G3에 한정된다. 정상 종료·재기동 복구, 네이티브 SQL Server 플랫폼 인증, 성능·부하, Gradle 작업, Spring Boot 자동 구성 및 Boot 3/4 인증은 **NOT RUN**이다. [컨테이너 보존 요약](../../evidence/PHASE3-CONTAINER-RETENTION.json)

## 재현과 다음 단계

```bash
python3 tools/run-phase3.py
python3 tools/run-phase3-real.py
python3 tools/verify-phase3.py
```

첫 명령은 H2 검증, 두 번째는 전용 실DB 검증, 세 번째는 보존 증거의 정적 검증이다. 현재 보존 상한 8개에 도달했으므로 전용 DB를 새로 만드는 재실행에는 승인된 재사용 또는 회수로 여유 확보가 필요하다. 실행기는 DB를 자동 삭제하지 않는다.

Phase 4 Transaction Consistency Guard는 DataSource·트랜잭션 매니저 구성 오류와 전파, readOnly, timeout, isolation 진단을 다룬다. 범위는 로컬 트랜잭션 진단이며 XA 원자성은 포함하지 않는다. [트랜잭션 일관성 설계](06-TRANSACTION-CONSISTENCY.md)
