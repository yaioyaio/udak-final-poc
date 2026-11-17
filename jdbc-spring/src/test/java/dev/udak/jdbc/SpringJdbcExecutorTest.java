package dev.udak.jdbc;

import dev.udak.api.CrudClient;
import dev.udak.api.TableDefinition;
import dev.udak.core.Bind;
import dev.udak.core.CompiledQuery;
import dev.udak.core.DbVendor;
import java.io.PrintWriter;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.SQLFeatureNotSupportedException;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.logging.Logger;
import javax.sql.DataSource;
import org.h2.jdbcx.JdbcDataSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.jdbc.datasource.ConnectionHolder;
import java.util.logging.Handler;
import java.util.logging.Level;
import java.util.logging.LogRecord;

public final class SpringJdbcExecutorTest {
    private static int checks;
    private static final DbVendor VENDOR = DbVendor.POSTGRESQL;
    private static CompiledQuery q(String sql, Object... values) {
        return new CompiledQuery(sql, java.util.Arrays.stream(values).map(v -> new Bind("value", v)).toList(), VENDOR);
    }
    private static void check(boolean ok) {
        checks++;
        if (!ok) throw new AssertionError("JDBC contract check failed: " + checks);
    }
    public static void main(String[] args) {
        JdbcDataSource h2 = new JdbcDataSource();
        h2.setURL("jdbc:h2:mem:udak_jdbc_contract;DB_CLOSE_DELAY=-1");
        Probe dataSource = new Probe(h2);
        JdbcTemplate raw = new JdbcTemplate(dataSource);
        raw.execute("CREATE TABLE sample (id INT, name VARCHAR(120))");
        SpringJdbcExecutor executor = new SpringJdbcExecutor(dataSource, VENDOR, 3, 100);
        CrudClient crud = new CrudClient(new TableDefinition("sample", List.of("id", "name"), "id"), VENDOR, executor);
        Map<String, Object> insert = new HashMap<>();
        insert.put("id", 1); insert.put("name", null);
        check(crud.insert(insert) == 1);
        check(crud.findById(1, (row, n) -> row.getObject("name") == null).orElseThrow());
        String input = "a' OR 1=1 --";
        check(crud.updateById(1, Map.of("name", input)) == 1);
        check(crud.findById(1, (row, n) -> row.getString("name")).orElseThrow().equals(input));
        check(crud.findById(9, (row, n) -> row.getInt("id")).isEmpty());
        check(crud.deleteById(1) == 1);
        executor.update(q("INSERT INTO sample (id, name) VALUES (?, ?)", 7, "one"));
        executor.update(q("INSERT INTO sample (id, name) VALUES (?, ?)", 7, "two"));
        try { crud.findById(7, (row, n) -> row.getInt("id")); throw new AssertionError(); }
        catch (IllegalStateException expected) { check(true); }
        SpringJdbcExecutor singleRowExecutor = new SpringJdbcExecutor(dataSource, VENDOR, 3, 1);
        CrudClient singleRowCrud = new CrudClient(new TableDefinition("sample", List.of("id", "name"), "id"), VENDOR, singleRowExecutor);
        try { singleRowCrud.findById(7, (row, n) -> row.getInt("id")); throw new AssertionError(); }
        catch (SpringJdbcExecutor.SafeJdbcException expected) { check(expected.getCause() == null); }
        try { singleRowExecutor.query(q("SELECT id FROM sample"), (row, n) -> row.getInt("id")); throw new AssertionError(); }
        catch (SpringJdbcExecutor.SafeJdbcException expected) { check(expected.getCause() == null); }
        check(dataSource.connectionsOpened == dataSource.connectionsClosed);
        check(dataSource.statementsOpened == dataSource.statementsClosed);
        check(dataSource.resultsOpened == dataSource.resultsClosed);
        check(crud.deleteById(7) == 2);
        TransactionTemplate tx = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
        tx.executeWithoutResult(status -> {
            executor.update(q("INSERT INTO sample (id, name) VALUES (?, ?)", 2, "commit"));
            raw.update("INSERT INTO sample (id, name) VALUES (?, ?)", 3, "commit");
        });
        check(raw.queryForObject("SELECT COUNT(*) FROM sample", Integer.class) == 2);
        tx.executeWithoutResult(status -> {
            executor.update(q("INSERT INTO sample (id, name) VALUES (?, ?)", 4, "rollback"));
            raw.update("INSERT INTO sample (id, name) VALUES (?, ?)", 5, "rollback");
            status.setRollbackOnly();
        });
        check(raw.queryForObject("SELECT COUNT(*) FROM sample", Integer.class) == 2);
        TransactionTemplate timed = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
        timed.setTimeout(1);
        timed.executeWithoutResult(status -> executor.query(q("SELECT id FROM sample"), (row, n) -> row.getInt("id")));
        check(dataSource.timeoutSeen == 1);
        try {
            tx.executeWithoutResult(status -> {
                executor.update(q("INSERT INTO sample (id, name) VALUES (?, ?)", 6, "expired"));
                ConnectionHolder holder = (ConnectionHolder) TransactionSynchronizationManager.getResource(dataSource);
                holder.setTimeoutInMillis(0);
                executor.query(q("SELECT id FROM sample"), (row, n) -> row.getInt("id"));
            });
            throw new AssertionError();
        } catch (SpringJdbcExecutor.SafeJdbcException expected) { check(expected.getCause() == null); }
        check(raw.queryForObject("SELECT COUNT(*) FROM sample", Integer.class) == 2);
        try {
            tx.executeWithoutResult(status -> {
                executor.update(q("INSERT INTO sample (id, name) VALUES (?, ?)", 8, "automatic"));
                executor.update(q("INSERT INTO absent_table (id) VALUES (?)", 8));
            });
            throw new AssertionError();
        } catch (SpringJdbcExecutor.SafeJdbcException expected) { check(expected.getCause() == null); }
        check(raw.queryForObject("SELECT COUNT(*) FROM sample", Integer.class) == 2);
        Logger springLog = Logger.getLogger("org.springframework.jdbc.datasource.DataSourceUtils");
        Level oldLevel = springLog.getLevel();
        boolean oldParent = springLog.getUseParentHandlers();
        final boolean[] leaked = {false};
        Handler capture = new Handler() {
            @Override public void publish(LogRecord record) {
                String message = record.getMessage();
                Throwable thrown = record.getThrown();
                if ((message != null && message.contains("synthetic-close-sentinel")) ||
                    (thrown != null && thrown.toString().contains("synthetic-close-sentinel"))) leaked[0] = true;
            }
            @Override public void flush() { }
            @Override public void close() { }
        };
        capture.setLevel(Level.ALL);
        springLog.addHandler(capture); springLog.setLevel(Level.ALL); springLog.setUseParentHandlers(false);
        try {
            dataSource.failNextClose = true;
            try { executor.update(q("UPDATE sample SET name = ? WHERE id = ?", "safe", -1)); throw new AssertionError(); }
            catch (SpringJdbcExecutor.SafeJdbcException expected) { check(expected.getCause() == null); }
            check(!leaked[0]);
        } finally {
            springLog.removeHandler(capture); springLog.setLevel(oldLevel); springLog.setUseParentHandlers(oldParent);
        }
        try { executor.update(new CompiledQuery("SELECT 1", List.of(), DbVendor.MYSQL)); throw new AssertionError(); }
        catch (IllegalArgumentException expected) { check(true); }
        try { executor.query(q("SELECT ? FROM absent_table", "private-bind"), (row, n) -> row.getString(1)); throw new AssertionError(); }
        catch (SpringJdbcExecutor.SafeJdbcException expected) {
            check(expected.getCause() == null && expected.getMessage().equals("JDBC operation failed"));
            check(!expected.toString().contains("private-bind") && !expected.toString().contains("absent_table"));
        }
        try { executor.query(q("SELECT id FROM sample"), (row, n) -> { throw new SQLException("private-mapper"); }); throw new AssertionError(); }
        catch (SpringJdbcExecutor.SafeJdbcException expected) { check(expected.getCause() == null && !expected.toString().contains("private-mapper")); }
        try { executor.query(q("SELECT id FROM sample"), (row, n) -> null); throw new AssertionError(); }
        catch (SpringJdbcExecutor.SafeJdbcException expected) { check(expected.getCause() == null); }
        try { executor.query(q("SELECT id FROM sample"), null); throw new AssertionError(); }
        catch (NullPointerException expected) { check(true); }
        try { new SpringJdbcExecutor(dataSource, VENDOR, 31, 100); throw new AssertionError(); }
        catch (IllegalArgumentException expected) { check(true); }
        try { new SpringJdbcExecutor(dataSource, VENDOR, 3, 1001); throw new AssertionError(); }
        catch (IllegalArgumentException expected) { check(true); }
        check(dataSource.timeoutSeen == 3);
        check(dataSource.connectionsOpened == dataSource.connectionsClosed);
        check(dataSource.statementsOpened == dataSource.statementsClosed);
        check(dataSource.resultsOpened == dataSource.resultsClosed);
        System.out.println("JDBC contract checks: " + checks);
    }

    private static final class Probe implements DataSource {
        private final DataSource delegate;
        int connectionsOpened, connectionsClosed, statementsOpened, statementsClosed, resultsOpened, resultsClosed, timeoutSeen;
        boolean failNextClose;
        Probe(DataSource delegate) { this.delegate = delegate; }
        private Object wrap(Object target, Class<?> type) {
            return Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, (proxy, method, args) -> {
                if (method.getName().equals("close")) {
                    if (type == Connection.class) connectionsClosed++;
                    if (type == PreparedStatement.class) statementsClosed++;
                    if (type == ResultSet.class) resultsClosed++;
                }
                if (type == PreparedStatement.class && method.getName().equals("setQueryTimeout")) timeoutSeen = (Integer) args[0];
                try {
                    Object value = method.invoke(target, args);
                    if (type == Connection.class && method.getName().equals("close") && failNextClose) {
                        failNextClose = false;
                        throw new SQLException("synthetic-close-sentinel");
                    }
                    if (type == Connection.class && method.getName().equals("prepareStatement") && value instanceof PreparedStatement) {
                        statementsOpened++; return wrap(value, PreparedStatement.class);
                    }
                    if (type == PreparedStatement.class && method.getName().equals("executeQuery") && value instanceof ResultSet) {
                        resultsOpened++; return wrap(value, ResultSet.class);
                    }
                    return value;
                } catch (InvocationTargetException e) { throw e.getCause(); }
            });
        }
        public Connection getConnection() throws SQLException { connectionsOpened++; return (Connection) wrap(delegate.getConnection(), Connection.class); }
        public Connection getConnection(String user, String password) throws SQLException { connectionsOpened++; return (Connection) wrap(delegate.getConnection(user, password), Connection.class); }
        public PrintWriter getLogWriter() throws SQLException { return delegate.getLogWriter(); }
        public void setLogWriter(PrintWriter out) throws SQLException { delegate.setLogWriter(out); }
        public void setLoginTimeout(int seconds) throws SQLException { delegate.setLoginTimeout(seconds); }
        public int getLoginTimeout() throws SQLException { return delegate.getLoginTimeout(); }
        public Logger getParentLogger() throws SQLFeatureNotSupportedException { return delegate.getParentLogger(); }
        public <T> T unwrap(Class<T> type) throws SQLException { return delegate.unwrap(type); }
        public boolean isWrapperFor(Class<?> type) throws SQLException { return delegate.isWrapperFor(type); }
    }
}
