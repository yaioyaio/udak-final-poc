package dev.udak.testkit;

import dev.udak.core.DbVendor;
import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.sql.Statement;
import java.sql.ResultSet;
import java.util.List;
import javax.sql.DataSource;
import org.h2.jdbcx.JdbcDataSource;

/** H2 exercises the scenario only; it is not evidence of a real DBMS. */
public final class DatabaseFoundationTest {
    private static int assertions;
    private static void check(boolean ok) { assertions++; if (!ok) throw new AssertionError("Foundation assertion failed: " + assertions); }
    public static void main(String[] args) throws Exception {
        String fixture = "udak_p2_012345abcdef";
        String[] products = {"PostgreSQL", "MySQL", "Microsoft SQL Server", "Oracle"};
        String[] drivers = {"org.postgresql.Driver", "com.mysql.cj.jdbc.Driver", "com.microsoft.sqlserver.jdbc.SQLServerDriver", "oracle.jdbc.OracleDriver"};
        DatabaseProfile[] profiles = DatabaseProfile.values();
        check(profiles.length == 4);
        for (int i = 0; i < profiles.length; i++) {
            DatabaseProfile p = profiles[i];
            check(p.matchesProduct(products[i]) && p.matchesProduct(products[i].toUpperCase(java.util.Locale.ROOT)));
            check(!p.matchesProduct("H2") && !p.matchesProduct(products[i] + " extra"));
            check(p.driverClass().equals(drivers[i]));
            String ddl = p.createFixtureSql(fixture);
            check(ddl.contains(p == DatabaseProfile.ORACLE ? "NUMBER" : "INTEGER"));
            check(ddl.contains(p == DatabaseProfile.ORACLE ? "VARCHAR2(120)" : "VARCHAR(120)"));
            check(RealDatabaseContractRunner.execute(p, List.of()).equals("NOT RUN: DEDICATED_PROVIDER_REQUIRED"));
            try { p.createFixtureSql("existing_table"); throw new AssertionError(); }
            catch (IllegalArgumentException expected) { check(true); }
        }
        check(DatabaseProfile.ORACLE.vendor() == DbVendor.ORACLE_19);
        RealDatabaseProvider unapproved = new RealDatabaseProvider() {
            public DatabaseProfile profile() { return DatabaseProfile.POSTGRESQL; }
            public DataSource dataSource() { throw new AssertionError("DataSource must not be requested"); }
            public boolean dedicatedSchemaApproved() { return false; }
        };
        check(RealDatabaseContractRunner.execute(DatabaseProfile.POSTGRESQL, List.of(unapproved))
                .equals("NOT RUN: DEDICATED_PROVIDER_REQUIRED"));
        check(RealDatabaseContractRunner.execute(DatabaseProfile.POSTGRESQL, List.of(unapproved, unapproved))
                .equals("NOT RUN: DEDICATED_PROVIDER_REQUIRED"));
        check(DatabaseFoundationTest.class.getClassLoader().getResource(
                "META-INF/services/dev.udak.testkit.RealDatabaseProvider") != null);
        ByteArrayOutputStream inventory = new ByteArrayOutputStream();
        PrintStream original = System.out;
        try (PrintStream capture = new PrintStream(inventory)) {
            System.setOut(capture);
            RealDatabaseContractRunner.main(new String[0]);
        } finally { System.setOut(original); }
        check(inventory.toString(java.nio.charset.StandardCharsets.UTF_8).lines().count() == 4);
        check(InventoryProvider.calls == 0);
        RealDatabaseProvider approved = new RealDatabaseProvider() {
            public DatabaseProfile profile() { return DatabaseProfile.POSTGRESQL; }
            public DataSource dataSource() { throw new AssertionError("driver must be checked first"); }
            public boolean dedicatedSchemaApproved() { return true; }
        };
        check(RealDatabaseContractRunner.execute(DatabaseProfile.POSTGRESQL, List.of(approved),
                name -> { throw new ClassNotFoundException("sentinel"); }).equals("NOT RUN: DRIVER_UNAVAILABLE"));
        JdbcDataSource h2 = new JdbcDataSource();
        h2.setURL("jdbc:h2:mem:udak_foundation;DB_CLOSE_DELAY=-1");
        RealDatabaseProvider h2Provider = new RealDatabaseProvider() {
            public DatabaseProfile profile() { return DatabaseProfile.POSTGRESQL; }
            public DataSource dataSource() { return h2; }
            public boolean dedicatedSchemaApproved() { return true; }
        };
        check(RealDatabaseContractRunner.execute(DatabaseProfile.POSTGRESQL, List.of(h2Provider), name -> { })
                .equals("NOT RUN: PRODUCT_MISMATCH"));
        check(RealDatabaseContractRunner.runEmbeddedTest(h2) == 10);
        FailureDataSource createFailure = new FailureDataSource(h2, true);
        try { RealDatabaseContractRunner.runEmbeddedTest(createFailure.proxy()); throw new AssertionError(); }
        catch (DatabaseScenario.Failure failure) {
            check(failure.code.equals("CREATION_UNCONFIRMED"));
            check(failure.fixture.equals(createFailure.fixture));
            DatabaseProfile.validateFixture(failure.fixture);
        }
        check(createFailure.opened == createFailure.closed);
        FailureDataSource dropFailure = new FailureDataSource(h2, false);
        try { RealDatabaseContractRunner.runEmbeddedTest(dropFailure.proxy()); throw new AssertionError(); }
        catch (DatabaseScenario.Failure failure) {
            check(failure.code.equals("CLEANUP_UNCONFIRMED"));
            check(failure.fixture.equals(dropFailure.fixture));
            DatabaseProfile.validateFixture(failure.fixture);
            try (Connection c = h2.getConnection(); Statement statement = c.createStatement()) {
                statement.executeUpdate("DROP TABLE " + failure.fixture);
            }
        }
        check(dropFailure.opened == dropFailure.closed);
        try (Connection c = h2.getConnection(); ResultSet rs = c.getMetaData().getTables(null, null, "UDAK_P2_%", new String[]{"BASE TABLE", "TABLE"})) {
            check(!rs.next());
        }
        System.out.println("DB FOUNDATION: PASS (assertions=" + assertions + ")");
    }
    /** Service registration lets inventory mode prove it does not instantiate or call a provider. */
    public static final class InventoryProvider implements RealDatabaseProvider {
        static int calls;
        public InventoryProvider() { calls++; }
        public DatabaseProfile profile() { calls++; return DatabaseProfile.POSTGRESQL; }
        public DataSource dataSource() { calls++; throw new AssertionError(); }
        public boolean dedicatedSchemaApproved() { calls++; return true; }
    }

    private static final class FailureDataSource {
        final DataSource delegate;
        final boolean failCreate;
        int opened, closed;
        String fixture;
        FailureDataSource(DataSource delegate, boolean failCreate) { this.delegate = delegate; this.failCreate = failCreate; }
        DataSource proxy() { return (DataSource) wrap(delegate, DataSource.class); }
        Object wrap(Object target, Class<?> type) {
            return Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, (proxy, method, args) -> {
                String name = method.getName();
                if (type == Connection.class && name.equals("close")) closed++;
                if (type == Statement.class && name.equals("executeUpdate") && args != null && args[0] instanceof String sql) {
                    if (sql.startsWith("CREATE TABLE ")) {
                        fixture = sql.substring("CREATE TABLE ".length(), sql.indexOf(" ("));
                        DatabaseProfile.validateFixture(fixture);
                        if (failCreate) throw new java.sql.SQLException("sentinel");
                    }
                    if (sql.startsWith("DROP TABLE ") && !failCreate) throw new java.sql.SQLException("sentinel");
                }
                try {
                    Object value = method.invoke(target, args);
                    if (type == DataSource.class && name.equals("getConnection")) { opened++; return wrap(value, Connection.class); }
                    if (type == Connection.class && name.equals("createStatement")) return wrap(value, Statement.class);
                    return value;
                } catch (InvocationTargetException ex) { throw ex.getCause(); }
            });
        }
    }

}
