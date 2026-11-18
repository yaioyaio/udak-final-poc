package dev.udak.trace.spring;

import dev.udak.compat.LegacyCompatibilityTest;
import dev.udak.observe.Framework;
import dev.udak.observe.ObservationPoint;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.StatementKind;
import dev.udak.observe.hibernate.HibernateObserveInspector;
import dev.udak.observe.jdbc.ObserveDataSource;
import dev.udak.observe.mybatis.MyBatisObserveInterceptor;
import dev.udak.trace.spring.SpringTransactionTrace.Association;
import dev.udak.trace.spring.SpringTransactionTrace.Event;
import dev.udak.trace.spring.SpringTransactionTrace.Kind;
import dev.udak.trace.spring.SpringTransactionTrace.Outcome;
import dev.udak.trace.spring.SpringTransactionTrace.Report;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.io.PrintStream;
import java.sql.SQLException;
import java.util.List;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import javax.sql.DataSource;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;
import org.apache.ibatis.session.Configuration;
import org.apache.ibatis.session.LocalCacheScope;
import org.h2.jdbcx.JdbcDataSource;
import org.hibernate.Session;
import org.hibernate.jpa.SpecHints;
import org.mybatis.spring.SqlSessionFactoryBean;
import org.mybatis.spring.SqlSessionTemplate;
import org.mybatis.spring.transaction.SpringManagedTransactionFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceUtils;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.orm.jpa.JpaTransactionManager;
import org.springframework.orm.jpa.LocalContainerEntityManagerFactoryBean;
import org.springframework.orm.jpa.SharedEntityManagerCreator;
import org.springframework.orm.jpa.persistenceunit.PersistenceManagedTypes;
import org.springframework.orm.jpa.vendor.HibernateJpaVendorAdapter;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionSystemException;
import org.springframework.transaction.UnexpectedRollbackException;
import org.springframework.transaction.support.DefaultTransactionStatus;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Exercises transaction trace metadata and business outcomes with fixed, in-memory H2 fixtures. */
public final class TransactionTraceIntegrationTest {
    private static final int TIMEOUT_SECONDS = 5;
    private static final String CREATE_TABLE =
            "CREATE TABLE tx_trace_entry (id BIGINT PRIMARY KEY, val VARCHAR(120) NOT NULL)";
    private static final String INSERT = "INSERT INTO tx_trace_entry (id, val) VALUES (?, ?)";
    private static final String SELECT_VALUE = "SELECT val FROM tx_trace_entry WHERE id = ?";
    private static final String SELECT_IDS = "SELECT id FROM tx_trace_entry WHERE id BETWEEN ? AND ? ORDER BY id";
    private static final String MIXED_MARKER = "TxTraceMixedValue";
    private static final String BOUND_MARKER = "TxTraceBoundValue";
    private static final String LITERAL_MARKER = "TxTraceLiteralValue";
    private static final String LABEL_MARKER = "TxTraceTransactionLabel";
    private static final Pattern DIGEST = Pattern.compile("[0-9a-f]{64}");

    private enum Scenario {
        MIXED_COMMIT, REQUIRED_ROLLBACK, REQUIRES_NEW, SAVEPOINT, CONTEXT_ISOLATION, COMPLETION_REENTRY, UNKNOWN_OUTCOME, REDACTION_AND_LIMIT
    }

    private final JdbcDataSource raw = dataSource("jdbc:h2:mem:udak_tx_trace_fixture");
    private final JdbcTemplate readback = jdbc(raw);
    private String stage = "BOOTSTRAP";
    private int assertions;
    private String mixedTimeline;

    private TransactionTraceIntegrationTest() { }

    public static void main(String[] args) {
        PrintStream protocol = LegacyCompatibilityTest.suppressRuntimeOutput();
        TransactionTraceIntegrationTest test = null;
        try {
            if (args.length != 0) throw new IllegalArgumentException();
            test = new TransactionTraceIntegrationTest();
            test.run();
            protocol.println("TX_TRACE PASS");
            protocol.println("ASSERTIONS=" + test.assertions);
            for (Scenario scenario : Scenario.values()) {
                protocol.println("SCENARIO=" + scenario.name() + ":PASS");
            }
            protocol.println("TIMELINE=" + test.mixedTimeline);
        } catch (Exception | AssertionError | LinkageError failure) {
            protocol.println("TX_TRACE FAIL: " + (test == null ? "BOOTSTRAP" : test.stage));
            printDiagnostic(protocol, failure);
            System.exit(1);
        }
    }

    private void run() throws Exception {
        checkThreadClean();
        try (var anchor = raw.getConnection()) {
            readback.execute(CREATE_TABLE);
            run(Scenario.MIXED_COMMIT, this::mixedCommit);
            run(Scenario.REQUIRED_ROLLBACK, this::requiredRollback);
            run(Scenario.REQUIRES_NEW, this::requiresNew);
            run(Scenario.SAVEPOINT, this::savepoint);
            run(Scenario.CONTEXT_ISOLATION, this::contextIsolation);
            run(Scenario.COMPLETION_REENTRY, this::completionReentry);
            run(Scenario.UNKNOWN_OUTCOME, this::unknownOutcome);
            run(Scenario.REDACTION_AND_LIMIT, this::redactionAndLimit);
            stage = "CLEANUP";
        }
    }

    private void run(Scenario scenario, ScenarioAction action) throws Exception {
        stage = scenario.name();
        action.run();
        checkThreadClean();
    }

    private void mixedCommit() throws Exception {
        var observed = new ObservedDataSource(raw);
        var factory = new LocalContainerEntityManagerFactoryBean();
        try {
            factory.setDataSource(observed.source);
            factory.setJpaVendorAdapter(new HibernateJpaVendorAdapter());
            factory.setManagedTypes(PersistenceManagedTypes.of(TraceEntry.class.getName()));
            factory.getJpaPropertyMap().put("hibernate.hbm2ddl.auto", "none");
            factory.getJpaPropertyMap().put(SpecHints.HINT_SPEC_QUERY_TIMEOUT, TIMEOUT_SECONDS * 1_000);
            factory.getJpaPropertyMap().put("hibernate.session_factory.statement_inspector",
                    new HibernateObserveInspector(observed.observer));
            factory.afterPropertiesSet();

            var entityFactory = factory.getObject();
            var trace = new SpringTransactionTrace(observed.source, entityFactory);
            observed.trace = trace;
            var manager = new JpaTransactionManager(entityFactory);
            manager.setDataSource(observed.source);
            manager.afterPropertiesSet();
            trace.registerWith(manager);
            var entityManager = SharedEntityManagerCreator.createSharedEntityManager(entityFactory);
            var sqlSession = myBatis(observed);
            var mapper = sqlSession.getMapper(TraceMapper.class);

            transaction(manager, TransactionDefinition.PROPAGATION_REQUIRED).executeWithoutResult(status -> {
                entityManager.unwrap(Session.class).doWork(hibernateConnection -> {
                    var jdbcConnection = DataSourceUtils.getConnection(observed.source);
                    try {
                        require(jdbcConnection == hibernateConnection);
                    } finally {
                        DataSourceUtils.releaseConnection(jdbcConnection, observed.source);
                    }
                });
                entityManager.persist(new TraceEntry(10, MIXED_MARKER));
                require(mapper.findValue(10) == null);
                entityManager.flush();
                trace.markFlushCompleted();
                require(MIXED_MARKER.equals(mapper.findValue(10)));
                require(mapper.updateValue(10, BOUND_MARKER) == 1);
                require(BOUND_MARKER.equals(observed.jdbc.queryForObject(SELECT_VALUE, String.class, 10L)));
                write(observed.jdbc, 11);
            });

            require(ids(10, 11).equals(List.of(10L, 11L)));
            require(BOUND_MARKER.equals(readback.queryForObject(SELECT_VALUE, String.class, 10L)));
            List<Event> events = completeEvents(trace);
            List<Event> sql = sqlEvents(events);
            require(kinds(events).equals(List.of(Kind.ATTACHED, Kind.SQL, Kind.SQL, Kind.SQL, Kind.SQL,
                    Kind.FLUSH_COMPLETED, Kind.SQL, Kind.SQL, Kind.SQL, Kind.SQL, Kind.SQL, Kind.SQL,
                    Kind.BEFORE_COMMIT, Kind.BEFORE_COMPLETION, Kind.COMPLETED)));
            require(sql.stream().map(event -> event.observation().framework()).toList().equals(List.of(
                    Framework.MYBATIS, Framework.JDBC, Framework.JPA, Framework.JDBC, Framework.MYBATIS,
                    Framework.JDBC, Framework.MYBATIS, Framework.JDBC, Framework.JDBC, Framework.JDBC)));
            require(sql.stream().map(event -> event.observation().statementKind()).toList().equals(List.of(
                    StatementKind.SELECT, StatementKind.SELECT, StatementKind.INSERT, StatementKind.INSERT,
                    StatementKind.SELECT, StatementKind.SELECT, StatementKind.UPDATE, StatementKind.UPDATE,
                    StatementKind.SELECT, StatementKind.INSERT)));
            sameTransaction(events, events.get(0).transactionId());
            require(events.stream().allMatch(event -> event.managerKind() == SpringTransactionTrace.ManagerKind.JPA));
            require(events.get(events.size() - 1).outcome() == Outcome.COMMITTED);
            require(!trace.snapshot().toString().contains("findValue"));
            require(!trace.snapshot().toString().contains(MIXED_MARKER));
            mixedTimeline = events.stream().map(TransactionTraceIntegrationTest::timelineEntry)
                    .collect(Collectors.joining(","));
        } finally {
            factory.destroy();
        }
    }

    private void requiredRollback() {
        var observed = observedJdbc(256);
        var manager = tracedJdbcManager(observed);
        var required = transaction(manager, TransactionDefinition.PROPAGATION_REQUIRED);
        expect(UnexpectedRollbackException.class, () -> required.executeWithoutResult(outer -> {
            write(observed.jdbc, 20);
            required.executeWithoutResult(inner -> {
                observed.trace.checkpoint();
                write(observed.jdbc, 21);
                inner.setRollbackOnly();
            });
            require(outer.isRollbackOnly());
        }));
        require(ids(20, 21).isEmpty());
        List<Event> events = completeEvents(observed.trace);
        require(kinds(events).equals(List.of(Kind.ATTACHED, Kind.SQL, Kind.CHECKPOINT_REUSED, Kind.SQL,
                Kind.BEFORE_COMPLETION, Kind.COMPLETED)));
        sameTransaction(events, events.get(0).transactionId());
        require(events.get(events.size() - 1).outcome() == Outcome.ROLLED_BACK);
    }

    private void requiresNew() {
        var observed = observedJdbc(256);
        var manager = tracedJdbcManager(observed);
        var inner = transaction(manager, TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        transaction(manager, TransactionDefinition.PROPAGATION_REQUIRED).executeWithoutResult(outer -> {
            write(observed.jdbc, 30);
            inner.executeWithoutResult(status -> {
                write(observed.jdbc, 31);
            });
            require(BOUND_MARKER.equals(observed.jdbc.queryForObject(SELECT_VALUE, String.class, 31L)));
            outer.setRollbackOnly();
        });
        require(ids(30, 31).equals(List.of(31L)));
        List<Event> events = completeEvents(observed.trace);
        require(kinds(events).equals(List.of(Kind.ATTACHED, Kind.SQL, Kind.SUSPENDED, Kind.ATTACHED, Kind.SQL,
                Kind.BEFORE_COMMIT, Kind.BEFORE_COMPLETION, Kind.COMPLETED, Kind.RESUMED, Kind.SQL,
                Kind.BEFORE_COMPLETION, Kind.COMPLETED)));
        long outerId = events.get(0).transactionId();
        long innerId = events.get(3).transactionId();
        require(outerId != innerId);
        sameTransaction(events.subList(0, 3), outerId);
        sameTransaction(events.subList(3, 8), innerId);
        sameTransaction(events.subList(8, 12), outerId);
        require(events.get(7).outcome() == Outcome.COMMITTED);
        require(events.get(11).outcome() == Outcome.ROLLED_BACK);
    }

    private void savepoint() {
        var observed = observedJdbc(256);
        var manager = tracedJdbcManager(observed);
        var nested = transaction(manager, TransactionDefinition.PROPAGATION_NESTED);
        transaction(manager, TransactionDefinition.PROPAGATION_REQUIRED).executeWithoutResult(outer -> {
            write(observed.jdbc, 40);
            nested.executeWithoutResult(status -> {
                require(status.hasSavepoint());
                write(observed.jdbc, 41);
                status.setRollbackOnly();
            });
            require(!outer.isRollbackOnly());
            write(observed.jdbc, 42);
        });
        require(ids(40, 42).equals(List.of(40L, 42L)));
        List<Event> events = completeEvents(observed.trace);
        require(kinds(events).equals(List.of(Kind.ATTACHED, Kind.SQL, Kind.SAVEPOINT_CREATED, Kind.SQL,
                Kind.SAVEPOINT_ROLLBACK_REQUESTED, Kind.SQL, Kind.BEFORE_COMMIT, Kind.BEFORE_COMPLETION, Kind.COMPLETED)));
        sameTransaction(events, events.get(0).transactionId());
        require(events.get(events.size() - 1).outcome() == Outcome.COMMITTED);
    }

    private void contextIsolation() throws Exception {
        var observed = observedJdbc(256);
        var required = transaction(new DataSourceTransactionManager(observed.source),
                TransactionDefinition.PROPAGATION_REQUIRED);
        observed.trace.checkpoint();
        require(observed.jdbc.queryForObject("SELECT 1", Integer.class) == 1);
        required.executeWithoutResult(status -> {
            observed.trace.checkpoint();
            require(observed.jdbc.queryForObject("SELECT 1", Integer.class) == 1);
        });

        var foreign = dataSource("jdbc:h2:mem:udak_tx_trace_foreign");
        var foreignManager = new DataSourceTransactionManager(foreign);
        expect(IllegalArgumentException.class, () -> observed.trace.registerWith(foreignManager));
        transaction(foreignManager, TransactionDefinition.PROPAGATION_REQUIRED)
                .executeWithoutResult(status -> {
                    require(TransactionSynchronizationManager.hasResource(foreign));
                    require(!TransactionSynchronizationManager.hasResource(observed.source));
                    observed.trace.checkpoint();
                    // This independently obtained connection does not bind a local Spring resource.
                    try (var connection = observed.source.getConnection(); var statement = connection.createStatement()) {
                        statement.setQueryTimeout(TIMEOUT_SECONDS);
                        try (var rows = statement.executeQuery("SELECT 1")) {
                            require(rows.next() && rows.getInt(1) == 1);
                        }
                    } catch (SQLException failure) {
                        throw new IllegalStateException(failure);
                    }
                    // JdbcTemplate binds a second, synchronization-only holder under the foreign transaction.
                    require(observed.jdbc.queryForObject("SELECT 1", Integer.class) == 1);
                    require(TransactionSynchronizationManager.hasResource(observed.source));
                    observed.trace.checkpoint();
                });

        var traced = tracedJdbcManager(observed);
        int configuredListeners = traced.getTransactionExecutionListeners().size();
        observed.trace.registerWith(traced);
        require(traced.getTransactionExecutionListeners().size() == configuredListeners);
        int[] orderCalls = {0};
        transaction(traced, TransactionDefinition.PROPAGATION_REQUIRED).executeWithoutResult(status -> {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public int getOrder() {
                    orderCalls[0]++;
                    return 0;
                }
            });
            observed.trace.markFlushCompleted();
            require(observed.jdbc.queryForObject("SELECT 1", Integer.class) == 1);
            var read = new FutureTask<>(() -> observed.jdbc.queryForObject("SELECT 1", Integer.class));
            var worker = new Thread(read, "tx-trace-fixture-reader");
            worker.setDaemon(true);
            worker.start();
            try {
                require(read.get(TIMEOUT_SECONDS, TimeUnit.SECONDS) == 1);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException(interrupted);
            } catch (Exception failure) {
                throw new IllegalStateException(failure);
            } finally {
                read.cancel(true);
            }
            require(orderCalls[0] == 0);
        });
        require(orderCalls[0] > 0); // Spring, not SQL tracing, sorts callbacks at completion.
        List<Event> events = completeEvents(observed.trace);
        require(kinds(events).equals(List.of(Kind.SQL, Kind.SQL, Kind.SQL, Kind.SQL, Kind.ATTACHED, Kind.SQL, Kind.SQL,
                Kind.BEFORE_COMMIT, Kind.BEFORE_COMPLETION, Kind.COMPLETED)));
        List<Event> sql = sqlEvents(events);
        require(sql.stream().map(Event::association).toList().equals(List.of(Association.NO_TRANSACTION,
                Association.UNTRACKED_TRANSACTION, Association.UNMATCHED_RESOURCE, Association.UNMATCHED_RESOURCE,
                Association.BOUND_CONTEXT,
                Association.NO_TRANSACTION)));
        require(sql.stream().filter(event -> event.association() != Association.BOUND_CONTEXT)
                .allMatch(event -> event.transactionId() == 0));
        require(sql.get(4).transactionId() == events.get(4).transactionId() && sql.get(4).transactionId() > 0);
        require(sql.get(4).managerKind() == SpringTransactionTrace.ManagerKind.JDBC);
        require(sql.stream().filter(event -> event.association() != Association.BOUND_CONTEXT)
                .allMatch(event -> event.managerKind() == SpringTransactionTrace.ManagerKind.NONE));
    }

    private void completionReentry() {
        var observed = observedJdbc(256);
        var required = transaction(tracedJdbcManager(observed), TransactionDefinition.PROPAGATION_REQUIRED);
        int[] callbackResult = {0};
        required.executeWithoutResult(status -> {
            write(observed.jdbc, 52);
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public int getOrder() {
                    return 0;
                }

                @Override
                public void afterCompletion(int completion) {
                    if (completion != STATUS_COMMITTED) return;
                    // Spring may still expose the completed transaction's holder to a REQUIRED call.
                    required.executeWithoutResult(inner -> {
                        observed.trace.checkpoint();
                        callbackResult[0] = observed.jdbc.queryForObject("SELECT 1", Integer.class);
                    });
                }
            });
        });
        require(callbackResult[0] == 1);
        require(ids(52, 52).equals(List.of(52L)));
        List<Event> events = completeEvents(observed.trace);
        require(kinds(events).equals(List.of(Kind.ATTACHED, Kind.SQL, Kind.BEFORE_COMMIT,
                Kind.BEFORE_COMPLETION, Kind.SQL, Kind.COMPLETED)));
        Event fromCallback = events.get(4);
        require(fromCallback.association() == Association.UNTRACKED_TRANSACTION);
        require(fromCallback.transactionId() == 0 && fromCallback.managerKind() == SpringTransactionTrace.ManagerKind.NONE);
        require(events.get(5).outcome() == Outcome.COMMITTED);
    }

    private void unknownOutcome() {
        var observed = observedJdbc(256);
        var manager = new UncertainCommitManager(observed.source);
        observed.trace.registerWith(manager);
        var required = transaction(manager, TransactionDefinition.PROPAGATION_REQUIRED);
        expect(TransactionSystemException.class, () -> required.executeWithoutResult(status -> {
            write(observed.jdbc, 50);
        }));
        require(manager.commitAttempts == 1);
        require(ids(50, 50).equals(List.of(50L)));
        List<Event> events = completeEvents(observed.trace);
        require(kinds(events).equals(List.of(Kind.ATTACHED, Kind.SQL, Kind.BEFORE_COMMIT, Kind.BEFORE_COMPLETION,
                Kind.COMPLETED)));
        sameTransaction(events, events.get(0).transactionId());
        require(events.get(events.size() - 1).outcome() == Outcome.UNKNOWN);
    }

    private void redactionAndLimit() {
        var observed = observedJdbc(3);
        var required = transaction(tracedJdbcManager(observed), TransactionDefinition.PROPAGATION_REQUIRED);
        required.setName(LABEL_MARKER);
        required.executeWithoutResult(status -> {
            require(LITERAL_MARKER.equals(observed.jdbc.queryForObject(
                    "SELECT '" + LITERAL_MARKER + "' AS marker", String.class)));
            write(observed.jdbc, 60);
            write(observed.jdbc, 61);
        });
        require(ids(60, 61).equals(List.of(60L, 61L)));
        Report report = observed.trace.snapshot();
        require(report.dropped() == 4);
        require(kinds(report.events()).equals(List.of(Kind.ATTACHED, Kind.SQL, Kind.SQL)));
        expect(UnsupportedOperationException.class, report.events()::clear);
        String metadata = report.toString();
        require(!metadata.contains(LITERAL_MARKER) && !metadata.contains(BOUND_MARKER) && !metadata.contains(LABEL_MARKER));
        require(!metadata.contains("tx_trace_entry") && !metadata.contains("jdbc:h2:") && !metadata.contains(INSERT));
        require(sqlEvents(report.events()).stream().allMatch(event ->
                DIGEST.matcher(event.observation().queryIdHash()).matches()
                        && DIGEST.matcher(event.observation().fingerprintHash()).matches()));
        require(report.events().get(1).observation().point() == ObservationPoint.JDBC_EXECUTE);
    }

    private ObservedDataSource observedJdbc(int capacity) {
        var observed = new ObservedDataSource(raw);
        observed.trace = new SpringTransactionTrace(observed.source, null, capacity);
        return observed;
    }

    private static DataSourceTransactionManager tracedJdbcManager(ObservedDataSource observed) {
        var manager = new DataSourceTransactionManager(observed.source);
        observed.trace.registerWith(manager);
        return manager;
    }

    private static SqlSessionTemplate myBatis(ObservedDataSource observed) throws Exception {
        var configuration = new Configuration();
        configuration.setDefaultStatementTimeout(TIMEOUT_SECONDS);
        configuration.setLocalCacheScope(LocalCacheScope.STATEMENT);
        configuration.addMapper(TraceMapper.class);
        configuration.addInterceptor(new MyBatisObserveInterceptor(observed.observer));
        var factory = new SqlSessionFactoryBean();
        factory.setDataSource(observed.source);
        factory.setConfiguration(configuration);
        factory.setTransactionFactory(new SpringManagedTransactionFactory());
        return new SqlSessionTemplate(factory.getObject());
    }

    private static TransactionTemplate transaction(PlatformTransactionManager manager, int propagation) {
        var template = new TransactionTemplate(manager);
        template.setPropagationBehavior(propagation);
        template.setTimeout(TIMEOUT_SECONDS);
        return template;
    }

    private static JdbcDataSource dataSource(String url) {
        var source = new JdbcDataSource();
        source.setURL(url);
        return source;
    }

    private static JdbcTemplate jdbc(DataSource source) {
        var template = new JdbcTemplate(source);
        template.setQueryTimeout(TIMEOUT_SECONDS);
        return template;
    }

    private List<Long> ids(long start, long end) {
        return readback.queryForList(SELECT_IDS, Long.class, start, end);
    }

    private void write(JdbcTemplate jdbc, long id) {
        require(jdbc.update(INSERT, id, BOUND_MARKER) == 1);
    }

    private List<Event> completeEvents(SpringTransactionTrace trace) {
        Report report = trace.snapshot();
        require(report.dropped() == 0);
        List<Event> events = report.events();
        for (int index = 0; index < events.size(); index++) {
            Event event = events.get(index);
            require(event.sequence() == index + 1L);
            require((event.kind() == Kind.SQL) == (event.observation() != null));
            require((event.kind() == Kind.COMPLETED) == (event.outcome() != Outcome.NONE));
        }
        return events;
    }

    private void sameTransaction(List<Event> events, long id) {
        require(id > 0);
        require(events.stream().allMatch(event -> event.transactionId() == id
                && event.association() == Association.BOUND_CONTEXT));
    }

    private static List<Kind> kinds(List<Event> events) {
        return events.stream().map(Event::kind).toList();
    }

    private static List<Event> sqlEvents(List<Event> events) {
        return events.stream().filter(event -> event.kind() == Kind.SQL).toList();
    }

    private static String timelineEntry(Event event) {
        return switch (event.kind()) {
            case SQL -> "SQL/" + event.observation().framework().name() + "/1";
            case COMPLETED -> "COMPLETED/" + event.outcome().name() + "/1";
            default -> event.kind().name() + "/1";
        };
    }

    private void checkThreadClean() {
        require(TransactionSynchronizationManager.getResourceMap().isEmpty());
        require(!TransactionSynchronizationManager.isActualTransactionActive());
        require(!TransactionSynchronizationManager.isSynchronizationActive());
    }

    private void expect(Class<? extends RuntimeException> expected, Runnable action) {
        try {
            action.run();
        } catch (RuntimeException failure) {
            if (!expected.isInstance(failure)) throw failure;
            assertions++;
            return;
        }
        throw new AssertionError();
    }

    private void require(boolean condition) {
        assertions++;
        if (!condition) throw new AssertionError();
    }

    private static void printDiagnostic(PrintStream output, Throwable failure) {
        Throwable cause = failure;
        for (int depth = 0; cause != null && depth < 6; depth++, cause = cause.getCause()) {
            output.println("DIAGNOSTIC=" + cause.getClass().getName());
            for (StackTraceElement frame : cause.getStackTrace()) {
                if (frame.getClassName().startsWith("dev.udak.trace.") && frame.getLineNumber() > 0
                        && !frame.getMethodName().equals("require")) {
                    output.println("DIAGNOSTIC=" + frame.getClassName() + "." + frame.getMethodName() + ":" + frame.getLineNumber());
                    break;
                }
            }
        }
    }

    @FunctionalInterface
    private interface ScenarioAction {
        void run() throws Exception;
    }

    @Entity
    @Table(name = "tx_trace_entry")
    public static class TraceEntry {
        @Id
        private long id;
        private String val;

        protected TraceEntry() { }

        TraceEntry(long id, String val) {
            this.id = id;
            this.val = val;
        }
    }

    public interface TraceMapper {
        @Select("SELECT val FROM tx_trace_entry WHERE id = #{id}")
        String findValue(long id);

        @Update("UPDATE tx_trace_entry SET val = #{value} WHERE id = #{id}")
        int updateValue(@Param("id") long id, @Param("value") String value);
    }

    private static final class ObservedDataSource {
        private volatile SpringTransactionTrace trace;
        private final SqlObserver observer = new SqlObserver(observation -> {
            if (trace != null) trace.accept(observation);
        });
        private final DataSource source;
        private final JdbcTemplate jdbc;

        private ObservedDataSource(DataSource source) {
            this.source = new ObserveDataSource(source, observer);
            jdbc = jdbc(this.source);
        }
    }

    private static final class UncertainCommitManager extends DataSourceTransactionManager {
        private static final long serialVersionUID = 1L;
        private int commitAttempts;

        private UncertainCommitManager(DataSource dataSource) {
            super(dataSource);
        }

        @Override
        protected void doCommit(DefaultTransactionStatus status) {
            commitAttempts++;
            super.doCommit(status);
            // Simulate a commit acknowledgement failure after H2 has committed the write.
            throw new TransactionSystemException("Controlled commit acknowledgement failure");
        }
    }
}
