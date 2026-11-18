package dev.udak.observe.jdbc;

import dev.udak.observe.Framework;
import dev.udak.observe.ObservationPoint;
import dev.udak.observe.SqlObserver;
import java.io.PrintWriter;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.sql.CallableStatement;
import java.sql.Connection;
import java.sql.ConnectionBuilder;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.SQLFeatureNotSupportedException;
import java.sql.ShardingKeyBuilder;
import java.sql.Statement;
import java.util.Objects;
import java.util.logging.Logger;
import javax.sql.DataSource;

/**
 * Observes JDBC execution attempts through connections acquired with {@code getConnection}.
 * Wire this instance into the transaction manager and all clients sharing that transaction.
 * Driver-specific unwraps and directly delegated connection builders can bypass observation.
 * Plain Statement batches are delegated without collecting individual SQL strings.
 */
public final class ObserveDataSource implements DataSource {
    private final DataSource delegate;
    private final SqlObserver observer;

    public ObserveDataSource(DataSource delegate, SqlObserver observer) {
        this.delegate = Objects.requireNonNull(delegate, "delegate");
        this.observer = Objects.requireNonNull(observer, "observer");
    }

    @Override
    public Connection getConnection() throws SQLException {
        return wrapConnection(delegate.getConnection());
    }

    @Override
    public Connection getConnection(String username, String password) throws SQLException {
        return wrapConnection(delegate.getConnection(username, password));
    }

    private Connection wrapConnection(Connection target) {
        if (target == null) {
            return null;
        }
        return proxy(Connection.class, (connection, method, args) -> {
            if (method.getDeclaringClass() == Object.class) {
                return identity(connection, method, args, "ObserveConnection");
            }
            if (wrapsSelf(connection, method, args)) {
                return method.getName().equals("unwrap") ? connection : true;
            }
            Object result = invoke(target, method, args);
            if (result == null) {
                return null;
            }
            return switch (method.getName()) {
                case "createStatement" -> wrapStatement(Statement.class, (Statement) result,
                        (Connection) connection, null);
                case "prepareStatement" -> wrapStatement(PreparedStatement.class, (PreparedStatement) result,
                        (Connection) connection, (String) args[0]);
                case "prepareCall" -> wrapStatement(CallableStatement.class, (CallableStatement) result,
                        (Connection) connection, (String) args[0]);
                default -> result;
            };
        });
    }

    private <T extends Statement> T wrapStatement(Class<T> type, T target, Connection connection, String preparedSql) {
        return proxy(type, (statement, method, args) -> {
            if (method.getDeclaringClass() == Object.class) {
                return identity(statement, method, args, "Observe" + type.getSimpleName());
            }
            if (wrapsSelf(statement, method, args)) {
                return method.getName().equals("unwrap") ? statement : true;
            }

            switch (method.getName()) {
                case "execute", "executeQuery", "executeUpdate", "executeLargeUpdate", "executeBatch", "executeLargeBatch":
                    if (args != null) {
                        observe((String) args[0]);
                    } else if (type != Statement.class) {
                        observe(preparedSql);
                    }
                    break;
                default:
                    break;
            }

            Object result = invoke(target, method, args);
            if (method.getName().equals("getConnection") && result != null) {
                return connection;
            }
            return result;
        });
    }

    private void observe(String sql) {
        observer.observe(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, null, sql);
    }

    private static boolean wrapsSelf(Object proxy, Method method, Object[] args) {
        return (method.getName().equals("unwrap") || method.getName().equals("isWrapperFor"))
                && args[0] instanceof Class<?> type && type.isInstance(proxy);
    }

    private static Object identity(Object proxy, Method method, Object[] args, String name) {
        return switch (method.getName()) {
            case "equals" -> proxy == args[0];
            case "hashCode" -> System.identityHashCode(proxy);
            case "toString" -> name;
            default -> throw new AssertionError("Unexpected Object method");
        };
    }

    private static Object invoke(Object target, Method method, Object[] args) throws Throwable {
        try {
            return method.invoke(target, args);
        } catch (InvocationTargetException wrapper) {
            throw wrapper.getCause();
        }
    }

    private static <T> T proxy(Class<T> type, InvocationHandler handler) {
        return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[] {type}, handler));
    }

    @Override
    public <T> T unwrap(Class<T> type) throws SQLException {
        return type != null && type.isInstance(this) ? type.cast(this) : delegate.unwrap(type);
    }

    @Override
    public boolean isWrapperFor(Class<?> type) throws SQLException {
        return (type != null && type.isInstance(this)) || delegate.isWrapperFor(type);
    }

    @Override
    public PrintWriter getLogWriter() throws SQLException {
        return delegate.getLogWriter();
    }

    @Override
    public void setLogWriter(PrintWriter out) throws SQLException {
        delegate.setLogWriter(out);
    }

    @Override
    public void setLoginTimeout(int seconds) throws SQLException {
        delegate.setLoginTimeout(seconds);
    }

    @Override
    public int getLoginTimeout() throws SQLException {
        return delegate.getLoginTimeout();
    }

    @Override
    public Logger getParentLogger() throws SQLFeatureNotSupportedException {
        return delegate.getParentLogger();
    }

    @Override
    public ConnectionBuilder createConnectionBuilder() throws SQLException {
        return delegate.createConnectionBuilder();
    }

    @Override
    public ShardingKeyBuilder createShardingKeyBuilder() throws SQLException {
        return delegate.createShardingKeyBuilder();
    }
}
