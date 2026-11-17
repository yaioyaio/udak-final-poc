package dev.udak.core;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/** Reusable, dependency-free provider contract checks. */
public final class CompilerContractTest {
    private static int assertions;
    private CompilerContractTest() {}
    private static void check(boolean condition) {
        assertions++;
        if (!condition) throw new AssertionError("Compiler contract assertion failed");
    }
    private static void rejects(Runnable action) {
        assertions++;
        try { action.run(); } catch (IllegalArgumentException | NullPointerException | ArithmeticException | UnsupportedOperationException expected) { return; }
        throw new AssertionError("Compiler contract rejection missing");
    }
    private static QueryDefinition query(String table, List<String> columns, String where, Object value,
                                         String order, int limit, long offset) {
        return new QueryDefinition(table, columns, where, value, order, false, limit, offset);
    }
    public static void verify(String providerName, SqlCompiler compiler) {
        if (providerName == null || compiler == null) throw new IllegalArgumentException("Provider required");
        String injected = "sensitive' OR 1=1 --";
        var inputColumns = new ArrayList<>(List.of("id", "name"));
        var q = query("users", inputColumns, "status", injected, "id", 20, 5);
        inputColumns.clear();
        check(q.columns().size() == 2);
        rejects(() -> q.columns().add("status"));
        for (DbVendor vendor : DbVendor.values()) {
            CompiledQuery result = compiler.compile(q, vendor);
            check(result != null && result.vendor() == vendor);
            check(result.sql() != null && !result.sql().contains(injected));
            check(result.binds().size() == 3 && result.binds().get(0).value().equals(injected));
            check(result.equals(compiler.compile(q, vendor)));
            check(result.sql().contains("ORDER BY id ASC"));
            rejects(() -> result.binds().add(new Bind("extra", null)));
            if (vendor == DbVendor.SQLSERVER || vendor == DbVendor.ORACLE_19) {
                check(result.sql().contains("OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"));
                check(result.binds().equals(List.of(new Bind("filter", injected), new Bind("offset", 5L), new Bind("limit", 20))));
            } else if (vendor == DbVendor.ORACLE_11) {
                check(result.sql().contains("ROWNUM"));
                check(result.binds().equals(List.of(new Bind("filter", injected), new Bind("upperBound", 25L), new Bind("offset", 5L))));
            } else {
                check(result.sql().contains("LIMIT ? OFFSET ?"));
                check(result.binds().equals(List.of(new Bind("filter", injected), new Bind("limit", 20), new Bind("offset", 5L))));
            }
            check(compiler.compile(query("users", List.of("id"), "status", null, "id", 1, 0), vendor).binds().get(0).value() == null);
            check(compiler.compile(query("users", List.of("id"), "status", 1, "id", 1000, 0), vendor) != null);
        }
        rejects(() -> compiler.compile(null, DbVendor.MYSQL));
        rejects(() -> compiler.compile(q, null));
        rejects(() -> compiler.compile(query("invalid", List.of("id"), "status", 1, "id", 1, 0), DbVendor.MYSQL));
        rejects(() -> compiler.compile(query("users", List.of("invalid"), "status", 1, "id", 1, 0), DbVendor.MYSQL));
        rejects(() -> compiler.compile(query("users", List.of("id"), "invalid", 1, "id", 1, 0), DbVendor.MYSQL));
        rejects(() -> compiler.compile(query("users", List.of("id"), "status", 1, "invalid", 1, 0), DbVendor.MYSQL));
        rejects(() -> compiler.compile(query("users;DROP", List.of("id"), "status", 1, "id", 1, 0), DbVendor.MYSQL));
        rejects(() -> compiler.compile(query("users", List.of(), "status", 1, "id", 1, 0), DbVendor.MYSQL));
        for (int limit : new int[]{0, -1, 1001})
            rejects(() -> compiler.compile(query("users", List.of("id"), "status", 1, "id", limit, 0), DbVendor.MYSQL));
        rejects(() -> compiler.compile(query("users", List.of("id"), "status", 1, "id", 1, -1), DbVendor.MYSQL));
        rejects(() -> compiler.compile(query("users", List.of("id"), "status", 1, "id", 1, Long.MAX_VALUE), DbVendor.ORACLE_11));
        rejects(() -> query(null, List.of("id"), "status", 1, "id", 1, 0));
        rejects(() -> query("users", null, "status", 1, "id", 1, 0));
        rejects(() -> query("users", List.of("id"), null, 1, "id", 1, 0));
        rejects(() -> query("users", List.of("id"), "status", 1, null, 1, 0));
        var binds = new ArrayList<>(List.of(new Bind("filter", 1)));
        var output = new CompiledQuery("SELECT ?", binds, DbVendor.MYSQL);
        binds.clear();
        check(output.binds().size() == 1);
        rejects(() -> new CompiledQuery(null, List.of(), DbVendor.MYSQL));
        rejects(() -> new CompiledQuery(" ", List.of(), DbVendor.MYSQL));
        rejects(() -> new CompiledQuery("SELECT 1", null, DbVendor.MYSQL));
        rejects(() -> new CompiledQuery("SELECT 1", List.of(), null));
    }
    public static int assertionCount() { return assertions; }
    public static void main(String[] args) {
        verify("basic", new BasicSqlCompiler(Set.of("users", "id", "name", "status")));
        System.out.println("COMPILER CONTRACT: PASS (assertions=" + assertionCount() + ")");
    }
}
