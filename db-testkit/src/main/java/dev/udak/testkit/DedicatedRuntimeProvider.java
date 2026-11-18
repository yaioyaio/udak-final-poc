package dev.udak.testkit;

import java.io.ByteArrayInputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.sql.SQLFeatureNotSupportedException;
import java.util.Arrays;
import java.util.EnumMap;
import java.util.Map;
import java.util.Optional;
import java.util.Properties;
import java.util.logging.Logger;
import java.util.regex.Pattern;
import javax.sql.DataSource;

/** Supplies loopback-only connections for the managed G2 process. */
public abstract class DedicatedRuntimeProvider implements RealDatabaseProvider {
    private static final String PIPE_PROPERTY = "udak.g2.dedicatedPipe";
    private static final int PIPE_MAGIC = 0x5544414B;
    private static final int PIPE_VERSION = 1;
    private static final int MAX_PIPE_BYTES = 8192;
    private static final int MAX_FIELD_BYTES = 256;
    private static final int LOGIN_TIMEOUT_SECONDS = 5;
    private static final Pattern IDENTIFIER = Pattern.compile("[A-Za-z0-9_]{1,63}");
    private static final Pattern PASSWORD = Pattern.compile("[A-Za-z0-9_-]{24,128}");
    private static final Pattern OWNERSHIP = Pattern.compile("[0-9a-f]{32}");

    private final DatabaseProfile profile;

    private DedicatedRuntimeProvider(DatabaseProfile profile) {
        this.profile = profile;
    }

    public static final class Postgresql extends DedicatedRuntimeProvider {
        public Postgresql() { super(DatabaseProfile.POSTGRESQL); }
    }

    public static final class MySql extends DedicatedRuntimeProvider {
        public MySql() { super(DatabaseProfile.MYSQL); }
    }

    public static final class SqlServer extends DedicatedRuntimeProvider {
        public SqlServer() { super(DatabaseProfile.SQLSERVER); }
    }

    public static final class Oracle extends DedicatedRuntimeProvider {
        public Oracle() { super(DatabaseProfile.ORACLE); }
    }

    @Override
    public final DatabaseProfile profile() {
        return profile;
    }

    @Override
    public final boolean dedicatedSchemaApproved() {
        return configuredSource() != null;
    }

    @Override
    public final DataSource dataSource() {
        DataSource source = configuredSource();
        if (source == null) throw new IllegalStateException("Dedicated database provider is not approved");
        return source;
    }

    private DataSource configuredSource() {
        if (!"true".equals(System.getProperty(PIPE_PROPERTY))) return null;
        return SharedPipe.SOURCES.orElseThrow(DedicatedRuntimeProvider::invalidPipe).get(profile);
    }

    private static final class SharedPipe {
        private static final Optional<Map<DatabaseProfile, DataSource>> SOURCES = load();

        private static Optional<Map<DatabaseProfile, DataSource>> load() {
            try {
                return Optional.of(readPipe(System.in));
            } catch (IllegalArgumentException ex) {
                return Optional.empty();
            }
        }
    }

    static Map<DatabaseProfile, DataSource> readPipe(InputStream input) {
        byte[] frame = new byte[MAX_PIPE_BYTES + 1];
        try {
            int length = input.readNBytes(frame, 0, frame.length);
            if (length > MAX_PIPE_BYTES) throw invalidPipe();
            var data = new DataInputStream(new ByteArrayInputStream(frame, 0, length));
            if (data.readInt() != PIPE_MAGIC || data.readInt() != PIPE_VERSION) throw invalidPipe();
            int count = data.readInt();
            if (count < 1 || count > DatabaseProfile.values().length) throw invalidPipe();

            Map<DatabaseProfile, DataSource> sources = new EnumMap<>(DatabaseProfile.class);
            for (int index = 0; index < count; index++) {
                DatabaseProfile profile = DatabaseProfile.valueOf(readAscii(data));
                if (sources.containsKey(profile)) throw invalidPipe();
                int port = data.readInt();
                String database = readAscii(data);
                String username = readAscii(data);
                String password = readAscii(data);
                String ownership = readAscii(data);
                if (port < 1 || port > 65535 || !IDENTIFIER.matcher(database).matches()
                        || !IDENTIFIER.matcher(username).matches() || !PASSWORD.matcher(password).matches()
                        || !OWNERSHIP.matcher(ownership).matches()) {
                    throw invalidPipe();
                }
                sources.put(profile, new DedicatedDataSource(profile, port, database, username, password));
            }
            if (data.read() != -1) throw invalidPipe();
            return Map.copyOf(sources);
        } catch (IOException | RuntimeException ex) {
            throw invalidPipe();
        } finally {
            Arrays.fill(frame, (byte) 0);
        }
    }

    // For non-NUL ASCII, DataOutputStream.writeUTF encodes the field as its length and raw bytes.
    private static String readAscii(DataInputStream data) throws IOException {
        int length = data.readUnsignedShort();
        if (length > MAX_FIELD_BYTES) throw invalidPipe();
        byte[] value = new byte[length];
        try {
            data.readFully(value);
            for (byte character : value) if (character <= 0) throw invalidPipe();
            return new String(value, StandardCharsets.US_ASCII);
        } finally {
            Arrays.fill(value, (byte) 0);
        }
    }

    private static IllegalArgumentException invalidPipe() {
        return new IllegalArgumentException("Invalid dedicated database pipe");
    }

    private static final class DedicatedDataSource implements DataSource {
        private final String url;
        private final Properties properties = new Properties();

        private DedicatedDataSource(DatabaseProfile profile, int port, String database, String username, String password) {
            String address = "127.0.0.1:" + port;
            properties.setProperty("user", username);
            properties.setProperty("password", password);
            url = switch (profile) {
                case POSTGRESQL -> {
                    properties.setProperty("connectTimeout", "5");
                    properties.setProperty("socketTimeout", "10");
                    yield "jdbc:postgresql://" + address + "/" + database;
                }
                case MYSQL -> {
                    properties.setProperty("connectTimeout", "5000");
                    properties.setProperty("socketTimeout", "10000");
                    properties.setProperty("useSSL", "false");
                    properties.setProperty("allowPublicKeyRetrieval", "true");
                    yield "jdbc:mysql://" + address + "/" + database;
                }
                case SQLSERVER -> {
                    properties.setProperty("databaseName", database);
                    properties.setProperty("loginTimeout", "5");
                    properties.setProperty("socketTimeout", "10000");
                    properties.setProperty("encrypt", "true");
                    properties.setProperty("trustServerCertificate", "true");
                    yield "jdbc:sqlserver://" + address;
                }
                case ORACLE -> {
                    properties.setProperty("oracle.net.CONNECT_TIMEOUT", "5000");
                    properties.setProperty("oracle.jdbc.ReadTimeout", "10000");
                    yield "jdbc:oracle:thin:@//" + address + "/" + database;
                }
            };
        }

        @Override
        public Connection getConnection() throws SQLException {
            if (DriverManager.getLogWriter() != null) throw new IllegalStateException("Dedicated database logging is disabled");
            try {
                return DriverManager.getConnection(url, (Properties) properties.clone());
            } catch (SQLException | RuntimeException | LinkageError ex) {
                throw new SQLException("Dedicated database connection failed");
            }
        }

        @Override
        public Connection getConnection(String username, String password) throws SQLException {
            throw new SQLFeatureNotSupportedException("Dedicated database credentials are fixed");
        }

        @Override
        public PrintWriter getLogWriter() {
            return null;
        }

        @Override
        public void setLogWriter(PrintWriter writer) throws SQLException {
            if (writer != null) throw new SQLFeatureNotSupportedException("Dedicated database logging is disabled");
        }

        @Override
        public Logger getParentLogger() throws SQLFeatureNotSupportedException {
            throw new SQLFeatureNotSupportedException("Dedicated database logging is disabled");
        }

        @Override
        public int getLoginTimeout() {
            return LOGIN_TIMEOUT_SECONDS;
        }

        @Override
        public void setLoginTimeout(int seconds) throws SQLException {
            throw new SQLFeatureNotSupportedException("Dedicated database timeout is fixed");
        }

        @Override
        public boolean isWrapperFor(Class<?> type) {
            return type != null && type.isInstance(this);
        }

        @Override
        public <T> T unwrap(Class<T> type) throws SQLException {
            if (isWrapperFor(type)) return type.cast(this);
            throw new SQLFeatureNotSupportedException("Dedicated database wrapper is unavailable");
        }
    }
}
