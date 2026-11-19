package dev.udak.observe.jdbc;

import dev.udak.observe.Framework;
import dev.udak.observe.ObservationPoint;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.SqlObserver.PreparedObservation;
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
    private static final ProxyFactory<Connection> CONNECTION = new ProxyFactory<>(Connection.class);
    private static final ProxyFactory<Statement> STATEMENT = new ProxyFactory<>(Statement.class);
    private static final ProxyFactory<PreparedStatement> PREPARED = new ProxyFactory<>(PreparedStatement.class);
    private static final ProxyFactory<CallableStatement> CALLABLE = new ProxyFactory<>(CallableStatement.class);

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
        return CONNECTION.create((connection, method, args) -> switch (method.getName()) {
            case "equals", "hashCode", "toString" -> identity(connection, method, args, CONNECTION.label);
            case "unwrap", "isWrapperFor" -> wrapperMethod(target, connection, method, args);
            case "createStatement" -> wrapStatement(STATEMENT, (Statement) invoke(target, method, args),
                    (Connection) connection, null);
            case "prepareStatement" -> {
                String sql = (String) args[0];
                PreparedStatement result = args.length == 1 ? target.prepareStatement(sql)
                        : (PreparedStatement) invoke(target, method, args);
                yield wrapPreparedStatement(PREPARED, result, (Connection) connection, sql);
            }
            case "prepareCall" -> wrapPreparedStatement(CALLABLE,
                    (CallableStatement) invoke(target, method, args), (Connection) connection, (String) args[0]);
            case "close" -> {
                target.close();
                yield null;
            }
            default -> invoke(target, method, args);
        });
    }

    private <T extends PreparedStatement> T wrapPreparedStatement(ProxyFactory<T> factory, T target,
                                                                  Connection connection, String sql) {
        return target == null ? null : wrapStatement(factory, target, connection, observer.prepareJdbc(sql));
    }

    private <T extends Statement> T wrapStatement(ProxyFactory<T> factory, T target, Connection connection,
                                                  PreparedObservation prepared) {
        if (target == null) {
            return null;
        }
        return factory.create((statement, method, args) -> switch (method.getName()) {
            case "equals", "hashCode", "toString" -> identity(statement, method, args, factory.label);
            case "unwrap", "isWrapperFor" -> wrapperMethod(target, statement, method, args);
            case "getConnection" -> target.getConnection() == null ? null : connection;
            case "close" -> {
                target.close();
                yield null;
            }
            case "setQueryTimeout" -> {
                target.setQueryTimeout((int) args[0]);
                yield null;
            }
            case "setInt" -> {
                if (args[0] instanceof Integer index) {
                    ((PreparedStatement) target).setInt(index, (int) args[1]);
                    yield null;
                }
                // CallableStatement also accepts parameter names, including null passed to the driver.
                yield invoke(target, method, args);
            }
            case "executeQuery" -> {
                if (args == null) {
                    observer.observeJdbc(prepared);
                    yield ((PreparedStatement) target).executeQuery();
                }
                String sql = (String) args[0];
                observe(sql);
                yield target.executeQuery(sql);
            }
            case "execute", "executeUpdate", "executeLargeUpdate", "executeBatch", "executeLargeBatch" -> {
                if (args != null) {
                    observe((String) args[0]);
                } else if (prepared != null) {
                    observer.observeJdbc(prepared);
                }
                yield invoke(target, method, args);
            }
            default -> invoke(target, method, args);
        });
    }

    private void observe(String sql) {
        observer.observe(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, null, sql);
    }

    private static Object wrapperMethod(Object target, Object proxy, Method method, Object[] args) throws Throwable {
        if (args[0] instanceof Class<?> type && type.isInstance(proxy)) {
            return method.getName().equals("unwrap") ? proxy : true;
        }
        return invoke(target, method, args);
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

    private static final class ProxyFactory<T> {
        private final Class<T> type;
        private final Class<?>[] interfaces;
        private final String label;

        private ProxyFactory(Class<T> type) {
            this.type = type;
            interfaces = new Class<?>[] {type};
            label = "Observe" + type.getSimpleName();
        }

        private T create(InvocationHandler handler) {
            return type.cast(Proxy.newProxyInstance(type.getClassLoader(), interfaces, handler));
        }
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
