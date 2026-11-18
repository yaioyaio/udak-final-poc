package dev.udak.rewrite.testkit;

import dev.udak.rewrite.Rewrite;
import dev.udak.rewrite.Rewrite.Dialect;
import dev.udak.rewrite.Rewrite.Environment;
import dev.udak.rewrite.testkit.RewriteEquivalenceTest.Failure;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.List;
import java.util.Locale;
import javax.sql.DataSource;

final class RewriteFixture implements AutoCloseable {
    static final String TABLE = "udak_p5_entry";
    static final int QUERY_TIMEOUT_SECONDS = 5;
    private static final String INSERT = "INSERT INTO " + TABLE + " (id, name, status) VALUES (?, ?, ?)";
    private static final List<Entry> ENTRIES = List.of(new Entry(50, "echo", "active"),
            new Entry(15, "other-one", "other"), new Entry(20, null, "active"),
            new Entry(40, "delta", "active"), new Entry(60, "null-status", null),
            new Entry(10, "alpha", "active"), new Entry(35, "other-two", "other"),
            new Entry(30, "charlie", "active"));

    private final Environment environment;
    private final DataSource source;
    private Connection owner;
    private boolean created;

    RewriteFixture(DataSource source, Environment environment) {
        this.source = source;
        this.environment = environment;
    }

    void create() throws SQLException {
        // Retain the owner connection across probes so H2 can use its ordinary in-memory lifetime.
        owner = source.getConnection();
        if (!owner.getAutoCommit()) throw new Failure("FIXTURE_AUTOCOMMIT_REQUIRED");
        if (!matchesDatabase(owner.getMetaData())) throw new Failure("FIXTURE_IDENTITY_MISMATCH");
        if (exists()) throw new Failure("PREEXISTING_FIXTURE");
        String varchar = environment.target() == Dialect.ORACLE ? "VARCHAR2" : "VARCHAR";
        update(owner, "CREATE TABLE " + TABLE + " (id INTEGER PRIMARY KEY, name " + varchar + "(80), status "
                + varchar + "(16))", true);
        if (!exists()) throw new Failure("FIXTURE_CREATION_UNCONFIRMED");
        for (Entry entry : ENTRIES) {
            if (insert(owner, entry.id(), entry.name(), entry.status()) != 1) {
                throw new Failure("FIXTURE_INSERT_UNCONFIRMED");
            }
        }
    }

    static int insert(Connection connection, int id, String name, String status) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(INSERT)) {
            statement.setQueryTimeout(QUERY_TIMEOUT_SECONDS);
            statement.setInt(1, id);
            statement.setString(2, name);
            statement.setString(3, status);
            return statement.executeUpdate();
        }
    }

    private void update(Connection connection, String ddl, boolean ownershipAfterSuccess) throws SQLException {
        try (Statement statement = connection.createStatement()) {
            statement.setQueryTimeout(QUERY_TIMEOUT_SECONDS);
            statement.executeUpdate(ddl);
            // Only our own successful plain CREATE grants ownership of the fixture.
            created = ownershipAfterSuccess;
        }
    }

    private boolean matchesDatabase(DatabaseMetaData metadata) throws SQLException {
        String product = switch (environment.target()) {
            case H2 -> "H2";
            case POSTGRESQL -> "PostgreSQL";
            case MYSQL -> "MySQL";
            case SQLSERVER -> "Microsoft SQL Server";
            case ORACLE -> "Oracle";
        };
        return product.equals(metadata.getDatabaseProductName())
                && environment.targetVersion().equals(Rewrite.fingerprint(metadata.getDatabaseProductVersion()))
                && environment.driverVersion().equals(Rewrite.fingerprint(metadata.getDriverVersion()));
    }

    private boolean exists() throws SQLException {
        DatabaseMetaData metadata = owner.getMetaData();
        for (String pattern : List.of(TABLE, TABLE.toUpperCase(Locale.ROOT))) {
            // Preserve a matching object in any visible schema, including views.
            try (ResultSet tables = metadata.getTables(null, null, pattern, null)) {
                while (tables.next()) {
                    if (TABLE.equalsIgnoreCase(tables.getString("TABLE_NAME"))) return true;
                }
            }
        }
        return false;
    }

    @Override
    public void close() {
        if (owner == null) return;
        try (Connection connection = owner) {
            if (created) {
                String suffix = environment.target() == Dialect.ORACLE ? " PURGE" : "";
                update(connection, "DROP TABLE " + TABLE + suffix, false);
                if (exists()) throw new Failure("FIXTURE_CLEANUP_UNCONFIRMED");
            }
        } catch (SQLException | RuntimeException failure) {
            if (failure instanceof Failure safe) throw safe;
            throw new Failure("FIXTURE_CLEANUP_FAILED", failure);
        }
    }

    private record Entry(int id, String name, String status) {}
}
