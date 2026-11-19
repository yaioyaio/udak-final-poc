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

/** Discards the reply to one real commit on a supervisor-owned Oracle Free connection. */
public final class OracleCommitAckFixture {
    private static String stage = "INPUT";

    private static void require(boolean condition) {
        if (!condition) throw new IllegalStateException();
    }

    private static Thread start(String name, Runnable work) {
        Thread thread = new Thread(work, name);
        thread.setDaemon(true);
        thread.start();
        return thread;
    }

    private static final class Relay implements AutoCloseable {
        private final ServerSocket listener;
        private final Socket upstream = new Socket();
        private final Thread requests;
        private volatile Socket downstream;
        private volatile Thread responses;
        private volatile boolean armed;
        private volatile boolean ended;
        private final CountDownLatch commitRequest = new CountDownLatch(1);
        private final CountDownLatch lostReply = new CountDownLatch(1);

        Relay(int dbPort) throws IOException {
            InetAddress loopback = InetAddress.getByName("127.0.0.1");
            listener = new ServerSocket(0, 1, loopback);
            try {
                listener.setSoTimeout(5000);
                upstream.connect(new InetSocketAddress(loopback, dbPort), 3000);
                upstream.setSoTimeout(12_000);
                requests = start("oracle-ack-requests", () -> {
                    try (Socket client = listener.accept()) {
                        downstream = client;
                        listener.close();
                        client.setSoTimeout(12_000);
                        responses = start("oracle-ack-responses", () -> pump(upstream, client, true));
                        pump(client, upstream, false);
                    } catch (IOException disconnected) {
                        ended = true;
                    }
                });
            } catch (IOException failure) {
                listener.close();
                upstream.close();
                throw failure;
            }
        }

        private void pump(Socket source, Socket destination, boolean fromOracle) {
            byte[] bytes = new byte[8192];
            try {
                InputStream input = source.getInputStream();
                OutputStream output = destination.getOutputStream();
                int total = 0;
                int length;
                while ((length = input.read(bytes)) != -1) {
                    total += length;
                    if (total > 1_048_576) throw new IOException();
                    if (armed) {
                        if (fromOracle) {
                            if (commitRequest.getCount() == 0) lostReply.countDown();
                            continue;
                        }
                        commitRequest.countDown();
                    }
                    output.write(bytes, 0, length);
                }
            } catch (IOException disconnected) {
                // An early disconnect invalidates the proof checked before the deliberate cut.
            } finally {
                ended = true;
                Arrays.fill(bytes, (byte) 0);
                try { destination.shutdownOutput(); } catch (IOException closed) { /* already closed */ }
            }
        }

        @Override
        public void close() throws Exception {
            listener.close();
            upstream.close();
            Socket client = downstream;
            if (client != null) client.close();
            requests.join(1000);
            require(!requests.isAlive());
            Thread responseThread = responses;
            if (responseThread != null) {
                responseThread.join(1000);
                require(!responseThread.isAlive());
            }
        }
    }

    private static Connection open(int port, Properties options) throws SQLException {
        String descriptor = "(DESCRIPTION=(RETRY_COUNT=0)(ADDRESS=(PROTOCOL=TCP)(HOST=127.0.0.1)(PORT="
                + port + "))(CONNECT_DATA=(SERVER=DEDICATED)(SERVICE_NAME=FREEPDB1)))";
        return DriverManager.getConnection("jdbc:oracle:thin:@" + descriptor, options);
    }

    private static String scalar(Connection connection, String sql) throws SQLException {
        try (Statement statement = connection.createStatement()) {
            statement.setQueryTimeout(3);
            try (ResultSet rows = statement.executeQuery(sql)) {
                require(rows.next());
                String value = rows.getString(1);
                require(!rows.next());
                return value;
            }
        }
    }

    private static void requireBlockedRetry(SQLException failure) {
        require(failure != null);
        String state = failure.getSQLState();
        // Oracle Thin also reports closed sockets using vendor-specific I/O / end-of-stream codes.
        require((state != null && state.startsWith("08"))
                || failure.getErrorCode() == 17002 || failure.getErrorCode() == 17410);
        var intent = new TransactionGuard.Intent(false, true, false, TransactionGuard.Propagation.REQUIRED, false,
                TransactionGuard.Isolation.DEFAULT, -1, TransactionGuard.Outcome.UNKNOWN, true);
        var idle = new TransactionGuard.Snapshot(false, false, false, false, false,
                TransactionGuard.Isolation.UNKNOWN, TransactionGuard.Timeout.UNKNOWN, TransactionGuard.Rollback.UNKNOWN);
        var decision = TransactionGuard.assess(intent, idle);
        require(decision.codes().equals(List.of(TransactionGuard.Code.OUTCOME_UNKNOWN_NO_RETRY)));
        try {
            decision.requireAllowed();
        } catch (TransactionGuard.Violation blocked) {
            require(decision.equals(blocked.report()));
            return;
        }
        throw new IllegalStateException();
    }

    private static void exercise(int port, String schema, Properties options) throws Exception {
        stage = "METADATA";
        try (Connection observer = open(port, options)) {
            require("Oracle".equals(observer.getMetaData().getDatabaseProductName()));
            require("23.26.4.0.0".equals(observer.getMetaData().getDriverVersion()));
            require("FREEPDB1".equals(scalar(observer, "select sys_context('USERENV','CON_NAME') from dual")));
            require(schema.equals(scalar(observer, "select sys_context('USERENV','CURRENT_SCHEMA') from dual")));
            String version = scalar(observer, "select version_full from product_component_version where product like 'Oracle%'");
            require(version != null && version.matches("23\\.26(\\.[0-9]{1,3}){3}"));
            stage = "CREATE";
            try (Statement ddl = observer.createStatement()) {
                ddl.setQueryTimeout(5);
                ddl.execute("create table G5_ACK (id number(9) constraint G5_ACK_PK primary key)");
            }
            stage = "WRITER";
            try (Relay relay = new Relay(port); Connection writer = open(relay.listener.getLocalPort(), options)) {
                writer.setAutoCommit(false);
                try (PreparedStatement insert = writer.prepareStatement("insert into G5_ACK (id) values (?)")) {
                    insert.setQueryTimeout(3);
                    insert.setInt(1, 1);
                    require(insert.executeUpdate() == 1);
                }
                require("1".equals(scalar(writer, "select id from G5_ACK")));
                require("0".equals(scalar(observer, "select count(*) from G5_ACK")));
                FutureTask<SQLException> result = new FutureTask<>(() -> {
                    try {
                        writer.commit();
                        return null;
                    } catch (SQLException failure) {
                        return failure;
                    }
                });
                stage = "SUPPRESS";
                relay.armed = true;
                start("oracle-ack-commit", result);
                require(relay.lostReply.await(3, TimeUnit.SECONDS));
                stage = "VISIBLE";
                require("1".equals(scalar(observer, "select id from G5_ACK")));
                require(!relay.ended && !result.isDone());
                stage = "CUT";
                relay.downstream.close();
                SQLException lost = result.get(3, TimeUnit.SECONDS);
                stage = "NO_RETRY";
                requireBlockedRetry(lost);
            }
            stage = "RECONCILE";
            require("1".equals(scalar(observer, "select id from G5_ACK")));
        }
    }

    public static void main(String[] args) {
        PrintStream report = System.out;
        System.setOut(new PrintStream(OutputStream.nullOutputStream()));
        System.setErr(new PrintStream(OutputStream.nullOutputStream()));
        LogManager.getLogManager().reset();
        Properties options = new Properties();
        try {
            require(args.length == 0);
            byte[] bytes = System.in.readNBytes(80);
            try {
                require(bytes.length < 80);
                String[] fields = new String(bytes, StandardCharsets.US_ASCII).split("\\r?\\n", -1);
                require(fields.length == 4 && fields[3].isEmpty());
                require(fields[0].matches("[1-9][0-9]{0,4}") && fields[1].matches("UDAKG5[A-F0-9]{24}")
                        && fields[2].matches("ABab12#_[A-Fa-f0-9]{22}"));
                int port = Integer.parseInt(fields[0]);
                require(port <= 65535);
                options.setProperty("user", fields[1]);
                options.setProperty("password", fields[2]);
                options.setProperty("oracle.net.CONNECT_TIMEOUT", "3000");
                options.setProperty("oracle.jdbc.ReadTimeout", "10000");
                DriverManager.setLoginTimeout(5);
                exercise(port, fields[1], options);
            } finally {
                Arrays.fill(bytes, (byte) 0);
            }
            report.println("ORACLE_LOST_ACK PASS");
        } catch (Throwable failure) {
            String type = failure instanceof SQLException ? "SQL" : failure instanceof IOException ? "IO"
                    : failure instanceof java.util.concurrent.TimeoutException ? "TIMEOUT" : "CHECK";
            report.println("ORACLE_LOST_ACK FAIL " + stage + " " + type);
            System.exit(1);
        } finally {
            options.clear();
        }
    }
}
