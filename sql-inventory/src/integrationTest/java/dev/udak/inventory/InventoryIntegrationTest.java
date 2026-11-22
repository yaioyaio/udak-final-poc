package dev.udak.inventory;

import dev.udak.compat.LegacyCompatibilityTest;
import dev.udak.demo.UserEntity;
import dev.udak.observe.Framework;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.hibernate.HibernateObserveInspector;
import dev.udak.observe.jdbc.ObserveDataSource;
import dev.udak.observe.mybatis.MyBatisObserveInterceptor;
import jakarta.persistence.EntityManager;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.HexFormat;
import javax.sql.DataSource;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.session.Configuration;
import org.h2.jdbcx.JdbcDataSource;
import org.mybatis.spring.SqlSessionFactoryBean;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.orm.jpa.LocalContainerEntityManagerFactoryBean;
import org.springframework.orm.jpa.persistenceunit.PersistenceManagedTypes;
import org.springframework.orm.jpa.vendor.HibernateJpaVendorAdapter;

/** Exercises actual Hibernate, MyBatis and JDBC calls to an isolated, in-memory fixture. */
public final class InventoryIntegrationTest {
    private static final String FIXTURE_NAME = "InventoryFixtureOnlyName";
    private static final String PROFILE = "udak-inventory-h2-adapters-v1";
    private static final String JPA_QUERY = "UserJpa.findName";
    private static final String MYBATIS_QUERY = "UserMapper.findName";
    private static final String JDBC_QUERY = "UserJdbc.findName";
    private static final String JDBC_OPTIONAL = "UserJdbc.countById";
    private static final String JDBC_GAP = "UserJdbc.coverageGap";
    private static final String STATIC_QUERY = "UserMapper.notCalled";
    private static final String MAIN_TEST = "InventoryAdapters.contract";
    private static final String DYNAMIC_TEST = "UserMapper.dynamicShape";
    private static final String OPTIONAL_TEST = "UserJdbc.optionalCoverage";
    private static final String GAP_TEST = "UserJdbc.coverageGapContract";
    private static final String GAP_MARKER = "InventoryGapFixtureMarker";
    private static final String GAP_SQL = "SHOW TABLES /* " + GAP_MARKER + " */";

    private enum Sample {
        BASE("1", 1L, FIXTURE_NAME),
        HEAD("2", 1L, FIXTURE_NAME),
        CONTROL("3", 2L, "InventoryControlBoundFixtureName"),
        GAP("4", 1L, FIXTURE_NAME);

        private final String revisionDigit;
        private final long id;
        private final String name;

        Sample(String revisionDigit, long id, String name) {
            this.revisionDigit = revisionDigit;
            this.id = id;
            this.name = name;
        }
    }

    private static int assertions;

    private InventoryIntegrationTest() { }

    public static void main(String[] args) {
        PrintStream output = LegacyCompatibilityTest.suppressRuntimeOutput();
        try {
            require(args.length == 2 || args.length == 4);
            write(Path.of(args[0]), capture(Sample.BASE));
            write(Path.of(args[1]), capture(Sample.HEAD));
            if (args.length == 4) {
                write(Path.of(args[2]), capture(Sample.CONTROL));
                write(Path.of(args[3]), capture(Sample.GAP));
            }
            output.println("INVENTORY_INTEGRATION PASS");
            output.println("ASSERTIONS=" + assertions);
        } catch (Exception | AssertionError | LinkageError failure) {
            output.println("INVENTORY_INTEGRATION FAIL");
            Throwable cause = failure;
            for (int depth = 0; cause != null && depth < 6; depth++, cause = cause.getCause()) {
                output.println("DIAGNOSTIC=" + cause.getClass().getName());
                for (StackTraceElement frame : cause.getStackTrace()) {
                    if (frame.getClassName().startsWith("dev.udak.") && frame.getLineNumber() > 0) {
                        output.println("DIAGNOSTIC=" + frame.getClassName() + ":" + frame.getLineNumber());
                        break;
                    }
                }
            }
            System.exit(1);
        }
    }

    private static String capture(Sample sample) throws Exception {
        InventoryCapture inventory = new InventoryCapture();
        SqlObserver observer = new SqlObserver(inventory);
        inventory.declare(Framework.MYBATIS, STATIC_QUERY, MAIN_TEST);
        inventory.declare(Framework.JDBC, JDBC_OPTIONAL, OPTIONAL_TEST);
        JdbcDataSource source = new JdbcDataSource();
        source.setURL("jdbc:h2:mem:udak_inventory_fixture");
        try (var keepAlive = source.getConnection()) {
            try (var ddl = keepAlive.createStatement()) {
                ddl.setQueryTimeout(5);
                ddl.executeUpdate("CREATE TABLE app_user (id BIGINT PRIMARY KEY, name VARCHAR(120) NOT NULL)");
            }
            try (var insert = keepAlive.prepareStatement("INSERT INTO app_user (id, name) VALUES (?, ?)")) {
                insert.setQueryTimeout(5);
                insert.setLong(1, sample.id);
                insert.setString(2, sample.name);
                require(insert.executeUpdate() == 1);
            }
            jpa(source, observer, inventory, sample);
            myBatis(source, observer, inventory, sample);
            jdbc(source, observer, inventory, sample);
            try (var count = keepAlive.createStatement(); var rows = count.executeQuery("SELECT COUNT(*) FROM app_user")) {
                require(rows.next() && rows.getInt(1) == 1);
            }
        }
        String revision = sample.revisionDigit.repeat(40);
        String profile = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(PROFILE.getBytes(StandardCharsets.UTF_8)));
        String snapshot = inventory.snapshotJson(revision, profile);
        require(!snapshot.contains(sample.name) && !snapshot.contains(JPA_QUERY)
                && !snapshot.contains(DYNAMIC_TEST) && !snapshot.contains("app_user") && !snapshot.contains("jdbc:"));
        if (sample == Sample.GAP) {
            require(snapshot.contains("\"UNSUPPORTED_SYNTAX\":1") && !snapshot.contains(GAP_MARKER)
                    && !snapshot.contains(JDBC_GAP) && !snapshot.contains(GAP_TEST) && !snapshot.contains("SHOW TABLES"));
        }
        return snapshot;
    }

    private static void jpa(DataSource source, SqlObserver observer, InventoryCapture inventory, Sample sample) {
        var factory = new LocalContainerEntityManagerFactoryBean();
        factory.setDataSource(source);
        factory.setJpaVendorAdapter(new HibernateJpaVendorAdapter());
        factory.setManagedTypes(PersistenceManagedTypes.of(UserEntity.class.getName()));
        factory.getJpaPropertyMap().put("hibernate.hbm2ddl.auto", "none");
        factory.getJpaPropertyMap().put("hibernate.session_factory.statement_inspector", new HibernateObserveInspector(observer));
        try {
            factory.afterPropertiesSet();
            EntityManager entityManager = factory.getObject().createEntityManager();
            try (var scope = inventory.scope(JPA_QUERY, MAIN_TEST)) {
                String result = entityManager.createQuery("SELECT u.name FROM UserEntity u WHERE u.id = :id", String.class)
                        .setHint("jakarta.persistence.query.timeout", 5_000).setParameter("id", sample.id).getSingleResult();
                require(sample.name.equals(result));
            } finally {
                entityManager.close();
            }
        } finally {
            factory.destroy();
        }
    }

    private static void myBatis(DataSource source, SqlObserver observer, InventoryCapture inventory, Sample sample)
            throws Exception {
        Configuration configuration = new Configuration();
        configuration.setDefaultStatementTimeout(5);
        configuration.addMapper(DynamicMapper.class);
        configuration.addInterceptor(new MyBatisObserveInterceptor(observer));
        SqlSessionFactoryBean factory = new SqlSessionFactoryBean();
        factory.setDataSource(source);
        factory.setConfiguration(configuration);
        DynamicMapper mapper = new SqlSessionTemplate(factory.getObject()).getMapper(DynamicMapper.class);
        try (var scope = inventory.scope(MYBATIS_QUERY, DYNAMIC_TEST)) {
            require(sample.name.equals(mapper.findName(sample.id, sample == Sample.HEAD, sample.name)));
        }
    }

    private static void jdbc(DataSource source, SqlObserver observer, InventoryCapture inventory, Sample sample) {
        JdbcTemplate jdbc = new JdbcTemplate(new ObserveDataSource(source, observer));
        jdbc.setQueryTimeout(5);
        try (var scope = inventory.scope(JDBC_QUERY, MAIN_TEST)) {
            require(sample.name.equals(jdbc.queryForObject(
                    "SELECT name FROM app_user WHERE id = ?", String.class, sample.id)));
        }
        if (sample == Sample.HEAD) {
            try (var scope = inventory.scope(JDBC_OPTIONAL, OPTIONAL_TEST)) {
                require(Integer.valueOf(1).equals(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM app_user WHERE id = ?", Integer.class, sample.id)));
            }
        }
        if (sample == Sample.GAP) {
            try (var scope = inventory.scope(JDBC_GAP, GAP_TEST)) {
                require(jdbc.query(GAP_SQL, (row, number) -> row.getString(1)).contains("APP_USER"));
            }
        }
    }

    private static void write(Path target, String snapshot) throws Exception {
        Files.writeString(target, snapshot, StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
    }

    private static void require(boolean condition) {
        assertions++;
        if (!condition) throw new AssertionError("Inventory integration contract failed");
    }

    public interface DynamicMapper {
        @Select("""
                <script>
                SELECT name FROM app_user WHERE id = #{id}
                <if test="checkName">AND name = #{name}</if>
                </script>
                """)
        String findName(@Param("id") long id, @Param("checkName") boolean checkName, @Param("name") String name);
    }
}
