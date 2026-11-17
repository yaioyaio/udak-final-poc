package dev.udak.jdbc;

import dev.udak.api.RowMapper;
import dev.udak.api.SqlExecutor;
import dev.udak.core.Bind;
import dev.udak.core.CompiledQuery;
import dev.udak.core.DbVendor;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import javax.sql.DataSource;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.datasource.DataSourceUtils;

/** Executes trusted compiler output using the externally supplied Spring-managed DataSource. */
public final class SpringJdbcExecutor implements SqlExecutor {
    private final DataSource dataSource;
    private final DbVendor vendor;
    private final int timeoutSeconds;
    private final int maxRows;

    public SpringJdbcExecutor(DataSource dataSource, DbVendor vendor) {
        this(dataSource, vendor, 5, 1000);
    }

    public SpringJdbcExecutor(DataSource dataSource, DbVendor vendor, int queryTimeoutSeconds) {
        this(dataSource, vendor, queryTimeoutSeconds, 1000);
    }

    public SpringJdbcExecutor(DataSource dataSource, DbVendor vendor, int queryTimeoutSeconds, int maxRows) {
        this.dataSource = Objects.requireNonNull(dataSource, "dataSource");
        this.vendor = Objects.requireNonNull(vendor, "vendor");
        if (queryTimeoutSeconds < 1 || queryTimeoutSeconds > 30 || maxRows < 1 || maxRows > 1000) {
            throw new IllegalArgumentException("Invalid execution limits");
        }
        this.timeoutSeconds = queryTimeoutSeconds;
        this.maxRows = maxRows;
    }

    @Override
    public <T> List<T> query(CompiledQuery query, RowMapper<T> mapper) {
        validate(query);
        Objects.requireNonNull(mapper, "mapper");
        try {
            return execute(connection -> {
                try (PreparedStatement statement = connection.prepareStatement(query.sql())) {
                    configure(statement, query);
                    try (ResultSet rows = statement.executeQuery()) {
                        List<T> result = new ArrayList<>();
                        int rowNum = 0;
                        while (rows.next()) {
                            // Enforce the bound even for a driver that ignores setMaxRows.
                            if (rowNum >= maxRows) throw new SQLException("Row limit exceeded");
                            result.add(Objects.requireNonNull(mapper.map(rows, rowNum++), "Mapper returned null"));
                        }
                        return result;
                    }
                } catch (SQLException ex) {
                    // Do not pass driver messages through Spring's SQLException translator/loggers.
                    throw new SafeJdbcException();
                }
            });
        } catch (RuntimeException ex) {
            throw new SafeJdbcException();
        }
    }

    @Override
    public int update(CompiledQuery query) {
        validate(query);
        try {
            Integer count = execute(connection -> {
                try (PreparedStatement statement = connection.prepareStatement(query.sql())) {
                    configure(statement, query);
                    return statement.executeUpdate();
                } catch (SQLException ex) {
                    throw new SafeJdbcException();
                }
            });
            return count;
        } catch (RuntimeException ex) {
            throw new SafeJdbcException();
        }
    }

    @FunctionalInterface
    private interface ConnectionOperation<T> {
        T apply(Connection connection);
    }

    private <T> T execute(ConnectionOperation<T> operation) {
        Connection connection = null;
        try {
            connection = DataSourceUtils.getConnection(dataSource);
            return operation.apply(connection);
        } catch (RuntimeException ex) {
            throw new SafeJdbcException();
        } finally {
            if (connection != null) {
                try {
                    // Unlike releaseConnection, this variant does not log close failures.
                    DataSourceUtils.doReleaseConnection(connection, dataSource);
                } catch (SQLException | RuntimeException ex) {
                    throw new SafeJdbcException();
                }
            }
        }
    }

    private void validate(CompiledQuery query) {
        Objects.requireNonNull(query, "query");
        if (query.vendor() != vendor) throw new IllegalArgumentException("Vendor mismatch");
    }

    private void configure(PreparedStatement statement, CompiledQuery query) throws SQLException {
        // Avoid Spring's StatementCreatorUtils, whose TRACE output can include parameter values.
        int index = 1;
        for (Bind bind : query.binds()) statement.setObject(index++, bind.value());
        // Request one sentinel row so exceeding the contract fails instead of truncating.
        statement.setMaxRows(maxRows + 1);
        // Spring applies the current transaction deadline, if any.
        DataSourceUtils.applyTimeout(statement, dataSource, timeoutSeconds);
        int effectiveTimeout = statement.getQueryTimeout();
        if (effectiveTimeout == 0 || effectiveTimeout > timeoutSeconds) {
            statement.setQueryTimeout(timeoutSeconds);
        }
    }

    /** No SQL, parameter, connection or original cause is retained. */
    public static final class SafeJdbcException extends DataAccessException {
        private SafeJdbcException() { super("JDBC operation failed"); }
    }
}
