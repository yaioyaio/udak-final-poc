package dev.udak.observe;

import dev.udak.observe.hibernate.HibernateObserveInspector;
import dev.udak.observe.jdbc.ObserveDataSource;
import dev.udak.observe.mybatis.MyBatisObserveInterceptor;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.CallableStatement;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import javax.sql.DataSource;
import org.apache.ibatis.cache.CacheKey;
import org.apache.ibatis.executor.Executor;
import org.apache.ibatis.executor.statement.StatementHandler;
import org.apache.ibatis.mapping.BoundSql;
import org.apache.ibatis.mapping.MappedStatement;
import org.apache.ibatis.mapping.ParameterMapping;
import org.apache.ibatis.mapping.ResultMap;
import org.apache.ibatis.mapping.SqlCommandType;
import org.apache.ibatis.session.Configuration;
import org.apache.ibatis.session.ResultHandler;
import org.apache.ibatis.session.RowBounds;

public final class LegacyObserveAdapterContractTest {
    private static int checks;

    private LegacyObserveAdapterContractTest() { }

    public static void main(String[] args) throws Exception {
        hibernateContract();
        hibernateCompositionContract();
        myBatisContract();
        jdbcContract();
        jdbcPreparedHotPathContract();
        jdbcQueryOverloadContract();
        System.out.println("Legacy Observe adapter contract checks: " + checks);
    }

    private static void hibernateContract() {
        List<SqlObservation> events = new ArrayList<>();
        HibernateObserveInspector inspector = new HibernateObserveInspector(new SqlObserver(events::add));
        String sql = new String("select 'synthetic-jpa-value'");
        same(sql, inspector.inspect(sql), "Hibernate retains original SQL reference");
        same(null, inspector.inspect(null), "Hibernate retains null SQL");
        check(events.size() == 2, "Hibernate records both inspections");
        observation(events.get(0), Framework.JPA, ObservationPoint.JPA_INSPECT);
        check(events.get(1).fingerprintStatus() == FingerprintStatus.UNAVAILABLE, "Hibernate null metadata");
        check(!events.get(0).toString().contains("synthetic-jpa-value"), "Hibernate event omits SQL literal");

        HibernateObserveInspector failing = new HibernateObserveInspector(failingObserver());
        same(sql, failing.inspect(sql), "Hibernate isolates listener failure");
    }

    private static void hibernateCompositionContract() {
        String sql = new String("select name from sample where id = ?");
        String replacement = new String("select name from sample where id = ? and enabled = ?");
        String empty = new String("");
        List<SqlObservation> expected = new ArrayList<>();
        HibernateObserveInspector baseline = new HibernateObserveInspector(new SqlObserver(expected::add));
        baseline.inspect(sql);
        baseline.inspect(replacement);
        baseline.inspect(empty);
        check(!expected.get(0).fingerprintHash().equals(expected.get(1).fingerprintHash()),
                "Hibernate composition fixture has different original and replacement shapes");

        List<SqlObservation> events = new ArrayList<>();
        List<String> calls = new ArrayList<>();
        SqlObserver observer = new SqlObserver(event -> {
            check(calls.size() == events.size() + 1, "Hibernate calls existing inspector before observing");
            events.add(event);
        });
        HibernateObserveInspector composed = HibernateObserveInspector.compose(input -> {
            calls.add(input);
            return switch (calls.size()) {
                case 1 -> null;
                case 2 -> replacement;
                default -> empty;
            };
        }, observer);
        same(null, composed.inspect(sql), "Hibernate preserves existing inspector's null return");
        same(replacement, composed.inspect(sql), "Hibernate preserves existing inspector's replacement reference");
        same(empty, composed.inspect(sql), "Hibernate preserves existing inspector's empty replacement reference");
        check(calls.size() == 3, "Hibernate calls existing inspector exactly once per inspection");
        for (String call : calls) {
            same(sql, call, "Hibernate passes original SQL reference to existing inspector");
        }
        check(events.equals(expected), "Hibernate emits one event per effective SQL");

        RuntimeException failure = new IllegalStateException();
        HibernateObserveInspector throwing = HibernateObserveInspector.compose(input -> {
            calls.add(input);
            throw failure;
        }, observer);
        try {
            throwing.inspect(sql);
            throw new AssertionError("Expected existing inspector failure");
        } catch (RuntimeException actual) {
            same(failure, actual, "Hibernate preserves existing inspector exception identity");
        }
        check(calls.size() == 4, "Hibernate does not retry the failed existing inspector");
        check(events.size() == 3, "Hibernate emits no event when existing inspector fails");

        HibernateObserveInspector failing = HibernateObserveInspector.compose(input -> replacement, failingObserver());
        same(replacement, failing.inspect(sql), "Hibernate preserves replacement when observation fails");
        try {
            HibernateObserveInspector.compose(null, observer);
            throw new AssertionError("Expected null existing inspector rejection");
        } catch (NullPointerException expectedFailure) {
            check(true, "Hibernate composition rejects a null existing inspector");
        }
    }

    private static void myBatisContract() throws Exception {
        MyBatisProbe probe = new MyBatisProbe();
        same(probe.rows, probe.executor.query(probe.outer, probe.parameter, probe.bounds, probe.resultHandler),
                "MyBatis preserves query result");
        check(probe.events.size() == 4, "MyBatis records the four prepare calls");
        String outerHash = hashQueryId(probe.outer.getId());
        String innerHash = hashQueryId(probe.inner.getId());
        check(probe.events.get(0).queryIdHash().equals(outerHash), "MyBatis outer mapped ID");
        check(probe.events.get(1).queryIdHash().equals(innerHash), "MyBatis nested mapped ID");
        check(probe.events.get(2).queryIdHash().equals(outerHash), "MyBatis restores mapped ID after error");
        check(!probe.events.get(3).queryIdHash().equals(outerHash), "MyBatis thread context is isolated");
        for (SqlObservation event : probe.events) {
            observation(event, Framework.MYBATIS, ObservationPoint.MYBATIS_PREPARE);
            check(event.fingerprintHash().equals(probe.events.get(0).fingerprintHash()),
                    "MyBatis fingerprints already-built BoundSql");
        }

        same(probe.statement, probe.handler.prepare(probe.connection, probe.timeout), "MyBatis standalone prepare");
        check(probe.events.get(4).queryIdHash().equals(probe.events.get(3).queryIdHash()),
                "MyBatis clears thread context after query");
        probe.cacheHit = true;
        same(probe.rows, probe.executor.query(probe.outer, probe.parameter, probe.bounds, probe.resultHandler),
                "MyBatis preserves cached result");
        check(probe.events.size() == 5, "MyBatis cache hit has no prepare event");
        check(probe.executor.update(probe.update, probe.parameter) == 2, "MyBatis preserves update count");
        check(probe.events.get(5).queryIdHash().equals(hashQueryId(probe.update.getId())), "MyBatis update ID");
        check(probe.prepareCalls == 6 && probe.boundSqlReads == 6, "MyBatis delegates prepare and reads metadata once");

        probe.metadataFailure = true;
        same(probe.statement, probe.handler.prepare(probe.connection, probe.timeout), "MyBatis isolates metadata failure");
        check(probe.events.size() == 6 && probe.prepareCalls == 7, "MyBatis metadata failure still runs prepare once");
        probe.failure = new SQLException("synthetic-prepare-failure");
        expectSqlFailure(probe.failure, () -> probe.handler.prepare(probe.connection, probe.timeout));
        check(probe.prepareCalls == 8, "MyBatis does not retry prepare failure");
        check(probe.sqlEvaluations == 0, "MyBatis observer never asks MappedStatement to evaluate SQL");
        same(probe.sql, probe.boundSql.getSql(), "MyBatis preserves BoundSql SQL reference");
        same(probe.parameter, probe.boundSql.getParameterObject(), "MyBatis preserves parameters");
        same(probe.parameter, probe.boundSql.getAdditionalParameter("sample"), "MyBatis preserves additional parameters");
        same(probe.mapping, probe.boundSql.getParameterMappings().get(0), "MyBatis preserves parameter mappings");
        same(probe.resultMap, probe.outer.getResultMaps().get(0), "MyBatis preserves result map");
        check(probe.cacheKey.equals(new CacheKey(new Object[] {"synthetic-cache-key", 7})), "MyBatis preserves cache key");
    }

    private static void jdbcContract() throws Exception {
        JdbcProbe driver = new JdbcProbe();
        List<SqlObservation> events = new ArrayList<>();
        DataSource dataSource = new ObserveDataSource(driver.dataSource, new SqlObserver(events::add));
        Connection connection = dataSource.getConnection();
        check(connection != driver.connection, "JDBC wraps the connection");
        same(dataSource, dataSource.unwrap(DataSource.class), "JDBC standard DataSource unwrap stays observed");
        same(connection, connection.unwrap(Connection.class), "JDBC standard connection unwrap stays observed");
        check(connection.isWrapperFor(Connection.class), "JDBC standard connection wrapper check");
        same(driver.vendor, connection.unwrap(VendorHandle.class), "JDBC delegates vendor unwrap");
        check(connection.isWrapperFor(VendorHandle.class), "JDBC delegates vendor wrapper check");
        check(connection.equals(connection) && !connection.equals(driver.connection), "JDBC connection identity equality");
        check(connection.hashCode() == System.identityHashCode(connection), "JDBC connection identity hash");
        check(connection.toString().equals("ObserveConnection"), "JDBC connection string omits delegate details");

        String update = new String("update sample set value = ? where id = ?");
        String[] generatedColumns = {"id"};
        PreparedStatement prepared = connection.prepareStatement(update, generatedColumns);
        call(driver.connectionCalls.get(driver.connectionCalls.size() - 1), "prepareStatement", update, generatedColumns);
        same(connection, prepared.getConnection(), "JDBC Statement retains wrapped Connection");
        same(prepared, prepared.unwrap(PreparedStatement.class), "JDBC prepared unwrap stays observed");
        same(driver.vendor, prepared.unwrap(VendorHandle.class), "JDBC delegates prepared vendor unwrap");
        check(prepared.toString().equals("ObservePreparedStatement"), "JDBC statement string omits SQL");
        Object value = new Object() {
            @Override public String toString() { throw new AssertionError("JDBC inspected a bound value"); }
        };
        prepared.setObject(1, value);
        call(driver.statementCalls.get(driver.statementCalls.size() - 1), "setObject", 1, value);
        prepared.addBatch();
        check(events.isEmpty(), "JDBC preparation, binding and batching emit no execute event");
        same(driver.batch, prepared.executeBatch(), "JDBC preserves prepared batch result");
        same(driver.largeBatch, prepared.executeLargeBatch(), "JDBC preserves large prepared batch result");
        check(prepared.executeLargeUpdate() == 23L, "JDBC preserves large update count");
        same(driver.result, prepared.executeQuery(), "JDBC preserves ResultSet reference");
        same(driver.result, prepared.getGeneratedKeys(), "JDBC preserves generated keys reference");
        check(events.size() == 4, "JDBC observes prepared execute attempts");
        for (SqlObservation event : events) {
            observation(event, Framework.JDBC, ObservationPoint.JDBC_EXECUTE);
            check(event.fingerprintHash().equals(events.get(0).fingerprintHash()), "JDBC uses saved prepared SQL");
        }

        Statement plain = connection.createStatement(ResultSet.TYPE_FORWARD_ONLY, ResultSet.CONCUR_READ_ONLY);
        int[] generatedIndexes = {1};
        String insert = new String("insert into sample (value) values ('synthetic-direct-value')");
        check(plain.execute(insert, generatedIndexes), "JDBC preserves Statement boolean result");
        call(driver.statementCalls.get(driver.statementCalls.size() - 1), "execute", insert, generatedIndexes);
        check(events.size() == 5, "JDBC observes explicit Statement SQL");
        check(!events.get(4).fingerprintHash().equals(events.get(0).fingerprintHash()), "JDBC fingerprints direct SQL");
        check(!events.get(4).toString().contains("synthetic-direct-value"), "JDBC event omits direct SQL literal");
        plain.addBatch(insert);
        call(driver.statementCalls.get(driver.statementCalls.size() - 1), "addBatch", insert);
        same(driver.batch, plain.executeBatch(), "JDBC preserves plain batch result");
        same(driver.largeBatch, plain.executeLargeBatch(), "JDBC preserves large plain batch result");
        check(events.size() == 5, "JDBC delegates plain batches without SQL inventory");

        String procedure = new String("{ call sample_procedure(?) }");
        CallableStatement callable = connection.prepareCall(procedure, ResultSet.TYPE_FORWARD_ONLY, ResultSet.CONCUR_READ_ONLY);
        call(driver.connectionCalls.get(driver.connectionCalls.size() - 1), "prepareCall", procedure,
                ResultSet.TYPE_FORWARD_ONLY, ResultSet.CONCUR_READ_ONLY);
        callable.registerOutParameter(1, java.sql.Types.INTEGER);
        check(callable.execute(), "JDBC preserves CallableStatement return value");
        same(driver.result, callable.getObject(1), "JDBC preserves CallableStatement output");
        check(events.size() == 6, "JDBC observes CallableStatement attempt");

        connection.commit();
        connection.rollback();
        prepared.close();
        plain.close();
        callable.close();
        connection.close();
        check(driver.connectionCalls.stream().filter(c -> c.named("commit")).count() == 1, "JDBC delegates commit once");
        check(driver.connectionCalls.stream().filter(c -> c.named("rollback")).count() == 1, "JDBC delegates rollback once");
        check(driver.connectionCalls.stream().filter(c -> c.named("close")).count() == 1, "JDBC delegates connection close once");
        check(driver.statementCalls.stream().filter(c -> c.named("close")).count() == 3, "JDBC delegates statement close once each");

        DataSource failing = new ObserveDataSource(driver.dataSource, failingObserver());
        String username = new String("synthetic-user");
        String password = new String("synthetic-pass");
        try (Connection second = failing.getConnection(username, password);
             PreparedStatement secondPrepared = second.prepareStatement(update)) {
            call(driver.dataSourceCalls.get(driver.dataSourceCalls.size() - 1), "getConnection", username, password);
            same(driver.result, secondPrepared.executeQuery(), "JDBC listener failure leaves driver result unchanged");
            driver.failure = new SQLException("synthetic-driver-failure");
            int priorCalls = driver.statementCalls.size();
            expectSqlFailure(driver.failure, secondPrepared::executeQuery);
            check(driver.statementCalls.size() == priorCalls + 1, "JDBC listener and driver failure delegates exactly once");
        }
    }

    private static void jdbcQueryOverloadContract() throws SQLException {
        List<SqlObservation> events = new ArrayList<>();
        SQLException rejected = new SQLException("synthetic-rejected-query");
        PreparedStatement statement = proxy(PreparedStatement.class, (target, method, args) -> {
            if (method.getName().equals("getConnection")) {
                return null;
            }
            call(new Call(method, args), "executeQuery", (String) null);
            check(events.size() == 1 && events.get(0).fingerprintStatus() == FingerprintStatus.UNAVAILABLE,
                    "JDBC observes explicit null SQL before delegating the inherited overload");
            throw rejected;
        });
        Connection delegate = proxy(Connection.class, (target, method, args) -> switch (method.getName()) {
            case "prepareStatement" -> statement;
            case "prepareCall", "createStatement" -> null;
            default -> throw new AssertionError("Unexpected connection call");
        });
        DataSource source = proxy(DataSource.class, (target, method, args) -> delegate);
        Connection connection = new ObserveDataSource(source, new SqlObserver(events::add)).getConnection();
        PreparedStatement prepared = connection.prepareStatement("select 1");
        same(null, prepared.getConnection(), "JDBC retains a null driver connection");
        expectSqlFailure(rejected, () -> prepared.executeQuery(null));
        same(null, connection.prepareCall("call sample()"), "JDBC retains a null callable statement");
        same(null, connection.createStatement(), "JDBC retains a null plain statement");
    }

    private static void jdbcPreparedHotPathContract() throws SQLException {
        JdbcProbe driver = new JdbcProbe();
        List<SqlObservation> events = new ArrayList<>();
        DataSource source = new ObserveDataSource(driver.dataSource, new SqlObserver(events::add));
        Connection first = source.getConnection();
        Connection second = source.getConnection();
        check(first != second, "Each checkout retains a separate observed connection");
        PreparedStatement prepared = first.prepareStatement("select ?");
        PreparedStatement repeat = first.prepareStatement("select ?");
        check(prepared != repeat, "Each preparation retains a separate observed statement");
        same(prepared, prepared.unwrap(PreparedStatement.class), "Prepared statement unwrap retains observation");
        same(first, prepared.getConnection(), "Prepared statement keeps its own connection wrapper");
        int before = driver.statementCalls.size();
        prepared.setInt(2, 17);
        call(driver.statementCalls.get(before), "setInt", 2, 17);
        prepared.setQueryTimeout(3);
        call(driver.statementCalls.get(before + 1), "setQueryTimeout", 3);
        CallableStatement callable = first.prepareCall("{call sample(?)}");
        String parameter = new String("public_parameter");
        callable.setInt(parameter, 4);
        call(driver.statementCalls.get(before + 2), "setInt", parameter, 4);
        callable.setInt((String) null, 5);
        call(driver.statementCalls.get(before + 3), "setInt", null, 5);
        check(driver.statementCalls.size() == before + 4, "Each JDBC setting delegates once");
        driver.failure = new SQLException("synthetic-setting-failure");
        expectSqlFailure(driver.failure, () -> prepared.setInt(1, 2));
        expectSqlFailure(driver.failure, () -> prepared.setQueryTimeout(2));
        check(driver.statementCalls.size() == before + 6, "Failing JDBC settings delegate once each");
        check(events.isEmpty(), "Settings and preparations emit no execution event");
        driver.failure = null;
        driver.beforeQuery = () -> check(events.size() == 1, "Execution is observed before the JDBC delegate");
        same(driver.result, prepared.executeQuery(), "The observed query returns the original JDBC result");
    }

    private static final class MyBatisProbe {
        private final List<SqlObservation> events = new ArrayList<>();
        private final Configuration configuration = new Configuration();
        private final String sql = new String("select value from sample where id = ?");
        private final Object parameter = new Object();
        private final RowBounds bounds = new RowBounds(1, 2);
        private final ResultHandler<Object> resultHandler = context -> { };
        private final ParameterMapping mapping = new ParameterMapping.Builder(configuration, "sample", String.class).build();
        private final ResultMap resultMap = new ResultMap.Builder(configuration, "syntheticResult", Object.class, List.of()).build();
        private final BoundSql boundSql = new BoundSql(configuration, sql, List.of(mapping), parameter);
        private final CacheKey cacheKey = new CacheKey(new Object[] {"synthetic-cache-key", 7});
        private final List<Object> rows = List.of(new Object());
        private final MappedStatement outer = mapped("synthetic.Mapper.outer", SqlCommandType.SELECT);
        private final MappedStatement inner = mapped("synthetic.Mapper.inner", SqlCommandType.SELECT);
        private final MappedStatement update = mapped("synthetic.Mapper.update", SqlCommandType.UPDATE);
        private final Connection connection = proxy(Connection.class, (target, method, args) -> null);
        private final Statement statement = proxy(Statement.class, (target, method, args) -> null);
        private final Integer timeout = 129;
        private final StatementHandler handler;
        private final Executor executor;
        private final SQLException nestedFailure = new SQLException("synthetic-nested-failure");
        private int sqlEvaluations;
        private int prepareCalls;
        private int boundSqlReads;
        private boolean cacheHit;
        private boolean metadataFailure;
        private SQLException failure;

        private MyBatisProbe() {
            boundSql.setAdditionalParameter("sample", parameter);
            MyBatisObserveInterceptor plugin = new MyBatisObserveInterceptor(new SqlObserver(events::add));
            handler = (StatementHandler) plugin.plugin(proxy(StatementHandler.class, this::invokeHandler));
            executor = (Executor) plugin.plugin(proxy(Executor.class, this::invokeExecutor));
        }

        private MappedStatement mapped(String id, SqlCommandType type) {
            return new MappedStatement.Builder(configuration, id, p -> {
                sqlEvaluations++;
                return boundSql;
            }, type).resultMaps(List.of(resultMap)).build();
        }

        private Object invokeHandler(Object target, Method method, Object[] args) throws SQLException {
            if (method.getName().equals("getBoundSql")) {
                boundSqlReads++;
                if (metadataFailure) {
                    throw new AssertionError("synthetic-metadata-failure");
                }
                return boundSql;
            }
            call(new Call(method, args), "prepare", connection, timeout);
            prepareCalls++;
            if (failure != null) {
                throw failure;
            }
            return statement;
        }

        private Object invokeExecutor(Object target, Method method, Object[] args) throws Exception {
            if (method.getName().equals("update")) {
                call(new Call(method, args), "update", update, parameter);
                same(statement, handler.prepare(connection, timeout), "MyBatis update prepare result");
                return 2;
            }
            if (args.length == 6) {
                call(new Call(method, args), "query", inner, parameter, bounds, resultHandler, cacheKey, boundSql);
                same(statement, handler.prepare(connection, timeout), "MyBatis nested prepare result");
                throw nestedFailure;
            }
            call(new Call(method, args), "query", outer, parameter, bounds, resultHandler);
            if (cacheHit) {
                return rows;
            }
            same(statement, handler.prepare(connection, timeout), "MyBatis outer prepare result");
            expectSqlFailure(nestedFailure, () -> executor.query(inner, parameter, bounds, resultHandler, cacheKey, boundSql));
            same(statement, handler.prepare(connection, timeout), "MyBatis resumed outer prepare result");
            FutureTask<Statement> prepare = new FutureTask<>(() -> handler.prepare(connection, timeout));
            Thread worker = new Thread(prepare, "mybatis-observe-contract");
            worker.setDaemon(true);
            worker.start();
            same(statement, prepare.get(5, TimeUnit.SECONDS), "MyBatis prepare on a separate thread");
            return rows;
        }
    }

    public interface VendorHandle { }

    private static final class JdbcProbe {
        private final List<Call> dataSourceCalls = new ArrayList<>();
        private final List<Call> connectionCalls = new ArrayList<>();
        private final List<Call> statementCalls = new ArrayList<>();
        private final VendorHandle vendor = new VendorHandle() { };
        private final ResultSet result = proxy(ResultSet.class, (target, method, args) -> null);
        private final int[] batch = {2, 3};
        private final long[] largeBatch = {4L, 5L};
        private final Connection connection = proxy(Connection.class, this::invokeConnection);
        private final DataSource dataSource = proxy(DataSource.class, (target, method, args) -> {
            dataSourceCalls.add(new Call(method, args));
            return connection;
        });
        private SQLException failure;
        private Runnable beforeQuery = () -> { };

        private Object invokeConnection(Object target, Method method, Object[] args) {
            connectionCalls.add(new Call(method, args));
            return switch (method.getName()) {
                case "createStatement" -> proxy(Statement.class, this::invokeStatement);
                case "prepareStatement" -> proxy(PreparedStatement.class, this::invokeStatement);
                case "prepareCall" -> proxy(CallableStatement.class, this::invokeStatement);
                case "unwrap" -> vendor;
                case "isWrapperFor" -> args[0] == VendorHandle.class;
                case "commit", "rollback", "close" -> null;
                default -> throw new AssertionError("Unexpected connection call");
            };
        }

        private Object invokeStatement(Object target, Method method, Object[] args) throws SQLException {
            statementCalls.add(new Call(method, args));
            return switch (method.getName()) {
                case "getConnection" -> connection;
                case "unwrap" -> vendor;
                case "executeQuery" -> {
                    beforeQuery.run();
                    if (failure != null) {
                        throw failure;
                    }
                    yield result;
                }
                case "executeBatch" -> batch;
                case "executeLargeBatch" -> largeBatch;
                case "executeLargeUpdate" -> 23L;
                case "execute" -> true;
                case "getGeneratedKeys", "getObject" -> result;
                case "setInt", "setQueryTimeout" -> {
                    if (failure != null) throw failure;
                    yield null;
                }
                case "setObject", "registerOutParameter", "addBatch", "close" -> null;
                default -> throw new AssertionError("Unexpected statement call");
            };
        }
    }

    private record Call(Method method, Object[] arguments) {
        private boolean named(String name) { return method.getName().equals(name); }
    }

    private static void call(Call actual, String method, Object... expected) {
        check(actual.named(method), "Expected delegated " + method);
        check(actual.arguments.length == expected.length, "Delegated " + method + " preserves arity");
        for (int i = 0; i < expected.length; i++) {
            if (actual.method.getParameterTypes()[i].isPrimitive()) {
                check(expected[i].equals(actual.arguments[i]), "Delegated " + method + " preserves primitive argument");
            } else {
                same(expected[i], actual.arguments[i], "Delegated " + method + " retains argument reference");
            }
        }
    }

    private static SqlObserver failingObserver() {
        return new SqlObserver(event -> { throw new AssertionError("synthetic-listener-failure"); });
    }

    private static void observation(SqlObservation actual, Framework framework, ObservationPoint point) {
        check(actual.framework() == framework && actual.point() == point, "Observation point and framework");
        check(actual.queryIdHash().matches("[0-9a-f]{64}"), "Metadata has a safe query ID hash");
        check(actual.fingerprintHash().matches("[0-9a-f]{64}"), "Metadata has a safe fingerprint hash");
    }

    private static String hashQueryId(String queryId) throws Exception {
        MessageDigest hash = MessageDigest.getInstance("SHA-256");
        hash.update("query-id".getBytes(StandardCharsets.US_ASCII));
        hash.update((byte) 0);
        return HexFormat.of().formatHex(hash.digest(queryId.getBytes(StandardCharsets.UTF_8)));
    }

    private static <T> T proxy(Class<T> type, InvocationHandler handler) {
        return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[] {type}, handler));
    }

    private static void expectSqlFailure(SQLException expected, SqlOperation action) throws SQLException {
        try {
            action.run();
            throw new AssertionError("Expected original SQLException");
        } catch (SQLException actual) {
            same(expected, actual, "Original SQLException identity");
        }
    }

    @FunctionalInterface
    private interface SqlOperation {
        void run() throws SQLException;
    }

    private static void same(Object expected, Object actual, String message) {
        check(expected == actual, message);
    }

    private static void check(boolean condition, String message) {
        checks++;
        if (!condition) {
            throw new AssertionError(message);
        }
    }
}
