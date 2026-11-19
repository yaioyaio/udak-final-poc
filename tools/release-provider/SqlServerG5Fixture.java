import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import dev.udak.consistency.TransactionGuard;
import java.io.IOException;
import java.io.OutputStream;
import java.io.PrintStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.SQLTimeoutException;
import java.sql.Statement;
import java.util.Arrays;
import java.util.List;
import java.util.Properties;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.logging.LogManager;

/** Fixed-scope checks for a fresh, supervisor-owned SQL Server 2022 instance. */
public final class SqlServerG5Fixture {
    private static final String DB = "udak_g5";
    private static final String CONNECTION_ID =
            "SELECT CONVERT(varchar(36),connection_id) FROM sys.dm_exec_connections WHERE session_id=@@SPID";
    private static final String DB_GUID =
            "SELECT database_guid FROM sys.database_recovery_status WHERE database_id=DB_ID()";
    private static final String DELAY = "WAITFOR DELAY '00:00:10'";
    private final int port;
    private final Properties options = new Properties();

    private SqlServerG5Fixture(String portText, String password) {
        require(portText.matches("[1-9][0-9]{0,4}"));
        port = Integer.parseInt(portText);
        require(port <= 65535 && password.matches("[!-~]{16,96}"));
        options.setProperty("user", "sa");
        options.setProperty("password", password);
        options.setProperty("applicationName", "UDAK_SQLSERVER_G5");
        options.setProperty("encrypt", "true");
        options.setProperty("trustServerCertificate", "true");
        options.setProperty("connectRetryCount", "0");
        options.setProperty("loginTimeout", "4");
        options.setProperty("queryTimeout", "5");
        options.setProperty("cancelQueryTimeout", "2");
        options.setProperty("lockTimeout", "4000");
        options.setProperty("socketTimeout", "12000");
    }

    private static void require(boolean ok) {
        if (!ok) throw new IllegalStateException();
    }

    private static String url(int port, String database) {
        return "jdbc:sqlserver://127.0.0.1:" + port + ";databaseName=" + database;
    }

    private Connection open(String database) throws SQLException {
        return DriverManager.getConnection(url(port, database), options);
    }

    private static String scalar(Connection c, String query) throws SQLException {
        try (Statement s = c.createStatement(); ResultSet rows = s.executeQuery(query)) {
            require(rows.next());
            String result = rows.getString(1);
            require(result != null && !rows.next());
            return result;
        }
    }

    private static void execute(Connection c, String sql) throws SQLException {
        try (Statement statement = c.createStatement()) {
            statement.execute(sql);
        }
    }

    private static void insert(Connection c, int id) throws SQLException {
        try (PreparedStatement s = c.prepareStatement("INSERT INTO dbo.g5_rows(id) VALUES (?)")) {
            s.setInt(1, id);
            require(s.executeUpdate() == 1);
        }
    }

    private static void visible(Connection c, int id, boolean expected) throws SQLException {
        try (PreparedStatement s = c.prepareStatement("SELECT COUNT(*) FROM dbo.g5_rows WHERE id=?")) {
            s.setInt(1, id);
            try (ResultSet rows = s.executeQuery()) {
                require(rows.next() && rows.getInt(1) == (expected ? 1 : 0) && !rows.next());
            }
        }
    }

    private static <T> FutureTask<T> start(Callable<T> task) {
        FutureTask<T> result = new FutureTask<>(task);
        Thread worker = new Thread(result, "sqlserver-g5-worker");
        worker.setDaemon(true);
        worker.start();
        return result;
    }

    private String ready() throws SQLException {
        try (Connection c = open("master")) {
            require("Microsoft SQL Server".equals(c.getMetaData().getDatabaseProductName()));
            require("13.6.2.0".equals(c.getMetaData().getDriverVersion()));
            String version = scalar(c, "SELECT CONVERT(varchar(32),SERVERPROPERTY('ProductVersion'))");
            require(version.matches("16\\.0\\.[0-9]{1,5}\\.[0-9]{1,5}"));
            return version;
        }
    }

    private void createDatabase() throws SQLException {
        try (Connection master = open("master")) {
            // CREATE must succeed before any modifications, including ALTER, are allowed.
            execute(master, "CREATE DATABASE udak_g5");
            execute(master, "ALTER DATABASE udak_g5 SET READ_COMMITTED_SNAPSHOT ON");
        }
        try (Connection c = open(DB)) {
            execute(c, "CREATE TABLE dbo.g5_rows(id int NOT NULL PRIMARY KEY)");
            execute(c, "CREATE TABLE dbo.g5_identity(guid uniqueidentifier NOT NULL PRIMARY KEY)");
            execute(c, "INSERT INTO dbo.g5_identity(guid) " + DB_GUID);
        }
    }

    private static void identity(Connection c) throws SQLException {
        require(DB.equals(scalar(c, "SELECT DB_NAME()")));
        require("1".equals(scalar(c, "SELECT COUNT(*) FROM dbo.g5_identity WHERE guid=(" + DB_GUID + ")")));
    }

    private static boolean disconnected(SQLException e) {
        String state = e.getSQLState();
        return (state != null && state.startsWith("08"))
                || e.getErrorCode() == 596 || e.getErrorCode() == 233;
    }

    private void poolAndPrecommitLoss(Connection observer) throws Exception {
        HikariConfig config = new HikariConfig();
        config.setJdbcUrl(url(port, DB));
        config.setDataSourceProperties(options);
        config.setMaximumPoolSize(1);
        config.setMinimumIdle(0);
        config.setConnectionTimeout(5000);
        config.setValidationTimeout(2000);
        config.setInitializationFailTimeout(-1);
        try (HikariDataSource pool = new HikariDataSource(config)) {
            String original;
            try (Connection first = pool.getConnection()) {
                original = scalar(first, CONNECTION_ID);
                first.setTransactionIsolation(Connection.TRANSACTION_SERIALIZABLE);
                first.setAutoCommit(false);
                insert(first, 101);
            }
            visible(observer, 101, false);
            try (Connection reused = pool.getConnection()) {
                require(original.equals(scalar(reused, CONNECTION_ID)) && reused.getAutoCommit()
                        && reused.getTransactionIsolation() == Connection.TRANSACTION_READ_COMMITTED);
                reused.setAutoCommit(false);
                insert(reused, 102);
                reused.commit();
                visible(observer, 102, true);
                insert(reused, 103);
                visible(reused, 103, true);
                visible(observer, 103, false);
                int victim = Integer.parseInt(scalar(reused, "SELECT @@SPID"));
                require(victim > 0 && victim <= 32767
                        && victim != Integer.parseInt(scalar(observer, "SELECT @@SPID")));
                // The target is the currently borrowed fixture session, identified by its own SPID.
                execute(observer, "KILL " + victim);
                try {
                    reused.commit();
                    throw new IllegalStateException();
                } catch (SQLException loss) {
                    require(disconnected(loss) || reused.isClosed());
                }
            }
            try (Connection replacement = pool.getConnection()) {
                require(!original.equals(scalar(replacement, CONNECTION_ID)) && replacement.getAutoCommit());
                insert(replacement, 104);
            }
            visible(observer, 103, false);
            visible(observer, 104, true);
        }
    }

    private static final class Metrics {
        private final long[] starts = new long[48];
        private int count, active, peak;

        synchronized void begin() throws InterruptedException {
            require(count < starts.length && active < 2);
            if (count > 0) {
                long wait;
                while ((wait = 250_000_000L - (System.nanoTime() - starts[count - 1])) > 0) {
                    TimeUnit.NANOSECONDS.sleep(wait);
                }
            }
            starts[count++] = System.nanoTime();
            peak = Math.max(peak, ++active);
        }

        synchronized void end() { active--; }

        String result() {
            require(count == 48 && peak == 2 && active == 0);
            int maxRolling = 0;
            long minSpacing = Long.MAX_VALUE;
            for (int i = 0, left = 0; i < count; i++) {
                while (starts[i] - starts[left] >= 1_000_000_000L) left++;
                maxRolling = Math.max(maxRolling, i - left + 1);
                if (i > 0) minSpacing = Math.min(minSpacing, starts[i] - starts[i - 1]);
            }
            require(maxRolling <= 4 && minSpacing >= 250_000_000L);
            return count + " " + peak + " " + maxRolling + " " + minSpacing;
        }
    }

    private static void operations(Connection c, int first, Metrics metrics, CyclicBarrier barrier) throws Exception {
        c.setAutoCommit(false);
        for (int i = first; i < 48; i += 2) {
            metrics.begin();
            try {
                int id = 200 + i;
                if (i % 3 != 2) insert(c, id);
                visible(c, id, i % 3 != 2);
                if (i < 2) {
                    barrier.await(5, TimeUnit.SECONDS);
                    visible(c, 201 - i, false);
                    barrier.await(5, TimeUnit.SECONDS);
                }
                if (i % 3 == 1) c.rollback();
                else c.commit();
            } finally {
                metrics.end();
            }
        }
    }

    private String concurrency(Connection observer) throws Exception {
        Metrics metrics = new Metrics();
        CyclicBarrier pair = new CyclicBarrier(2);
        try (Connection first = open(DB); Connection second = open(DB)) {
            FutureTask<Void> worker = start(() -> { operations(first, 0, metrics, pair); return null; });
            operations(second, 1, metrics, pair);
            worker.get(25, TimeUnit.SECONDS);
        }
        for (int i = 0; i < 48; i++) visible(observer, 200 + i, i % 3 == 0);
        return metrics.result();
    }

    private void interruptions(Connection observer) throws Exception {
        try (Connection c = open(DB); Statement s = c.createStatement()) {
            int spid = Integer.parseInt(scalar(c, "SELECT @@SPID"));
            require(spid > 0 && spid <= 32767);
            c.setAutoCommit(false);
            insert(c, 301);
            s.setQueryTimeout(8);
            FutureTask<SQLException> pending = start(() -> {
                try { s.execute(DELAY); return null; }
                catch (SQLException failure) { return failure; }
            });
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(4);
            try (PreparedStatement probe = observer.prepareStatement(
                    "SELECT COUNT(*) FROM sys.dm_exec_requests WHERE session_id=? AND wait_type='WAITFOR'")) {
                probe.setInt(1, spid);
                while (true) {
                    require(System.nanoTime() < deadline && !pending.isDone());
                    try (ResultSet rows = probe.executeQuery()) {
                        require(rows.next());
                        if (rows.getInt(1) == 1) break;
                    }
                    Thread.sleep(100);
                }
            }
            s.cancel();
            SQLException cancelled = pending.get(4, TimeUnit.SECONDS);
            require(cancelled != null && !(cancelled instanceof SQLTimeoutException)
                    && "HY008".equals(cancelled.getSQLState()));
            c.rollback();
            visible(observer, 301, false);
            insert(c, 302);
            s.setQueryTimeout(1);
            try {
                s.execute(DELAY);
                throw new IllegalStateException();
            } catch (SQLTimeoutException expected) {
                c.rollback();
            }
            visible(observer, 302, false);
            insert(c, 303);
            c.commit();
            visible(observer, 303, true);
        }
    }

    /** For one writer, forwards TLS records without inspecting or retaining their contents. */
    private static final class ReplyGate implements AutoCloseable {
        private final Socket upstream = new Socket();
        private final ServerSocket listener;
        private final CountDownLatch request = new CountDownLatch(1);
        private final CountDownLatch suppressed = new CountDownLatch(1);
        private volatile Socket client;
        private volatile boolean armed;
        private volatile boolean ended;
        private final FutureTask<Void> requests;
        private volatile FutureTask<Void> replies;

        ReplyGate(int port) throws IOException {
            InetAddress loopback = InetAddress.getByName("127.0.0.1");
            listener = new ServerSocket(0, 1, loopback);
            try {
                listener.setSoTimeout(5000);
                upstream.connect(new InetSocketAddress(loopback, port), 3000);
                upstream.setSoTimeout(12000);
                requests = start(() -> {
                    try (Socket accepted = listener.accept()) {
                        client = accepted;
                        listener.close();
                        accepted.setSoTimeout(12000);
                        replies = start(() -> { copy(upstream, accepted, true); return null; });
                        copy(accepted, upstream, false);
                    }
                    return null;
                });
            } catch (IOException failure) {
                listener.close();
                upstream.close();
                throw failure;
            }
        }

        private void copy(Socket from, Socket to, boolean reply) {
            byte[] bytes = new byte[8192];
            try {
                var input = from.getInputStream();
                var output = to.getOutputStream();
                int total = 0, length;
                while ((length = input.read(bytes)) != -1) {
                    total += length;
                    require(total <= 1_048_576);
                    if (armed && reply) {
                        if (request.getCount() == 0) suppressed.countDown();
                    } else {
                        if (armed) request.countDown();
                        output.write(bytes, 0, length);
                    }
                }
            } catch (IOException closed) {
                // The proof checks that neither direction ended before the deliberate cut.
            } finally {
                ended = true;
                Arrays.fill(bytes, (byte) 0);
                try { to.shutdownOutput(); } catch (IOException closed) { /* closed */ }
            }
        }

        @Override
        public void close() throws Exception {
            listener.close();
            upstream.close();
            Socket accepted = client;
            if (accepted != null) accepted.close();
            requests.get(2, TimeUnit.SECONDS);
            if (replies != null) replies.get(2, TimeUnit.SECONDS);
        }
    }

    private static void verifyNoRetry() {
        var intent = new TransactionGuard.Intent(false, true, false, TransactionGuard.Propagation.REQUIRED, false,
                TransactionGuard.Isolation.DEFAULT, -1, TransactionGuard.Outcome.UNKNOWN, true);
        var idle = new TransactionGuard.Snapshot(false, false, false, false, false,
                TransactionGuard.Isolation.UNKNOWN, TransactionGuard.Timeout.UNKNOWN, TransactionGuard.Rollback.UNKNOWN);
        var report = TransactionGuard.assess(intent, idle);
        require(report.codes().equals(List.of(TransactionGuard.Code.OUTCOME_UNKNOWN_NO_RETRY)));
        try {
            report.requireAllowed();
            throw new IllegalStateException();
        } catch (TransactionGuard.Violation blocked) {
            require(blocked.report().equals(report));
        }
    }

    private void lostAcknowledgement(Connection observer) throws Exception {
        try (ReplyGate gate = new ReplyGate(port);
             Connection writer = DriverManager.getConnection(url(gate.listener.getLocalPort(), DB), options)) {
            writer.setAutoCommit(false);
            insert(writer, 401);
            visible(writer, 401, true);
            visible(observer, 401, false);
            gate.armed = true;
            FutureTask<SQLException> outcome = start(() -> {
                try { writer.commit(); return null; }
                catch (SQLException loss) { return loss; }
            });
            require(gate.suppressed.await(4, TimeUnit.SECONDS));
            visible(observer, 401, true);
            require(!outcome.isDone() && !gate.ended);
            gate.client.close();
            SQLException loss = outcome.get(4, TimeUnit.SECONDS);
            require(loss != null && disconnected(loss));
            verifyNoRetry();
            visible(observer, 401, true);
        }
    }

    private String functional() throws Exception {
        ready();
        createDatabase();
        try (Connection observer = open(DB)) {
            identity(observer);
            poolAndPrecommitLoss(observer);
            String metrics = concurrency(observer);
            interruptions(observer);
            lostAcknowledgement(observer);
            return metrics;
        }
    }

    private void seed(PrintStream report) throws Exception {
        try (Connection c = open(DB); Connection observer = open(DB)) {
            identity(c);
            c.setAutoCommit(false);
            insert(c, 501);
            c.commit();
            insert(c, 502);
            visible(c, 502, true);
            visible(observer, 501, true);
            visible(observer, 502, false);
            emit(report, "SEED READY");
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(75);
            while (System.nanoTime() < deadline) {
                Thread.sleep(250);
                try {
                    visible(c, 502, true);
                } catch (SQLException loss) {
                    require(disconnected(loss));
                    return;
                }
            }
            throw new IllegalStateException();
        }
    }

    private void recover(boolean graceful) throws SQLException {
        try (Connection c = open(DB); Connection observer = open(DB)) {
            identity(c);
            visible(c, 501, true);
            visible(c, 502, false);
            visible(c, 503, graceful);
            int next = graceful ? 504 : 503;
            c.setAutoCommit(false);
            insert(c, next);
            c.commit();
            visible(observer, next, true);
        }
    }

    private String awaitReady() throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(60);
        while (true) {
            try { return ready(); }
            catch (SQLException starting) {
                if (System.nanoTime() >= deadline) throw starting;
                Thread.sleep(1000);
            }
        }
    }

    private static void emit(PrintStream output, String message) {
        output.println("SQLSERVER_G5 " + message);
        output.flush();
    }

    public static void main(String[] args) {
        PrintStream report = System.out;
        System.setOut(new PrintStream(OutputStream.nullOutputStream()));
        System.setErr(new PrintStream(OutputStream.nullOutputStream()));
        LogManager.getLogManager().reset();
        try {
            require(args.length == 1);
            byte[] bytes = System.in.readNBytes(128);
            try {
                require(bytes.length > 0 && bytes.length < 128);
                String[] fields = new String(bytes, StandardCharsets.US_ASCII).split("\\r?\\n", -1);
                require(fields.length == 3 && fields[2].isEmpty());
                SqlServerG5Fixture fixture = new SqlServerG5Fixture(fields[0], fields[1]);
                try {
                    switch (args[0]) {
                        case "READY" -> emit(report, "READY PASS " + fixture.awaitReady());
                        case "FUNCTIONAL" -> emit(report, "FUNCTIONAL PASS " + fixture.functional());
                        case "SEED" -> { fixture.seed(report); emit(report, "SEED DISCONNECTED"); }
                        case "RECOVER" -> { fixture.recover(false); emit(report, "RECOVER PASS"); }
                        case "GRACEFUL" -> { fixture.recover(true); emit(report, "GRACEFUL PASS"); }
                        default -> throw new IllegalArgumentException();
                    }
                } finally {
                    fixture.options.clear();
                }
            } finally {
                Arrays.fill(bytes, (byte) 0);
            }
        } catch (Throwable failure) {
            emit(report, "FAIL");
            System.exit(1);
        }
    }
}
