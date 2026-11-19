import dev.udak.consistency.TransactionGuard;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.PrintStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.Arrays;
import java.util.List;
import java.util.Properties;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.logging.LogManager;

public final class FailureFixture {
    private static final String CRASH_TABLE = "udak_failure_crash";
    private static final String ACK_TABLE = "udak_failure_ack";

    private static void require(boolean condition) {
        if (!condition) throw new IllegalStateException();
    }

    private record Database(boolean postgres, int port, Properties options) {
        Connection open(int targetPort) throws SQLException {
            String catalog = postgres ? "postgres" : "udak_fixture";
            String url = "jdbc:" + (postgres ? "postgresql" : "mysql") + "://127.0.0.1:" + targetPort + "/" + catalog;
            Connection connection = DriverManager.getConnection(url, options);
            try {
                DatabaseMetaData meta = connection.getMetaData();
                require(connection.getAutoCommit() && catalog.equals(connection.getCatalog()));
                require((postgres ? "PostgreSQL" : "MySQL").equals(meta.getDatabaseProductName()));
                require(meta.getDatabaseProductVersion().matches(
                        (postgres ? "17\\.11" : "8\\.0\\.46") + "(?:[ -][ -~]{1,180})?"));
                require(meta.getDriverVersion().matches(postgres ? "42\\.7\\.14"
                        : "mysql-connector-j-26\\.10\\.0 \\(Revision: [A-Za-z0-9._-]{1,128}\\)"));
                return connection;
            } catch (SQLException | RuntimeException failure) {
                connection.close();
                throw failure;
            }
        }

        void create(Connection connection, String table) throws SQLException {
            try (Statement ddl = connection.createStatement()) {
                ddl.execute("CREATE TABLE " + table + "(id INTEGER PRIMARY KEY)" + (postgres ? "" : " ENGINE=InnoDB"));
            }
        }
    }

    private static void insert(Connection connection, String table, int id) throws SQLException {
        try (PreparedStatement insert = connection.prepareStatement("INSERT INTO " + table + "(id) VALUES (?)")) {
            insert.setInt(1, id);
            require(insert.executeUpdate() == 1);
        }
    }

    private static int count(Connection connection, String table, int id) throws SQLException {
        try (PreparedStatement select = connection.prepareStatement("SELECT COUNT(*) FROM " + table + " WHERE id=?")) {
            select.setInt(1, id);
            try (ResultSet rows = select.executeQuery()) {
                require(rows.next());
                int value = rows.getInt(1);
                require(!rows.wasNull() && !rows.next());
                return value;
            }
        }
    }

    private static void drop(Connection connection, String table) throws SQLException {
        try (Statement ddl = connection.createStatement()) {
            ddl.execute("DROP TABLE " + table);
        }
    }

    private static void seed(Database db, PrintStream report, String profile) throws Exception {
        try (Connection writer = db.open(db.port()); Connection observer = db.open(db.port())) {
            db.create(writer, CRASH_TABLE);
            writer.setAutoCommit(false);
            insert(writer, CRASH_TABLE, 1);
            writer.commit();
            insert(writer, CRASH_TABLE, 2);
            require(count(writer, CRASH_TABLE, 2) == 1);
            require(count(observer, CRASH_TABLE, 1) == 1 && count(observer, CRASH_TABLE, 2) == 0);
            report.println("FAILURE " + profile + " CRASH_SEED READY");
            report.flush();
            // The supervisor must kill the database while this uncommitted transaction is open.
            Thread.sleep(60_000);
            throw new IllegalStateException();
        }
    }

    private static void verify(Database db) throws SQLException {
        try (Connection writer = db.open(db.port())) {
            require(count(writer, CRASH_TABLE, 1) == 1 && count(writer, CRASH_TABLE, 2) == 0
                    && count(writer, CRASH_TABLE, 3) == 0);
            writer.setAutoCommit(false);
            insert(writer, CRASH_TABLE, 3);
            writer.commit();
        }
        try (Connection observer = db.open(db.port())) {
            require(count(observer, CRASH_TABLE, 1) == 1 && count(observer, CRASH_TABLE, 2) == 0
                    && count(observer, CRASH_TABLE, 3) == 1);
            drop(observer, CRASH_TABLE);
        }
    }

    private static Thread start(String name, Runnable task) {
        Thread thread = new Thread(task, name);
        thread.setDaemon(true);
        thread.start();
        return thread;
    }

    // One JDBC client, one supervisor-assigned loopback DB, bounded traffic. Wire bytes are never inspected or stored.
    private static final class CommitRelay implements AutoCloseable {
        private final ServerSocket listener;
        private final Socket server = new Socket();
        private final Thread requests;
        private volatile Thread responses;
        private volatile Socket client;
        private volatile boolean suppress;
        private final CountDownLatch discarded = new CountDownLatch(1);

        CommitRelay(int databasePort) throws IOException {
            InetAddress loopback = InetAddress.getByName("127.0.0.1");
            listener = new ServerSocket(0, 1, loopback);
            try {
                listener.setSoTimeout(4000);
                server.connect(new InetSocketAddress(loopback, databasePort), 2000);
                server.setSoTimeout(12_000);
                requests = start("fixture-requests", () -> {
                    try (Socket accepted = listener.accept()) {
                        client = accepted;
                        listener.close();
                        accepted.setSoTimeout(12_000);
                        responses = start("fixture-responses", () -> forward(server, accepted, true));
                        forward(accepted, server, false);
                    } catch (IOException closed) {
                        // A failed relay prevents JDBC, response suppression or reconciliation from passing.
                    }
                });
            } catch (IOException failure) {
                listener.close();
                server.close();
                throw failure;
            }
        }

        private void forward(Socket source, Socket target, boolean fromServer) {
            byte[] buffer = new byte[8192];
            try {
                InputStream input = source.getInputStream();
                OutputStream output = target.getOutputStream();
                int total = 0;
                int length;
                while ((length = input.read(buffer)) != -1) {
                    total += length;
                    if (total > 1024 * 1024) throw new IOException();
                    if (fromServer && suppress) discarded.countDown();
                    else output.write(buffer, 0, length);
                }
            } catch (IOException closed) {
                // Closing the sockets ends both pumps.
            } finally {
                Arrays.fill(buffer, (byte) 0);
                try { target.shutdownOutput(); } catch (IOException closed) { /* already disconnected */ }
            }
        }

        @Override
        public void close() throws Exception {
            listener.close();
            server.close();
            Socket accepted = client;
            if (accepted != null) accepted.close();
            requests.join(1000);
            require(!requests.isAlive());
            Thread downstream = responses;
            if (downstream != null) {
                downstream.join(1000);
                require(!downstream.isAlive());
            }
        }
    }

    private static void requireBlockedRetry(SQLException lost) {
        String state = lost.getSQLState();
        require(state != null && (state.startsWith("08") || state.equals("40003") || state.equals("25S03")));
        var retry = new TransactionGuard.Intent(false, true, false, TransactionGuard.Propagation.REQUIRED, false,
                TransactionGuard.Isolation.DEFAULT, -1, TransactionGuard.Outcome.UNKNOWN, true);
        var idle = new TransactionGuard.Snapshot(false, false, false, false, false, TransactionGuard.Isolation.UNKNOWN,
                TransactionGuard.Timeout.UNKNOWN, TransactionGuard.Rollback.UNKNOWN);
        var decision = TransactionGuard.assess(retry, idle);
        require(decision.codes().equals(List.of(TransactionGuard.Code.OUTCOME_UNKNOWN_NO_RETRY)));
        try {
            decision.requireAllowed();
        } catch (TransactionGuard.Violation blocked) {
            require(blocked.report().equals(decision));
            return;
        }
        throw new IllegalStateException();
    }

    private static void lostAck(Database db) throws Exception {
        try (Connection observer = db.open(db.port()); CommitRelay relay = new CommitRelay(db.port());
             Connection writer = db.open(relay.listener.getLocalPort())) {
            db.create(observer, ACK_TABLE);
            writer.setAutoCommit(false);
            insert(writer, ACK_TABLE, 4);
            require(count(writer, ACK_TABLE, 4) == 1 && count(observer, ACK_TABLE, 4) == 0);

            FutureTask<SQLException> commit = new FutureTask<>(() -> {
                try {
                    writer.commit();
                    return null;
                } catch (SQLException failure) {
                    return failure;
                }
            });
            relay.suppress = true;
            start("fixture-commit", commit);
            require(relay.discarded.await(3, TimeUnit.SECONDS));
            int visible = count(observer, ACK_TABLE, 4);
            for (int poll = 0; visible == 0 && poll < 10; poll++) {
                Thread.sleep(50);
                visible = count(observer, ACK_TABLE, 4);
            }
            require(visible == 1 && !commit.isDone());
            relay.client.close();
            SQLException lost = commit.get(3, TimeUnit.SECONDS);
            require(lost != null);
            requireBlockedRetry(lost);

            try (Connection reconciliation = db.open(db.port())) {
                require(count(reconciliation, ACK_TABLE, 4) == 1);
                drop(reconciliation, ACK_TABLE);
            }
        }
    }

    public static void main(String[] args) {
        PrintStream report = System.out;
        PrintStream discard = new PrintStream(OutputStream.nullOutputStream());
        System.setOut(discard);
        System.setErr(discard);
        LogManager.getLogManager().reset();
        try {
            require(args.length == 3 && args[1].matches("[1-9][0-9]{0,4}"));
            int port = Integer.parseInt(args[1]);
            require(port <= 65535);
            boolean postgres = "POSTGRESQL".equals(args[0]);
            require(postgres || "MYSQL".equals(args[0]));
            require(List.of("CRASH_SEED", "CRASH_VERIFY", "LOST_ACK").contains(args[2]));
            byte[] bytes = System.in.readNBytes(50);
            Properties options = new Properties();
            try {
                require(bytes.length == 49 && bytes[48] == '\n');
                String password = new String(bytes, 0, 48, StandardCharsets.US_ASCII);
                require(password.matches("[0-9a-f]{48}"));
                options.setProperty("password", password);
            } finally {
                Arrays.fill(bytes, (byte) 0);
            }
            try {
                options.setProperty("user", "udak_fixture");
                options.setProperty("connectTimeout", postgres ? "2" : "2000");
                options.setProperty("socketTimeout", postgres ? "10" : "10000");
                if (postgres) {
                    options.setProperty("sslmode", "disable");
                    options.setProperty("gssEncMode", "disable");
                    options.setProperty("options", "-c statement_timeout=3000 -c lock_timeout=2000");
                } else {
                    options.setProperty("sslMode", "DISABLED");
                    options.setProperty("logger", "com.mysql.cj.log.NullLogger");
                    options.setProperty("autoReconnect", "false");
                }
                DriverManager.setLoginTimeout(2);
                Database db = new Database(postgres, port, options);
                switch (args[2]) {
                    case "CRASH_SEED" -> seed(db, report, args[0]);
                    case "CRASH_VERIFY" -> verify(db);
                    case "LOST_ACK" -> lostAck(db);
                    default -> throw new IllegalStateException();
                }
            } finally {
                options.clear();
            }
            report.println("FAILURE " + args[0] + " " + args[2] + " PASS");
        } catch (Exception | LinkageError failure) {
            report.println("FAILURE FAIL");
            System.exit(1);
        }
    }
}
