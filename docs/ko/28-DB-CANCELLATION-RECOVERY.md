# DB 쿼리 취소와 복구

[English](../en/28-DB-CANCELLATION-RECOVERY.md) | 한국어

제품 확장 Phase 4는 제한된 범위에서 JDBC 문장 취소, 쿼리 타임아웃, 세션 종료 후 복구를 검증한다. 인수 기준은 `RECOVERY-001`부터 `RECOVERY-003`까지 기록한다. [추적성](16-TRACEABILITY.md)

## 격리된 fixture 실행

저장소 루트에서 실행한다. Python 3, JDK 17 이상, Maven Central 접근과 macOS 네이티브 arm64 PostgreSQL 17 및 MySQL 8.0 바이너리가 필요하다. 실행기는 한 번에 임시 DB 한 개에서 잠금으로 대기하는 쓰기 한 건을 검증한다.

```bash
python3 tools/run-db-recovery.py
```

| DB | JDBC 드라이버 | 검증 상태 |
|---|---|---|
| PostgreSQL 17.11 | PostgreSQL JDBC 42.7.14 | PASS (시나리오 3개, 단언 56개) |
| MySQL 8.0.46 | MySQL Connector/J 26.10.0 | PASS (시나리오 3개, 단언 56개) |
| SQL Server | 별도 검증 | NOT RUN |
| Oracle | 별도 검증 | NOT RUN |

## 시나리오별 검증 기준

| 시나리오 | 인수 기준 |
|---|---|
| `JDBC_CANCEL` | 독립된 DB 세션에서 fixture 쓰기의 잠금 대기를 확인한다. 잠금을 유지한 채 `Statement.cancel()`로 쓰기를 중단한다. 명시적으로 트랜잭션을 롤백해 미커밋 변경을 되돌리고, DB 서버에서 확인한 동일 물리 세션에서 후속 트랜잭션이 성공하는지 검증한다. |
| `JDBC_TIMEOUT` | 독립된 DB 세션에서 동일한 잠금 대기를 확인한다. 잠금을 유지한 상태에서 JDBC 쿼리 타임아웃으로 문장이 중단되는지 확인한다. 명시적 롤백으로 미커밋 변경을 되돌리고 동일 물리 세션에서 후속 트랜잭션을 실행한다. |
| `SESSION_LOSS` | 커밋 전에 실행기가 소유한 fixture 세션을 의도적으로 종료한다. 별도 세션에서 미커밋 변경이 롤백됐는지 확인한다. 새 JDBC 커넥션이 다른 물리 세션을 사용하며 새 트랜잭션을 커밋할 수 있는지 검증한다. |

독립된 읽기 세션으로 커밋된 데이터의 가시성을 확인한다.

PostgreSQL은 `pg_blocking_pids`로 차단 세션과 작업 세션의 관계를 확인한다. MySQL은 해당 작업 세션의 활성 문장을 두 번 확인하고 같은 InnoDB 행에 `FOR UPDATE NOWAIT`를 실행해 잠금 충돌을 확인한다. 두 시험 모두 작업 세션의 문장이 끝난 뒤 같은 행의 잠금을 다시 검사한다. JDBC 타임아웃 경로에서는 명시 취소를 호출하지 않으며 경과 시간을 서버 대기 한도와 대조한다.

## 실제 검증 결과

| 시나리오 | DB별 단언 수 | PostgreSQL 17.11 | MySQL 8.0.46 |
|---|---:|---|---|
| `JDBC_CANCEL` | 21 | SQLSTATE `57014` | `MySQLStatementCancelledException`, SQLSTATE 없음 |
| `JDBC_TIMEOUT` | 21 | SQLSTATE `57014` | `MySQLTimeoutException`, SQLSTATE 없음 |
| `SESSION_LOSS` | 14 | SQLSTATE `57P01` | SQLSTATE `08S01` |

취소 또는 타임아웃 후 PostgreSQL은 트랜잭션을 실패 상태로 두었고, 명시적 롤백까지 후속 문장에 SQLSTATE `25P02`를 반환했다. MySQL은 명시적 롤백까지 트랜잭션을 활성 상태로 유지했다. 두 DB 모두 롤백 후 동일한 물리 세션을 재사용했고, 커밋 전 세션 종료 후에는 새 물리 세션에서 복구했다.

단언 112개, 증거 파서 계약 검사 8개, Core smoke를 통과했다. 실행기는 두 격리 DB 서버를 정리했다. [실행 및 정리 증거](../../evidence/DB-RECOVERY-VALIDATION.json)

이 세션 종료로 확인하는 결과는 커밋 전 fixture에 한정된다. 운영 환경에서 커밋 도중 연결이 끊어져 커밋 결과를 알 수 없다면, 연결 종료만을 근거로 트랜잭션을 재시도하면 안 된다. G5 인증은 별도다. 확장 Phase 5는 쿼리별 승인·폐기 이력을 다룬다. [확장 로드맵](09-WBS-ROADMAP.md)
