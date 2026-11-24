package dev.udak.pilot;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.sql.DatabaseMetaData;
import java.sql.SQLException;
import java.sql.Types;
import java.util.HexFormat;
import java.util.List;
import java.util.StringJoiner;
import java.util.UUID;
import org.postgresql.ds.PGSimpleDataSource;

/** Collects the three PostgreSQL fixture schemas and replays the selected device query. */
public final class DeviceProfileSchemaImpact {
    private DeviceProfileSchemaImpact() {}

    private static void prepareSchemas(PGSimpleDataSource postgres) throws SQLException {
        try (var connection = postgres.getConnection(); var ddl = connection.createStatement()) {
            ddl.execute("ALTER TABLE public.device ADD COLUMN fixture_note varchar(16)");
            for (String schema : List.of("missing", "unused")) {
                ddl.execute("CREATE SCHEMA " + schema);
                ddl.execute("CREATE TABLE " + schema + ".device (LIKE public.device INCLUDING ALL)");
                ddl.execute("INSERT INTO " + schema + ".device SELECT * FROM public.device");
            }
            ddl.execute("ALTER TABLE missing.device DROP COLUMN customer_id");
            ddl.execute("ALTER TABLE unused.device ALTER COLUMN fixture_note TYPE varchar(32)");
        }
    }

    private static void snapshot(PGSimpleDataSource postgres, String schema, String revision, String profile,
            Path output) throws Exception {
        var columns = new StringJoiner(",");
        try (var connection = postgres.getConnection();
                var rows = connection.getMetaData().getColumns(connection.getCatalog(), schema, "device", "%")) {
            while (rows.next()) {
                String name = rows.getString("COLUMN_NAME");
                int nullable = rows.getInt("NULLABLE");
                if (rows.wasNull() || !schema.equals(rows.getString("TABLE_SCHEM"))
                        || !"device".equals(rows.getString("TABLE_NAME"))
                        || !name.matches("[a-z][a-z0-9_]{0,62}")
                        || (nullable != DatabaseMetaData.columnNoNulls && nullable != DatabaseMetaData.columnNullable)) {
                    throw new IllegalStateException("Unexpected device fixture metadata");
                }
                int jdbcType = rows.getInt("DATA_TYPE");
                String type = switch (jdbcType) {
                    case Types.BIGINT -> "BIGINT";
                    case Types.VARCHAR -> "VARCHAR";
                    case Types.OTHER -> "uuid".equals(rows.getString("TYPE_NAME")) ? "UUID" : null;
                    default -> null;
                };
                int width = jdbcType == Types.VARCHAR ? rows.getInt("COLUMN_SIZE") : 0;
                if (type == null || (jdbcType == Types.VARCHAR && (width <= 0 || width > 32))) {
                    throw new IllegalStateException("Unsupported device fixture column type or width");
                }
                columns.add("{\"table\":\"device\",\"column\":\"" + name + "\",\"type\":\"" + type
                        + "\",\"width\":" + width + ",\"nullable\":" + (nullable == DatabaseMetaData.columnNullable) + "}");
            }
        }
        if (columns.length() == 0) {
            throw new IllegalStateException("Device fixture metadata is empty");
        }
        Files.writeString(output, "{\"schema_version\":1,\"revision\":\"" + revision + "\",\"scope\":\""
                + profile + "\",\"columns\":[" + columns + "]}\n");
    }

    private static void replayMissing(PGSimpleDataSource postgres, String sql) throws SQLException {
        postgres.setCurrentSchema("missing");
        try (var connection = postgres.getConnection(); var statement = connection.createStatement()) {
            try (var result = statement.executeQuery(sql)) {
                throw new IllegalStateException("Expected the selected device query to fail on the missing column");
            } catch (SQLException failure) {
                if (!"42703".equals(failure.getSQLState())) {
                    throw new IllegalStateException("Unexpected SQL state for the selected device query");
                }
            }
        }
    }

    public static void main(String[] args) throws Exception {
        Path work = Path.of(args[0]);
        var input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        var postgres = UpstreamDeviceProfile.postgres(args[1], input.readLine());
        String profile = input.readLine();
        String sql = input.readLine();
        String baseline = input.readLine();
        String missing = input.readLine();
        String unused = input.readLine();
        if ("replay".equals(args[2])) {
            Path schema = work.resolve("MISSING-REPLAY-SCHEMA.json");
            snapshot(postgres, "missing", missing, profile, schema);
            var digest = MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(schema));
            if (!HexFormat.of().formatHex(digest).equals(args[3])) {
                throw new IllegalStateException("Selected replay schema differs from the impact input");
            }
            replayMissing(postgres, sql);
            System.out.println("SQLSTATE=42703");
        } else if ("prepare".equals(args[2])) {
            String query = input.readLine();
            String test = input.readLine();
            UUID tenant = UUID.fromString(input.readLine());
            UUID otherTenant = UUID.fromString(input.readLine());
            var device = UpstreamDeviceProfile.Device.create(tenant, 20);
            UpstreamDeviceProfile.seed(postgres, UpstreamDeviceProfile.Device.create(tenant, 30),
                    UpstreamDeviceProfile.Device.create(otherTenant, 10), device);
            prepareSchemas(postgres);
            snapshot(postgres, "public", baseline, profile, work.resolve("BASELINE-SCHEMA.json"));
            snapshot(postgres, "missing", missing, profile, work.resolve("MISSING-SCHEMA.json"));
            snapshot(postgres, "unused", unused, profile, work.resolve("UNUSED-SCHEMA.json"));
            UpstreamDeviceProfile.capture(postgres, sql, device, true, work.resolve("BASELINE-INVENTORY.json"),
                    baseline, profile, query, test);
            postgres.setCurrentSchema("unused");
            UpstreamDeviceProfile.capture(postgres, sql, device, true, work.resolve("UNUSED-INVENTORY.json"),
                    unused, profile, query, test);
            System.out.println("assertions=2");
        } else {
            throw new IllegalArgumentException("Unknown schema impact mode");
        }
    }
}
