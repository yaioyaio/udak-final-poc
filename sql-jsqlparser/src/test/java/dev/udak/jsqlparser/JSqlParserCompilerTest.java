package dev.udak.jsqlparser;

import dev.udak.core.BasicSqlCompiler;
import dev.udak.core.Bind;
import dev.udak.core.CompiledQuery;
import dev.udak.core.CompilerContractTest;
import dev.udak.core.DbVendor;
import dev.udak.core.QueryDefinition;
import dev.udak.core.SqlCompiler;
import java.util.List;
import java.util.Set;

/** Executable adapter checks; no test framework or external database required. */
public final class JSqlParserCompilerTest {
    private static int assertions;
    private static final QueryDefinition QUERY = new QueryDefinition(
        "users", List.of("id"), "status", "secret", "id", false, 1, 0);
    private static void rejected(SqlCompiler baseline, SqlCompiler delegate) {
        assertions++;
        SqlCompiler compiler = new JSqlParserValidatingCompiler(baseline, delegate);
        try {
            compiler.compile(QUERY, DbVendor.MYSQL);
        } catch (IllegalArgumentException expected) {
            if (expected.getCause() != null || !"SQL compilation or validation failed".equals(expected.getMessage()))
                throw new AssertionError("Unsafe exception");
            return;
        }
        throw new AssertionError("Expected validation rejection");
    }
    public static void main(String[] args) {
        var allowed = Set.of("users", "id", "name", "status");
        CompilerContractTest.verify("jsqlparser", new JSqlParserValidatingCompiler(allowed));
        SqlCompiler baseline = new BasicSqlCompiler(allowed);
        var binds = List.of(new Bind("filter", "secret"), new Bind("limit", 1), new Bind("offset", 0L));
        // Equal baseline and delegate outputs make the parser and SELECT checks decisive.
        for (String sql : List.of("SELECT FROM", "DELETE FROM users", "SELECT id FROM users; SELECT id FROM users")) {
            SqlCompiler stub = (q, v) -> new CompiledQuery(sql, binds, v);
            rejected(stub, stub);
        }
        String validSql = "SELECT id FROM users WHERE status = ? ORDER BY id ASC LIMIT ? OFFSET ?";
        rejected(baseline, (q, v) -> new CompiledQuery(validSql, List.of(), v));
        rejected(baseline, (q, v) -> new CompiledQuery(validSql, binds, DbVendor.POSTGRESQL));
        rejected(baseline, (q, v) -> new CompiledQuery("x".repeat(16_385), binds, v));
        rejected(baseline, (q, v) -> null);
        rejected(baseline, (q, v) -> { throw new IllegalStateException("secret SQL", new RuntimeException("secret")); });
        assertions++;
        CompiledQuery delegated = new JSqlParserValidatingCompiler(baseline, (q, v) -> baseline.compile(q, v))
            .compile(QUERY, DbVendor.MYSQL);
        if (!delegated.equals(baseline.compile(QUERY, DbVendor.MYSQL)))
            throw new AssertionError("Delegated output changed");
        System.out.println("JSQLPARSER CONTRACT: PASS (assertions=" + (CompilerContractTest.assertionCount() + assertions) + ")");
    }
}
