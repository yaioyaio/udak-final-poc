package dev.udak.rewrite.testkit;

import java.lang.reflect.InvocationHandler;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import javax.sql.DataSource;
import org.springframework.jdbc.datasource.AbstractDataSource;

/** Records only the owned fixture's JDBC calls in memory. */
final class JdbcProbe extends AbstractDataSource {
    private final DataSource delegate;
    private final List<Bind> binds = new ArrayList<>();
    private int connections;
    private int prepares;
    private int closed;
    private String sql;
    private Connection preparedOn;

    JdbcProbe(DataSource delegate) {
        this.delegate = delegate;
    }

    @Override
    public Connection getConnection() throws SQLException {
        Connection connection = delegate.getConnection();
        connections++;
        return proxy(Connection.class, (self, method, args) -> {
            if (method.getName().equals("prepareStatement")) {
                prepares++;
                sql = (String) args[0];
                preparedOn = (Connection) self;
                binds.clear();
                return statement((PreparedStatement) invoke(connection, method, args));
            }
            if (method.getName().equals("close")) closed++;
            return invoke(connection, method, args);
        });
    }

    @Override
    public Connection getConnection(String username, String password) throws SQLException {
        throw new SQLException("Unexpected credential overload");
    }

    private PreparedStatement statement(PreparedStatement statement) {
        return proxy(PreparedStatement.class, (self, method, args) -> {
            if (method.getName().equals("setString") || method.getName().equals("setInt")) {
                binds.add(new Bind(method.getName(), (int) args[0], args[1]));
            }
            return invoke(statement, method, args);
        });
    }

    private static Object invoke(Object target, Method method, Object[] args) throws Throwable {
        try {
            return method.invoke(target, args);
        } catch (InvocationTargetException failure) {
            throw failure.getCause();
        }
    }

    private static <T> T proxy(Class<T> type, InvocationHandler handler) {
        return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, (self, method, args) ->
                switch (method.getName()) {
                    case "toString" -> "Fixture JDBC probe";
                    case "equals" -> self == args[0];
                    case "hashCode" -> System.identityHashCode(self);
                    default -> handler.invoke(self, method, args);
                }));
    }

    record Bind(String method, int index, Object value) {}

    int connections() { return connections; }
    int prepares() { return prepares; }
    int closed() { return closed; }
    String sql() { return sql; }
    Connection preparedOn() { return preparedOn; }
    List<Bind> binds() { return List.copyOf(binds); }
}
