# Query approval and revocation history

English | [한국어](../ko/29-QUERY-APPROVAL-HISTORY.md)

Expansion Phase 5 adds persistent approval and revocation history to the opt-in JDBC path for approved SELECT rewrites. The existing approval policy rechecks the Query ID, SQL and plan fingerprints, source and target, environment versions, expiration, and evidence when deciding whether to admit a query. The application supplies trusted evidence.

## Open the journal and use it with JDBC

The `approval-history` module provides `dev.udak.rewrite.ApprovalHistory` and `dev.udak.rewrite.jdbc.ApprovalHistoryJdbcClient`.

1. Open a local journal with `ApprovalHistory.open(Path journal, Clock clock)` and close it when the application shuts down. Use a dedicated mode `0600` journal in a trusted private directory on a local POSIX filesystem that supports file locking. Keep the operational journal outside test scratch directories.
2. Register an approval with `long approve(Rewrite.Approval approval, Rewrite.Evidence evidence)`. Keep the returned generation for revocation. A successful approval or revocation is acknowledged after its event is durably written.
3. Construct `new ApprovalHistoryJdbcClient(dataSource, environment, history, provider)` and call `query(template, parameters, rowMapper)` using the same inputs as `SelectiveJdbcClient.query(...)`.
4. Revoke an approval with `boolean revoke(queryId, generation)`. A stale generation returns `false`. Revoke the active generation before registering a replacement. Revocation prevents later admissions for that generation, including after reopening. An execution already admitted may finish.
5. Call `history(queryId)` for immutable approval and revocation metadata. The journal retains identifiers, fingerprints, environment versions, and evidence links. Keep raw SQL, bind values, and free-text actor information out of the journal.

## Storage and recovery

The journal is locked for one local owner. Generations start at 1 for each query, and the chronological event sequence starts at 1 for the journal. The limit is 4,096 events, with one slot reserved for revoking each active query approval. A corrupt record or incomplete write prevents opening the journal for approval decisions. Preserve the file for investigation and verify the approval state before resuming use. An earlier intact copy can contain approvals revoked later, so restoring that copy cannot establish the current approval state. The journal relies on the private directory to protect the file from replacement and provides local admission control only.

Keep local audit journals under `.approval-history-local/` or use the filename pattern `*.udak-approval-history`. Git and Docker exclusions cover both. Keep the production journal in an operator-managed location outside test scratch directories.

## Validation

The guarded command for `APPROVAL-001`, `APPROVAL-002`, and `APPROVAL-003` runs the Core smoke test and the approval history and Spring JDBC/H2 contracts. These cover persistence and reopening, rejection of invalid journals and stale generations, query isolation, admission timing, and new approvals. [Requirement and test mapping](16-TRACEABILITY.md)

```bash
python3 tools/run-approval-history.py
```

**PASS.** The run passed 65 new JDK-only Core assertions and 36 new JDBC assertions against pinned H2 2.3.232. The existing Core smoke test, rewrite policy and JDBC regression tests, all 8 H2 equivalence cases with 323 assertions, and the isolated Gradle `jar` and `testClasses` tasks also passed. Automatic cleanup removed 1,124 temporary files totaling 390,648,221 bytes. [Execution evidence](../../evidence/APPROVAL-HISTORY-VALIDATION.json)

The new full real-DB matrix is **NOT RUN**. Release readiness is evaluated by the existing release gate and still depends on Phase 6 G0/G5, signing, and publication. An actual JDK 17 run, a full mixed-access demo run, and broader database support certification require separate evidence. [Release requirements](24-STARTERS-CLI-RELEASE-GATES.md)
