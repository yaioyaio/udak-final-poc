package dev.udak.api;

import dev.udak.core.*;
import java.util.*;

/** Standalone contract tests; no database or test framework is required. */
public final class CrudApiContractTest {
    private static final RowMapper<String> MAPPER = (row, index) -> "mapped";
    private static final class Capture implements SqlExecutor {
        CompiledQuery last;
        List<?> rows = List.of();
        public <T> List<T> query(CompiledQuery query, RowMapper<T> mapper) {
            last = query;
            @SuppressWarnings("unchecked") List<T> result = (List<T>) rows;
            return result;
        }
        public int update(CompiledQuery query) { last = query; return 3; }
    }
    private static int assertions;
    private static void check(boolean ok) { assertions++; if (!ok) throw new AssertionError(); }
    private static void fails(Runnable action) {
        assertions++;
        try { action.run(); } catch (IllegalArgumentException | NullPointerException | IllegalStateException | UnsupportedOperationException expected) { return; }
        throw new AssertionError("expected rejection");
    }
    private static void binds(CompiledQuery q, String[] names, Object... values) {
        check(q.binds().size() == names.length);
        for (int i = 0; i < names.length; i++) {
            check(q.binds().get(i).name().equals(names[i]));
            check(Objects.equals(q.binds().get(i).value(), values[i]));
        }
    }
    public static void main(String[] args) {
        var columns = new ArrayList<>(List.of("id", "name", "status"));
        var table = new TableDefinition("users", columns, "id");
        columns.clear();
        check(table.columns().equals(List.of("id", "name", "status")));
        fails(() -> table.columns().add("x"));
        fails(() -> new TableDefinition("bad;sql", List.of("id"), "id"));
        fails(() -> new TableDefinition("users", List.of("id", "id"), "id"));
        fails(() -> new TableDefinition("users", List.of("name"), "id"));
        fails(() -> new TableDefinition("users", List.of("bad-name", "id"), "id"));
        var spyCapture = new Capture();
        int[] calls = {0};
        SqlCompiler spy = (query, vendor) -> {
            calls[0]++;
            return new BasicSqlCompiler(Set.of("users", "id", "name", "status")).compile(query, vendor);
        };
        var injected = new CrudClient(table, DbVendor.POSTGRESQL, spyCapture, spy);
        injected.select(new QueryDefinition("users", List.of("name"), "status", "x", "id", false, 1, 0), MAPPER);
        check(calls[0] == 1);
        fails(() -> injected.select(new QueryDefinition("other", List.of("id"), "id", 1, "id", false, 1, 0), MAPPER));
        fails(() -> injected.select(new QueryDefinition("users", List.of("other"), "id", 1, "id", false, 1, 0), MAPPER));
        fails(() -> injected.select(new QueryDefinition("users", List.of("id"), "other", 1, "id", false, 1, 0), MAPPER));
        fails(() -> injected.select(new QueryDefinition("users", List.of("id"), "id", 1, "other", false, 1, 0), MAPPER));
        check(calls[0] == 1);
        fails(() -> new CrudClient(table, DbVendor.POSTGRESQL, spyCapture, null));
        for (DbVendor vendor : DbVendor.values()) {
            var capture = new Capture();
            var client = new CrudClient(table, vendor, capture);
            var values = new LinkedHashMap<String, Object>();
            values.put("status", null); values.put("name", "x' OR 1=1 --"); values.put("id", 7);
            check(client.insert(values) == 3);
            check(capture.last.sql().equals("INSERT INTO users (id, name, status) VALUES (?, ?, ?)"));
            binds(capture.last, new String[]{"id", "name", "status"}, 7, "x' OR 1=1 --", null);
            values.clear();
            check(capture.last.binds().size() == 3);
            check(!capture.last.sql().contains("OR 1=1"));
            var update = new LinkedHashMap<String, Object>();
            update.put("status", null); update.put("name", "n");
            check(client.updateById(7, update) == 3);
            check(capture.last.sql().equals("UPDATE users SET name = ?, status = ? WHERE id = ?"));
            binds(capture.last, new String[]{"name", "status", "id"}, "n", null, 7);
            check(client.deleteById(7) == 3);
            check(capture.last.sql().equals("DELETE FROM users WHERE id = ?"));
            binds(capture.last, new String[]{"id"}, 7);
            check(client.findById(7, MAPPER).isEmpty());
            check(capture.last.sql().contains("WHERE id = ?"));
            if (vendor == DbVendor.ORACLE_11) binds(capture.last, new String[]{"filter", "upperBound", "offset"}, 7, 2L, 0L);
            else if (vendor == DbVendor.SQLSERVER || vendor == DbVendor.ORACLE_19) binds(capture.last, new String[]{"filter", "offset", "limit"}, 7, 0L, 2);
            else binds(capture.last, new String[]{"filter", "limit", "offset"}, 7, 2, 0L);
            capture.rows = List.of("one"); check(client.findById(7, MAPPER).orElseThrow().equals("one"));
            capture.rows = List.of("one", "two"); fails(() -> client.findById(7, MAPPER));
            capture.rows = new ArrayList<>(List.of("one"));
            var q = new QueryDefinition("users", List.of("name"), "status", null, "id", true, 4, 3);
            var result = client.select(q, MAPPER); ((List<?>) capture.rows).clear();
            check(result.equals(List.of("one"))); fails(() -> result.add("other"));
            if (vendor == DbVendor.ORACLE_11) binds(capture.last, new String[]{"filter", "upperBound", "offset"}, null, 7L, 3L);
            else if (vendor == DbVendor.SQLSERVER || vendor == DbVendor.ORACLE_19) binds(capture.last, new String[]{"filter", "offset", "limit"}, null, 3L, 4);
            else binds(capture.last, new String[]{"filter", "limit", "offset"}, null, 4, 3L);
            capture.rows = Arrays.asList((String) null); fails(() -> client.select(q, MAPPER));
            fails(() -> client.select(new QueryDefinition("other", List.of("id"), "id", 1, "id", false, 1, 0), MAPPER));
            fails(() -> client.select(new QueryDefinition("users", List.of("other"), "id", 1, "id", false, 1, 0), MAPPER));
            fails(() -> client.select(new QueryDefinition("users", List.of("id"), "other", 1, "id", false, 1, 0), MAPPER));
            fails(() -> client.select(new QueryDefinition("users", List.of("id"), "id", 1, "other", false, 1, 0), MAPPER));
            fails(() -> client.insert(Map.of())); fails(() -> client.insert(Map.of("name", "n")));
            fails(() -> client.insert(Collections.singletonMap("id", null)));
            fails(() -> client.insert(Map.of("id", 1, "other", 2)));
            fails(() -> client.updateById(null, Map.of("name", "n")));
            fails(() -> client.updateById(1, Map.of())); fails(() -> client.updateById(1, Map.of("id", 2)));
            fails(() -> client.updateById(1, Map.of("other", 2)));
            fails(() -> client.deleteById(null)); fails(() -> client.findById(null, MAPPER));
        }
        System.out.println("CRUD API CONTRACT: PASS (assertions=" + assertions + ")");
    }
}
