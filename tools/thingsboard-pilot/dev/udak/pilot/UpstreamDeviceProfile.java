package dev.udak.pilot;

import dev.udak.inventory.InventoryCapture;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.jdbc.ObserveDataSource;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.SQLException;
import java.util.UUID;
import org.postgresql.ds.PGSimpleDataSource;

/** Exercises the three pinned Device DAO statements on a disposable PostgreSQL fixture. */
public final class UpstreamDeviceProfile {
    private record Device(UUID tenant, UUID id, UUID profile, UUID customer, long createdTime) {
        private static Device create(UUID tenant, long createdTime) {
            return new Device(tenant, UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), createdTime);
        }
    }

    private UpstreamDeviceProfile() {}

    private static void seed(PGSimpleDataSource postgres, Device... devices) throws SQLException {
        try (var connection = postgres.getConnection();
                var create = connection.createStatement()) {
            create.execute("CREATE TABLE device (id uuid NOT NULL, tenant_id uuid NOT NULL,"
                    + " device_profile_id uuid NOT NULL, customer_id uuid NOT NULL, created_time bigint NOT NULL)");
            try (var insert = connection.prepareStatement(
                    "INSERT INTO device (id, tenant_id, device_profile_id, customer_id, created_time) VALUES (?, ?, ?, ?, ?)")) {
                for (Device device : devices) {
                    insert.setObject(1, device.id());
                    insert.setObject(2, device.tenant());
                    insert.setObject(3, device.profile());
                    insert.setObject(4, device.customer());
                    insert.setLong(5, device.createdTime());
                    if (insert.executeUpdate() != 1) {
                        throw new IllegalStateException("Device fixture insert failed");
                    }
                }
            }
        }
    }

    private static void capture(PGSimpleDataSource postgres, String sql, Device expected, boolean includesCustomer,
            Path output, String revision, String profile, String queryId, String testId) throws Exception {
        var capture = new InventoryCapture();
        var observed = new ObserveDataSource(postgres, new SqlObserver(capture));
        try (var scope = capture.scope(queryId, testId);
                var connection = observed.getConnection();
                var statement = connection.createStatement();
                var results = statement.executeQuery(sql)) {
            var metadata = results.getMetaData();
            if (metadata.getColumnCount() != (includesCustomer ? 4 : 3)
                    || !results.next()
                    || !expected.tenant().equals(results.getObject("tenantid", UUID.class))
                    || !expected.profile().equals(results.getObject("profileid", UUID.class))
                    || !expected.id().equals(results.getObject("id", UUID.class))
                    || includesCustomer && !expected.customer().equals(results.getObject("customerid", UUID.class))
                    || results.next()) {
                throw new IllegalStateException("Device query returned an unexpected projection or row");
            }
        }
        Files.writeString(output, capture.snapshotJsonWithObservedTests(revision, profile));
    }

    public static void main(String[] args) throws Exception {
        Path workspace = Path.of(args[0]);
        var input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        var postgres = new PGSimpleDataSource();
        postgres.setServerNames(new String[]{"127.0.0.1"});
        postgres.setPortNumbers(new int[]{Integer.parseInt(args[1])});
        postgres.setDatabaseName("postgres");
        postgres.setUser("postgres");
        postgres.setPassword(input.readLine());
        postgres.setConnectTimeout(4);
        postgres.setSocketTimeout(5);
        String base = input.readLine();
        String head = input.readLine();
        String profile = input.readLine();
        String queryId = input.readLine();
        String testId = input.readLine();
        UUID firstTenant = UUID.fromString(input.readLine());
        UUID secondTenant = UUID.fromString(input.readLine());
        String baseSql = input.readLine();
        String headSql = input.readLine();
        String controlSql = input.readLine();

        Device first = Device.create(firstTenant, 20);
        Device second = Device.create(secondTenant, 10);
        seed(postgres, Device.create(firstTenant, 30), second, first);
        capture(postgres, baseSql, first, false, workspace.resolve("BASE.json"), base, profile, queryId, testId);
        capture(postgres, headSql, first, true, workspace.resolve("HEAD.json"), head, profile, queryId, testId);
        capture(postgres, controlSql, second, true, workspace.resolve("CONTROL.json"), head, profile, queryId, testId);
        System.out.println("assertions=3");
    }
}
