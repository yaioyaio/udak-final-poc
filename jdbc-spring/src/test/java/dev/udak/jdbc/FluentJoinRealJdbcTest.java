package dev.udak.jdbc;

import dev.udak.core.DbVendor;
import java.io.IOException;
import java.io.OutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.Arrays;
import java.util.Properties;
import java.util.logging.LogManager;
import java.util.regex.Pattern;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/** Runs the shared Spring JDBC fixture on a fresh native database owned by the runner. */
public final class FluentJoinRealJdbcTest {
    private static final int PASSWORD_LENGTH = 48;
    private static final Pattern PORT = Pattern.compile("[1-9][0-9]{0,4}");
    private static final Pattern SERVER_RELEASE = Pattern.compile(
        "([0-9]{1,3}(?:\\.[0-9]{1,4}){1,2})(?:[ -][ -~]{1,180})?");

    private FluentJoinRealJdbcTest() {}

    public static void main(String[] args) {
        PrintStream report = System.out;
        PrintStream errors = System.err;
        PrintStream discard = new PrintStream(OutputStream.nullOutputStream());
        System.setOut(discard);
        System.setErr(discard);
        LogManager.getLogManager().reset();

        Stage stage = Stage.ARGUMENTS;
        try {
            if (args.length != 2 || !PORT.matcher(args[1]).matches()) {
                throw new IllegalArgumentException();
            }
            Profile profile = Profile.valueOf(args[0]);
            int port = Integer.parseInt(args[1]);
            if (port > 65535) {
                throw new IllegalArgumentException();
            }

            stage = Stage.INPUT;
            String password = readPassword();
            stage = Stage.CONNECTION;
            DriverManager.setLoginTimeout(5);
            DriverManagerDataSource dataSource = profile.dataSource(port, password);
            Identity identity;
            try (Connection connection = dataSource.getConnection()) {
                stage = Stage.IDENTITY;
                identity = verifyIdentity(connection, profile);
            }

            stage = Stage.FIXTURE;
            int checks = FluentJoinJdbcTest.checkQueries(dataSource, DbVendor.valueOf(profile.name()));
            report.printf("FLUENT_JOIN_REAL %s %s %s %d%n",
                profile, identity.serverVersion(), identity.driverVersion(), checks);
        } catch (Exception | AssertionError | LinkageError failure) {
            errors.println("FLUENT_JOIN_REAL FAIL " + stage);
            System.exit(1);
        }
    }

    private static String readPassword() throws IOException {
        byte[] input = System.in.readNBytes(PASSWORD_LENGTH + 2);
        try {
            if (input.length != PASSWORD_LENGTH + 1 || input[PASSWORD_LENGTH] != '\n') {
                throw new IllegalArgumentException();
            }
            for (int index = 0; index < PASSWORD_LENGTH; index++) {
                int digit = input[index];
                if ((digit < '0' || digit > '9') && (digit < 'a' || digit > 'f')) {
                    throw new IllegalArgumentException();
                }
            }
            return new String(input, 0, PASSWORD_LENGTH, StandardCharsets.US_ASCII);
        } finally {
            Arrays.fill(input, (byte) 0);
        }
    }

    private static Identity verifyIdentity(Connection connection, Profile profile) throws SQLException {
        var metadata = connection.getMetaData();
        String serverVersion = numericVersion(SERVER_RELEASE, metadata.getDatabaseProductVersion());
        String driverVersion = numericVersion(profile.driverRelease, metadata.getDriverVersion());
        String[] serverParts = serverVersion.split("\\.");
        if (!profile.product.equals(metadata.getDatabaseProductName())
            || !profile.driver.equals(metadata.getDriverName())
            || !profile.database.equals(connection.getCatalog())
            || !profile.serverVersion.equals(serverVersion)
            || !profile.driverVersion.equals(driverVersion)
            || Integer.parseInt(serverParts[0]) != metadata.getDatabaseMajorVersion()
            || Integer.parseInt(serverParts[1]) != metadata.getDatabaseMinorVersion()) {
            throw new IllegalStateException();
        }
        return new Identity(serverVersion, driverVersion);
    }

    private static String numericVersion(Pattern format, String release) {
        if (release == null || release.length() > 256) {
            throw new IllegalStateException();
        }
        var match = format.matcher(release);
        if (!match.matches()) {
            throw new IllegalStateException();
        }
        return match.group(1);
    }

    private enum Stage { ARGUMENTS, INPUT, CONNECTION, IDENTITY, FIXTURE }

    private enum Profile {
        POSTGRESQL("postgresql", "postgres", "PostgreSQL", "org.postgresql.Driver", "PostgreSQL JDBC Driver",
            "17.11", "42.7.14", "([0-9]+(?:\\.[0-9]+){2})"),
        MYSQL("mysql", "udak_fixture", "MySQL", "com.mysql.cj.jdbc.Driver", "MySQL Connector/J",
            "8.0.46", "26.10.0", "mysql-connector-j-([0-9]+(?:\\.[0-9]+){2}) \\(Revision: [A-Za-z0-9._-]{1,128}\\)");

        private final String protocol;
        private final String database;
        private final String product;
        private final String driverClass;
        private final String driver;
        private final String serverVersion;
        private final String driverVersion;
        private final Pattern driverRelease;

        Profile(String protocol, String database, String product, String driverClass, String driver,
                String serverVersion, String driverVersion, String driverRelease) {
            this.protocol = protocol;
            this.database = database;
            this.product = product;
            this.driverClass = driverClass;
            this.driver = driver;
            this.serverVersion = serverVersion;
            this.driverVersion = driverVersion;
            this.driverRelease = Pattern.compile(driverRelease);
        }

        private DriverManagerDataSource dataSource(int port, String password) {
            Properties options = new Properties();
            switch (this) {
                case POSTGRESQL -> {
                    options.setProperty("connectTimeout", "5");
                    options.setProperty("socketTimeout", "5");
                    options.setProperty("sslmode", "disable");
                    options.setProperty("gssEncMode", "disable");
                    options.setProperty("currentSchema", "public");
                    options.setProperty("options", "-c statement_timeout=3000");
                }
                case MYSQL -> {
                    options.setProperty("connectTimeout", "5000");
                    options.setProperty("socketTimeout", "5000");
                    options.setProperty("sslMode", "DISABLED");
                    options.setProperty("allowPublicKeyRetrieval", "true");
                    options.setProperty("logger", "com.mysql.cj.log.NullLogger");
                    options.setProperty("databaseTerm", "CATALOG");
                    options.setProperty("sessionVariables",
                        "max_execution_time=3000,lock_wait_timeout=3,innodb_lock_wait_timeout=3");
                }
            }
            var dataSource = new DriverManagerDataSource();
            dataSource.setDriverClassName(driverClass);
            dataSource.setUrl("jdbc:" + protocol + "://127.0.0.1:" + port + "/" + database);
            dataSource.setUsername("udak_fixture");
            dataSource.setPassword(password);
            dataSource.setConnectionProperties(options);
            return dataSource;
        }
    }

    private record Identity(String serverVersion, String driverVersion) {}
}
