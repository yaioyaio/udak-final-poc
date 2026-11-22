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

## Rehearse on the existing H2 integration

```bash
python3 -B tools/run-legacy-adoption.py
```

The fixture defines two expected review candidates before comparison. One MyBatis case changes SQL shape under a stable logical ID, and one JDBC case adds observed coverage. An independent control changes only a bind value and should produce no review candidate. A separate SQL-successful case with unsupported normalization should report a sanitized unavailable reason. Compare the actual and expected candidate sets and count unexpected candidates in this fixture. Record setup locations by configuration responsibility (shared DataSource, Hibernate, MyBatis and JDBC wiring) and record manual setup time as unmeasured. The fixture can show that the expected cases are distinguishable under its fixed conditions.

The internal rehearsal passed. It found both expected review candidates and zero unexpected findings across the five unchanged inventory entries. The separate H2 metadata query succeeded and yielded one `UNSUPPORTED_SYNTAX`, correctly marking that comparison `INCOMPLETE`. The harness verified three integration hooks and the same demo source with Observe OFF and ON. It passed ten legacy checks, four inspector checks, 28 pilot inventory assertions, 14 original capture assertions and protected Core smoke. Operator setup time was unmeasured. Only in-memory H2 ran. [H2 metadata command reference](https://h2database.github.io/html/commands.html#show) · [Rehearsal evidence](../../evidence/LEGACY-ADOPTION-VALIDATION.json)

## Apply to an approved legacy project

External pilot status **NOT RUN**. With an approved project and test environment, agree on one workflow, the allowed test scope, participating frameworks and expected controls. Compare OFF and ON behavior and workload coverage. Have a maintainer review each reported candidate against the expected change or coverage gap.

Record actionable findings, false positives, and setup effort. Use synthetic case labels, enum codes, counts, the reviewed denominator and time spent on configuration and verification. Record which configuration responsibilities changed and where the checks had incomplete coverage. Keep raw SQL, input and result data, local paths, original identifiers, accounts, credentials and logs out of the shared evidence. Use the reviewed results to decide whether the project benefits from a wider rollout.
