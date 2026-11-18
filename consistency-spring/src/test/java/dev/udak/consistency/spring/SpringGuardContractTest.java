package dev.udak.consistency.spring;

import dev.udak.consistency.TransactionGuard.Code;
import dev.udak.consistency.TransactionGuard.Intent;
import dev.udak.consistency.TransactionGuard.Isolation;
import dev.udak.consistency.TransactionGuard.Outcome;
import dev.udak.consistency.TransactionGuard.Propagation;
import dev.udak.consistency.TransactionGuard.Report;
import dev.udak.consistency.TransactionGuard.Rollback;
import dev.udak.consistency.TransactionGuard.Snapshot;
import dev.udak.consistency.TransactionGuard.Timeout;
import dev.udak.consistency.spring.SpringConsistencyGuard.Configuration;
import dev.udak.consistency.spring.SpringConsistencyGuard.InspectionException;
import jakarta.persistence.EntityManagerFactory;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.ExecutorType;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.session.defaults.DefaultSqlSessionFactory;
import org.apache.ibatis.transaction.TransactionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.mybatis.spring.SqlSessionTemplate;
import org.mybatis.spring.transaction.SpringManagedTransactionFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.ConnectionHandle;
import org.springframework.jdbc.datasource.ConnectionHolder;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.support.JdbcTransactionManager;
import org.springframework.orm.jpa.EntityManagerFactoryInfo;
import org.springframework.orm.jpa.EntityManagerHolder;
import org.springframework.orm.jpa.JpaTransactionManager;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import javax.sql.DataSource;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.util.AbstractList;
import java.util.ArrayList;
import java.util.List;

import static dev.udak.consistency.spring.SpringConsistencyGuard.inspectConfiguration;
import static dev.udak.consistency.spring.SpringConsistencyGuard.inspectTransaction;
import static dev.udak.consistency.spring.SpringConsistencyGuard.snapshot;

public final class SpringGuardContractTest {
    private static final String SYNTHETIC_DETAIL = "synthetic-inspection-detail";
    private static int assertions;
    private static int nextHash;

    private SpringGuardContractTest() {
    }

    public static void main(String[] args) {
        jdbcConfiguration();
        jpaConfiguration();
        myBatisConfiguration();
        threadState();
        inspectionFailures();
        System.out.println("Spring Guard assertions: " + assertions);
    }

    private static void jdbcConfiguration() {
        DataSource primary = probe(DataSource.class).reference;
        DataSource other = probe(DataSource.class).reference;
        var manager = new JdbcTransactionManager(primary);
        JdbcTemplate jdbc = new JdbcTemplate(primary);
        expect(inspectConfiguration(null), Code.CONFIGURATION_MISSING);
        expect(inspectConfiguration(new Configuration(null, List.of(), List.of(), null, null, null)),
                Code.CONFIGURATION_MISSING);
        expect(inspectConfiguration(configuration(primary, manager, null, null, jdbc)),
                Code.EXISTING_TRANSACTION_VALIDATION_DISABLED);
        expect(inspectTransaction(configuration(primary, manager, null, null, jdbc),
                        new Intent(true, false, false, Propagation.REQUIRED, false,
                                Isolation.DEFAULT, -1, Outcome.NONE, false)),
                Code.EXISTING_TRANSACTION_VALIDATION_DISABLED, Code.NO_ACTUAL_TRANSACTION, Code.RESOURCE_NOT_BOUND);
        check(!manager.isValidateExistingTransaction(), "Validation setting changed");
        manager.setValidateExistingTransaction(true);

        var dataSources = new ArrayList<>(List.of(primary, primary));
        var managers = new ArrayList<PlatformTransactionManager>(List.of(manager, manager));
        var config = new Configuration(primary, dataSources, managers, null, null, jdbc);
        var same = new Configuration(primary, dataSources, managers, null, null, jdbc);
        dataSources.clear();
        managers.clear();
        expect(inspectConfiguration(config));
        check(config.equals(same) && config.hashCode() == same.hashCode(), "Configuration identity comparison");
        check(config.toString().equals("SpringConsistencyGuard.Configuration"), "Configuration representation");
        check(config.dataSources().size() == 2 && config.transactionManagers().size() == 2,
                "Configuration lists were not copied");

        expect(inspectConfiguration(new Configuration(primary, List.of(), List.of(manager), null, null, null)),
                Code.CONFIGURATION_MISSING);
        expect(inspectConfiguration(new Configuration(primary, List.of(primary, other), List.of(manager),
                null, null, null)), Code.MULTIPLE_DATA_SOURCES);
        expect(inspectConfiguration(new Configuration(primary, List.of(other), List.of(manager), null, null, null)),
                Code.RESOURCE_MISMATCH);
        expect(inspectConfiguration(new Configuration(primary, List.of(primary), List.of(), null, null, null)),
                Code.MISSING_TRANSACTION_MANAGER);
        expect(inspectConfiguration(new Configuration(primary, List.of(primary), List.of(manager, manager(other)),
                null, null, null)), Code.MULTIPLE_TRANSACTION_MANAGERS);
        expect(inspectConfiguration(configuration(primary, probe(PlatformTransactionManager.class).reference,
                null, null, null)), Code.UNSUPPORTED_TRANSACTION_MANAGER);
        expect(inspectConfiguration(configuration(primary, manager(other), null, null, null)), Code.RESOURCE_MISMATCH);
        expect(inspectConfiguration(configuration(primary, manager, null, null, new JdbcTemplate(other))),
                Code.RESOURCE_MISMATCH);
    }

    private static void jpaConfiguration() {
        DataSource primary = probe(DataSource.class).reference;
        DataSource other = probe(DataSource.class).reference;
        EntityManagerFactory emf = entityManagerFactory(primary).reference;
        JpaTransactionManager manager = jpaManager(primary, emf);
        expect(inspectConfiguration(configuration(primary, manager, emf, null, null)));
        expect(inspectConfiguration(configuration(primary, manager, emf, null, new JdbcTemplate(primary))),
                Code.MIXED_ACCESS_REQUIRES_EXPLICIT_FLUSH, Code.MIXED_ACCESS_REQUIRES_CACHE_REFRESH);
        expect(inspectConfiguration(configuration(primary, manager(primary), emf, null, null)),
                Code.JPA_REQUIRES_JPA_MANAGER);
        expect(inspectConfiguration(configuration(primary, manager, entityManagerFactory(primary).reference,
                null, null)), Code.ENTITY_MANAGER_FACTORY_MISMATCH);
        EntityManagerFactory otherEmf = entityManagerFactory(other).reference;
        expect(inspectConfiguration(configuration(primary, jpaManager(primary, otherEmf), otherEmf, null, null)),
                Code.RESOURCE_MISMATCH);
        EntityManagerFactory opaqueEmf = probe(EntityManagerFactory.class).reference;
        expect(inspectConfiguration(configuration(primary, jpaManager(primary, opaqueEmf), opaqueEmf, null, null)),
                Code.UNVERIFIED_ENTITY_MANAGER_FACTORY);
        EntityManagerFactory unavailableEmf = entityManagerFactory(null).reference;
        expect(inspectConfiguration(configuration(primary, jpaManager(primary, unavailableEmf), unavailableEmf,
                null, null)), Code.UNVERIFIED_ENTITY_MANAGER_FACTORY);
    }

    private static void myBatisConfiguration() {
        DataSource primary = probe(DataSource.class).reference;
        DataSource other = probe(DataSource.class).reference;
        var manager = manager(primary);
        var managedFactory = sqlSessionFactory(primary, new SpringManagedTransactionFactory());
        var otherFactory = sqlSessionFactory(other, new SpringManagedTransactionFactory());
        expect(inspectConfiguration(configuration(primary, manager, null, template(managedFactory), null)));
        expect(inspectConfiguration(configuration(primary, manager, null, template(otherFactory), null)),
                Code.RESOURCE_MISMATCH);
        expect(inspectConfiguration(configuration(primary, manager, null,
                template(sqlSessionFactory(primary, new JdbcTransactionFactory())), null)),
                Code.MYBATIS_NOT_SPRING_MANAGED);
        var unspecifiedFactory = new DefaultSqlSessionFactory(new org.apache.ibatis.session.Configuration());
        expect(inspectConfiguration(configuration(primary, manager, null, template(unspecifiedFactory), null)),
                Code.MYBATIS_TEMPLATE_MISMATCH);
        SqlSessionTemplate changingTemplate = new SqlSessionTemplate(managedFactory, ExecutorType.SIMPLE, null) {
            private boolean read;

            @Override
            public SqlSessionFactory getSqlSessionFactory() {
                SqlSessionFactory factory = read ? otherFactory : managedFactory;
                read = true;
                return factory;
            }
        };
        expect(inspectConfiguration(configuration(primary, manager, null, changingTemplate, null)),
                Code.MYBATIS_TEMPLATE_MISMATCH);
    }

    private static void threadState() {
        Probe<DataSource> source = probe(DataSource.class);
        Probe<EntityManagerFactory> factory = entityManagerFactory(source.reference);
        var config = configuration(source.reference, jpaManager(source.reference, factory.reference),
                factory.reference, null, null);
        check(snapshot(config).equals(new Snapshot(false, false, false, false, false,
                Isolation.UNKNOWN, Timeout.UNKNOWN, Rollback.UNKNOWN)), "Empty current-thread state");
        ConnectionHandle unavailableConnection = () -> {
            throw new AssertionError("Connection requested");
        };
        var jdbcHolder = new ConnectionHolder(unavailableConnection);
        var jpaHolder = new EntityManagerHolder(null);
        bind(source, jdbcHolder);
        bind(factory, jpaHolder);
        try {
            TransactionSynchronizationManager.initSynchronization();
            TransactionSynchronizationManager.setActualTransactionActive(true);
            TransactionSynchronizationManager.setCurrentTransactionReadOnly(true);
            TransactionSynchronizationManager.setCurrentTransactionIsolationLevel(Connection.TRANSACTION_REPEATABLE_READ);
            check(snapshot(config).equals(new Snapshot(true, true, true, true, true,
                    Isolation.REPEATABLE_READ, Timeout.NONE, Rollback.CLEAR)), "Bound current-thread state");
            jpaHolder.setTimeoutInSeconds(120);
            check(snapshot(config).timeout() == Timeout.ACTIVE, "Active JPA deadline");
            jdbcHolder.setTimeoutInMillis(-10);
            check(snapshot(config).timeout() == Timeout.EXPIRED, "Earliest observed deadline");
            check(!jdbcHolder.isRollbackOnly() && !jpaHolder.isRollbackOnly(), "Inspection marked rollback-only");
            jpaHolder.setRollbackOnly();
            check(snapshot(config).rollback() == Rollback.MARKED, "JPA rollback marker");
            expect(inspectTransaction(config, intent()), Code.READ_ONLY_WRITE, Code.TIMEOUT_EXPIRED,
                    Code.ROLLBACK_ONLY, Code.MIXED_ACCESS_REQUIRES_EXPLICIT_FLUSH,
                    Code.MIXED_ACCESS_REQUIRES_CACHE_REFRESH, Code.TRANSACTION_OWNERSHIP_UNVERIFIED);
            jdbcHolder.unbound();
            check(!snapshot(config).resourceBound(), "Void holder counted as bound");
            check(TransactionSynchronizationManager.getResourceMap().size() == 2, "Inspection removed a binding");
            check(TransactionSynchronizationManager.isSynchronizationActive(), "Synchronization state changed");
        } finally {
            unbind(factory);
            unbind(source);
            TransactionSynchronizationManager.clear();
        }

        bind(source, new Object());
        try {
            check(!snapshot(config).resourceBound(), "Unrecognized holder counted as bound");
        } finally {
            unbind(source);
        }
        check(TransactionSynchronizationManager.getResourceMap().isEmpty(), "Test bindings remain");
    }

    private static void inspectionFailures() {
        Probe<DataSource> source = probe(DataSource.class);
        DataSource primary = source.reference;
        var manager = manager(primary);
        var brokenJdbc = new JdbcTemplate() {
            @Override
            public DataSource getDataSource() {
                throw new IllegalStateException(SYNTHETIC_DETAIL);
            }
        };
        var config = configuration(primary, manager, null, null, null);
        expect(inspectConfiguration(configuration(primary, manager, null, null, brokenJdbc)), Code.INSPECTION_FAILED);
        var assertionJdbc = jdbcThrowing(new AssertionError(SYNTHETIC_DETAIL));
        expect(inspectConfiguration(configuration(primary, manager, null, null, assertionJdbc)), Code.INSPECTION_FAILED);
        expect(inspectTransaction(config, null), Code.INSPECTION_FAILED);
        expectInspectionException(() -> new Configuration(primary, null, List.of(manager), null, null, null));
        var brokenSources = new AbstractList<DataSource>() {
            @Override
            public DataSource get(int index) {
                throw new AssertionError(SYNTHETIC_DETAIL);
            }

            @Override
            public int size() {
                return 1;
            }
        };
        expectInspectionException(() -> new Configuration(primary, brokenSources, List.of(manager), null, null, null));
        expectInspectionException(() -> snapshot(null));

        ConnectionHandle unavailableConnection = () -> {
            throw new AssertionError("Connection requested");
        };
        var brokenHolder = new ConnectionHolder(unavailableConnection) {
            @Override
            public boolean hasTimeout() {
                throw new AssertionError(SYNTHETIC_DETAIL);
            }
        };
        bind(source, brokenHolder);
        try {
            expectInspectionException(() -> snapshot(config));
            expect(inspectTransaction(config, intent()), Code.INSPECTION_FAILED);
            check(TransactionSynchronizationManager.getResourceMap().size() == 1, "Failure removed a binding");
        } finally {
            unbind(source);
        }

        var fatal = new InternalError();
        var fatalConfig = configuration(primary, manager, null, null, jdbcThrowing(fatal));
        expectFatalPropagation(fatal, () -> inspectConfiguration(fatalConfig));

        var termination = new ThreadDeath();
        var terminatingHolder = new ConnectionHolder(unavailableConnection) {
            @Override
            public boolean hasTimeout() {
                throw termination;
            }
        };
        bind(source, terminatingHolder);
        try {
            expectFatalPropagation(termination, () -> inspectTransaction(config, intent()));
        } finally {
            unbind(source);
        }
    }

    private static JdbcTemplate jdbcThrowing(Error failure) {
        return new JdbcTemplate() {
            @Override
            public DataSource getDataSource() {
                throw failure;
            }
        };
    }

    private static Configuration configuration(DataSource primary, PlatformTransactionManager manager,
                                               EntityManagerFactory emf, SqlSessionTemplate myBatis, JdbcTemplate jdbc) {
        return new Configuration(primary, List.of(primary), List.of(manager), emf, myBatis, jdbc);
    }

    private static Intent intent() {
        return new Intent(true, true, true, Propagation.REQUIRED, false, Isolation.DEFAULT, -1, Outcome.NONE, false);
    }

    private static DataSourceTransactionManager manager(DataSource source) {
        var manager = new DataSourceTransactionManager(source);
        manager.setValidateExistingTransaction(true);
        return manager;
    }

    private static JpaTransactionManager jpaManager(DataSource source, EntityManagerFactory factory) {
        var manager = new JpaTransactionManager();
        manager.setDataSource(source);
        manager.setEntityManagerFactory(factory);
        manager.setValidateExistingTransaction(true);
        return manager;
    }

    private static SqlSessionFactory sqlSessionFactory(DataSource source, TransactionFactory transactions) {
        var environment = new Environment("test", transactions, source);
        return new DefaultSqlSessionFactory(new org.apache.ibatis.session.Configuration(environment));
    }

    private static SqlSessionTemplate template(SqlSessionFactory factory) {
        return new SqlSessionTemplate(factory, ExecutorType.SIMPLE, null);
    }

    private static void expect(Report actual, Code... expected) {
        check(actual.equals(Report.of(expected)), "Unexpected diagnoses " + actual.codes());
    }

    private static void expectInspectionException(Runnable inspect) {
        try {
            inspect.run();
            throw new AssertionError("Inspection failure was hidden");
        } catch (InspectionException ex) {
            check("Spring transaction inspection failed".equals(ex.getMessage()) && ex.getCause() == null
                    && ex.getSuppressed().length == 0, "Inspection failure was not sanitized");
        }
    }

    private static void expectFatalPropagation(Error failure, Runnable inspect) {
        try {
            inspect.run();
            throw new AssertionError("Fatal error was swallowed");
        } catch (VirtualMachineError | ThreadDeath propagated) {
            check(propagated == failure, "Fatal error changed");
        }
    }

    private static void check(boolean condition, String message) {
        if (!condition) {
            throw new AssertionError(message);
        }
        assertions++;
    }

    private static <T> Probe<T> probe(Class<T> type) {
        return new Probe<>(type, null, type);
    }

    private static Probe<EntityManagerFactory> entityManagerFactory(DataSource source) {
        return new Probe<>(EntityManagerFactory.class, source, EntityManagerFactory.class, EntityManagerFactoryInfo.class);
    }

    private static void bind(Probe<?> key, Object holder) {
        key.allowHash = true;
        try {
            TransactionSynchronizationManager.bindResource(key.reference, holder);
        } finally {
            key.allowHash = false;
        }
    }

    private static void unbind(Probe<?> key) {
        key.allowHash = true;
        try {
            TransactionSynchronizationManager.unbindResourceIfPossible(key.reference);
        } finally {
            key.allowHash = false;
        }
    }

    private static final class Probe<T> implements InvocationHandler {
        private final int hash = ++nextHash;
        private final T reference;
        private final DataSource factorySource;
        private boolean allowHash;

        private Probe(Class<T> type, DataSource factorySource, Class<?>... interfaces) {
            this.reference = type.cast(Proxy.newProxyInstance(type.getClassLoader(), interfaces, this));
            this.factorySource = factorySource;
        }

        @Override
        public Object invoke(Object proxy, Method method, Object[] arguments) {
            if (method.getDeclaringClass() == EntityManagerFactoryInfo.class
                    && method.getName().equals("getDataSource")) {
                return factorySource;
            }
            if (allowHash && method.getName().equals("hashCode")) {
                return hash;
            }
            throw new AssertionError("Unexpected resource call " + method.getName());
        }
    }
}
