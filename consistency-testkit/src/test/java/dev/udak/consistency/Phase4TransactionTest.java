package dev.udak.consistency;

import dev.udak.consistency.TransactionGuard.Code;
import dev.udak.consistency.TransactionGuard.Intent;
import dev.udak.consistency.TransactionGuard.Isolation;
import dev.udak.consistency.TransactionGuard.Outcome;
import dev.udak.consistency.TransactionGuard.Propagation;
import dev.udak.consistency.TransactionGuard.Report;
import dev.udak.consistency.TransactionGuard.Rollback;
import dev.udak.consistency.TransactionGuard.Severity;
import dev.udak.consistency.TransactionGuard.Snapshot;
import dev.udak.consistency.TransactionGuard.Timeout;
import dev.udak.consistency.TransactionGuard.Violation;
import dev.udak.consistency.spring.SpringConsistencyGuard;
import dev.udak.consistency.spring.SpringConsistencyGuard.Configuration;
import dev.udak.demo.UserEntity;
import jakarta.persistence.EntityManagerFactory;
import java.io.OutputStream;
import java.io.PrintStream;
import java.sql.Connection;
import java.util.ArrayList;
import java.util.List;
import java.util.logging.Level;
import java.util.logging.LogManager;
import java.util.logging.Logger;
import javax.sql.DataSource;
import org.apache.ibatis.logging.LogFactory;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSessionFactoryBuilder;
import org.apache.ibatis.transaction.TransactionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.h2.jdbcx.JdbcDataSource;
import org.hibernate.jpa.SpecHints;
import org.mybatis.spring.SqlSessionTemplate;
import org.mybatis.spring.transaction.SpringManagedTransactionFactory;
import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.ConnectionHolder;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.orm.jpa.JpaTransactionManager;
import org.springframework.orm.jpa.LocalContainerEntityManagerFactoryBean;
import org.springframework.orm.jpa.persistenceunit.PersistenceManagedTypes;
import org.springframework.orm.jpa.vendor.HibernateJpaVendorAdapter;
import org.springframework.transaction.IllegalTransactionStateException;
import org.springframework.transaction.NestedTransactionNotSupportedException;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionTimedOutException;
import org.springframework.transaction.UnexpectedRollbackException;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Executes the Phase 4 contracts with an owned H2 database on the current thread. */
public final class Phase4TransactionTest {
    private static final int TIMEOUT_SECONDS = 5;
    private static final String CREATE_TABLE = "CREATE TABLE udak_phase4_entry (id integer PRIMARY KEY, val integer)";
    private static final String DROP_TABLE = "DROP TABLE udak_phase4_entry";
    private static final String CLEAR_TABLE = "DELETE FROM udak_phase4_entry";
    private static final String INSERT = "INSERT INTO udak_phase4_entry (id, val) VALUES (?, ?)";
    private static final String SELECT_IDS = "SELECT id FROM udak_phase4_entry ORDER BY id";

    private enum Scenario {
        CONFIGURATION,
        REQUIRED_ROLLBACK_ONLY,
        REQUIRES_NEW_BOUNDARY,
        NESTED_SAVEPOINT,
        JPA_NESTED_GUARD,
        READ_ONLY_WRITE,
        ISOLATION_PARTICIPATION,
        TIMEOUT_BOUNDARY,
        MISSING_AND_FOREIGN_TRANSACTION,
        UNKNOWN_OUTCOME_NO_RETRY
    }

    private final JdbcDataSource dataSource = dataSource();
    private final JdbcDataSource foreignDataSource = dataSource();
    private final DataSourceTransactionManager jdbcManager = jdbcManager(dataSource);
    private final DataSourceTransactionManager foreignManager = jdbcManager(foreignDataSource);
    private final JdbcTemplate jdbc = jdbc(dataSource);
    private final JpaFactory jpaFactory = new JpaFactory(dataSource);
    private final Configuration jdbcConfig = jdbcConfiguration(jdbcManager);
    private final List<Scenario> completedScenarios = new ArrayList<>();
    private JpaTransactionManager jpaManager;
    private Configuration jpaConfig;
    private String stage = "BOOTSTRAP";
    private int assertions;

    public static void main(String[] args) {
        PrintStream protocol = System.out;
        Phase4TransactionTest test = null;
        try {
            suppressRuntimeOutput();
            if (args.length != 0) {
                protocol.println("H2 FAIL: INVALID_ARGUMENT");
                System.exit(2);
                return;
            }
            test = new Phase4TransactionTest();
            test.run();
            protocol.println("H2 PASS");
            protocol.println("CHECKS=" + test.completedScenarios.size());
            protocol.println("CLEANUP=CONFIRMED");
            for (Scenario scenario : test.completedScenarios) {
                protocol.println("SCENARIO=" + scenario.name() + ":PASS");
            }
            protocol.println("ASSERTIONS=" + test.assertions);
        } catch (Throwable failure) {
            protocol.println("H2 FAIL: " + (test == null ? "BOOTSTRAP" : test.stage));
            printDiagnostic(protocol, failure);
            System.exit(1);
        }
    }

    private void run() throws Exception {
        checkThreadClean();
        Connection anchor = dataSource.getConnection();
        try (anchor) {
            jdbc.execute(CREATE_TABLE);
            try (AutoCloseable table = () -> jdbc.execute(DROP_TABLE); jpaFactory) {
                jpaFactory.start();
                jpaManager = new JpaTransactionManager(jpaFactory.get());
                jpaManager.setDefaultTimeout(TIMEOUT_SECONDS);
                jpaConfig = new Configuration(dataSource, List.of(dataSource), List.of(jpaManager),
                        jpaFactory.get(), myBatis(new SpringManagedTransactionFactory()), jdbc);
                run(Scenario.CONFIGURATION, this::configuration);
                run(Scenario.REQUIRED_ROLLBACK_ONLY, this::requiredRollbackOnly);
                run(Scenario.REQUIRES_NEW_BOUNDARY, this::requiresNewBoundary);
                run(Scenario.NESTED_SAVEPOINT, this::nestedSavepoint);
                run(Scenario.JPA_NESTED_GUARD, this::jpaNestedGuard);
                run(Scenario.READ_ONLY_WRITE, this::readOnlyWrite);
                run(Scenario.ISOLATION_PARTICIPATION, this::isolationParticipation);
                run(Scenario.TIMEOUT_BOUNDARY, this::timeoutBoundary);
                run(Scenario.MISSING_AND_FOREIGN_TRANSACTION, this::missingAndForeignTransaction);
                run(Scenario.UNKNOWN_OUTCOME_NO_RETRY, this::unknownOutcomeNoRetry);
                stage = "CLEANUP";
            }
        }
        check(anchor.isClosed());
        checkThreadClean();
        check(completedScenarios.equals(List.of(Scenario.values())));
    }

    private void run(Scenario scenario, Runnable checkScenario) {
        stage = scenario.name();
        jdbc.update(CLEAR_TABLE);
        checkScenario.run();
        checkThreadClean();
        completedScenarios.add(scenario);
    }

    private void configuration() {
        Report jdbcReport = SpringConsistencyGuard.inspectConfiguration(jdbcConfig);
        check(!jdbcReport.hasErrors());
        jdbcReport.requireAllowed();
        checkCode(SpringConsistencyGuard.inspectConfiguration(jdbcConfiguration(foreignManager)),
                Code.RESOURCE_MISMATCH);
        checkCode(SpringConsistencyGuard.inspectConfiguration(new Configuration(dataSource,
                List.of(dataSource, foreignDataSource), List.of(jdbcManager), null, null, jdbc)),
                Code.MULTIPLE_DATA_SOURCES);
        checkCode(SpringConsistencyGuard.inspectConfiguration(new Configuration(dataSource, List.of(dataSource),
                List.of(jdbcManager, foreignManager), null, null, jdbc)), Code.MULTIPLE_TRANSACTION_MANAGERS);
        checkCode(SpringConsistencyGuard.inspectConfiguration(new Configuration(dataSource, List.of(dataSource),
                List.of(jdbcManager), null, myBatis(new JdbcTransactionFactory()), jdbc)),
                Code.MYBATIS_NOT_SPRING_MANAGED);

        try (JpaFactory otherFactory = new JpaFactory(dataSource)) {
            otherFactory.start();
            checkCode(SpringConsistencyGuard.inspectConfiguration(new Configuration(dataSource, List.of(dataSource),
                    List.of(jpaManager), otherFactory.get(), jpaConfig.myBatis(), jdbc)),
                    Code.ENTITY_MANAGER_FACTORY_MISMATCH);
        }
        check(!SpringConsistencyGuard.inspectConfiguration(jpaConfig).hasErrors());

        transaction(jpaManager, TransactionDefinition.PROPAGATION_REQUIRED).executeWithoutResult(status -> {
            Snapshot snapshot = SpringConsistencyGuard.snapshot(jpaConfig);
            check(status.isNewTransaction() && snapshot.actualTransactionActive() && snapshot.synchronizationActive());
            check(snapshot.resourceBound());
            check(snapshot.entityManagerBound());
            check(TransactionSynchronizationManager.hasResource(dataSource));
            check(TransactionSynchronizationManager.hasResource(jpaFactory.get()));
            check(!inspect(jpaConfig, intent(false, true, Propagation.REQUIRED, false)).hasErrors());
        });
    }

    private void requiredRollbackOnly() {
        TransactionTemplate required = transaction(jdbcManager, TransactionDefinition.PROPAGATION_REQUIRED);
        expect(UnexpectedRollbackException.class, () -> required.executeWithoutResult(outer -> {
            check(outer.isNewTransaction());
            ConnectionHolder outerHolder = connectionHolder(dataSource);
            write(1);
            required.executeWithoutResult(inner -> {
                check(!inner.isNewTransaction());
                check(connectionHolder(dataSource) == outerHolder);
                write(2);
                inner.setRollbackOnly();
            });
            check(outer.isRollbackOnly());
            check(SpringConsistencyGuard.snapshot(jdbcConfig).rollback() == Rollback.MARKED);
            checkBlocked(inspect(jdbcConfig, intent(true, false, Propagation.REQUIRED, true)), Code.ROLLBACK_ONLY);
        }));
        check(ids().isEmpty());
    }

    private void requiresNewBoundary() {
        TransactionTemplate required = transaction(jdbcManager, TransactionDefinition.PROPAGATION_REQUIRED);
        TransactionTemplate requiresNew = transaction(jdbcManager, TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        required.executeWithoutResult(outer -> {
            ConnectionHolder outerHolder = connectionHolder(dataSource);
            Connection outerConnection = outerHolder.getConnection();
            write(1);
            requiresNew.executeWithoutResult(inner -> {
                check(inner.isNewTransaction());
                ConnectionHolder innerHolder = connectionHolder(dataSource);
                check(innerHolder != outerHolder);
                // JdbcDataSource supplies direct H2 connections in this fixture.
                check(innerHolder.getConnection() != outerConnection);
                Report report = inspect(jdbcConfig, intent(true, false, Propagation.REQUIRES_NEW, true));
                checkCode(report, Code.REQUIRES_NEW_INDEPENDENT_COMMIT);
                check(Code.REQUIRES_NEW_INDEPENDENT_COMMIT.severity() == Severity.WARNING && !report.hasErrors());
                write(2);
            });
            check(connectionHolder(dataSource) == outerHolder);
            check(connectionHolder(dataSource).getConnection() == outerConnection);
            outer.setRollbackOnly();
        });
        check(ids().equals(List.of(2)));

        required.setReadOnly(true);
        required.executeWithoutResult(outer -> {
            check(SpringConsistencyGuard.snapshot(jdbcConfig).readOnly());
            requiresNew.executeWithoutResult(inner -> check(!SpringConsistencyGuard.snapshot(jdbcConfig).readOnly()));
            check(SpringConsistencyGuard.snapshot(jdbcConfig).readOnly());
        });
    }

    private void nestedSavepoint() {
        TransactionTemplate required = transaction(jdbcManager, TransactionDefinition.PROPAGATION_REQUIRED);
        TransactionTemplate nested = transaction(jdbcManager, TransactionDefinition.PROPAGATION_NESTED);
        required.executeWithoutResult(outer -> {
            ConnectionHolder outerHolder = connectionHolder(dataSource);
            write(1);
            nested.executeWithoutResult(inner -> {
                check(inner.hasSavepoint() && !inner.isNewTransaction());
                check(connectionHolder(dataSource) == outerHolder);
                check(!inspect(jdbcConfig, intent(true, false, Propagation.NESTED, true)).hasErrors());
                write(2);
                check(ids().equals(List.of(1, 2)));
                inner.setRollbackOnly();
            });
            check(!outer.isRollbackOnly());
            check(ids().equals(List.of(1)));
        });
        check(ids().equals(List.of(1)));
    }

    private void jpaNestedGuard() {
        TransactionTemplate required = transaction(jpaManager, TransactionDefinition.PROPAGATION_REQUIRED);
        TransactionTemplate nested = transaction(jpaManager, TransactionDefinition.PROPAGATION_NESTED);
        boolean nestedAllowed = jpaManager.isNestedTransactionAllowed();
        required.executeWithoutResult(outer -> {
            check(SpringConsistencyGuard.snapshot(jpaConfig).entityManagerBound());
            checkBlocked(inspect(jpaConfig, intent(true, true, Propagation.NESTED, true)),
                    Code.NESTED_JPA_UNSUPPORTED);
            // The pinned HibernateJpaDialect does not supply a JPA SavepointManager.
            expect(NestedTransactionNotSupportedException.class, () ->
                    nested.executeWithoutResult(inner -> { throw new AssertionError(); }));
            check(!outer.isRollbackOnly());
        });
        check(jpaManager.isNestedTransactionAllowed() == nestedAllowed);
    }

    private void readOnlyWrite() {
        TransactionTemplate readOnly = transaction(jdbcManager, TransactionDefinition.PROPAGATION_REQUIRED);
        readOnly.setReadOnly(true);
        readOnly.executeWithoutResult(status -> {
            Snapshot snapshot = SpringConsistencyGuard.snapshot(jdbcConfig);
            check(snapshot.actualTransactionActive() && snapshot.readOnly());
            checkBlocked(inspect(jdbcConfig, intent(true, false, Propagation.REQUIRED, false)), Code.READ_ONLY_WRITE);
            check(!status.isRollbackOnly());
            check(SpringConsistencyGuard.snapshot(jdbcConfig).readOnly());
        });
        check(ids().isEmpty());
    }

    private void isolationParticipation() {
        TransactionTemplate outer = transaction(jdbcManager, TransactionDefinition.PROPAGATION_REQUIRED);
        outer.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
        TransactionTemplate inner = transaction(jdbcManager, TransactionDefinition.PROPAGATION_REQUIRED);
        inner.setIsolationLevel(TransactionDefinition.ISOLATION_SERIALIZABLE);
        Intent serializable = new Intent(true, false, false, Propagation.REQUIRED, true,
                Isolation.SERIALIZABLE, TIMEOUT_SECONDS, Outcome.NONE, false);

        check(!jdbcManager.isValidateExistingTransaction());
        outer.executeWithoutResult(outerStatus -> inner.executeWithoutResult(innerStatus -> {
            check(!innerStatus.isNewTransaction());
            check(SpringConsistencyGuard.snapshot(jdbcConfig).isolation() == Isolation.READ_COMMITTED);
            check(jdbc.execute((ConnectionCallback<Integer>) Connection::getTransactionIsolation)
                    == Connection.TRANSACTION_READ_COMMITTED);
            Report report = inspect(jdbcConfig, serializable);
            checkBlocked(report, Code.ISOLATION_MISMATCH);
            checkCode(report, Code.PARTICIPATING_TIMEOUT_NOT_APPLIED);
            check(!jdbcManager.isValidateExistingTransaction());
            check(!outerStatus.isRollbackOnly());
        }));

        DataSourceTransactionManager strict = jdbcManager(dataSource);
        strict.setValidateExistingTransaction(true);
        Configuration strictConfig = jdbcConfiguration(strict);
        TransactionTemplate strictOuter = transaction(strict, TransactionDefinition.PROPAGATION_REQUIRED);
        strictOuter.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
        TransactionTemplate strictInner = transaction(strict, TransactionDefinition.PROPAGATION_REQUIRED);
        strictInner.setIsolationLevel(TransactionDefinition.ISOLATION_SERIALIZABLE);
        strictOuter.executeWithoutResult(status -> {
            checkBlocked(inspect(strictConfig, serializable), Code.ISOLATION_MISMATCH);
            check(strict.isValidateExistingTransaction());
            expect(IllegalTransactionStateException.class, () ->
                    strictInner.executeWithoutResult(innerStatus -> { throw new AssertionError(); }));
            check(!status.isRollbackOnly());
        });
        check(strict.isValidateExistingTransaction());
    }

    private void timeoutBoundary() {
        TransactionTemplate shortTransaction = transaction(jdbcManager, TransactionDefinition.PROPAGATION_REQUIRED);
        shortTransaction.setTimeout(1);
        Intent timed = new Intent(true, true, false, Propagation.REQUIRED, false,
                Isolation.DEFAULT, 1, Outcome.NONE, false);
        expect(UnexpectedRollbackException.class, () -> shortTransaction.executeWithoutResult(status -> {
            ConnectionHolder holder = connectionHolder(dataSource);
            check(SpringConsistencyGuard.snapshot(jdbcConfig).timeout() == Timeout.ACTIVE);
            write(1);
            var deadline = holder.getDeadline();
            check(deadline != null);
            long remainingMillis = deadline.getTime() - System.currentTimeMillis();
            try {
                Thread.sleep(Math.min(1_100, Math.max(0, remainingMillis) + 75));
            } catch (InterruptedException failure) {
                Thread.currentThread().interrupt();
                throw new AssertionError();
            }
            check(!holder.isRollbackOnly() && !status.isRollbackOnly());
            Snapshot snapshot = SpringConsistencyGuard.snapshot(jdbcConfig);
            check(snapshot.timeout() == Timeout.EXPIRED);
            check(snapshot.rollback() == Rollback.CLEAR);
            checkBlocked(inspect(jdbcConfig, timed), Code.TIMEOUT_EXPIRED);
            check(!holder.isRollbackOnly() && !status.isRollbackOnly());
            check(deadline.equals(holder.getDeadline()));

            expect(TransactionTimedOutException.class, this::ids);
            check(holder.isRollbackOnly() && status.isRollbackOnly());
        }));
        check(ids().isEmpty());
    }

    private void missingAndForeignTransaction() {
        Intent requiresTransaction = intent(false, false, Propagation.REQUIRED, false);
        checkBlocked(inspect(jdbcConfig, requiresTransaction), Code.NO_ACTUAL_TRANSACTION);
        transaction(jdbcManager, TransactionDefinition.PROPAGATION_SUPPORTS).executeWithoutResult(status -> {
            Snapshot snapshot = SpringConsistencyGuard.snapshot(jdbcConfig);
            check(snapshot.synchronizationActive() && !snapshot.actualTransactionActive());
            Report report = inspect(jdbcConfig, intent(false, false, Propagation.SUPPORTS, false));
            checkBlocked(report, Code.NO_ACTUAL_TRANSACTION);
            checkCode(report, Code.SYNCHRONIZATION_WITHOUT_TRANSACTION);
        });

        transaction(foreignManager, TransactionDefinition.PROPAGATION_REQUIRED).executeWithoutResult(status -> {
            Snapshot before = SpringConsistencyGuard.snapshot(jdbcConfig);
            check(before.actualTransactionActive() && !before.resourceBound());
            check(TransactionSynchronizationManager.hasResource(foreignDataSource));
            checkBlocked(inspect(jdbcConfig, requiresTransaction), Code.RESOURCE_NOT_BOUND);
            check(ids().isEmpty());
            // JdbcTemplate can bind the primary handle for synchronization during a foreign transaction.
            Snapshot after = SpringConsistencyGuard.snapshot(jdbcConfig);
            check(after.actualTransactionActive() && after.resourceBound());
            check(connectionHolder(dataSource) != connectionHolder(foreignDataSource));
            check(connectionHolder(dataSource).getConnection() != connectionHolder(foreignDataSource).getConnection());
            checkCode(inspect(jdbcConfig, requiresTransaction), Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
            check(Code.TRANSACTION_OWNERSHIP_UNVERIFIED.severity() == Severity.WARNING);
        });
    }

    private void unknownOutcomeNoRetry() {
        Intent retry = new Intent(true, true, false, Propagation.REQUIRED, false,
                Isolation.DEFAULT, -1, Outcome.UNKNOWN, true);
        Snapshot otherwiseAllowed = new Snapshot(true, true, true, false, false,
                Isolation.READ_COMMITTED, Timeout.ACTIVE, Rollback.CLEAR);
        checkBlocked(TransactionGuard.assess(retry, otherwiseAllowed), Code.OUTCOME_UNKNOWN_NO_RETRY);
        Intent confirmedRollback = new Intent(true, true, false, Propagation.REQUIRED, false,
                Isolation.DEFAULT, -1, Outcome.CONFIRMED_ROLLBACK, true);
        check(!TransactionGuard.assess(confirmedRollback, otherwiseAllowed).hasErrors());
    }

    private static Intent intent(boolean write, boolean jpaAccess, Propagation propagation, boolean outerPresent) {
        return new Intent(true, write, jpaAccess, propagation, outerPresent, Isolation.DEFAULT, -1,
                Outcome.NONE, false);
    }

    private static Report inspect(Configuration config, Intent intent) {
        return SpringConsistencyGuard.inspectTransaction(config, intent);
    }

    private void checkCode(Report report, Code code) {
        check(report.codes().contains(code));
    }

    private void checkBlocked(Report report, Code code) {
        checkCode(report, code);
        check(report.hasErrors());
        expect(Violation.class, report::requireAllowed);
    }

    private void expect(Class<? extends RuntimeException> expected, Runnable action) {
        try {
            action.run();
        } catch (RuntimeException failure) {
            if (!expected.isInstance(failure)) {
                throw failure;
            }
            assertions++;
            return;
        }
        throw new AssertionError();
    }

    private ConnectionHolder connectionHolder(DataSource source) {
        Object resource = TransactionSynchronizationManager.getResource(source);
        check(resource instanceof ConnectionHolder);
        return (ConnectionHolder) resource;
    }

    private void checkThreadClean() {
        check(TransactionSynchronizationManager.getResourceMap().isEmpty());
        check(!TransactionSynchronizationManager.isActualTransactionActive());
        check(!TransactionSynchronizationManager.isSynchronizationActive());
        check(!TransactionSynchronizationManager.isCurrentTransactionReadOnly());
        check(TransactionSynchronizationManager.getCurrentTransactionIsolationLevel() == null);
        check(TransactionSynchronizationManager.getCurrentTransactionName() == null);
    }

    private void write(int id) {
        check(jdbc.update(INSERT, id, id) == 1);
    }

    private List<Integer> ids() {
        return jdbc.queryForList(SELECT_IDS, Integer.class);
    }

    private void check(boolean condition) {
        if (!condition) {
            throw new AssertionError();
        }
        assertions++;
    }

    private Configuration jdbcConfiguration(PlatformTransactionManager manager) {
        return new Configuration(dataSource, List.of(dataSource), List.of(manager), null, null, jdbc);
    }

    private SqlSessionTemplate myBatis(TransactionFactory transactionFactory) {
        Environment environment = new Environment("phase4", transactionFactory, dataSource);
        var configuration = new org.apache.ibatis.session.Configuration(environment);
        configuration.setDefaultStatementTimeout(TIMEOUT_SECONDS);
        return new SqlSessionTemplate(new SqlSessionFactoryBuilder().build(configuration));
    }

    private static JdbcDataSource dataSource() {
        JdbcDataSource source = new JdbcDataSource();
        source.setURL("jdbc:h2:mem:udak_phase4");
        return source;
    }

    private static DataSourceTransactionManager jdbcManager(DataSource source) {
        DataSourceTransactionManager manager = new DataSourceTransactionManager(source);
        manager.setDefaultTimeout(TIMEOUT_SECONDS);
        return manager;
    }

    private static JdbcTemplate jdbc(DataSource source) {
        JdbcTemplate template = new JdbcTemplate(source);
        template.setQueryTimeout(TIMEOUT_SECONDS);
        return template;
    }

    private static TransactionTemplate transaction(PlatformTransactionManager manager, int propagation) {
        TransactionTemplate template = new TransactionTemplate(manager);
        template.setPropagationBehavior(propagation);
        template.setTimeout(TIMEOUT_SECONDS);
        return template;
    }

    private static void suppressRuntimeOutput() {
        PrintStream sink = new PrintStream(OutputStream.nullOutputStream());
        System.setOut(sink);
        System.setErr(sink);
        LogManager.getLogManager().reset();
        Logger.getLogger("").setLevel(Level.OFF);
        System.setProperty("org.jboss.logging.provider", "jdk");
        System.setProperty("slf4j.provider", "org.slf4j.nop.NOPServiceProvider");
        LogFactory.useNoLogging();
    }

    private static void printDiagnostic(PrintStream protocol, Throwable failure) {
        protocol.println("DIAGNOSTIC=" + failure.getClass().getName());
        for (StackTraceElement frame : failure.getStackTrace()) {
            if (frame.getClassName().startsWith("dev.udak.") && frame.getLineNumber() > 0
                    && !"check".equals(frame.getMethodName()) && !"expect".equals(frame.getMethodName())) {
                protocol.println("DIAGNOSTIC=" + frame.getClassName() + "." + frame.getMethodName()
                        + ":" + frame.getLineNumber());
                break;
            }
        }
    }

    private final class JpaFactory implements AutoCloseable {
        private final LocalContainerEntityManagerFactoryBean factory = new LocalContainerEntityManagerFactoryBean();

        private JpaFactory(DataSource source) {
            factory.setDataSource(source);
            factory.setJpaVendorAdapter(new HibernateJpaVendorAdapter());
            factory.setManagedTypes(PersistenceManagedTypes.of(UserEntity.class.getName()));
            factory.getJpaPropertyMap().put("hibernate.hbm2ddl.auto", "none");
            factory.getJpaPropertyMap().put(SpecHints.HINT_SPEC_QUERY_TIMEOUT, TIMEOUT_SECONDS * 1_000);
        }

        private void start() {
            factory.afterPropertiesSet();
        }

        private EntityManagerFactory get() {
            return factory.getObject();
        }

        @Override
        public void close() {
            EntityManagerFactory entityManagerFactory = get();
            factory.destroy();
            if (entityManagerFactory != null) {
                check(!entityManagerFactory.isOpen());
            }
        }
    }
}
