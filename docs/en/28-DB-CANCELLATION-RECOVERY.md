# Database cancellation and recovery

English | [한국어](../ko/28-DB-CANCELLATION-RECOVERY.md)

Product expansion Phase 4 covers bounded functional checks of JDBC statement cancellation, query timeout and recovery after session loss. `RECOVERY-001` through `RECOVERY-003` record the acceptance criteria. [Traceability](16-TRACEABILITY.md)

## Run the isolated fixtures

Run from the repository root with Python 3, JDK 17 or later, Maven Central access and native macOS arm64 PostgreSQL 17 and MySQL 8.0 binaries. The runner uses one disposable database and one blocked write at a time.

```bash
python3 tools/run-db-recovery.py
```

| Database | JDBC driver | Validation status |
|---|---|---|
| PostgreSQL 17.11 | PostgreSQL JDBC 42.7.14 | PASS (3 scenarios, 56 assertions) |
| MySQL 8.0.46 | MySQL Connector/J 26.10.0 | PASS (3 scenarios, 56 assertions) |
| SQL Server | Separate validation | NOT RUN |
| Oracle | Separate validation | NOT RUN |

## What each scenario checks

| Scenario | Acceptance criteria |
|---|---|
| `JDBC_CANCEL` | An independent database session confirms the fixture write is waiting on a lock. The lock stays held while `Statement.cancel()` interrupts the write. Explicit transaction rollback clears the uncommitted changes. A subsequent transaction succeeds on the same physical session, identified on the database server. |
| `JDBC_TIMEOUT` | An independent database session confirms the same lock wait. The lock stays held while the JDBC query timeout interrupts the statement. Explicit rollback clears the uncommitted changes, and the same physical session can run a subsequent transaction. |
| `SESSION_LOSS` | Deliberately disconnect the owned fixture session before commit. Confirm from a separate session that its uncommitted change was rolled back. A fresh JDBC connection uses a different physical session and can commit a new transaction. |

An independent reader checks committed visibility.

PostgreSQL confirms the blocker and worker relationship with `pg_blocking_pids`. MySQL observes the fixture worker's exact active statement twice and probes the same InnoDB row with `FOR UPDATE NOWAIT`. Both fixtures check the row lock again after the worker's statement ends. The JDBC timeout path makes no explicit cancel call and checks elapsed time against the configured server wait limits.

## Actual validation results

| Scenario | Assertions per database | PostgreSQL 17.11 | MySQL 8.0.46 |
|---|---:|---|---|
| `JDBC_CANCEL` | 21 | SQLSTATE `57014` | `MySQLStatementCancelledException` with no SQLSTATE |
| `JDBC_TIMEOUT` | 21 | SQLSTATE `57014` | `MySQLTimeoutException` with no SQLSTATE |
| `SESSION_LOSS` | 14 | SQLSTATE `57P01` | SQLSTATE `08S01` |

After cancellation or timeout, PostgreSQL rejected subsequent statements in the aborted transaction with SQLSTATE `25P02` until explicit rollback. MySQL kept the transaction active until explicit rollback. Both databases reused the same physical session after rollback and recovered on a new session after pre-commit session loss.

All 112 assertions, eight evidence parser contract tests and Core smoke passed. The runner cleaned up both isolated database servers. [Execution and cleanup evidence](../../evidence/DB-RECOVERY-VALIDATION.json)

The deliberate disconnect establishes the outcome for the pre-commit fixture only. If a production connection is lost during commit and the outcome is unknown, never retry the transaction on that basis. G5 certification is separate. Expansion Phase 5 covers per-query approval and revocation history. [Expansion roadmap](09-WBS-ROADMAP.md)
