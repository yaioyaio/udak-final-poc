# Legacy Observe adoption pilot

English | [한국어](../ko/34-LEGACY-ADOPTION-PILOT.md)

NEXT-005 / FR-005 / FR-006 / FR-007 / FR-008 / NFR-03. Start with one testable path in an existing application that shares a DataSource across Hibernate, MyBatis and JdbcTemplate. Apply Observe through explicit Java configuration. The reference configuration uses Hibernate 6.6.53.Final, Spring Framework 6.2.19, MyBatis 3.5.19, MyBatis-Spring 3.0.5 and H2 2.3.232. [Traceability](16-TRACEABILITY.md) · [Phase 3 results and version scope](21-LEGACY-OBSERVE-RESULTS.md)

## Wire Observe into the existing application

Use the repository's `legacy-observe` and `sql-inventory` modules. Choose OFF or ON before constructing and initializing the factories. In OFF keep the original DataSource and existing Hibernate inspector. In ON create one wrapper and pass the same reference to the JPA factory, its local transaction manager, the MyBatis factory and JdbcTemplate. Let the application continue to own the original DataSource and connection pool.

```java
var capture = new InventoryCapture();
var observer = new SqlObserver(capture);
DataSource shared = observeEnabled ? new ObserveDataSource(originalDataSource, observer)
        : originalDataSource;

jpaFactory.setDataSource(shared);
StatementInspector inspector = existingInspector;
if (observeEnabled) {
    inspector = existingInspector == null ? new HibernateObserveInspector(observer)
            : HibernateObserveInspector.compose(existingInspector, observer);
}
if (inspector != null) {
    jpaFactory.getJpaPropertyMap().put("hibernate.session_factory.statement_inspector", inspector);
}

if (observeEnabled) {
    myBatisConfiguration.addInterceptor(new MyBatisObserveInterceptor(observer));
}
myBatisFactory.setDataSource(shared);
myBatisFactory.setConfiguration(myBatisConfiguration);
myBatisFactory.setTransactionFactory(new SpringManagedTransactionFactory());

var jdbc = new JdbcTemplate(shared);
// After initializing the existing JPA factory:
var transactionManager = new JpaTransactionManager(entityManagerFactory);
transactionManager.setDataSource(shared);
```

Here `jpaFactory` is the existing `LocalContainerEntityManagerFactoryBean`, `myBatisFactory` is the existing `SqlSessionFactoryBean`, and `existingInspector` is the application's inspector instance, or `null`. Use the application's existing factory lifecycle, `SqlSessionTemplate`, and local transaction manager configuration. Register the interceptor once for an ON configuration. The Hibernate composition preserves the inspector's return value and exception behavior and observes the effective SQL. [Reference integration test](../../legacy-compat-testkit/src/test/java/dev/udak/compat/LegacyCompatibilityTest.java#L283)

Compare the same business results and rollback in OFF and ON. Keep the application's current flush, cache and transaction boundaries. When another access path must see a pending JPA write, test the existing explicit flush point. Test stale cache behavior and explicit refresh or clear separately. The verified transaction contract covers the shared local DataSource. [Observe contract and limits](21-LEGACY-OBSERVE-RESULTS.md) · [Local transaction diagnostics](22-TRANSACTION-GUARD-RESULTS.md)

## Collect sanitized diagnostics

Use a separate `InventoryCapture` for each run. Wrap each same-thread test action in a try-with-resources scope such as `capture.scope("MYBATIS_USER_LOOKUP", "LOOKUP_CASE")`. Use stable synthetic IDs across comparisons. After all producers finish, call `snapshotJson(revision, profile)` with the revision as 40 or 64 lowercase hexadecimal characters and the profile as a 64-character lowercase hexadecimal digest. Compare equivalent profiles with the inventory report. Review dropped observations before interpreting differences. [Inventory usage and report](25-SQL-INVENTORY-PR-REPORT.md)

For a custom sink, implement both methods on `ObservationSink` and capture the reason in `accept(SqlObservation, UnavailableReason)`. A one-argument sink receives only the observation. The reason is the first lexical rejection. `NONE` means a normalized shape, and `UNSPECIFIED` means the unavailable observation carried no specific reason. Codes such as `UNSUPPORTED_SYNTAX`, `AMBIGUOUS_SYNTAX` and `SQL_TOO_LONG` describe normalization coverage. Emit bounded counts by framework, observation point and reason, using a fast, thread-safe sink. Keep raw SQL, bind values and literals, original IDs, paths, connection and account details, secrets and exception text out of the record. [Fixed reason codes](../../observe-core/src/main/java/dev/udak/observe/UnavailableReason.java) · [Reason contract test](../../observe-core/src/test/java/dev/udak/observe/ObserveContractTest.java#L80)

`JPA_INSPECT`, `MYBATIS_PREPARE` and `JDBC_EXECUTE` count observations at their respective boundaries. A single operation can appear at multiple boundaries, and a MyBatis cache hit can skip prepare. Record SQL success through business assertions. Shape fingerprints support inventory grouping and can coincide across SQL forms. Use the separate exact SQL fingerprint and approval workflow for transformation decisions. [Legacy compatibility and approval](05-LEGACY-COMPATIBILITY.md)

## Diagnose gaps in Observe coverage

- **Successful SQL with unavailable normalization.** For the H2 metadata query, the `InventoryIntegrationTest` and `compare_gap` checks verified a successful query result, one `JDBC_EXECUTE` event, one `UNSUPPORTED_SYNTAX` unavailable observation, no normalized shape and zero dropped observations. The inventory comparison reports `INCOMPLETE` (exit 2). Confirm the result with an independent assertion, then use the target DB and dialect with a small synthetic fixture to reproduce the normalization reason.
- **MyBatis local cache hit.** In `LegacyCompatibilityTest.verifyMyBatisCache`, the asserted `MYBATIS_PREPARE` count changes were `[1, 0, 1, 0, 1]` in one session and transaction. The first read prepares a statement. Reads after a JDBC update and after a JPA flush hit the local cache. The read after each explicit cache clear prepares a statement and sees the current value. Verify the result of each read independently. Check that the comparison uses the same session, transaction and local cache mode. Clear the cache only in an isolated test. If a confirmed cache miss still yields no observation, check interceptor registration, capture scope and dropped counts.

Record business results, event counts and capture scope separately. Use a DB result assertion to confirm SQL success on a path that reached the database. An empty capture or a missing event alone leaves the cause undetermined. The protected run passed both fixed H2 examples. [Coverage example validation](../../evidence/OBSERVE-COVERAGE-EXAMPLES-VALIDATION.json)

## Rehearse on the existing H2 integration

```bash
python3 -B tools/run-legacy-adoption.py
```

The fixture defines two expected review candidates before comparison. One MyBatis case changes SQL shape under a stable logical ID, and one JDBC case adds observed coverage. An independent control changes only a bind value and should produce no review candidate. A separate SQL-successful case with unsupported normalization should report a sanitized unavailable reason. Compare the actual and expected candidate sets and count unexpected candidates in this fixture. Record setup locations by configuration responsibility (shared DataSource, Hibernate, MyBatis and JDBC wiring) and record manual setup time as unmeasured. The fixture can show that the expected cases are distinguishable under its fixed conditions.

The internal rehearsal passed. It found both expected review candidates and zero unexpected findings across the five unchanged inventory entries. The separate H2 metadata query succeeded and yielded one `UNSUPPORTED_SYNTAX`, correctly marking that comparison `INCOMPLETE`. The harness verified three integration hooks and the same demo source with Observe OFF and ON. It passed ten legacy checks, four inspector checks, 28 pilot inventory assertions, 14 original capture assertions and protected Core smoke. Operator setup time was unmeasured. Only in-memory H2 ran. [H2 metadata command reference](https://h2database.github.io/html/commands.html#show) · [Rehearsal evidence](../../evidence/LEGACY-ADOPTION-VALIDATION.json)

## Independent order service pilot

The user designated an empty repository for the order pilot. It established a Spring application baseline before adding Observe in a separate test source set. JPA stores and flushes the order, MyBatis reserves stock, and JdbcTemplate records the audit through one DataSource and local transaction. The unchanged baseline passed 25 assertions and the Observe pilot passed 107. OFF and ON produced the same success response and stored state. A failure after all three writes restored the starting order, stock and audit state.

The report showed one review candidate for the active-stock predicate, with MyBatis and JDBC observations. The binding-only control had zero false positives across three inventory entries. A successful H2 metadata query yielded one `UNSUPPORTED_SYNTAX` and `INCOMPLETE` coverage. The first ON wiring and factory initialization took 20.411 ms with three configuration hooks. Manual maintainer setup time was unmeasured. Existing production legacy adoption and external DB validation are NOT RUN. [Independent pilot evidence](../../evidence/ORDER-ADOPTION-PILOT-VALIDATION.json)

## Apply to an approved legacy project

Production legacy adoption status **NOT RUN**. With an approved project and test environment, agree on one workflow, the allowed test scope, participating frameworks and expected controls. Compare OFF and ON behavior and workload coverage. Have a maintainer review each reported candidate against the expected change or coverage gap.

Record actionable findings, false positives, and setup effort. Use synthetic case labels, enum codes, counts, the reviewed denominator and time spent on configuration and verification. Record which configuration responsibilities changed and where the checks had incomplete coverage. Keep raw SQL, input and result data, local paths, original identifiers, accounts, credentials and logs out of the shared evidence. Use the reviewed results to decide whether the project benefits from a wider rollout.

### ThingsBoard CE external pilot

The external target for NEXT-005 is ThingsBoard CE `v4.3.1.8` at `ebbfc6789b81a4e04cae2711208130fb2841b31f`. Keep the source in a separate detached checkout named `thingsboard-ce-v4.3.1.8`. The sparse public-source checkout excluded 45 environment and key files. The checkout is clean and the excluded blobs are absent locally. [Upstream release](https://github.com/thingsboard/thingsboard/releases/tag/v4.3.1.8)

The fixed workflow is device registration in `dao`. Run `DeviceServiceTest#testFindDeviceById` to compare saved and retrieved state and `DeviceServiceTest#testShouldRollbackValidatedDeviceIfDeviceCredentialsValidationFailed` to check that a rejected device is absent after rollback. The published-jar execution uses the Surefire test goal with those exact method names and one fork. The existing PostgreSQL initializer recreates its test schema. Use a dedicated test database, and require Surefire results for both methods with zero failures, errors or skips before establishing the baseline. [Successful registration test](https://github.com/thingsboard/thingsboard/blob/v4.3.1.8/dao/src/test/java/org/thingsboard/server/dao/service/DeviceServiceTest.java#L610) · [Rollback test](https://github.com/thingsboard/thingsboard/blob/v4.3.1.8/dao/src/test/java/org/thingsboard/server/dao/service/DeviceServiceTest.java#L216) · [PostgreSQL initializer](https://github.com/thingsboard/thingsboard/blob/v4.3.1.8/dao/src/test/java/org/thingsboard/server/dao/PostgreSqlInitializer.java#L18-L49)

Once the baseline passes, enable the UDAK Hibernate inspector through test-only configuration of the primary `entityManagerFactory`, preserving any supported existing inspector. Keep the application and original test bodies unchanged. Compare both methods with Observe OFF and ON and record the business assertions, fingerprint coverage and connection effort. Verify a reviewed upstream SQL change as a separate check after establishing behavioral compatibility.

The official ThingsBoard Maven repository supplied the published `langchain4j-bom:1.16.1-TB1`, parent POM, and both POM/JAR pairs for `langchain4j` and `langchain4j-core`. All six files matched the supplier's SHA-256 checksums. JAR metadata confirmed both module coordinates. Keep the artifacts in the external pilot's isolated Maven repository. Preserve the earlier dependency diagnostics as historical evidence. [Official artifact verification](../../evidence/THINGSBOARD-TB1-OFFICIAL-ARTIFACTS.json) · [Earlier dependency diagnostics](../../evidence/THINGSBOARD-DEVICE-PILOT-DEPENDENCIES.json)

The official published DAO test JAR and the published dependencies were verified with supplier checksums. The DAO POM and both test configuration resources matched the pinned source. On PostgreSQL 18, Surefire reported 2 tests, 0 failures, 0 errors and 0 skips in each of two executions. The corroborating run observed one new PostgreSQL test container during execution. The process group, temporary workspace, test container and any additional volumes were cleared. The host used the verified local PostgreSQL 18.7 image under the required major-version tag. [Baseline results](../../evidence/THINGSBOARD-DEVICE-BASELINE-VALIDATION.json) · [Earlier source-build diagnostics](../../evidence/THINGSBOARD-DAO-REACTOR-VALIDATION.json)

Both Observe modes passed the two unchanged published methods on separate PostgreSQL 18 instances. OFF recorded no events. ON attached the Hibernate inspector once and captured 17 events (16 shapes) in registration and lookup and 7 events (7 shapes) in rollback. Both captures had zero dropped or unavailable events. Capture is scoped to synchronous execution within those test methods. [Observe comparison](../../evidence/THINGSBOARD-OBSERVE-AND-SQL-CHANGE-VALIDATION.json)

For ThingsBoard PR #14858, the parent and change source blobs were verified. The original COUNT pair and a UUID-only control were executed through UDAK JDBC observation against a disposable PostgreSQL 18 table with two synthetic tenants. The report showed one removed and one added fingerprint for the same logical query, one impacted replay test, and zero changes for the UUID-only control. The replay exercised the pinned statements and isolated fixture. Full historical ThingsBoard application runs are NOT RUN. Maintainer manual setup time remains unmeasured. [Upstream PR](https://github.com/thingsboard/thingsboard/pull/14858) · [SQL replay evidence](../../evidence/THINGSBOARD-OBSERVE-AND-SQL-CHANGE-VALIDATION.json)

### ThingsBoard adoption review

An independent technical review confirmed one actionable COUNT change and zero false positives in the UUID-only control. The replay code associates the impacted test hash through an explicit inventory scope. A local runbook rehearsal with verified cached inputs measured 1.229 seconds for checking artifacts, rebuilding the Observe overlay and staging it. The source and evidence review with 28 inventory regression tests took 1.048 seconds. The PostgreSQL replay, report checks and cleanup took 3.011 seconds after resource preflight. The observed-test links in the base and head inventory snapshots matched the impacted hash in the report. Upstream maintainer review is pending, and maintainer hands-on setup and verification time remains unmeasured. [Adoption review evidence](../../evidence/THINGSBOARD-NEXT-005-ADOPTION-REVIEW.json)

Limit the next expansion to a separate published ThingsBoard PR with one SQL change in the same Device DAO. Register one affected replay test and verify its report hash, use the same profile, require a complete report, confirm the PostgreSQL result assertions and literal-only negative control, and verify cleanup. Record a maintainer-led setup and verification time when that review takes place. [Adoption review evidence](../../evidence/THINGSBOARD-NEXT-005-ADOPTION-REVIEW.json)

### Maintainer hands-on timing

On the pilot Mac, use the verified warm-cache ThingsBoard layout, JDK 21 and the pinned PostgreSQL image. Run from the UDAK root in your own terminal, selecting your actual role.

```bash
python3 -B tools/thingsboard-pilot/run-maintainer-review.py --role thingsboard-maintainer
```

UDAK maintainers use `--role udak-maintainer` and record their own review scope. Time setup from the first Enter through the integrity and cleanup confirmation. Time verification from the second Enter through review of the changed query and UUID control counts. The tool runs the pinned COUNT replay, checks the inventory snapshots and impacted test hash, runs inventory regression tests, and verifies container and workspace cleanup. Resource preflight precedes timing, and an interrupted session is incomplete. [Replay and review scope](#thingsboard-adoption-review)

Artifact and overlay setup can start at macOS memory pressure level 1 or 2 with at least 768 MiB of free swap. PostgreSQL verification requires level 1 and the same swap headroom. After setup confirmation the tool saves the setup timing. If PostgreSQL verification has to wait, run the printed `--resume RECEIPT_NAME` command with the same role. Verification starts its own timer after the resource check.

The tool prints a metadata-only `NEXT-005-MAINTAINER-*.json` receipt name in the local pilot layout. Supply a PASS receipt with both timings, the declared role and the explicit review confirmation. Roles are self-declared. The `--rehearsal` mode validates the workflow with a rehearsal receipt. [Timing tool](../../tools/thingsboard-pilot/run-maintainer-review.py)
