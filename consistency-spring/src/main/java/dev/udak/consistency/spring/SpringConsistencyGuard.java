package dev.udak.consistency.spring;

import dev.udak.consistency.TransactionGuard;
import dev.udak.consistency.TransactionGuard.Code;
import dev.udak.consistency.TransactionGuard.Intent;
import dev.udak.consistency.TransactionGuard.Isolation;
import dev.udak.consistency.TransactionGuard.Report;
import dev.udak.consistency.TransactionGuard.Rollback;
import dev.udak.consistency.TransactionGuard.Snapshot;
import dev.udak.consistency.TransactionGuard.Timeout;
import jakarta.persistence.EntityManagerFactory;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSessionFactory;
import org.mybatis.spring.SqlSessionTemplate;
import org.mybatis.spring.transaction.SpringManagedTransactionFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.ConnectionHolder;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.orm.jpa.EntityManagerFactoryInfo;
import org.springframework.orm.jpa.EntityManagerHolder;
import org.springframework.orm.jpa.JpaTransactionManager;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.AbstractPlatformTransactionManager;
import org.springframework.transaction.support.ResourceHolderSupport;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import javax.sql.DataSource;
import java.sql.Connection;
import java.util.Collections;
import java.util.EnumSet;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Diagnoses explicitly supplied Spring handles and state associated with the current thread. */
public final class SpringConsistencyGuard {
    private SpringConsistencyGuard() {
    }

    /** Lists are immutable snapshots of the handles registered by the caller. */
    public record Configuration(DataSource dataSource, List<DataSource> dataSources,
                                List<PlatformTransactionManager> transactionManagers,
                                EntityManagerFactory entityManagerFactory, SqlSessionTemplate myBatis,
                                JdbcTemplate jdbc) {
        public Configuration {
            try {
                dataSources = List.copyOf(dataSources);
                transactionManagers = List.copyOf(transactionManagers);
            } catch (Throwable failure) {
                rethrowFatal(failure);
                throw new InspectionException();
            }
        }

        @Override
        public boolean equals(Object other) {
            return this == other || other instanceof Configuration configuration
                    && dataSource == configuration.dataSource
                    && entityManagerFactory == configuration.entityManagerFactory
                    && myBatis == configuration.myBatis && jdbc == configuration.jdbc
                    && sameReferences(dataSources, configuration.dataSources)
                    && sameReferences(transactionManagers, configuration.transactionManagers);
        }

        @Override
        public int hashCode() {
            int hash = System.identityHashCode(dataSource);
            hash = 31 * hash + System.identityHashCode(entityManagerFactory);
            hash = 31 * hash + System.identityHashCode(myBatis);
            hash = 31 * hash + System.identityHashCode(jdbc);
            hash = 31 * hash + referenceListHash(dataSources);
            return 31 * hash + referenceListHash(transactionManagers);
        }

        @Override
        public String toString() {
            return "SpringConsistencyGuard.Configuration";
        }
    }

    public static Report inspectConfiguration(Configuration config) {
        if (config == null || config.dataSource() == null) {
            return Report.of(Code.CONFIGURATION_MISSING);
        }

        Set<Code> codes = EnumSet.noneOf(Code.class);
        try {
            Set<DataSource> dataSources = identities(config.dataSources());
            if (dataSources.isEmpty()) {
                codes.add(Code.CONFIGURATION_MISSING);
            } else if (!dataSources.contains(config.dataSource())) {
                codes.add(Code.RESOURCE_MISMATCH);
            }
            if (dataSources.size() > 1) {
                codes.add(Code.MULTIPLE_DATA_SOURCES);
            }

            inspectManager(config, codes);
            if (config.entityManagerFactory() != null) {
                inspectEntityManagerFactory(config, codes);
            }
            if (config.myBatis() != null) {
                inspectMyBatis(config, codes);
            }
            if (config.jdbc() != null && config.jdbc().getDataSource() != config.dataSource()) {
                codes.add(Code.RESOURCE_MISMATCH);
            }
        } catch (Throwable failure) {
            rethrowFatal(failure);
            codes.add(Code.INSPECTION_FAILED);
        }
        return new Report(List.copyOf(codes));
    }

    private static void inspectManager(Configuration config, Set<Code> codes) {
        Set<PlatformTransactionManager> managers = identities(config.transactionManagers());
        if (managers.isEmpty()) {
            codes.add(Code.MISSING_TRANSACTION_MANAGER);
            return;
        }
        if (managers.size() > 1) {
            codes.add(Code.MULTIPLE_TRANSACTION_MANAGERS);
            return;
        }

        PlatformTransactionManager manager = managers.iterator().next();
        DataSource managedDataSource;
        if (manager instanceof DataSourceTransactionManager jdbcManager) {
            managedDataSource = jdbcManager.getDataSource();
            if (config.entityManagerFactory() != null) {
                codes.add(Code.JPA_REQUIRES_JPA_MANAGER);
            }
        } else if (manager instanceof JpaTransactionManager jpaManager) {
            managedDataSource = jpaManager.getDataSource();
            if (config.entityManagerFactory() != null
                    && jpaManager.getEntityManagerFactory() != config.entityManagerFactory()) {
                codes.add(Code.ENTITY_MANAGER_FACTORY_MISMATCH);
            }
        } else {
            codes.add(Code.UNSUPPORTED_TRANSACTION_MANAGER);
            if (config.entityManagerFactory() != null) {
                codes.add(Code.JPA_REQUIRES_JPA_MANAGER);
            }
            return;
        }

        if (managedDataSource != config.dataSource()) {
            codes.add(Code.RESOURCE_MISMATCH);
        }
        if (!((AbstractPlatformTransactionManager) manager).isValidateExistingTransaction()) {
            codes.add(Code.EXISTING_TRANSACTION_VALIDATION_DISABLED);
        }
    }

    private static void inspectEntityManagerFactory(Configuration config, Set<Code> codes) {
        DataSource factoryDataSource = config.entityManagerFactory() instanceof EntityManagerFactoryInfo info
                ? info.getDataSource() : null;
        if (factoryDataSource == null) {
            codes.add(Code.UNVERIFIED_ENTITY_MANAGER_FACTORY);
        } else if (factoryDataSource != config.dataSource()) {
            codes.add(Code.RESOURCE_MISMATCH);
        }
        if (config.jdbc() != null || config.myBatis() != null) {
            codes.add(Code.MIXED_ACCESS_REQUIRES_EXPLICIT_FLUSH);
            codes.add(Code.MIXED_ACCESS_REQUIRES_CACHE_REFRESH);
        }
    }

    private static void inspectMyBatis(Configuration config, Set<Code> codes) {
        SqlSessionTemplate template = config.myBatis();
        SqlSessionFactory factory = template.getSqlSessionFactory();
        var factoryConfiguration = factory == null ? null : factory.getConfiguration();
        Environment environment = factoryConfiguration == null ? null : factoryConfiguration.getEnvironment();
        if (environment == null || factory != template.getSqlSessionFactory()) {
            codes.add(Code.MYBATIS_TEMPLATE_MISMATCH);
            return;
        }
        if (environment.getDataSource() != config.dataSource()) {
            codes.add(Code.RESOURCE_MISMATCH);
        }
        if (!(environment.getTransactionFactory() instanceof SpringManagedTransactionFactory)) {
            codes.add(Code.MYBATIS_NOT_SPRING_MANAGED);
        }
    }

    /**
     * Reads current-thread Spring metadata. Isolation is UNKNOWN when Spring has no explicit
     * isolation level. Rollback and timeout describe only the matching Spring holders. They do
     * not cover provider-local state or establish which manager owns the actual transaction.
     *
     * @throws InspectionException if the configuration or inspection cannot supply a snapshot
     */
    public static Snapshot snapshot(Configuration config) {
        if (config == null || config.dataSource() == null) {
            throw new InspectionException();
        }
        try {
            // Spring getResource may unwrap keys, invoke hashCode and remove void holders.
            var resources = TransactionSynchronizationManager.getResourceMap();
            ConnectionHolder jdbc = boundHolder(resources, config.dataSource(), ConnectionHolder.class);
            EntityManagerHolder jpa = config.entityManagerFactory() == null ? null
                    : boundHolder(resources, config.entityManagerFactory(), EntityManagerHolder.class);

            return new Snapshot(TransactionSynchronizationManager.isActualTransactionActive(),
                    TransactionSynchronizationManager.isSynchronizationActive(), jdbc != null, jpa != null,
                    TransactionSynchronizationManager.isCurrentTransactionReadOnly(),
                    isolation(TransactionSynchronizationManager.getCurrentTransactionIsolationLevel()),
                    timeout(jdbc, jpa), rollback(jdbc, jpa));
        } catch (Throwable failure) {
            rethrowFatal(failure);
            throw new InspectionException();
        }
    }

    public static Report inspectTransaction(Configuration config, Intent intent) {
        Report configuration = inspectConfiguration(config);
        if (intent == null) {
            return configuration.plus(Report.of(Code.INSPECTION_FAILED));
        }
        if (config == null || config.dataSource() == null) {
            return configuration;
        }
        try {
            return configuration.plus(TransactionGuard.assess(intent, snapshot(config)));
        } catch (Throwable failure) {
            rethrowFatal(failure);
            return configuration.plus(Report.of(Code.INSPECTION_FAILED));
        }
    }

    private static void rethrowFatal(Throwable failure) {
        if (failure instanceof VirtualMachineError fatal) {
            throw fatal;
        }
        if (failure instanceof ThreadDeath termination) {
            throw termination;
        }
    }

    /** Inspection failure without a reference to the inspected resources or original exception. */
    public static final class InspectionException extends IllegalStateException {
        private static final long serialVersionUID = 1L;

        private InspectionException() {
            super("Spring transaction inspection failed", null);
        }
    }

    private static Isolation isolation(Integer level) {
        return switch (level == null ? Connection.TRANSACTION_NONE : level) {
            case Connection.TRANSACTION_READ_UNCOMMITTED -> Isolation.READ_UNCOMMITTED;
            case Connection.TRANSACTION_READ_COMMITTED -> Isolation.READ_COMMITTED;
            case Connection.TRANSACTION_REPEATABLE_READ -> Isolation.REPEATABLE_READ;
            case Connection.TRANSACTION_SERIALIZABLE -> Isolation.SERIALIZABLE;
            default -> Isolation.UNKNOWN;
        };
    }

    private static Timeout timeout(ResourceHolderSupport jdbc, ResourceHolderSupport jpa) {
        long now = System.currentTimeMillis();
        Timeout jdbcTimeout = timeout(jdbc, now);
        Timeout jpaTimeout = timeout(jpa, now);
        if (jdbcTimeout == Timeout.EXPIRED || jpaTimeout == Timeout.EXPIRED) {
            return Timeout.EXPIRED;
        }
        if (jdbcTimeout == Timeout.ACTIVE || jpaTimeout == Timeout.ACTIVE) {
            return Timeout.ACTIVE;
        }
        return jdbc == null && jpa == null ? Timeout.UNKNOWN : Timeout.NONE;
    }

    private static Timeout timeout(ResourceHolderSupport holder, long now) {
        if (holder == null) {
            return Timeout.UNKNOWN;
        }
        if (!holder.hasTimeout()) {
            return Timeout.NONE;
        }
        // Spring's time-to-live accessors may mark the holder rollback-only.
        var deadline = holder.getDeadline();
        if (deadline == null) {
            throw new InspectionException();
        }
        return deadline.getTime() <= now ? Timeout.EXPIRED : Timeout.ACTIVE;
    }

    private static Rollback rollback(ResourceHolderSupport jdbc, ResourceHolderSupport jpa) {
        if ((jdbc != null && jdbc.isRollbackOnly()) || (jpa != null && jpa.isRollbackOnly())) {
            return Rollback.MARKED;
        }
        return jdbc == null && jpa == null ? Rollback.UNKNOWN : Rollback.CLEAR;
    }

    private static <T extends ResourceHolderSupport> T boundHolder(Map<Object, Object> resources, Object key,
                                                                   Class<T> type) {
        for (var resource : resources.entrySet()) {
            if (resource.getKey() == key && type.isInstance(resource.getValue())) {
                T holder = type.cast(resource.getValue());
                return holder.isVoid() ? null : holder;
            }
        }
        return null;
    }

    private static <T> Set<T> identities(List<T> references) {
        Set<T> unique = Collections.newSetFromMap(new IdentityHashMap<>());
        unique.addAll(references);
        return unique;
    }

    private static boolean sameReferences(List<?> left, List<?> right) {
        if (left.size() != right.size()) {
            return false;
        }
        for (int index = 0; index < left.size(); index++) {
            if (left.get(index) != right.get(index)) {
                return false;
            }
        }
        return true;
    }

    private static int referenceListHash(List<?> references) {
        int hash = 1;
        for (Object reference : references) {
            hash = 31 * hash + System.identityHashCode(reference);
        }
        return hash;
    }
}
