package dev.udak.testkit;

import dev.udak.api.CrudClient;
import dev.udak.api.TableDefinition;
import dev.udak.core.QueryDefinition;
import dev.udak.jdbc.SpringJdbcExecutor;
import java.sql.Connection;
import java.sql.Statement;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import javax.sql.DataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Owns exactly one randomly named fixture; never operates on pre-existing tables. */
final class DatabaseScenario {
    // Each name corresponds, in order, to one require() below.
    static final List<String> CHECKS = List.of("INSERT_NULL", "READ_NULL", "UPDATE", "INSERT_SECOND",
            "INSERT_THIRD", "PAGE", "BIND", "COMMIT", "ROLLBACK", "DELETE");
    static final class Failure extends Exception {
        final String code, fixture;
        Failure(String code, String fixture) { super(code); this.code = code; this.fixture = fixture; }
    }
    static int run(DataSource ds, DatabaseProfile profile) throws Failure {
        return run(ds, profile, "udak_p2_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12));
    }
    static int run(DataSource ds, DatabaseProfile profile, String table) throws Failure {
        DatabaseProfile.validateFixture(table);
        boolean created = false;
        boolean creationAttempted = false;
        boolean failed = false;
        int checks = 0;
        try {
            try (Connection c = ds.getConnection(); Statement s = c.createStatement()) {
                s.setQueryTimeout(5);
                creationAttempted = true;
                s.executeUpdate(profile.createFixtureSql(table));
                created = true;
            }
            CrudClient crud = new CrudClient(new TableDefinition(table, List.of("id", "name"), "id"),
                    profile.vendor(), new SpringJdbcExecutor(ds, profile.vendor()));
            Map<String, Object> nullRow = new HashMap<>(); nullRow.put("id", 1); nullRow.put("name", null);
            require(crud.insert(nullRow) == 1); checks++;
            require(crud.findById(1, (r, n) -> r.getObject("name") == null).orElse(false)); checks++;
            require(crud.updateById(1, Map.of("name", "group")) == 1); checks++;
            require(crud.insert(Map.of("id", 2, "name", "group")) == 1); checks++;
            require(crud.insert(Map.of("id", 3, "name", "group")) == 1); checks++;
            QueryDefinition page = new QueryDefinition(table, List.of("id", "name"), "name", "group", "id", false, 1, 1);
            require(crud.select(page, (r, n) -> r.getInt("id")).equals(List.of(2))); checks++;
            QueryDefinition injected = new QueryDefinition(table, List.of("id"), "name", "group' OR 1=1 --", "id", false, 10, 0);
            require(crud.select(injected, (r, n) -> r.getInt("id")).isEmpty()); checks++;
            TransactionTemplate tx = new TransactionTemplate(new DataSourceTransactionManager(ds));
            tx.executeWithoutResult(status -> crud.insert(Map.of("id", 4, "name", "commit")));
            require(crud.findById(4, (r, n) -> r.getInt("id")).isPresent()); checks++;
            tx.executeWithoutResult(status -> { crud.insert(Map.of("id", 5, "name", "rollback")); status.setRollbackOnly(); });
            require(crud.findById(5, (r, n) -> r.getInt("id")).isEmpty()); checks++;
            require(crud.deleteById(1) == 1 && crud.findById(1, (r, n) -> r.getInt("id")).isEmpty()); checks++;
        } catch (Exception | AssertionError ex) {
            failed = true;
        } finally {
            if (created) {
                try (Connection c = ds.getConnection(); Statement s = c.createStatement()) {
                    s.setQueryTimeout(5);
                    s.executeUpdate("DROP TABLE " + table);
                } catch (Exception ex) {
                    throw new Failure("CLEANUP_UNCONFIRMED", table);
                }
            }
        }
        if (failed && creationAttempted && !created) throw new Failure("CREATION_UNCONFIRMED", table);
        if (failed) throw new Failure("SCENARIO_FAILED", null);
        if (checks != CHECKS.size()) throw new Failure("CHECK_COUNT_MISMATCH", null);
        return checks;
    }
    private static void require(boolean result) { if (!result) throw new AssertionError(); }
}
