package dev.udak.rewrite.jdbc;

import dev.udak.rewrite.Rewrite;
import dev.udak.rewrite.Rewrite.Code;
import dev.udak.rewrite.Rewrite.Denied;
import dev.udak.rewrite.Rewrite.Environment;
import dev.udak.rewrite.Rewrite.Plan;
import dev.udak.rewrite.Rewrite.Provider;
import dev.udak.rewrite.Rewrite.Registry;
import dev.udak.rewrite.Rewrite.Role;
import dev.udak.rewrite.Rewrite.Template;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import javax.sql.DataSource;
import org.springframework.jdbc.datasource.DataSourceUtils;

/** A caller-selected, approval-gated SELECT entry point for one Spring DataSource. */
public final class SelectiveJdbcClient {
    private static final int QUERY_TIMEOUT_SECONDS = 5;
    private static final int MAX_LIMIT = 1_000;

    private final DataSource dataSource;
    private final Environment environment;
    private final Registry registry;
    private final Provider provider;

    public SelectiveJdbcClient(DataSource dataSource, Environment environment, Registry registry, Provider provider) {
        this.dataSource = Objects.requireNonNull(dataSource, "dataSource");
        this.environment = Objects.requireNonNull(environment, "environment");
        this.registry = Objects.requireNonNull(registry, "registry");
        this.provider = Objects.requireNonNull(provider, "provider");
    }

    /** A valid filter may be null, with the SQL semantics of equality to a null bind. */
    public record Parameters(String filter, int limit, int offset) {
        public Parameters {
            if ((filter != null && filter.length() > 1_024) || limit < 1 || limit > MAX_LIMIT
                    || offset < 0 || offset > 1_000_000) {
                throw new IllegalArgumentException("Invalid SELECT parameters");
            }
        }

        @Override
        public String toString() {
            return "Parameters[redacted]";
        }
    }

    @FunctionalInterface
    public interface RowMapper<T> {
        T map(ResultSet rows, int rowNumber) throws SQLException;
    }

    public <T> List<T> query(Template template, Parameters parameters, RowMapper<T> mapper) {
        Objects.requireNonNull(template, "template");
        Objects.requireNonNull(parameters, "parameters");
        Objects.requireNonNull(mapper, "mapper");
        if (!environment.equals(template.environment())) {
            throw new Denied(Code.MISMATCH);
        }
        try {
            return registry.withApproved(template, provider, plan -> execute(plan, parameters, mapper));
        } catch (Denied denial) {
            throw new Denied(denial.code());
        } catch (Throwable failure) {
            throw safeFailure(failure);
        }
    }

    private <T> List<T> execute(Plan plan, Parameters parameters, RowMapper<T> mapper) {
        final Connection connection;
        try {
            connection = DataSourceUtils.getConnection(dataSource);
        } catch (Throwable failure) {
            throw safeFailure(failure);
        }
        try (ConnectionRelease release = () -> release(connection)) {
            if (!matchesTarget(connection)) {
                throw new Denied(Code.MISMATCH);
            }
            try (PreparedStatement statement = connection.prepareStatement(plan.sql())) {
                configure(statement, plan, parameters);
                try (ResultSet rows = statement.executeQuery()) {
                    verifyLabels(rows.getMetaData(), plan.columns());
                    List<T> result = new ArrayList<>();
                    while (rows.next()) {
                        if (result.size() == parameters.limit()) {
                            throw new SafeJdbcException();
                        }
                        result.add(Objects.requireNonNull(mapper.map(rows, result.size()), "Mapper returned null"));
                    }
                    return List.copyOf(result);
                }
            } catch (Throwable failure) {
                throw safeFailure(failure);
            }
        }
    }

    @FunctionalInterface
    private interface ConnectionRelease extends AutoCloseable {
        @Override void close();
    }

    private void release(Connection connection) {
        try {
            // This variant releases Spring-owned references without logging close errors.
            DataSourceUtils.doReleaseConnection(connection, dataSource);
        } catch (Throwable failure) {
            throw safeFailure(failure);
        }
    }

    private boolean matchesTarget(Connection connection) {
        String product = switch (environment.target()) {
            case H2 -> "H2";
            case POSTGRESQL -> "PostgreSQL";
            case MYSQL -> "MySQL";
            case SQLSERVER -> "Microsoft SQL Server";
            case ORACLE -> "Oracle";
        };
        try {
            DatabaseMetaData metadata = connection.getMetaData();
            return product.equals(metadata.getDatabaseProductName())
                    && environment.targetVersion().equals(Rewrite.fingerprint(metadata.getDatabaseProductVersion()))
                    && environment.driverVersion().equals(Rewrite.fingerprint(metadata.getDriverVersion()));
        } catch (Throwable failure) {
            throw safeFailure(failure);
        }
    }

    private static SafeJdbcException safeFailure(Throwable failure) {
        if (failure instanceof VirtualMachineError fatal) throw fatal;
        if (failure instanceof ThreadDeath fatal) throw fatal;
        return new SafeJdbcException();
    }

    private void configure(PreparedStatement statement, Plan plan, Parameters parameters) throws SQLException {
        int index = 1;
        for (Role role : plan.bindOrder()) {
            switch (role) {
                case FILTER -> statement.setString(index, parameters.filter());
                case LIMIT -> statement.setInt(index, parameters.limit());
                case OFFSET -> statement.setInt(index, parameters.offset());
            }
            index++;
        }
        statement.setMaxRows(MAX_LIMIT + 1);
        DataSourceUtils.applyTimeout(statement, dataSource, QUERY_TIMEOUT_SECONDS);
        int timeout = statement.getQueryTimeout();
        if (timeout == 0 || timeout > QUERY_TIMEOUT_SECONDS) {
            statement.setQueryTimeout(QUERY_TIMEOUT_SECONDS);
        }
    }

    private static void verifyLabels(ResultSetMetaData metadata, List<String> columns) throws SQLException {
        if (metadata.getColumnCount() != columns.size()) {
            throw new SafeJdbcException();
        }
        for (int index = 0; index < columns.size(); index++) {
            String label = metadata.getColumnLabel(index + 1);
            if (!columns.get(index).equals(label)) {
                throw new SafeJdbcException();
            }
        }
    }

    /** Carries no SQL, arguments, driver error, or mapper error. */
    public static final class SafeJdbcException extends RuntimeException {
        private static final long serialVersionUID = 1L;

        private SafeJdbcException() {
            super("Approved JDBC query failed", null, false, true);
        }
    }
}
