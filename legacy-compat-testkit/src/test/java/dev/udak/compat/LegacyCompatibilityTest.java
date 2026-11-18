package dev.udak.compat;

import dev.udak.demo.MixedUserService;
import dev.udak.demo.UserEntity;
import dev.udak.demo.UserJpaRepository;
import dev.udak.demo.UserMapper;
import dev.udak.observe.FingerprintStatus;
import dev.udak.observe.Framework;
import dev.udak.observe.ObservationPoint;
import dev.udak.observe.SqlObservation;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.hibernate.HibernateObserveInspector;
import dev.udak.observe.jdbc.ObserveDataSource;
import dev.udak.observe.mybatis.MyBatisObserveInterceptor;
import jakarta.persistence.EntityManager;
import jakarta.persistence.EntityManagerFactory;
import java.io.OutputStream;
import java.io.PrintStream;
import java.lang.reflect.Field;
import java.sql.Connection;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.List;
import java.util.logging.Level;
import java.util.logging.LogManager;
import java.util.logging.Logger;
import java.util.regex.Pattern;
import javax.sql.DataSource;
import org.apache.ibatis.annotations.Arg;
import org.apache.ibatis.annotations.ConstructorArgs;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Results;
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
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.data.jpa.repository.support.JpaRepositoryFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceUtils;
import org.springframework.orm.jpa.EntityManagerFactoryInfo;
import org.springframework.orm.jpa.JpaTransactionManager;
import org.springframework.orm.jpa.LocalContainerEntityManagerFactoryBean;
import org.springframework.orm.jpa.SharedEntityManagerCreator;
import org.springframework.orm.jpa.persistenceunit.PersistenceManagedTypes;
import org.springframework.orm.jpa.vendor.HibernateJpaVendorAdapter;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Executable compatibility checks for the unmodified demo and the Observe adapters. */
public final class LegacyCompatibilityTest {
    public static final List<String> CHECKS = List.of(
            "SHARED_RESOURCE", "EXISTING_SERVICE", "FLUSH_VISIBILITY", "JPA_CACHE", "MYBATIS_CACHE",
            "MIXED_COMMIT", "MIXED_ROLLBACK", "RESULT_MAPPING", "OBSERVATION_METADATA", "LISTENER_FAILURE");

    static final int QUERY_TIMEOUT_SECONDS = 5;
    private static final int TRANSACTION_TIMEOUT_SECONDS = 10;
    private static final String FIND_NAME = "SELECT name FROM app_user WHERE id = ?";
    private static final String UPDATE_NAME = "UPDATE app_user SET name = ? WHERE id = ?";
    private static final String BIND_MARKER = "Phase3BoundFixtureValue";
    private static final String LITERAL_MARKER = "Phase3LiteralFixtureValue";
    private static final Pattern DIGEST = Pattern.compile("[0-9a-f]{64}");

    private LegacyCompatibilityTest() { }

    public static void main(String[] args) {
        PrintStream out = suppressRuntimeOutput();
        if (args.length != 0) {
            out.println("H2 NOT RUN: INVALID_ARGUMENT");
            System.exit(2);
            return;
        }
        try {
            JdbcDataSource raw = new JdbcDataSource();
            raw.setURL("jdbc:h2:mem:udak_phase3");
            int checks = run(raw, "H2");
            out.println("H2 PASS");
            out.println("CHECKS=" + checks);
            out.println("CLEANUP=CONFIRMED");
            for (String check : CHECKS) out.println("SCENARIO=" + check + ":PASS");
        } catch (Failure failure) {
            out.println("H2 FAIL: " + failure.code());
            for (String diagnostic : failure.diagnostics()) out.println("DIAGNOSTIC=" + diagnostic);
            System.exit(1);
        } catch (Throwable failure) {
            out.println("H2 FAIL: EXECUTION_ERROR");
            for (String diagnostic : diagnosticsFor(failure)) out.println("DIAGNOSTIC=" + diagnostic);
            System.exit(1);
        }
    }

    /** Install process-lifetime output suppression before any framework or provider is loaded. */
    public static PrintStream suppressRuntimeOutput() {
        PrintStream out = System.out;
        PrintStream sink = new PrintStream(OutputStream.nullOutputStream());
        System.setOut(sink);
        System.setErr(sink);
        LogManager.getLogManager().reset();
        Logger.getLogger("").setLevel(Level.OFF);
        System.setProperty("org.jboss.logging.provider", "jdk");
        return out;
    }

    /** Requires an exclusive disposable database. The caller keeps ownership of its DataSource. */
    public static int run(DataSource raw, String profile) {
        try (CompatibilityFixture fixture = new CompatibilityFixture(raw, profile)) {
            fixture.create();
            try (Stack stack = Stack.open(raw, null)) {
                stack.runScenarios(null);
            }
            fixture.clearRows();
            Observations observations = new Observations();
            SqlObserver observer = new SqlObserver(observations::record);
            try (Stack stack = Stack.open(raw, observer)) {
                stack.runScenarios(observations);
                verify("OBSERVATION_METADATA", () -> stack.verifyObservations(observations));
                verify("LISTENER_FAILURE", () -> stack.verifyListenerFailure(observations));
            }
        } catch (Failure failure) {
            throw failure;
        } catch (RuntimeException | LinkageError failure) {
            throw new Failure("EXECUTION_ERROR", failure);
        }
        return CHECKS.size();
    }

    public static final class Failure extends RuntimeException {
        private static final long serialVersionUID = 1L;
        private final List<String> diagnosticLines;

        Failure(String code) {
            this(code, null);
        }

        Failure(String code, Throwable failure) {
            super(code, null, true, false);
            diagnosticLines = diagnosticsFor(failure);
        }

        public String code() {
            return getMessage();
        }

        public List<String> diagnostics() {
            List<String> result = new ArrayList<>(diagnosticLines);
            for (Throwable suppressed : getSuppressed()) {
                if (suppressed instanceof Failure failure) result.add("cleanup " + failure.code());
            }
            return List.copyOf(result);
        }
    }

    private static List<String> diagnosticsFor(Throwable failure) {
        List<String> result = new ArrayList<>();
        Throwable current = failure;
        for (int depth = 0; current != null && depth < 5; depth++, current = current.getCause()) {
            StringBuilder line = new StringBuilder(current.getClass().getName());
            for (StackTraceElement frame : current.getStackTrace()) {
                if (frame.getClassName().startsWith("dev.udak.") && frame.getLineNumber() > 0) {
                    line.append(" at ").append(frame.getClassName()).append(':').append(frame.getLineNumber());
                    break;
                }
            }
            result.add(line.toString());
        }
        return List.copyOf(result);
    }

    @FunctionalInterface
    private interface Scenario {
        void run() throws Exception;
    }

    private static void verify(String code, Scenario scenario) {
        try {
            scenario.run();
        } catch (Exception | AssertionError | LinkageError failure) {
            throw new Failure(code, failure);
        }
    }

    private static void require(boolean condition) {
        if (!condition) throw new AssertionError();
    }

    private static final class Stack implements AutoCloseable {
        private final LocalContainerEntityManagerFactoryBean factory;
        private final EntityManager entityManager;
        private final JpaTransactionManager manager;
        private final TransactionTemplate transaction;
        private final UserJpaRepository repository;
        private final SqlSessionTemplate sqlSession;
        private final UserMapper mapper;
        private final CompatibilityMapper compatibilityMapper;
        private final JdbcTemplate jdbc;
        private final MixedUserService service;
        private final DataSource dataSource;

        static Stack open(DataSource raw, SqlObserver observer) {
            DataSource ds = observer == null ? raw : new ObserveDataSource(raw, observer);
            LocalContainerEntityManagerFactoryBean factory = new LocalContainerEntityManagerFactoryBean();
            try {
                factory.setDataSource(ds);
                factory.setJpaVendorAdapter(new HibernateJpaVendorAdapter());
                factory.setManagedTypes(PersistenceManagedTypes.of(UserEntity.class.getName()));
                factory.getJpaPropertyMap().put("hibernate.hbm2ddl.auto", "none");
                factory.getJpaPropertyMap().put(SpecHints.HINT_SPEC_QUERY_TIMEOUT, QUERY_TIMEOUT_SECONDS * 1_000);
                if (observer != null) {
                    factory.getJpaPropertyMap().put("hibernate.session_factory.statement_inspector",
                            new HibernateObserveInspector(observer));
                }
                factory.afterPropertiesSet();
                return new Stack(factory, ds, observer);
            } catch (Exception | LinkageError failure) {
                Failure bootstrap = new Failure("FRAMEWORK_BOOTSTRAP", failure);
                try {
                    closeFactory(factory);
                } catch (Failure cleanup) {
                    bootstrap.addSuppressed(cleanup);
                }
                throw bootstrap;
            }
        }

        private Stack(LocalContainerEntityManagerFactoryBean factory, DataSource ds, SqlObserver observer)
                throws Exception {
            this.factory = factory;
            dataSource = ds;
            EntityManagerFactory emf = factory.getObject();
            entityManager = SharedEntityManagerCreator.createSharedEntityManager(emf);
            manager = new JpaTransactionManager(emf);
            manager.setDataSource(ds);
            manager.setDefaultTimeout(TRANSACTION_TIMEOUT_SECONDS);
            manager.afterPropertiesSet();
            transaction = new TransactionTemplate(manager);
            repository = new JpaRepositoryFactory(entityManager).getRepository(UserJpaRepository.class);

            Configuration configuration = new Configuration();
            configuration.setLocalCacheScope(LocalCacheScope.SESSION);
            configuration.setDefaultStatementTimeout(QUERY_TIMEOUT_SECONDS);
            configuration.addMapper(UserMapper.class);
            configuration.addMapper(CompatibilityMapper.class);
            if (observer != null) configuration.addInterceptor(new MyBatisObserveInterceptor(observer));
            SqlSessionFactoryBean sessions = new SqlSessionFactoryBean();
            sessions.setDataSource(ds);
            sessions.setConfiguration(configuration);
            sessions.setTransactionFactory(new SpringManagedTransactionFactory());
            sqlSession = new SqlSessionTemplate(sessions.getObject());
            mapper = sqlSession.getMapper(UserMapper.class);
            compatibilityMapper = sqlSession.getMapper(CompatibilityMapper.class);
            jdbc = new JdbcTemplate(ds);
            jdbc.setQueryTimeout(QUERY_TIMEOUT_SECONDS);

            MixedUserService target = new MixedUserService(repository, mapper, jdbc, entityManager);
            ProxyFactory proxy = new ProxyFactory(target);
            proxy.setProxyTargetClass(true);
            proxy.addAdvice(new TransactionInterceptor(manager, new AnnotationTransactionAttributeSource()));
            service = (MixedUserService) proxy.getProxy();
        }

        void runScenarios(Observations observations) {
            verify("SHARED_RESOURCE", this::verifySharedResource);
            verify("EXISTING_SERVICE", () -> verifyExistingService("existing-service"));
            verify("FLUSH_VISIBILITY", this::verifyFlushVisibility);
            verify("JPA_CACHE", this::verifyJpaCache);
            verify("MYBATIS_CACHE", () -> verifyMyBatisCache(observations));
            verify("MIXED_COMMIT", this::verifyMixedCommit);
            verify("MIXED_ROLLBACK", this::verifyMixedRollback);
            verify("RESULT_MAPPING", this::verifyResultMapping);
        }

        private void verifySharedResource() {
            require(((EntityManagerFactoryInfo) factory.getObject()).getDataSource() == dataSource);
            require(manager.getDataSource() == dataSource);
            require(jdbc.getDataSource() == dataSource);
            require(sqlSession.getConfiguration().getEnvironment().getDataSource() == dataSource);
            transaction.executeWithoutResult(status -> {
                require(TransactionSynchronizationManager.isActualTransactionActive());
                require(TransactionSynchronizationManager.hasResource(factory.getObject()));
                require(TransactionSynchronizationManager.hasResource(dataSource));
                entityManager.unwrap(Session.class).doWork(hibernateConnection -> {
                    Connection jdbcConnection = DataSourceUtils.getConnection(dataSource);
                    try {
                        require(hibernateConnection == jdbcConnection);
                        require(sqlSession.getConnection() == jdbcConnection);
                        require(TransactionSynchronizationManager.hasResource(sqlSession.getSqlSessionFactory()));
                    } finally {
                        DataSourceUtils.releaseConnection(jdbcConnection, dataSource);
                    }
                });
            });
            require(!TransactionSynchronizationManager.hasResource(factory.getObject()));
            require(!TransactionSynchronizationManager.hasResource(dataSource));
            require(!TransactionSynchronizationManager.hasResource(sqlSession.getSqlSessionFactory()));
        }

        private void verifyExistingService(String label) {
            String visible = label + "-visible";
            String rollback = label + "-rollback";
            long id = service.createAndRead(visible);
            require(id > 0);
            require(visible.equals(jdbcName(id)));
            require(service.countByName(visible) == 1);
            try {
                service.createThenFail(rollback);
                throw new AssertionError();
            } catch (IllegalStateException failure) {
                require("test rollback".equals(failure.getMessage()));
            }
            require(service.countByName(rollback) == 0);
            require(service.countByName("temporary") == 0);
        }

        private void verifyFlushVisibility() throws ReflectiveOperationException {
            long id = service.createAndRead("flush-before");
            Field name = UserEntity.class.getDeclaredField("name");
            name.setAccessible(true);
            transaction.executeWithoutResult(status -> {
                UserEntity managed = entityManager.find(UserEntity.class, id);
                setName(name, managed, "flush-after");
                require("flush-after".equals(managed.getName()));
                require("flush-before".equals(mapper.findName(id)));
                require("flush-before".equals(jdbcName(id)));

                entityManager.flush();
                require("flush-after".equals(jdbcName(id)));
                // This independent mapped statement has no local cache entry for this ID.
                require(new UserProjection(id, "flush-after").equals(compatibilityMapper.project(id)));
            });
            require("flush-after".equals(mapper.findName(id)));
        }

        private void verifyJpaCache() {
            long id = service.createAndRead("jpa-cache-before");
            transaction.executeWithoutResult(status -> {
                UserEntity managed = entityManager.find(UserEntity.class, id);
                require(jdbc.update(UPDATE_NAME, "jpa-cache-refresh", id) == 1);
                require(entityManager.find(UserEntity.class, id) == managed);
                require("jpa-cache-before".equals(managed.getName()));

                entityManager.refresh(managed);
                require("jpa-cache-refresh".equals(managed.getName()));
                require(jdbc.update(UPDATE_NAME, "jpa-cache-clear", id) == 1);
                require("jpa-cache-refresh".equals(entityManager.find(UserEntity.class, id).getName()));

                entityManager.clear();
                UserEntity reloaded = entityManager.find(UserEntity.class, id);
                require(reloaded != managed);
                require("jpa-cache-clear".equals(reloaded.getName()));
            });
        }

        private void verifyMyBatisCache(Observations observations) throws ReflectiveOperationException {
            long id = service.createAndRead("mybatis-cache-before");
            Field name = UserEntity.class.getDeclaredField("name");
            name.setAccessible(true);
            transaction.executeWithoutResult(status -> {
                int before = observations == null ? 0 : observations.count(Framework.MYBATIS);
                require("mybatis-cache-before".equals(mapper.findName(id)));
                SqlObservation first = null;
                if (observations != null) {
                    require(observations.count(Framework.MYBATIS) == before + 1);
                    first = observations.last(Framework.MYBATIS);
                }
                require(jdbc.update(UPDATE_NAME, "mybatis-cache-jdbc", id) == 1);
                require("mybatis-cache-before".equals(mapper.findName(id)));
                if (observations != null) require(observations.count(Framework.MYBATIS) == before + 1);

                sqlSession.clearCache();
                require("mybatis-cache-jdbc".equals(mapper.findName(id)));
                if (observations != null) {
                    require(observations.count(Framework.MYBATIS) == before + 2);
                    require(first.equals(observations.last(Framework.MYBATIS)));
                }

                UserEntity managed = entityManager.find(UserEntity.class, id);
                setName(name, managed, "mybatis-cache-jpa");
                entityManager.flush();
                require("mybatis-cache-jpa".equals(jdbcName(id)));
                require("mybatis-cache-jdbc".equals(mapper.findName(id)));
                if (observations != null) require(observations.count(Framework.MYBATIS) == before + 2);

                sqlSession.clearCache();
                require("mybatis-cache-jpa".equals(mapper.findName(id)));
                if (observations != null) {
                    require(observations.count(Framework.MYBATIS) == before + 3);
                    require(first.equals(observations.last(Framework.MYBATIS)));
                }
            });
        }

        private void verifyMixedCommit() {
            long myBatisId = service.createAndRead("commit-mybatis-before");
            long jdbcId = service.createAndRead("commit-jdbc-before");
            Long jpaId = transaction.execute(status -> writeThroughAllThree("commit", myBatisId, jdbcId));
            require(jpaId != null);
            String reloadedName = transaction.execute(status -> repository.findById(jpaId).orElseThrow().getName());
            require("commit-jpa".equals(reloadedName));
            require("commit-mybatis".equals(jdbcName(myBatisId)));
            require("commit-jdbc".equals(mapper.findName(jdbcId)));
        }

        private void verifyMixedRollback() {
            long myBatisId = service.createAndRead("rollback-mybatis-before");
            long jdbcId = service.createAndRead("rollback-jdbc-before");
            IllegalStateException requestedRollback = new IllegalStateException();
            try {
                transaction.executeWithoutResult(status -> {
                    writeThroughAllThree("rollback", myBatisId, jdbcId);
                    throw requestedRollback;
                });
                throw new AssertionError();
            } catch (IllegalStateException failure) {
                require(failure == requestedRollback);
            }
            require(service.countByName("rollback-jpa") == 0);
            require("rollback-mybatis-before".equals(jdbcName(myBatisId)));
            require("rollback-jdbc-before".equals(mapper.findName(jdbcId)));
        }

        private long writeThroughAllThree(String label, long myBatisId, long jdbcId) {
            long jpaId = repository.save(new UserEntity(label + "-jpa")).getId();
            entityManager.flush();
            require(compatibilityMapper.rename(myBatisId, label + "-mybatis") == 1);
            require(jdbc.update(UPDATE_NAME, label + "-jdbc", jdbcId) == 1);
            require((label + "-jpa").equals(jdbcName(jpaId)));
            require((label + "-mybatis").equals(jdbcName(myBatisId)));
            require((label + "-jdbc").equals(mapper.findName(jdbcId)));
            return jpaId;
        }

        private void verifyResultMapping() {
            long id = service.createAndRead("result-mapping");
            UserProjection expected = new UserProjection(id, "result-mapping");
            UserProjection result = jdbc.queryForObject("SELECT id, name FROM app_user WHERE id = ?",
                    (row, index) -> new UserProjection(row.getLong("id"), row.getString("name")), id);
            require(expected.equals(result));
            require(expected.equals(compatibilityMapper.project(id)));
        }

        private void verifyObservations(Observations observations) {
            long markerId = service.createAndRead(BIND_MARKER);
            SqlObservation mapped = observations.last(Framework.MYBATIS);
            long literalId = service.createAndRead(LITERAL_MARKER);
            require(mapped.fingerprintStatus() == FingerprintStatus.NORMALIZED);
            require(mapped.equals(observations.last(Framework.MYBATIS)));
            require(new UserProjection(markerId, BIND_MARKER).equals(compatibilityMapper.project(markerId)));
            require(!mapped.queryIdHash().equals(observations.last(Framework.MYBATIS).queryIdHash()));
            int before = observations.count(Framework.JDBC);
            require(BIND_MARKER.equals(jdbcName(markerId)));
            require(observations.count(Framework.JDBC) == before + 1);
            SqlObservation direct = observations.last(Framework.JDBC);
            require(direct.fingerprintStatus() == FingerprintStatus.NORMALIZED);
            require(LITERAL_MARKER.equals(jdbcName(literalId)));
            require(direct.equals(observations.last(Framework.JDBC)));

            require(LITERAL_MARKER.equals(jdbc.queryForObject(
                    "SELECT name FROM app_user WHERE name = '" + LITERAL_MARKER + "'", String.class)));
            SqlObservation literal = observations.last(Framework.JDBC);
            require(BIND_MARKER.equals(jdbc.queryForObject(
                    "SELECT name FROM app_user WHERE name = '" + BIND_MARKER + "'", String.class)));
            require(literal.fingerprintStatus() == FingerprintStatus.NORMALIZED);
            require(literal.equals(observations.last(Framework.JDBC)));
            for (SqlObservation event : observations.events) {
                require(DIGEST.matcher(event.queryIdHash()).matches());
                require(DIGEST.matcher(event.fingerprintHash()).matches());
                require(event.point() == switch (event.framework()) {
                    case JPA -> ObservationPoint.JPA_INSPECT;
                    case MYBATIS -> ObservationPoint.MYBATIS_PREPARE;
                    case JDBC -> ObservationPoint.JDBC_EXECUTE;
                });
                String metadata = event.toString();
                require(!metadata.contains(BIND_MARKER) && !metadata.contains(LITERAL_MARKER));
                require(!metadata.contains("app_user") && !metadata.contains("jdbc:"));
            }
            require(observations.count(Framework.JPA) > 0);
            require(observations.count(Framework.MYBATIS) > 0);
            require(observations.count(Framework.JDBC) > 0);
        }

        private void verifyListenerFailure(Observations observations) {
            observations.fail = true;
            verifyExistingService("listener-failure");
            for (Framework framework : Framework.values()) require(observations.failures.contains(framework));
        }

        private String jdbcName(long id) {
            return jdbc.queryForObject(FIND_NAME, String.class, id);
        }

        @Override
        public void close() {
            // The transaction manager and SqlSessionTemplate release their per-call resources.
            closeFactory(factory);
            if (factory.getObject().isOpen()) throw new Failure("FRAMEWORK_CLEANUP");
        }

        private static void closeFactory(LocalContainerEntityManagerFactoryBean factory) {
            try {
                factory.destroy();
            } catch (RuntimeException failure) {
                throw new Failure("FRAMEWORK_CLEANUP", failure);
            }
        }
    }

    private static void setName(Field field, UserEntity entity, String value) {
        try {
            // Exercise dirty tracking on the existing field-mapped entity, which has no name setter.
            field.set(entity, value);
        } catch (IllegalAccessException failure) {
            throw new AssertionError();
        }
    }

    private static final class Observations {
        private final List<SqlObservation> events = new ArrayList<>();
        private final EnumSet<Framework> failures = EnumSet.noneOf(Framework.class);
        private boolean fail;

        void record(SqlObservation event) {
            if (fail) {
                failures.add(event.framework());
                throw new IllegalStateException();
            }
            events.add(event);
        }

        int count(Framework framework) {
            int count = 0;
            for (SqlObservation event : events) {
                if (event.framework() == framework) count++;
            }
            return count;
        }

        SqlObservation last(Framework framework) {
            for (int i = events.size() - 1; i >= 0; i--) {
                SqlObservation event = events.get(i);
                if (event.framework() == framework) return event;
            }
            throw new AssertionError();
        }
    }

    public record UserProjection(long id, String label) { }

    public interface CompatibilityMapper {
        @Select("SELECT id AS mapped_id, name AS mapped_name FROM app_user WHERE id = #{id}")
        @Results(id = "compatibilityUserProjection")
        @ConstructorArgs({@Arg(column = "mapped_id", javaType = long.class, id = true),
                @Arg(column = "mapped_name", javaType = String.class)})
        UserProjection project(@Param("id") long id);

        @Update("UPDATE app_user SET name = #{name} WHERE id = #{id}")
        int rename(@Param("id") long id, @Param("name") String name);
    }
}
